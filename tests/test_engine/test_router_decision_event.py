"""Phase 1 — RouterDecisionEvent: ensure the event helper extracts the
post-pipeline router metadata into a stable shape that the WebUI HUD can
consume."""

from __future__ import annotations

from types import SimpleNamespace

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.runtime import _build_router_decision_event
from opensquilla.engine.types import RouterDecisionEvent


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
    assert _build_router_decision_event(_ctx({})) is None


def test_returns_none_when_routed_tier_empty_string() -> None:
    assert _build_router_decision_event(_ctx({"routed_tier": ""})) is None


def test_full_router_metadata_populates_all_event_fields() -> None:
    metadata = {
        "routed_tier": "t2",
        "routed_model": "claude-sonnet-4.6",
        "baseline_model": "claude-opus-4.7",
        "routing_source": "router",
        "routing_confidence": 0.71,
        "thinking_mode": "balanced",
        "prompt_policy": "default",
        "routing_extra": {
            "probs": [0.12, 0.71, 0.14, 0.03],
            "tier_savings": {"pct": 64.0},
        },
    }
    event = _build_router_decision_event(_ctx(metadata))
    assert isinstance(event, RouterDecisionEvent)
    assert event.kind == "router_decision"
    assert event.tier == "t2"
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


def test_falls_back_to_turn_model_when_routed_model_absent() -> None:
    event = _build_router_decision_event(
        _ctx({"routed_tier": "t1"}, model="deepseek-v4-flash")
    )
    assert event is not None
    assert event.model == "deepseek-v4-flash"
    assert event.source == "none"
    assert event.probs == []
    assert event.fallback is False


def test_fallback_source_sets_fallback_flag() -> None:
    event = _build_router_decision_event(
        _ctx({"routed_tier": "t2", "routed_model": "x", "routing_source": "fallback"})
    )
    assert event is not None
    assert event.fallback is True
    assert event.source == "fallback"


def test_malformed_probs_do_not_crash() -> None:
    event = _build_router_decision_event(
        _ctx(
            {
                "routed_tier": "t3",
                "routed_model": "claude-opus-4.7",
                "routing_extra": {"probs": ["bad", None, 0.5, "x"]},
            }
        )
    )
    assert event is not None
    assert event.probs == [0.0, 0.0, 0.5, 0.0]


def test_unknown_tier_string_results_in_negative_tier_index() -> None:
    event = _build_router_decision_event(
        _ctx({"routed_tier": "image", "routed_model": "gemini-3.5-pro"})
    )
    assert event is not None
    assert event.tier == "image"
    assert event.tier_index == -1


def test_tier_index_maps_naturally_so_t0_and_t1_dont_collide() -> None:
    # Regression: an earlier max(0, int(...) - 1) collapsed both t0
    # and t1 onto index 0. The natural mapping puts t0 at 0, t1 at 1,
    # and so on.
    t0_event = _build_router_decision_event(
        _ctx({"routed_tier": "t0", "routed_model": "deepseek-v4-flash"})
    )
    t1_event = _build_router_decision_event(
        _ctx({"routed_tier": "t1", "routed_model": "claude-sonnet-4.6"})
    )
    t3_event = _build_router_decision_event(
        _ctx({"routed_tier": "t3", "routed_model": "claude-opus-4.7"})
    )
    assert t0_event is not None and t0_event.tier_index == 0
    assert t1_event is not None and t1_event.tier_index == 1
    assert t3_event is not None and t3_event.tier_index == 3


def test_routing_applied_and_rollout_phase_round_trip() -> None:
    # observe-mode rollout: the router classifies but the routed
    # model is NOT swapped in. Frontend uses this to dim the strip.
    observe_event = _build_router_decision_event(
        _ctx(
            {
                "routed_tier": "t2",
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
    full_event = _build_router_decision_event(
        _ctx(
            {
                "routed_tier": "t2",
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
    event = _build_router_decision_event(
        _ctx({"routed_tier": "t2", "routed_model": "claude-sonnet-4.6"})
    )
    assert event is not None
    assert event.routing_applied is True
    assert event.rollout_phase == "full"
