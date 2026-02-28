"""
GitHub webhook handler.

Receives webhook events from GitHub, verifies their authenticity,
filters for relevant PR events, and dispatches the review pipeline.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, Response

from app.webhook.security import verify_webhook_signature
from app.github.client import GitHubClient
from app.analyzer.diff_parser import parse_patch, split_diff_into_chunks
from app.analyzer.filters import filter_pr_files
from app.reviewer.engine import ReviewEngine, ReviewResult, ReviewComment
from app.github.reviews import publish_review
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Reference to the review engine — set by main.py during startup
_review_engine: ReviewEngine | None = None

# PR actions we care about
_RELEVANT_ACTIONS = {"opened", "synchronize", "reopened"}


def set_review_engine(engine: ReviewEngine) -> None:
    """Register the review engine for use by the webhook handler."""
    global _review_engine
    _review_engine = engine


@router.post("/webhook")
async def handle_webhook(request: Request) -> Response:
    """
    GitHub webhook endpoint.

    Verifies the signature, checks if the event is a relevant PR event,
    and dispatches the review pipeline in the background.

    Returns 200 immediately to avoid GitHub webhook timeout (10 seconds).
    """
    # ── Verify webhook signature ────────────────────────────────────
    body = await verify_webhook_signature(request)

    # ── Parse event type ────────────────────────────────────────────
    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "unknown")

    logger.info(
        "webhook_received",
        event=event_type,
        delivery_id=delivery_id,
    )

    # ── Ignore non-PR events ───────────────────────────────────────
    if event_type != "pull_request":
        logger.debug("webhook_ignored", event=event_type, reason="not_pull_request")
        return Response(
            content=json.dumps({"status": "ignored", "reason": "not a PR event"}),
            status_code=200,
            media_type="application/json",
        )

    # ── Parse payload ───────────────────────────────────────────────
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("webhook_payload_parse_error", error=str(exc))
        return Response(
            content=json.dumps({"status": "error", "reason": "invalid JSON"}),
            status_code=400,
            media_type="application/json",
        )

    action = payload.get("action", "")

    # ── Filter relevant actions ─────────────────────────────────────
    if action not in _RELEVANT_ACTIONS:
        logger.debug("webhook_action_ignored", action=action)
        return Response(
            content=json.dumps({"status": "ignored", "reason": f"action '{action}' not relevant"}),
            status_code=200,
            media_type="application/json",
        )

    # ── Extract PR metadata ─────────────────────────────────────────
    pr_data = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})
    installation_data = payload.get("installation", {})

    pr_number = pr_data.get("number")
    owner = repo_data.get("owner", {}).get("login")
    repo_name = repo_data.get("name")
    head_sha = pr_data.get("head", {}).get("sha")
    installation_id = installation_data.get("id")

    if not all([pr_number, owner, repo_name, head_sha, installation_id]):
        logger.error(
            "webhook_missing_fields",
            pr_number=pr_number,
            owner=owner,
            repo=repo_name,
        )
        return Response(
            content=json.dumps({"status": "error", "reason": "missing required fields"}),
            status_code=400,
            media_type="application/json",
        )

    logger.info(
        "pr_review_triggered",
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        action=action,
        head_sha=head_sha[:8],
    )

    # ── Dispatch review pipeline in background ──────────────────────
    asyncio.create_task(
        _run_review_pipeline(
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            head_sha=head_sha,
            installation_id=installation_id,
        )
    )

    return Response(
        content=json.dumps({"status": "accepted", "pr": pr_number}),
        status_code=200,
        media_type="application/json",
    )


async def _run_review_pipeline(
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    installation_id: int,
) -> None:
    """
    Execute the full review pipeline:
      1. Fetch PR files
      2. Filter reviewable files
      3. Parse and chunk diffs
      4. Run AI review on each chunk
      5. Aggregate results
      6. Publish review to GitHub

    Runs as a background task so the webhook response isn't delayed.
    """
    if _review_engine is None:
        logger.error("review_engine_not_set")
        return

    try:
        # ── 1. Fetch PR files ───────────────────────────────────────
        client = GitHubClient(installation_id)
        pr_files = await client.get_pr_files(owner, repo, pr_number)

        if not pr_files:
            logger.info("no_files_in_pr", pr_number=pr_number)
            return

        # ── 2. Filter reviewable files ──────────────────────────────
        reviewable_files = filter_pr_files(pr_files)

        if not reviewable_files:
            logger.info("no_reviewable_files", pr_number=pr_number)
            return

        # ── 3. Parse diffs and split into chunks ────────────────────
        all_comments: list[ReviewComment] = []
        all_summaries: list[str] = []
        all_errors: list[str] = []
        reviewed_file_paths: set[str] = set()

        for pr_file in reviewable_files:
            if pr_file.patch is None:
                continue

            file_diff = parse_patch(pr_file.filename, pr_file.patch)
            chunks = split_diff_into_chunks(file_diff)

            reviewed_file_paths.add(pr_file.filename)

            # ── 4. Run AI review on each chunk ──────────────────────
            for chunk in chunks:
                result = await _review_engine.review_diff(
                    chunk.file_path,
                    chunk.content,
                )

                all_comments.extend(result.comments)
                if result.summary:
                    all_summaries.append(result.summary)
                if result.error:
                    all_errors.append(result.error)

        # ── 5. Aggregate results ────────────────────────────────────
        aggregated = ReviewResult(
            summary="\n\n".join(all_summaries) if all_summaries else "No issues found.",
            comments=all_comments,
            error="; ".join(all_errors) if all_errors else None,
        )

        # ── 6. Publish review ───────────────────────────────────────
        success = await publish_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            review_result=aggregated,
            reviewed_files=reviewed_file_paths,
            installation_id=installation_id,
        )

        if success:
            logger.info(
                "review_pipeline_complete",
                pr_number=pr_number,
                files_reviewed=len(reviewed_file_paths),
                comments=len(all_comments),
            )
        else:
            logger.error("review_pipeline_publish_failed", pr_number=pr_number)

    except Exception as exc:
        logger.error(
            "review_pipeline_error",
            pr_number=pr_number,
            error=str(exc),
            exc_info=True,
        )
