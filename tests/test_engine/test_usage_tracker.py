"""Unit tests for SessionUsage / UsageTracker cache token accumulation."""

from opensquilla.engine.usage import ModelUsage, SessionUsage, UsageTracker, usage_scope


def test_session_usage_accumulates_cache_tokens() -> None:
    usage = SessionUsage(model_id="claude-opus-4-7")
    usage.add(1000, 50, "claude-opus-4-7", cache_read_tokens=500, cache_write_tokens=100)
    usage.add(2000, 80, "claude-opus-4-7", cache_read_tokens=300, cache_write_tokens=40)

    assert usage.input_tokens == 3000
    assert usage.output_tokens == 130
    assert usage.cache_read_tokens == 800
    assert usage.cache_write_tokens == 140


def test_session_usage_per_model_breakdown_isolates_cache_tokens() -> None:
    usage = SessionUsage()
    usage.add(1000, 50, "claude-opus-4-7", cache_read_tokens=500, cache_write_tokens=100)
    usage.add(2000, 80, "deepseek-v4-pro", cache_read_tokens=300, cache_write_tokens=40)

    assert usage._per_model is not None
    opus = usage._per_model["claude-opus-4-7"]
    deepseek = usage._per_model["deepseek-v4-pro"]
    assert opus.cache_read_tokens == 500
    assert opus.cache_write_tokens == 100
    assert deepseek.cache_read_tokens == 300
    assert deepseek.cache_write_tokens == 40


def test_session_usage_add_default_cache_zero() -> None:
    """Existing positional callers (no cache kwargs) still work; cache fields stay at 0."""
    usage = SessionUsage(model_id="claude-opus-4-7")
    usage.add(1000, 50, "claude-opus-4-7")

    assert usage.input_tokens == 1000
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


def test_usage_tracker_add_passes_cache_to_session() -> None:
    tracker = UsageTracker()
    tracker.add(
        "session-a",
        input_tokens=1000,
        output_tokens=50,
        model_id="claude-opus-4-7",
        cache_read_tokens=200,
        cache_write_tokens=80,
    )
    tracker.add(
        "session-a",
        input_tokens=500,
        output_tokens=20,
        model_id="claude-opus-4-7",
        cache_read_tokens=100,
        cache_write_tokens=40,
    )

    usage = tracker.get("session-a")
    assert usage is not None
    assert usage.cache_read_tokens == 300
    assert usage.cache_write_tokens == 120


def test_usage_tracker_isolates_sessions() -> None:
    tracker = UsageTracker()
    tracker.add(
        "session-a",
        input_tokens=100,
        output_tokens=10,
        model_id="m",
        cache_read_tokens=50,
        cache_write_tokens=5,
    )
    tracker.add(
        "session-b",
        input_tokens=200,
        output_tokens=20,
        model_id="m",
        cache_read_tokens=70,
        cache_write_tokens=15,
    )

    a = tracker.get("session-a")
    b = tracker.get("session-b")
    assert a is not None and b is not None
    assert a.cache_read_tokens == 50
    assert a.cache_write_tokens == 5
    assert b.cache_read_tokens == 70
    assert b.cache_write_tokens == 15


def test_usage_tracker_records_current_scope_without_changing_session_total() -> None:
    tracker = UsageTracker()

    with usage_scope("meta-run:step-a"):
        tracker.add(
            "session-a",
            input_tokens=100,
            output_tokens=10,
            model_id="m-a",
            cache_read_tokens=3,
            cache_write_tokens=2,
        )
    with usage_scope("meta-run:step-b"):
        tracker.add(
            "session-a",
            input_tokens=200,
            output_tokens=20,
            model_id="m-b",
        )

    total = tracker.get("session-a")
    assert total is not None
    assert total.input_tokens == 300
    assert total.output_tokens == 30

    step_a = tracker.get_scope("session-a", "meta-run:step-a")
    step_b = tracker.get_scope("session-a", "meta-run:step-b")
    assert step_a is not None
    assert step_b is not None
    assert step_a.input_tokens == 100
    assert step_a.output_tokens == 10
    assert step_a.cache_read_tokens == 3
    assert step_a.cache_write_tokens == 2
    assert step_a.model_id == "m-a"
    assert step_b.input_tokens == 200
    assert step_b.output_tokens == 20
    assert step_b.model_id == "m-b"


# ---------------------------------------------------------------------------
# Positional dataclass construction safety.
# ---------------------------------------------------------------------------


def test_session_usage_positional_construction_does_not_shift_fields() -> None:
    """Regression: SessionUsage(1, 2, "claude-opus-4-7") must keep the third
    positional arg in model_id, not in a cache field. Asserts the new cache
    counters were appended at the *end* of the dataclass."""
    usage = SessionUsage(1000, 50, "claude-opus-4-7")

    assert usage.input_tokens == 1000
    assert usage.output_tokens == 50
    assert usage.model_id == "claude-opus-4-7"
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


def test_model_usage_positional_construction_keeps_model_id_first() -> None:
    """ModelUsage(model_id, in, out) — sanity check for positional callers."""
    mu = ModelUsage("claude-opus-4-7", 1000, 50)

    assert mu.model_id == "claude-opus-4-7"
    assert mu.input_tokens == 1000
    assert mu.output_tokens == 50
    assert mu.cache_read_tokens == 0
    assert mu.cache_write_tokens == 0


# ---------------------------------------------------------------------------
# model_breakdown must surface cache fields.
# ---------------------------------------------------------------------------


def test_model_breakdown_serializes_cache_fields_for_per_model_path() -> None:
    """Multi-model session: each breakdown entry must carry cache R/W counters
    so the UI's modelBreakdown column can show per-model cache split."""
    usage = SessionUsage()
    usage.add(1000, 50, "claude-opus-4-7", cache_read_tokens=500, cache_write_tokens=100)
    usage.add(2000, 80, "deepseek-v4-pro", cache_read_tokens=300, cache_write_tokens=40)

    breakdown = usage.model_breakdown
    assert len(breakdown) == 2

    by_model = {row["model"]: row for row in breakdown}
    assert by_model["claude-opus-4-7"]["cacheReadTokens"] == 500
    assert by_model["claude-opus-4-7"]["cacheWriteTokens"] == 100
    assert by_model["deepseek-v4-pro"]["cacheReadTokens"] == 300
    assert by_model["deepseek-v4-pro"]["cacheWriteTokens"] == 40


def test_model_breakdown_serializes_cache_fields_for_single_model_path() -> None:
    """Single-model session (no per-model dict yet): the synthesized one-row
    breakdown must also carry cache R/W counters."""
    usage = SessionUsage(model_id="claude-opus-4-7")
    # Direct field mutation — exercises the no-_per_model branch in model_breakdown.
    usage.input_tokens = 1000
    usage.output_tokens = 50
    usage.cache_read_tokens = 200
    usage.cache_write_tokens = 80

    [row] = usage.model_breakdown
    assert row["model"] == "claude-opus-4-7"
    assert row["cacheReadTokens"] == 200
    assert row["cacheWriteTokens"] == 80
