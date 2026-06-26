from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_search_docs_describe_runtime_provider_matrix() -> None:
    docs = "\n".join(
        [
            _read("docs/search.md"),
            _read("docs/configuration.md"),
            _read("docs/troubleshooting.md"),
            _read("README.md"),
            _read("README.product.md"),
            _read("opensquilla.toml.example"),
        ]
    )

    for expected in [
        "Bocha",
        "BOCHA_SEARCH_API_KEY",
        "Tavily",
        "TAVILY_API_KEY",
        "Exa",
        "EXA_API_KEY",
        "DuckDuckGo",
        "no-key",
        "partial-key",
        "all-key",
        "search_api_key_env",
        "search_fallback_policy",
        "search_diagnostics",
    ]:
        assert expected in docs

    assert '"duckduckgo", "bocha", "brave", "tavily", or "exa"' in docs
    assert "web search (DuckDuckGo, Bocha, Brave, Tavily, or Exa)" in docs


def test_desktop_search_surfaces_use_shared_runtime_provider_catalog() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    selector_vue = _read("opensquilla-webui/src/components/settings/SearchProviderSelector.vue")
    settings_vue = _read("opensquilla-webui/src/views/desktop/DesktopSettingsView.vue")
    platform_types = _read("opensquilla-webui/src/platform/types.ts")

    for expected in [
        "SEARCH_PROVIDER_CATALOG",
        "BOCHA_SEARCH_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "Bocha",
        "Tavily",
        "Exa",
    ]:
        assert expected in main_ts

    old_normalizer = (
        "return String(raw || '').trim().toLowerCase() === 'brave' "
        "? 'brave' : 'duckduckgo'"
    )
    assert old_normalizer not in main_ts
    assert "searchProviders: SEARCH_PROVIDER_CATALOG" in main_ts
    assert "searchProviders?: SearchProviderOption[]" in platform_types

    assert "providers:" in selector_vue
    assert "v-for=\"provider in providers\"" in selector_vue
    assert "defineModel<string>" in selector_vue
    assert "defineModel<'duckduckgo' | 'brave'>" not in selector_vue

    assert "settings.searchProviders" in settings_vue
    assert "searchProviderRequiresKey" in settings_vue
    assert "form.searchProvider === 'brave'" not in settings_vue
