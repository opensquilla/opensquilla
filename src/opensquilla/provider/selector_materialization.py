"""Provider selector materialization from effective runtime config."""

from __future__ import annotations

from typing import Any

from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig

__all__ = [
    "build_provider_selector_from_runtime",
    "provider_config_from_runtime",
]


def provider_config_from_runtime(
    runtime: Any,
    *,
    base_url: str | None = None,
) -> ProviderConfig:
    """Build provider selector config from an effective LLM runtime object."""

    return ProviderConfig(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        base_url=runtime.base_url if base_url is None else base_url,
        proxy=runtime.proxy,
        provider_routing=runtime.provider_routing,
    )


def build_provider_selector_from_runtime(
    runtime: Any,
    *,
    base_url: str | None = None,
) -> ModelSelector:
    """Create a provider selector from an effective LLM runtime object."""

    return ModelSelector(
        SelectorConfig(
            primary=provider_config_from_runtime(runtime, base_url=base_url),
        )
    )
