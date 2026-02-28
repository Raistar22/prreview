"""
Pluggable AI code review engine.

Provides an abstract base class and two implementations:
  - LlamaCppReviewEngine: Real inference using a GGUF model via llama-cpp-python (CPU).
  - MockReviewEngine: Returns sample output for testing without a model.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.reviewer.prompt import SYSTEM_PROMPT, build_review_prompt
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Data models ─────────────────────────────────────────────────────

@dataclass
class ReviewComment:
    """A single inline review comment from the AI."""

    file: str
    line: int
    comment: str


@dataclass
class ReviewResult:
    """Complete review output from the AI engine."""

    summary: str
    comments: list[ReviewComment] = field(default_factory=list)
    error: str | None = None


# ── Abstract base class ────────────────────────────────────────────

class ReviewEngine(ABC):
    """
    Abstract base class for AI review engines.

    Subclass this to integrate different LLM backends (local, cloud, etc.)
    The engine must accept a diff and return structured ReviewResult.
    """

    @abstractmethod
    async def review_diff(self, file_path: str, diff_content: str) -> ReviewResult:
        """
        Review a single file diff.

        Args:
            file_path: Path of the file being reviewed.
            diff_content: Unified diff content.

        Returns:
            ReviewResult with summary and inline comments.
        """
        ...

    @abstractmethod
    async def startup(self) -> None:
        """Initialize the engine (load model, warm up, etc.)."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources (unload model, close connections, etc.)."""
        ...


# ── JSON parsing helpers ───────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any] | None:
    """
    Extract a JSON object from model output, handling common LLM quirks
    like markdown code fences or leading/trailing text.
    """
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _parse_review_result(raw_output: str) -> ReviewResult:
    """
    Parse raw model output into a ReviewResult.

    Handles malformed JSON gracefully — if parsing fails, the raw
    output is captured in the error field.
    """
    data = _extract_json(raw_output)

    if data is None:
        logger.warning("ai_output_parse_failed", raw_length=len(raw_output))
        return ReviewResult(
            summary="AI review completed but output could not be parsed.",
            error=f"Unparsable AI output: {raw_output[:500]}",
        )

    summary = data.get("summary", "No summary provided.")
    comments_raw = data.get("comments", [])

    comments = []
    for c in comments_raw:
        if isinstance(c, dict) and "file" in c and "line" in c and "comment" in c:
            try:
                comments.append(
                    ReviewComment(
                        file=str(c["file"]),
                        line=int(c["line"]),
                        comment=str(c["comment"]),
                    )
                )
            except (ValueError, TypeError) as exc:
                logger.warning("comment_parse_error", comment=c, error=str(exc))
                continue

    return ReviewResult(summary=summary, comments=comments)


# ── LlamaCpp implementation ────────────────────────────────────────

class LlamaCppReviewEngine(ReviewEngine):
    """
    AI review engine using llama-cpp-python for CPU-only inference.

    Loads a GGUF model file and runs inference locally.
    """

    def __init__(self) -> None:
        self._model = None
        self._settings = get_settings()

    async def startup(self) -> None:
        """Load the GGUF model into memory."""
        from llama_cpp import Llama

        logger.info(
            "loading_model",
            path=self._settings.AI_MODEL_PATH,
            context_size=self._settings.AI_CONTEXT_SIZE,
            threads=self._settings.AI_THREADS,
        )

        self._model = Llama(
            model_path=self._settings.AI_MODEL_PATH,
            n_ctx=self._settings.AI_CONTEXT_SIZE,
            n_threads=self._settings.AI_THREADS or None,
            n_gpu_layers=0,  # Force CPU-only
            verbose=False,
        )

        logger.info("model_loaded", path=self._settings.AI_MODEL_PATH)

    async def shutdown(self) -> None:
        """Release the model from memory."""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("model_unloaded")

    async def review_diff(self, file_path: str, diff_content: str) -> ReviewResult:
        """
        Run the AI model on a single file diff.

        The model is called synchronously (CPU inference) but wrapped
        in an async method for API consistency.
        """
        if self._model is None:
            return ReviewResult(
                summary="Review engine not initialized.",
                error="Model not loaded. Call startup() first.",
            )

        user_prompt = build_review_prompt(file_path, diff_content)

        try:
            import asyncio

            # Run synchronous inference in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._model.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=self._settings.AI_MAX_TOKENS,
                    temperature=0.1,  # Low temperature for deterministic reviews
                    top_p=0.9,
                ),
            )

            raw_output = result["choices"][0]["message"]["content"]
            logger.debug(
                "inference_complete",
                file=file_path,
                output_length=len(raw_output),
            )
            return _parse_review_result(raw_output)

        except Exception as exc:
            logger.error("inference_failed", file=file_path, error=str(exc))
            return ReviewResult(
                summary=f"AI review failed for {file_path}.",
                error=str(exc),
            )


# ── Mock implementation (for testing) ──────────────────────────────

class MockReviewEngine(ReviewEngine):
    """
    Mock review engine that returns sample output.
    Useful for testing the pipeline without a real model.
    """

    async def startup(self) -> None:
        logger.info("mock_engine_started")

    async def shutdown(self) -> None:
        logger.info("mock_engine_stopped")

    async def review_diff(self, file_path: str, diff_content: str) -> ReviewResult:
        """Return a sample review for any diff."""
        logger.info("mock_review", file=file_path)

        # Generate a realistic-looking mock review
        return ReviewResult(
            summary=(
                f"Reviewed changes in `{file_path}`. "
                "The code looks reasonable with minor suggestions."
            ),
            comments=[
                ReviewComment(
                    file=file_path,
                    line=1,
                    comment=(
                        "[Mock Review] Consider adding type hints to improve "
                        "code readability and IDE support."
                    ),
                ),
            ],
        )


def create_engine() -> ReviewEngine:
    """
    Factory function that creates the appropriate review engine
    based on configuration.

    Returns:
        MockReviewEngine if USE_MOCK_ENGINE is true, else LlamaCppReviewEngine.
    """
    settings = get_settings()

    if settings.USE_MOCK_ENGINE:
        logger.info("using_mock_engine")
        return MockReviewEngine()

    logger.info("using_llamacpp_engine")
    return LlamaCppReviewEngine()
