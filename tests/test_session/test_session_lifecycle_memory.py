from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from opensquilla.session.lifecycle_memory import preserve_lifecycle_memory


class _TranscriptSessionManager:
    def __init__(self, transcript: list[object]) -> None:
        self.transcript = transcript

    async def get_transcript(self, key: str) -> list[object]:
        return self.transcript


@pytest.mark.asyncio
async def test_preserve_lifecycle_memory_owns_unavailable_flush_policy() -> None:
    session = SimpleNamespace(session_id="abc123", agent_id="agent-1")
    result = await preserve_lifecycle_memory(
        "reset",
        _TranscriptSessionManager([object(), object()]),
        None,
        "agent:main:webchat:abc123",
        session,
        force=False,
        principal_scopes={"operator.write"},
    )

    assert result.previous_session_id == "abc123"
    assert result.receipt is None
    assert result.failure is not None
    assert result.failure.code == "flush_unavailable"
    assert result.failure.details == {
        "key": "agent:main:webchat:abc123",
        "session_id": "abc123",
        "reason": "flush_service_disabled",
        "message_count": 2,
    }


@pytest.mark.asyncio
async def test_preserve_lifecycle_memory_owns_available_flush_execution_contract() -> None:
    transcript = [object()]
    receipt = SimpleNamespace(mode="skipped", error=None, to_dict=lambda: {"mode": "skipped"})
    flush_service = SimpleNamespace(execute=AsyncMock(return_value=receipt))
    session = SimpleNamespace(session_id="abc123", agent_id="agent/custom")

    result = await preserve_lifecycle_memory(
        "compact",
        _TranscriptSessionManager(transcript),
        flush_service,
        "agent:main:webchat:abc123",
        session,
        force=False,
        principal_scopes={"operator.write"},
    )

    flush_service.execute.assert_awaited_once_with(
        transcript,
        "agent:main:webchat:abc123",
        agent_id="agent-custom",
        timeout=30.0,
        message_window=0,
        segment_mode="auto",
    )
    assert result.previous_session_id == "abc123"
    assert result.receipt is receipt
    assert result.failure is None
