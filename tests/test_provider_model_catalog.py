from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensquilla.provider.model_catalog import ModelCatalog


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


def test_provider_qualified_metadata_keeps_same_model_ids_separate() -> None:
    catalog = ModelCatalog()
    catalog.add_models(
        "openai_compatible",
        "http://localhost:8001/v1",
        [{"id": "shared-model", "max_model_len": 32768}],
    )
    catalog.add_models(
        "openai_compatible",
        "http://localhost:8002/v1",
        [
            {
                "id": "shared-model",
                "context_window": 65536,
                "max_output_tokens": 4096,
            }
        ],
    )

    first = catalog.get(
        "shared-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8001/v1",
    )
    second = catalog.get(
        "shared-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8002/v1/",
    )

    assert first is not None
    assert second is not None
    assert first.context_window == 32768
    assert second.context_window == 65536
    assert (
        catalog.resolve_context_window(
            "shared-model",
            provider_name="openai_compatible",
            base_url="http://localhost:8001/v1",
        )
        == 32768
    )
    assert (
        catalog.resolve_context_window(
            "shared-model",
            provider_name="openai_compatible",
            base_url="http://localhost:8002/v1",
        )
        == 65536
    )
    assert (
        catalog.resolve_max_tokens(
            "shared-model",
            provider_name="openai_compatible",
            base_url="http://localhost:8002/v1",
        )
        == 4096
    )


def test_provider_qualified_metadata_normalizes_versioned_base_url_suffix() -> None:
    catalog = ModelCatalog()
    catalog.add_models(
        "openai_compatible",
        "http://localhost:8008",
        [{"id": "local-model", "max_model_len": 32768}],
    )

    assert (
        catalog.resolve_context_window(
            "local-model",
            provider_name="openai_compatible",
            base_url="http://localhost:8008/v1/",
        )
        == 32768
    )


def test_openai_compatible_metadata_without_tool_parameters_is_unknown() -> None:
    catalog = ModelCatalog()
    catalog.add_models(
        "openai_compatible",
        "http://localhost:8008/v1",
        [{"id": "local-model", "max_model_len": 32768}],
    )

    caps = catalog.get_capabilities(
        "local-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8008/v1",
    )

    assert caps.supports_tools is False
    assert caps.tool_support_state == "unknown"


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


@pytest.mark.asyncio
async def test_probe_openai_compatible_tools_updates_provider_scoped_capability() -> None:
    captured: dict[str, object] = {}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": "ping", "arguments": "{}"},
                        }
                    ]
                }
            }
        ]
    }

    with patch("opensquilla.provider.model_catalog.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return mock_response

        mock_client.post = AsyncMock(side_effect=capture_post)
        mock_client_cls.return_value = mock_client

        catalog = ModelCatalog()
        result = await catalog.probe_openai_compatible_tools(
            provider_name="openai_compatible",
            base_url="http://localhost:8008/v1",
            model_id="local-model",
            api_key="test-key",
        )

    assert result is True
    assert captured["url"] == "http://localhost:8008/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    payload = captured["json"]
    assert payload["model"] == "local-model"
    assert payload["tool_choice"] == "required"
    assert payload["tools"][0]["function"]["name"] == "ping"
    caps = catalog.get_capabilities(
        "local-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8008/v1",
    )
    assert caps.supports_tools is True
    assert caps.tool_support_state == "supported"


@pytest.mark.asyncio
async def test_probe_openai_compatible_tools_auto_mode_does_not_force_required() -> None:
    captured: dict[str, object] = {}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": "ping", "arguments": "{}"},
                        }
                    ]
                }
            }
        ]
    }

    with patch("opensquilla.provider.model_catalog.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return mock_response

        mock_client.post = AsyncMock(side_effect=capture_post)
        mock_client_cls.return_value = mock_client

        catalog = ModelCatalog()
        result = await catalog.probe_openai_compatible_tools(
            provider_name="openai_compatible",
            base_url="http://localhost:8008/v1",
            model_id="local-model",
            tool_probe_mode="auto",
        )

    assert result is True
    payload = captured["json"]
    assert payload["tool_choice"] == "auto"
    assert payload["messages"][0]["content"] == "Call the ping tool."


@pytest.mark.asyncio
async def test_probe_openai_compatible_tools_timeout_keeps_capability_unknown() -> None:
    with patch("opensquilla.provider.model_catalog.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=TimeoutError("probe timed out"))
        mock_client_cls.return_value = mock_client

        catalog = ModelCatalog()
        result = await catalog.probe_openai_compatible_tools(
            provider_name="openai_compatible",
            base_url="http://localhost:8008/v1",
            model_id="local-model",
            tool_probe_mode="auto",
        )

    assert result is None
    caps = catalog.get_capabilities(
        "local-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8008/v1",
    )
    assert caps.supports_tools is True
    assert caps.tool_support_state == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [{"content": "pong"}, {"tool_calls": []}])
async def test_probe_openai_compatible_tools_keeps_unknown_without_returned_tool_call(
    message: dict[str, object],
) -> None:
    """A 200 without tool_calls must not persist an unsupported verdict.

    Endpoints like Inception diffusion models answer the probe prompt in
    text while calling tools fine in real turns; only an explicit 400/422
    rejection proves the endpoint cannot take tools.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": message}],
    }

    with patch("opensquilla.provider.model_catalog.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        catalog = ModelCatalog()
        result = await catalog.probe_openai_compatible_tools(
            provider_name="openai_compatible",
            base_url="http://localhost:8008/v1",
            model_id="local-model",
        )

    assert result is None
    caps = catalog.get_capabilities(
        "local-model",
        provider_name="openai_compatible",
        base_url="http://localhost:8008/v1",
    )
    assert caps.supports_tools is True
    assert caps.tool_support_state == "unknown"
