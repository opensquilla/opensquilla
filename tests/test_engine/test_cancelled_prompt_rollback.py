"""Zero-output cancelled turns keep their ingress-persisted prompt visible."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.runtime import TurnRunner


class _RecordingSessionManager:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    async def remove_message(self, session_key: str, message_id: str) -> bool:
        self.removed.append((session_key, message_id))
        return True


def _runner(manager) -> TurnRunner:
    return TurnRunner(
        provider_selector=None,
        session_manager=manager,
        config=SimpleNamespace(context_window_tokens=100_000),
    )


@pytest.mark.asyncio
async def test_zero_output_cancel_keeps_bound_prompt_visible() -> None:
    manager = _RecordingSessionManager()
    runner = _runner(manager)

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")

    assert removed is False
    assert manager.removed == []


@pytest.mark.asyncio
async def test_cancelled_prompt_retention_is_noop_without_remove_message() -> None:
    # A session manager without remove_message must not raise.
    manager = SimpleNamespace()
    runner = _runner(manager)

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")

    assert removed is False


@pytest.mark.asyncio
async def test_cancelled_prompt_retention_never_calls_remove_message() -> None:
    class _FailingManager:
        async def remove_message(self, session_key: str, message_id: str) -> bool:
            raise AssertionError("remove_message should not be called")

    runner = _runner(_FailingManager())

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")
    assert removed is False
