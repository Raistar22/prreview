"""
GitHub PR diff parser.

Parses the unified diff (patch) format returned by the GitHub API
into structured hunks, and splits large diffs into manageable chunks
for the AI review engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Regex matching unified diff hunk headers: @@ -old_start,old_count +new_start,new_count @@
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


@dataclass
class DiffHunk:
    """A single hunk within a file's diff."""

    file_path: str
    start_line: int   # Starting line in the new (head) version
    end_line: int     # Ending line in the new (head) version
    content: str      # The raw diff content for this hunk


@dataclass
class FileDiff:
    """Parsed diff for a single file, containing one or more hunks."""

    file_path: str
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def total_content(self) -> str:
        """Concatenated content of all hunks."""
        return "\n".join(h.content for h in self.hunks)


def parse_patch(file_path: str, patch: str) -> FileDiff:
    """
    Parse a GitHub API patch string into a structured FileDiff.

    GitHub's patch format is a standard unified diff without the
    file header lines (--- a/ and +++ b/).

    Args:
        file_path: Path of the file within the repository.
        patch: Raw patch string from the GitHub API.

    Returns:
        FileDiff containing parsed hunks with line number mappings.
    """
    file_diff = FileDiff(file_path=file_path)

    if not patch or not patch.strip():
        return file_diff

    lines = patch.split("\n")
    current_hunk_lines: list[str] = []
    current_start_line: int = 0
    current_line: int = 0

    for line in lines:
        hunk_match = _HUNK_HEADER_RE.match(line)

        if hunk_match:
            # Save previous hunk if exists
            if current_hunk_lines:
                file_diff.hunks.append(
                    DiffHunk(
                        file_path=file_path,
                        start_line=current_start_line,
                        end_line=current_line,
                        content="\n".join(current_hunk_lines),
                    )
                )

            # Start new hunk
            current_start_line = int(hunk_match.group(3))  # new file start
            current_line = current_start_line
            current_hunk_lines = [line]

        elif current_hunk_lines is not None:
            current_hunk_lines.append(line)

            # Track line numbers in the new (head) version
            if line.startswith("+"):
                current_line += 1
            elif line.startswith("-"):
                pass  # Deleted lines don't affect new-file line numbers
            else:
                current_line += 1  # Context line

    # Save last hunk
    if current_hunk_lines:
        file_diff.hunks.append(
            DiffHunk(
                file_path=file_path,
                start_line=current_start_line,
                end_line=current_line,
                content="\n".join(current_hunk_lines),
            )
        )

    logger.debug(
        "patch_parsed",
        file=file_path,
        hunk_count=len(file_diff.hunks),
    )
    return file_diff


def split_diff_into_chunks(file_diff: FileDiff) -> list[DiffHunk]:
    """
    Split a file's diff into chunks that fit within the AI context window.

    Large diffs are broken at hunk boundaries first. If a single hunk
    exceeds the limit, it is split at line boundaries.

    Args:
        file_diff: Parsed file diff to split.

    Returns:
        List of DiffHunk chunks, each within the configured size limit.
    """
    settings = get_settings()
    max_size = settings.MAX_DIFF_CHUNK_SIZE
    chunks: list[DiffHunk] = []

    for hunk in file_diff.hunks:
        if len(hunk.content) <= max_size:
            chunks.append(hunk)
        else:
            # Split oversized hunk at line boundaries
            lines = hunk.content.split("\n")
            current_chunk_lines: list[str] = []
            current_size = 0
            chunk_start_line = hunk.start_line
            current_line_num = hunk.start_line

            for line in lines:
                line_size = len(line) + 1  # +1 for newline

                if current_size + line_size > max_size and current_chunk_lines:
                    chunks.append(
                        DiffHunk(
                            file_path=file_diff.file_path,
                            start_line=chunk_start_line,
                            end_line=current_line_num,
                            content="\n".join(current_chunk_lines),
                        )
                    )
                    current_chunk_lines = []
                    current_size = 0
                    chunk_start_line = current_line_num

                current_chunk_lines.append(line)
                current_size += line_size

                # Track line progression
                if not line.startswith("-"):
                    current_line_num += 1

            # Save remaining lines
            if current_chunk_lines:
                chunks.append(
                    DiffHunk(
                        file_path=file_diff.file_path,
                        start_line=chunk_start_line,
                        end_line=current_line_num,
                        content="\n".join(current_chunk_lines),
                    )
                )

            logger.debug(
                "hunk_split",
                file=file_diff.file_path,
                original_size=len(hunk.content),
                chunk_count=len(chunks),
            )

    return chunks
