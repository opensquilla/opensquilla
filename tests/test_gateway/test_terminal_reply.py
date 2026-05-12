from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.session.models import AgentTaskStatus
from opensquilla.session.terminal_reply import build_terminal_reply

RAW_INTERNAL_STRINGS = (
    "Gateway task timeout",
    "Stream idle for more than",
)


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        (
            {
                "status": "timeout",
                "terminal_reason": "timeout",
                "error_class": "TimeoutError",
                "error_message": "Gateway task timeout: Stream idle for more than 60s",
            },
            "timed out",
        ),
        (
            {
                "status": "failed",
                "terminal_reason": "error",
                "error_class": "RuntimeError",
                "error_message": "boom",
            },
            "failed",
        ),
        (
            {
                "status": "abandoned",
                "terminal_reason": "shutdown_timeout",
            },
            "stopped",
        ),
        (
            {
                "status": "cancelled",
                "terminal_reason": "cancelled",
            },
            "cancelled",
        ),
    ],
)
def test_build_terminal_reply_returns_user_readable_messages(
    payload: dict[str, Any],
    expected_fragment: str,
) -> None:
    message = build_terminal_reply(payload)

    assert message
    assert expected_fragment in message.lower()
    assert not message.startswith("terminal_reason=")
    for raw in RAW_INTERNAL_STRINGS:
        assert raw not in message


def test_build_terminal_reply_accepts_agent_task_record_like_objects() -> None:
    record = SimpleNamespace(
        status=AgentTaskStatus.TIMEOUT,
        terminal_reason="timeout",
        error_class="TimeoutError",
        error_message="Gateway task timeout: Stream idle for more than 120s",
    )

    message = build_terminal_reply(record, surface="terminal", locale="en")

    assert "timed out" in message.lower()
    for raw in RAW_INTERNAL_STRINGS:
        assert raw not in message
