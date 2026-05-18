"""Gateway boot compatibility facade for Provider runtime assembly."""

from __future__ import annotations

from opensquilla.gateway.provider_runtime_assembly import (
    ProviderRuntimeServices,
    build_provider_runtime_services,
    normalize_provider_base_url,
)

__all__ = [
    "ProviderRuntimeServices",
    "build_provider_runtime_services",
    "normalize_provider_base_url",
]
