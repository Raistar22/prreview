"""
Tests for the diff parser module.
"""

import pytest
from unittest.mock import patch

from app.analyzer.diff_parser import parse_patch, split_diff_into_chunks, FileDiff, DiffHunk


# ── Sample patches ──────────────────────────────────────────────────

SIMPLE_PATCH = """@@ -1,4 +1,5 @@
 import os
+import sys
 
 def main():
     pass"""

MULTI_HUNK_PATCH = """@@ -1,3 +1,4 @@
 import os
+import sys
 import json
@@ -10,3 +11,4 @@
 def foo():
     pass
+    return True"""

ADDITIONS_ONLY_PATCH = """@@ -0,0 +1,3 @@
+def new_function():
+    \"\"\"A brand new function.\"\"\"
+    return 42"""


# ── parse_patch tests ──────────────────────────────────────────────

class TestParsePatch:
    def test_simple_patch(self):
        """Parse a simple patch with one hunk."""
        result = parse_patch("test.py", SIMPLE_PATCH)

        assert result.file_path == "test.py"
        assert len(result.hunks) == 1
        assert result.hunks[0].start_line == 1
        assert result.hunks[0].file_path == "test.py"

    def test_multi_hunk_patch(self):
        """Parse a patch with multiple hunks."""
        result = parse_patch("test.py", MULTI_HUNK_PATCH)

        assert len(result.hunks) == 2
        assert result.hunks[0].start_line == 1
        assert result.hunks[1].start_line == 11

    def test_additions_only(self):
        """Parse a patch for a newly added file."""
        result = parse_patch("new_file.py", ADDITIONS_ONLY_PATCH)

        assert len(result.hunks) == 1
        assert result.hunks[0].start_line == 1
        assert "+def new_function" in result.hunks[0].content

    def test_empty_patch(self):
        """Parse an empty patch."""
        result = parse_patch("empty.py", "")

        assert result.file_path == "empty.py"
        assert len(result.hunks) == 0

    def test_none_patch(self):
        """Parse a None patch."""
        result = parse_patch("none.py", None)

        assert len(result.hunks) == 0

    def test_total_content(self):
        """Verify total_content concatenates hunks."""
        result = parse_patch("test.py", MULTI_HUNK_PATCH)
        total = result.total_content

        assert "@@ -1,3 +1,4 @@" in total
        assert "@@ -10,3 +11,4 @@" in total


# ── split_diff_into_chunks tests ───────────────────────────────────

class TestSplitDiffIntoChunks:
    def test_small_diff_single_chunk(self):
        """A small diff should stay as one chunk."""
        file_diff = parse_patch("small.py", SIMPLE_PATCH)

        with patch("app.analyzer.diff_parser.get_settings") as mock:
            mock.return_value.MAX_DIFF_CHUNK_SIZE = 5000
            chunks = split_diff_into_chunks(file_diff)

        assert len(chunks) == 1

    def test_large_diff_splits(self):
        """A diff exceeding the chunk size should be split."""
        # Create a large patch
        large_lines = ["+" + f"line_{i} = {i}" for i in range(200)]
        large_patch = "@@ -0,0 +1,200 @@\n" + "\n".join(large_lines)
        file_diff = parse_patch("large.py", large_patch)

        with patch("app.analyzer.diff_parser.get_settings") as mock:
            mock.return_value.MAX_DIFF_CHUNK_SIZE = 500
            chunks = split_diff_into_chunks(file_diff)

        assert len(chunks) > 1
        # All chunks should reference the same file
        for chunk in chunks:
            assert chunk.file_path == "large.py"

    def test_multi_hunk_stays_separate(self):
        """Multiple hunks within the limit remain as separate chunks."""
        file_diff = parse_patch("multi.py", MULTI_HUNK_PATCH)

        with patch("app.analyzer.diff_parser.get_settings") as mock:
            mock.return_value.MAX_DIFF_CHUNK_SIZE = 5000
            chunks = split_diff_into_chunks(file_diff)

        assert len(chunks) == 2
