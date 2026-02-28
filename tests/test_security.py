"""
Tests for webhook signature verification.
"""

import hashlib
import hmac

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch, MagicMock

from app.webhook.security import verify_webhook_signature


def _make_signature(body: bytes, secret: str) -> str:
    """Helper to compute a valid HMAC-SHA256 signature."""
    return (
        "sha256="
        + hmac.new(
            key=secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )


def _make_mock_request(body: bytes, signature: str | None = None) -> MagicMock:
    """Create a mock FastAPI Request with given body and signature header."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = {}
    if signature is not None:
        request.headers["X-Hub-Signature-256"] = signature
    return request


@pytest.mark.asyncio
async def test_valid_signature():
    """Verify that a correctly signed payload passes verification."""
    secret = "test-secret-123"
    body = b'{"action": "opened"}'
    signature = _make_signature(body, secret)

    request = _make_mock_request(body, signature)

    with patch("app.webhook.security.get_settings") as mock_settings:
        mock_settings.return_value.GITHUB_WEBHOOK_SECRET = secret
        result = await verify_webhook_signature(request)

    assert result == body


@pytest.mark.asyncio
async def test_missing_signature():
    """Verify that a request without a signature is rejected."""
    body = b'{"action": "opened"}'
    request = _make_mock_request(body, signature=None)

    with patch("app.webhook.security.get_settings") as mock_settings:
        mock_settings.return_value.GITHUB_WEBHOOK_SECRET = "any-secret"
        with pytest.raises(HTTPException) as exc_info:
            await verify_webhook_signature(request)

    assert exc_info.value.status_code == 403
    assert "Missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_invalid_signature():
    """Verify that an incorrect signature is rejected."""
    secret = "correct-secret"
    body = b'{"action": "opened"}'
    wrong_signature = _make_signature(body, "wrong-secret")

    request = _make_mock_request(body, wrong_signature)

    with patch("app.webhook.security.get_settings") as mock_settings:
        mock_settings.return_value.GITHUB_WEBHOOK_SECRET = secret
        with pytest.raises(HTTPException) as exc_info:
            await verify_webhook_signature(request)

    assert exc_info.value.status_code == 403
    assert "Invalid" in exc_info.value.detail


@pytest.mark.asyncio
async def test_tampered_body():
    """Verify that a tampered body fails verification."""
    secret = "test-secret"
    original_body = b'{"action": "opened"}'
    tampered_body = b'{"action": "closed"}'
    signature = _make_signature(original_body, secret)

    request = _make_mock_request(tampered_body, signature)

    with patch("app.webhook.security.get_settings") as mock_settings:
        mock_settings.return_value.GITHUB_WEBHOOK_SECRET = secret
        with pytest.raises(HTTPException) as exc_info:
            await verify_webhook_signature(request)

    assert exc_info.value.status_code == 403
