"""Phase 1 — RouterDecisionEvent: ensure the event helper extracts the
post-pipeline router metadata into a stable shape that the WebUI HUD can
consume."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.router_decision import build_router_decision_event
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.types import RouterDecisionEvent
from opensquilla.provider import DoneEvent, Message, ModelInfo, TextDeltaEvent
from opensquilla.tools.types import CallerKind, ToolContext


def _ctx(metadata: dict, model: str = "") -> TurnContext:
    return TurnContext(
        message="hi",
        session_key="agent:main:webchat:abc",
        config=SimpleNamespace(),
        provider=None,
        model=model,
        tool_defs=[],
        system_prompt="",
        metadata=metadata,
    )


def test_returns_none_when_router_did_not_fire() -> None:
    assert build_router_decision_event(_ctx({})) is None


def test_returns_none_when_routed_tier_empty_string() -> None:
    assert build_router_decision_event(_ctx({"routed_tier": ""})) is None


def test_full_router_metadata_populates_all_event_fields() -> None:
    metadata = {
        "routed_tier": "c2",
        "routed_model": "claude-sonnet-4.6",
        "baseline_model": "claude-opus-4.7",
        "routing_source": "router",
        "routing_confidence": 0.71,
        "savings_pct": 64.0,
        "thinking_mode": "balanced",
        "prompt_policy": "default",
        "routing_extra": {
            "probabilities": {"R0": 0.12, "R1": 0.71, "R2": 0.14, "R3": 0.03},
        },
    }
    event = build_router_decision_event(_ctx(metadata))
    assert isinstance(event, RouterDecisionEvent)
    assert event.kind == "router_decision"
    assert event.tier == "c2"
    assert event.tier_index == 2
    assert event.model == "claude-sonnet-4.6"
    assert event.baseline_model == "claude-opus-4.7"
    assert event.source == "router"
    assert event.confidence == 0.71
    assert event.probs == [0.12, 0.71, 0.14, 0.03]
    assert event.savings_pct == 64.0
    assert event.fallback is False
    assert event.thinking_mode == "balanced"
    assert event.prompt_policy == "default"


def test_legacy_router_probability_and_savings_keys_still_work() -> None:
    event = build_router_decision_event(
        _ctx(
            {
                "routed_tier": "c2",
                "routing_extra": {
                    "probs": [0.12, 0.71, 0.14, 0.03],
                    "tier_savings": {"pct": 64.0},
                },
            }
        )
    )
    assert event is not None
    assert event.probs == [0.12, 0.71, 0.14, 0.03]
    assert event.savings_pct == 64.0


def test_falls_back_to_turn_model_when_routed_model_absent() -> None:
    event = build_router_decision_event(
        _ctx({"routed_tier": "c1"}, model="deepseek-v4-flash")
    )
    assert event is not None
    assert event.model == "deepseek-v4-flash"
    assert event.source == "none"
    assert event.probs == []
    assert event.fallback is False


def test_fallback_source_sets_fallback_flag() -> None:
    event = build_router_decision_event(
        _ctx({"routed_tier": "c2", "routed_model": "x", "routing_source": "fallback"})
    )
    assert event is not None
    assert event.fallback is True
    assert event.source == "fallback"


def test_malformed_probs_do_not_crash() -> None:
    event = build_router_decision_event(
        _ctx(
            {
                "routed_tier": "c3",
                "routed_model": "claude-opus-4.7",
                "routing_extra": {"probs": ["bad", None, 0.5, "x"]},
            }
        )
    )
    assert event is not None
    assert event.probs == [0.0, 0.0, 0.5, 0.0]


def test_unknown_tier_string_results_in_negative_tier_index() -> None:
    event = build_router_decision_event(
        _ctx({"routed_tier": "image", "routed_model": "gemini-3.5-pro"})
    )
    assert event is not None
    assert event.tier == "image"
    assert event.tier_index == -1


def test_tier_index_maps_naturally_so_c0_and_c1_dont_collide() -> None:
    # Regression: an earlier max(0, int(...) - 1) collapsed both c0
    # and c1 onto index 0. The natural mapping puts c0 at 0, c1 at 1,
    # and so on.
    t0_event = build_router_decision_event(
        _ctx({"routed_tier": "c0", "routed_model": "deepseek-v4-flash"})
    )
    t1_event = build_router_decision_event(
        _ctx({"routed_tier": "c1", "routed_model": "claude-sonnet-4.6"})
    )
    t3_event = build_router_decision_event(
        _ctx({"routed_tier": "c3", "routed_model": "claude-opus-4.7"})
    )
    assert t0_event is not None and t0_event.tier_index == 0
    assert t1_event is not None and t1_event.tier_index == 1
    assert t3_event is not None and t3_event.tier_index == 3


def test_routing_applied_and_rollout_phase_round_trip() -> None:
    # observe-mode rollout: the router classifies but the routed
    # model is NOT swapped in. Frontend uses this to dim the strip.
    observe_event = build_router_decision_event(
        _ctx(
            {
                "routed_tier": "c2",
                "routed_model": "claude-sonnet-4.6",
                "routing_applied": False,
                "rollout_phase": "observe",
            }
        )
    )
    assert observe_event is not None
    assert observe_event.routing_applied is False
    assert observe_event.rollout_phase == "observe"

    # full rollout: routing actually swapped in.
    full_event = build_router_decision_event(
        _ctx(
            {
                "routed_tier": "c2",
                "routed_model": "claude-sonnet-4.6",
                "routing_applied": True,
                "rollout_phase": "full",
            }
        )
    )
    assert full_event is not None
    assert full_event.routing_applied is True
    assert full_event.rollout_phase == "full"


def test_legacy_metadata_without_routing_applied_defaults_to_applied() -> None:
    # Older transcripts predate the routing_applied/rollout_phase
    # metadata fields. The event helper must fall back to applied=True
    # + rollout_phase="full" so historic strips keep rendering normally.
    event = build_router_decision_event(
        _ctx({"routed_tier": "c2", "routed_model": "claude-sonnet-4.6"})
    )
    assert event is not None
    assert event.routing_applied is True
    assert event.rollout_phase == "full"


class _DoneProvider:
    async def chat(
        self,
        messages: list[Message],
        tools=None,
        config=None,
    ) -> AsyncIterator[object]:
        yield TextDeltaEvent(text="ok")
        yield DoneEvent(model="routed-model", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[ModelInfo]:
        return []


class _Selector:
    current_config = SimpleNamespace(model="base-model")

    def clone(self) -> _Selector:
        return self

    def override_model(self, model: str) -> None:
        self.current_config = SimpleNamespace(model=model)

    def resolve(self) -> _DoneProvider:
        return _DoneProvider()


@pytest.mark.asyncio
async def test_turn_runner_emits_router_decision_event_from_pipeline_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def routed_pipeline(
        self: TurnRunner,
        message: str,
        session_key: str,
        provider: Any,
        cloned_selector: Any,
        tool_defs: list[Any],
        base_prompt: str | tuple[str, str],
        attachments: list[dict[str, Any]],
        **_: Any,
    ) -> tuple[TurnContext, Any]:
        return (
            TurnContext(
                message=message,
                session_key=session_key,
                config=self._config,
                provider=provider,
                model="routed-model",
                tool_defs=tool_defs,
                system_prompt=base_prompt,
                attachments=attachments,
                metadata={
                    "routed_tier": "c2",
                    "routed_model": "routed-model",
                    "routing_source": "router",
                    "routing_confidence": 0.8,
                },
            ),
            provider,
        )

    monkeypatch.setattr(TurnRunner, "_run_pipeline", routed_pipeline)
    runner = TurnRunner(provider_selector=_Selector())

    events = [
        event
        async for event in runner.run(
            "hi",
            "agent:main:router-e2e",
            tool_context=ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
            history_has_persisted_user=False,
            no_memory_capture=True,
        )
    ]

    router_events = [event for event in events if isinstance(event, RouterDecisionEvent)]
    assert len(router_events) == 1
    assert router_events[0].tier == "c2"
    assert router_events[0].model == "routed-model"
