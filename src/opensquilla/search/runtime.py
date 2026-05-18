"""Process-wide search runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


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


def ensure_builtin_search_providers() -> None:
    """Register built-in search providers."""
    import opensquilla.search.providers.brave  # noqa: F401
    import opensquilla.search.providers.duckduckgo  # noqa: F401


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


def _search_config_value(config: Any, name: str, default: Any) -> Any:
    return getattr(config, name, default)


def _search_api_key_from_config(config: Any, provider_name: str) -> str:
    configured_key = str(_search_config_value(config, "search_api_key", "") or "").strip()
    if configured_key:
        return configured_key

    from opensquilla.search.registry import get_provider_spec

    env_key = str(_search_config_value(config, "search_api_key_env", "") or "").strip()
    if not env_key:
        env_key = get_provider_spec(provider_name).env_key or ""
    return os.environ.get(env_key, "") if env_key else ""


def sync_search_runtime_from_config(config: Any) -> SearchRuntimeConfig:
    """Apply gateway/onboarding search settings to the process runtime."""
    ensure_builtin_search_providers()
    provider = str(_search_config_value(config, "search_provider", "duckduckgo") or "duckduckgo")
    search_api_key = _search_api_key_from_config(config, provider)
    if provider == "duckduckgo" and (search_api_key or os.environ.get("BRAVE_SEARCH_API_KEY")):
        provider = "brave"

    configure_search(
        provider_name=provider,
        max_results=int(_search_config_value(config, "search_max_results", 5) or 5),
        api_key=search_api_key,
        proxy=str(_search_config_value(config, "search_proxy", "") or ""),
        use_env_proxy=bool(_search_config_value(config, "search_use_env_proxy", False)),
        fallback_policy=str(_search_config_value(config, "search_fallback_policy", "off") or "off"),
        diagnostics=bool(_search_config_value(config, "search_diagnostics", False)),
    )
    return current_search_runtime()


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
