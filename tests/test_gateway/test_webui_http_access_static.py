from __future__ import annotations

from pathlib import Path

GATEWAY_ROOT = Path("src/opensquilla/gateway")
TEMPLATE = GATEWAY_ROOT / "templates/index.html"
HTTP_ACCESS_JS = GATEWAY_ROOT / "static/js/http_access.js"
STATIC_JS = GATEWAY_ROOT / "static/js"
APPROVAL_MONITOR_JS = STATIC_JS / "approval_monitor.js"


def test_webui_http_access_boundary_loads_before_http_callers() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    rpc_access_idx = template.index("static/js/rpc_access.js")
    http_access_idx = template.index("static/js/http_access.js")
    approval_monitor_idx = template.index("static/js/approval_monitor.js")
    first_view_idx = template.index("static/js/views/overview.js")

    assert rpc_access_idx < http_access_idx < approval_monitor_idx < first_view_idx


def test_webui_http_access_boundary_owns_fetch_and_auth_headers() -> None:
    boundary = HTTP_ACCESS_JS.read_text(encoding="utf-8")

    assert "window.WebUiHttp = WebUiHttp;" in boundary
    assert "fetch(url" in boundary
    assert "getAuthToken" in boundary
    assert "Authorization" in boundary
    for exported_name in (
        "request",
        "getJson",
        "postJson",
        "postJsonResponse",
        "download",
        "upload",
        "getPendingApprovals",
        "resolveApproval",
    ):
        assert exported_name in boundary

    direct_fetch_callers = []
    for path in sorted(STATIC_JS.glob("**/*.js")):
        if path.name == "http_access.js":
            continue
        source = path.read_text(encoding="utf-8")
        if "fetch(" in source:
            direct_fetch_callers.append(path.relative_to(STATIC_JS).as_posix())

    assert direct_fetch_callers == []


def test_approval_monitor_uses_http_access_approval_helpers() -> None:
    boundary = HTTP_ACCESS_JS.read_text(encoding="utf-8")
    monitor = APPROVAL_MONITOR_JS.read_text(encoding="utf-8")

    assert "function getPendingApprovals()" in boundary
    assert "return getJson('/api/approvals', { cache: 'no-store' });" in boundary
    assert "function resolveApproval(body)" in boundary
    assert "return postJson('/api/approvals/resolve', body);" in boundary

    assert "WebUiHttp.getPendingApprovals()" in monitor
    assert "WebUiHttp.resolveApproval(body)" in monitor
    assert "'/api/approvals'" not in monitor
    assert "'/api/approvals/resolve'" not in monitor
