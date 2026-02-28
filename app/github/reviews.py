"""
GitHub PR review publisher.

Converts AI review results into GitHub-compatible review comments
and posts them to the pull request via the GitHub API.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.github.auth import get_installation_token
from app.config import get_settings
from app.reviewer.engine import ReviewResult, ReviewComment
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GitHubReviewComment:
    """A review comment formatted for the GitHub API."""

    path: str
    line: int       # Line number in the diff (new file side)
    body: str


def _format_comment_body(comment: ReviewComment) -> str:
    """
    Format an AI review comment into a readable GitHub comment body.
    Adds the bot attribution header.
    """
    return (
        f"🤖 **AI Review**\n\n"
        f"{comment.comment}"
    )


def _format_summary(result: ReviewResult, file_count: int) -> str:
    """
    Format the overall review summary for the PR review body.

    Args:
        result: Aggregated review result.
        file_count: Number of files reviewed.

    Returns:
        Markdown-formatted summary string.
    """
    summary_parts = [
        "## 🤖 AI Code Review Summary\n",
        f"**Files reviewed:** {file_count}\n",
        f"**Inline comments:** {len(result.comments)}\n",
        "---\n",
        result.summary,
    ]

    if result.error:
        summary_parts.append(
            f"\n\n> ⚠️ **Note:** Some files could not be reviewed: {result.error}"
        )

    return "\n".join(summary_parts)


def map_comments_to_review(
    comments: list[ReviewComment],
    valid_files: set[str],
) -> list[GitHubReviewComment]:
    """
    Convert AI comments into GitHub review comments, filtering out
    any that reference invalid files or lines.

    Args:
        comments: AI-generated review comments.
        valid_files: Set of filenames that exist in the PR diff.

    Returns:
        List of valid GitHubReviewComment objects.
    """
    mapped: list[GitHubReviewComment] = []

    for comment in comments:
        # Validate file exists in the PR
        if comment.file not in valid_files:
            logger.warning(
                "comment_file_not_in_pr",
                file=comment.file,
                valid_files=list(valid_files)[:5],
            )
            continue

        # Validate line number is positive
        if comment.line < 1:
            logger.warning(
                "comment_invalid_line",
                file=comment.file,
                line=comment.line,
            )
            continue

        mapped.append(
            GitHubReviewComment(
                path=comment.file,
                line=comment.line,
                body=_format_comment_body(comment),
            )
        )

    logger.info(
        "comments_mapped",
        total=len(comments),
        valid=len(mapped),
        dropped=len(comments) - len(mapped),
    )
    return mapped


async def publish_review(
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    review_result: ReviewResult,
    reviewed_files: set[str],
    installation_id: int,
) -> bool:
    """
    Post a complete code review to a GitHub pull request.

    Creates a review with:
      - Inline comments mapped to specific files and lines
      - A summary body with overall assessment

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
        head_sha: The HEAD commit SHA of the PR.
        review_result: Aggregated AI review output.
        reviewed_files: Set of file paths that were reviewed.
        installation_id: GitHub App installation ID.

    Returns:
        True if the review was posted successfully, False otherwise.
    """
    settings = get_settings()
    token = await get_installation_token(installation_id)

    # Map AI comments to GitHub format
    github_comments = map_comments_to_review(
        review_result.comments,
        reviewed_files,
    )

    # Build the review body (summary)
    review_body = _format_summary(review_result, len(reviewed_files))

    # Build the API payload
    payload: dict = {
        "body": review_body,
        "event": "COMMENT",  # COMMENT = neutral, doesn't approve or request changes
        "commit_id": head_sha,
    }

    # Add inline comments if any valid ones exist
    if github_comments:
        payload["comments"] = [
            {
                "path": c.path,
                "line": c.line,
                "body": c.body,
            }
            for c in github_comments
        ]

    # Post the review
    url = (
        f"{settings.GITHUB_API_BASE_URL}"
        f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        if response.status_code == 422:
            # Validation error — likely invalid line numbers. Retry without
            # inline comments to at least post the summary.
            logger.warning(
                "review_validation_error",
                status=response.status_code,
                body=response.text[:500],
            )

            payload.pop("comments", None)
            payload["body"] += (
                "\n\n> ⚠️ Some inline comments could not be posted "
                "due to line mapping issues."
            )

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )

        response.raise_for_status()

        logger.info(
            "review_published",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            comments=len(github_comments),
        )
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "review_publish_failed",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            status=exc.response.status_code,
            body=exc.response.text[:500],
        )
        return False

    except Exception as exc:
        logger.error(
            "review_publish_error",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            error=str(exc),
        )
        return False
