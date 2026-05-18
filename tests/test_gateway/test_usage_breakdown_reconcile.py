"""Pin _reconcile_breakdown_to_row pro-rate semantics in rpc_usage.

Background: ``engine.usage.ModelUsage.cost`` ignores cache_read pricing
because ``engine.pricing.ModelPrice`` has no cache fields. For multi-model
billed sessions this caused the per-model breakdown sum to drift well above
the row's billed cost (3x for sessions with 90%+ cache hit). The reconcile
helper rescales each item so the breakdown sums to the row total while
preserving the *relative* share implied by the estimates.
"""

from __future__ import annotations

from opensquilla.gateway.rpc_usage import _reconcile_breakdown_to_row


def _make_row(*, cost_usd: float, cost_source: str, breakdown: list) -> dict:
    return {
        "session": "agent:main:webchat:test",
        "cost_usd": cost_usd,
        "costUsd": cost_usd,
        "cost_source": cost_source,
        "costSource": cost_source,
        "modelBreakdown": breakdown,
    }


def _make_item(model: str, cost: float) -> dict:
    return {
        "model": model,
        "costUsd": cost,
        "cost_usd": cost,
    }


def test_billed_multi_model_prorates_to_row_total() -> None:
    """User-reported scenario reproduced exactly.

    Real numbers from production session:
      Row billed (with cache discount):  $0.0607
      Per-model estimates (no cache):    $0.1024 + $0.0811 = $0.1835
      Pre-fix breakdown sum drifted 3x above the row.
    Post-fix expectation: items sum to row.cost (within float epsilon),
    and relative proportion preserved (0.1024/0.1835 ≈ 55.8%).
    """
    row = _make_row(
        cost_usd=0.0607,
        cost_source="provider_billed",
        breakdown=[
            _make_item("z-ai/glm-5.1-20260406", 0.1024),
            _make_item("deepseek/deepseek-v4-flash-20260423", 0.0811),
        ],
    )
    _reconcile_breakdown_to_row(row)

    items = row["modelBreakdown"]
    total = sum(item["costUsd"] for item in items)
    assert abs(total - 0.0607) < 1e-6, f"breakdown sum {total} drifts from row 0.0607"

    # Relative proportion preserved (within rounding):
    expected_share = 0.1024 / 0.1835
    actual_share = items[0]["costUsd"] / total
    assert abs(actual_share - expected_share) < 1e-3, actual_share

    # Source rebadged for UI disclosure.
    for item in items:
        assert item["costSource"] == "provider_billed_prorated"
        assert item["cost_source"] == "provider_billed_prorated"
        # Original estimate is preserved alongside the pro-rated cost.
        assert "estimatedCostUsd" in item
        assert item["estimatedCostUsd"] > item["costUsd"]


def test_billed_single_model_no_change() -> None:
    row = _make_row(
        cost_usd=0.05,
        cost_source="provider_billed",
        breakdown=[_make_item("only-model", 0.07)],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # Single-item path: leave as-is (cost_rollup pipeline handles single-item parity)
    assert items[0]["costUsd"] == 0.07
    assert items[0].get("costSource") != "provider_billed_prorated"


def test_estimate_only_no_change() -> None:
    row = _make_row(
        cost_usd=0.05,
        cost_source="opensquilla_estimate",
        breakdown=[
            _make_item("model-a", 0.03),
            _make_item("model-b", 0.02),
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # Estimate-only rows: row cost is also estimate, sums match by construction.
    assert items[0]["costUsd"] == 0.03
    assert items[1]["costUsd"] == 0.02
    for item in items:
        assert item.get("costSource") != "provider_billed_prorated"


def test_mixed_source_also_prorates() -> None:
    row = _make_row(
        cost_usd=0.10,
        cost_source="mixed",
        breakdown=[
            _make_item("model-a", 0.18),
            _make_item("model-b", 0.02),
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    assert abs(sum(i["costUsd"] for i in items) - 0.10) < 1e-6
    for item in items:
        assert item["costSource"] == "provider_billed_prorated"


def test_zero_estimate_falls_back_to_equal_split() -> None:
    """Defensive: tracker breakdown can land with all-zero costs (e.g. when
    pricing lookup fails for unknown model ids). Without the equal-split
    fallback, the breakdown would still show $0 across the board even though
    the row recorded a real billed total — even worse than the original drift.
    """
    row = _make_row(
        cost_usd=0.04,
        cost_source="provider_billed",
        breakdown=[
            _make_item("unknown-model-a", 0.0),
            _make_item("unknown-model-b", 0.0),
            _make_item("unknown-model-c", 0.0),
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    total = sum(item["costUsd"] for item in items)
    assert abs(total - 0.04) < 1e-6
    # All three get the equal share.
    for item in items:
        assert abs(item["costUsd"] - 0.04 / 3) < 1e-6
        assert item["costSource"] == "provider_billed_prorated"


def test_zero_row_cost_no_change() -> None:
    row = _make_row(
        cost_usd=0.0,
        cost_source="provider_billed",
        breakdown=[
            _make_item("a", 0.01),
            _make_item("b", 0.01),
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # No row total to spread → leave untouched.
    assert items[0]["costUsd"] == 0.01


def test_unavailable_source_no_change() -> None:
    row = _make_row(
        cost_usd=0.05,
        cost_source="unavailable",
        breakdown=[
            _make_item("a", 0.02),
            _make_item("b", 0.03),
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # unavailable source is not in {provider_billed, mixed} so no rebadge.
    assert items[0].get("costSource") != "provider_billed_prorated"
    assert items[0]["costUsd"] == 0.02


def test_reconcile_skips_when_items_already_billed_and_sum_matches_row() -> None:
    """When billed items already sum to the row total, reconcile is a no-op.

    If the tracker has filled in real per-call billed costs for every item and
    their sum already matches the row total, the reconcile must do nothing: no
    rebadge to
    'provider_billed_prorated', no value rewrite. Otherwise the UI would
    falsely show the "split is estimated" disclosure for sessions where the
    split is in fact the literal provider receipt.
    """
    row = _make_row(
        cost_usd=0.1365,
        cost_source="provider_billed",
        breakdown=[
            {"model": "anthropic/claude-4.7-opus", "costUsd": 0.1254,
             "cost_usd": 0.1254, "costSource": "provider_billed",
             "cost_source": "provider_billed"},
            {"model": "z-ai/glm-5.1", "costUsd": 0.0111,
             "cost_usd": 0.0111, "costSource": "provider_billed",
             "cost_source": "provider_billed"},
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # Values untouched.
    assert items[0]["costUsd"] == 0.1254
    assert items[1]["costUsd"] == 0.0111
    # Source untouched (NOT rebadged to provider_billed_prorated).
    assert items[0]["costSource"] == "provider_billed"
    assert items[1]["costSource"] == "provider_billed"


def test_reconcile_still_prorates_when_mixed_items_drift_from_row() -> None:
    """Mixed-source breakdown whose sum DRIFTS from row.cost_usd still
    triggers the pro-rate path (drift = real correction needed). row=0.10
    but breakdown sums to 0.20 → pro-rate scales each to half."""
    row = _make_row(
        cost_usd=0.10,
        cost_source="provider_billed",
        breakdown=[
            # First item has real billed (but inflated for this scenario)
            {"model": "a", "costUsd": 0.18, "cost_usd": 0.18,
             "costSource": "provider_billed", "cost_source": "provider_billed"},
            # Second item is estimate-only
            {"model": "b", "costUsd": 0.02, "cost_usd": 0.02,
             "costSource": "opensquilla_estimate", "cost_source": "opensquilla_estimate"},
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # Drift detected → pro-rate fallback rebadges all items.
    assert all(it["costSource"] == "provider_billed_prorated" for it in items)
    assert abs(sum(it["costUsd"] for it in items) - 0.10) < 1e-6


def test_reconcile_skips_mixed_breakdown_when_sum_already_matches_row() -> None:
    """Mixed-source breakdowns are no-ops when they already sum to the row.

    When the row uses SessionUsage.total_cost (billed where available, estimate
    where not), the breakdown sum already equals the row total. The fast-path
    must skip even though item sources are heterogeneous —
    otherwise mixed rows get falsely rebadged as provider_billed_prorated.
    """
    row = _make_row(
        cost_usd=0.08,  # = 0.05 billed + 0.03 estimate
        cost_source="mixed",
        breakdown=[
            {"model": "claude", "costUsd": 0.05, "cost_usd": 0.05,
             "costSource": "provider_billed", "cost_source": "provider_billed"},
            {"model": "deepseek", "costUsd": 0.03, "cost_usd": 0.03,
             "costSource": "opensquilla_estimate", "cost_source": "opensquilla_estimate"},
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # No rebadge — each item keeps its honest source.
    assert items[0]["costSource"] == "provider_billed"
    assert items[1]["costSource"] == "opensquilla_estimate"
    # Values untouched.
    assert items[0]["costUsd"] == 0.05
    assert items[1]["costUsd"] == 0.03


def test_reconcile_fast_path_tolerates_subcent_drift() -> None:
    """Float arithmetic in the cost rollup pipeline can leave a sub-cent
    drift between the row total and the per-model billed sum. The
    fast-path tolerance (0.001) must absorb this without falling back to
    pro-rate (which would needlessly rebadge as provider_billed_prorated)."""
    row = _make_row(
        cost_usd=0.13649,  # 0.0001 below the breakdown sum of 0.1365
        cost_source="provider_billed",
        breakdown=[
            {"model": "a", "costUsd": 0.1254, "cost_usd": 0.1254,
             "costSource": "provider_billed", "cost_source": "provider_billed"},
            {"model": "b", "costUsd": 0.0111, "cost_usd": 0.0111,
             "costSource": "provider_billed", "cost_source": "provider_billed"},
        ],
    )
    _reconcile_breakdown_to_row(row)
    items = row["modelBreakdown"]
    # No rebadge, no value mutation — within tolerance.
    assert items[0]["costSource"] == "provider_billed"


def test_camel_case_only_row_works() -> None:
    """Tracker rows in some paths use camelCase keys only."""
    row = {
        "session": "agent:main:webchat:test",
        "costUsd": 0.10,
        "costSource": "provider_billed",
        "modelBreakdown": [
            {"model": "a", "costUsd": 0.15},
            {"model": "b", "costUsd": 0.05},
        ],
    }
    _reconcile_breakdown_to_row(row)
    total = sum(i["costUsd"] for i in row["modelBreakdown"])
    assert abs(total - 0.10) < 1e-6
