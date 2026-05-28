"""Smoke tests for Cache-Control on /control/static/* responses.

The Control UI serves vendored JS/CSS through a `_CachedStaticFiles` subclass
(see ``opensquilla.gateway.control_ui``). These tests pin the header semantics
so a refactor that drops the subclass — or breaks the env-rollback knob —
shows up immediately.
"""

from __future__ import annotations

import os

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from opensquilla.gateway.config import GatewayConfig
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
