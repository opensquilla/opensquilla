"""SessionManager.finish drops module-level subagent + injected runtime bookkeeping."""

from __future__ import annotations

import pytest

from opensquilla.session.manager import SessionManager
from opensquilla.session.models import SessionStatus
from opensquilla.session.spawn_groups import spawn_group_tracker


class _MemoryStorage:
    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}

    async def get_session(self, session_key: str):
        return self._sessions.get(session_key)

    async def upsert_session(self, node) -> None:
        self._sessions[node.session_key] = node


@pytest.mark.asyncio
async def test_finish_evicts_spawn_group_tracker_and_routing_history() -> None:
    from opensquilla.session.models import SessionNode

    evicted: list[str] = []
    storage = _MemoryStorage()
    node = SessionNode(
        session_key="agent:main:main",
        session_id="abc",
        agent_id="main",
        created_at=1,
        updated_at=1,
        started_at=1,
        status=SessionStatus.RUNNING,
    )
    await storage.upsert_session(node)

    spawn_group_tracker.mark_closed("agent:main:main", "task-X")
    assert spawn_group_tracker.is_closed("agent:main:main", "task-X")

    mgr = SessionManager(storage, runtime_state_evictors=[evicted.append])  # type: ignore[arg-type]
    await mgr.finish("agent:main:main", status=SessionStatus.DONE)

    assert not spawn_group_tracker.is_closed("agent:main:main", "task-X")
    assert evicted == ["agent:main:main"]
