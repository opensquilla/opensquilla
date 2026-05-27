"""Paste display helpers for terminal chat input."""

from __future__ import annotations

PASTED_CONTENT_CHAR_THRESHOLD = 800
PASTED_CONTENT_LINE_THRESHOLD = 10


def should_collapse_pasted_content(text: str) -> bool:
    """Return whether text is large enough to show as a paste marker."""
    return (
        len(text) > PASTED_CONTENT_CHAR_THRESHOLD
        or len(text.splitlines()) > PASTED_CONTENT_LINE_THRESHOLD
    )


def pasted_content_summary(text: str, *, index: int | None = None) -> str:
    """Human-readable marker for collapsed pasted content."""
    suffix = f" #{index}" if index is not None else ""
    return f"[Pasted Content{suffix} {len(text)} chars]"


def display_text_for_echo(text: str) -> str:
    """Return the scrollback display text for a submitted user input."""
    if should_collapse_pasted_content(text):
        return pasted_content_summary(text)
    return text
