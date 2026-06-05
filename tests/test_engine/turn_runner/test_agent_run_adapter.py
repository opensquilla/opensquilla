from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine.agent_injection import ListPendingInputProvider
from opensquilla.engine.turn_runner.harness import _TurnRunnerAgentRunAdapter
from opensquilla.engine.types import DoneEvent


async def _collect(events: AsyncIterator[Any]) -> list[Any]:
    return [event async for event in events]


class _LegacyAgent:
    async def run_turn(
        self,
        turn_input: str,
        *,
        extra_messages: list[Any] | None = None,
        semantic_message: str | None = None,
    ) -> AsyncIterator[Any]:
        yield DoneEvent(text=f"{turn_input}:{semantic_message}:{extra_messages}")


class _ModernAgent:
    def __init__(self) -> None:
        self.received: dict[str, Any] | None = None

    async def run_turn(
        self,
        turn_input: str,
        *,
        extra_messages: list[Any] | None = None,
        semantic_message: str | None = None,
        pending_input_provider: Any | None = None,
    ) -> AsyncIterator[Any]:
        self.received = {
            "turn_input": turn_input,
            "extra_messages": extra_messages,
            "semantic_message": semantic_message,
            "pending_input_provider": pending_input_provider,
        }
        yield DoneEvent(text="ok")


@pytest.mark.asyncio
async def test_agent_run_adapter_omits_pending_input_provider_for_legacy_agent() -> None:
    pending = ListPendingInputProvider()
    pending.append("later")
    adapter = _TurnRunnerAgentRunAdapter()

    events = await _collect(
        adapter.run_turn(
            _LegacyAgent(),
            turn_input="hi",
            extra_messages=None,
            semantic_message="semantic-hi",
            pending_input_provider=pending,
        )
    )

    assert [event.kind for event in events] == ["done"]


@pytest.mark.asyncio
async def test_agent_run_adapter_forwards_pending_input_provider_when_supported() -> None:
    pending = ListPendingInputProvider()
    pending.append("later")
    agent = _ModernAgent()
    adapter = _TurnRunnerAgentRunAdapter()

    await _collect(
        adapter.run_turn(
            agent,
            turn_input="hi",
            extra_messages=[],
            semantic_message="semantic-hi",
            pending_input_provider=pending,
        )
    )

    assert agent.received == {
        "turn_input": "hi",
        "extra_messages": [],
        "semantic_message": "semantic-hi",
        "pending_input_provider": pending,
    }
