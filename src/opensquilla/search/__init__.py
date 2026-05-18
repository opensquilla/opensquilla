"""Web search abstraction layer."""

from opensquilla.search.execution import (
    run_search_payload,
    search_runtime_status,
)
from opensquilla.search.registry import get_provider, register_provider
from opensquilla.search.rpc_payload import search_status_rpc_payload
from opensquilla.search.runtime import (
    SearchRuntimeConfig,
    configure_search,
    current_search_runtime,
    ensure_builtin_search_providers,
    reset_search_runtime,
    sync_search_runtime_from_config,
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
    "ensure_builtin_search_providers",
    "get_provider",
    "register_provider",
    "reset_search_runtime",
    "run_search_payload",
    "search_runtime_status",
    "search_status_rpc_payload",
    "sync_search_runtime_from_config",
]
