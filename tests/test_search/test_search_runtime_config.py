from __future__ import annotations

import sys

from opensquilla.search.providers.exa import ExaSearchProvider
from opensquilla.search.runtime_config import SearchRuntimeConfig, resolve_search_runtime
from opensquilla.search.types import SearchOptions


def _clear_search_env(monkeypatch) -> None:
    for key in ("BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "CUSTOM_EXA_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_resolver_no_key_default_uses_duckduckgo_without_keyed_attempts(monkeypatch) -> None:
    _clear_search_env(monkeypatch)

    runtime = resolve_search_runtime(SearchRuntimeConfig(provider="duckduckgo"))

    assert runtime.provider_order(SearchOptions(query="q")) == ("duckduckgo",)
    duckduckgo = runtime.provider_config("duckduckgo")
    assert duckduckgo.available is True
    assert duckduckgo.credential_source == "none"
    assert runtime.provider_config("tavily").available is False


def test_resolver_uses_configured_env_for_active_provider(monkeypatch) -> None:
    _clear_search_env(monkeypatch)
    monkeypatch.setenv("CUSTOM_EXA_KEY", "env-exa-key")

    runtime = resolve_search_runtime(
        SearchRuntimeConfig(provider="exa", api_key_env="CUSTOM_EXA_KEY")
    )

    exa = runtime.provider_config("exa")
    assert exa.available is True
    assert exa.credential_source == "configured_env"
    assert exa.provider_kwargs()["api_key"] == "env-exa-key"


def test_resolver_prefers_configured_exa_key_over_configured_env(monkeypatch) -> None:
    _clear_search_env(monkeypatch)
    monkeypatch.setenv("CUSTOM_EXA_KEY", "env-exa-key")

    runtime = resolve_search_runtime(
        SearchRuntimeConfig(
            provider="exa",
            api_key="configured-exa-key",
            api_key_env="CUSTOM_EXA_KEY",
        )
    )

    exa = runtime.provider_config("exa")
    assert exa.available is True
    assert exa.credential_source == "configured"
    assert exa.provider_kwargs()["api_key"] == "configured-exa-key"

    provider = runtime.build_provider("exa")
    assert isinstance(provider, ExaSearchProvider)
    assert provider._api_key == "configured-exa-key"


def test_resolver_partial_key_orders_configured_provider_then_duckduckgo(monkeypatch) -> None:
    _clear_search_env(monkeypatch)

    runtime = resolve_search_runtime(
        SearchRuntimeConfig(provider="brave", api_key="brave-key")
    )

    assert runtime.provider_order(SearchOptions(query="q")) == ("brave", "duckduckgo")


def test_resolver_all_key_mode_tie_breakers(monkeypatch) -> None:
    _clear_search_env(monkeypatch)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("EXA_API_KEY", "exa-key")

    runtime = resolve_search_runtime(SearchRuntimeConfig(provider="duckduckgo"))

    assert runtime.provider_order(SearchOptions(query="q")) == (
        "tavily",
        "brave",
        "exa",
        "duckduckgo",
    )
    assert runtime.provider_order(SearchOptions(query="q", mode="technical")) == (
        "exa",
        "brave",
        "tavily",
        "duckduckgo",
    )
    assert runtime.provider_order(SearchOptions(query="q", recency="week")) == (
        "tavily",
        "brave",
        "exa",
        "duckduckgo",
    )
    assert runtime.provider_order(SearchOptions(query="q", mode="news")) == (
        "tavily",
        "brave",
        "exa",
        "duckduckgo",
    )


def test_resolver_provider_kwargs_include_proxy_and_diagnostics(monkeypatch) -> None:
    _clear_search_env(monkeypatch)

    runtime = resolve_search_runtime(
        SearchRuntimeConfig(
            provider="duckduckgo",
            proxy="http://proxy.test",
            use_env_proxy=True,
            diagnostics=True,
        )
    )

    kwargs = runtime.provider_config("duckduckgo").provider_kwargs()
    assert kwargs == {
        "proxy": "http://proxy.test",
        "use_env_proxy": True,
        "diagnostics": True,
    }


def test_runtime_build_provider_registers_builtin_providers_in_fresh_process(
    monkeypatch,
) -> None:
    import opensquilla.search.registry as registry

    for module_name in (
        "opensquilla.search.providers.tavily",
        "opensquilla.search.providers.brave",
        "opensquilla.search.providers.exa",
        "opensquilla.search.providers.duckduckgo",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(registry, "_providers", {})

    runtime = resolve_search_runtime(
        SearchRuntimeConfig(provider="tavily", api_key="tavily-key")
    )

    provider = runtime.build_provider("tavily")

    assert provider.name == "tavily"
