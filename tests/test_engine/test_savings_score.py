import pytest

from opensquilla.engine.pricing import (
    PriceEntry,
    reset_live_price_cache_for_tests,
    seed_live_price_cache_for_tests,
)
from opensquilla.engine.runtime import _compute_comprehensive_turn_savings
from opensquilla.engine.types import DoneEvent

TEXT_TIERS = {
    "c0": {"model": "deepseek/deepseek-v4-flash"},
    "c2": {"model": "deepseek/deepseek-v4-pro"},
    "c3": {"model": "anthropic/claude-opus-4.7"},
    "image_model": {"model": "moonshotai/kimi-k2.6", "image_only": True},
}


@pytest.fixture(autouse=True)
def no_live_pricing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")
    reset_live_price_cache_for_tests()
    yield
    reset_live_price_cache_for_tests()


def test_comprehensive_savings_uses_input_output_and_reasoning_prices() -> None:
    result = _compute_comprehensive_turn_savings(
        DoneEvent(
            input_tokens=1000,
            output_tokens=200,
            reasoning_tokens=300,
            model="deepseek/deepseek-v4-flash",
        ),
        {},
        TEXT_TIERS,
        "deepseek/deepseek-v4-flash",
    )

    assert result.baseline_model == "anthropic/claude-opus-4.7"
    assert result.baseline_cost_usd == pytest.approx(0.0175)
    assert result.actual_cost_usd == pytest.approx(0.00028)
    assert result.usd == pytest.approx(0.01722)
    assert result.pct == pytest.approx(98.4)


def test_tool_projection_restores_only_the_input_baseline() -> None:
    event = DoneEvent(
        input_tokens=1000,
        output_tokens=200,
        reasoning_tokens=300,
        model="deepseek/deepseek-v4-flash",
    )

    base = _compute_comprehensive_turn_savings(event, {}, TEXT_TIERS, "deepseek/deepseek-v4-flash")
    compressed = _compute_comprehensive_turn_savings(
        event,
        {"tool_projection_tokens_saved": 1000},
        TEXT_TIERS,
        "deepseek/deepseek-v4-flash",
    )

    assert compressed.baseline_cost_usd == pytest.approx(base.baseline_cost_usd + 0.005)
    assert compressed.actual_cost_usd == pytest.approx(base.actual_cost_usd)
    assert compressed.usd > base.usd


def test_p0_prompt_policy_estimates_three_percent_less_output_side_tokens() -> None:
    result = _compute_comprehensive_turn_savings(
        DoneEvent(
            input_tokens=1000,
            output_tokens=700,
            reasoning_tokens=300,
            model="deepseek/deepseek-v4-flash",
        ),
        {"prompt_policy": "P0"},
        TEXT_TIERS,
        "deepseek/deepseek-v4-flash",
        estimated_output_savings_pct=0.03,
    )

    expected_baseline_cost = (1000 / 1_000_000) * 5.0 + ((1000 / 0.97) / 1_000_000) * 25.0
    expected_actual_cost = (1000 / 1_000_000) * 0.14 + (1000 / 1_000_000) * 0.28

    assert result.baseline_cost_usd == pytest.approx(expected_baseline_cost)
    assert result.actual_cost_usd == pytest.approx(expected_actual_cost)
    assert result.usd == pytest.approx(round(expected_baseline_cost - expected_actual_cost, 6))


def test_billed_cost_cost_usd_and_cache_tokens_do_not_change_score() -> None:
    common = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "reasoning_tokens": 300,
        "model": "deepseek/deepseek-v4-flash",
    }

    high_billed = _compute_comprehensive_turn_savings(
        DoneEvent(**common, cached_tokens=0, billed_cost=999.0, cost_usd=888.0),
        {},
        TEXT_TIERS,
        "deepseek/deepseek-v4-flash",
    )
    cache_hit = _compute_comprehensive_turn_savings(
        DoneEvent(**common, cached_tokens=99999, billed_cost=0.000001, cost_usd=0.0),
        {},
        TEXT_TIERS,
        "deepseek/deepseek-v4-flash",
    )

    assert cache_hit.pct == high_billed.pct
    assert cache_hit.usd == high_billed.usd
    assert cache_hit.baseline_cost_usd == high_billed.baseline_cost_usd
    assert cache_hit.actual_cost_usd == high_billed.actual_cost_usd


def test_zero_price_baseline_returns_zero_savings() -> None:
    result = _compute_comprehensive_turn_savings(
        DoneEvent(input_tokens=1000, output_tokens=1000, model="local/routed"),
        {},
        {"local": {"model": "local/baseline"}},
        "local/routed",
    )

    assert result.pct == 0.0
    assert result.usd == 0.0
    assert result.baseline_cost_usd == 0.0
    assert result.actual_cost_usd == 0.0


def test_baseline_uses_one_highest_cost_text_model_for_the_turn_mix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "1")
    seed_live_price_cache_for_tests("vendor/high-input", PriceEntry(10.0, 1.0))
    seed_live_price_cache_for_tests("vendor/high-output", PriceEntry(1.0, 20.0))
    seed_live_price_cache_for_tests("vendor/image-only", PriceEntry(100.0, 100.0))
    seed_live_price_cache_for_tests("vendor/routed", PriceEntry(1.0, 1.0))

    result = _compute_comprehensive_turn_savings(
        DoneEvent(input_tokens=100, output_tokens=1000, model="vendor/routed"),
        {},
        {
            "input": {"model": "vendor/high-input"},
            "output": {"model": "vendor/high-output"},
            "image": {"model": "vendor/image-only", "image_only": True},
        },
        "vendor/routed",
    )

    assert result.baseline_model == "vendor/high-output"
    assert result.baseline_cost_usd == pytest.approx(0.0201)
