from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from opensquilla.cli.chat.turn_stream import (
    default_turn_stream_dependencies,
    stream_response_gateway,
    stream_response_turnrunner,
)
from opensquilla.cli.tui.backend.domain_events import (
    KIND_DONE,
    KIND_STATUS,
    KIND_TEXT_FLUSH,
    KIND_TOOL_FINISHED,
    KIND_TOOL_STARTED,
    TuiDomainEvent,
    now_ms,
)
from opensquilla.cli.tui.backend.plugins import (
    TuiPluginContext,
    TuiPluginManager,
)
from opensquilla.engine.types import DoneEvent, ToolResultEvent, ToolUseStartEvent
from opensquilla.tools.types import CallerKind, ToolContext


@dataclass
class _RecordingPlugin:
    plugin_id: str
    slots: frozenset[str]
    value: object | None = None
    seen: list[str] = field(default_factory=list)
    fail: bool = False

    def on_event(self, event: TuiDomainEvent, context: TuiPluginContext) -> None:
        self.seen.append(event.kind)
        context.set_state(f"{self.plugin_id}:last", event.kind)
        if self.fail:
            raise RuntimeError("plugin exploded")

    def snapshot(self, slot: str) -> object | None:
        if slot not in self.slots:
            return None
        return self.value


class _GatewayClient:
    async def send_message(self, *_args: Any, **_kwargs: Any):
        yield {
            "event": "session.event.tool_use_start",
            "tool_name": "search",
            "tool_use_id": "tool-1",
            "input": {"query": "opensquilla"},
        }
        yield {
            "event": "session.event.tool_result",
            "tool_use_id": "tool-1",
            "result": "ok",
            "execution_status": {"status": "success"},
        }
        yield {"event": "session.event.text_delta", "text": "hidden from domain sink"}
        yield {"event": "session.event.done", "model": "openrouter/test"}

    async def resolve_approval(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def abort_session(self, _key: str) -> None:
        return None


class _TurnRunner:
    async def run(self, *_args: Any, **_kwargs: Any):
        yield ToolUseStartEvent(tool_use_id="tool-1", tool_name="search")
        yield ToolResultEvent(
            tool_use_id="tool-1",
            tool_name="search",
            result="ok",
            is_error=False,
        )
        yield DoneEvent(model="openrouter/test")


def test_domain_event_is_frozen_and_timestamped() -> None:
    event = TuiDomainEvent(
        kind=KIND_STATUS,
        source="runtime",
        payload={"message": "ready"},
        turn_id="turn-1",
        timestamp_ms=now_ms(),
    )

    assert event.kind == "status"
    assert event.payload["message"] == "ready"
    assert event.timestamp_ms > 0
    with pytest.raises(AttributeError):
        event.kind = "done"  # type: ignore[misc]


def test_plugin_manager_dispatches_in_priority_order_and_snapshots() -> None:
    low = _RecordingPlugin("low", frozenset({"status"}), value={"low": True})
    high = _RecordingPlugin("high", frozenset({"status"}), value={"high": True})
    manager = TuiPluginManager()
    manager.register(low, priority=0)
    manager.register(high, priority=10)
    event = TuiDomainEvent(
        kind=KIND_STATUS,
        source="runtime",
        payload={"message": "working"},
        turn_id=None,
        timestamp_ms=now_ms(),
    )

    manager.dispatch(event)

    assert [plugin.plugin_id for plugin in manager.plugins] == ["high", "low"]
    assert high.seen == [KIND_STATUS]
    assert low.seen == [KIND_STATUS]
    assert manager.snapshot("status") == {"high": True}
    assert manager.context.get_state("high:last") == KIND_STATUS


def test_plugin_manager_captures_plugin_errors_and_continues() -> None:
    failing = _RecordingPlugin("failing", frozenset({"status"}), fail=True)
    healthy = _RecordingPlugin("healthy", frozenset({"status"}), value="ok")
    manager = TuiPluginManager([failing, healthy])
    event = TuiDomainEvent(
        kind=KIND_STATUS,
        source="runtime",
        payload={"message": "working"},
        turn_id=None,
        timestamp_ms=now_ms(),
    )

    manager.dispatch(event)

    assert failing.seen == [KIND_STATUS]
    assert healthy.seen == [KIND_STATUS]
    assert manager.snapshot("status") == "ok"
    assert [(error.plugin_id, error.message) for error in manager.errors] == [
        ("failing", "plugin exploded")
    ]


@pytest.mark.asyncio
async def test_gateway_turn_stream_emits_tool_and_done_domain_events() -> None:
    events: list[TuiDomainEvent] = []
    deps = default_turn_stream_dependencies(tui_event_sink=events.append)

    await stream_response_gateway(
        _GatewayClient(),
        "agent:main:test",
        "hello",
        {"mode": None},
        deps=deps,
    )

    assert [event.kind for event in events] == [
        KIND_TOOL_STARTED,
        KIND_TOOL_FINISHED,
        KIND_TEXT_FLUSH,
        KIND_DONE,
    ]
    assert {event.source for event in events} == {"gateway"}
    assert events[0].payload["tool_name"] == "search"
    assert events[3].payload["model"] == "openrouter/test"


@pytest.mark.asyncio
async def test_turnrunner_stream_emits_matching_tool_and_done_domain_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", _TurnRunner)
    events: list[TuiDomainEvent] = []
    deps = default_turn_stream_dependencies(
        stream_wrapper=lambda stream, _svc: stream,
        tui_event_sink=events.append,
    )
    tool_ctx = ToolContext(
        caller_kind=CallerKind.CLI,
        channel_kind="cli",
        channel_id="cli:chat",
    )

    await stream_response_turnrunner(
        _TurnRunner(),
        "agent:main:test",
        tool_ctx,
        "hello",
        deps=deps,
    )

    assert [event.kind for event in events] == [
        KIND_TOOL_STARTED,
        KIND_TOOL_FINISHED,
        KIND_DONE,
    ]
    assert {event.source for event in events} == {"turn_runner"}
    assert events[0].payload["tool_name"] == "search"
    assert events[2].payload["model"] == "openrouter/test"
