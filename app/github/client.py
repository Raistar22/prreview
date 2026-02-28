"""
Async GitHub REST API client.

Provides typed methods for fetching PR details and files.
Handles rate-limiting with automatic retry and structured error logging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.github.auth import get_installation_token
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Retry configuration
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds


@dataclass(frozen=True)
class PRFile:
    """Represents a single file in a pull request."""

    filename: str
    status: str          # "added", "modified", "removed", "renamed"
    patch: str | None    # Unified diff patch (None for binary files)
    additions: int
    deletions: int
    changes: int


@dataclass(frozen=True)
class PRDetails:
    """Core metadata for a pull request."""

    owner: str
    repo: str
    number: int
    title: str
    body: str | None
    head_sha: str
    base_ref: str
    head_ref: str


class GitHubClient:
    """
    Async GitHub REST API client authenticated via installation tokens.

    Usage:
        client = GitHubClient(installation_id=12345)
        details = await client.get_pr_details("owner", "repo", 42)
        files = await client.get_pr_files("owner", "repo", 42)
    """

    def __init__(self, installation_id: int) -> None:
        self._installation_id = installation_id
        self._settings = get_settings()
        self._base_url = self._settings.GITHUB_API_BASE_URL

    async def _get_headers(self) -> dict[str, str]:
        """Build authenticated request headers."""
        token = await get_installation_token(self._installation_id)
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make an authenticated GitHub API request with retry logic.

        Handles 403 (rate limit) and 5xx errors with exponential backoff.
        """
        import asyncio

        headers = await self._get_headers()
        url = f"{self._base_url}{path}"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(
                        method, url, headers=headers, **kwargs
                    )

                # Handle rate limiting
                if response.status_code == 403:
                    remaining = response.headers.get("X-RateLimit-Remaining", "?")
                    logger.warning(
                        "github_rate_limit",
                        remaining=remaining,
                        attempt=attempt,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF_BASE ** attempt)
                        continue

                # Handle server errors
                if response.status_code >= 500:
                    logger.warning(
                        "github_server_error",
                        status=response.status_code,
                        attempt=attempt,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF_BASE ** attempt)
                        continue

                response.raise_for_status()
                return response

            except httpx.ConnectError as exc:
                logger.error("github_connection_error", error=str(exc), attempt=attempt)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_BASE ** attempt)
                    continue
                raise

        # Should not reach here, but satisfy type checker
        raise httpx.HTTPStatusError(
            "Max retries exceeded",
            request=httpx.Request(method, url),
            response=response,  # type: ignore[possibly-undefined]
        )

    async def get_pr_details(
        self, owner: str, repo: str, pr_number: int
    ) -> PRDetails:
        """
        Fetch core metadata for a pull request.

        Args:
            owner: Repository owner (user or org).
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            PRDetails with title, body, refs, and head SHA.
        """
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = await self._request("GET", path)
        data = response.json()

        details = PRDetails(
            owner=owner,
            repo=repo,
            number=pr_number,
            title=data["title"],
            body=data.get("body"),
            head_sha=data["head"]["sha"],
            base_ref=data["base"]["ref"],
            head_ref=data["head"]["ref"],
        )

        logger.info(
            "pr_details_fetched",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            title=details.title,
        )
        return details

    async def get_pr_files(
        self, owner: str, repo: str, pr_number: int
    ) -> list[PRFile]:
        """
        Fetch all changed files in a pull request.

        Handles pagination (GitHub returns max 30 files per page by default,
        up to 100 with per_page parameter).

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of PRFile objects with patches.
        """
        files: list[PRFile] = []
        page = 1

        while True:
            path = (
                f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
                f"?per_page=100&page={page}"
            )
            response = await self._request("GET", path)
            data = response.json()

            if not data:
                break

            for item in data:
                files.append(
                    PRFile(
                        filename=item["filename"],
                        status=item["status"],
                        patch=item.get("patch"),
                        additions=item.get("additions", 0),
                        deletions=item.get("deletions", 0),
                        changes=item.get("changes", 0),
                    )
                )

            # If we got fewer than 100, we've reached the last page
            if len(data) < 100:
                break

            page += 1

        logger.info(
            "pr_files_fetched",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            file_count=len(files),
        )
        return files
