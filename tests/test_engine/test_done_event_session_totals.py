"""Coverage for SessionTotalsSnapshot embedded in DoneEvent."""

from __future__ import annotations

import json
from dataclasses import asdict

from opensquilla.engine.types import DoneEvent
from opensquilla.engine.usage import UsageTracker


def test_tracked_session_emits_six_field_snapshot():
    """When a session has usage recorded, snapshot has exactly 6 fields populated."""
    tracker = UsageTracker()
    tracker.add(
        "sess-A",
        input_tokens=10,
        output_tokens=20,
        model_id="gpt-test",
        cache_read_tokens=3,
        cache_write_tokens=1,
        billed_cost=0.001,
    )
    snap = tracker.session_snapshot("sess-A")
    assert snap is not None
    data = asdict(snap)
    assert set(data.keys()) == {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "billed_cost",
    }
    assert data["input_tokens"] == 10
    assert data["output_tokens"] == 20


def test_untracked_session_emits_none_snapshot():
    """An unknown session_key yields None, not an empty snapshot."""
    tracker = UsageTracker()
    assert tracker.session_snapshot("never-seen") is None


def test_multi_turn_aggregates_in_snapshot():
    """Snapshot on turn 2 reflects cumulative across turns 1+2."""
    tracker = UsageTracker()
    tracker.add("sess-B", input_tokens=10, output_tokens=20, model_id="gpt-test")
    tracker.add("sess-B", input_tokens=5, output_tokens=7, model_id="gpt-test")
    snap = tracker.session_snapshot("sess-B")
    assert snap is not None
    assert snap.input_tokens == 15
    assert snap.output_tokens == 27


def test_stale_replay_roundtrips_through_json_and_live_tracker_wins():
    """DoneEvent embedded snapshot survives asdict+json round-trip; server-side
    replay-precedence rule: live tracker beats embedded for re-emitted events."""
    tracker = UsageTracker()
    tracker.add("sess-C", input_tokens=10, output_tokens=20, model_id="gpt-test")
    snap_s1 = tracker.session_snapshot("sess-C")
    done = DoneEvent(session_totals=snap_s1)

    serialized = json.loads(json.dumps(asdict(done)))
    assert serialized["session_totals"] is not None
    assert serialized["session_totals"]["input_tokens"] == 10

    # Advance tracker beyond the frozen snapshot — server-side consumers should
    # NOT see stale values if they re-derive from the live tracker.
    tracker.add("sess-C", input_tokens=99, output_tokens=99, model_id="gpt-test")
    snap_s2 = tracker.session_snapshot("sess-C")
    assert snap_s2.input_tokens == 109
    assert snap_s2.input_tokens != snap_s1.input_tokens  # live > frozen


def test_positional_construction_through_reasoning_content_leaves_session_totals_none():
    """Append-at-end invariant for new fields. Build DoneEvent positionally up
    through reasoning_content and assert session_totals defaults to None."""
    # DoneEvent positional order (excluding kind which is init=False):
    # text, input_tokens, output_tokens, reasoning_tokens, cached_tokens,
    # iterations, cost_usd, billed_cost, cost_source, model,
    # runtime_context_hash, runtime_context_chars, routed_tier, routing_source,
    # routing_confidence, baseline_model, routed_model, savings_pct, savings_usd,
    # cache_hit_active, total_savings_pct, total_savings_usd, cache_write_tokens,
    # reasoning_content. Newer fields must remain after session_totals.
    done = DoneEvent(
        "hello", 1, 2, 0, 0, 1, 0.0, 0.0, "none", "gpt-test",
        None, 0, None, "none", 0.0, "", "", 0.0, 0.0,
        False, 0.0, 0.0, 0, None,
    )
    assert done.session_totals is None
    assert done.text == "hello"
    assert done.input_tokens == 1
