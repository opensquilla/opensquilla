"""Provider runtime selector/catalog/image assembly service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from opensquilla.engine.pricing import refresh_live_prices
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.provider_runtime_sync import (
    sync_image_generation,
)
from opensquilla.provider.model_catalog import (
    ModelCatalog,
    openrouter_pricing_model_ids,
    refresh_openrouter_catalog_and_pricing,
)
from opensquilla.provider.runtime_config import resolve_llm_runtime_config
from opensquilla.provider.selector_materialization import (
    build_provider_selector_from_runtime,
)

log = structlog.get_logger(__name__)


@dataclass
class ProviderRuntimeServices:
    """Provider-facing services assembled during gateway startup."""

    provider_selector: Any
    model_catalog: ModelCatalog
    llm_runtime: Any
    base_url: str


def normalize_provider_base_url(base_url: str) -> str:
    """Normalize provider base URLs for selector/catalog consumers."""

    if base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


async def build_provider_runtime_services(
    config: GatewayConfig,
    *,
    provider_selector: Any = None,
) -> ProviderRuntimeServices:
    """Build provider selector, model catalog, and image runtime state."""

    llm_runtime = resolve_llm_runtime_config(config)
    api_key = llm_runtime.api_key
    resolved_base = normalize_provider_base_url(llm_runtime.base_url)

    if provider_selector is None and api_key:
        provider_selector = build_provider_selector_from_runtime(
            llm_runtime,
            base_url=resolved_base,
        )
        log.info(
            "build_services.provider_ready",
            provider=llm_runtime.provider,
            model=llm_runtime.model,
        )

    model_catalog = ModelCatalog()
    if api_key and config.llm.provider == "openrouter":
        await refresh_openrouter_catalog_and_pricing(
            model_catalog,
            api_key=api_key,
            base_url=resolved_base,
            proxy=llm_runtime.proxy or "",
            pricing_model_ids=openrouter_pricing_model_ids(
                config.llm.model,
                getattr(getattr(config, "squilla_router", None), "tiers", {}),
            ),
            refresh_prices=refresh_live_prices,
        )

    try:
        sync_image_generation(config)
    except Exception as e:
        log.warning("build_services.image_generation_config_failed", error=str(e))

    return ProviderRuntimeServices(
        provider_selector=provider_selector,
        model_catalog=model_catalog,
        llm_runtime=llm_runtime,
        base_url=resolved_base,
    )
