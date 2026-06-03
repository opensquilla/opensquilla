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
    assert "Run Mode" in sandbox_js
    assert "Workspace & Mounts" in sandbox_js
    assert "Managed Network" in sandbox_js
    assert "Full Host Access" in sandbox_js
    assert "Browse" in sandbox_js
    assert "Status" not in sandbox_js
    assert "Target" not in sandbox_js
    assert "Sandbox Rules" not in sandbox_js
    assert "Recent Decisions" not in sandbox_js
    assert "sandbox-status-card" not in sandbox_css
    assert ".sandbox-strip" not in sandbox_css
    assert "Approval activity" not in sandbox_js
    assert ".sandbox-stage" in sandbox_css


def test_sandbox_view_exposes_realtime_run_context_editing() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)

    for method in (
        "sandbox.workspace.set",
        "sandbox.mount.add",
        "sandbox.mount.remove",
        "sandbox.domain.add",
        "sandbox.domain.remove",
        "sandbox.bundle.enable",
        "sandbox.bundle.disable",
        "sandbox.run_context.set",
        "sandbox.path.list",
    ):
        assert method in sandbox_js

    assert "data-sandbox-action=\"run-mode-set\"" in sandbox_js
    assert "data-sandbox-action=\"workspace-save\"" in sandbox_js
    assert "data-sandbox-action=\"workspace-browse\"" in sandbox_js
    assert "data-sandbox-action=\"mount-add\"" in sandbox_js
    assert "data-sandbox-action=\"mount-browse\"" in sandbox_js
    assert "data-sandbox-action=\"path-browser-select\"" in sandbox_js
    assert "data-sandbox-action=\"path-browser-ok\"" in sandbox_js
    assert "data-sandbox-action=\"path-browser-cancel\"" in sandbox_js
    assert "data-sandbox-action=\"domain-add\"" in sandbox_js
    assert "data-sandbox-action=\"bundle-toggle\"" in sandbox_js
    assert ".sandbox-inline-form" in sandbox_css
    assert ".sandbox-icon-btn" in sandbox_css
    assert ".sandbox-run-mode-grid" in sandbox_css
    assert ".sandbox-path-field" in sandbox_css
    assert ".sandbox-path-browser" in sandbox_css


def test_sandbox_view_uses_inline_path_browser_not_native_picker_rpc() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "sandbox.path.list" in sandbox_js
    assert "sandbox.path.pick" not in sandbox_js
    assert "Opening directory picker" not in sandbox_js
    assert "function _renderPathBrowser" in sandbox_js
    assert "function _loadPathBrowser" in sandbox_js
    assert "browseChildren" in sandbox_js
    assert "_loadPathBrowser(kind, path, { browseChildren: true })" in sandbox_js
    assert "entryKind === 'directory'" in sandbox_js
    assert "path-browser-ok" in sandbox_js
    assert "path-browser-cancel" in sandbox_js


def test_path_browser_has_ok_cancel_and_close_behavior() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert 'data-sandbox-action="path-browser-ok"' in sandbox_js
    assert 'data-sandbox-action="path-browser-cancel"' in sandbox_js
    assert "function _commitPathBrowser" in sandbox_js
    assert "function _closePathBrowser" in sandbox_js
    assert "Escape" in sandbox_js
    assert "click outside" not in sandbox_js.lower()
    assert "document.addEventListener('click'" in sandbox_js or 'document.addEventListener(\"click\"' in sandbox_js


def test_path_browser_does_not_render_current_path_header() -> None:
    sandbox_js = _read(SANDBOX_JS)

    start = sandbox_js.index("function _renderPathBrowser")
    body = sandbox_js[start : sandbox_js.index("  function _renderPathBrowserEntry", start)]
    assert "sandbox-path-browser__head" not in body
    assert "Reload path list" not in body


def test_sandbox_view_hides_editing_panels_for_full_host_access() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "function _isFullHostAccess" in sandbox_js
    assert "function _renderFullHostAccessEmpty" in sandbox_js
    assert "_renderFullHostAccessEmpty(runContext)" in sandbox_js
    assert "No sandbox mounts, domains, or bundles are applied in this mode." in sandbox_js
    full_host_start = sandbox_js.index("function _renderFullHostAccessEmpty")
    full_host_body = sandbox_js[
        full_host_start : sandbox_js.index("  function _renderWorkspace", full_host_start)
    ]
    assert "Managed Network" not in full_host_body
    assert "Default Allowlist" not in full_host_body
    assert "Bundles" not in full_host_body


def test_sandbox_managed_network_assets_use_collapsed_summaries() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)

    assert "Default Allowlist" in sandbox_js
    assert "Bundles" in sandbox_js
    assert "This chat" in sandbox_js
    assert "This user" in sandbox_js
    assert "[['chat', 'This chat'], ['workspace', 'This user']]" in sandbox_js
    assert "No custom domains" not in sandbox_js
    assert "No domains added for this chat. Default access is still active." in sandbox_js
    assert "No domains added for this user. Default access is still active." in sandbox_js
    assert "sandbox-network-summary" in sandbox_js
    assert "sandbox-network-summary--default" in sandbox_js
    assert "sandbox-network-summary--bundles" in sandbox_js
    assert "sandbox-network-summary--chat" in sandbox_js
    assert "sandbox-network-summary--user" in sandbox_js
    assert "<details" in sandbox_js
    assert ".sandbox-network-summary" in sandbox_css


def test_sandbox_managed_network_audits_public_network_grants() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "function _renderPublicNetworkGrants" in sandbox_js
    assert "publicNetwork: Array.isArray(runContext.publicNetwork)" in sandbox_js
    assert "runContext.public_network" in sandbox_js
    assert "Normal public network" in sandbox_js
    assert "Blocked, private, and unsafe hosts stay blocked." in sandbox_js


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


def test_approval_monitor_renders_custom_choice_buttons_and_posts_selected_choice() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)

    assert "item.params.choices" in monitor
    assert "data-choice-id" in monitor
    assert "choice:" in monitor
    assert "decision:" in monitor
    assert "Approve This Time" in monitor
    assert "Always Allow This Type" in monitor


def test_sandbox_view_tracks_pending_approval_activity() -> None:
    sandbox = _read(SANDBOX_JS)

    assert "opensquilla:approvals-pending" in sandbox
    assert "window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);" in sandbox
    assert "window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);" in sandbox
    assert "function _onApprovalsPending(event)" in sandbox
    assert "function _updateApprovalActivity(count)" in sandbox
    assert "root.querySelector('#sandbox-approval-count')" in sandbox
    assert "root.querySelector('#sandbox-approval-activity')" in sandbox
    assert "Approvals pending" in sandbox
    assert "#sb-activity" not in sandbox


def test_sandbox_bundle_controls_treat_defaults_as_enabled_until_disabled() -> None:
    sandbox = _read(SANDBOX_JS)

    assert "enabledByDefault" in sandbox
    assert "source === 'disabled'" in sandbox
    assert "enabled_by_default" in sandbox


def test_sandbox_view_renders_read_only_default_allowlist() -> None:
    sandbox = _read(SANDBOX_JS)

    assert "Default Allowlist" in sandbox
    assert "status.default_allowlist" in sandbox
    assert "status.defaultAllowlist" in sandbox
    assert "function _renderDefaultAllowlist" in sandbox
    assert "default-allowlist-remove" not in sandbox


def test_sandbox_approval_activity_preserves_rules_panel_base_state() -> None:
    sandbox = _read(SANDBOX_JS)
    update_start = sandbox.index("function _updateApprovalActivity(count)")
    update_body = sandbox[update_start : sandbox.index("  function _setNotice", update_start)]

    assert "_rulesBaseCountLabel" not in sandbox
    assert "countEl.textContent = `${safeCount}`;" in update_body
    assert "activityEl.innerHTML = activity;" in update_body
    assert "_renderEmpty('No sandbox rules reported')" not in update_body
