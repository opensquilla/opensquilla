from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "opensquilla" / "gateway" / "static"
APP_JS = STATIC / "js" / "app.js"
ICONS_JS = STATIC / "js" / "icons.js"
TEMPLATE = ROOT / "src" / "opensquilla" / "gateway" / "templates" / "index.html"
APPROVAL_MONITOR_JS = STATIC / "js" / "approval_monitor.js"
CHAT_JS = STATIC / "js" / "views" / "chat.js"
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
    assert "Status" in sandbox_js
    assert "Sandbox Rules" in sandbox_js
    assert "Recent Decisions" not in sandbox_js
    assert "sandbox-status-card" not in sandbox_css
    assert ".sandbox-strip" not in sandbox_css
    assert "Approval activity" not in sandbox_js
    assert ".sandbox-stage" in sandbox_css


def test_frontend_defaults_to_full_host_access_when_no_session_context_exists() -> None:
    chat_js = _read(CHAT_JS)
    sandbox_js = _read(SANDBOX_JS)

    assert "const _RUN_MODE_DEFAULT = 'full';" in chat_js
    assert "status.run_mode || 'full'" in sandbox_js


def test_run_mode_tooltips_can_escape_execution_panel() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)

    assert "sandbox-panel sandbox-panel--run-mode" in sandbox_js
    assert ".sandbox-panel--run-mode" in sandbox_css
    assert "overflow: visible;" in sandbox_css
    assert ".sandbox-run-mode-option::after" in sandbox_css
    assert "z-index: 1000;" in sandbox_css


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
    assert (
        "document.addEventListener('click'" in sandbox_js
        or 'document.addEventListener("click"' in sandbox_js
    )


def test_path_browser_fields_are_not_wrapped_in_implicit_labels() -> None:
    sandbox_js = _read(SANDBOX_JS)

    start = sandbox_js.index("function _renderWorkspace")
    body = sandbox_js[start : sandbox_js.index("  function _renderMount", start)]

    assert '<div class="sandbox-field sandbox-field--span">' in body
    assert '<label class="sandbox-field sandbox-field--span">' not in body
    assert 'aria-label="Workspace path"' in body
    assert 'aria-label="Mount path"' in body


def test_mount_rows_keep_long_paths_separate_from_actions() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)

    start = sandbox_js.index("function _renderMount")
    body = sandbox_js[start : sandbox_js.index("  function _renderNetwork", start)]

    assert "sandbox-list__row--mount" in body
    assert "sandbox-list__content" in body
    assert "sandbox-list__meta" in body
    assert "sandbox-list__main--path" in body
    assert "_mountAccessLabel(access)" in body
    assert "_networkScopeLabel(scope)" in body
    assert ".sandbox-list__row--mount" in sandbox_css
    assert ".sandbox-list__content" in sandbox_css
    assert ".sandbox-list__meta" in sandbox_css
    assert ".sandbox-list__main--path" in sandbox_css
    assert "grid-template-columns: minmax(0, 1fr) auto;" in sandbox_css
    assert "white-space: nowrap;" in sandbox_css


def test_sandbox_remove_actions_preserve_chat_or_user_scope() -> None:
    sandbox_js = _read(SANDBOX_JS)

    mount_start = sandbox_js.index("function _renderMount")
    mount_body = sandbox_js[
        mount_start : sandbox_js.index("  function _mountAccessLabel", mount_start)
    ]
    domain_start = sandbox_js.index("function _renderDomain")
    domain_body = sandbox_js[
        domain_start : sandbox_js.index("  async function _onSubmit", domain_start)
    ]
    click_start = sandbox_js.index("async function _onClick")
    click_body = sandbox_js[
        click_start : sandbox_js.index("  async function _onFocusIn", click_start)
    ]

    assert 'data-scope="${_esc(scope || \'chat\')}"' in mount_body
    assert 'data-scope="${_esc(domain.scope || \'chat\')}"' in domain_body
    assert "scope: btn.dataset.scope || 'chat'" in click_body
    assert "sandbox.mount.remove" in click_body
    assert "sandbox.domain.remove" in click_body


def test_path_browser_overlay_does_not_push_mount_form_columns() -> None:
    sandbox_css = _read(SANDBOX_CSS)
    sandbox_js = _read(SANDBOX_JS)

    assert ".sandbox-panel--wide" in sandbox_css
    assert "overflow: visible;" in sandbox_css
    assert ".sandbox-inline-form.is-path-browser-open" in sandbox_css
    assert "z-index: 2000;" in sandbox_css
    assert ".sandbox-field > span" in sandbox_css
    assert ".sandbox-field span {" not in sandbox_css
    assert ".sandbox-field--span.is-path-browser-open" in sandbox_css
    assert "z-index: 2001;" in sandbox_css
    assert ".sandbox-path-field {\n  display: grid;" in sandbox_css
    assert "position: relative;" in sandbox_css
    assert ".sandbox-path-browser-slot {\n  grid-column: 1 / -1;" in sandbox_css
    assert "position: absolute;" in sandbox_css
    assert "top: calc(36px + var(--sp-2));" in sandbox_css
    assert "z-index: 1000;" in sandbox_css
    assert ".sandbox-path-browser {\n  background: var(--bg-surface);" in sandbox_css
    assert (
        ".sandbox-path-browser__row {\n  align-items: center;\n  background: var(--bg-surface);"
        in sandbox_css
    )
    assert "function _setPathBrowserLayer" in sandbox_js
    assert "_setPathBrowserLayer(root, kind, true);" in sandbox_js
    assert "_setPathBrowserLayer(root, kind, false);" in sandbox_js
    assert "classList?.toggle('is-path-browser-open', active)" in sandbox_js


def test_sandbox_network_details_preserve_open_state_after_rerender() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "function _captureOpenNetworkDetails" in sandbox_js
    assert "function _restoreOpenNetworkDetails" in sandbox_js
    assert "const openDetails = _captureOpenNetworkDetails(root);" in sandbox_js
    assert "_restoreOpenNetworkDetails(controls, openDetails);" in sandbox_js
    assert 'data-details-key="${_esc(summaryClass)}"' in sandbox_js


def test_path_browser_document_click_closes_outside_active_path_field() -> None:
    sandbox_js = _read(SANDBOX_JS)

    start = sandbox_js.index("function _onDocumentClick")
    body = sandbox_js[start : sandbox_js.index("  function _closeAllPathBrowsers", start)]
    kind_start = sandbox_js.index("function _pathBrowserKindFromNode")
    kind_body = sandbox_js[
        kind_start : sandbox_js.index("  function _nextPathBrowserLoadId", kind_start)
    ]

    assert "if (!_el || !_hasOpenPathBrowser()) return;" in body
    assert "const targetKind = _pathBrowserKindFromNode(event.target);" in body
    assert "if (targetKind && _hasOpenPathBrowser(targetKind)) return;" in body
    assert "_closeAllPathBrowsers({ restore: true });" in body
    assert "_el.contains(event.target)" not in body
    assert "node?.closest?.('.sandbox-path-field')" in kind_body
    assert "node?.closest?.('.sandbox-path-browser')" in kind_body


def test_path_browser_opens_from_path_inputs() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "_el.addEventListener('focusin', _onFocusIn);" in sandbox_js
    assert "_el.removeEventListener('focusin', _onFocusIn);" in sandbox_js
    assert "function _onFocusIn" in sandbox_js
    assert "input[data-path-browser-kind]" in sandbox_js
    assert "function _openPathBrowserFromInput" in sandbox_js
    assert "_hasOpenPathBrowser(kind)" in sandbox_js
    assert "_loadPathBrowser(kind)" in sandbox_js


def test_path_browser_empty_input_defaults_to_root_not_workspace() -> None:
    sandbox_js = _read(SANDBOX_JS)

    assert "function _pathBrowserRequestPath" in sandbox_js
    assert "return value || '/';" in sandbox_js
    assert "_lastData?.runContext?.workspace || '~'" not in sandbox_js


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
    assert "Default Access" not in full_host_body
    assert "Default Allowlist" not in sandbox_js
    assert "Bundles" not in full_host_body


def test_sandbox_managed_network_assets_use_collapsed_summaries() -> None:
    sandbox_js = _read(SANDBOX_JS)
    sandbox_css = _read(SANDBOX_CSS)

    assert "Default Access" in sandbox_js
    assert "Default Allowlist" not in sandbox_js
    assert "Bundles" in sandbox_js
    assert "This chat" in sandbox_js
    assert "This user" in sandbox_js
    assert "[['chat', 'This chat'], ['workspace', 'This user']]" in sandbox_js
    assert "[['chat', 'This chat'], ['user', 'This user']]" not in sandbox_js
    assert "No custom domains" not in sandbox_js
    assert "No domains added for this chat. Default public access is still active." in sandbox_js
    assert "No domains added for this user. Default public access is still active." in sandbox_js
    assert "No domains added for this chat. Default access is still active." not in sandbox_js
    assert "No domains added for this user. Default access is still active." not in sandbox_js
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
    components_css = _read(STATIC / "css" / "components.css")

    assert "item.params.choices" in monitor
    assert "approval-modal-choices" in monitor
    assert "approval-modal-choice" in monitor
    assert "data-choice-id" in monitor
    assert "choice:" in monitor
    assert "decision:" in monitor
    assert "function _approvalToolLabel" in monitor
    assert "Workspace boundary" in monitor
    assert ".approval-modal-choices" in components_css
    assert ".approval-modal-choice" in components_css
    assert "white-space: normal;" in components_css
    assert "justify-content: space-between;" in components_css
    assert "Approve This Time" in monitor
    assert "Always Allow This Type" in monitor


def test_approval_monitor_renders_sandbox_path_approval_as_plain_language_card() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)
    components_css = _read(STATIC / "css" / "components.css")

    assert "function _renderSandboxPathApproval" in monitor
    assert "Allow access outside the workspace?" in monitor
    assert "Current workspace" in monitor
    assert "Path requested" in monitor
    assert "Access needed" in monitor
    assert "Host workspace" not in monitor
    assert "Sandbox view" not in monitor
    assert "Current access" not in monitor
    assert "Not mounted" not in monitor
    assert "Requested mount" not in monitor
    assert "<dt>Access</dt>" not in monitor
    assert "If approved, OpenSquilla can" in monitor
    assert "copy files into the workspace" in monitor
    meta_start = monitor.index("function _approvalMeta")
    meta_body = monitor[meta_start : monitor.index("  function _approvalDetailHtml", meta_start)]
    assert "if (_isSandboxApproval(item)) return '';" in meta_body
    assert "JSON.stringify(args, null, 2)" in monitor
    assert "_isSandboxApproval(item)" in monitor
    assert ".approval-modal-summary" in components_css
    assert ".approval-modal-choice-description" in components_css


def test_sandbox_view_tracks_pending_approval_activity() -> None:
    sandbox = _read(SANDBOX_JS)

    assert "opensquilla:approvals-pending" in sandbox
    assert (
        "window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);"
        in sandbox
    )
    assert (
        "window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);"
        in sandbox
    )
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

    assert "Default Access" in sandbox
    assert "Default Allowlist" not in sandbox
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
