"""Extension-service runtime composition boundaries."""

from __future__ import annotations

from opensquilla.extension_services.gateway_runtime import (
    ExtensionServicesRuntime,
    build_extension_services_runtime,
)

__all__ = [
    "ExtensionServicesRuntime",
    "build_extension_services_runtime",
]
