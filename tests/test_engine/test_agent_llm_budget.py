from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine import (
    Agent,
    AgentConfig,
    AgentState,
    DoneEvent,
    ErrorEvent,
    RunHeartbeatEvent,
    SubagentSpec,
    ToolCall,
    ToolResult,
    WarningEvent,
)
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.session_sanitize import session_payload_chars
from opensquilla.provider import (
    ChatConfig,
    Message,
    ProviderHeartbeatEvent,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import ErrorEvent as ProviderError
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseDeltaEvent as ProviderToolUseDelta
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart
from opensquilla.provider.request_proof import (
    ProviderRequestBudgetExceeded,
    prove_provider_payload,
)
from opensquilla.session.compaction import CompactionResult

RAW_CURRENT_TURN_OVERFLOW_MESSAGE = (
    "Context overflow is in the current turn's recent tool calls or "
    "reasoning tail; history compaction cannot reduce it."
)


class _StallingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.stream_closed = False

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        try:
            await asyncio.sleep(60.0)
            yield ProviderText(text="late")
        finally:
            self.stream_closed = True

    async def list_models(self) -> list[Any]:
        return []


class _ActiveLongToolArgumentProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        fragment_delay: float = 0.02,
        content: str = "alpha\\nbeta\\ngamma\\n",
    ) -> None:
        self.fragment_delay = fragment_delay
        self.content = content
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number > 1:
            yield ProviderText(text="done")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        tool_use_id = "tool-1"
        yield ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="write_file")
        fragments = [
            '{"path":"deck.py","content":"',
            self.content,
            '"}',
        ]
        for fragment in fragments:
            await asyncio.sleep(self.fragment_delay)
            yield ProviderToolUseDelta(tool_use_id=tool_use_id, json_fragment=fragment)
        yield ProviderToolUseEnd(
            tool_use_id=tool_use_id,
            tool_name="write_file",
            arguments={},
        )
        yield ProviderDone(stop_reason="tool_calls", input_tokens=1, output_tokens=100)

    async def list_models(self) -> list[Any]:
        return []


class _ContextOverflowProvider:
    provider_name = "fake"

    def __init__(self, *, success_after: int | None = None) -> None:
        self.success_after = success_after
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if self.success_after is not None and call_number > self.success_after:
            yield ProviderText(text="ok")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        yield ProviderError(message="context length exceeded", code="400")

    async def list_models(self) -> list[Any]:
        return []


class _ProviderRequestBudgetExceededProvider:
    provider_name = "openrouter"

    def __init__(
        self,
        *,
        success_after: int | None = None,
        proof: dict[str, Any] | None = None,
    ) -> None:
        self.success_after = success_after
        self.proof = proof
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if self.success_after is not None and call_number > self.success_after:
            yield ProviderText(text="ok")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        message = (
            '{"fallback_reason":"provider_request_budget_exhausted"}'
            if self.proof is None
            else json.dumps(self.proof)
        )
        yield ProviderError(message=message, code="provider_request_budget_exhausted")

    async def list_models(self) -> list[Any]:
        return []


class _RepeatedToolFailureThenDoneProvider:
    provider_name = "fake"

    def __init__(self, *, tool_retries: int = 3) -> None:
        self.tool_retries = tool_retries
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number > self.tool_retries:
            yield ProviderText(text="handled")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        tool_use_id = f"cmd-{call_number}"
        yield ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="exec_command")
        yield ProviderToolUseEnd(
            tool_use_id=tool_use_id,
            tool_name="exec_command",
            arguments={"command": "python build_pptx.py", "timeout": 30},
        )
        yield ProviderDone(stop_reason="tool_calls", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _HighUsageToolLoopProvider:
    provider_name = "fake"

    def __init__(self, *, tool_rounds: int = 3, input_tokens_per_call: int = 4000) -> None:
        self.tool_rounds = tool_rounds
        self.input_tokens_per_call = input_tokens_per_call
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number > self.tool_rounds:
            yield ProviderText(text="done")
            yield ProviderDone(
                stop_reason="stop",
                input_tokens=self.input_tokens_per_call,
                output_tokens=0,
            )
            return
        tool_use_id = f"read-{call_number}"
        yield ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="exec_command")
        yield ProviderToolUseEnd(
            tool_use_id=tool_use_id,
            tool_name="exec_command",
            arguments={"command": f"printf round-{call_number}"},
        )
        yield ProviderDone(
            stop_reason="tool_calls",
            input_tokens=self.input_tokens_per_call,
            output_tokens=0,
        )

    async def list_models(self) -> list[Any]:
        return []


class _ConfigCapturingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.configs: list[ChatConfig | None] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.configs.append(config)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _NoBilledCostUsageProvider:
    provider_name = "fake"

    def __init__(self, *, input_tokens: int = 1, output_tokens: int = 1) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="done")
        yield ProviderDone(
            stop_reason="stop",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            billed_cost=0.0,
        )

    async def list_models(self) -> list[Any]:
        return []


class _MixedBilledAndEstimatedCostProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            # First call reports a real billed cost, small enough to stay
            # under budget on its own.
            tool_use_id = "tool-1"
            yield ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="exec_command")
            yield ProviderToolUseEnd(
                tool_use_id=tool_use_id,
                tool_name="exec_command",
                arguments={"command": "echo hi"},
            )
            yield ProviderDone(
                stop_reason="tool_calls",
                input_tokens=1,
                output_tokens=1,
                billed_cost=0.0005,
            )
            return
        # Second call is cost-blind (billed_cost=0.0), forcing the estimator
        # to supply the remaining component that tips the turn over budget.
        yield ProviderText(text="done")
        yield ProviderDone(
            stop_reason="stop",
            input_tokens=1000,
            output_tokens=1000,
            billed_cost=0.0,
        )

    async def list_models(self) -> list[Any]:
        return []


class _CompactingErrorSessionManager:
    def __init__(self, *, compact_raises: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.compact_raises = compact_raises

    async def compact(self, session_key: str, budget: int, config: Any | None = None) -> str:
        self.calls.append(("compact", session_key))
        assert budget > 0
        if self.compact_raises:
            raise RuntimeError("compact failed")
        return "[summary]"

    async def append_message(self, session_key: str, **kwargs: Any) -> None:
        self.calls.append(("append", session_key))
        assert kwargs["role"] == "system"
        assert kwargs["content"].startswith("Error: ")


@pytest.mark.asyncio
async def test_turn_error_persist_records_current_turn_exhaustion_without_compacting() -> None:
    session_manager = _CompactingErrorSessionManager()
    runner = TurnRunner(
        provider_selector=None,
        session_manager=session_manager,
        config=SimpleNamespace(context_budget_tokens=96_000),
    )

    await runner._persist_turn_error(
        "agent:main:webchat:test",
        ErrorEvent(
            message="Context overflow is in the current turn's recent tool calls.",
            code="current_turn_context_exhausted",
        ),
    )

    assert session_manager.calls == [("append", "agent:main:webchat:test")]


@pytest.mark.asyncio
async def test_turn_error_persist_skips_error_time_compaction_for_exhaustion() -> None:
    session_manager = _CompactingErrorSessionManager(compact_raises=True)
    runner = TurnRunner(
        provider_selector=None,
        session_manager=session_manager,
        config=SimpleNamespace(context_budget_tokens=96_000),
    )

    await runner._persist_turn_error(
        "agent:main:webchat:test",
        ErrorEvent(
            message="Context overflow is in the current turn's recent tool calls.",
            code="current_turn_context_exhausted",
        ),
    )

    assert session_manager.calls == [("append", "agent:main:webchat:test")]


@pytest.mark.asyncio
async def test_agent_blocks_repeated_identical_tool_failures_before_tail_growth() -> None:
    calls = 0

    async def _failing_tool(call: Any) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="write failed: " + ("permission denied " * 200),
            is_error=True,
        )

    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(
            tool_failure_loop_block_threshold=3,
        ),
        tool_handler=_failing_tool,
    )
    tool_call = ToolCall(
        tool_use_id="write-1",
        tool_name="write_file",
        arguments={"path": "index.html", "content": "<html>bad</html>"},
    )

    first = await agent._execute_tool(tool_call)
    second = await agent._execute_tool(tool_call)
    third = await agent._execute_tool(tool_call)

    assert first.is_error is True
    assert second.is_error is True
    assert third.is_error is True
    assert calls == 2
    assert "tool_failure_loop_exhausted" not in third.content
    assert "Do not retry this exact call unchanged" in third.content
    assert len(third.content) < len(second.content)
    assert third.execution_status is not None
    assert third.execution_status.get("reason") == "tool_failure_loop_exhausted"


@pytest.mark.asyncio
async def test_agent_tool_failure_loop_allows_changed_arguments() -> None:
    calls = 0

    async def _failing_tool(call: Any) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="write failed",
            is_error=True,
        )

    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(tool_failure_loop_block_threshold=3),
        tool_handler=_failing_tool,
    )

    await agent._execute_tool(
        ToolCall(
            tool_use_id="write-1",
            tool_name="write_file",
            arguments={"path": "index.html", "content": "first"},
        )
    )
    await agent._execute_tool(
        ToolCall(
            tool_use_id="write-2",
            tool_name="write_file",
            arguments={"path": "index.html", "content": "first"},
        )
    )
    changed = await agent._execute_tool(
        ToolCall(
            tool_use_id="write-3",
            tool_name="write_file",
            arguments={"path": "index.html", "content": "changed"},
        )
    )

    assert calls == 3
    assert changed.content == "write failed"


@pytest.mark.asyncio
async def test_agent_tool_failure_loop_result_returns_to_model_instead_of_terminal_error() -> None:
    provider = _RepeatedToolFailureThenDoneProvider(tool_retries=3)
    handler_calls = 0

    async def _failing_tool(call: Any) -> ToolResult:
        nonlocal handler_calls
        handler_calls += 1
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="syntax error",
            is_error=True,
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            tool_failure_loop_block_threshold=3,
            max_iterations=5,
            flush_enabled=False,
        ),
        tool_handler=_failing_tool,
    )

    events = [event async for event in agent.run_turn("build the deck")]

    assert handler_calls == 2
    assert len(provider.calls) == 4
    assert any(isinstance(event, DoneEvent) for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and getattr(event, "code", None) == "tool_failure_loop_exhausted"
        for event in events
    )
    assert any(
        getattr(event, "kind", None) == "tool_result"
        and (getattr(event, "execution_status", None) or {}).get("reason")
        == "tool_failure_loop_exhausted"
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_tool_failure_loop_resets_after_successful_state_change() -> None:
    calls: list[str] = []

    async def _tool(call: Any) -> ToolResult:
        calls.append(call.tool_name)
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="ok" if call.tool_name == "edit_file" else "syntax error",
            is_error=call.tool_name != "edit_file",
        )

    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(tool_failure_loop_block_threshold=3),
        tool_handler=_tool,
    )
    command_call = ToolCall(
        tool_use_id="cmd-1",
        tool_name="exec_command",
        arguments={"command": "python build_pptx.py", "timeout": 30},
    )

    await agent._execute_tool(command_call)
    await agent._execute_tool(
        ToolCall(
            tool_use_id="cmd-2",
            tool_name="exec_command",
            arguments=command_call.arguments,
        )
    )
    await agent._execute_tool(
        ToolCall(
            tool_use_id="edit-1",
            tool_name="edit_file",
            arguments={"path": "build_pptx.py", "old_text": "bad", "new_text": "good"},
        )
    )
    retry_after_edit = await agent._execute_tool(
        ToolCall(
            tool_use_id="cmd-3",
            tool_name="exec_command",
            arguments=command_call.arguments,
        )
    )

    assert calls == ["exec_command", "exec_command", "edit_file", "exec_command"]
    assert retry_after_edit.content == "syntax error"
    assert retry_after_edit.execution_status is None


@pytest.mark.asyncio
async def test_agent_blocks_repeated_missing_tool_handler_failures() -> None:
    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(tool_failure_loop_block_threshold=3),
    )
    tool_call = ToolCall(
        tool_use_id="missing-1",
        tool_name="missing_tool",
        arguments={"value": "same"},
    )

    await agent._execute_tool(tool_call)
    await agent._execute_tool(tool_call)
    third = await agent._execute_tool(tool_call)

    assert "tool_failure_loop_exhausted" not in third.content
    assert "Do not retry this exact call unchanged" in third.content
    assert third.execution_status is not None
    assert third.execution_status.get("reason") == "tool_failure_loop_exhausted"


@pytest.mark.asyncio
async def test_agent_provider_request_proof_budget_is_separate_from_tool_result_cap() -> None:
    provider = _ConfigCapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=200_000,
            max_tokens=8192,
            tool_result_provider_request_max_chars=96_000,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert provider.configs
    assert provider.configs[0] is not None
    assert provider.configs[0].provider_request_max_chars > 96_000


@pytest.mark.asyncio
async def test_agent_provider_request_proof_budget_accepts_explicit_override() -> None:
    provider = _ConfigCapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            provider_request_proof_max_chars=123_456,
            tool_result_provider_request_max_chars=96_000,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert provider.configs
    assert provider.configs[0] is not None
    assert provider.configs[0].provider_request_max_chars == 123_456


def test_agent_child_config_inherits_tool_failure_loop_thresholds() -> None:
    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(
            tool_failure_loop_block_threshold=7,
        ),
    )

    child = agent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child.config.tool_failure_loop_block_threshold == 7


def test_agent_config_normalizes_flush_triggers_and_clamps_compaction_tail() -> None:
    config = AgentConfig(
        flush_triggers=["reset", "inline_overflow"],
        compaction_protected_recent_messages=-4,
    )

    assert config.flush_triggers == ["session_reset", "pre_compaction"]
    assert config.compaction_protected_recent_messages == 0


def test_agent_config_rejects_unknown_flush_triggers() -> None:
    with pytest.raises(ValueError, match="unknown flush trigger"):
        AgentConfig(flush_triggers=["manual", "bogus"])


def test_agent_child_config_inherits_context_and_flush_budget_policy() -> None:
    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(
            context_window_tokens=200_000,
            max_tokens=8192,
            provider_request_proof_max_chars=123_456,
            tool_use_argument_provider_request_max_chars=12_345,
            tool_result_provider_request_max_chars=54_321,
            max_turn_llm_calls=9,
            max_turn_input_tokens=700_000,
            max_turn_output_tokens=70_000,
            max_turn_billed_cost_usd=0.75,
            max_turn_tool_errors=4,
            flush_enabled=True,
            flush_triggers=["session_reset", "manual", "idle", "pre_compaction"],
            flush_pre_compaction=True,
            flush_timeout_seconds=1.5,
            flush_background_timeout_seconds=15.0,
            flush_backoff_initial_seconds=3.0,
            flush_backoff_max_seconds=30.0,
            flush_archive_max_bytes=999_999,
            flush_compaction_requires_safe_receipt=False,
        ),
    )

    child = agent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child.config.context_window_tokens == 200_000
    assert child.config.provider_request_proof_max_chars == 123_456
    assert child.config.tool_use_argument_provider_request_max_chars == 12_345
    assert child.config.tool_result_provider_request_max_chars == 54_321
    assert child.config.max_turn_llm_calls == 9
    assert child.config.max_turn_input_tokens == 700_000
    assert child.config.max_turn_output_tokens == 70_000
    assert child.config.max_turn_billed_cost_usd == 0.75
    assert child.config.max_turn_tool_errors == 4
    assert child.config.flush_enabled is True
    assert child.config.flush_triggers == [
        "session_reset",
        "manual",
        "idle",
        "pre_compaction",
    ]
    assert child.config.flush_pre_compaction is True
    assert child.config.flush_timeout_seconds == 1.5
    assert child.config.flush_background_timeout_seconds == 15.0
    assert child.config.flush_backoff_initial_seconds == 3.0
    assert child.config.flush_backoff_max_seconds == 30.0
    assert child.config.flush_archive_max_bytes == 999_999
    assert child.config.flush_compaction_requires_safe_receipt is False


def test_agent_config_max_turn_cost_usd_defaults_to_disabled() -> None:
    assert AgentConfig().max_turn_cost_usd == 0.0


@pytest.mark.asyncio
async def test_agent_skips_price_resolution_per_event_when_turn_cost_budget_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # max_turn_cost_usd left at its disabled default (0.0): the turn-cost
    # accumulator in the per-event ProviderDoneEvent branch must never touch
    # the (potentially network-blocking) price resolver, even across several
    # cost-blind LLM calls in the same turn. A single call to
    # resolve_model_price still happens once, at the very end of the turn,
    # for the pre-existing DoneEvent cost-reporting computation (out of scope
    # for this gate) — so this asserts the count does *not* scale with the
    # number of LLM calls, rather than asserting zero calls overall.
    import opensquilla.engine.pricing as pricing_module

    calls: list[tuple[str, str]] = []
    real_resolve_model_price = pricing_module.resolve_model_price

    def _counting_resolve_model_price(model_id: str, provider: str = "") -> Any:
        calls.append((model_id, provider))
        return real_resolve_model_price(model_id, provider)

    monkeypatch.setattr(pricing_module, "resolve_model_price", _counting_resolve_model_price)

    provider = _HighUsageToolLoopProvider(tool_rounds=3, input_tokens_per_call=1000)

    async def _tool(call: Any) -> ToolResult:
        return ToolResult(tool_use_id=call.tool_use_id, tool_name=call.tool_name, content="ok")

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            model_id="deepseek/deepseek-v4-pro-20260423",
            flush_enabled=False,
        ),
        tool_handler=_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 4
    assert not any(event.kind == "error" for event in events)
    assert any(event.kind == "done" for event in events)
    # Exactly one call: the end-of-turn DoneEvent cost estimate. None of the
    # four per-event ProviderDoneEvent accumulation passes should have called
    # the resolver while the gate is disabled.
    assert len(calls) == 1


def test_agent_child_config_inherits_max_turn_cost_usd() -> None:
    agent = Agent(
        provider=_ContextOverflowProvider(success_after=1),
        config=AgentConfig(max_turn_cost_usd=0.42),
    )

    child = agent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child.config.max_turn_cost_usd == 0.42


@pytest.mark.asyncio
async def test_agent_stops_when_turn_estimated_cost_budget_is_exceeded() -> None:
    # No provider-billed cost at all (billed_cost=0.0 on every call), so the
    # gate must fall back to the estimator to know it is over budget.
    provider = _NoBilledCostUsageProvider(input_tokens=1000, output_tokens=1000)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            model_id="deepseek/deepseek-v4-pro-20260423",
            max_turn_cost_usd=0.001,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    error = next(
        event
        for event in events
        if event.kind == "error" and event.code == "turn_cost_budget_exceeded"
    )
    assert "estimated cost basis" in error.message


@pytest.mark.asyncio
async def test_agent_labels_turn_cost_budget_error_as_mixed_when_billed_and_estimated() -> None:
    # Turn mixes a real billed cost (call 1) with an estimated cost (call 2,
    # cost-blind) — the gate's basis label must reflect both contributions.
    provider = _MixedBilledAndEstimatedCostProvider()

    async def _tool(call: Any) -> ToolResult:
        return ToolResult(tool_use_id=call.tool_use_id, tool_name=call.tool_name, content="ok")

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            model_id="deepseek/deepseek-v4-pro-20260423",
            max_turn_cost_usd=0.001,
        ),
        tool_handler=_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    error = next(
        event
        for event in events
        if event.kind == "error" and event.code == "turn_cost_budget_exceeded"
    )
    assert "mixed cost basis" in error.message


def test_with_model_usage_cost_fields_prices_unbilled_cache_reads_cache_aware() -> None:
    from opensquilla.engine import agent as agent_module

    blind_row = {
        "model": "deepseek/deepseek-v4-pro-20260423",
        "input_tokens": 1000,
        "output_tokens": 0,
        "billed_cost": 0.0,
    }
    cached_row = dict(blind_row, cache_read_tokens=800)

    blind = agent_module._with_model_usage_cost_fields([blind_row])[0]
    cached = agent_module._with_model_usage_cost_fields([cached_row])[0]

    assert blind["estimate_basis"] == "cache_aware"
    assert cached["estimate_basis"] == "cache_aware"
    # (200 * 0.435 + 800 * 0.003625) / 1e6 == 0.0000899, rounded to 6dp by
    # model_usage_cost_fields.
    assert cached["cost_usd"] == pytest.approx(0.00009)
    assert cached["cost_usd"] < blind["cost_usd"]


class _BudgetCheckingProvider:
    provider_name = "openrouter"

    def __init__(self, *, proof_budget: int) -> None:
        self.proof_budget = proof_budget
        self.calls: list[list[Message]] = []
        self.proofs: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(messages)

    async def _stream(self, messages: list[Message]) -> AsyncIterator[Any]:
        payload = {
            "messages": [message.model_dump(mode="json") for message in messages]
        }
        try:
            proof = prove_provider_payload(
                payload,
                projection_adapter="openrouter",
                proof_budget=self.proof_budget,
            )
        except ProviderRequestBudgetExceeded as exc:
            self.proofs.append(exc.proof)
            yield ProviderError(
                message=json.dumps(exc.proof),
                code="provider_request_budget_exhausted",
            )
            return

        self.proofs.append(proof)
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _ProviderRaisesTimeout:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        raise TimeoutError("provider transport timeout")
        yield ProviderText(text="unreachable")

    async def list_models(self) -> list[Any]:
        return []


class _ProviderHeartbeatThenText:
    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderHeartbeatEvent(phase="llm_fallback", message="retrying")
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _ToolUseProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="slow")
        yield ProviderToolUseEnd(
            tool_use_id="tool-1",
            tool_name="slow",
            arguments={},
        )
        yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_provider_heartbeat_reaches_agent_stream() -> None:
    agent = Agent(
        provider=_ProviderHeartbeatThenText(),
        config=AgentConfig(iteration_timeout=30.0, timeout=60.0, max_provider_retries=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    heartbeat_index = _event_index(
        events,
        lambda event: isinstance(event, RunHeartbeatEvent)
        and event.phase == "llm_fallback"
        and event.message == "retrying",
    )
    text_index = _event_index(
        events,
        lambda event: getattr(event, "kind", None) == "text_delta"
        and getattr(event, "text", None) == "ok",
    )
    assert heartbeat_index < text_index


@pytest.mark.asyncio
async def test_iteration_timeout_interrupts_stalled_provider_stream() -> None:
    provider = _StallingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(iteration_timeout=0.01, max_provider_retries=0),
    )

    events = await asyncio.wait_for(
        _collect_events(agent.run_turn("hello")),
        timeout=0.5,
    )

    error_index = _event_index(
        events,
        lambda event: isinstance(event, ErrorEvent) and event.code == "iteration_timeout",
    )
    state_index = _event_index(
        events,
        lambda event: getattr(event, "kind", None) == "state_change"
        and getattr(event, "to_state", None) == AgentState.ERROR,
    )
    assert state_index < error_index
    assert len(provider.calls) == 1
    assert provider.stream_closed is True
    assert not any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_iteration_timeout_does_not_interrupt_active_tool_argument_stream() -> None:
    async def write_file_tool(call: object) -> ToolResult:
        return ToolResult(
            tool_use_id=getattr(call, "tool_use_id"),
            tool_name=getattr(call, "tool_name"),
            content="written",
        )

    provider = _ActiveLongToolArgumentProvider(fragment_delay=0.02)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            iteration_timeout=0.03,
            timeout=1.0,
            max_provider_retries=0,
        ),
        tool_definitions=[
            ToolDefinition(
                name="write_file",
                description="Write a file.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=write_file_tool,
    )

    events = await asyncio.wait_for(_collect_events(agent.run_turn("hello")), timeout=1.0)

    assert provider.calls
    assert any(
        getattr(event, "kind", None) == "tool_result"
        and getattr(event, "tool_name", None) == "write_file"
        and getattr(event, "result", None) == "written"
        for event in events
    )
    assert any(isinstance(event, DoneEvent) for event in events)
    assert not any(
        isinstance(event, ErrorEvent) and event.code == "iteration_timeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_large_tool_argument_stream_emits_progress_heartbeat() -> None:
    async def write_file_tool(call: object) -> ToolResult:
        return ToolResult(
            tool_use_id=getattr(call, "tool_use_id"),
            tool_name=getattr(call, "tool_name"),
            content="written",
        )

    provider = _ActiveLongToolArgumentProvider(
        fragment_delay=0.0,
        content="x" * 5000,
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(iteration_timeout=1.0, timeout=2.0, max_provider_retries=0),
        tool_definitions=[
            ToolDefinition(
                name="write_file",
                description="Write a file.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=write_file_tool,
    )

    events = await asyncio.wait_for(_collect_events(agent.run_turn("hello")), timeout=1.0)

    heartbeat_index = _event_index(
        events,
        lambda event: isinstance(event, RunHeartbeatEvent)
        and event.phase == "llm_tool_arguments"
        and "write_file" in (event.message or ""),
    )
    done_index = _event_index(events, lambda event: isinstance(event, DoneEvent))
    assert heartbeat_index < done_index


@pytest.mark.asyncio
async def test_iteration_timeout_caps_tool_execution() -> None:
    async def slow_tool(call: object) -> ToolResult:
        await asyncio.sleep(0.5)
        return ToolResult(
            tool_use_id=getattr(call, "tool_use_id"),
            tool_name=getattr(call, "tool_name"),
            content="late",
        )

    agent = Agent(
        provider=_ToolUseProvider(),
        config=AgentConfig(
            iteration_timeout=0.05,
            timeout=1.0,
            tool_timeout=5.0,
            max_provider_retries=0,
        ),
        tool_definitions=[
            ToolDefinition(
                name="slow",
                description="Slow tool.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=slow_tool,
    )

    events = await asyncio.wait_for(_collect_events(agent.run_turn("hello")), timeout=0.25)

    assert any(
        isinstance(event, ErrorEvent) and event.code == "iteration_timeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_provider_timeout_error_is_not_reclassified_as_iteration_timeout() -> None:
    provider = _ProviderRaisesTimeout()
    agent = Agent(
        provider=provider,
        config=AgentConfig(iteration_timeout=30.0, timeout=60.0, max_provider_retries=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "agent_runtime_timeout"
        for event in events
    )
    assert not any(
        isinstance(event, ErrorEvent) and event.code == "iteration_timeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_context_overflow_noop_compaction_does_not_resend_unchanged_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _noop_compact)
    provider = _ContextOverflowProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "compaction_not_smaller"
        for event in events
    )
    assert not any(getattr(event, "kind", None) == "compaction" for event in events)


@pytest.mark.asyncio
async def test_context_overflow_summary_only_larger_payload_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _summary_only_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="summary without reducing request payload",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _summary_only_compact)
    provider = _ContextOverflowProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "compaction_not_smaller"
        for event in events
    )
    assert not any(getattr(event, "kind", None) == "compaction" for event in events)


@pytest.mark.asyncio
async def test_context_overflow_effective_compaction_allows_single_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert len(provider.calls) == 2
    assert _provider_payload_is_smaller(provider.calls[0], provider.calls[1])
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)


@pytest.mark.asyncio
async def test_inline_overflow_uses_live_context_not_cumulative_provider_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    provider = _HighUsageToolLoopProvider(tool_rounds=3, input_tokens_per_call=4000)
    flush_calls: list[int] = []
    compact_requests: list[Any] = []

    async def _tool(call: Any) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="ok",
        )

    async def _flush(_plan: Any, flush_messages: list[Message]) -> Any:
        flush_calls.append(len(flush_messages))
        return SimpleNamespace(
            mode="llm",
            indexed_chunk_count=1,
            integrity_status="ok",
            output_coverage_status="ok",
            invalid_candidate_count=0,
            candidate_missing_ids=[],
            obligation_status="ok",
            obligation_missing_ids=[],
        )

    async def _compact(request: Any) -> CompactionResult:
        compact_requests.append(request)
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=20_000,
            context_overflow_threshold=0.5,
            flush_enabled=True,
            flush_pre_compaction=True,
            flush_timeout_seconds=0.01,
            max_iterations=10,
        ),
        tool_handler=_tool,
    )
    monkeypatch.setattr(agent, "_run_flush", _flush)
    monkeypatch.setattr(agent_module, "compact_context", _compact)

    events = [event async for event in agent.run_turn("read the files one by one")]

    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.text == "done"
    assert done.input_tokens == 16_000
    assert len(provider.calls) == 4
    assert flush_calls == []
    assert compact_requests == []


@pytest.mark.asyncio
async def test_inline_overflow_still_triggers_for_large_live_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    provider = _HighUsageToolLoopProvider(tool_rounds=0, input_tokens_per_call=1)
    large_tool = ToolDefinition(
        name="large_context_tool",
        description="large live request surface " + ("z" * 6000),
        input_schema=ToolInputSchema(),
    )
    flush_calls: list[int] = []
    compact_requests: list[Any] = []

    async def _flush(_plan: Any, flush_messages: list[Message]) -> Any:
        flush_calls.append(len(flush_messages))
        return SimpleNamespace(
            mode="llm",
            indexed_chunk_count=1,
            integrity_status="ok",
            output_coverage_status="ok",
            invalid_candidate_count=0,
            candidate_missing_ids=[],
            obligation_status="ok",
            obligation_missing_ids=[],
        )

    async def _compact(request: Any) -> CompactionResult:
        compact_requests.append(request)
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=3000,
            context_overflow_threshold=0.5,
            flush_enabled=True,
            flush_pre_compaction=True,
            flush_timeout_seconds=0.01,
            system_prompt="live request system context " + ("s" * 2000),
        ),
        tool_definitions=[large_tool],
    )
    monkeypatch.setattr(agent, "_run_flush", _flush)
    monkeypatch.setattr(agent_module, "compact_context", _compact)

    events = [event async for event in agent.run_turn("hello")]

    assert any(isinstance(event, DoneEvent) for event in events)
    assert len(provider.calls) == 1
    assert flush_calls == [1]
    assert len(compact_requests) == 1


@pytest.mark.asyncio
async def test_inline_overflow_flush_enabled_without_trigger_skips_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    provider = _HighUsageToolLoopProvider(tool_rounds=0, input_tokens_per_call=1)
    flush_calls: list[int] = []
    compact_requests: list[Any] = []

    async def _flush(_plan: Any, flush_messages: list[Message]) -> Any:
        flush_calls.append(len(flush_messages))

    async def _compact(request: Any) -> CompactionResult:
        compact_requests.append(request)
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=3000,
            context_overflow_threshold=0.5,
            flush_enabled=True,
            flush_pre_compaction=False,
            system_prompt="live request system context " + ("s" * 2000),
        ),
        tool_definitions=[
            ToolDefinition(
                name="large_context_tool",
                description="large live request surface " + ("z" * 6000),
                input_schema=ToolInputSchema(),
            )
        ],
    )
    monkeypatch.setattr(agent, "_run_flush", _flush)
    monkeypatch.setattr(agent_module, "compact_context", _compact)

    events = [event async for event in agent.run_turn("hello")]

    assert any(isinstance(event, DoneEvent) for event in events)
    assert flush_calls == []
    assert len(compact_requests) == 1


@pytest.mark.asyncio
async def test_provider_request_budget_exhausted_compacts_warns_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compaction_events: list[tuple[str, dict[str, Any]]] = []

    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    monkeypatch.setattr(
        "opensquilla.engine.agent.notify_compaction",
        lambda session_key, **payload: compaction_events.append((session_key, payload)),
    )
    provider = _ProviderRequestBudgetExceededProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
        session_key="agent:main:budget",
    )

    events = [event async for event in agent.run_turn("x" * 4000)]
    warning_codes = [
        event.code for event in events if isinstance(event, WarningEvent)
    ]

    assert len(provider.calls) == 2
    assert _provider_payload_is_smaller(provider.calls[0], provider.calls[1])
    assert warning_codes == [
        "context_auto_compaction_start",
        "context_auto_compaction_retry",
    ]
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code == "provider_request_budget_exhausted"
        for event in events
    )
    assert [(key, payload["status"]) for key, payload in compaction_events] == [
        ("agent:main:budget", "started"),
        ("agent:main:budget", "observed"),
        ("agent:main:budget", "observed"),
    ]
    compaction_ids = {payload.get("compaction_id") for _, payload in compaction_events}
    assert len(compaction_ids) == 1
    assert None not in compaction_ids
    assert [payload["event"] for _, payload in compaction_events] == [
        "compaction.triggered",
        "compaction.chunk_summarized",
        "compaction.summary_verified",
    ]


@pytest.mark.asyncio
async def test_provider_request_budget_uses_provider_window_for_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compaction_windows: list[int] = []

    async def _effective_compact(request: Any) -> CompactionResult:
        compaction_windows.append(request.context_window_tokens)
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ProviderRequestBudgetExceededProvider(
        success_after=1,
        proof={
            "fallback_reason": "provider_request_budget_exhausted",
            "estimated_chars": 109_055,
            "estimated_tokens": 27_263,
            "proof_budget": 96_000,
            "recent_tail_too_large": True,
        },
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=1_048_576,
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert compaction_windows
    assert compaction_windows[0] < 100_000
    assert len(provider.calls) == 2
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)


@pytest.mark.asyncio
async def test_provider_request_budget_retry_payload_is_rechecked_against_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compaction_windows: list[int] = []

    async def _effective_compact(request: Any) -> CompactionResult:
        compaction_windows.append(request.context_window_tokens)
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _BudgetCheckingProvider(proof_budget=2_500)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=1_048_576,
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert [proof["fits"] for proof in provider.proofs] == [False, True]
    assert compaction_windows
    assert compaction_windows[0] < agent.config.context_window_tokens
    assert len(provider.calls) == 2
    assert provider.proofs[1]["estimated_chars"] <= provider.proof_budget
    assert session_payload_chars(provider.calls[1]) < provider.proof_budget
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)


@pytest.mark.asyncio
async def test_provider_budget_retry_uses_effective_proof_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compaction_windows: list[int] = []

    async def _record_compaction_window(request: Any) -> CompactionResult:
        compaction_windows.append(request.context_window_tokens)
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _record_compaction_window)
    provider = _ProviderRequestBudgetExceededProvider(
        success_after=1,
        proof={
            "fallback_reason": "provider_request_budget_exhausted",
            "estimated_chars": 100_000,
            "estimated_tokens": 25_000,
            "proof_budget": 96_000,
            "raw_proof_budget": 96_000,
            "effective_proof_budget": 86_400,
            "proof_headroom_chars": 9_600,
            "recent_tail_too_large": False,
        },
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=1_048_576,
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert compaction_windows == [21_600]
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)


@pytest.mark.asyncio
async def test_provider_request_budget_recent_tail_reason_survives_noop_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _noop_compact)
    provider = _ProviderRequestBudgetExceededProvider(
        proof={
            "fallback_reason": "provider_request_budget_exhausted",
            "estimated_chars": 109_055,
            "estimated_tokens": 27_263,
            "proof_budget": 96_000,
            "recent_tail_too_large": True,
        },
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=1_048_576,
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]
    errors = [event for event in events if isinstance(event, ErrorEvent)]

    assert len(provider.calls) == 1
    assert errors[-1].code == "provider_request_too_large"
    assert RAW_CURRENT_TURN_OVERFLOW_MESSAGE not in errors[-1].message
    assert not any(
        isinstance(event, ErrorEvent) and event.code == "compaction_not_smaller"
        for event in events
    )


@pytest.mark.asyncio
async def test_provider_request_budget_recent_tail_exhaustion_is_reported_as_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ProviderRequestBudgetExceededProvider(
        proof={
            "fallback_reason": "provider_request_budget_exhausted",
            "recent_tail_too_large": True,
            "estimated_chars": 100_000,
            "proof_budget": 96_000,
        }
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=1,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]
    errors = [event for event in events if isinstance(event, ErrorEvent)]

    assert len(provider.calls) == 2
    assert errors[-1].code == "provider_request_too_large"
    assert "current turn" not in errors[-1].message.lower()
    assert RAW_CURRENT_TURN_OVERFLOW_MESSAGE not in errors[-1].message


@pytest.mark.asyncio
async def test_context_overflow_degraded_flush_still_runs_live_compaction_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compact_called = False

    async def _compact_runs_after_degraded_flush(request: Any) -> CompactionResult:
        nonlocal compact_called
        compact_called = True
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr(
        "opensquilla.engine.agent.compact_context",
        _compact_runs_after_degraded_flush,
    )
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_provider_retries=0, max_overflow_retries=2),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert compact_called is True
    assert len(provider.calls) == 2
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code in {"compaction_refused_memory_flush", "compaction_refused_flush_timeout"}
        for event in events
    )


@pytest.mark.asyncio
async def test_context_overflow_flush_timeout_records_backoff_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _compact_runs_after_flush_timeout(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr(
        "opensquilla.engine.agent.compact_context",
        _compact_runs_after_flush_timeout,
    )
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=True,
            flush_pre_compaction=True,
            flush_timeout_seconds=0.01,
            flush_backoff_initial_seconds=10.0,
        ),
    )

    async def slow_flush(_plan: Any, _messages: Any) -> None:
        await asyncio.sleep(1.0)

    monkeypatch.setattr(agent, "_run_flush", slow_flush)
    try:
        events = [event async for event in agent.run_turn("x" * 4000)]
    finally:
        task = agent._active_flush_task
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert len(provider.calls) == 2
    assert agent._flush_backoff_seconds == 10.0
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code in {"compaction_refused_memory_flush", "compaction_refused_flush_timeout"}
        for event in events
    )


async def _collect_events(stream: AsyncIterator[Any]) -> list[Any]:
    return [event async for event in stream]


def _event_index(events: list[Any], predicate: Any) -> int:
    return next(index for index, event in enumerate(events) if predicate(event))


def _provider_payload_is_smaller(before: list[Message], after: list[Message]) -> bool:
    return len(after) < len(before) or session_payload_chars(after) < session_payload_chars(before)
