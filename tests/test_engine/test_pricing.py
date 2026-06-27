from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from opensquilla.engine.pricing import (
    PriceEntry,
    PricingCache,
    lookup_price,
    reset_live_price_cache_for_tests,
    seed_live_price_cache_for_tests,
)


@pytest.fixture(autouse=True)
def reset_pricing_cache() -> Iterator[None]:
    reset_live_price_cache_for_tests()
    yield
    reset_live_price_cache_for_tests()


def test_deepseek_v4_pro_uses_non_discount_price_when_live_pricing_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price("deepseek/deepseek-v4-pro")

    assert price.input_per_m == pytest.approx(1.74)
    assert price.output_per_m == pytest.approx(3.48)


@pytest.mark.asyncio
async def test_pricing_cache_refresh_adds_openrouter_app_attribution() -> None:
    import httpx as _httpx

    cache = PricingCache(api_key="test-key", ttl_seconds=60)
    captured: dict[str, object] = {}
    mock_response = _httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
                }
            ]
        },
        request=_httpx.Request("GET", "https://openrouter.ai/api/v1/models"),
    )

    with patch("opensquilla.engine.pricing.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()

        async def capture_get(url, *, headers):
            captured["url"] = url
            captured["headers"] = headers
            return mock_response

        mock_instance.get = AsyncMock(side_effect=capture_get)
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        await cache.refresh()

    assert captured["url"] == "https://openrouter.ai/api/v1/models"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://opensquilla.ai",
        "X-OpenRouter-Title": "OpenSquilla",
        "X-OpenRouter-Categories": "cli-agent,personal-agent",
    }
    price = cache.get_price_sync("openai/gpt-4o")
    assert price is not None
    assert price.input_per_token == 0.0000025
    assert price.output_per_token == 0.00001


def test_deepseek_v4_pro_override_wins_over_discounted_live_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "1")
    seed_live_price_cache_for_tests("deepseek/deepseek-v4-pro", PriceEntry(0.435, 0.87))

    price = lookup_price("deepseek/deepseek-v4-pro")

    assert price.input_per_m == pytest.approx(1.74)
    assert price.output_per_m == pytest.approx(3.48)


def test_deepseek_v4_pro_override_covers_versioned_openrouter_model_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "1")
    seed_live_price_cache_for_tests(
        "deepseek/deepseek-v4-pro-20260423",
        PriceEntry(0.435, 0.87),
    )

    price = lookup_price("deepseek/deepseek-v4-pro-20260423")

    assert price.input_per_m == pytest.approx(1.74)
    assert price.output_per_m == pytest.approx(3.48)


def test_pricing_cache_returns_non_discount_deepseek_v4_pro_price() -> None:
    cache = PricingCache(api_key="test")

    price = cache.get_price_sync("deepseek/deepseek-v4-pro")

    assert price is not None
    assert price.input_per_token == pytest.approx(1.74 / 1_000_000)
    assert price.output_per_token == pytest.approx(3.48 / 1_000_000)


@pytest.mark.parametrize("model", ["z-ai/glm-5.1", "z-ai/glm-5.2"])
def test_glm_5_static_price_matches_openrouter_native_provider(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price(model)

    assert price.input_per_m == pytest.approx(1.40)
    assert price.output_per_m == pytest.approx(4.40)


def test_claude_opus_4_8_static_price_matches_openrouter_model_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price("anthropic/claude-opus-4.8")

    assert price.input_per_m == pytest.approx(5.0)
    assert price.output_per_m == pytest.approx(25.0)


@pytest.mark.parametrize(
    ("model", "input_per_m", "output_per_m"),
    [
        ("qwen-plus", 0.115, 0.287),
        ("qwen-flash", 0.022, 0.216),
        ("qwen-turbo", 0.044, 0.087),
        ("qwen-max", 0.345, 1.377),
    ],
)
def test_dashscope_beijing_qwen_static_prices_match_official_model_studio_pricing(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    input_per_m: float,
    output_per_m: float,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price(model)

    assert price.input_per_m == pytest.approx(input_per_m)
    assert price.output_per_m == pytest.approx(output_per_m)


def test_dashscope_beijing_qwen_plus_smoke_usage_estimates_cost_from_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")
    price = lookup_price("qwen-plus")

    estimated_cost = (31 * price.input_per_m + 6 * price.output_per_m) / 1_000_000

    assert estimated_cost == pytest.approx(0.000005287)


def test_provider_profile_models_do_not_use_default_pricing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")
    default = PriceEntry(3.0, 15.0)
    models = [
        "qwen3.6-flash",
        "qwen3.6-plus",
        "qwen3-max",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "doubao-seed-1-6-flash-250828",
        "doubao-seed-1-6-251015",
        "doubao-seed-1-6-thinking-250715",
        "doubao-seed-2-0-mini-260215",
        "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-code-preview-260215",
    ]

    for model in models:
        assert lookup_price(model) != default, model


def test_local_embedding_model_does_not_fetch_openrouter_pricing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "1")

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("local embedding models should not hit OpenRouter pricing")

    monkeypatch.setattr("opensquilla.engine.pricing._fetch_openrouter_json_sync", fail_fetch)

    price = lookup_price("BAAI/bge-small-zh-v1.5")

    assert price.input_per_m == 0
    assert price.output_per_m == 0


@pytest.mark.parametrize(
    ("model", "input_per_m", "output_per_m"),
    [
        ("gpt-5.4-nano", 0.20, 1.25),
        ("gpt-5.4-mini", 0.75, 4.50),
        ("gpt-5.5", 5.0, 30.0),
        ("glm-5", 0.72, 2.30),
        ("glm-5.1", 1.40, 4.40),
        ("kimi-k2.5", 0.3827, 1.72),
        ("kimi-k2.6", 0.95, 4.0),
    ],
)
def test_direct_provider_profile_estimate_prices_match_approved_static_entries(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    input_per_m: float,
    output_per_m: float,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price(model)

    assert price.input_per_m == pytest.approx(input_per_m)
    assert price.output_per_m == pytest.approx(output_per_m)


@pytest.mark.parametrize(
    ("model", "input_per_m", "output_per_m"),
    [
        ("doubao-seed-2-0-mini-260215", 0.029, 0.287),
        ("doubao-seed-2-0-lite-260215", 0.086, 0.516),
        ("doubao-seed-2-0-pro-260215", 0.459, 2.294),
        ("doubao-seed-2-0-code-preview-260215", 0.459, 2.294),
    ],
)
def test_volcengine_seed_2_static_prices_match_under_32k_online_inference_pricing(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    input_per_m: float,
    output_per_m: float,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price(model)

    assert price.input_per_m == pytest.approx(input_per_m)
    assert price.output_per_m == pytest.approx(output_per_m)


@pytest.mark.parametrize(
    ("model", "input_per_m", "output_per_m"),
    [
        ("gpt-4.1", 2.0, 8.0),
        ("glm-4.5", 0.115, 0.287),
        ("kimi-k2.6", 0.95, 4.0),
        ("MiniMax-M2.7", 0.118, 0.99),
    ],
)
def test_direct_openai_zhipu_kimi_and_minimax_prices_do_not_fall_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    input_per_m: float,
    output_per_m: float,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "0")

    price = lookup_price(model)

    assert price.input_per_m == pytest.approx(input_per_m)
    assert price.output_per_m == pytest.approx(output_per_m)
