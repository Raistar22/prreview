"""
Webhook signature verification.

Validates the HMAC-SHA256 signature sent by GitHub in the
X-Hub-Signature-256 header to ensure payloads are authentic.
"""

import hashlib
import hmac

from fastapi import HTTPException, Request

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def verify_webhook_signature(request: Request) -> bytes:
    """
    Verify the GitHub webhook HMAC-SHA256 signature.

    This MUST be called before processing any webhook payload.
    The raw body is returned so it can be parsed after verification.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The raw request body bytes (verified).

    Raises:
        HTTPException(403): If the signature is missing or invalid.
    """
    settings = get_settings()

    # ── Extract signature header ────────────────────────────────────
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("webhook_signature_missing")
        raise HTTPException(
            status_code=403,
            detail="Missing X-Hub-Signature-256 header",
        )

    # ── Read raw body ───────────────────────────────────────────────
    body = await request.body()

    # ── Compute expected signature ──────────────────────────────────
    expected_signature = (
        "sha256="
        + hmac.new(
            key=settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    # ── Constant-time comparison ────────────────────────────────────
    if not hmac.compare_digest(expected_signature, signature_header):
        logger.warning(
            "webhook_signature_invalid",
            received=signature_header[:20] + "...",
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid webhook signature",
        )

    logger.debug("webhook_signature_verified")
    return body
