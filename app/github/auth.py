"""
GitHub App authentication module.

Handles:
  1. Generating a short-lived JWT signed with the App's private key.
  2. Exchanging the JWT for an installation access token.
  3. Caching tokens until near-expiry to minimise API calls.
"""

import time
from pathlib import Path
from datetime import datetime, timezone

import jwt
import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Cache: installation_id -> (token, expiry_timestamp)
_token_cache: dict[int, tuple[str, float]] = {}

# Safety margin before token expiry (seconds)
_EXPIRY_BUFFER = 60


def _load_private_key() -> str:
    """
    Read the PEM-formatted private key from disk.
    Raises FileNotFoundError with clear message if missing.
    """
    settings = get_settings()
    pem_path = Path(settings.GITHUB_PRIVATE_KEY_PATH)

    if not pem_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at: {pem_path}. "
            "Ensure GITHUB_PRIVATE_KEY_PATH points to a valid .pem file."
        )

    return pem_path.read_text(encoding="utf-8")


def generate_jwt() -> str:
    """
    Generate a short-lived JWT (10 minutes) for GitHub App authentication.

    The JWT is signed with RS256 using the App's private key and contains:
      - iss: GitHub App ID
      - iat: issued-at time (60 seconds in the past to account for clock drift)
      - exp: expiration time (10 minutes from iat)

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    private_key = _load_private_key()

    now = int(time.time())
    payload = {
        "iss": settings.GITHUB_APP_ID,
        "iat": now - 60,      # 60s clock drift allowance
        "exp": now + (10 * 60),  # 10 minute max lifetime
    }

    encoded = jwt.encode(payload, private_key, algorithm="RS256")
    logger.debug("jwt_generated", app_id=settings.GITHUB_APP_ID)
    return encoded


async def get_installation_token(installation_id: int) -> str:
    """
    Obtain an installation access token for a specific GitHub App installation.

    Tokens are cached until 60 seconds before expiry to avoid unnecessary
    API calls while ensuring we never use an expired token.

    Args:
        installation_id: The GitHub App installation ID (from the webhook payload).

    Returns:
        Installation access token string.

    Raises:
        httpx.HTTPStatusError: If the GitHub API rejects the request.
    """
    # Return cached token if still valid
    if installation_id in _token_cache:
        token, expiry = _token_cache[installation_id]
        if time.time() < (expiry - _EXPIRY_BUFFER):
            logger.debug("token_cache_hit", installation_id=installation_id)
            return token

    # Generate a fresh JWT and exchange it for an installation token
    app_jwt = generate_jwt()
    settings = get_settings()

    url = (
        f"{settings.GITHUB_API_BASE_URL}"
        f"/app/installations/{installation_id}/access_tokens"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()

    data = response.json()
    token = data["token"]

    # Parse expiry and cache
    expires_at = data.get("expires_at", "")
    if expires_at:
        expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        expiry_ts = expiry_dt.timestamp()
    else:
        # Fallback: tokens typically last 1 hour
        expiry_ts = time.time() + 3600

    _token_cache[installation_id] = (token, expiry_ts)

    logger.info(
        "installation_token_obtained",
        installation_id=installation_id,
        expires_at=expires_at,
    )
    return token
