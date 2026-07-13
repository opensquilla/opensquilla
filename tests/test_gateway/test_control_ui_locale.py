"""Control UI first-paint locale resolution + template injection (i18n v1)."""

import json
from html.parser import HTMLParser
from types import SimpleNamespace

from opensquilla.gateway import control_ui
from opensquilla.gateway.config import ControlUiConfig, GatewayConfig


def _req(accept_language: str | None = None) -> SimpleNamespace:
    headers: dict[str, str] = {}
    if accept_language is not None:
        headers["accept-language"] = accept_language
    return SimpleNamespace(headers=headers)


def test_default_is_en_with_no_header():
    assert control_ui._resolve_locale(GatewayConfig(), _req()) == "en"


def test_accept_language_zh_yields_zh_hans():
    cfg = GatewayConfig()
    assert control_ui._resolve_locale(cfg, _req("zh-CN,zh;q=0.9,en;q=0.8")) == "zh-Hans"


def test_accept_language_zh_hant_variants_yield_zh_hant():
    cfg = GatewayConfig()
    assert control_ui._resolve_locale(cfg, _req("zh-Hant,zh;q=0.9,en;q=0.8")) == "zh-Hant"
    assert control_ui._resolve_locale(cfg, _req("zh-TW,zh;q=0.9,en;q=0.8")) == "zh-Hant"
    assert control_ui._resolve_locale(cfg, _req("zh-HK,zh;q=0.9,en;q=0.8")) == "zh-Hant"
    assert control_ui._resolve_locale(cfg, _req("zh-MO,zh;q=0.9,en;q=0.8")) == "zh-Hant"


def test_accept_language_supported_non_en():
    cfg = GatewayConfig()
    assert control_ui._resolve_locale(cfg, _req("fr-FR,fr;q=0.9")) == "fr"
    assert control_ui._resolve_locale(cfg, _req("ja-JP")) == "ja"


def test_accept_language_unsupported_falls_back_to_en():
    cfg = GatewayConfig()
    # Korean is not a supported locale → default en
    assert control_ui._resolve_locale(cfg, _req("ko-KR,ko;q=0.9")) == "en"


def test_configured_default_wins_over_accept_language():
    cfg = GatewayConfig(control_ui=ControlUiConfig(default_locale="zh-Hans"))
    # An explicit non-en default is honored regardless of the browser header.
    assert control_ui._resolve_locale(cfg, _req("en-US,en;q=0.9")) == "zh-Hans"


def test_configured_zh_hant_default_wins_over_accept_language():
    cfg = GatewayConfig(control_ui=ControlUiConfig(default_locale="zh-Hant"))
    assert control_ui._resolve_locale(cfg, _req("en-US,en;q=0.9")) == "zh-Hant"


def test_garbage_accept_language_never_throws():
    cfg = GatewayConfig()
    assert control_ui._resolve_locale(cfg, _req(";;;,,q=junk")) == "en"


def test_config_clamps_arbitrary_locale_values():
    assert ControlUiConfig(default_locale="zh").default_locale == "zh-Hans"
    assert ControlUiConfig(default_locale="zh-CN").default_locale == "zh-Hans"
    assert ControlUiConfig(default_locale="zh-SG").default_locale == "zh-Hans"
    assert ControlUiConfig(default_locale="ZH-hans").default_locale == "zh-Hans"
    # An explicit Hans script subtag wins over a Traditional-default region.
    assert ControlUiConfig(default_locale="zh-Hans-TW").default_locale == "zh-Hans"
    # Traditional-圈 tags (explicit Hant, or bare Traditional-default regions,
    # any case, hyphen- or underscore-separated) clamp to zh-Hant.
    assert ControlUiConfig(default_locale="zh-Hant").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="zh-TW").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="zh-HK").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="zh-MO").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="ZH-tw").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="zh_TW").default_locale == "zh-Hant"
    assert ControlUiConfig(default_locale="fr").default_locale == "fr"
    assert ControlUiConfig(default_locale="ja-JP").default_locale == "ja"
    assert ControlUiConfig(default_locale="ko").default_locale == "en"
    assert ControlUiConfig().default_locale == "en"


class _OpenSquillaDataParser(HTMLParser):
    data_update: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "div" and attr_map.get("id") == "opensquilla-data":
            self.data_update = attr_map.get("data-update")


def _render(
    locale: str,
    update: dict | None = None,
    link_token: str = "",
    vite_js_url: str = "",
) -> str:
    tpl = control_ui._get_jinja_env().get_template("index.html")
    return tpl.render(
        version="0.0.0",
        ws_url="ws://host/ws",
        auth_mode="none",
        base_path="/control",
        config_path="",
        locale=locale,
        update=update,
        features={},
        link_token=link_token,
        vite_js_url=vite_js_url,
        vite_css_urls=[],
    )


def test_template_injects_zh_hans():
    html = _render("zh-Hans")
    assert '<html lang="zh-Hans">' in html
    assert 'data-locale="zh-Hans"' in html


def test_template_injects_zh_hant():
    html = _render("zh-Hant")
    assert '<html lang="zh-Hant">' in html
    assert 'data-locale="zh-Hant"' in html


def test_template_injects_en():
    html = _render("en")
    assert '<html lang="en">' in html
    assert 'data-locale="en"' in html


def test_template_escapes_update_json_for_data_attribute():
    html = _render(
        "en",
        update={
            "available": True,
            "latest": '0.5.0-"quoted"',
            "url": 'https://example.test/releases?note="quoted"&ok=1',
        },
    )
    parser = _OpenSquillaDataParser()
    parser.feed(html)

    assert parser.data_update is not None
    assert json.loads(parser.data_update) == {
        "available": True,
        "latest": '0.5.0-"quoted"',
        "url": 'https://example.test/releases?note="quoted"&ok=1',
    }


def test_bootstrap_context_includes_link_token_from_query_param():
    request = SimpleNamespace(
        headers={"host": "example.test"},
        url=SimpleNamespace(scheme="http"),
        query_params={"token": "link-token"},
    )

    ctx = control_ui._build_bootstrap_context(GatewayConfig(), request)

    assert ctx["link_token"] == "link-token"


def test_template_bootstraps_link_token_before_frontend_loads():
    html = _render(
        "en",
        link_token='tok-"quoted"&ok=1',
        vite_js_url="/control/static/dist/assets/app.js",
    )

    assert "key.indexOf('opensquilla.') === 0" not in html
    assert "localStorage.removeItem('opensquilla.wsUrl')" in html
    assert "sessionStorage.removeItem('opensquilla.wsToken')" in html
    assert "sessionStorage.removeItem('opensquilla.cachedAuth')" in html
    assert "key.indexOf('opensquilla.chat.draft:') === 0" in html
    assert "sessionStorage.setItem('opensquilla.wsToken'" in html
    assert "localStorage.setItem('opensquilla.wsUrl'" in html
    assert "ws://host/ws" in html
    assert 'tok-\\"quoted\\"&ok=1' in html
    assert "url.searchParams.delete('token')" in html
    assert html.index("localStorage.removeItem('opensquilla.wsUrl')") < html.index(
        "sessionStorage.setItem('opensquilla.wsToken'"
    )
    assert html.index("sessionStorage.setItem('opensquilla.wsToken'") < html.index(
        'type="module"'
    )
