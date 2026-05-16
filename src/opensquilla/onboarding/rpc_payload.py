"""RPC payload builders for onboarding surfaces."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.channel_specs import channel_catalog_payload
from opensquilla.onboarding.image_generation_specs import (
    image_generation_provider_catalog_payload,
)
from opensquilla.onboarding.provider_specs import provider_catalog_payload
from opensquilla.onboarding.router_specs import router_catalog_payload
from opensquilla.onboarding.search_specs import search_provider_catalog_payload
from opensquilla.onboarding.status import get_onboarding_status


def onboarding_status_rpc_payload(
    config: GatewayConfig,
    *,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Build the RPC wire payload for ``onboarding.status``."""

    status = get_onboarding_status(config)
    return {
        "configPath": config_path or status.config_path,
        "hasConfig": status.has_config,
        "llmConfigured": status.llm_configured,
        "llmSource": status.llm_source,
        "imageGenerationConfigured": status.image_generation_configured,
        "imageGenerationEnabled": status.image_generation_enabled,
        "imageGenerationSource": status.image_generation_source,
        "imageGenerationProvider": status.image_generation_provider,
        "imageGenerationPrimary": status.image_generation_primary,
        "searchConfigured": status.search_configured,
        "channelCount": status.channel_count,
        "channelsConfigured": status.channels_configured,
        "needsOnboarding": status.needs_onboarding,
        "warnings": list(status.warnings),
    }


def memory_embedding_provider_catalog_payload() -> list[dict[str, Any]]:
    """Build the memory embedding provider catalog wire payload."""

    return [
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


def onboarding_catalog_rpc_payload() -> dict[str, Any]:
    """Build the RPC wire payload for ``onboarding.catalog``."""

    return {
        "providers": provider_catalog_payload(),
        "channels": channel_catalog_payload(),
        "searchProviders": search_provider_catalog_payload(),
        "routerProfiles": router_catalog_payload(),
        "memoryEmbeddingProviders": memory_embedding_provider_catalog_payload(),
        "imageGenerationProviders": image_generation_provider_catalog_payload(),
    }


__all__ = [
    "memory_embedding_provider_catalog_payload",
    "onboarding_catalog_rpc_payload",
    "onboarding_status_rpc_payload",
]
