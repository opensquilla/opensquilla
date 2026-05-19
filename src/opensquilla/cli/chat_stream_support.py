"""Chat stream support helpers."""

from __future__ import annotations

from typing import Any

from opensquilla.session.terminal_reply import build_terminal_reply

_DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
_DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 180.0


def _turn_stream_error_message(event: Any) -> str:
    message = getattr(event, "message", "")
    code = str(getattr(event, "code", "") or "").lower()
    message_text = str(message)
    if "timeout" in code or "stream idle" in message_text.lower():
        return build_terminal_reply(
            {
                "status": "timeout",
                "terminal_reason": "timeout",
                "error_class": getattr(event, "code", None),
                "error_message": message_text,
            }
        )
    return message_text


def _timeout_exception_message(exc: BaseException) -> str:
    return build_terminal_reply(
        {
            "status": "timeout",
            "terminal_reason": "timeout",
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
        }
    )


def _optional_positive_config_float(
    config_source: Any,
    attr: str,
    default: float,
) -> float | None:
    config = getattr(config_source, "config", config_source)
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


def _wrap_cli_turn_stream(stream: Any, config_source: Any) -> Any:
    from opensquilla.runtime.stream_wrappers import wrap_stream

    return wrap_stream(
        stream,
        idle_timeout=_optional_positive_config_float(
            config_source,
            "agent_stream_idle_timeout_seconds",
            _DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
        ),
        heartbeat_interval=_optional_positive_config_float(
            config_source,
            "agent_stream_heartbeat_interval_seconds",
            _DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS,
        ),
        heartbeat_phase="cli",
        heartbeat_message="Still working",
    )
