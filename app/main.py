"""
FastAPI application entry point.

Configures the application, registers routes, and manages the
AI review engine lifecycle via lifespan events.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.utils.logger import setup_logging, get_logger
from app.webhook.handler import router as webhook_router, set_review_engine
from app.reviewer.engine import create_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup: Initialize logging and load the AI review engine.
    Shutdown: Clean up the review engine.
    """
    # ── Startup ─────────────────────────────────────────────────────
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    logger.info(
        "app_starting",
        app_id=settings.GITHUB_APP_ID,
        mock_engine=settings.USE_MOCK_ENGINE,
        log_level=settings.LOG_LEVEL,
    )

    # Create and initialize the review engine
    engine = create_engine()
    await engine.startup()
    set_review_engine(engine)

    logger.info("app_ready")

    yield

    # ── Shutdown ────────────────────────────────────────────────────
    logger.info("app_shutting_down")
    await engine.shutdown()
    logger.info("app_stopped")


# ── Create FastAPI application ──────────────────────────────────────

app = FastAPI(
    title="PR Review Bot",
    description="AI-powered GitHub Pull Request code reviewer",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Register routes ─────────────────────────────────────────────────

app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring and load balancer probes.
    Returns 200 with basic status info.
    """
    return {
        "status": "healthy",
        "service": "pr-review-bot",
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    """Root endpoint with basic API info."""
    return {
        "service": "PR Review Bot",
        "docs": "/docs",
        "health": "/health",
        "webhook": "/webhook",
    }
