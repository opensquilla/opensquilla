"""Characterization matrix: provider calls a tool absent from the offered schema.

Multi-provider per-turn routing makes "history or model references a tool that
this turn's narrowed schema does not offer" a normal condition, not an attack.
"Absent from the offered tool_definitions" is THREE distinct behaviors at the
dispatch layer, and these tests pin each fork as it behaves today:

(i)   absent because ToolContext policy denied it -> dispatch policy chain
      denies (PolicyDenied envelope), the handler never runs;
(ii)  absent because schema-budget/toolset fit dropped it (registered and
      ctx-allowed, just not advertised) -> dispatch EXECUTES it; there is no
      execution-side restriction to the offered schema;
(iii) tools unsupported for the call (model capability gate) -> tool events
      are dropped pre-dispatch, nothing reaches the handler.

Unknown names (in neither registry nor schema) produce a mid-turn error
receipt whose verbosity depends on caller trust, and the turn still completes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine import (
    Agent,
    AgentConfig,
    DoneEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.engine.runtime import TurnRunner
from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig, ToolsConfig
from opensquilla.provider import ChatConfig, ModelCapabilities
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolStart
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, ToolContext, ToolSpec


class _ForeignToolCallProvider:
    provider_name = "test"

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.calls: list[str] = []
        self.offered_tools: list[list[str]] = []
        self.model = "base-model"

    def chat(
        self,
        messages: list[Any],
        tools=None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(self.model)
        self.offered_tools.append([tool.name for tool in tools or []])
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderText(text="attempting tool")
            yield ProviderToolStart(tool_use_id="tool-1", tool_name=self.tool_name)
            yield ProviderToolEnd(
                tool_use_id="tool-1",
                tool_name=self.tool_name,
                arguments={},
            )
            yield ProviderDone(stop_reason="tool_calls", input_tokens=1, output_tokens=1)
            return
        yield ProviderText(text="final answer")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _SelectorClone:
    def __init__(self, provider: _ForeignToolCallProvider) -> None:
        self.provider = provider
        self.current_config = SimpleNamespace(model=provider.model)

    def override_model(self, model: str) -> None:
        self.current_config = SimpleNamespace(model=model)
        self.provider.model = model

    def resolve(self) -> _ForeignToolCallProvider:
        return self.provider


class _Selector:
    def __init__(self, provider: _ForeignToolCallProvider) -> None:
        self.provider = provider

    def clone(self) -> _SelectorClone:
        return _SelectorClone(self.provider)


def _stub_registry(ran: list[str]) -> ToolRegistry:
    registry = ToolRegistry()

    async def _tool_x() -> str:
        ran.append("tool_x")
        return "tool_x ran"

    async def _tool_y() -> str:
        ran.append("tool_y")
        return "tool_y ran"

    registry.register(
        ToolSpec(name="tool_x", description="Harmless read-only stub X.", parameters={}),
        _tool_x,
    )
    registry.register(
        ToolSpec(name="tool_y", description="Harmless read-only stub Y.", parameters={}),
        _tool_y,
    )
    return registry


def _tool_results(events: list[Any]) -> list[Any]:
    return [event for event in events if getattr(event, "kind", None) == "tool_result"]


async def _run_turn(
    runner: TurnRunner,
    session_key: str,
    tool_context: ToolContext,
) -> list[Any]:
    return [
        event
        async for event in runner.run(
            "go",
            session_key,
            tool_context=tool_context,
            history_has_persisted_user=False,
            no_memory_capture=True,
        )
    ]


@pytest.mark.asyncio
async def test_registered_but_unoffered_tool_still_executes() -> None:
    """Fork (ii): toolset fit narrows the offer, dispatch still executes."""
    ran: list[str] = []
    provider = _ForeignToolCallProvider("tool_x")
    cfg = GatewayConfig(
        llm=LlmProviderConfig(toolset="lite"),
        tools=ToolsConfig(toolsets={"lite": ["tool_y"]}),
    )
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=_stub_registry(ran),
        config=cfg,
    )

    events = await _run_turn(
        runner,
        "agent:main:foreign-tool-unoffered-executes",
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
    )

    results = _tool_results(events)
    assert provider.offered_tools[0] == ["tool_y"]
    assert ran == ["tool_x"]
    assert len(results) == 1
    assert results[0].is_error is False
    assert "tool_x ran" in results[0].result
    assert any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_unknown_tool_name_gets_descriptive_receipt_for_cli_owner() -> None:
    """Unknown name, trusted caller: ToolNotFound receipt names the tool."""
    ran: list[str] = []
    provider = _ForeignToolCallProvider("definitely_not_a_tool")
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=_stub_registry(ran),
        config=GatewayConfig(),
    )

    events = await _run_turn(
        runner,
        "agent:main:foreign-tool-unknown-cli",
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
    )

    results = _tool_results(events)
    assert ran == []
    assert len(results) == 1
    assert results[0].is_error is True
    payload = json.loads(results[0].result)
    assert payload["error_class"] == "ToolNotFound"
    assert payload["tool"] == "definitely_not_a_tool"
    assert "Tool not found: definitely_not_a_tool" in payload["user_message"]
    assert any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_unknown_tool_name_gets_opaque_receipt_for_channel_non_owner() -> None:
    """Unknown name, untrusted CHANNEL caller: opaque PolicyDenied receipt."""
    ran: list[str] = []
    provider = _ForeignToolCallProvider("definitely_not_a_tool")
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=_stub_registry(ran),
        config=GatewayConfig(),
    )

    events = await _run_turn(
        runner,
        "agent:main:foreign-tool-unknown-channel",
        ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL),
    )

    results = _tool_results(events)
    assert ran == []
    assert len(results) == 1
    assert results[0].is_error is True
    payload = json.loads(results[0].result)
    assert payload["error_class"] == "PolicyDenied"
    assert payload["user_message"] == "Tool unavailable for this surface."
    # Characterization: the opaque envelope hides the probed name from the
    # user_message, but the structured "tool" field still echoes it today.
    assert payload["tool"] == "definitely_not_a_tool"
    assert any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_ctx_denied_tool_gets_policy_denied_and_handler_never_runs() -> None:
    """Fork (i): ctx policy denial -> PolicyDenied receipt, no execution."""
    ran: list[str] = []
    provider = _ForeignToolCallProvider("tool_x")
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=_stub_registry(ran),
        config=GatewayConfig(),
    )

    events = await _run_turn(
        runner,
        "agent:main:foreign-tool-ctx-denied",
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            denied_tools={"tool_x"},
        ),
    )

    results = _tool_results(events)
    assert provider.offered_tools[0] == ["tool_y"]
    assert ran == []
    assert len(results) == 1
    assert results[0].is_error is True
    payload = json.loads(results[0].result)
    assert payload["error_class"] == "PolicyDenied"
    assert payload["tool"] == "tool_x"
    assert any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_capability_gated_model_drops_tool_events_pre_dispatch() -> None:
    """Fork (iii): tools_supported_for_call=False drops events before dispatch."""
    ran: list[str] = []
    registry = _stub_registry(ran)
    ctx = ToolContext(is_owner=True, caller_kind=CallerKind.CLI)
    provider = _ForeignToolCallProvider("tool_x")
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            model_capabilities=ModelCapabilities(
                supports_tools=False,
                tool_support_state="unsupported",
            ),
            flush_enabled=False,
        ),
        tool_definitions=registry.to_tool_definitions(ctx),
        tool_handler=build_tool_handler(registry, ctx),
    )

    events = [event async for event in agent.run_turn("go")]

    assert ran == []
    assert provider.offered_tools[0] == []
    assert not any(isinstance(event, ToolUseStartEvent) for event in events)
    assert not any(isinstance(event, ToolResultEvent) for event in events)
    assert any(isinstance(event, DoneEvent) for event in events)
