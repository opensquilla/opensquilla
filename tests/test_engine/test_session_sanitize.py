from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.session_sanitize import sanitize_session_messages
from opensquilla.engine.types import ThinkingLevel
from opensquilla.memory.session_flush import _usage_from_complete_response
from opensquilla.provider import (
    ChatConfig,
    ContentBlockText,
    ContentBlockToolResult,
    Message,
    ModelCapabilities,
)
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart


class CapturingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="end_turn", input_tokens=3, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class StaticCostProvider(CapturingProvider):
    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="ok")
        yield ProviderDone(
            stop_reason="end_turn",
            input_tokens=1000,
            output_tokens=1000,
            billed_cost=0.0,
            model="deepseek-v4-flash",
        )


class ToolLoopCapturingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        call_number = len(self.calls) + 1
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        return self._stream(call_number)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo")
            yield ProviderToolUseEnd(
                tool_use_id="tool-1",
                tool_name="echo",
                arguments={"value": "ok"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=3, output_tokens=1)
            return
        yield ProviderText(text="done")
        yield ProviderDone(stop_reason="end_turn", input_tokens=4, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class ReasoningToolLoopCapturingProvider(ToolLoopCapturingProvider):
    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo")
            yield ProviderToolUseEnd(
                tool_use_id="tool-1",
                tool_name="echo",
                arguments={"value": "ok"},
            )
            yield ProviderDone(
                stop_reason="tool_use",
                input_tokens=3,
                output_tokens=1,
                reasoning_content="I should call echo before finalizing.",
            )
            return
        yield ProviderText(text="done")
        yield ProviderDone(stop_reason="end_turn", input_tokens=4, output_tokens=1)


class CapturingTurnLog:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, kind: str, payload: dict[str, Any]) -> None:
        self.records.append({"kind": kind, "payload": payload})


def test_session_sanitize_strips_block_metadata_without_compressing_content() -> None:
    message = Message.model_construct(
        role="user",
        content=[
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "result text with details that must remain factual",
                "is_error": False,
                "details": {"raw_provider": "debug-only"},
                "timestamp": "2026-04-28T14:35:00Z",
            }
        ],
        reasoning_content=None,
    )

    sanitized, result = sanitize_session_messages([message])

    assert result.metadata_keys_removed == 2
    block = sanitized[0].content[0]
    assert isinstance(block, ContentBlockToolResult)
    assert block.content == "result text with details that must remain factual"
    assert "details" not in block.model_dump(mode="json")
    assert "timestamp" not in block.model_dump(mode="json")


def test_tool_result_compression_default_behavior_is_unchanged() -> None:
    config = AgentConfig()
    provider = CapturingProvider()
    agent = Agent(provider=provider, config=config)

    assert config.tool_result_compression_enabled is True
    assert config.tool_result_compression_mode is None
    assert agent._tool_result_compression_mode() == "truncate"


@pytest.mark.asyncio
async def test_agent_static_cost_source_is_explicitly_distinct_from_provider_billed() -> None:
    provider = StaticCostProvider()
    agent = Agent(provider=provider, config=AgentConfig(model_id="deepseek-v4-flash"))

    events = [event async for event in agent.run_turn("hello")]
    done = next(event for event in events if event.kind == "done")

    assert done.billed_cost == 0.0
    assert done.cost_usd > 0.0
    assert done.cost_source == "opensquilla_static_estimate"


def test_complete_response_usage_cost_is_not_provider_billed_for_direct_providers() -> None:
    response = SimpleNamespace(
        model="deepseek-v4-flash",
        usage={
            "prompt_tokens": 1000,
            "completion_tokens": 1000,
            "cost": 0.0123,
        },
    )
    provider = SimpleNamespace(provider_name="deepseek")

    usage = _usage_from_complete_response(response, provider)

    assert usage["billed_cost"] == 0.0
    assert usage["cost_source"] == "opensquilla_static_estimate"
    assert usage["estimated_cost_usd"] > 0.0


@pytest.mark.asyncio
async def test_agent_uses_sanitized_request_view_and_records_context_stages() -> None:
    provider = CapturingProvider()
    turn_log = CapturingTurnLog()
    agent = Agent(
        provider=provider,
        config=AgentConfig(),
        turn_call_logger=turn_log,  # type: ignore[arg-type]
    )
    agent.set_history(
        [
            Message.model_construct(
                role="assistant",
                content=[
                    {
                        "type": "text",
                        "text": "previous answer",
                        "details": {"debug": True},
                    }
                ],
                reasoning_content=None,
            )
        ]
    )

    events = [event async for event in agent.run_turn("continue")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls
    sent_history_block = provider.calls[0]["messages"][0].content[0]
    assert isinstance(sent_history_block, ContentBlockText)
    assert sent_history_block.text == "previous answer"
    assert "details" not in sent_history_block.model_dump(mode="json")

    stages = [
        record["payload"]["stage"]
        for record in turn_log.records
        if record["kind"] == "context_stage"
    ]
    assert stages == [
        "session:loaded",
        "session:sanitized",
        "session:limited",
        "prompt:before",
        "prompt:images",
        "stream:context",
        "session:after",
    ]


@pytest.mark.asyncio
async def test_agent_runtime_context_is_request_only_and_not_system_prefix() -> None:
    provider = CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            system_prompt="stable system",
            cache_breakpoints=[{"text": "stable system", "cache": "true"}],
            cache_mode="auto",
            max_iterations=1,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    call = provider.calls[0]
    assert call["config"].system == "stable system"
    assert call["config"].cache_breakpoints == [{"text": "stable system", "cache": "true"}]
    assert call["messages"][0].role == "user"
    assert "[Runtime context for this turn]" in call["messages"][0].content
    assert call["messages"][1] == Message(role="user", content="hello")
    assert all(
        "[Runtime context for this turn]" not in message.content
        for message in agent._history
        if isinstance(message.content, str)
    )


def test_turn_runner_keeps_dynamic_prompt_out_of_system_when_cache_enabled() -> None:
    from opensquilla.engine.runtime import TurnRunner

    runner = TurnRunner.__new__(TurnRunner)
    turn = SimpleNamespace(
        system_prompt=("stable base", "<memory_context>volatile recall</memory_context>"),
        metadata={"cache_enabled": True},
    )

    final_prompt, cache_breakpoints, request_context_prompt = runner._resolve_prompt_config(turn)

    assert final_prompt == "stable base"
    assert cache_breakpoints == [{"text": "stable base", "cache": "true"}]
    assert request_context_prompt == "<memory_context>volatile recall</memory_context>"


def test_turn_runner_preserves_joined_system_prompt_when_cache_disabled() -> None:
    from opensquilla.engine.runtime import TurnRunner

    runner = TurnRunner.__new__(TurnRunner)
    turn = SimpleNamespace(
        system_prompt=("stable base", "<memory_context>volatile recall</memory_context>"),
        metadata={},
    )

    final_prompt, cache_breakpoints, request_context_prompt = runner._resolve_prompt_config(turn)

    assert final_prompt == "stable base\n\n<memory_context>volatile recall</memory_context>"
    assert cache_breakpoints is None
    assert request_context_prompt is None


def test_agent_adjusts_request_context_indexes_after_compaction() -> None:
    entries = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "[Available skills for this turn]\nskill"},
        {"role": "user", "content": "current question"},
    ]
    kept_entries = [
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current question"},
    ]

    request_idx = Agent._adjust_compacted_insert_index(
        entries,
        kept_entries,
        2,
        summary_present=True,
    )
    runtime_idx = Agent._adjust_compacted_insert_index(
        entries,
        kept_entries,
        3,
        summary_present=True,
    )

    compacted_messages = [
        Message(role="user", content="[Context summary]\nsummary"),
        Message(role="assistant", content="Understood. Continuing from summary."),
        Message(role="assistant", content="old answer"),
        Message(role="user", content="current question"),
    ]
    request_context = Message(role="user", content="[Request context for this turn]\nvolatile")
    runtime_context = Message(role="user", content="[Runtime context for this turn]\nnow")

    request_messages = Agent._with_request_context_messages(
        compacted_messages,
        request_context,
        request_idx,
        runtime_context,
        runtime_idx,
    )

    assert [message.content for message in request_messages] == [
        "[Context summary]\nsummary",
        "Understood. Continuing from summary.",
        "old answer",
        "[Request context for this turn]\nvolatile",
        "[Runtime context for this turn]\nnow",
        "current question",
    ]


@pytest.mark.asyncio
async def test_agent_request_context_is_request_only_after_history() -> None:
    provider = CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            system_prompt="stable system",
            request_context_prompt="<memory_context>volatile recall</memory_context>",
            skills_context_prompt="<skill id='memory'>Memory helper</skill>",
            cache_breakpoints=[{"text": "stable system", "cache": "true"}],
            cache_mode="auto",
            max_iterations=1,
        ),
    )
    agent.set_history(
        [
            Message(role="user", content="old question"),
            Message(role="assistant", content="old answer"),
        ]
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    call = provider.calls[0]
    assert call["config"].system == "stable system"
    assert call["config"].cache_breakpoints == [{"text": "stable system", "cache": "true"}]
    assert "<memory_context>volatile recall</memory_context>" not in call["config"].system
    assert [message.role for message in call["messages"]] == [
        "user",
        "assistant",
        "user",
        "user",
        "user",
        "user",
    ]
    assert call["messages"][0] == Message(role="user", content="old question")
    assert call["messages"][1] == Message(role="assistant", content="old answer")
    assert "[Request context for this turn]" in call["messages"][2].content
    assert "<memory_context>volatile recall</memory_context>" in call["messages"][2].content
    assert "[Available skills for this turn]" in call["messages"][3].content
    assert "[Runtime context for this turn]" in call["messages"][4].content
    assert call["messages"][5] == Message(role="user", content="hello")
    assert all(
        "<memory_context>volatile recall</memory_context>" not in message.content
        for message in agent._history
        if isinstance(message.content, str)
    )


@pytest.mark.asyncio
async def test_agent_request_context_repeats_across_tool_loop_without_persisting() -> None:
    provider = ToolLoopCapturingProvider()

    async def tool_handler(call: Any) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="tool ok",
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            system_prompt="stable system",
            request_context_prompt="<memory_context>volatile recall</memory_context>",
            max_iterations=2,
        ),
        tool_handler=tool_handler,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 2
    for call in provider.calls:
        request_context_messages = [
            message
            for message in call["messages"]
            if isinstance(message.content, str)
            and "<memory_context>volatile recall</memory_context>" in message.content
        ]
        assert len(request_context_messages) == 1
        assert "[Request context for this turn]" in request_context_messages[0].content
    assert all(
        "<memory_context>volatile recall</memory_context>" not in message.content
        for message in agent._history
        if isinstance(message.content, str)
    )


@pytest.mark.asyncio
async def test_agent_preserves_reasoning_content_for_deepseek_tool_replay() -> None:
    provider = ReasoningToolLoopCapturingProvider()

    async def tool_handler(call: Any) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="tool ok",
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=2,
            thinking=ThinkingLevel.HIGH,
            model_id="deepseek-v4-flash",
            model_capabilities=ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="deepseek",
            ),
        ),
        tool_handler=tool_handler,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 2
    replay_messages = provider.calls[1]["messages"]
    assistant_replay = next(
        message
        for message in replay_messages
        if message.role == "assistant"
        and isinstance(message.content, list)
        and any(getattr(block, "type", None) == "tool_use" for block in message.content)
    )
    assert assistant_replay.reasoning_content == "I should call echo before finalizing."


@pytest.mark.asyncio
async def test_agent_preserves_reasoning_content_for_deepseek_text_replay() -> None:
    provider = CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            thinking=ThinkingLevel.HIGH,
            model_id="deepseek-v4-flash",
            model_capabilities=ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="deepseek",
            ),
        ),
    )
    agent.set_history(
        [
            Message(role="user", content="old question"),
            Message(
                role="assistant",
                content=[ContentBlockText(text="old answer")],
                reasoning_content="I reasoned before answering.",
            ),
        ]
    )

    events = [event async for event in agent.run_turn("continue")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls
    sent_assistant = provider.calls[0]["messages"][1]
    assert sent_assistant.reasoning_content == "I reasoned before answering."


@pytest.mark.asyncio
async def test_agent_preserves_direct_deepseek_v4_reasoning_without_capabilities() -> None:
    provider = CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            thinking=ThinkingLevel.HIGH,
            model_id="deepseek-v4-flash",
            model_capabilities=None,
        ),
    )
    agent.set_history(
        [
            Message(role="user", content="old question"),
            Message(
                role="assistant",
                content=[ContentBlockText(text="old answer")],
                reasoning_content="I reasoned before answering.",
            ),
        ]
    )

    events = [event async for event in agent.run_turn("continue")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls
    sent_assistant = provider.calls[0]["messages"][1]
    assert sent_assistant.reasoning_content == "I reasoned before answering."


@pytest.mark.asyncio
async def test_agent_drops_reasoning_content_when_model_is_not_deepseek() -> None:
    provider = CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            thinking=ThinkingLevel.HIGH,
            model_id="custom-reasoning-model",
            model_capabilities=ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="deepseek",
            ),
        ),
    )
    agent.set_history(
        [
            Message(role="user", content="old question"),
            Message(
                role="assistant",
                content=[ContentBlockText(text="old answer")],
                reasoning_content="I reasoned before answering.",
            ),
        ]
    )

    events = [event async for event in agent.run_turn("continue")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls
    sent_assistant = provider.calls[0]["messages"][1]
    assert sent_assistant.reasoning_content is None
