"""Web search abstraction layer."""

from opensquilla.search.registry import get_provider, register_provider
from opensquilla.search.runtime import (
    SearchRuntimeConfig,
    configure_search,
    current_search_runtime,
    reset_search_runtime,
)
from opensquilla.search.types import (
    SearchProvider,
    SearchProviderError,
    SearchProviderSpec,
    SearchRequest,
    SearchResult,
)

__all__ = [
    "SearchResult",
    "SearchRequest",
    "SearchProviderSpec",
    "SearchProviderError",
    "SearchProvider",
    "SearchRuntimeConfig",
    "configure_search",
    "current_search_runtime",
    "get_provider",
    "register_provider",
    "reset_search_runtime",
]
