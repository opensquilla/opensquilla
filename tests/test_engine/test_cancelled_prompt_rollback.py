"""Zero-output cancelled turns roll back their ingress-persisted prompt (#240)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.runtime import TurnRunner


class _RecordingSessionManager:
    def __init__(self, *, removable: bool = True) -> None:
        self.removed: list[tuple[str, str]] = []
        self._removable = removable

    async def remove_message(self, session_key: str, message_id: str) -> bool:
        self.removed.append((session_key, message_id))
        return self._removable


def _runner(manager) -> TurnRunner:
    return TurnRunner(
        provider_selector=None,
        session_manager=manager,
        config=SimpleNamespace(context_window_tokens=100_000),
    )


@pytest.mark.asyncio
async def test_rollback_removes_bound_prompt() -> None:
    manager = _RecordingSessionManager()
    runner = _runner(manager)

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")

    assert removed is True
    assert manager.removed == [("agent:main:webchat:x", "msg-1")]


@pytest.mark.asyncio
async def test_rollback_reports_false_when_nothing_removed() -> None:
    manager = _RecordingSessionManager(removable=False)
    runner = _runner(manager)

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")

    assert removed is False


@pytest.mark.asyncio
async def test_rollback_is_noop_without_remove_message() -> None:
    # A session manager without remove_message must not raise.
    manager = SimpleNamespace()
    runner = _runner(manager)

    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")

    assert removed is False


@pytest.mark.asyncio
async def test_rollback_swallows_remove_errors() -> None:
    class _FailingManager:
        async def remove_message(self, session_key: str, message_id: str) -> bool:
            raise RuntimeError("boom")

    runner = _runner(_FailingManager())

    # Must not propagate — a rollback failure cannot mask the cancellation.
    removed = await runner._rollback_cancelled_prompt("agent:main:webchat:x", "msg-1")
    assert removed is False
