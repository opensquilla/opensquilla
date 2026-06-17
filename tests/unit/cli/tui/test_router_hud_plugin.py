from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.cli.chat.turn_stream import (
    default_turn_stream_dependencies,
    stream_response_gateway,
    stream_response_turnrunner,
)
from opensquilla.cli.tui.adapters.turn_stream_defaults import router_hud_event_sink_factory
from opensquilla.cli.tui.backend.domain_events import (
    KIND_DONE,
    KIND_ROUTER_DECISION,
    KIND_TEXT_FLUSH,
    TuiDomainEvent,
    now_ms,
)
from opensquilla.cli.tui.backend.plugins import TuiPluginManager
from opensquilla.cli.tui.plugins.router_hud import (
    ROUTER_HUD_SLOT,
    RouterHudPlugin,
    RouterHudSnapshot,
)
from opensquilla.engine.types import DoneEvent, RouterDecisionEvent
from opensquilla.tools.types import CallerKind, ToolContext

ROUTER_PAYLOAD: dict[str, object] = {
    "tier": "t2",
    "tier_index": 2,
    "model": "anthropic/claude-sonnet-4.6",
    "baseline_model": "anthropic/claude-opus-4.7",
    "source": "router",
    "confidence": 0.71,
    "probs": [0.1, 0.2, 0.7],
    "savings_pct": 64.0,
    "fallback": False,
    "thinking_mode": "balanced",
    "prompt_policy": "default",
    "routing_applied": True,
    "rollout_phase": "full",
    "context_window": 200_000,
}


class _GatewayClient:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def send_message(self, *_args: Any, **_kwargs: Any):
        for event in self._events:
            yield event

    async def resolve_approval(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def abort_session(self, _key: str) -> None:
        return None


class _TurnRunner:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    async def run(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
        for event in self._events:
            yield event


def _router_event(payload: dict[str, object]) -> TuiDomainEvent:
    return TuiDomainEvent(
        kind=KIND_ROUTER_DECISION,
        source="gateway",
        payload=payload,
        turn_id="agent:main:test",
        timestamp_ms=now_ms(),
    )


def _snapshot_for(payload: dict[str, object]) -> RouterHudSnapshot:
    plugin = RouterHudPlugin()
    plugin.on_event(_router_event(payload), context=object())
    snapshot = plugin.snapshot(ROUTER_HUD_SLOT)
    assert isinstance(snapshot, RouterHudSnapshot)
    return snapshot


@pytest.mark.asyncio
async def test_gateway_stream_surfaces_normalized_router_decision_domain_event() -> None:
    events: list[TuiDomainEvent] = []
    deps = default_turn_stream_dependencies(tui_event_sink=events.append)

    await stream_response_gateway(
        _GatewayClient(
            [
                {"event": "session.event.router_decision", **ROUTER_PAYLOAD},
                {"event": "session.event.done", "model": "anthropic/claude-sonnet-4.6"},
            ]
        ),
        "agent:main:test",
        "hello",
        deps=deps,
    )

    assert [event.kind for event in events] == [KIND_ROUTER_DECISION, KIND_DONE]
    assert events[0].source == "gateway"
    assert events[0].payload == ROUTER_PAYLOAD


@pytest.mark.asyncio
async def test_turnrunner_stream_surfaces_matching_router_decision_domain_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_event = RouterDecisionEvent(**ROUTER_PAYLOAD)
    turn_runner = _TurnRunner([router_event, DoneEvent(model="anthropic/claude-sonnet-4.6")])
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
        turn_runner,
        "agent:main:test",
        tool_ctx,
        "hello",
        deps=deps,
    )

    assert [event.kind for event in events] == [KIND_ROUTER_DECISION, KIND_DONE]
    assert events[0].source == "turn_runner"
    assert events[0].payload == ROUTER_PAYLOAD


def test_router_hud_formats_full_route_label_and_snapshot_fields() -> None:
    snapshot = _snapshot_for(ROUTER_PAYLOAD)

    assert snapshot.tier == "t2"
    assert snapshot.tier_index == 2
    assert snapshot.model == "anthropic/claude-sonnet-4.6"
    assert snapshot.baseline_model == "anthropic/claude-opus-4.7"
    assert snapshot.confidence == 0.71
    assert snapshot.savings_pct == 64.0
    assert snapshot.label == "route t2 -> claude-sonnet-4.6 71% save 64%"
    assert snapshot.style == "normal"


def test_router_hud_uses_natural_tier_indexes_and_observe_style() -> None:
    payload = {
        **ROUTER_PAYLOAD,
        "tier": "t1",
        "tier_index": None,
        "routing_applied": False,
        "rollout_phase": "observe",
    }

    snapshot = _snapshot_for(payload)

    assert snapshot.tier_index == 1
    assert snapshot.label == "observe t1 -> claude-sonnet-4.6 71%"
    assert snapshot.style == "dim"


def test_router_hud_highlights_fallback_routes() -> None:
    snapshot = _snapshot_for(
        {
            **ROUTER_PAYLOAD,
            "source": "fallback",
            "fallback": True,
            "savings_pct": 0.0,
        }
    )

    assert snapshot.fallback is True
    assert snapshot.label == "fallback -> claude-sonnet-4.6"
    assert snapshot.style == "warning"


def test_router_hud_formats_forced_and_no_baseline_without_savings() -> None:
    snapshot = _snapshot_for(
        {
            **ROUTER_PAYLOAD,
            "tier": "t0",
            "tier_index": 0,
            "source": "forced",
            "baseline_model": "",
            "savings_pct": 64.0,
        }
    )

    assert snapshot.tier_index == 0
    assert snapshot.label == "forced t0 -> claude-sonnet-4.6 71%"
    assert "save" not in snapshot.label


def test_router_hud_omits_malformed_confidence() -> None:
    snapshot = _snapshot_for(
        {
            **ROUTER_PAYLOAD,
            "confidence": "not-a-number",
            "savings_pct": "also-bad",
        }
    )

    assert snapshot.confidence is None
    assert snapshot.savings_pct is None
    assert snapshot.label == "route t2 -> claude-sonnet-4.6"


def test_opentui_router_sink_updates_toolbar_only_for_router_events() -> None:
    class _Output:
        def __init__(self) -> None:
            self.updates: list[tuple[str, object | None]] = []
            self.invalidations = 0

        def set_toolbar(self, key: str, value: object | None) -> None:
            self.updates.append((key, value))

        def invalidate(self) -> None:
            self.invalidations += 1

    output = _Output()
    sink = router_hud_event_sink_factory(output)

    sink(_router_event(ROUTER_PAYLOAD))
    after_router = list(output.updates)
    sink(
        TuiDomainEvent(
            kind=KIND_TEXT_FLUSH,
            source="renderer",
            payload={"text": "hello"},
            turn_id="agent:main:test",
            timestamp_ms=now_ms(),
        )
    )

    assert ("router_hud", "route t2 -> claude-sonnet-4.6 71% save 64%") in after_router
    assert ("router_hud_style", "normal") in after_router
    assert output.updates == after_router
    assert output.invalidations == 1


def test_opentui_router_sink_writes_context_window_from_payload() -> None:
    class _Output:
        def __init__(self) -> None:
            self.updates: list[tuple[str, object | None]] = []

        def set_toolbar(self, key: str, value: object | None) -> None:
            self.updates.append((key, value))

        def invalidate(self) -> None:
            return None

    output = _Output()
    sink = router_hud_event_sink_factory(output)

    sink(_router_event({**ROUTER_PAYLOAD, "context_window": 1_000_000}))

    assert ("router_context_window", 1_000_000) in output.updates


def test_opentui_router_sink_reuses_launch_scoped_plugin_manager() -> None:
    class _Output:
        def __init__(self, plugin_manager: TuiPluginManager) -> None:
            self.plugin_manager = plugin_manager
            self.updates: list[tuple[str, object | None]] = []

        def set_toolbar(self, key: str, value: object | None) -> None:
            self.updates.append((key, value))

        def invalidate(self) -> None:
            return None

    manager = TuiPluginManager([RouterHudPlugin()])
    output = _Output(manager)
    sink = router_hud_event_sink_factory(output)

    sink(_router_event(ROUTER_PAYLOAD))

    snapshot = manager.snapshot(ROUTER_HUD_SLOT)
    assert isinstance(snapshot, RouterHudSnapshot)
    assert snapshot.label == "route t2 -> claude-sonnet-4.6 71% save 64%"
    assert ("router_hud", snapshot.label) in output.updates
