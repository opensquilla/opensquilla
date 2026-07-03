from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.types import EnsembleProgressEvent as EngineEnsembleProgressEvent
from opensquilla.engine.types import ToolCall
from opensquilla.provider import (
    ChatConfig,
    Message,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import (
    DoneEvent as ProviderDone,
)
from opensquilla.provider import (
    TextDeltaEvent as ProviderText,
)
from opensquilla.provider.types import (
    EnsembleProgressEvent as ProviderEnsembleProgressEvent,
)


class _EnsembleLikeProvider:
    """A provider that emits mid-stream ensemble_progress deltas, exactly like the
    real EnsembleProvider does for its proposers."""

    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderEnsembleProgressEvent(
            event_type="proposer_start",
            proposer_label="anchor",
            proposer_provider="openrouter",
            proposer_model="qwen/qwen3.7-plus",
        )
        yield ProviderEnsembleProgressEvent(
            event_type="proposer_finish",
            proposer_label="anchor",
            proposer_provider="openrouter",
            proposer_model="qwen/qwen3.7-plus",
            input_tokens=10,
            output_tokens=5,
        )
        yield ProviderText(text="synthesized answer")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


async def _tool_handler(call: ToolCall) -> ToolResult:
    return ToolResult(tool_use_id=call.tool_use_id, tool_name=call.tool_name, content="ok")


@pytest.mark.asyncio
async def test_agent_forwards_provider_ensemble_progress_as_engine_event() -> None:
    # This is the previously-unverified link: the ensemble provider yields
    # provider-level EnsembleProgressEvents; the agent loop must re-emit them as
    # engine-level EnsembleProgressEvents so channel_dispatch can broadcast them.
    agent = Agent(
        provider=_EnsembleLikeProvider(),
        config=AgentConfig(max_iterations=2),
        tool_definitions=[
            ToolDefinition(
                name="echo",
                description="Echo.",
                input_schema=ToolInputSchema(properties={}, required=[]),
            )
        ],
        tool_handler=_tool_handler,
    )

    events = [event async for event in agent.run_turn("hi")]
    progress = [e for e in events if isinstance(e, EngineEnsembleProgressEvent)]

    assert len(progress) == 2, f"expected 2 engine ensemble_progress events, got {len(progress)}"
    assert {p.event_type for p in progress} == {"proposer_start", "proposer_finish"}
    assert progress[0].proposer_model == "qwen/qwen3.7-plus"
    finish = next(p for p in progress if p.event_type == "proposer_finish")
    assert finish.input_tokens == 10
    assert finish.output_tokens == 5
