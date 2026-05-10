"""Human-readable terminal replies for task and stream terminal events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opensquilla.session.models import AgentTaskStatus


def build_terminal_reply(
    record_or_payload: Any,
    *,
    surface: str | None = None,
    locale: str | None = None,
) -> str:
    """Return an additive human-readable message for a terminal payload.

    The returned string is intended for user-facing terminal surfaces. Existing
    technical fields such as ``terminal_reason`` and ``error_message`` remain
    the source of machine/debug detail; this helper deliberately avoids exposing
    raw timeout internals in the normal reply text.
    """

    del surface, locale  # Reserved for future surface/locale-specific phrasing.

    existing = _read_value(record_or_payload, "terminal_message")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    status = _normalize(_read_value(record_or_payload, "status"))
    reason = _normalize(_read_value(record_or_payload, "terminal_reason"))
    error_class = _normalize(_read_value(record_or_payload, "error_class"))
    error_message = _normalize(_read_value(record_or_payload, "error_message"))

    if (
        status == AgentTaskStatus.TIMEOUT.value
        or reason == "timeout"
        or "timeouterror" in error_class
        or "stream idle" in error_message
    ):
        return "The task timed out before it could finish."
    if status == AgentTaskStatus.CANCELLED.value or reason.startswith("cancelled"):
        return "The task was cancelled before it finished."
    if status == AgentTaskStatus.ABANDONED.value or reason == "shutdown_timeout":
        return "The task stopped before it could finish."
    if status == AgentTaskStatus.FAILED.value or reason in {"error", "tool_error"}:
        return "The task failed before it could finish."
    if status == AgentTaskStatus.SUCCEEDED.value or reason in {"completed", "done"}:
        return "The task completed."
    return "The task ended before it could finish."


def _read_value(record_or_payload: Any, field: str) -> Any:
    if isinstance(record_or_payload, Mapping):
        return record_or_payload.get(field)
    return getattr(record_or_payload, field, None)


def _normalize(value: Any) -> str:
    if isinstance(value, AgentTaskStatus):
        return value.value
    if isinstance(value, str):
        return value.strip().lower()
    return ""
