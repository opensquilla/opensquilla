"""Agent re-emit hop: provider ReasoningDeltaEvent -> engine ThinkingEvent.

The agent layer translates provider-level stream events into engine-level
events. Reasoning must cross this hop as a first-class ThinkingEvent (not folded
into assistant text), so the TUI can render it as a distinct thinking stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from opensquilla.engine import Agent, AgentConfig
from opensquilla.engine.types import ThinkingEvent
from opensquilla.provider import ChatConfig, Message
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import ReasoningDeltaEvent as ProviderReasoning
from opensquilla.provider import TextDeltaEvent as ProviderText


class _ReasoningProvider:
    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderReasoning(text="Let me ")
        yield ProviderReasoning(text="think.")
        yield ProviderText(text="The answer.")
        yield ProviderDone(
            stop_reason="stop",
            input_tokens=5,
            output_tokens=3,
            reasoning_content="Let me think.",
        )

    async def list_models(self) -> list[Any]:
        return []


def test_agent_reemits_reasoning_as_thinking_event() -> None:
    import asyncio

    async def run() -> list[Any]:
        agent = Agent(provider=_ReasoningProvider(), config=AgentConfig(max_iterations=1))
        return [event async for event in agent.run_turn("hi")]

    events = asyncio.run(run())

    thinking = [e for e in events if isinstance(e, ThinkingEvent)]
    assert [t.text for t in thinking] == ["Let me ", "think."]

    # reasoning must NOT be folded into the assistant answer text
    answer = "".join(
        e.text for e in events if type(e).__name__ == "TextDeltaEvent"
    )
    assert answer == "The answer."
    assert "think" not in answer


from opensquilla.engine import ToolResult  # noqa: E402
from opensquilla.engine.types import TextDeltaEvent, ToolCall  # noqa: E402
from opensquilla.provider import (  # noqa: E402
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import ToolUseEndEvent as ProviderToolEnd  # noqa: E402
from opensquilla.provider import ToolUseStartEvent as ProviderToolStart  # noqa: E402


class _TextThenToolThenAnswerProvider:
    """Round 1: narration text + a tool call. Round 2: final answer text."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls += 1
        return self._stream(self.calls)

    async def _stream(self, call: int) -> AsyncIterator[Any]:
        if call == 1:
            # text the model speaks before deciding to call a tool
            yield ProviderText(text="Let me look ")
            yield ProviderText(text="at the file.")
            yield ProviderToolStart(tool_use_id="t1", tool_name="read")
            yield ProviderToolEnd(tool_use_id="t1", tool_name="read", arguments={})
            yield ProviderDone(stop_reason="tool_use", input_tokens=5, output_tokens=2)
            return
        # final answer round: no tool
        yield ProviderText(text="Here is the answer.")
        yield ProviderDone(stop_reason="end_turn", input_tokens=6, output_tokens=3)


def test_pre_tool_text_is_intermediate_final_text_is_answer() -> None:
    import asyncio

    async def tool_handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="{}",
        )

    async def run() -> list[Any]:
        agent = Agent(
            provider=_TextThenToolThenAnswerProvider(),
            config=AgentConfig(max_iterations=3),
            tool_definitions=[
                ToolDefinition(
                    name="read",
                    description="read a file",
                    input_schema=ToolInputSchema(properties={}, required=[]),
                )
            ],
            tool_handler=tool_handler,
        )
        return [event async for event in agent.run_turn("hi")]

    events = asyncio.run(run())
    text_events = [e for e in events if isinstance(e, TextDeltaEvent)]

    intermediate = "".join(e.text for e in text_events if e.presentation == "intermediate")
    answer = "".join(e.text for e in text_events if e.presentation == "answer")

    # text before the tool call is intermediate narration (purple), the text
    # in the final no-tool round is the answer (card)
    assert intermediate == "Let me look at the file."
    assert answer == "Here is the answer."
