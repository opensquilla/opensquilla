"""Provider runtime synchronization helpers for gateway config RPCs."""

from __future__ import annotations

from typing import Any

from opensquilla.provider.selector_materialization import (
    build_provider_selector_from_runtime,
    provider_config_from_runtime,
)

__all__ = [
    "build_provider_selector_from_runtime",
    "clear_runtime_secret_paths",
    "inherit_runtime_secrets",
    "provider_config_from_runtime",
    "sync_image_generation",
    "sync_provider_selector",
]


def inherit_runtime_secrets(source: Any, target: Any) -> None:
    """Carry runtime-only secret values from one config object to another."""

    if hasattr(target, "inherit_runtime_secrets") and source is not None:
        target.inherit_runtime_secrets(source)


def clear_runtime_secret_paths(config: Any, paths: set[str]) -> None:
    """Clear runtime-only secret values for explicitly changed config paths."""

    if not hasattr(config, "clear_runtime_secret"):
        return
    for path in paths:
        config.clear_runtime_secret(path)


def sync_provider_selector(ctx: Any, config: Any) -> None:
    """Sync the gateway provider selector from the effective runtime config."""

    llm_cfg = getattr(config, "llm", None)
    if llm_cfg is None:
        return

    from opensquilla.provider.runtime_config import resolve_llm_runtime_config

    runtime = resolve_llm_runtime_config(config)
    selector = getattr(ctx, "provider_selector", None)
    if selector is None or not hasattr(selector, "sync_primary"):
        return

    selector.sync_primary(provider_config_from_runtime(runtime))


def sync_image_generation(config: Any) -> None:
    """Sync image-generation runtime settings from the effective config."""

    from opensquilla.provider.image_generation_runtime import configure_image_generation

    configure_image_generation(
        getattr(config, "image_generation", None),
        llm_config=getattr(config, "llm", None),
    )
