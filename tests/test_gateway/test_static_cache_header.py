"""Smoke tests for Cache-Control on /control/static/* responses.

The Control UI serves vendored JS/CSS through a `_CachedStaticFiles` subclass
(see ``opensquilla.gateway.control_ui``). These tests pin the header semantics
so a refactor that drops the subclass — or breaks the env-rollback knob —
shows up immediately.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.testclient import TestClient

from opensquilla.gateway import control_ui
from opensquilla.gateway.config import ControlUiConfig, GatewayConfig
from opensquilla.gateway.control_ui import create_control_ui_routes


@pytest.fixture
def _app(monkeypatch: pytest.MonkeyPatch) -> Starlette:
    monkeypatch.delenv("OPENSQUILLA_STATIC_NO_CACHE", raising=False)
    config = GatewayConfig()
    config.control_ui.enabled = True
    routes = create_control_ui_routes(config)
    return Starlette(routes=routes)


def test_static_asset_carries_long_cache_control(_app: Starlette) -> None:
    client = TestClient(_app)
    response = client.get("/control/static/js/app.js")
    assert response.status_code == 200, response.text
    cache = response.headers.get("Cache-Control", "")
    assert "max-age=2592000" in cache, cache
    assert "public" in cache, cache


def test_control_ui_bootstrap_includes_config_path(tmp_path) -> None:
    config = GatewayConfig()
    config.config_path = str(tmp_path / "OpenSquilla Config.toml")
    config.control_ui.enabled = True
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)

    response = client.get("/control/")

    assert response.status_code == 200
    assert 'data-config-path="' in response.text
    assert str(config.config_path) in response.text


def test_control_ui_vite_asset_urls_use_configured_base_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text(
        '<script type="module" crossorigin src="./assets/index.js"></script>'
        '<link rel="stylesheet" crossorigin href="./assets/index.css">',
        encoding="utf-8",
    )
    monkeypatch.setattr(control_ui, "_DIST_DIR", tmp_path)

    js_url, css_url = control_ui._read_vite_assets("/ops")

    assert js_url == "/ops/static/dist/assets/index.js"
    assert css_url == "/ops/static/dist/assets/index.css"


def test_control_ui_rebases_hard_coded_vite_base_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text(
        '<script type="module" src="/control/static/dist/assets/index.js"></script>'
        '<link rel="stylesheet" href="/control/static/dist/assets/index.css">',
        encoding="utf-8",
    )
    monkeypatch.setattr(control_ui, "_DIST_DIR", tmp_path)

    js_url, css_url = control_ui._read_vite_assets("/custom")

    assert js_url == "/custom/static/dist/assets/index.js"
    assert css_url == "/custom/static/dist/assets/index.css"


def test_control_ui_defaults_to_vue_bootstrap(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "index.html").write_text(
        '<script type="module" crossorigin src="./assets/index.js"></script>'
        '<link rel="stylesheet" crossorigin href="./assets/index.css">',
        encoding="utf-8",
    )
    monkeypatch.setattr(control_ui, "_DIST_DIR", tmp_path)
    config = GatewayConfig()
    config.control_ui.enabled = True
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)

    response = client.get("/control/")

    assert response.status_code == 200
    assert '/control/static/dist/assets/index.js' in response.text
    assert '/control/static/js/app.js' not in response.text


def test_control_ui_legacy_frontend_uses_static_bootstrap() -> None:
    config = GatewayConfig()
    config.control_ui.enabled = True
    config.control_ui.frontend = "legacy"
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)

    response = client.get("/control/")

    assert response.status_code == 200
    assert '/control/static/js/app.js' in response.text
    assert '/control/static/dist/assets/' not in response.text


def test_control_ui_frontend_reads_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_CONTROL_UI_FRONTEND", "legacy")

    config = GatewayConfig()

    assert config.control_ui.frontend == "legacy"


def test_control_ui_frontend_reads_toml_config(tmp_path) -> None:
    config_path = tmp_path / "opensquilla.toml"
    config_path.write_text(
        '[control_ui]\nfrontend = "legacy"\n',
        encoding="utf-8",
    )

    config = GatewayConfig.load_from_toml(config_path)

    assert config.control_ui.frontend == "legacy"


def test_control_ui_frontend_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        ControlUiConfig(frontend="retro")


def test_control_ui_legacy_frontend_uses_configured_base_path() -> None:
    config = GatewayConfig()
    config.control_ui.enabled = True
    config.control_ui.base_path = "/ops"
    config.control_ui.frontend = "legacy"
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)

    response = client.get("/ops/")

    assert response.status_code == 200
    assert '/ops/static/js/app.js' in response.text
    assert '/control/static/js/app.js' not in response.text


def test_control_ui_bootstrap_ws_url_uses_client_reachable_wildcard_host() -> None:
    config = GatewayConfig()
    config.host = "0.0.0.0"
    config.port = 20002
    config.control_ui.enabled = True
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)

    response = client.get("/control/")

    assert response.status_code == 200
    assert 'data-ws-url="ws://127.0.0.1:20002/ws"' in response.text
    assert 'data-ws-url="ws://0.0.0.0:20002/ws"' not in response.text


def test_env_rollback_disables_cache_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OPENSQUILLA_STATIC_NO_CACHE=1 must completely skip the Cache-Control
    # header so a release with a static-cache problem can be defused without
    # a redeploy.
    monkeypatch.setenv("OPENSQUILLA_STATIC_NO_CACHE", "1")
    config = GatewayConfig()
    config.control_ui.enabled = True
    app = Starlette(routes=create_control_ui_routes(config))
    client = TestClient(app)
    response = client.get("/control/static/js/app.js")
    assert response.status_code == 200
    # Either header is absent or it does not advertise our long max-age.
    cache = response.headers.get("Cache-Control", "")
    assert "max-age=2592000" not in cache


def test_nonexistent_path_does_not_add_header(_app: Starlette) -> None:
    client = TestClient(_app)
    response = client.get("/control/static/js/does-not-exist-12345.js")
    # 404 must not be tagged with a long-cache header — clients would otherwise
    # remember a "missing" asset for 30 days.
    assert response.status_code == 404
    assert "max-age=2592000" not in response.headers.get("Cache-Control", "")


def _cleanup_env() -> None:
    os.environ.pop("OPENSQUILLA_STATIC_NO_CACHE", None)
