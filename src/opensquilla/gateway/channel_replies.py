"""Reply payload and directive sanitation helpers for channel dispatch."""

from __future__ import annotations

import re

from opensquilla.channels.types import OutgoingMessage
from opensquilla.engine.types import ErrorEvent

_DIRECTIVE_TAG_RE = re.compile(
    r"\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*"
)
_DIRECTIVE_TAG_BUFFER_LIMIT = 256


def terminal_payload_from_exception(exc: BaseException) -> dict[str, str]:
    is_timeout = isinstance(exc, TimeoutError)
    return {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": "timeout" if is_timeout else "error",
        "error_class": exc.__class__.__name__,
        "error_message": str(exc),
    }


def terminal_payload_from_error_event(event: ErrorEvent) -> dict[str, str | None]:
    code = (event.code or "").lower()
    is_timeout = "timeout" in code or "stream_idle" in code
    return {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": "timeout" if is_timeout else "error",
        "error_class": event.code,
        "error_message": event.message,
    }


def terminal_reply_suffix(message: str) -> str:
    return f"\n\n({message})"


def _strip_inline_directive_tags(content: str) -> str:
    return _DIRECTIVE_TAG_RE.sub("", content)


def sanitize_outgoing_message(message: OutgoingMessage) -> OutgoingMessage:
    cleaned = _strip_inline_directive_tags(message.content)
    if cleaned == message.content:
        return message
    return message.model_copy(update={"content": cleaned})


class DirectiveTagStreamSanitizer:
    """Strip inline reply directives even when a tag is split across chunks."""

    def __init__(self) -> None:
        self._pending = ""

    def clean(self, chunk: str) -> str:
        text = self._pending + chunk
        self._pending = ""
        cleaned = _strip_inline_directive_tags(text)
        start = cleaned.rfind("[[")
        if start == -1:
            return cleaned
        suffix = cleaned[start:]
        if (
            "]]" not in suffix
            and "\n" not in suffix
            and len(suffix) <= _DIRECTIVE_TAG_BUFFER_LIMIT
        ):
            self._pending = suffix
            return cleaned[:start]
        return cleaned

    def flush(self) -> str:
        pending = self._pending
        self._pending = ""
        return _strip_inline_directive_tags(pending)
