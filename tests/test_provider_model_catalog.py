from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensquilla.provider import model_catalog as provider_model_catalog
from opensquilla.provider.model_catalog import (
    ModelCatalog,
    refresh_openrouter_catalog_and_pricing,
)


class FakeRefreshCatalog:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.fetch_calls: list[tuple[str, str, str]] = []

    def __len__(self) -> int:
        return 7

    async def fetch_openrouter(self, api_key: str, base_url: str, proxy: str = "") -> None:
        self.fetch_calls.append((api_key, base_url, proxy))
        if self.fail:
            raise RuntimeError("catalog down")


def test_deepseek_v4_direct_models_use_official_context_and_output_windows() -> None:
    catalog = ModelCatalog()

    for model in ("deepseek-v4-flash", "deepseek-v4-pro"):
        assert catalog.resolve_context_window(model) == 1_048_576
        assert catalog.resolve_max_tokens(model) == 393_216
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
        "glm-5": 200_000,
        "glm-5.1": 200_000,
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


def test_openrouter_pricing_model_ids_collects_primary_and_router_tiers() -> None:
    assert hasattr(provider_model_catalog, "openrouter_pricing_model_ids")

    assert provider_model_catalog.openrouter_pricing_model_ids(
        "openrouter/active",
        {
            "fast": {"model": "openrouter/fast"},
            "empty": {},
            "custom": {"model": 12345},
            "ignored": object(),
        },
    ) == {"openrouter/active", "openrouter/fast", "12345"}


@pytest.mark.asyncio
async def test_refresh_openrouter_catalog_and_pricing_materializes_provider_catalog() -> None:
    catalog = FakeRefreshCatalog()
    pricing_calls: list[tuple[set[str], str]] = []

    await refresh_openrouter_catalog_and_pricing(
        catalog,  # type: ignore[arg-type]
        api_key="test-key",
        base_url="https://openrouter.ai/api",
        proxy="socks5://127.0.0.1:7891",
        pricing_model_ids=["openrouter/a", "openrouter/b", "openrouter/a"],
        refresh_prices=lambda models, base_url: pricing_calls.append((set(models), base_url)),
    )

    assert catalog.fetch_calls == [
        ("test-key", "https://openrouter.ai/api", "socks5://127.0.0.1:7891")
    ]
    assert pricing_calls == [
        ({"openrouter/a", "openrouter/b"}, "https://openrouter.ai/api/v1")
    ]


@pytest.mark.asyncio
async def test_refresh_openrouter_catalog_and_pricing_keeps_pricing_best_effort() -> None:
    catalog = FakeRefreshCatalog(fail=True)
    pricing_calls: list[tuple[set[str], str]] = []

    await refresh_openrouter_catalog_and_pricing(
        catalog,  # type: ignore[arg-type]
        api_key="test-key",
        base_url="https://openrouter.ai/api/",
        pricing_model_ids=["openrouter/a"],
        refresh_prices=lambda models, base_url: pricing_calls.append((set(models), base_url)),
    )

    assert catalog.fetch_calls == [("test-key", "https://openrouter.ai/api/", "")]
    assert pricing_calls == [({"openrouter/a"}, "https://openrouter.ai/api/v1")]


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
