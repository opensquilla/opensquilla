from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "opensquilla" / "gateway" / "static"
APP_JS = STATIC / "js" / "app.js"
ICONS_JS = STATIC / "js" / "icons.js"
TEMPLATE = ROOT / "src" / "opensquilla" / "gateway" / "templates" / "index.html"
SANDBOX_JS = STATIC / "js" / "views" / "sandbox.js"
SANDBOX_CSS = STATIC / "css" / "views" / "sandbox.css"
APPROVALS_JS = STATIC / "js" / "views" / "approvals.js"
APPROVALS_CSS = STATIC / "css" / "views" / "approvals.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sandbox_route_replaces_approvals_route() -> None:
    app = _read(APP_JS)

    assert "Router.register('/sandbox'" in app
    assert "Router.register('/approvals'" not in app


def test_sidebar_links_to_sandbox_and_not_approvals() -> None:
    app = _read(APP_JS)

    assert 'data-path="/sandbox"' in app
    assert 'data-path="/approvals"' not in app


def test_template_loads_sandbox_assets_not_approvals_view_assets() -> None:
    template = _read(TEMPLATE)

    assert "/static/css/views/sandbox.css" in template
    assert "/static/js/views/sandbox.js" in template
    assert "/static/css/views/approvals.css" not in template
    assert "/static/js/views/approvals.js" not in template


def test_sandbox_assets_define_icon_and_control_sections() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)
    icons = _read(ICONS_JS)

    assert "icons.sandbox" in icons
    assert "Status" in sandbox_js
    assert "Workspace & Mounts" in sandbox_js
    assert "Managed Network" in sandbox_js
    assert ("Recent Decisions" in sandbox_js) or ("Sandbox Rules" in sandbox_js)
    assert "Approval activity" not in sandbox_js
    assert ".sandbox-stage" in sandbox_css


def test_standalone_approvals_view_assets_are_removed() -> None:
    assert not APPROVALS_JS.exists()
    assert not APPROVALS_CSS.exists()
