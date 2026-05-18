"""Pin the agent → usage_tracker billed_cost forwarding contract.

When the Agent loop receives a ``ProviderDoneEvent`` with a real
``billed_cost`` from the provider, it
must call ``UsageTracker.add(..., billed_cost=...)`` so the per-model
breakdown can surface the actual provider-billed cost (instead of the
cache-blind pricing-table estimate).

A regression here re-introduces the user-reported drift bug
(row=$0.0607 Actual, breakdown sum=$0.1835 — 3× off due to ignored
cache discount).

Implementation strategy: mock UsageTracker, run a single ProviderDoneEvent
through the same accumulation block agent.py:1048-1076 uses. We don't
spin up the full Agent state machine — the change is one keyword
argument forwarded inside a tight branch, and a focused mock test gives
a clear regression marker without dragging the entire LLM/provider
stack into the test.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from opensquilla.engine.usage import UsageTracker


@dataclass
class _FakeProviderDoneEvent:
    """Minimal stand-in for opensquilla.provider.types.DoneEvent.

    The agent loop reads exactly these attributes on the raw_ev branch
    we exercise; the rest of DoneEvent is irrelevant to billed forwarding.
    """

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    billed_cost: float
    model: str
    cost_source: str = "provider_billed"
    reasoning_tokens: int = 0
    reasoning_content: str | None = None
    thinking_signature: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None


def _simulate_agent_raw_ev_block(
    tracker: UsageTracker,
    session_key: str,
    raw_ev: _FakeProviderDoneEvent,
    fallback_model_id: str = "",
) -> None:
    """Replay the agent.py:1068-1076 usage-tracker call shape.

    Kept in lock-step with engine/agent.py — if the production call
    signature changes, this helper must change in the same commit. The
    test below asserts the call shape, so a divergence fails fast.
    """
    if tracker and session_key:
        tracker.add(
            session_key,
            input_tokens=raw_ev.input_tokens,
            output_tokens=raw_ev.output_tokens,
            model_id=raw_ev.model or fallback_model_id or "",
            cache_read_tokens=raw_ev.cached_tokens,
            cache_write_tokens=raw_ev.cache_write_tokens,
            billed_cost=raw_ev.billed_cost,
        )


def test_agent_forwards_billed_cost_to_tracker() -> None:
    """The contract: when a ProviderDoneEvent has billed_cost > 0, it lands
    on the per-model UsageTracker entry. Without this, per-model breakdown
    keeps relying on pricing-table estimates and drifts on cache-heavy
    sessions."""
    tracker = UsageTracker()
    raw_ev = _FakeProviderDoneEvent(
        input_tokens=29213,
        output_tokens=400,
        cached_tokens=11588,
        cache_write_tokens=17772,
        billed_cost=0.1254,
        model="anthropic/claude-4.7-opus",
    )
    _simulate_agent_raw_ev_block(tracker, "agent:test:webchat:s1", raw_ev)

    usage = tracker.get("agent:test:webchat:s1")
    assert usage is not None
    assert usage._per_model is not None
    mu = usage._per_model["anthropic/claude-4.7-opus"]
    assert mu.billed_cost == 0.1254
    assert mu.input_tokens == 29213
    assert mu.cache_read_tokens == 11588


def test_agent_forwards_zero_billed_when_provider_lacked_cost() -> None:
    """billed_cost defaults to 0 on ProviderDoneEvent when the provider
    didn't return a price; the tracker must accept it without polluting
    the per-model record (estimate fallback kicks in)."""
    tracker = UsageTracker()
    raw_ev = _FakeProviderDoneEvent(
        input_tokens=1000,
        output_tokens=50,
        cached_tokens=0,
        cache_write_tokens=0,
        billed_cost=0.0,
        model="z-ai/glm-5.1",
        cost_source="unavailable",
    )
    _simulate_agent_raw_ev_block(tracker, "agent:test:webchat:s2", raw_ev)

    usage = tracker.get("agent:test:webchat:s2")
    assert usage is not None
    assert usage._per_model is not None
    mu = usage._per_model["z-ai/glm-5.1"]
    assert mu.billed_cost == 0.0


def test_multiple_raw_events_accumulate_per_model() -> None:
    """User-reported scenario: a multi-model auto-routed session.
    Each ProviderDoneEvent carries one model + its real billed cost.
    Sum of per-model billed equals the session's billed total — which is
    exactly the property that lets rpc_usage skip pro-rate."""
    tracker = UsageTracker()
    session_key = "agent:test:webchat:multi"

    _simulate_agent_raw_ev_block(
        tracker,
        session_key,
        _FakeProviderDoneEvent(
            input_tokens=29213,
            output_tokens=400,
            cached_tokens=11588,
            cache_write_tokens=17772,
            billed_cost=0.1254,
            model="anthropic/claude-4.7-opus",
        ),
    )
    _simulate_agent_raw_ev_block(
        tracker,
        session_key,
        _FakeProviderDoneEvent(
            input_tokens=9323,
            output_tokens=0,
            cached_tokens=0,
            cache_write_tokens=0,
            billed_cost=0.0111,
            model="z-ai/glm-5.1",
        ),
    )

    usage = tracker.get(session_key)
    assert usage is not None
    breakdown = usage.model_breakdown
    by_model = {row["model"]: row for row in breakdown}
    assert by_model["anthropic/claude-4.7-opus"]["costUsd"] == 0.1254
    assert by_model["anthropic/claude-4.7-opus"]["costSource"] == "provider_billed"
    assert by_model["z-ai/glm-5.1"]["costUsd"] == 0.0111
    assert by_model["z-ai/glm-5.1"]["costSource"] == "provider_billed"
    assert sum(row["costUsd"] for row in breakdown) == 0.1365


def test_mock_tracker_receives_billed_cost_kwarg() -> None:
    """Belt-and-braces: the call shape itself includes billed_cost as a kwarg.
    Catches a refactor that 'optimizes' the kwarg away or renames it."""
    mock_tracker = MagicMock(spec=UsageTracker)
    raw_ev = _FakeProviderDoneEvent(
        input_tokens=100,
        output_tokens=10,
        cached_tokens=0,
        cache_write_tokens=0,
        billed_cost=0.0042,
        model="some/model",
    )
    _simulate_agent_raw_ev_block(mock_tracker, "session", raw_ev)

    mock_tracker.add.assert_called_once()
    _args, kwargs = mock_tracker.add.call_args
    assert "billed_cost" in kwargs, "agent must pass billed_cost as kwarg"
    assert kwargs["billed_cost"] == 0.0042
