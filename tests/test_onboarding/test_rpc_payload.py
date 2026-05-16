from __future__ import annotations

from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.onboarding.rpc_payload import (
    memory_embedding_provider_catalog_payload,
    onboarding_catalog_rpc_payload,
    onboarding_status_rpc_payload,
)


def test_onboarding_status_rpc_payload_owns_gateway_wire_shape(tmp_path) -> None:
    cfg = GatewayConfig()
    cfg.config_path = str(tmp_path / "disk.toml")
    cfg.llm = LlmProviderConfig(
        provider="ollama",
        model="llama3",
        api_key="",
        base_url="http://localhost:11434",
    )

    payload = onboarding_status_rpc_payload(cfg, config_path=str(tmp_path / "active.toml"))

    assert payload == {
        "configPath": str(tmp_path / "active.toml"),
        "hasConfig": False,
        "llmConfigured": True,
        "llmSource": "none",
        "imageGenerationConfigured": False,
        "imageGenerationEnabled": False,
        "imageGenerationSource": "none",
        "imageGenerationProvider": "",
        "imageGenerationPrimary": "openai/gpt-image-1",
        "searchConfigured": True,
        "channelCount": 0,
        "channelsConfigured": False,
        "needsOnboarding": False,
        "warnings": [],
    }


def test_memory_embedding_provider_catalog_payload_owns_wire_shape() -> None:
    payload = memory_embedding_provider_catalog_payload()

    assert payload == [
        {
            "providerId": "auto",
            "label": "Auto (local BGE first)",
            "requiresApiKey": False,
            "requiresBaseUrl": False,
        },
        {
            "providerId": "local",
            "label": "Bundled BGE-small",
            "requiresApiKey": False,
            "requiresBaseUrl": False,
        },
        {
            "providerId": "openai",
            "label": "OpenAI",
            "requiresApiKey": True,
            "requiresBaseUrl": False,
        },
        {
            "providerId": "openai-compatible",
            "label": "OpenAI-compatible remote",
            "requiresApiKey": True,
            "requiresBaseUrl": False,
        },
        {
            "providerId": "ollama",
            "label": "Ollama",
            "requiresApiKey": False,
            "requiresBaseUrl": False,
        },
        {
            "providerId": "none",
            "label": "FTS-only",
            "requiresApiKey": False,
            "requiresBaseUrl": False,
        },
    ]


def test_onboarding_catalog_rpc_payload_composes_onboarding_catalogs() -> None:
    payload = onboarding_catalog_rpc_payload()

    assert set(payload) == {
        "providers",
        "channels",
        "searchProviders",
        "routerProfiles",
        "memoryEmbeddingProviders",
        "imageGenerationProviders",
    }
    assert {p["providerId"] for p in payload["memoryEmbeddingProviders"]} >= {
        "auto",
        "local",
        "openai",
        "ollama",
        "none",
    }
