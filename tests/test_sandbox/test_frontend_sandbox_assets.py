from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "opensquilla" / "gateway" / "static"
APP_JS = STATIC / "js" / "app.js"
RPC_JS = STATIC / "js" / "rpc.js"
TEMPLATE = ROOT / "src" / "opensquilla" / "gateway" / "templates" / "index.html"
APPROVAL_MONITOR_JS = STATIC / "js" / "approval_monitor.js"
CHAT_JS = STATIC / "js" / "views" / "chat.js"
CHAT_CSS = STATIC / "css" / "views" / "chat.css"
WEBUI_DIST = STATIC / "dist"
SANDBOX_JS = STATIC / "js" / "views" / "sandbox.js"
SANDBOX_CSS = STATIC / "css" / "views" / "sandbox.css"
APPROVALS_JS = STATIC / "js" / "views" / "approvals.js"
APPROVALS_CSS = STATIC / "css" / "views" / "approvals.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_standalone_sandbox_and_approvals_pages_are_removed() -> None:
    app = _read(APP_JS)
    template = _read(TEMPLATE)

    assert not SANDBOX_JS.exists()
    assert not SANDBOX_CSS.exists()
    assert not APPROVALS_JS.exists()
    assert not APPROVALS_CSS.exists()
    assert "Router.register('/sandbox'" not in app
    assert "Router.register('/approvals'" not in app
    assert 'data-path="/sandbox"' not in app
    assert 'data-path="/approvals"' not in app
    assert "/static/css/views/sandbox.css" not in template
    assert "/static/js/views/sandbox.js" not in template
    assert "/static/css/views/approvals.css" not in template
    assert "/static/js/views/approvals.js" not in template


def test_chat_run_mode_control_remains_the_only_sandbox_frontend_control() -> None:
    chat_js = _read(CHAT_JS)
    chat_css = _read(CHAT_CSS)

    assert "const _RUN_MODE_FALLBACK = 'trusted';" in chat_js
    assert "_applyHelloRunModePolicy" in chat_js
    assert "owner，不能选择 Full Host Access" in chat_js
    assert "Full Host Access is unavailable" in chat_js
    assert 'id="chat-run-mode-trigger"' in chat_js
    assert 'id="chat-run-mode-menu"' in chat_js
    assert "sandbox.run_context.get" not in chat_js
    assert "sandbox.run_context.set" not in chat_js
    assert "sandbox.status" not in chat_js
    assert "_source.runMode" in chat_js
    assert "Standard-Sandbox" in chat_js
    assert "Managed Execution" in chat_js
    assert "Full Host Access" in chat_js
    assert "_requestSandboxSetupForMode(mode)" in chat_js

    assert "chat-sandbox-setup-banner" in chat_js
    assert "Establish sandbox" in chat_js
    assert "sandbox.setup.status" in chat_js
    assert "sandbox.setup.ensure" in chat_js
    assert "_sandboxSetupReadyForMode" in chat_js
    assert "_requestSandboxSetupForMode" in chat_js
    assert ".chat-sandbox-setup-banner" in chat_css


def test_built_webui_run_mode_label_matches_managed_execution() -> None:
    built_js = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(WEBUI_DIST.rglob("*.js"))
    )

    assert "Trusted-Sandbox" not in built_js
    assert "可信沙箱" not in built_js
    assert "Managed Execution" in built_js
    assert "托管执行" in built_js


def test_static_rpc_caches_hello_for_late_chat_mounts() -> None:
    rpc_js = _read(RPC_JS)
    chat_js = _read(CHAT_JS)

    assert "this._hello = null;" in rpc_js
    assert "get hello() { return this._hello; }" in rpc_js
    assert "this._hello = data;" in rpc_js
    assert "_applyHelloRunModePolicy(_rpc?.hello);" in chat_js


def test_approval_monitor_inline_button_uses_modal_polling_path() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)
    start = monitor.index("inline.addEventListener('click'")
    handler = monitor[start : monitor.index("});", start) + 3]

    assert "Router.navigate('/approvals')" not in monitor
    assert "Router.navigate('/sandbox')" not in monitor
    assert "_openModal(pending[0], data.mode || 'prompt');" in monitor
    assert "_resetPollBackoff();" in handler
    assert "_poll();" in handler
    assert "_modal" in handler
    assert 'data-approval-action="once"' in monitor
    assert 'data-approval-action="deny"' in monitor
    # "Allow always" was a removed no-op — the legacy monitor must not ship it or
    # send its now-rejected params.
    assert 'data-approval-action="always"' not in monitor
    assert "allowAlways" not in monitor
    assert "rememberIntent" not in monitor


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
    assert "Always Allow This Type" not in monitor


def test_approval_monitor_renders_sandbox_path_approval_as_plain_language_card() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)
    components_css = _read(STATIC / "css" / "components.css")

    assert "function _renderSandboxPathApproval" in monitor
    assert "host_once" not in monitor
    assert "Sandbox fallback" not in monitor
    assert "Run outside the sandbox?" not in monitor
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


def test_approval_monitor_closes_stale_modal_when_pending_approval_disappears() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)

    assert "let _modalApprovalId = null;" in monitor
    assert "_modalApprovalId = String(item.id || '');" in monitor
    assert "const modalStillPending = _modalApprovalId" in monitor
    assert "if (_modal && !modalStillPending && !_modalResolutionPending) {" in monitor
    assert "_closeModal();" in monitor
    resolve_start = monitor.index("fetch('/api/approvals/resolve'")
    resolve_block = monitor[resolve_start : monitor.index("} catch", resolve_start)]
    assert "await _poll();" in resolve_block


def test_approval_monitor_uses_canonical_cross_surface_resolution() -> None:
    monitor = _read(APPROVAL_MONITOR_JS)
    resolve_start = monitor.index("async function _resolve")
    resolve_block = monitor[resolve_start : monitor.index("function _closeModal", resolve_start)]

    assert "const result = await resp.json();" in resolve_block
    assert "const canonicalApproved = _canonicalApprovalOutcome(result);" in resolve_block
    assert "if (canonicalApproved === null)" in resolve_block
    assert "_modalResolutionPending = true;" in resolve_block
    assert "if (_modal === overlay) _resolve(item, resolution, overlay);" in resolve_block
    assert "canonicalApproved ? 'Approval granted' : 'Approval denied'" in resolve_block
    assert "body.approved ? 'Approval granted' : 'Approval denied'" not in resolve_block
    assert "result.pending === true" in resolve_block
    assert "result.resolutionInProgress === true" in resolve_block
    assert "typeof result.approved !== 'boolean'" in resolve_block
    assert "!modalStillPending && !_modalResolutionPending" in monitor
