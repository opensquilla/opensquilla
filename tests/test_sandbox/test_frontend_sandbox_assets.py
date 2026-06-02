from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "opensquilla" / "gateway" / "static"
APP_JS = STATIC / "js" / "app.js"
ICONS_JS = STATIC / "js" / "icons.js"
TEMPLATE = ROOT / "src" / "opensquilla" / "gateway" / "templates" / "index.html"
APPROVAL_MONITOR_JS = STATIC / "js" / "approval_monitor.js"
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


def test_approval_monitor_inline_button_uses_modal_polling_path() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)
    start = monitor.index("inline.addEventListener('click'")
    handler = monitor[start : monitor.index("});", start) + 3]

    assert "Router.navigate('/approvals')" not in monitor
    assert "_openModal(pending[0], data.mode || 'prompt');" in monitor
    assert "_resetPollBackoff();" in handler
    assert "_poll();" in handler
    assert "_modal" in handler
    assert 'data-approval-action="once"' in monitor
    assert 'data-approval-action="always"' in monitor
    assert 'data-approval-action="deny"' in monitor


def test_sandbox_view_tracks_pending_approval_activity() -> None:
    sandbox = _read(SANDBOX_JS)

    assert "opensquilla:approvals-pending" in sandbox
    assert "window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);" in sandbox
    assert "window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);" in sandbox
    assert "function _onApprovalsPending(event)" in sandbox
    assert "function _updateApprovalActivity(count)" in sandbox
    assert "root.querySelector('#sandbox-rules-count')" in sandbox
    assert "root.querySelector('#sandbox-rules')" in sandbox
    assert "Approvals pending" in sandbox
    assert "#sb-activity" not in sandbox


def test_sandbox_approval_activity_preserves_rules_panel_base_state() -> None:
    sandbox = _read(SANDBOX_JS)
    update_start = sandbox.index("function _updateApprovalActivity(count)")
    update_body = sandbox[update_start : sandbox.index("  function _detailRow", update_start)]

    assert "_setRulesContent(root, _renderEmpty('Loading rules'), '0 rules');" in sandbox
    assert (
        "_setRulesContent(root, _renderEmpty('Sandbox rules are unavailable'), '0 rules');"
        in sandbox
    )
    assert "insertAdjacentHTML('afterbegin', activity)" in update_body
    assert "rulesCount.textContent = _rulesBaseCountLabel;" in update_body
    assert "_renderEmpty('No sandbox rules reported')" not in update_body
