"""
File filters for the diff analyzer.

Determines which files should be reviewed and which should be skipped.
Skips binary files, lock files, images, generated code, and other
non-reviewable content.
"""

from __future__ import annotations

from app.github.client import PRFile
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── File extensions to SKIP (non-code / generated / binary) ─────────
SKIP_EXTENSIONS: set[str] = {
    # Lock files
    ".lock",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Binary / compiled
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".class", ".jar",
    ".o", ".a", ".dylib",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    # Media
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    # Documents (not source code)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Data / config that shouldn't be reviewed
    ".min.js", ".min.css", ".map",
}

# ── Filenames to SKIP (exact match, case-insensitive) ───────────────
SKIP_FILENAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "composer.lock",
    "gemfile.lock",
    "cargo.lock",
    "go.sum",
    ".ds_store",
    "thumbs.db",
}

# ── Directory prefixes to SKIP ──────────────────────────────────────
SKIP_DIRECTORIES: list[str] = [
    "vendor/",
    "node_modules/",
    ".git/",
    "__pycache__/",
    "dist/",
    "build/",
    ".next/",
    ".nuxt/",
    "coverage/",
]

# ── Extensions to INCLUDE (allowlist — if set, only these are reviewed) ──
# Leave empty to allow all extensions not in SKIP_EXTENSIONS.
ALLOW_EXTENSIONS: set[str] = set()


def should_review_file(pr_file: PRFile) -> bool:
    """
    Determine whether a PR file should be sent for AI code review.

    Applies the following filters in order:
      1. Skip removed files (nothing to review)
      2. Skip files without a patch (binary / too large)
      3. Skip files matching SKIP_FILENAMES
      4. Skip files matching SKIP_EXTENSIONS
      5. Skip files in SKIP_DIRECTORIES
      6. If ALLOW_EXTENSIONS is set, require a match

    Args:
        pr_file: A file from the pull request.

    Returns:
        True if the file should be reviewed, False to skip.
    """
    filename = pr_file.filename
    filename_lower = filename.lower()

    # 1. Removed files have no new code to review
    if pr_file.status == "removed":
        logger.debug("file_skipped", file=filename, reason="removed")
        return False

    # 2. No patch means binary or oversized
    if pr_file.patch is None:
        logger.debug("file_skipped", file=filename, reason="no_patch")
        return False

    # 3. Exact filename matches
    basename = filename.rsplit("/", maxsplit=1)[-1].lower()
    if basename in SKIP_FILENAMES:
        logger.debug("file_skipped", file=filename, reason="skip_filename")
        return False

    # 4. Extension matches
    dot_idx = filename_lower.rfind(".")
    if dot_idx != -1:
        ext = filename_lower[dot_idx:]
        if ext in SKIP_EXTENSIONS:
            logger.debug("file_skipped", file=filename, reason="skip_extension")
            return False

    # 5. Directory prefix matches
    for prefix in SKIP_DIRECTORIES:
        if filename_lower.startswith(prefix):
            logger.debug(
                "file_skipped", file=filename, reason="skip_directory", prefix=prefix
            )
            return False

    # 6. Allowlist (only if non-empty)
    if ALLOW_EXTENSIONS:
        dot_idx = filename_lower.rfind(".")
        if dot_idx == -1:
            logger.debug("file_skipped", file=filename, reason="no_extension")
            return False
        ext = filename_lower[dot_idx:]
        if ext not in ALLOW_EXTENSIONS:
            logger.debug(
                "file_skipped", file=filename, reason="not_in_allowlist"
            )
            return False

    return True


def filter_pr_files(files: list[PRFile]) -> list[PRFile]:
    """
    Filter a list of PR files, keeping only those that should be reviewed.

    Args:
        files: All files from a pull request.

    Returns:
        Filtered list of reviewable files.
    """
    reviewable = [f for f in files if should_review_file(f)]

    logger.info(
        "files_filtered",
        total=len(files),
        reviewable=len(reviewable),
        skipped=len(files) - len(reviewable),
    )
    return reviewable
