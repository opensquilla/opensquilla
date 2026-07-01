from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensquilla.provider.model_catalog import _STATIC_FALLBACK, ModelCatalog


def test_deepseek_v4_direct_models_use_conservative_output_window() -> None:
    catalog = ModelCatalog()

    for model in ("deepseek-v4-flash", "deepseek-v4-pro"):
        assert catalog.resolve_context_window(model) == 1_048_576
        # Conservative-min of the former qualified (16k) vs bare (393k) entries.
        assert catalog.resolve_max_tokens(model) == 16_384
        caps = catalog.get_capabilities(model, provider_name="deepseek")
        assert caps.supports_reasoning is True
        assert caps.supports_tools is True
        assert caps.reasoning_format == "deepseek"


def test_direct_profile_static_fallbacks_cover_context_windows() -> None:
    catalog = ModelCatalog()

    expected_windows = {
        "gpt-5.4-nano": 400_000,
        "gpt-5.4-mini": 400_000,
        "gpt-5.5": 1_000_000,
        "glm-4.7-flashx": 200_000,
        "glm-5": 80_000,
        "glm-5.1": 200_000,
        "z-ai/glm-5.2": 1_048_576,
        "moonshot-v1-8k": 8_192,
        "moonshot-v1-128k": 131_072,
        "kimi-k2.5": 262_144,
        "kimi-k2.6": 262_144,
    }

    for model_id, context_window in expected_windows.items():
        assert catalog.resolve_context_window(model_id) == context_window
        max_tokens = catalog.resolve_max_tokens(model_id)
        assert max_tokens > 0
        assert max_tokens <= context_window


def test_static_fallback_keys_are_provider_agnostic_and_conservative() -> None:
    # No provider-qualified spellings remain, so one physical model cannot
    # carry two divergent budget tuples.
    assert all("/" not in key for key in _STATIC_FALLBACK)
    # Conservative-min merges of formerly divergent pairs.
    assert _STATIC_FALLBACK["glm-5"] == (80_000, 80_000)
    assert _STATIC_FALLBACK["deepseek-v4-flash"] == (16_384, 1_048_576)
    assert _STATIC_FALLBACK["kimi-k2.6"] == (32_768, 262_144)


def test_static_fallback_qualified_and_unqualified_resolve_identically() -> None:
    catalog = ModelCatalog()
    for qualified, bare in (
        ("z-ai/glm-5", "glm-5"),
        ("deepseek/deepseek-v4-pro", "deepseek-v4-pro"),
    ):
        assert catalog.resolve_context_window(qualified) == catalog.resolve_context_window(bare)
        assert catalog.resolve_max_tokens(qualified) == catalog.resolve_max_tokens(bare)


def test_populate_from_data_parses_openrouter_pricing() -> None:
    catalog = ModelCatalog()
    catalog._populate_from_data(
        [
            {
                "id": "vendor/priced-model",
                "context_length": 100_000,
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            },
            {"id": "vendor/free-model", "context_length": 8_192},
            {"id": "vendor/bad-pricing", "pricing": {"prompt": "n/a", "completion": None}},
        ]
    )

    priced = catalog.get("vendor/priced-model")
    assert priced is not None
    assert priced.input_cost_per_1k == pytest.approx(0.0025)
    assert priced.output_cost_per_1k == pytest.approx(0.01)
    # Missing pricing block → 0.0
    assert catalog.get("vendor/free-model").input_cost_per_1k == 0.0
    # Non-numeric / None → 0.0 (no crash)
    bad = catalog.get("vendor/bad-pricing")
    assert bad.input_cost_per_1k == 0.0
    assert bad.output_cost_per_1k == 0.0


def test_openrouter_near_context_completion_window_uses_safe_default() -> None:
    catalog = ModelCatalog()
    catalog._populate_from_data(
        [
            {
                "id": "provider/vision-model",
                "context_length": 262_144,
                "top_provider": {"max_completion_tokens": 262_142},
            }
        ]
    )

    assert catalog.resolve_context_window("provider/vision-model") == 262_144
    assert catalog.resolve_max_tokens("provider/vision-model") == 8192


def test_openrouter_safe_default_never_raises_smaller_provider_limit() -> None:
    catalog = ModelCatalog()
    catalog._populate_from_data(
        [
            {
                "id": "provider/smaller-output-model",
                "context_length": 12_000,
                "top_provider": {"max_completion_tokens": 4096},
            }
        ]
    )

    assert catalog.resolve_context_window("provider/smaller-output-model") == 12_000
    assert catalog.resolve_max_tokens("provider/smaller-output-model") == 4096


@pytest.mark.asyncio
async def test_fetch_openrouter_adds_app_attribution_headers() -> None:
    captured: dict[str, object] = {}
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_length": 128_000,
                "top_provider": {"max_completion_tokens": 16_384},
            }
        ]
    }

    with patch("opensquilla.provider.model_catalog.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_get(url, *, headers):
            captured["url"] = url
            captured["headers"] = headers
            return mock_response

        mock_client.get = AsyncMock(side_effect=capture_get)
        mock_client_cls.return_value = mock_client

        catalog = ModelCatalog()
        await catalog.fetch_openrouter(api_key="test-key", base_url="https://openrouter.ai/api")

    assert captured["url"] == "https://openrouter.ai/api/v1/models"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "HTTP-Referer": "https://opensquilla.ai",
        "X-OpenRouter-Title": "OpenSquilla",
        "X-OpenRouter-Categories": "cli-agent,personal-agent",
    }
    model = catalog.get("openai/gpt-4o")
    assert model is not None
    assert model.context_window == 128_000


def test_local_provider_context_window_uses_runtime_default_not_cloud() -> None:
    from opensquilla.provider.model_catalog import (
        _LOCAL_CONTEXT_WINDOW,
        DEFAULT_CONTEXT_WINDOW,
    )

    catalog = ModelCatalog()
    # Without provider context a bare ollama id falls to the 200k cloud default.
    assert catalog.resolve_context_window("qwen3:4b") == DEFAULT_CONTEXT_WINDOW
    # With the local provider it reports the runtime window instead.
    assert catalog.resolve_context_window("qwen3:4b", provider="ollama") == _LOCAL_CONTEXT_WINDOW
    assert _LOCAL_CONTEXT_WINDOW < DEFAULT_CONTEXT_WINDOW


def test_local_provider_max_tokens_clamped_to_local_window() -> None:
    from opensquilla.provider.model_catalog import _LOCAL_CONTEXT_WINDOW

    catalog = ModelCatalog()
    # max_tokens cannot exceed the (smaller) local context window.
    assert catalog.resolve_max_tokens("llama3.2:3b", provider="ollama") <= _LOCAL_CONTEXT_WINDOW


def test_cloud_provider_context_window_unchanged() -> None:
    from opensquilla.provider.model_catalog import DEFAULT_CONTEXT_WINDOW

    catalog = ModelCatalog()
    # An unknown cloud model id is unaffected by the provider argument.
    assert catalog.resolve_context_window("some-cloud-model", provider="openai") == (
        DEFAULT_CONTEXT_WINDOW
    )
