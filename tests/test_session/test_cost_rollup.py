"""Tests for session cost source rollup helpers."""

from opensquilla.session.cost_rollup import (
    normalize_event_cost_source,
    rollup_cost_source,
)


def test_normalize_event_cost_source_prefers_provider_billed_signals() -> None:
    assert normalize_event_cost_source("provider_billed") == "provider_billed"
    assert normalize_event_cost_source("openrouter_usage") == "provider_billed"
    assert normalize_event_cost_source(None, billed_cost_usd=0.01) == "provider_billed"


def test_normalize_event_cost_source_preserves_mixed_components() -> None:
    assert normalize_event_cost_source("mixed") == "mixed"
    assert (
        normalize_event_cost_source(None, cost_usd=0.03, billed_cost_usd=0.01)
        == "mixed"
    )


def test_normalize_event_cost_source_distinguishes_estimate_unavailable_and_none() -> None:
    assert normalize_event_cost_source("opensquilla_estimate") == "opensquilla_estimate"
    assert normalize_event_cost_source(None, cost_usd=0.02) == "opensquilla_estimate"
    assert normalize_event_cost_source(None, input_tokens=100) == "unavailable"
    assert normalize_event_cost_source("unpriced") == "unavailable"
    assert normalize_event_cost_source(None) == "none"


def test_rollup_cost_source_classifies_single_and_mixed_components() -> None:
    assert (
        rollup_cost_source(
            billed_cost_usd=0.03,
            estimated_cost_component_usd=0.0,
            missing_cost_entries=0,
        )
        == "provider_billed"
    )
    assert (
        rollup_cost_source(
            billed_cost_usd=0.0,
            estimated_cost_component_usd=0.02,
            missing_cost_entries=0,
        )
        == "opensquilla_estimate"
    )
    assert (
        rollup_cost_source(
            billed_cost_usd=0.0,
            estimated_cost_component_usd=0.0,
            missing_cost_entries=1,
        )
        == "unavailable"
    )
    assert (
        rollup_cost_source(
            billed_cost_usd=0.03,
            estimated_cost_component_usd=0.02,
            missing_cost_entries=0,
        )
        == "mixed"
    )
    assert (
        rollup_cost_source(
            billed_cost_usd=0.0,
            estimated_cost_component_usd=0.0,
            missing_cost_entries=0,
        )
        == "none"
    )
