"""
Application configuration loaded from environment variables.

Uses pydantic-settings for type-safe, validated configuration.
All secrets are loaded from environment variables — never hardcoded.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the PR Review application.
    Values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ── GitHub App ────────────────────────────────────────────────────
    GITHUB_APP_ID: int
    GITHUB_PRIVATE_KEY_PATH: str
    GITHUB_WEBHOOK_SECRET: str

    # ── AI Model ──────────────────────────────────────────────────────
    AI_MODEL_PATH: str = "/app/models/model.gguf"
    AI_MAX_TOKENS: int = 1024
    AI_CONTEXT_SIZE: int = 2048
    AI_THREADS: int = 0  # 0 = auto-detect

    # ── Application ──────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    USE_MOCK_ENGINE: bool = False
    MAX_DIFF_CHUNK_SIZE: int = 3000

    # ── GitHub API ───────────────────────────────────────────────────
    GITHUB_API_BASE_URL: str = "https://api.github.com"


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached Settings instance. The cache ensures
    environment variables are read only once per process.
    """
    return Settings()
