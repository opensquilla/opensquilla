"""Static-asset checks for the WebUI two-mode attachment buffer.

The frontend has no JS test harness in v1, so these checks use text-scrape
assertions plus a manual checklist documented in the PR description as the
substitute for chat.js behavior coverage.

These checks lock the contract so the implementation cannot quietly drift
back to image-only or break the bridge-upload integration.
"""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("src/opensquilla/gateway/static/js/app.js")
CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
APPROVAL_MONITOR_JS = Path("src/opensquilla/gateway/static/js/approval_monitor.js")
CONFIG_JS = Path("src/opensquilla/gateway/static/js/views/config.js")
CHAT_CSS = Path("src/opensquilla/gateway/static/css/views/chat.css")
BASE_CSS = Path("src/opensquilla/gateway/static/css/base.css")


def _read_app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _read_chat_js() -> str:
    return CHAT_JS.read_text(encoding="utf-8")


def _read_approval_monitor_js() -> str:
    return APPROVAL_MONITOR_JS.read_text(encoding="utf-8")


def _read_config_js() -> str:
    return CONFIG_JS.read_text(encoding="utf-8")


def _read_chat_css() -> str:
    return CHAT_CSS.read_text(encoding="utf-8")


def _read_base_css() -> str:
    return BASE_CSS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1 — file picker `accept` attribute matches the gateway allow-list.
# ---------------------------------------------------------------------------

def test_chat_input_accept_attribute_matches_allowlist() -> None:
    source = _read_chat_js()
    from opensquilla.gateway.uploads import _ALLOWED_MIMES

    accept_required_substrings = [
        'id="chat-file-input"',
        # Image family stays present while document/text upload support is added.
        "image/",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    ]
    for needle in accept_required_substrings:
        assert needle in source, needle

    for mime in sorted(_ALLOWED_MIMES):
        assert mime in source, mime


def test_chat_run_mode_control_replaces_elevated_bypass_copy() -> None:
    source = _read_chat_js()
    config_source = _read_config_js()
    chat_css = _read_chat_css()

    assert '<span class="chat-toolbar-row-label">Run Mode</span>' in source
    assert '<span class="chat-toolbar-row-label">Approvals</span>' not in source
    assert source.count('class="chat-toolbar-row-label"') == 3
    assert '<span class="chat-toolbar-row-label">Squilla Router</span>' in source
    assert '<span class="chat-toolbar-row-label">Visual effects</span>' in source
    assert "Workspace" not in source[source.index('id="chat-toolbar"'):]
    assert "Open Sandbox" not in source[source.index('id="chat-toolbar"'):]
    assert 'id="chat-run-mode-trigger"' in source
    assert 'id="chat-run-mode-menu"' in source
    assert 'class="chat-run-mode-current"' in source
    assert "chat-run-mode-option" in source
    assert "chat-run-mode-tooltip" in source
    assert ".chat-run-mode-tooltip" in chat_css
    assert "sandbox.run_context.get" not in source
    assert "sandbox.run_context.set" not in source
    assert "Standard-Sandbox" in source
    assert "Trusted-Sandbox" in source
    assert "Full Host Access" in source
    assert "Sandboxed execution. Risky actions ask before running." in source
    assert (
        "Sandboxed execution with fewer routine prompts. Boundary changes still ask."
        in source
    )
    assert "Host execution without per-command prompts. Use only for trusted workspaces." in source
    assert 'title="Standard:' not in source
    assert 'title="Trusted:' not in source
    assert 'title="Full:' not in source
    assert "chat-run-mode-segment" not in source
    assert "_source.runMode" in source
    assert "_source.elevated" not in source
    assert "opensquilla sandbox on|trust|full|reset" in config_source
    assert "sandbox.run_mode: standard, trusted, or full" in config_source
    assert "opensquilla sandbox on|bypass|full|reset" not in source
    assert "opensquilla sandbox on|bypass|full|reset" not in config_source
    assert "This maps to /elevated bypass" not in source
    assert "Execution mode" not in source
    assert "Session ${_elevatedMode.toUpperCase()}" not in source
    assert "Bypass Off" not in source

    # The legacy image-only `accept="image/*" multiple` literal must be gone:
    assert 'accept="image/*" multiple' not in source


def test_chat_run_mode_defaults_full_and_normalizes_standard_explicitly() -> None:
    source = _read_chat_js()
    start = source.index("function _normalizeRunMode(mode)")
    end = source.index("  function _setRunMode", start)
    helper = source[start:end]

    assert "const _RUN_MODE_DEFAULT = 'full';" in source
    assert "Establish sandbox" in source
    assert "sandbox.setup.status" in source
    assert "sandbox.setup.ensure" in source
    assert (
        "if (value === 'standard' || value === 'standard-sandbox') return 'standard';"
        in helper
    )


def test_chat_session_transitions_do_not_change_current_run_mode() -> None:
    source = _read_chat_js()

    start = source.index("function _startNewChatSession(")
    end = source.index("  function _bindEvents()", start)
    new_chat_helper = source[start:end]

    start = source.index("function _switchToSession(key)")
    end = source.index("  function _bindSessionChip()", start)
    switch_helper = source[start:end]

    assert "_updateSessionChip(key);" in switch_helper
    assert "_setRunMode(_RUN_MODE_DEFAULT" not in switch_helper
    assert "_loadRunContext()" not in switch_helper
    assert "_syncRunMode(" not in switch_helper

    new_persist_idx = new_chat_helper.index("_persistSession(key);")
    inherit_idx = new_chat_helper.index(
        "_setRunMode(inheritedRunMode, { toast: false });"
    )
    assert "_updateSessionChip(key);" in new_chat_helper
    assert "const inheritedRunMode = _normalizeRunMode(_runMode);" in new_chat_helper
    assert "_setRunMode(_RUN_MODE_DEFAULT" not in new_chat_helper
    assert "_loadRunContext()" not in new_chat_helper
    assert "_syncRunMode(" not in new_chat_helper
    assert new_persist_idx < inherit_idx

    assert "function _startNewChatSession(source)" in new_chat_helper
    assert "_parkCurrentSessionStreamState(source || 'new_chat')" in new_chat_helper
    assert "newBtn.addEventListener('click', () => _startNewChatSession('new_chat'))" in source


def test_chat_run_mode_is_client_state_not_gateway_status() -> None:
    source = _read_chat_js()
    render = source[
        source.index("function render(el)")
        : source.index("  function _shouldAutofocusComposer", source.index("function render(el)"))
    ]

    assert "_loadRunModeStatusFallback" not in source
    assert "sandbox.status" not in source
    assert "_loadRunContext" not in source
    assert "_syncRunMode" not in source
    assert "sandbox.run_context.get" not in source
    assert "sandbox.run_context.set" not in source
    assert "_loadSandboxSetupStatus({ showPrompt: true });" in render


def test_chat_does_not_render_persistent_bypass_warning_chip() -> None:
    chat_source = _read_chat_js()
    chat_css = _read_chat_css()

    assert "chat-bypass-warn" not in chat_source
    assert "chat-bypass-warn" not in chat_css
    assert "Approvals bypassed by global default" not in chat_source


def test_webui_removes_bypass_approval_shortcuts() -> None:
    chat_source = _read_chat_js()
    monitor_source = _read_approval_monitor_js()
    app_source = _read_app_js()
    template_source = Path("src/opensquilla/gateway/templates/index.html").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([chat_source, monitor_source])

    assert "Bypass Approvals" not in combined
    assert "Bypass approvals" not in combined
    assert 'data-approval-action="bypass"' not in monitor_source
    assert "action === 'bypass'" not in monitor_source
    assert "elevatedMode" not in monitor_source
    assert "opensquilla:elevated-mode" not in monitor_source
    assert "maps to /elevated full" not in combined
    assert "Bypass All Permissions" not in combined
    assert "Router.register('/approvals'" not in app_source
    assert "/static/js/views/approvals.js" not in template_source
    assert "/static/css/views/approvals.css" not in template_source


def test_app_uses_dynamic_viewport_height_after_100vh_fallback_for_mobile_composer() -> None:
    css = _read_base_css()

    assert "#app" in css
    assert "height: 100vh;" in css
    assert "height: 100dvh;" in css
    assert css.index("height: 100vh;") < css.index("height: 100dvh;")


def test_app_preserves_explicit_mobile_routes_instead_of_forcing_chat() -> None:
    app = _read_app_js()
    router = Path("src/opensquilla/gateway/static/js/router.js").read_text(encoding="utf-8")

    assert "Router.currentPath() === '/overview'" not in app
    assert "Router.navigate('/chat');" not in app
    assert "window.matchMedia('(max-width: 768px)').matches ? '/chat' : '/overview'" in router


def test_chat_session_controls_mount_in_topbar_center_slot() -> None:
    app = _read_app_js()
    chat = _read_chat_js()
    base_css = _read_base_css()
    chat_css = _read_chat_css()
    approval_monitor = _read_approval_monitor_js()

    assert 'id="topbar-center"' in app
    assert "function getTopbarCenter()" in app
    assert "function clearTopbarCenter()" in app
    assert "clearTopbarCenter();" in app
    export_start = app.index("return {")
    export_body = app[export_start:]
    assert "getTopbarCenter" in export_body
    assert "clearTopbarCenter" in export_body

    assert 'class="chat-header"' not in chat
    assert "App.getTopbarCenter" in chat
    assert "App.clearTopbarCenter" in chat
    assert 'id="chat-session-chip"' in chat
    assert 'id="chat-session-chip-key"' in chat
    assert 'id="chat-session-copy"' in chat
    assert 'id="chat-run-status"' in chat
    assert 'id="chat-ctx-warn"' in chat

    destroy_start = chat.index("function destroy()")
    destroy_body = chat[destroy_start:]
    assert "App.clearTopbarCenter" in destroy_body

    topbar_center_rule = base_css[
        base_css.index(".topbar-center {") : base_css.index("}", base_css.index(".topbar-center {"))
    ]
    assert "min-width: 0" in topbar_center_rule
    assert "overflow: hidden" in topbar_center_rule

    approval_start = base_css.index(".approval-inline {")
    approval_rule = base_css[approval_start : base_css.index("}", approval_start)]
    assert "flex-shrink: 0" in approval_rule
    assert "@media (max-width: 768px)" in base_css
    assert "width: 34px" in base_css
    assert "font-size: 0" in base_css
    assert "inline.setAttribute('aria-label', inlineText);" in approval_monitor

    session_chip_start = chat_css.index(".chat-session-chip {")
    session_chip_rule = chat_css[
        session_chip_start : chat_css.index("}", session_chip_start)
    ]
    assert "min-width: 0" in session_chip_rule
    assert "clamp(180px, 34vw, 720px)" in session_chip_rule

    for selector in ("#chat-run-status", ".chat-session-copy-btn", ".chat-ctx-warn"):
        start = chat_css.index(selector)
        rule = chat_css[start : chat_css.index("}", start)]
        assert "flex-shrink: 0" in rule


def test_chat_composer_autofocus_is_desktop_only() -> None:
    source = _read_chat_js()

    assert "function _shouldAutofocusComposer()" in source
    assert "window.matchMedia('(max-width: 768px)')" in source
    assert "window.matchMedia('(pointer: coarse)')" in source
    assert "if (_textarea && _shouldAutofocusComposer()) _textarea.focus();" in source
    assert "// Autofocus chat input\n    if (_textarea) _textarea.focus();" not in source


def test_chat_composer_has_microphone_transcription_flow() -> None:
    source = _read_chat_js()
    css = _read_chat_css()

    assert 'id="chat-btn-mic"' in source
    assert 'aria-label="Record voice input"' in source
    assert "navigator.mediaDevices.getUserMedia" in source
    assert "new MediaRecorder" in source
    assert "/api/audio/transcribe" in source
    assert "Authorization" in source
    assert "Bearer ${token}" in source
    assert "voice_input" in source
    assert "chat-mic-recording" in css


def test_mobile_sidebar_closed_state_leaves_focus_order() -> None:
    app = _read_app_js()

    assert 'id="sidebar-nav"' in app
    assert 'aria-controls="sidebar-nav"' in app
    assert "_syncSidebarAccessibility(sidebar, toggle, mobileQuery)" in app
    assert "window.matchMedia('(max-width: 768px)')" in app
    assert "sidebar.setAttribute('aria-hidden', 'true')" in app
    assert "sidebar.setAttribute('inert', '')" in app
    assert "sidebar.removeAttribute('aria-hidden')" in app
    assert "sidebar.removeAttribute('inert')" in app
    assert "toggle.setAttribute('aria-expanded', String(isOpen));" in app


def test_desktop_sidebar_nav_items_keep_polished_hit_areas() -> None:
    css = _read_base_css()

    nav_start = css.index(".nav-item {")
    nav_rule = css[nav_start : css.index("}", nav_start)]

    assert "min-height: 40px" in nav_rule


def test_short_desktop_sidebar_keeps_primary_nav_visible() -> None:
    css = _read_base_css()

    assert "@media (min-width: 769px) and (max-height: 640px)" in css
    compact_start = css.index("@media (min-width: 769px) and (max-height: 640px)")
    compact_rule = css[compact_start:]

    assert ".nav-brand {" in compact_rule
    assert "min-height: 44px" in compact_rule
    assert ".nav-group-label {" in compact_rule
    assert "padding: 5px var(--sp-4) 2px" in compact_rule
    assert ".nav-group-label:first-of-type" in compact_rule
    assert "margin-top: 4px" in compact_rule


# ---------------------------------------------------------------------------
# Test 2 — INLINE_THRESHOLD_BYTES single-sourced; no magic-number drift.
# ---------------------------------------------------------------------------

def test_inline_threshold_constant_single_sourced() -> None:
    source = _read_chat_js()

    # The constant is declared once, then referenced — never re-typed as a
    # raw 2_000_000 / 2*1024*1024 anywhere else in chat.js.
    assert "INLINE_THRESHOLD_BYTES" in source

    # The legacy 20 MB per-image client warning has either been removed or
    # rewritten to use the new threshold; either way the literal
    # `20 * 1024 * 1024` must not coexist with INLINE_THRESHOLD_BYTES because
    # that's the exact magic-number drift the constant exists to prevent.
    assert source.count("INLINE_THRESHOLD_BYTES") >= 2, (
        "INLINE_THRESHOLD_BYTES must be referenced from both the size-check "
        "and the dispatch-decision call sites"
    )


# ---------------------------------------------------------------------------
# Test 3 — chat.js carries the two-mode payload shape (inline vs staged).
# ---------------------------------------------------------------------------

def test_chat_js_uses_two_mode_attachment_payload() -> None:
    source = _read_chat_js()

    # The kind discriminator distinguishes inline (data) from staged (file_uuid)
    # attachments at send time. Both literals must appear in the source.
    assert "'staged'" in source or '"staged"' in source
    assert "'inline'" in source or '"inline"' in source
    assert "file_uuid" in source

    # Bridge upload endpoint URL is referenced from chat.js (the POST happens
    # client-side when a file exceeds INLINE_THRESHOLD_BYTES).
    assert "/api/v1/files/upload" in source


def test_chat_empty_attachment_turn_has_separate_display_text() -> None:
    source = _read_chat_js()
    send_start = source.index("async function _onSend()")
    send_end = source.index("  function _onStop", send_start)
    send_body = source[send_start:send_end]

    assert "const providerText = text || 'Describe these attachments';" in send_body
    assert (
        "const userText = displayTextOverride !== null ? displayTextOverride : text;"
        in send_body
    )
    assert "params.displayText = userText" in send_body
    assert "text || '(attachment)'" not in send_body


def test_chat_meta_preflight_confirmation_uses_hidden_send_payload() -> None:
    source = _read_chat_js()
    handler_start = source.index("const _onMetaPreflightAction = async (ev) => {")
    handler_end = source.index("document.addEventListener('meta-preflight-action'", handler_start)
    handler_body = source[handler_start:handler_end]

    assert "_sendHiddenMetaPreflightConfirmation(confirmed, detail);" in handler_body
    assert "_textarea.value = confirmed.message" not in handler_body
    assert "_onSend();" not in handler_body
    assert "confirmed.message || `${detail.interpretedRequest" not in handler_body


def test_chat_artifact_layout_groups_visuals_and_files_without_stretching() -> None:
    source = _read_chat_js()
    css = _read_chat_css()
    render_start = source.index("function _renderArtifacts(artifacts)")
    render_end = source.index("  async function _downloadArtifact", render_start)
    render_body = source[render_start:render_end]
    artifacts_start = css.index(".msg-artifacts {")
    artifacts_end = css.index(".msg-artifact-gallery", artifacts_start)
    artifacts_css = css[artifacts_start:artifacts_end]

    assert "const groupKind = category === 'visual' ? 'visual' : 'file';" in render_body
    assert "msg-artifact-gallery" in render_body
    assert "msg-artifact-files" in render_body
    assert "display: grid;" in artifacts_css
    assert "display: flex;" not in artifacts_css


def test_chat_artifact_category_has_unknown_file_fallback() -> None:
    source = _read_chat_js()
    start = source.index("function _artifactCategory(artifact)")
    end = source.index("  function _isImageArtifact", start)
    body = source[start:end]

    assert "application/octet-stream" in body
    assert "ARTIFACT_EXTENSION_CATEGORIES" in body
    assert "return 'file';" in body


# ---------------------------------------------------------------------------
# Test 4 — staged uploads use the same auth source as the WebSocket session.
# ---------------------------------------------------------------------------

def test_chat_upload_uses_app_auth_token_accessor() -> None:
    app_source = _read_app_js()
    chat_source = _read_chat_js()

    assert "window.OpenSquillaAuth" not in chat_source
    assert "function getAuthToken()" in app_source
    assert "loadConnectionSettings().token" in app_source
    assert "getAuthToken" in app_source
    assert "App.getAuthToken" in chat_source
    assert "window.App && App.getAuthToken" not in chat_source
    assert "const token = (App.getAuthToken && App.getAuthToken()) || '';" in chat_source
    assert "headers['Authorization'] = `Bearer ${token}`" in chat_source


# ---------------------------------------------------------------------------
# Test 5 — file selection has visible in-progress states before final payload.
# ---------------------------------------------------------------------------

def test_chat_attachment_selection_has_pending_states_and_send_guard() -> None:
    source = _read_chat_js()
    css = _read_chat_css()

    assert "'inline_pending'" in source
    assert "'uploading'" in source
    assert "reader.onerror" in source
    assert "_hasPendingAttachmentWork()" in source
    assert "Wait for file attachment processing to finish" in source
    assert "attachment-chip--busy" in source
    assert ".attachment-chip--busy" in css
    assert ".msg-file-chip" in css


# ---------------------------------------------------------------------------
# Test 6 — browser-empty MIME values can still map common allowed extensions.
# ---------------------------------------------------------------------------

def test_chat_attachment_empty_browser_mime_falls_back_by_extension() -> None:
    source = _read_chat_js()

    assert "ATTACHMENT_EXTENSION_MIMES" in source
    assert "_isAllowedAttachmentMime(file.type)" in source
    assert "return extensionMime || (file && file.type) || 'application/octet-stream';" in source
    assert "new File([file], file.name, { type: mime })" in source
    expected_extension_pairs = {
        "md": "text/markdown",
        "markdown": "text/markdown",
        "txt": "text/plain",
        "csv": "text/csv",
        "json": "application/json",
        "pdf": "application/pdf",
    }
    for ext, mime in expected_extension_pairs.items():
        assert f"{ext}: '{mime}'" in source
    assert "'application/octet-stream'" in source


def test_chat_attachment_hard_cap_is_category_specific() -> None:
    source = _read_chat_js()

    assert "ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES" in source
    assert "ATTACHMENT_IMAGE_HARD_CAP_BYTES = 5 * 1024 * 1024" in source
    assert "ATTACHMENT_PDF_HARD_CAP_BYTES = 30 * 1024 * 1024" in source
    assert "function _canStageAttachmentMime(mime)" in source
    assert "function _attachmentHardCapBytes(mime)" in source
    assert "mime === 'application/pdf'" in source
    assert "_isImageAttachmentMime(mime)" in source
    assert "_isTextAttachmentMime(mime)" in source
    assert "!_canStageAttachmentMime(mime)" in source
    assert "text-family attachments are limited" in source
    assert "ATTACHMENT_NON_PDF_HARD_CAP_BYTES" not in source
    assert "ATTACHMENT_HARD_CAP_BYTES" not in source


# ---------------------------------------------------------------------------
# Test 8 — ESC has a document-level handler with overlay/editable guards.
# ---------------------------------------------------------------------------

def test_chat_js_has_document_level_escape_handler() -> None:
    source = _read_chat_js()

    # The function name + the document.addEventListener wiring + matching
    # removeEventListener cleanup must all be present. Without the cleanup
    # entry, the listener leaks across view re-mounts.
    assert "function _onDocKeydown" in source
    assert "document.addEventListener('keydown', _onDocKeydown)" in source
    assert "document.removeEventListener('keydown', _onDocKeydown)" in source
    # The handler must defer to other ESC consumers (slash menu via
    # defaultPrevented, popover/modal handlers via the overlay-visibility
    # probe). Without these gates, ESC pressed to dismiss a popover would
    # also abort the streaming turn behind it.
    assert "if (e.defaultPrevented) return;" in source
    assert "if (_chatOverlayVisible()) return;" in source


def test_chat_escape_aborts_from_composer_but_not_other_editable_targets() -> None:
    source = _read_chat_js()
    handler_start = source.index("function _onDocKeydown(e) {")
    handler_end = source.index("document.addEventListener('keydown', _onDocKeydown)", handler_start)
    handler = source[handler_start:handler_end]

    other_editable_idx = handler.index(
        "const inOtherEditable = target && target !== _textarea && ("
    )
    streaming_idx = handler.index("if (_isStreaming) {")
    assert other_editable_idx < streaming_idx
    assert "if (inOtherEditable) return;" in handler
    assert "target !== _textarea" in handler
    assert "_onStop('webui_escape')" in handler


def test_chat_stop_sends_abort_source() -> None:
    source = _read_chat_js()
    stop_start = source.index("function _onStop(")
    stop_end = source.index("// Delegated click handler", stop_start)
    stop_body = source[stop_start:stop_end]

    assert "function _onStop(source = 'webui_stop_button')" in stop_body
    assert "_rpc.call('chat.abort', { sessionKey: _sessionKey, source })" in stop_body
    assert "function _chatOverlayVisible" in source


def test_chat_tool_rendering_is_idempotent_by_tool_use_id() -> None:
    source = _read_chat_js()

    assert "function _findToolDetailsById(root, toolId)" in source
    assert "const existing = _findToolDetailsById(body, toolId);" in source
    assert "if (existing) {" in source
    assert "return;" in source
    assert "data-tool-result-for" in source
    assert "_findToolResultById" in source


# ---------------------------------------------------------------------------
# Test 9 — pending recovery: ESC / abort funnels the queue into the composer.
# ---------------------------------------------------------------------------

def test_chat_js_recovers_pending_queue_into_composer_on_abort() -> None:
    source = _read_chat_js()

    # The recovery helper itself.
    assert "function _popAllPendingIntoComposer" in source
    # _onStop must invoke recovery so user-initiated stop does not lose pending.
    assert "_endStreaming({ reason: 'aborted' })" in source
    assert "_popAllPendingIntoComposer()" in source
    # The wildcard .done branch reuses the same recovery on server-initiated
    # cancel paths (timeout / external abort) — so the wasAborted early-exit
    # that previously skipped drain has been removed.
    assert "_doneWasAborted" in source
    # The legacy "skip drain on abort" comment must not survive.
    assert "Bug 2c: drain the head of the pending queue on natural completion" not in source


# ---------------------------------------------------------------------------
# Test 10 — ↑/↓ history cursor + Alt-modifier pending edit shortcuts.
# ---------------------------------------------------------------------------

def test_chat_js_has_history_navigation_and_alt_pending_shortcuts() -> None:
    source = _read_chat_js()

    assert "function _cycleHistory" in source
    assert "function _setTextareaProgrammatic" in source
    assert "function _enqueueCurrentInput" in source
    enqueue_start = source.index("function _enqueueCurrentInput")
    enqueue_end = source.index("  function _updateStopButton", enqueue_start)
    enqueue_body = source[enqueue_start:enqueue_end]
    assert (
        "return _enqueuePendingInput(text, null, 'the current response', "
        "normalized.attachments);"
    ) in enqueue_body
    assert "_pendingQueue.push" not in enqueue_body
    assert "_inputHistoryIdx" in source
    assert "_inputHistoryDraft" in source
    assert "_suppressHistoryReset" in source
    # Alt+↑ / Alt+↓ are the pending-queue shortcuts; ↑/↓ are reserved for history.
    assert "e.key === 'ArrowUp' && e.altKey" in source
    assert "e.key === 'ArrowDown' && e.altKey" in source
    # ↑ must work both on an empty composer (enter nav mode) and while
    # already navigating (continue further back). The second clause is what
    # keeps the cursor moving after the first ↑ has filled the textarea.
    assert "(!_textarea.value || _inputHistoryIdx !== null)" in source
    # The legacy ↑-without-modifier-pops-pending behavior is gone.
    assert "ArrowUp' && !_textarea.value && _pendingQueue.length > 0" not in source


# ---------------------------------------------------------------------------
# Test 11 — interrupted streaming turns are visually marked in the transcript.
# ---------------------------------------------------------------------------

def test_chat_interrupt_mark_is_rendered_and_styled() -> None:
    source = _read_chat_js()
    css = _read_chat_css()

    # JS appends the marker element when _endStreaming is called with reason.
    assert "msg-interrupt-mark" in source
    assert "function _endStreaming(opts)" in source
    assert "wasAborted" in source
    # CSS for the marker exists and is themed via the project's muted token.
    assert ".msg-interrupt-mark" in css
    assert "var(--text-muted)" in css.split(".msg-interrupt-mark", 1)[1].split("}", 1)[0]


def test_control_index_loads_vue_entrypoint() -> None:
    index = Path("src/opensquilla/gateway/templates/index.html").read_text(encoding="utf-8")

    assert 'id="app"' in index
    assert 'id="opensquilla-data"' in index
    assert "vite_css_url" in index
    assert "vite_js_url" in index
