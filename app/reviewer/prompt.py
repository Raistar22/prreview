"""
AI code review prompt templates.

Contains the system prompt and user prompt builders that enforce
structured JSON output, actionable feedback, and no hallucination.
"""

SYSTEM_PROMPT = """You are an expert code reviewer. You review ONLY the provided code diff.

## Rules — you MUST follow all of these:
1. Review ONLY the lines shown in the diff. Do NOT reference code outside the diff.
2. Every comment MUST be specific and actionable. Never give vague advice like "consider improving this".
3. Do NOT suggest rewriting entire files or functions. Focus on the changed lines.
4. Do NOT hallucinate context. If you are unsure about something, say so.
5. Focus on these areas (in priority order):
   a. Bugs — logic errors, off-by-one, null/None handling, race conditions
   b. Security — injection, secrets exposure, unsafe deserialization, path traversal
   c. Performance — unnecessary allocations, O(n²) where O(n) is possible, blocking calls
   d. Readability — unclear naming, missing type hints, overly complex expressions
   e. Best practices — error handling, resource cleanup, idiomatic patterns

## Output format — you MUST respond with valid JSON and nothing else:

{
  "summary": "A 1-3 sentence overall assessment of this diff.",
  "comments": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "comment": "Specific actionable feedback for this line."
    }
  ]
}

If the diff looks correct and you have no comments, return:
{
  "summary": "The changes look good. No issues found.",
  "comments": []
}

IMPORTANT: Return ONLY the JSON object. No markdown, no explanation, no preamble."""


def build_review_prompt(file_path: str, diff_content: str) -> str:
    """
    Build the user prompt for the AI model, including the file path
    and the diff content to review.

    Args:
        file_path: Path of the file being reviewed.
        diff_content: The unified diff content to review.

    Returns:
        Formatted user prompt string.
    """
    return f"""Review the following code diff for file: `{file_path}`

```diff
{diff_content}
```

Provide your review as a JSON object following the output format specified in your instructions."""


def build_multi_file_prompt(file_diffs: list[tuple[str, str]]) -> str:
    """
    Build a single prompt for reviewing multiple file diffs at once.
    Used when the total diff is small enough to fit in one context window.

    Args:
        file_diffs: List of (file_path, diff_content) tuples.

    Returns:
        Formatted user prompt string.
    """
    sections = []
    for file_path, diff_content in file_diffs:
        sections.append(
            f"### File: `{file_path}`\n\n```diff\n{diff_content}\n```"
        )

    all_diffs = "\n\n---\n\n".join(sections)

    return f"""Review the following code diffs from a pull request:

{all_diffs}

Provide your review as a JSON object following the output format specified in your instructions.
Each comment must include the correct `file` path and `line` number."""
