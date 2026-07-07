from __future__ import annotations

import pytest

from opensquilla.engine.pricing import CostEstimate, PriceEntry, estimate_cost


def test_cache_aware_four_bucket_math():
    # Issue #490 row 1 at current official deepseek pricing -> $0.807416
    price = PriceEntry(0.435, 0.87, cache_read_per_m=0.003625)
    est: CostEstimate = estimate_cost(
        input_tokens=11_559_964,
        output_tokens=262_086,
        cache_read_tokens=10_313_958,
        price=price,
    )
    assert est.basis == "cache_aware"
    assert est.cost_usd == pytest.approx(0.807416, abs=1e-6)


def test_cache_write_priced_when_rate_known():
    # Claude opus 4.8 shape from issue #490 row 2 -> $4.236056
    price = PriceEntry(5.0, 25.0, cache_read_per_m=0.5, cache_write_per_m=6.25)
    est: CostEstimate = estimate_cost(
        input_tokens=1_120_049,
        output_tokens=39_102,
        cache_read_tokens=650_734,
        cache_write_tokens=469_251,
        price=price,
    )
    assert est.basis == "cache_aware"
    assert est.cost_usd == pytest.approx(4.236056, abs=1e-6)


def test_missing_cache_read_rate_falls_back_cache_blind():
    price = PriceEntry(1.0, 2.0)  # no cache rates
    est: CostEstimate = estimate_cost(
        input_tokens=1_000_000, output_tokens=0, cache_read_tokens=900_000, price=price
    )
    assert est.basis == "cache_blind"
    assert est.cost_usd == pytest.approx(1.0)  # legacy formula, full input rate


def test_missing_cache_write_rate_falls_back_cache_blind():
    price = PriceEntry(1.0, 2.0, cache_read_per_m=0.1)
    est: CostEstimate = estimate_cost(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=100_000,
        cache_write_tokens=100_000,
        price=price,
    )
    assert est.basis == "cache_blind"


def test_no_cache_tokens_is_cache_aware_even_without_rates():
    est: CostEstimate = estimate_cost(
        input_tokens=1000, output_tokens=500, price=PriceEntry(1.0, 2.0)
    )
    assert est.basis == "cache_aware"
    assert est.cost_usd == pytest.approx(0.002)


def test_free_price_is_free_basis():
    est: CostEstimate = estimate_cost(input_tokens=5, output_tokens=5, price=PriceEntry(0.0, 0.0))
    assert est.basis == "free"
    assert est.cost_usd == 0.0


def test_cache_counts_clamped_to_input():
    # malformed provider data must never produce negative fresh-input
    price = PriceEntry(1.0, 0.0, cache_read_per_m=0.1)
    est: CostEstimate = estimate_cost(
        input_tokens=100, output_tokens=0, cache_read_tokens=500, price=price
    )
    assert est.cost_usd == pytest.approx(100 * 0.1 / 1_000_000)
