"""Process-wide search runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchRuntimeConfig:
    provider_name: str = "duckduckgo"
    max_results: int = 5
    api_key: str = ""
    proxy: str = ""
    use_env_proxy: bool = False
    fallback_policy: str = "off"
    diagnostics: bool = False

    def provider_kwargs(self, provider_name: str) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "proxy": self.proxy,
            "use_env_proxy": self.use_env_proxy,
        }
        if provider_name == "brave" and self.api_key:
            kwargs["api_key"] = self.api_key
        if self.diagnostics or provider_name == "duckduckgo":
            kwargs["diagnostics"] = self.diagnostics
        return kwargs


_runtime = SearchRuntimeConfig()


def configure_search(
    provider_name: str,
    max_results: int = 5,
    *,
    api_key: str = "",
    proxy: str = "",
    use_env_proxy: bool = False,
    fallback_policy: str = "off",
    diagnostics: bool = False,
) -> None:
    global _runtime
    _runtime = SearchRuntimeConfig(
        provider_name=provider_name,
        max_results=max_results,
        api_key=api_key.strip(),
        proxy=proxy.strip(),
        use_env_proxy=bool(use_env_proxy),
        fallback_policy=fallback_policy if fallback_policy in {"off", "network"} else "off",
        diagnostics=bool(diagnostics),
    )


def reset_search_runtime() -> None:
    """Restore process-wide search configuration to boot defaults."""
    configure_search("duckduckgo")


def current_search_runtime() -> SearchRuntimeConfig:
    return _runtime


def get_active_provider() -> str:
    return _runtime.provider_name


def is_search_api_key_configured(provider_name: str | None = None) -> bool:
    provider = provider_name or _runtime.provider_name
    if provider == _runtime.provider_name and _runtime.api_key:
        return True
    try:
        from opensquilla.search.registry import get_provider_spec

        spec = get_provider_spec(provider)
    except Exception:
        return False
    return bool(spec.env_key and os.environ.get(spec.env_key))


def get_search_proxy() -> str:
    return _runtime.proxy


def get_search_use_env_proxy() -> bool:
    return _runtime.use_env_proxy


def get_search_fallback_policy() -> str:
    return _runtime.fallback_policy


def get_search_diagnostics() -> bool:
    return _runtime.diagnostics


def search_provider_kwargs(provider_name: str) -> dict[str, object]:
    return _runtime.provider_kwargs(provider_name)

