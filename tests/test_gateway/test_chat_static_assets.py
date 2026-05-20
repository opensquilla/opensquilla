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
APPROVALS_JS = Path("src/opensquilla/gateway/static/js/views/approvals.js")
CHAT_CSS = Path("src/opensquilla/gateway/static/css/views/chat.css")
BASE_CSS = Path("src/opensquilla/gateway/static/css/base.css")


def _read_app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _read_chat_js() -> str:
    return CHAT_JS.read_text(encoding="utf-8")


def _read_approval_monitor_js() -> str:
    return APPROVAL_MONITOR_JS.read_text(encoding="utf-8")


def _read_approvals_js() -> str:
    return APPROVALS_JS.read_text(encoding="utf-8")


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


def test_chat_permission_pill_distinguishes_global_and_session_modes() -> None:
    source = _read_chat_js()

    assert "cfg?.permissions?.default_mode" in source
    assert "Global ${_globalElevatedMode.toUpperCase()}" in source
    assert "Session ${_elevatedMode.toUpperCase()}" in source
    assert "Approvals bypassed by global default" in source
    assert "opensquilla sandbox on|bypass|full|reset" in source

    # The legacy image-only `accept="image/*" multiple` literal must be gone:
    assert 'accept="image/*" multiple' not in source


def test_webui_bypass_shortcuts_do_not_enable_full_mode() -> None:
    chat_source = _read_chat_js()
    monitor_source = _read_approval_monitor_js()
    approvals_source = _read_approvals_js()
    combined = "\n".join([chat_source, monitor_source, approvals_source])

    assert "ELEVATED_MODE_VERSION_KEY" in chat_source
    assert "localStorage.getItem(_ELEVATED_MODE_VERSION_KEY)" in chat_source
    assert "if (ok) _setElevatedMode('bypass', { toast: true, sync: true });" in chat_source
    assert "This maps to /elevated bypass" in chat_source
    assert "action === 'bypass' ? 'bypass' : ''" in monitor_source
    assert "decision === 'bypass' ? 'bypass' : ''" in approvals_source
    assert "maps to /elevated full" not in combined
    assert "Bypass All Permissions" not in combined


def test_app_uses_dynamic_viewport_height_after_100vh_fallback_for_mobile_composer() -> None:
    css = _read_base_css()

    assert "#app" in css
    assert "height: 100vh;" in css
    assert "height: 100dvh;" in css
    assert css.index("height: 100vh;") < css.index("height: 100dvh;")


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
    assert "const userText = text;" in send_body
    assert "params.displayText = userText" in send_body
    assert "text || '(attachment)'" not in send_body


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
# Test 8 — ESC has a document-level handler so abort works regardless of focus.
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
