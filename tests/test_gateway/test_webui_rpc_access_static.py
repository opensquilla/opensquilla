from __future__ import annotations

from pathlib import Path

GATEWAY_ROOT = Path("src/opensquilla/gateway")
TEMPLATE = GATEWAY_ROOT / "templates/index.html"
RPC_ACCESS_JS = GATEWAY_ROOT / "static/js/rpc_access.js"
VIEWS_DIR = GATEWAY_ROOT / "static/js/views"


def test_webui_rpc_access_boundary_loads_between_rpc_client_and_views() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    rpc_client_idx = template.index("static/js/rpc.js")
    rpc_access_idx = template.index("static/js/rpc_access.js")
    first_view_idx = template.index("static/js/views/overview.js")

    assert rpc_client_idx < rpc_access_idx < first_view_idx


def test_webui_views_get_rpc_client_through_access_boundary() -> None:
    boundary = RPC_ACCESS_JS.read_text(encoding="utf-8")

    assert "window.WebUiRpc = WebUiRpc;" in boundary
    for exported_name in ("client", "call", "waitForConnection", "on", "policy"):
        assert exported_name in boundary

    offenders = []
    for path in sorted(VIEWS_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        if "App.getRpc()" in source:
            offenders.append(path.name)

    assert offenders == []
