"""Shared onboarding setup engine for CLI and RPC paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.channel_specs import channel_catalog_payload
from opensquilla.onboarding.config_store import PersistResult, load_config, persist_config
from opensquilla.onboarding.image_generation_specs import (
    image_generation_provider_catalog_payload,
)
from opensquilla.onboarding.mutations import (
    MutationResult,
    upsert_channel,
    upsert_image_generation_provider,
    upsert_llm_provider,
    upsert_memory_embedding,
    upsert_router,
    upsert_search_provider,
)
from opensquilla.onboarding.next_steps import format_next_steps
from opensquilla.onboarding.provider_specs import provider_catalog_payload
from opensquilla.onboarding.router_specs import router_catalog_payload
from opensquilla.onboarding.search_specs import search_provider_catalog_payload
from opensquilla.onboarding.status import OnboardingStatus, get_onboarding_status


def _memory_embedding_catalog_payload() -> list[dict[str, Any]]:
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


class SetupEngine:
    """Apply onboarding sections against one in-memory config before persisting."""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        *,
        path: str | Path | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path is not None else None
        self.config = config if config is not None else load_config(self.path)
        self.restart_required = False
        self.warnings: list[str] = []

    def status(self) -> OnboardingStatus:
        return get_onboarding_status(self.config)

    def catalog(self, section: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "providers": provider_catalog_payload(),
            "routerProfiles": router_catalog_payload(),
            "searchProviders": search_provider_catalog_payload(),
            "channels": channel_catalog_payload(),
            "imageGenerationProviders": image_generation_provider_catalog_payload(),
            "memoryEmbeddingProviders": _memory_embedding_catalog_payload(),
        }
        if section is None:
            return payload
        normalized = section.strip().lower()
        aliases = {
            "provider": "providers",
            "providers": "providers",
            "router": "routerProfiles",
            "search": "searchProviders",
            "channels": "channels",
            "channel": "channels",
            "image-generation": "imageGenerationProviders",
            "image_generation": "imageGenerationProviders",
            "memory-embedding": "memoryEmbeddingProviders",
            "memory_embedding": "memoryEmbeddingProviders",
        }
        key = aliases.get(normalized)
        if key is None:
            raise ValueError(f"unknown setup section: {section!r}")
        return {key: payload[key]}

    def apply(self, section: str, payload: dict[str, Any]) -> MutationResult:
        normalized = section.strip().lower()
        if normalized in {"provider", "providers"}:
            res = upsert_llm_provider(
                self.config,
                provider_id=str(payload["providerId"]),
                model=str(payload.get("model", "")),
                api_key=str(payload.get("apiKey", "")),
                api_key_env=str(payload.get("apiKeyEnv", "")),
                base_url=str(payload.get("baseUrl", "")),
                proxy=str(payload.get("proxy", "")),
            )
        elif normalized == "router":
            res = upsert_router(
                self.config,
                mode=str(payload.get("mode", "recommended")),
                default_tier=payload.get("defaultTier"),
                tiers=payload.get("tiers"),
            )
        elif normalized == "search":
            res = upsert_search_provider(
                self.config,
                provider_id=str(payload["providerId"]),
                api_key=str(payload.get("apiKey", "")),
                api_key_env=str(payload.get("apiKeyEnv", "")),
                max_results=int(payload.get("maxResults", 5)),
                proxy=str(payload.get("proxy", "")),
                use_env_proxy=bool(payload.get("useEnvProxy", False)),
                fallback_policy=str(payload.get("fallbackPolicy", "off")),
                diagnostics=bool(payload.get("diagnostics", False)),
            )
        elif normalized in {"channel", "channels"}:
            entry = payload.get("entry", payload)
            if not isinstance(entry, dict):
                raise ValueError("channel payload must contain an entry object")
            res = upsert_channel(self.config, entry_payload=entry)
        elif normalized in {"image-generation", "image_generation"}:
            res = upsert_image_generation_provider(
                self.config,
                provider_id=str(payload["providerId"]),
                primary=str(payload.get("primary", "")),
                api_key=str(payload.get("apiKey", "")),
                api_key_env=str(payload.get("apiKeyEnv", "")),
                base_url=str(payload.get("baseUrl", "")),
                enabled=bool(payload.get("enabled", True)),
            )
        elif normalized in {"memory-embedding", "memory_embedding"}:
            res = upsert_memory_embedding(
                self.config,
                provider=str(payload["providerId"]),
                model=payload.get("model"),
                api_key=payload.get("apiKey"),
                base_url=payload.get("baseUrl"),
                onnx_dir=payload.get("onnxDir"),
            )
        else:
            raise ValueError(f"unknown setup section: {section!r}")

        self.config = res.config
        self.restart_required = self.restart_required or res.restart_required
        self.warnings.extend(res.warnings)
        return res

    def persist(self, *, backup: bool = True) -> PersistResult:
        return persist_config(
            self.config,
            path=self.path,
            backup=backup,
            restart_required=self.restart_required,
        )

    def preview_next_steps(self) -> str:
        return format_next_steps(self.config, config_path=self.path)
