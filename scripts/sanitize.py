"""Shared sanitization for untrusted input before inserting into prompts."""

from __future__ import annotations

import re

_INJECTION_PATTERN = re.compile(
    r"(ignore .* instructions|ignore .* prompt|system prompt|"
    r"you are now|new instructions|disregard|forget .* above)",
    re.IGNORECASE,
)


def sanitize_for_prompt(text: str) -> str:
    """Strip HTML tags, markdown image injection, and prompt injection attempts."""
    # Strip HTML/XML tags
    text = re.sub(r"<[^>]*>", "", text)
    # Strip markdown image/link injection
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Strip prompt injection attempts
    lines = text.splitlines()
    lines = [line for line in lines if not _INJECTION_PATTERN.search(line)]
    return "\n".join(lines)
