from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
CHAT_CSS = Path("src/opensquilla/gateway/static/css/views/chat.css")
APP_JS = Path("src/opensquilla/gateway/static/js/app.js")
RPC_JS = Path("src/opensquilla/gateway/static/js/rpc.js")
SAVINGS_FX_JS = Path("src/opensquilla/gateway/static/js/components/savings-fx.js")
TASK_RUNTIME_PY = Path("src/opensquilla/gateway/task_runtime.py")


def test_chat_view_defaults_to_full_host_access() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_DEFAULT = 'full';" in source
    trigger_start = source.index('id="chat-run-mode-trigger"')
    trigger_end = source.index("</button>", trigger_start)
    trigger_markup = source[trigger_start:trigger_end]
    assert 'data-run-mode="full"' in trigger_markup
    assert '<span class="chat-run-mode-current">Full Host Access</span>' in trigger_markup


def test_chat_view_exposes_sandbox_setup_entry_for_sandbox_modes() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert 'id="chat-sandbox-setup-banner"' in source
    assert "Establish sandbox" in source
    assert "Not now" in source
    assert "sandbox.setup.status" in source
    assert "sandbox.setup.ensure" in source
    assert "_sandboxSetupReadyForMode" in source
    assert "_requestSandboxSetupForMode" in source
    assert "if (mode === 'full') return true;" in source


def test_chat_sandbox_setup_banner_styles_are_present() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert ".chat-sandbox-setup-banner" in css
    assert ".chat-sandbox-setup-copy" in css
    assert ".chat-sandbox-setup-actions" in css


def test_chat_sandbox_setup_banner_prefers_human_message_over_detail() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _sandboxSetupMessage")
    body = source[start : source.index("  function _refreshSandboxSetupBanner", start)]

    assert "payload.state === 'failed'" in body
    assert "return `${payload.message}: ${payload.detail}`;" in body
    assert "return payload.message || payload.detail || '';" in body


def test_chat_sandbox_setup_prompt_is_inline_and_reopens_after_not_now() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    render = source[
        source.index("function render(el)")
        : source.index("  function _shouldAutofocusComposer", source.index("function render(el)"))
    ]
    assert "_loadSandboxSetupStatus({ showPrompt: true });" in render
    assert "_ensureSandboxSetupOnly();" not in render

    refresh = source[
        source.index("function _refreshSandboxSetupBanner")
        : source.index("  async function _loadSandboxSetupStatus")
    ]
    assert "const setupKnown = _sandboxSetupStatus !== null;" in refresh
    assert "const setupReady = _isSandboxSetupReadyPayload(_sandboxSetupStatus);" in refresh
    assert "const optionalPrompt = mode === 'full' && !_sandboxSetupPromptDismissed;" in refresh
    assert (
        "const shouldShow = !setupReady && (pendingPrompt || (setupKnown && optionalPrompt));"
        in refresh
    )

    bind = source[
        source.index("function _bindSandboxSetupBanner")
        : source.index("  function _runModeHelp")
    ]
    assert "_sandboxSetupPromptDismissed = true;" in bind
    assert "_setRunMode(_RUN_MODE_DEFAULT, { toast: false });" in bind

    request = source[
        source.index("async function _requestSandboxSetupForMode")
        : source.index("  function _bindSandboxSetupBanner")
    ]
    assert "_sandboxSetupPromptDismissed = false;" in request
    assert "_pendingSandboxSetupMode = mode;" in request


def test_chat_run_mode_does_not_initialize_from_gateway_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
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


def test_global_topbar_does_not_render_duplicate_chat_title() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    topbar_start = source.index('<header class="topbar"')
    topbar_end = source.index('<main class="content"', topbar_start)
    topbar_markup = source[topbar_start:topbar_end]

    assert 'id="topbar-title"' not in topbar_markup
    assert ">Chat</h1>" not in topbar_markup
    assert 'id="conn-pill"' in topbar_markup
    assert 'id="theme-toggle"' in topbar_markup


def test_chat_history_passes_subagent_completion_provenance_to_renderer() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "provenanceSourceTool: msg.provenance_source_tool || ''" in source
    assert "provenanceSourceSessionKey: msg.provenance_source_session_key || ''" in source


def test_chat_suppresses_internal_provider_retry_warning_toasts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    warning_start = source.index("_rpc.on('session.event.warning'")
    warning_end = source.index("    // Track session epoch", warning_start)
    warning_handler = source[warning_start:warning_end]

    assert "const silentWarningCodes = new Set([" in warning_handler
    assert "'provider_reasoning_only_retry'" in warning_handler
    assert "if (silentWarningCodes.has(code)) return;" in warning_handler
    silent_warning_index = warning_handler.index("if (silentWarningCodes.has(code)) return;")
    toast_index = warning_handler.index("UI.toast(msg, 'warn', 5000);")
    assert silent_warning_index < toast_index


def test_chat_toolbar_has_no_tool_compress_selector() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "Tool " + "Compress" not in source
    assert "tool" + "Compress" not in source
    assert "tool-compress" not in source


def test_chat_slash_menu_is_part_of_composer_and_width_capped() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    composer_start = source.index('<div class="chat-composer" id="chat-composer">')
    composer_end = source.index('<input type="file" id="chat-file-input"', composer_start)
    composer_markup = source[composer_start:composer_end]

    assert 'id="chat-slash"' in composer_markup
    assert composer_markup.index('id="chat-slash"') < composer_markup.index(
        'class="chat-input-bar"'
    )
    slash_css = css[css.index(".chat-slash {") : css.index(".chat-slash-item {")]
    assert "var(--chat-measure)" in slash_css

    slash_desc_start = css.index(".chat-slash-desc {")
    slash_desc = css[
        slash_desc_start : css.index("/* ─── Per-bubble", slash_desc_start)
    ]
    assert "min-width: 0;" in slash_desc
    assert "overflow: hidden;" in slash_desc
    assert "text-overflow: ellipsis;" in slash_desc
    assert "white-space: nowrap;" in slash_desc


def test_chat_pending_attachment_preview_is_composer_width_capped() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = css.index(".chat-attachments {")
    end = css.index(".chat-attachments.hidden", start)
    block = css[start:end]

    assert "box-sizing: border-box;" in block
    assert "width: min(calc(100% - var(--sp-8)), var(--chat-measure));" in block
    assert "margin: 0 auto var(--sp-2);" in block
    assert "overflow-x: auto;" in block


def test_chat_day_separator_stays_on_centered_chat_axis() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = css.index(".chat-day-sep {")
    end = css.index(".chat-day-sep::before", start)
    block = css[start:end]

    assert "width: 100%;" in block
    assert "max-width: var(--chat-measure);" in block
    assert "margin: var(--sp-2) auto;" in block


def test_chat_user_bubble_text_uses_reading_direction_alignment() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = css.index(".chat-msg--user .chat-msg-text,")
    end = css.index("/* Assistant", start)
    block = css[start:end]

    assert "display: flex;" in block
    assert "align-items: center;" in block
    assert "justify-content: flex-start;" in block
    assert "text-align: start;" in block


def test_chat_sent_attachment_images_render_as_separate_thumbnail_attachments() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    body_start = css.index(".msg.user .msg-body.msg-body--has-attachments {")
    body_end = css.index(".msg.user .msg-body--has-attachments .msg-attachment-text", body_start)
    body_block = css[body_start:body_end]
    text_start = css.index(".msg.user .msg-body--has-attachments .msg-attachment-text {")
    text_end = css.index(".msg.user .msg-body--has-attachments .msg-attachments", text_start)
    text_block = css[text_start:text_end]
    attachments_start = css.index(".msg.user .msg-body--has-attachments .msg-attachments {")
    attachments_end = css.index(
        ".msg.user .msg-body--has-attachments .msg-thumb",
        attachments_start,
    )
    attachments_block = css[attachments_start:attachments_end]
    thumb_start = css.index(".msg.user .msg-body--has-attachments .msg-thumb {")
    thumb_end = css.index("/* ─── Pending Queue", thumb_start)
    thumb_block = css[thumb_start:thumb_end]

    assert "max-width: min(360px, 78%);" in body_block
    assert "border: 0;" in body_block
    assert "background: transparent;" in body_block
    assert "max-width: min(360px, 100%);" in text_block
    assert "max-width: 100%;" in attachments_block
    assert "user-select: text;" in attachments_block
    assert "width: min(260px, 42vw);" in thumb_block
    assert "height: auto;" in thumb_block
    assert "min-height:" not in thumb_block
    assert "object-fit: contain;" in thumb_block
    assert "background: transparent;" in thumb_block
    assert "border-color: color-mix(in srgb, var(--border) 65%, transparent);" in thumb_block
    assert "box-shadow: none;" in thumb_block
    assert "var(--accent)" not in thumb_block


def test_chat_user_message_bubbles_preserve_multiline_text() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    user_start = css.index(".chat-msg--user .chat-msg-text,")
    user_end = css.index("/* Assistant", user_start)
    user_block = css[user_start:user_end]
    text_start = css.index(".msg.user .msg-body--has-attachments .msg-attachment-text {")
    text_end = css.index(".msg.user .msg-body--has-attachments .msg-attachments", text_start)
    attachment_text_block = css[text_start:text_end]

    assert "white-space: pre-wrap;" in user_block
    assert "overflow-wrap: anywhere;" in user_block
    assert "text-align: start;" in user_block
    assert "white-space: pre-wrap;" in attachment_text_block
    assert "overflow-wrap: anywhere;" in attachment_text_block
    assert "text-align: start;" in attachment_text_block


def test_chat_non_image_message_attachments_render_download_links_when_data_exists() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    render_start = source.index("function _renderMessageAttachmentHtml(att)")
    render_end = source.index("function _renderAttachmentPreview()", render_start)
    render_body = source[render_start:render_end]

    assert "function _escAttr(s)" in source
    assert "function _attachmentDownloadHref(att, mime)" in source
    assert "function _attachmentDownloadName(att)" in source
    assert '<a class="msg-file-chip msg-file-chip--download"' in render_body
    assert 'download="${_escAttr(downloadName)}"' in render_body
    assert 'href="${_escAttr(downloadHref)}"' in render_body
    assert '<span class="msg-file-chip msg-file-chip--disabled"' in render_body


def test_chat_file_attachment_download_links_keep_chip_styling() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    chip_start = css.index(".msg-file-chip {")
    chip_end = css.index(".msg-file-chip__icon", chip_start)
    chip_block = css[chip_start:chip_end]
    download_start = css.index(".msg-file-chip--download {")
    download_end = css.index(".msg-file-chip--download:hover", download_start)
    download_block = css[download_start:download_end]

    assert "text-decoration: none;" in chip_block
    assert "cursor: default;" in chip_block
    assert "cursor: pointer;" in download_block
    assert ".msg-file-chip--download:hover" in css
    assert ".msg-file-chip--download:focus-visible" in css
    assert ".msg-file-chip--disabled" in css


def test_chat_tool_display_map_does_not_reference_removed_wrapper_tools() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("const _TOOL_EMOJI = {")
    end = source.index("  function _toolEmoji", start)
    tool_display_map = source[start:end]

    assert "generate_image" not in tool_display_map
    assert "spawn_subagent" not in tool_display_map
    assert "send_message" not in tool_display_map
    # Display-only mappings for owner-visible or historical tool payloads may remain.
    assert "http_request" in tool_display_map


def test_system_messages_are_not_all_rendered_as_subagent_disclosures() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_isSubagentCompletionMessage(role, text, options)" in source
    assert "body.appendChild(_renderSubagentDisclosure(visibleText));" in source
    assert "body.textContent = visibleText;" in source


def test_live_subagent_completion_event_uses_same_renderer() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "session.event.subagent_completion" in source
    assert "_appendSubagentCompletion(payload)" in source

def test_chat_renders_live_and_historical_artifacts_as_header_auth_downloads() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "session.event.artifact" in source
    assert "_appendArtifact(payload)" in source
    assert "_renderArtifacts(msg.artifacts || [])" in source
    assert "data-artifact-download" in source
    assert "headers['x-opensquilla-session-key'] = _sessionKey" in source
    assert "url.searchParams.delete('sessionKey')" in source
    assert "fetch(downloadUrl" in source
    assert "Authorization" in source


def test_chat_artifact_download_url_carries_query_fallback_auth() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    helper_start = source.index("function _artifactAuthenticatedDownloadUrl(raw, token)")
    helper_end = source.index("  function _renderArtifacts", helper_start)
    helper_body = source[helper_start:helper_end]
    download_start = source.index("async function _downloadArtifact(artifact)")
    download_end = source.index("  function _reconstructToolCalls", download_start)
    download_body = source[download_start:download_end]

    assert "_artifactAuthenticatedDownloadUrl(downloadUrl, token)" in download_body
    assert "url.searchParams.set('sessionKey', _sessionKey)" in helper_body
    assert "url.searchParams.set('token', token)" in helper_body
    assert "headers['x-opensquilla-session-key'] = _sessionKey" in download_body
    assert "headers['Authorization'] = `Bearer ${token}`" in download_body


def test_chat_artifact_downloads_use_direct_links_to_preserve_user_activation() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    bind_start = source.index("function _bindHoverActions()")
    bind_end = source.index("  function _truncate", bind_start)
    bind_body = source[bind_start:bind_end]
    render_start = source.index("function _renderArtifacts(artifacts)")
    render_end = source.index("  async function _downloadArtifact", render_start)
    render_body = source[render_start:render_end]

    assert "if (artifactBtn.tagName === 'A') return;" in bind_body
    assert (
        "const downloadHref = _artifactAuthenticatedDownloadUrl(downloadUrl, token);"
        in render_body
    )
    assert '<a class="msg-artifact-card msg-artifact-card--image"' in render_body
    assert '<a class="msg-artifact-chip"' in render_body
    assert 'href="${_escAttr(downloadHref)}"' in render_body
    assert 'download="${_escAttr(name)}"' in render_body


def test_chat_message_actions_do_not_stick_after_history_rebuild_or_click() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _clearMessageActionFocus(reason = '') {" in source

    clear_start = source.index("function _clearMessageActionFocus(reason = '') {")
    clear_end = source.index("function _attachHoverActions", clear_start)
    clear_body = source[clear_start:clear_end]
    assert "const active = document.activeElement;" in clear_body
    assert "active.closest('.msg-actions')" in clear_body
    assert "active.blur();" in clear_body
    assert "_chatDiag('message_actions.focus_cleared'" in clear_body

    hover_start = source.index("function _bindHoverActions()")
    hover_end = source.index("  function _truncate", hover_start)
    hover_body = source[hover_start:hover_end]
    assert "btn.blur();" in hover_body
    assert "const action = btn.dataset.action;" in hover_body
    assert hover_body.index("btn.blur();") < hover_body.index("const action = btn.dataset.action;")

    history_start = source.index("function _renderHistoryMessages(messages, opts = {})")
    history_end = source.index("function _historyLiveTailAnchor", history_start)
    history_body = source[history_start:history_end]
    assert "_clearMessageActionFocus('history_rebuild');" in history_body


def test_chat_artifact_images_render_as_preview_cards_and_refresh_on_done() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    preview_start = source.index("function _artifactPreviewUrl(artifact)")
    preview_end = source.index("  function _renderArtifacts", preview_start)
    preview_body = source[preview_start:preview_end]
    render_start = source.index("function _renderArtifacts(artifacts)")
    render_end = source.index("  async function _downloadArtifact", render_start)
    render_body = source[render_start:render_end]
    done_start = source.index("if (event.endsWith('.done') || event === 'chat.done') {")
    done_end = source.index("        // On natural completion", done_start)
    done_body = source[done_start:done_end]

    assert "function _isImageArtifact(artifact)" in source
    assert "function _artifactCategory(artifact)" in source
    assert "function _artifactPreviewUrl(artifact)" in source
    assert "url.searchParams.set('sessionKey', _sessionKey)" in preview_body
    assert "const token = (App.getAuthToken && App.getAuthToken()) || '';" in preview_body
    assert "url.searchParams.set('token', token)" in preview_body
    assert "msg-artifact-gallery" in render_body
    assert "msg-artifact-files" in render_body
    assert "class=\"msg-artifact-card msg-artifact-card--image\"" in render_body
    assert "<img class=\"msg-artifact-preview\"" in render_body
    assert "data-artifact-download" in render_body
    assert "data-artifact-category" in render_body
    assert "_scheduleHistorySync();" in done_body
    assert ".msg-artifact-gallery" in css
    assert ".msg-artifact-files" in css
    assert ".msg-artifact-card--image" in css
    assert ".msg-artifact-preview" in css


def test_chat_audio_artifacts_render_inline_players_with_download_fallback() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    render_start = source.index("function _renderArtifacts(artifacts)")
    render_end = source.index("  async function _downloadArtifact", render_start)
    render_body = source[render_start:render_end]

    assert "function _isAudioArtifact(artifact)" in source
    assert "_isAudioArtifact(artifact)" in render_body
    assert '<div class="msg-artifact-card msg-artifact-card--audio"' in render_body
    assert '<audio class="msg-artifact-audio" controls preload="metadata"' in render_body
    assert 'src="${_escAttr(downloadHref)}"' in render_body
    assert '<a class="msg-artifact-card__action"' in render_body
    assert 'download="${_escAttr(name)}"' in render_body
    assert ".msg-artifact-card--audio" in css
    assert ".msg-artifact-audio" in css


def test_chat_final_text_reconciliation_preserves_live_artifacts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _replaceStreamText(finalText)")
    end = source.index("  function _reconcileFinalStreamText", start)
    body = source[start:end]

    assert "_renderStreamArtifacts();" in body


def test_chat_markdown_export_includes_artifact_download_entries() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _exportMarkdown()")
    end = source.index("  /* ── Pending Queue", start)
    export_body = source[start:end]

    assert "artifacts: msg.artifacts || []" in source
    assert "_artifactMarkdownLines(msg.artifacts || [])" in export_body
    assert "[Download" in source


def test_chat_resets_stream_timeout_on_run_heartbeat() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "session.event.run_heartbeat" in source
    assert "_resetStreamIdleTimer();" in source
    assert "_DEFAULT_STREAM_IDLE_TIMEOUT_MS = 210000" in source
    assert "webui_stream_idle_grace_ms" in source


def test_chat_shows_awaiting_model_hint_after_tool_result_heartbeat() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    heartbeat_start = source.index("_rpc.on('session.event.run_heartbeat'")
    heartbeat_end = source.index("    }));", heartbeat_start)
    heartbeat_body = source[heartbeat_start:heartbeat_end]
    tool_result_start = source.index("function _appendToolResult(payload)")
    tool_result_end = source.index("  // ── PR5", tool_result_start)
    tool_result_body = source[tool_result_start:tool_result_end]

    assert "const _AWAITING_MODEL_CLASS = 'awaiting-model';" in source
    assert "function _showAwaitingModelHintAfterToolResult()" in source
    assert "_markVisibleStreamEvent('tool_result');" in tool_result_body
    assert "_showAwaitingModelHintAfterToolResult();" in heartbeat_body
    assert "if (_streamBubble)" in heartbeat_body
    assert "_showThinkingIndicator();" in heartbeat_body
    assert ".msg.streaming.awaiting-model::after" in css
    assert "content: 'waiting for model response...';" in css
    assert "textContent = 'waiting for model response" not in source
    assert "document.createTextNode('waiting for model response" not in source


def test_chat_streaming_indicator_uses_delayed_bottom_dock() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert ".msg.streaming.streaming-active-mark:not(.awaiting-model) .msg-body::after" in css
    assert "padding-bottom: calc(var(--sp-2) + 24px);" in css
    # Mark is corner-aligned to the content-left edge and centered in the
    # reserved footer band, so the orbiting ring clears the tool card above
    # and the bubble's bottom edge — no overlap, no rightward-inset orphan.
    assert "left: var(--sp-4);" in css
    assert "bottom: var(--sp-2);" in css
    assert "left: calc(var(--sp-4) - 4px);" in css
    assert "bottom: calc(var(--sp-2) - 4px);" in css
    assert "left: calc(var(--sp-4) + 16px);" not in css
    assert "background-image: url('../../img/opensquilla-mark.png');" in css
    assert "width: 16px;" in css
    assert "height: 16px;" in css
    assert "background-size: 11px 11px;" in css
    assert "border-radius: 50%;" in css
    assert "0 0 0 1px color-mix(in srgb, var(--accent) 7%, transparent)" in css
    # Orbital-sweep design: the figurative squilla mark stays UPRIGHT and
    # legible (no spin on ::after); the motion lives in an orbiting ring
    # rendered on ::before. The mark must not tumble.
    assert "animation: squilla-activity-spin 1.6s linear infinite;" not in css
    assert ".msg.streaming.streaming-active-mark:not(.awaiting-model) .msg-body::before" in css
    assert "background: conic-gradient(from 0deg," in css
    assert "var(--accent-secondary) 320deg," in css
    assert (
        "mask: radial-gradient(farthest-side, transparent calc(100% - 2px), "
        "#000 calc(100% - 2px));"
        in css
    )
    assert "animation: squilla-activity-spin 1.15s linear infinite;" in css
    assert "@keyframes squilla-activity-spin" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".chat-tools-collapse--running > .chat-tools-summary .chat-tools-icon" not in css
    assert ".msg-text-seg:not(:empty):last-of-type > :last-child::after" not in css
    assert "streaming-harbor" not in css
    assert "animation: squilla-harbor-peek" not in css
    assert "@keyframes squilla-harbor-peek" not in css
    assert "animation: squilla-harbor-spin" not in css
    assert "@keyframes squilla-harbor-spin" not in css
    assert "animation: squilla-harbor-wave" not in css
    assert "@keyframes squilla-harbor-wave" not in css
    assert "animation: squilla-dock-patrol" not in css
    assert "@keyframes squilla-dock-patrol" not in css
    assert "animation: shrimp-roll" not in css
    assert "@keyframes shrimp-roll" not in css


def test_chat_streaming_active_mark_reveals_after_visible_bubble_delay() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _STREAM_ACTIVE_MARK_CLASS = 'streaming-active-mark';" in source
    assert "const _STREAM_ACTIVE_MARK_DELAY_MS = 3500;" in source
    assert "let _streamActiveMarkVisibleStartedAt = 0;" in source
    assert "function _beginStreamActiveMarkRevealWindow()" in source

    start_stream_start = source.index("function _startStreaming()")
    start_stream_end = source.index("  function _ensureStreamBubble", start_stream_start)
    start_stream_body = source[start_stream_start:start_stream_end]
    assert "_scheduleStreamActiveMarkReveal();" not in start_stream_body
    assert "_beginStreamActiveMarkRevealWindow();" not in start_stream_body

    ensure_start = source.index("function _ensureStreamBubble()")
    ensure_end = source.index("  /** Create a new .msg-text-seg", ensure_start)
    ensure_body = source[ensure_start:ensure_end]
    assert "_beginStreamActiveMarkRevealWindow();" in ensure_body
    assert "_maybeRevealStreamActiveMark();" in ensure_body

    reveal_start = source.index("function _maybeRevealStreamActiveMark()")
    reveal_end = source.index("  function _scheduleStreamActiveMarkReveal", reveal_start)
    reveal_body = source[reveal_start:reveal_end]
    assert (
        "_streamActiveMarkVisibleStartedAt ? Date.now() - _streamActiveMarkVisibleStartedAt : 0"
        in reveal_body
    )

    end_stream_start = source.index("function _endStreaming(opts)")
    end_stream_end = source.index("  function _hasViewLocalStreamState", end_stream_start)
    end_stream_body = source[end_stream_start:end_stream_end]
    assert "_clearStreamActiveMarkReveal();" in end_stream_body


def test_chat_clears_awaiting_model_hint_on_next_visible_event_and_stream_reset() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    append_delta_start = source.index("function _appendDelta(text)")
    append_delta_end = source.index("  function _flushPendingTextSegment", append_delta_start)
    append_delta_body = source[append_delta_start:append_delta_end]
    append_tool_start = source.index("function _appendToolCall(payload)")
    append_tool_end = source.index("  function _appendToolResult(payload)", append_tool_start)
    append_tool_body = source[append_tool_start:append_tool_end]
    append_artifact_start = source.index("function _appendArtifact(payload)")
    append_artifact_end = source.index("  function _renderStreamArtifacts", append_artifact_start)
    append_artifact_body = source[append_artifact_start:append_artifact_end]
    end_stream_start = source.index("function _endStreaming(opts)")
    end_stream_end = source.index("  function _hasViewLocalStreamState", end_stream_start)
    end_stream_body = source[end_stream_start:end_stream_end]
    clear_state_start = source.index("function _clearViewLocalStreamState(reason)")
    clear_state_end = source.index("  function _updateSendButton", clear_state_start)
    clear_state_body = source[clear_state_start:clear_state_end]

    assert "_markVisibleStreamEvent('text_delta');" in append_delta_body
    assert "_markVisibleStreamEvent('tool_use_start');" in append_tool_body
    assert "_markVisibleStreamEvent('artifact');" in append_artifact_body
    assert "_clearAwaitingModelHint();" in end_stream_body
    assert "_lastVisibleStreamEvent = '';" in end_stream_body
    assert "_lastVisibleStreamEvent = '';" in clear_state_body


def test_chat_tool_results_use_execution_status_for_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _toolExecutionStatus(payload)" in source
    assert "function _toolResultIsError(payload)" in source
    assert "function _toolResultStateClass(payload)" in source
    assert "chat-tools-collapse--unknown" in source
    assert "_toolResultIsTruncated(payload)," in source
    assert "_toolResultIsTruncated(seg)," in source


def test_chat_publish_artifact_tool_cards_show_target_filename() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    build_start = source.index("function _buildToolCallDOM")
    build_end = source.index("  function _findToolDetailsById", build_start)
    build_body = source[build_start:build_end]

    assert "function _toolDisplayName(name, input)" in source
    assert "function _publishArtifactTargetName(input)" in source
    assert "name === 'publish_artifact'" in source
    assert "input.name || input.path" in source
    assert "summary.appendChild(document.createTextNode(' ' + displayName));" in build_body
    assert "_buildToolCallDOM(name, toolId, input, true)" in source
    assert (
        "_buildToolCallDOM(seg.name || 'tool', seg.tool_use_id || '', seg.input || '', false)"
        in source
    )


def test_chat_meta_step_cards_explain_long_running_work() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    build_start = source.index("function _buildToolCallDOM")
    build_end = source.index("  function _findToolDetailsById", build_start)
    build_body = source[build_start:build_end]

    assert "function _metaStepRunningHint(name)" in source
    assert "stepId.endsWith('_video')" in source
    assert "may take several minutes" in source
    assert "chat-meta-step-running-hint" in build_body
    assert "_metaStepRunningHint(name)" in build_body
    assert ".chat-meta-step-running-hint" in css


def test_chat_memory_search_results_surface_sources() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert "function _memorySearchSourceRows(content)" in source
    assert "function _buildMemorySearchSourceDOM(content)" in source
    assert "toolName === 'memory_search'" in source
    assert "data-tool-name" in source
    assert "chat-memory-source-badge--sessions" in css
    assert "chat-memory-source-citation" in css


def test_chat_live_tool_result_provider_badge_is_web_search_only() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _appendToolResult(payload)")
    end = source.index("    // Only show result preview", start)
    live_result_body = source[start:end]

    guard_start = live_result_body.index("if (toolName === 'web_search'")
    block_start = live_result_body.index("{", guard_start)
    depth = 0
    block_end = -1
    for idx in range(block_start, len(live_result_body)):
        if live_result_body[idx] == "{":
            depth += 1
        elif live_result_body[idx] == "}":
            depth -= 1
            if depth == 0:
                block_end = idx
                break
    assert block_end != -1

    guarded_block = live_result_body[block_start:block_end]
    assert live_result_body.count("_toolResultProvider(payload, content)") == 1
    assert live_result_body.count("_injectProviderBadge") == 1
    assert "_toolResultProvider(payload, content)" in guarded_block
    assert "_injectProviderBadge" in guarded_block


def test_chat_tool_result_can_retitle_coerced_tool_cards() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    live_start = source.index("function _appendToolResult(payload)")
    live_end = source.index("    // Only show result preview", live_start)
    live_body = source[live_start:live_end]
    history_start = source.index("function _reconstructToolCalls(bubbleDiv, segments)")
    history_end = source.index("  function _renderMessageTags", history_start)
    history_body = source[history_start:history_end]

    assert "function _retitleToolCallDOM(details, name, input)" in source
    assert (
        "_retitleToolCallDOM(details, toolName, payload.arguments || payload.input || '')"
        in live_body
    )
    assert "const resultToolName = seg.name || _toolNameById[toolId] || '';" in history_body
    assert "_retitleToolCallDOM(details, resultToolName, seg.input || '')" in history_body


def test_chat_tool_result_full_view_uses_stable_modal_class() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    build_start = source.index("function _buildToolResultDOM")
    build_end = source.index("  function _appendToolCall", build_start)
    build_body = source[build_start:build_end]

    assert "class=\"chat-tool-result-full\"" in build_body
    assert "style=\"white-space:pre-wrap" not in build_body
    assert "viewBtn.type = 'button';" in build_body
    assert "event.stopPropagation();" in build_body
    assert ".chat-tool-result-full" in css
    assert "overflow-wrap: anywhere;" in css
    assert "max-width: min(" in css


def test_chat_historical_tool_results_stringify_non_string_payloads() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _reconstructToolCalls(bubbleDiv, segments)")
    history_end = source.index("  function _renderMessageTags", history_start)
    history_body = source[history_start:history_end]

    assert "function _toolResultContent" in source
    assert "const content = _toolResultContent(seg);" in history_body
    assert "const content = _toolResultContent(payload);" in source
    assert "JSON.stringify(raw, null, 2)" in source


def test_router_control_is_hidden_from_regular_tool_cards() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    append_tool_start = source.index("function _appendToolCall(payload)")
    append_tool_end = source.index("  function _appendToolResult(payload)", append_tool_start)
    append_tool_body = source[append_tool_start:append_tool_end]
    append_result_start = source.index("function _appendToolResult(payload)")
    append_result_end = source.index(
        "  // \u2500\u2500 PR5: meta-skill user_input form rendering",
        append_result_start,
    )
    append_result_body = source[append_result_start:append_result_end]
    history_start = source.index("function _reconstructToolCalls(bubbleDiv, segments)")
    history_end = source.index("  function _renderMessageTags", history_start)
    history_body = source[history_start:history_end]

    assert "function _isControlPlaneToolName(name)" in source
    assert "return name === 'router_control';" in source
    assert "if (_isControlPlaneToolName(name))" in append_tool_body
    assert "tool_call.append.skip_control_plane" in append_tool_body
    assert "if (_isControlPlaneToolName(toolName))" in append_result_body
    assert "tool_result.append.skip_control_plane" in append_result_body
    assert "if (_isControlPlaneToolName(seg.name || '')) continue;" in history_body
    assert "if (_isControlPlaneToolName(resultToolName)) continue;" in history_body


def test_chat_search_provider_badge_updates_running_web_search_cards() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "let badge = summary.querySelector('.chat-tool-provider');" in source
    assert "badge = document.createElement('span');" in source
    assert "function _refreshRunningSearchProviderBadges(provider)" in source
    assert (
        '.chat-tools-collapse--running[data-tool-name="web_search"] .chat-tools-summary'
        in source
    )
    assert "_setSearchProvider(res.provider)" in source
    assert "_setSearchProvider(provider, { refreshRunning: false })" in source


def test_chat_url_agent_query_resolves_default_webchat_session() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _readAgentFromUrl()" in source
    assert "function _webchatSessionKey(agentId, suffix = 'default')" in source
    assert "const urlAgent = _readAgentFromUrl();" in source
    assert "urlSession || (urlAgent ? _webchatSessionKey(urlAgent) : storedSession)" in source
    assert "url.searchParams.delete('agent');" in source


def test_chat_subscribe_does_not_advance_cursor_before_replayed_events() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _subscribeSession()")
    end = source.index("  async function _unsubscribeSession()", start)
    body = source[start:end]

    assert "Number(res.replayed_count || 0) <= 0" in body
    assert "replayed_count" in body


def test_chat_stream_seq_drops_only_seen_duplicates_not_late_unique_events() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _streamSeqSeenBySession = new Map();" in source
    assert "const _STREAM_SEQ_SEEN_WINDOW = 800;" in source
    assert "function _markSessionStreamSeqSeen(key, seq)" in source

    start = source.index("function _acceptStreamSeq(payload)")
    end = source.index("function _eventHasSpecificSessionHandler(event)", start)
    body = source[start:end]

    assert "return _markSessionStreamSeqSeen(key, seq);" in body
    assert "seq <= lastSeq" not in body

    marker_start = source.index("function _markSessionStreamSeqSeen(key, seq)")
    marker_end = source.index("function _syncLastStreamSeqFromSession(key)", marker_start)
    marker_body = source[marker_start:marker_end]
    assert "if (seen.has(seq)) return false;" in marker_body
    assert "seen.add(seq);" in marker_body
    assert "_setSessionStreamSeq(key, seq);" in marker_body
    assert "value < pruneBefore" in marker_body


def test_chat_new_session_uses_current_agent_namespace() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    click_start = source.index("newBtn.addEventListener('click'")
    click_end = source.index("    // Export", click_start)
    click_body = source[click_start:click_end]
    helper_start = source.index("function _startNewChatSession(source)")
    helper_end = source.index("  /* ── Event Bindings", helper_start)
    helper_body = source[helper_start:helper_end]
    slash_start = source.index("      case 'new_chat':")
    slash_end = source.index("      case 'reset_session':", slash_start)
    slash_body = source[slash_start:slash_end]

    assert "function _agentIdFromSessionKey(key)" in source
    assert "return _webchatSessionKey(_agentIdFromSessionKey(_sessionKey)," in source
    assert 'title="New chat session in the current agent"' in source
    assert "New chat session in the current agent: " in source
    assert "_startNewChatSession('new_chat')" in click_body
    assert "const key = _genKey();" in helper_body
    assert "_updateSessionChip(key);" in helper_body
    assert "_persistSession(key);" in helper_body
    assert "_loadHistory(" not in click_body
    assert "_loadHistory(" not in slash_body


def test_chat_slash_menu_loads_web_chat_catalog_from_rpc() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _SLASH_CMDS = [" not in source
    assert "let _slashCmds = [];" in source
    assert "let _slashCommandMap = new Map();" in source
    assert "let _slashCatalogLoaded = false;" in source
    assert "async function _loadSlashCommands()" in source
    assert "_rpc.call('commands.list_for_surface', { surface: 'web_chat' })" in source
    assert "_slashCommandMap.set(_slashCommandKey(cmd.name), cmd);" in source
    assert "cmd.aliases || []" in source
    assert "_loadSlashCommands();" in source


def test_chat_slash_input_supports_literal_slash_escape() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    send_start = source.index("async function _onSend()")
    send_end = source.index("    // Reset abort flag for new message", send_start)
    send_prefix = source[send_start:send_end]

    assert "let isLiteralSlash = false;" in send_prefix
    assert "if (text.startsWith('//')) {" in send_prefix
    assert "isLiteralSlash = true;" in send_prefix
    assert "text = text.slice(1);" in send_prefix
    literal_idx = send_prefix.index("if (text.startsWith('//')) {")
    normalize_idx = send_prefix.index("const normalized = await _normalizeOutgoingComposerPayload(")
    slash_exec_guard_idx = send_prefix.index("if (!isLiteralSlash && text.startsWith('/')) {")
    assert literal_idx < normalize_idx < slash_exec_guard_idx
    assert "{ allowSlashCommand: isSlashCommand }" in send_prefix
    assert "!!(await _lookupSlashCommand(text))" in send_prefix
    assert "await _executeSlashCommand(text)" in send_prefix
    assert "if (val.startsWith('//')) { _closeSlashMenu(); return; }" in source


def test_chat_slash_commands_are_blocked_while_streaming_after_literal_escape() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    send_start = source.index("async function _onSend()")
    send_end = source.index("    // Reset abort flag for new message", send_start)
    send_prefix = source[send_start:send_end]

    flag_idx = send_prefix.index("let isLiteralSlash = false;")
    literal_idx = send_prefix.index("if (text.startsWith('//')) {")
    flag_set_idx = send_prefix.index("isLiteralSlash = true;")
    normalize_idx = send_prefix.index("const normalized = await _normalizeOutgoingComposerPayload(")
    streaming_idx = send_prefix.index(
        "if (_isStreaming || _isCompactInFlightForCurrentSession()) {"
    )
    execute_idx = send_prefix.index("await _executeSlashCommand(text)")
    streaming_guard = "if (isSlashCommand) {"
    real_slash_guard = "if (!isLiteralSlash && text.startsWith('/')) {"
    streaming_block_end = send_prefix.index(f"\n\n    {real_slash_guard}", streaming_idx)
    streaming_block = send_prefix[streaming_idx:streaming_block_end]

    assert flag_idx < literal_idx < normalize_idx < streaming_idx
    assert literal_idx < flag_set_idx < normalize_idx
    assert "text = text.slice(1);" in send_prefix[literal_idx:normalize_idx]
    assert "text = normalized.text;" in send_prefix[normalize_idx:streaming_idx]
    assert (
        "attachmentsForSend = normalized.attachments;"
        in send_prefix[normalize_idx:streaming_idx]
    )
    assert streaming_guard in streaming_block
    assert "const waitReason = _isCompactInFlightForCurrentSession()" in streaming_block
    assert "Wait for ${waitReason} before running" in streaming_block
    assert "_executeSlashCommand" not in streaming_block
    assert streaming_idx < execute_idx
    assert real_slash_guard in send_prefix[streaming_idx:execute_idx]


def test_chat_slash_executor_lets_unknown_slash_input_fall_through() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    lookup_start = source.index("async function _lookupSlashCommand(text)")
    lookup_end = source.index("async function _executeSlashCommand(text)", lookup_start)
    exec_start = source.index("async function _executeSlashCommand(text)")
    exec_end = source.index("  /* ── Send Message", exec_start)
    lookup = source[lookup_start:lookup_end]
    executor = source[exec_start:exec_end]

    assert "await _loadSlashCommands()" in lookup
    assert "_slashCommandMap.get(_slashCommandKey(cmdText)) || null" in lookup
    assert "const cmd = await _lookupSlashCommand(text);" in executor
    assert "Unsupported command" not in executor
    assert "return false;" in executor
    assert "chat.send" not in executor


def test_chat_image_paste_prevents_default_only_after_attachment_acceptance() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    paste_start = source.index("const pasteHandler = (e) => {")
    paste_end = source.index("    document.addEventListener('paste', pasteHandler);", paste_start)
    paste_body = source[paste_start:paste_end]

    assert "let consumedAttachment = false;" in paste_body
    assert "if (file && _addAttachment(file)) consumedAttachment = true;" in paste_body
    assert "if (consumedAttachment) e.preventDefault();" in paste_body
    assert paste_body.index("_addAttachment(file)") < paste_body.index("e.preventDefault()")


def test_chat_add_attachment_reports_acceptance_for_paste_handler() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    add_start = source.index("function _addAttachment(file)")
    add_end = source.index(
        "  async function _uploadAttachmentStaged(file, mime, localId)",
        add_start,
    )
    add_body = source[add_start:add_end]

    assert "return false;" in add_body[
        add_body.index("if (!_isAllowedAttachmentMime(mime))") :
        add_body.index("const hardCap = _attachmentHardCapBytes(mime);")
    ]
    assert "return false;" in add_body[
        add_body.index("if (file.size > hardCap)") :
        add_body.index("const localId = _nextAttachmentId++;")
    ]
    assert "reader.readAsDataURL(file);" in add_body
    assert "reader.readAsDataURL(file);\n      return true;" in add_body
    assert "_uploadAttachmentStaged(file, mime, localId).catch" in add_body
    assert add_body.rstrip().endswith("return true;\n  }")


def test_chat_usage_slash_commands_call_usage_rpcs() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    select_start = source.index("function _selectSlashCmd(cmd, args = '')")
    select_end = source.index("  async function _executeSlashCommand(text)", select_start)
    selector = source[select_start:select_end]

    assert "case 'usage_status':" in selector
    assert (
        "const usageMethod = args.trim().toLowerCase() === 'cost' "
        "? 'usage.cost' : 'usage.status';"
    ) in selector
    assert "_rpc.call(usageMethod)" in selector
    assert "Usage cost" in source


def test_chat_usage_slash_status_reads_top_level_and_totals_fields() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    select_start = source.index("function _selectSlashCmd(cmd, args = '')")
    usage_start = source.index("case 'usage_status':", select_start)
    usage_end = source.index("          .catch((err) => UI.toast('Usage failed:", usage_start)
    usage_block = source[usage_start:usage_end]

    for field_name in (
        "result?.totalTokens",
        "result?.total_tokens",
        "result?.totalCostUsd",
        "result?.total_cost_usd",
        "totals.tokens",
        "totals.total_tokens",
        "totals.cost",
        "totals.cost_usd",
    ):
        assert field_name in usage_block


def test_chat_switching_existing_session_does_not_mark_new_chat_intent() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    switch_start = source.index("function _switchToSession(key)")
    switch_end = source.index("  function _bindSessionChip()", switch_start)
    switch_body = source[switch_start:switch_end]

    assert "_pendingSessionIntent = 'new_chat'" not in switch_body
    assert source.count("_pendingSessionIntent = 'new_chat'") == 1
    assert "_startNewChatSession('new_chat')" in source
    assert (
        "const sessionIntentForSend = textOverride !== null ? null : _pendingSessionIntent;"
        in source
    )
    assert "params.intent = sessionIntentForSend;" in source
    assert "params._source.runMode = _normalizeRunMode(_runMode);" in source


def test_chat_regenerate_targets_clicked_assistant_bubble() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    hover_start = source.index("function _bindHoverActions()")
    hover_end = source.index("  function _truncate", hover_start)
    hover_body = source[hover_start:hover_end]
    regen_start = source.index("function _regenerateAssistantBubble(bubble)")
    regen_end = source.index("  // Pop the user message back into the textarea", regen_start)
    regen_body = source[regen_start:regen_end]

    assert "_regenerateAssistantBubble(bubble);" in hover_body
    assert "_regenerateLastTurn" not in source
    assert "querySelectorAll(':scope > .msg.assistant')" in regen_body
    assert "const assistantOrdinal = assistantBubbles.indexOf(bubble);" in regen_body
    assert "assistantSeen === assistantOrdinal" in regen_body
    assert "_messages.splice(userIdx + 1);" in regen_body


def test_chat_maps_task_terminal_events_during_migration() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _taskTerminalAsSessionEvent(event, payload)" in source
    assert "task.failed" in source
    assert "task.timeout" in source
    assert "task.abandoned" in source
    assert "task.cancelled" in source
    assert "function _taskTerminalMessage(status, payload)" in source
    assert "function _sessionErrorMessage(payload)" in source
    assert "payload?.terminal_message" in source
    terminal_mapper = source[
        source.index("function _taskTerminalAsSessionEvent(event, payload)") :
        source.index("function _taskTerminalMessage(status, payload)")
    ]
    assert "Gateway task" not in terminal_mapper
    error_start = source.index("} else if (event.endsWith('.error'))")
    error_end = source.index("if (_activeTaskGroups.size > 0)", error_start)
    error_handler = source[error_start:error_end]
    assert "_sessionErrorMessage(payload)" in error_handler


def test_chat_succeeded_task_without_done_falls_back_to_history_sync() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    wildcard_start = source.index("const terminalStatus = _taskTerminalStatus(rawEvent);")
    wildcard_end = source.index(
        "const normalized = _taskTerminalAsSessionEvent(rawEvent, rawPayload);"
    )
    terminal_handler = source[wildcard_start:wildcard_end]
    fallback_start = source.index("function _scheduleSucceededTaskTerminalSync(payload = {})")
    fallback_end = source.index("  function _taskTerminalAsSessionEvent", fallback_start)
    fallback = source[fallback_start:fallback_end]

    assert "rawEvent === 'task.succeeded'" in terminal_handler
    assert "_scheduleSucceededTaskTerminalSync(rawPayload);" in terminal_handler
    assert "let _streamGeneration = 0;" in source
    assert "_streamGeneration += 1;" in source
    assert "const streamGeneration = _streamGeneration;" in fallback
    assert "_scheduleHistorySync();" in fallback
    assert "if (_isStreaming && _streamGeneration === streamGeneration)" in fallback
    assert "_endStreaming();" in fallback


def test_chat_reconciles_terminal_session_changed_events() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "if (value === 'killed') return 'cancelled';" in source
    assert "function _sessionChangeIsTerminal(payload)" in source
    assert "function _syncTerminalSessionChange(payload = {})" in source
    sessions_changed = source[
        source.index("_rpc.on('sessions.changed'") :
        source.index("_rpc.on('task.queued'", source.index("_rpc.on('sessions.changed'"))
    ]
    assert "_sessionChangeIsTerminal(payload)" in sessions_changed
    assert "_syncTerminalSessionChange(payload);" in sessions_changed
    assert "_applySessionRunState(payload);" in sessions_changed
    done_handler = source[
        source.index("const _doneWasAborted = payload?.reason === 'aborted';") :
        source.index("} else if (event.endsWith('.error'))")
    ]
    assert "run_status: 'cancelled'" in done_handler
    assert "status: 'cancelled'" in done_handler


def test_chat_failed_task_message_prefers_payload_error_detail() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    start = source.index("function _taskTerminalMessage(status, payload)")
    end = source.index("  function _sessionErrorMessage(payload)", start)
    body = source[start:end]

    assert "const failedDetail = _payloadErrorDetail(payload);" in body
    assert "if (failedDetail) return failedDetail;" in body
    assert "function _payloadErrorDetail(payload)" in source
    for field_name in ("error", "message", "error_message", "detail"):
        assert f"payload?.{field_name}" in source


def test_chat_error_event_refreshes_from_persisted_transcript() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    error_start = source.index("} else if (event.endsWith('.error'))")
    error_end = source.index("      }", source.index("_applySessionRunState({", error_start))
    error_body = source[error_start:error_end]

    assert "_addMessage('error', _sessionErrorMessage(payload));" in error_body
    assert "_scheduleHistorySync();" in error_body


def test_chat_subscribe_failure_is_visible() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "Session stream subscription failed:" in source
    assert "No subscription manager available" in source


def test_chat_subscribe_uses_stream_replay_cursor() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _subscribeSession() {")
    end = source.index("  async function _unsubscribeSession()", start)
    body = source[start:end]

    assert "let _lastStreamSeq = 0;" in source
    assert "const _streamSeqBySession = new Map();" in source
    assert "params.since_stream_seq = _sessionStreamSeq(subscribeKey);" in source
    assert "params.since_stream_seq = _lastStreamSeq;" not in source
    assert "if (_lastStreamSeq > 0) params.since_stream_seq = _lastStreamSeq;" not in body
    assert "function _acceptStreamSeq(payload)" in source
    assert "function _replayGapShouldWarn(reason)" in source
    assert "Session stream gap detected; reloading transcript." not in body


def test_chat_stream_handlers_drop_replayed_duplicate_frames() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _subscribeRpcEvents() {")
    end = source.index("  /* ── Chat History", start)
    body = source[start:end]

    assert "function _acceptStreamSeq(payload)" in source
    assert "if (!_acceptStreamSeq(payload)) return;" in body
    assert "_noteStreamSeq(payload);" not in body


def test_chat_replayed_wait_events_do_not_bootstrap_live_thinking() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _subscribeRpcEvents() {")
    end = source.index("  /* ── Chat History", start)
    body = source[start:end]

    assert "function _dropReplayedLiveWaitEvent(meta, payload, eventName)" in source
    assert "_rpc.on('session.event.state_change', (payload, meta = {}) =>" in body
    assert "_rpc.on('session.event.run_heartbeat', (payload, meta = {}) =>" in body
    assert "_dropReplayedLiveWaitEvent(meta, payload, 'event.state_change')" in body
    assert "_dropReplayedLiveWaitEvent(meta, payload, 'event.run_heartbeat')" in body

    subscribe_start = source.index("async function _subscribeSession() {")
    subscribe_end = source.index("  async function _unsubscribeSession()", subscribe_start)
    subscribe_body = source[subscribe_start:subscribe_end]
    assert "const subscribedState = _sessionRunStatus(res);" in subscribe_body
    assert "_runStatusIsActive(subscribedState.status)" in subscribe_body


def test_chat_stream_seq_cursor_is_scoped_per_session() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _acceptStreamSeq(payload)")
    end = source.index("  function _showThinkingIndicator()", start)
    body = source[start:end]

    assert "function _sessionStreamSeq(key)" in source
    assert "function _setSessionStreamSeq(key, seq)" in source
    assert "function _syncLastStreamSeqFromSession(key)" in source
    assert "function _markSessionStreamSeqSeen(key, seq)" in source
    assert "const key = _sessionKeyFromPayload(payload) || _sessionKey || '';" in body
    assert "return _markSessionStreamSeqSeen(key, seq);" in body
    assert "seq <= lastSeq" not in body
    assert "_syncLastStreamSeqFromSession(canonicalKey);" in source


def test_chat_surfaces_persisted_run_state_in_header_and_session_picker() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert 'id="chat-run-status"' in source
    assert "function _sessionRunStatus(source)" in source
    assert "function _applySessionRunState(source)" in source
    assert "_applySessionRunState(res);" in source
    assert "_applySessionRunState({ run_status: 'running'" in source
    assert "chat-session-popover-item-run" in source
    # Run-status pill renders as a shared .chip with a color modifier picked
    # by the _runStatusChipClass helper (see components.css for .chip styling).
    assert "_runStatusChipClass" in source
    assert ".chat-session-popover-item-run" in css


def test_chat_resets_replay_cursor_after_stream_gap() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _subscribeSession() {")
    end = source.index("  async function _unsubscribeSession()", start)
    body = source[start:end]

    assert "if (res && res.replay_complete === false)" in body
    assert "_setSessionStreamSeq(subscribeKey, res.current_stream_seq);" in body
    assert "const replayGapReason = res.replay_gap_reason || res.replayGapReason || '';" in body
    assert "if (_replayGapShouldWarn(replayGapReason))" in body
    assert "_loadHistory(_historyRefreshScrollOptions());" in body
    assert body.index("_setSessionStreamSeq(subscribeKey, res.current_stream_seq);") < body.index(
        "_loadHistory(_historyRefreshScrollOptions());"
    )
    assert body.index("if (_replayGapShouldWarn(replayGapReason))") < body.index(
        "_loadHistory(_historyRefreshScrollOptions());"
    )


def test_chat_replay_gap_history_refresh_preserves_reader_scroll() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _historyRefreshScrollOptions()" in source
    start = source.index("function _historyRefreshScrollOptions()")
    end = source.index("function _scheduleHistorySync", start)
    body = source[start:end]

    assert "!_thread || !_historyHasRendered" in body
    assert "_thread.scrollHeight - _thread.scrollTop - _thread.clientHeight" in body
    assert "if (gap < 60) return {};" in body
    assert "preserveScroll: true" in body
    assert "previousScrollHeight: _thread.scrollHeight" in body
    assert "previousScrollTop: _thread.scrollTop" in body


def test_chat_empty_history_preserves_live_stream_bubble() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _renderHistoryMessages(messages")
    end = source.index("    const existingByStableIdentity = new Map();", start)
    body = source[start:end]

    live_guard = "if (_isStreaming && ("
    assert "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');" in body
    assert (
        "const liveThinking = _isCurrentSessionThinkingIndicator(_thinkingEl) "
        "? _thinkingEl : null;"
    ) in body
    assert live_guard in body
    assert "_isCurrentSessionStreamBubble(_streamBubble)" in body
    assert "|| liveRouterStrips.length > 0" in body
    assert "|| liveUserAnchor" in body
    assert "|| liveThinking" in body
    assert (
        "if (liveUserAnchor && !liveUserAnchor.isConnected) "
        "_thread.appendChild(liveUserAnchor);"
    ) in body
    assert "_thread.appendChild(_streamBubble);" in body
    assert "return;" in body[body.index(live_guard) :]


def test_chat_live_stream_bubble_is_session_scoped() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "let _streamSessionKey = '';" in source
    assert "function _isCurrentSessionStreamBubble(el)" in source
    assert "streamKey === currentKey" in source
    assert (
        "_streamBubble.dataset.streamSessionKey = "
        "_streamSessionKey || _sessionKey || '';"
    ) in source
    assert "if (_isStreaming && el === _streamBubble) return;" not in source


def test_chat_session_switch_parks_and_restores_live_stream_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _switchToSession(key)")
    end = source.index("  function _bindSessionChip()", start)
    body = source[start:end]

    assert "const _liveStreamStateBySession = new Map();" in source
    assert "_parkCurrentSessionStreamState('session_switch');" in body
    assert "_restoreLiveStreamStateForSession(_sessionKey);" in body
    assert body.index("_parkCurrentSessionStreamState('session_switch');") < body.index(
        "_persistSession(key);"
    )
    assert body.index("_restoreLiveStreamStateForSession(_sessionKey);") < body.index(
        "_subscribeSession();"
    )
    assert "function _parkCurrentSessionStreamState(reason)" in source
    assert "function _restoreLiveStreamStateForSession(key)" in source
    assert "function _clearViewLocalStreamState(reason)" in source
    assert "function _currentSessionLiveRouterStrips(key = _sessionKey || '')" in source
    assert "function _currentSessionLiveUserAnchor(key = _sessionKey || '')" in source
    assert "routerStrips," in source
    assert "liveUserAnchor," in source
    assert "_routerFxPauseScanTimers(el);" in source
    assert "_routerFxResumeLiveStrip(el);" in source


def test_chat_session_switch_preserves_live_router_strip_without_stream_bubble() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    has_start = source.index("function _hasViewLocalStreamState()")
    has_end = source.index("function _parkCurrentSessionStreamState(reason)", has_start)
    has_body = source[has_start:has_end]
    assert (
        "_currentSessionLiveRouterStrips("
        "_streamSessionKey || _sessionKey || '').length"
    ) in has_body
    assert "_thinkingEl" in has_body
    assert "_thinkingDelayTimer" in has_body

    restore_start = source.index("function _restoreLiveStreamStateForSession(key)")
    restore_end = source.index("function _clearViewLocalStreamState(reason)", restore_start)
    restore_body = source[restore_start:restore_end]
    assert (
        "const routerStrips = Array.isArray(state.routerStrips) "
        "? state.routerStrips : [];"
    ) in restore_body
    assert "const liveUserAnchor = state.liveUserAnchor || null;" in restore_body
    assert "if (_thread && liveUserAnchor && !liveUserAnchor.isConnected)" in restore_body
    assert "_insertLiveRouterStripForAnchor(el, liveUserAnchor, _streamBubble);" in restore_body
    assert "_routerFxResumeLiveStrip(el);" in restore_body


def test_chat_empty_history_keeps_live_router_only_running_view() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _renderHistoryMessages(messages")
    history_end = source.index("const existingByStableIdentity = new Map();", history_start)
    history_body = source[history_start:history_end]

    assert (
        "const liveRouterStrips = "
        "_currentSessionLiveRouterStrips(_sessionKey || '');"
    ) in history_body
    assert (
        "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');"
    ) in history_body
    assert (
        "_isCurrentSessionStreamBubble(_streamBubble)"
    ) in history_body
    assert "|| liveRouterStrips.length > 0" in history_body
    assert "|| liveUserAnchor" in history_body
    assert "|| liveThinking" in history_body
    assert "_chatDiag('history.empty.keep_live_stream_view'" in history_body


def test_chat_session_switch_preserves_live_user_anchor_for_router_restore() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    helper_start = source.index("function _currentSessionLiveUserAnchor(")
    helper_end = source.index("function _insertLiveRouterStripForAnchor(", helper_start)
    helper_body = source[helper_start:helper_end]
    assert "const routerStrips = _currentSessionLiveRouterStrips(key);" in helper_body
    assert "if (_isUserMessageElement(prev)) return prev;" in helper_body
    assert "const streamAnchor = _routerFxUserMessageForAssistant(_streamBubble);" in helper_body
    assert "return _isStreaming ? _routerFxLastUserMessage() : null;" in helper_body

    park_start = source.index("function _parkCurrentSessionStreamState(reason)")
    park_end = source.index("function _restoreLiveStreamStateForSession(key)", park_start)
    park_body = source[park_start:park_end]
    assert "const liveUserAnchor = _currentSessionLiveUserAnchor(key);" in park_body
    assert "liveUserAnchor," in park_body
    assert "if (liveUserAnchor && liveUserAnchor.parentNode) liveUserAnchor.remove();" in park_body

    restore_start = source.index("function _restoreLiveStreamStateForSession(key)")
    restore_end = source.index("function _clearViewLocalStreamState(reason)", restore_start)
    restore_body = source[restore_start:restore_end]
    assert "const liveUserAnchor = state.liveUserAnchor || null;" in restore_body
    assert "_thread.appendChild(liveUserAnchor);" in restore_body
    assert "_insertLiveRouterStripForAnchor(el, liveUserAnchor, _streamBubble);" in restore_body


def test_chat_history_cleanup_keeps_live_user_anchor_during_streaming() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _renderHistoryMessages(messages")
    history_end = source.index("function _appendHistoryDaySeparator", history_start)
    history_body = source[history_start:history_end]

    assert (
        "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');"
    ) in history_body
    assert "if (_isStreaming && el === liveUserAnchor) return;" in history_body


def test_chat_router_restore_does_not_auto_settle_without_cached_decision() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    resume_start = source.index("function _routerFxResumeLiveStrip(wrap)")
    resume_end = source.index("  // When output begins", resume_start)
    resume_body = source[resume_start:resume_end]
    assert "if (wrap._fxDecision) {" in resume_body
    scan_cap = (
        "wrap._fxScanCap = setTimeout(() => _routerFxFinishScan(wrap), "
        "_ROUTER_FX_SCAN_MS);"
    )
    assert scan_cap in resume_body
    assert "_chatDiag('router_scan.resume_without_decision'" in resume_body
    assert resume_body.index("if (wrap._fxDecision) {") < resume_body.index(
        "wrap._fxScanCap = setTimeout"
    )

    settle_start = source.index("function _routerFxSettleForOutput()")
    settle_end = source.index("  // Lock an in-flight scanning strip", settle_start)
    settle_body = source[settle_start:settle_end]
    assert "if (wrap._fxDecision) {" in settle_body
    assert "_routerFxFinishScan(wrap);" in settle_body
    assert "_chatDiag('router_scan.keep_scanning_without_decision_on_output'" in settle_body


def test_chat_session_events_drop_foreign_session_before_stream_seq_acceptance() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _dropForeignSessionPayload(event, payload)" in source
    for event_name in (
        "session.event.router_decision",
        "session.event.text_delta",
        "session.event.tool_use_start",
        "session.event.tool_result",
        "session.event.state_change",
        "session.event.run_heartbeat",
    ):
        start = source.index(f"_rpc.on('{event_name}'")
        end = source.index("    }));", start)
        body = source[start:end]
        assert "_dropForeignSessionPayload(" in body
        assert body.index("_dropForeignSessionPayload(") < body.index("_acceptStreamSeq(payload)")


def test_chat_task_succeeded_clears_run_state_without_session_done() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _taskTerminalStatus(event)" in source
    assert "['succeeded', 'failed', 'timeout', 'abandoned', 'cancelled']" in source
    assert "terminalStatus === 'succeeded' ? 'idle'" in source


def test_chat_tracks_background_task_groups_as_active_run_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "let _activeTaskGroups = new Set();" in source
    assert "function _clearActiveTaskGroups()" in source
    assert "function _noteTaskGroupActive(payload)" in source
    assert "function _noteTaskGroupTerminal(payload, terminalStatus)" in source
    assert "session.event.task_group.waiting" in source
    assert "session.event.task_group.synthesizing" in source
    assert "session.event.task_group.done" in source
    assert "session.event.task_group.failed" in source
    assert "if (event.startsWith('session.event.task_group.')) return;" in source
    assert "_activeTaskGroups.size > 0" in source


def test_chat_surfaces_compaction_lifecycle_status_and_exception_toasts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    compact_block = source[
        source.index("case 'compact_context':") : source.index("case 'usage_status':")
    ]
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "_setCompactInFlight(true, compactKey);" in compact_block
    assert "_syncCompactionSeparator(" in compact_block
    assert "context compacting" in source
    assert "_compactionStatusLabel(payload || {}, source, status)" in source
    assert "Already within context budget; no compact was applied." in source
    assert "Context compaction could not be applied" in source
    assert "No compactable chat history yet." in source
    assert "Context was left unchanged because no usable summary was produced." in source
    assert "if (compactKey !== _sessionKey) return;" in compact_block
    assert (
        "_showCompactionToast({ ...(result || {}), key: compactKey, source: 'manual'"
        in compact_block
    )
    assert "session.event.compaction" in source
    assert "Context compacted older messages to keep this session within budget" not in source
    assert "Continuing with temporary context compaction" in source
    assert "Continuing with temporary context compaction for this turn" in body
    assert "Compact cancelled" in source
    assert "function _compactionUserVisible(payload, source, status)" in source
    assert "!_compactionUserVisible(payload || {}, source, status)" in source
    assert "structured content noop" not in source.lower()


def test_chat_compaction_uses_single_in_thread_separator_surface() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    # The composer pill (#chat-compact-status) is gone; the in-thread context
    # separator is the single compaction surface for every lifecycle state.
    assert 'id="chat-compact-status"' not in source
    assert "_compactStatusEl" not in source
    assert "function _setCompactStatus(" not in source
    assert "function _hideCompactStatus(" not in source

    # Lightweight separator state + renderer remain; no metrics, phase cards,
    # lifecycle chips, or rail panel are constructed.
    assert "let _compactionSeparatorEl = null;" in source
    assert "let _compactionSeparatorTimer = null;" in source
    assert "function _syncCompactionSeparator(payload, status, source, overrides = {})" in source
    assert "function _hideCompactionSeparator()" in source
    assert "chat-context-rail__panel" not in source
    assert "function _compactionLifecycleSteps(" not in source
    assert "function _compactionMetricItems(" not in source

    # Every lifecycle event renders through the one rail call; the branches below
    # only drive non-UI side effects + the corner toasts.
    assert "_syncCompactionSeparator(payload || {}, status, source);" in body
    assert "function _compactionSkipMessage(payload, source)" in source
    assert "if (_INTERNAL_COMPACTION_SKIP_REASONS.has(reason)) return '';" in source
    assert "Request-scoped; session history was not rewritten" in source
    assert "No usable summary was produced" in source
    assert "status === 'emergency_ephemeral'" in body
    assert "status === 'observed'" in body

    # destroy() tears down the separator (the only surface) — no pill teardown remains.
    assert "_hideCompactionSeparator();" in source[source.index("function destroy()") :]
    assert "_hideCompactStatus(" not in source

    # Pill/rail CSS removed; separator CSS is the only compaction thread surface.
    assert ".chat-compact-status" not in css
    assert ".chat-context-rail" not in css
    assert ".chat-context-separator" in css
    assert ".chat-context-separator::before" in css
    assert ".chat-context-separator::after" in css
    assert ".chat-context-separator--live span" in css
    assert "contextSeparatorShimmer 2.2s linear infinite" in css
    assert "@keyframes contextSeparatorShimmer" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "contextPulse" not in css


def test_chat_compaction_summary_separator_anchors_to_transcript_ids() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    sync_start = source.index(
        "function _syncCompactionSeparator(payload, status, source, overrides = {})"
    )
    sync_end = source.index("function _compactFailureBlocksPending", sync_start)
    sync_body = source[sync_start:sync_end]
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("_chatDiag('history.done'", history_start)
    history_body = source[history_start:history_end]

    assert "function _renderCompactionSummarySeparators(messages)" in source
    assert "function _clearCompactionSummarySeparators()" in source
    assert "if (inserted > 0) _hideCompactionSeparator();" in sync_body
    assert "covered_through_id" in source
    assert "transcript_id" in source
    assert "_renderCompactionSummarySeparators(messages);" in history_body
    assert "history.scroll.compaction_summary_anchor" not in history_body
    assert "_scrollHistoryAnchorIntoView(" not in history_body
    assert "_placeCompactionRail(" not in history_body
    assert "function _scheduleCompactionSeparatorRemoval(delayMs = 4500)" in source
    assert "_scheduleCompactionSeparatorRemoval();" in sync_body
    assert "status === 'skipped'" in sync_body


def test_chat_current_compaction_separator_bottom_anchors_and_autoscrolls() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    sync_start = source.index(
        "function _syncCompactionSeparator(payload, status, source, overrides = {})"
    )
    sync_end = source.index("function _clearCompactionSummarySeparators", sync_start)
    sync_body = source[sync_start:sync_end]

    assert "chat-context-separator--session" in sync_body
    assert "if (_autoScroll) _scrollToBottom();" in sync_body
    assert ".chat-context-separator--session" in css
    assert "margin-top: auto;" in css


def test_chat_compaction_separator_does_not_render_token_details() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    # The in-thread separator is intentionally terse; token/debug details stay
    # out of the chat transcript visual surface.
    assert "function _compactionTokenStats(" not in source
    assert "function _compactionMetricItems(" not in source
    assert "function _compactionLifecycleSteps(" not in source
    sync_start = source.index(
        "function _syncCompactionSeparator(payload, status, source, overrides = {})"
    )
    sync_end = source.index("function _compactFailureBlocksPending", sync_start)
    sync_body = source[sync_start:sync_end]
    assert "tokens_before" not in sync_body
    assert "tokens_after" not in sync_body
    assert "remaining_budget_tokens" not in sync_body

    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]
    skipped_start = body.index("if (status === 'skipped')")
    skipped_end = body.index("const semanticNotice", skipped_start)
    skipped_block = body[skipped_start:skipped_end]
    # Skips settle silently — no token figures, no skip-message toast spam.
    assert "_compactionTokenStats" not in skipped_block
    assert "tokens_after" not in skipped_block
    assert "UI.toast(" not in skipped_block
    assert "_scheduleCompactionSeparatorRemoval();" in skipped_block


def test_chat_semantic_memory_degraded_is_non_blocking_and_path_safe() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _compactSemanticMemoryNotice(payload)" in source
    assert "payload.semanticMemory || payload.semantic_memory" in source
    assert "Memory saved; organizing" in source
    assert "_syncCompactionSeparator(payload || {}, 'completed', source, {" in body
    assert "label: 'context compacted'," in body
    assert "UI.toast(semanticNotice" not in body
    assert body.index("const semanticNotice = _compactSemanticMemoryNotice") < body.index(
        "if (status === 'failed' || status === 'error')"
    )
    assert "function _compactSafeMessageDetail(payload)" in source
    assert "[memory checkpoint]" in source
    assert "const safe = _compactSafeMessageDetail(payload || {});" in body
    assert "payload.message ? ': ' + payload.message" not in body


def test_chat_distill_failures_do_not_surface_as_blocking_memory_errors() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]
    semantic_notice = body.index("const semanticNotice = _compactSemanticMemoryNotice")
    failure_branch = body.index("if (status === 'failed' || status === 'error')")

    assert semantic_notice < failure_branch
    assert "Memory saved; organizing" in source
    assert "flush failed" not in source.lower()
    assert "bad json" not in source.lower()


def test_chat_compact_inflight_uses_pending_queue_and_safe_terminal_drain() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    send_start = source.index("async function _onSend()")
    send_end = source.index("  /* ── Streaming", send_start)
    send_body = source[send_start:send_end]
    toast_start = source.index("function _showCompactionToast(payload, meta = {})")
    toast_end = source.index("  /* ── RPC Event Subscriptions", toast_start)
    toast_body = source[toast_start:toast_end]

    assert "let _compactInFlight = false;" in source
    assert "function _isCompactInFlightForCurrentSession()" in source
    assert "if (_isStreaming || _isCompactInFlightForCurrentSession())" in send_body
    assert "const waitReason = _isCompactInFlightForCurrentSession()" in send_body
    assert "_enqueuePendingInput(" in send_body
    assert "'Message queued until compaction finishes'" in send_body
    assert "'context compaction'" in send_body
    assert "Wait for ${waitReason} or clear." in source
    assert "_settleCompactInFlight(payload || {});" in toast_body
    assert "status === 'completed'" in source
    assert "status === 'skipped'" in source
    assert "_schedulePendingDrainAfterTerminal();" in source
    assert "status === 'failed' || status === 'error'" in toast_body
    assert "status === 'cancelled'" in toast_body
    assert "_settleCompactInFlight(payload || {}, { recoverPending: true })" in toast_body
    assert "_schedulePendingDrainAfterTerminal();" not in toast_body[
        toast_body.index("if (status === 'failed' || status === 'error')") :
        toast_body.index("if (status === 'cancelled')")
    ]
    assert "_schedulePendingDrainAfterTerminal();" not in toast_body[
        toast_body.index("if (status === 'cancelled')") :
        toast_body.index("if (status !== 'completed')")
    ]


def test_chat_large_paste_guard_runs_before_queue_and_rpc_send() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    send_start = source.index("async function _onSend()")
    send_end = source.index("  /* ── Streaming", send_start)
    send_body = source[send_start:send_end]
    normalize_start = source.index("async function _normalizeOutgoingComposerPayload(")
    normalize_end = source.index("  function _addAttachment(file)", normalize_start)
    normalize_body = source[normalize_start:normalize_end]

    assert "const LARGE_PASTE_CHARS = 20_000;" in source
    assert "const PAGE_DUMP_CHARS = 8_000;" in source
    assert "function _normalizeOutgoingComposerPayload(" in source
    assert "function _inputNormalizationProvenanceFromAttachments(" in source
    normalize_call = "await _normalizeOutgoingComposerPayload("
    assert normalize_call in send_body
    assert send_body.count(normalize_call) == 1
    assert send_body.index(normalize_call) < send_body.index(
        "if (_isStreaming || _isCompactInFlightForCurrentSession())"
    )
    assert send_body.index(normalize_call) < send_body.index("_enqueuePendingInput(")
    assert send_body.index(normalize_call) < send_body.index(
        "await _executeSlashCommand(text)"
    )
    assert send_body.index(normalize_call) < send_body.index("const params = { message:")
    provenance_call = (
        "const normalizationProvenance = "
        "_inputNormalizationProvenanceFromAttachments(attachmentsForSend);"
    )
    assert provenance_call in send_body
    assert (
        "if (normalizationProvenance) params.inputProvenance = normalizationProvenance;"
        in send_body
    )
    assert send_body.index("const params = { message:") < send_body.index(provenance_call)
    assert send_body.index(provenance_call) < send_body.index("_rpc.call('chat.send', params)")
    assert "inputNormalization: {" in normalize_body
    assert "materialEstimatedTokens," in normalize_body
    assert "guardAction: 'generated_text_attachment'," in normalize_body


def test_chat_pending_queue_can_store_normalized_attachments_explicitly() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    enqueue_start = source.index("function _enqueuePendingInput(")
    enqueue_end = source.index("  function _drainQueueHead()", enqueue_start)
    enqueue_body = source[enqueue_start:enqueue_end]

    assert "attachmentsOverride = null" in source
    assert "const queuedAttachments = attachmentsOverride || _pendingAttachments" in enqueue_body
    assert "attachments: queuedAttachments.map((a) => ({ ...a }))" in enqueue_body


def test_chat_manual_pending_enqueue_normalizes_large_pastes() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    current_start = source.index("async function _enqueueCurrentInput()")
    current_end = source.index("  function _updateStopButton()", current_start)
    current_body = source[current_start:current_end]

    normalize_idx = current_body.index(
        "const normalized = await _normalizeOutgoingComposerPayload("
    )
    enqueue_idx = current_body.index("_enqueuePendingInput(")

    assert "let text = _textarea.value.trim();" in current_body
    assert "let isLiteralSlash = false;" in current_body
    assert "if (text.startsWith('//')) {" in current_body
    assert "isLiteralSlash = true;" in current_body
    assert "text = text.slice(1);" in current_body
    assert "const isSlashCommand = !isLiteralSlash && text.startsWith('/')" in current_body
    assert "!!(await _lookupSlashCommand(text))" in current_body
    assert "{ allowSlashCommand: isSlashCommand }" in current_body
    assert normalize_idx < enqueue_idx
    assert "_pendingAttachments = normalized.attachments;" in current_body
    assert (
        "_enqueuePendingInput(text, null, 'the current response', normalized.attachments)"
        in current_body
    )


def test_chat_large_paste_attachment_base64_is_computed_once() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    normalize_start = source.index("async function _normalizeOutgoingComposerPayload(")
    normalize_end = source.index("  function _addAttachment(file)", normalize_start)
    normalize_body = source[normalize_start:normalize_end]

    assert "function _bytesToBase64(bytes)" in source
    assert "const encoded = _bytesToBase64(bytes);" in normalize_body
    assert "data: encoded," in normalize_body
    assert "dataUrl: `data:text/plain;base64,${encoded}`" in normalize_body
    assert "_encodeUtf8Base64(raw)" not in normalize_body


def test_chat_compact_blocking_failure_preserves_pending_queue() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    toast_start = source.index("function _showCompactionToast(payload, meta = {})")
    toast_end = source.index("  /* ── RPC Event Subscriptions", toast_start)
    toast_body = source[toast_start:toast_end]
    settle_start = source.index("function _settleCompactInFlight(payload = {}, options = {})")
    settle_end = source.index("  // Programmatic textarea write", settle_start)
    settle_body = source[settle_start:settle_end]

    assert "function _compactFailureBlocksPending(payload)" in source
    assert "compaction_insufficient" in source
    assert "compaction_flush_failed" in source
    assert "const preservePending = _compactFailureBlocksPending(payload || {});" in toast_body
    assert (
        "const keepPendingQueued = preservePending || (source !== 'manual' && _isStreaming);"
        in toast_body
    )
    assert "preservePending: keepPendingQueued" in toast_body
    assert "options && options.preservePending" in settle_body
    assert "_popAllPendingIntoComposer();" in settle_body
    assert "recovered = _pendingQueue.length > 0;" in settle_body


def test_chat_clears_background_task_groups_on_state_reset_paths() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    reset_idx = source.index("case '/reset':")
    epoch_idx = source.index("_rpc.on('session.epoch_changed'")
    destroy_idx = source.index("function destroy()")

    assert source.index("_clearActiveTaskGroups();", reset_idx) < source.index(
        "UI.toast('Session reset'",
        reset_idx,
    )
    assert source.index("_clearActiveTaskGroups();", epoch_idx) < source.index(
        "_currentEpoch = ep;",
        epoch_idx,
    )
    assert source.index("_clearActiveTaskGroups();", destroy_idx) > destroy_idx


def test_rpc_client_detects_frame_gaps_and_tick_timeout() -> None:
    source = RPC_JS.read_text(encoding="utf-8")

    assert "this._lastSeq = 0;" in source
    assert "_noteIncomingFrame(data)" in source
    assert "seq !== this._lastSeq + 1" in source
    assert "reason: 'tick_timeout'" in source
    assert "this._startTickWatch();" in source


def test_subagent_completion_has_distinct_chat_styles() -> None:
    source = CHAT_CSS.read_text(encoding="utf-8")

    assert ".msg.subagent" in source
    assert ".chat-subagent-disclosure" in source


def test_subagent_disclosure_renders_expand_chevron() -> None:
    source = CHAT_CSS.read_text(encoding="utf-8")

    assert ".chat-subagent-disclosure-summary::after" in source
    assert ".chat-subagent-disclosure[open] > .chat-subagent-disclosure-summary::after" in source


def test_savings_popup_suppresses_only_the_model_switch_turn() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_savingsPopupSuppressUntil" not in source
    assert "let _lastSavingsPopupIdentity = '';" in source
    assert "const cacheHit = !!(u.cache_hit_active || (u.cached_tokens || 0) > 0);" in source
    assert "const identityModel = u.routed_model || u.model || '';" in source
    assert (
        "const identity = identityModel ? `${identityModel}|${u.routed_tier || ''}` : '';"
        in source
    )
    assert "let suppressPopup = false;" in source
    assert "const identityChanged =" in source
    assert "suppressPopup = true;" in source
    assert "const _savingsPopupTsByIdentity = new Map();" in source
    assert (
        "if (!cacheHit && now - _identityLastTs < _SAVINGS_POPUP_COOLDOWN_MS) return;"
        in source
    )
    assert source.index("let suppressPopup = false;") < source.index(
        "window.SavingsFX.noteTurn(u);"
    )


def test_savings_popup_persists_cache_hit_active_to_turn_meta() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "cache_hit_active: !!u.cache_hit_active," in source
    assert "model: u.model || _usageModel || null," in source
    assert "routed_model: u.routed_model || null," in source
    assert "__savings_ui_suppressed: !!u.__savings_ui_suppressed," in source


def test_savings_fx_cleanup_removes_floating_labels() -> None:
    source = SAVINGS_FX_JS.read_text(encoding="utf-8")

    assert "const _labels = new Set();" in source
    assert "_labels.add(el);" in source
    assert "_labels.delete(el);" in source
    assert "for (const el of _labels)" in source
    assert "window.SavingsFX.cleanup();" in CHAT_JS.read_text(encoding="utf-8")


def test_turn_meta_and_router_share_model_display_normalization() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    attach_start = source.index("function _attachTurnMeta(")
    attach_end = source.index("    if (hasTokens)", attach_start)
    attach_body = source[attach_start:attach_end]
    router_strip_start = source.index("function _routerFxStripProvider(name)")
    router_strip_end = source.index("  // Promise resolved", router_strip_start)
    router_strip_body = source[router_strip_start:router_strip_end]

    assert "function _modelDisplayName(name)" in source
    assert r"return stripped.replace(/-\d{8}$/, '');" in source
    assert "const displayModel = _modelDisplayName(model);" in attach_body
    assert "span.textContent = displayModel;" in attach_body
    assert "return _modelDisplayName(name);" in router_strip_body


def test_router_fx_header_names_ai_model_router() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert '<span class="title">AI model router</span>' in source
    assert '<span class="title">model router</span>' not in source


def test_router_fx_replay_without_live_strip_renders_settled_history() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    handler_start = source.index("async function _handleRouterDecision(payload) {")
    handler_end = source.index("  // History-load entry point", handler_start)
    handler_body = source[handler_start:handler_end]
    subscription_start = source.index("function _subscribeRpcEvents() {")
    subscription_end = source.index(
        "    // Text delta: accumulate into streaming bubble", subscription_start
    )
    subscription_body = source[subscription_start:subscription_end]

    assert "function _routerFxShouldAnimateIdentity" not in source
    assert "shouldAnimate" not in handler_body
    assert "_rpc.on('session.event.router_decision'" in subscription_body
    assert "_handleRouterDecision(payload);" in subscription_body
    assert (
        "const liveStrip = _thread.querySelector('.router-fx[data-live=\"true\"]');"
        in handler_body
    )
    assert "liveStrip._fxDecision = payload;" in handler_body
    assert "_routerFxLock(liveStrip, payload);" in handler_body
    assert "preSettled: true," in handler_body
    assert "renderMode: 'history'," in handler_body
    assert "_routerFxNormalizeSettledStrip(wrap, 'history', payload);" in handler_body
    assert "_animateRouterFx(wrap, winnerIdx)" not in handler_body
    assert "_animateRouterFxCloud(wrap)" not in handler_body
    assert "router_decision.inserted_settled_strip" in handler_body


def test_chat_diag_captures_stream_router_and_history_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _CHAT_DIAG_KEY = 'opensquilla.chat.debugLog';" in source
    assert "window.OpenSquillaChatDiag" in source
    assert "function _chatDiagDomSnapshot() {" in source
    for marker in [
        "send.start",
        "event.router_decision",
        "event.text_delta",
        "router_scan.started",
        "router_decision.cached_on_live_strip",
        "stream.bubble.created",
        "stream.flush.done",
        "stream.end.start",
        "history.loaded",
        "history.done",
    ]:
        assert marker in source


def test_chat_diag_is_opt_in_by_default() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _chatDiagEnabled() {")
    end = source.index("function _chatDiagShortText", start)
    body = source[start:end]

    assert "window.localStorage.getItem(_CHAT_DIAG_ENABLED_KEY) === '1';" in body
    assert "window.localStorage.getItem(_CHAT_DIAG_ENABLED_KEY) !== '0';" not in body
    assert "return false;" in body
    assert "window.localStorage.setItem(_CHAT_DIAG_ENABLED_KEY, '1');" in source


def test_chat_history_requests_active_paginated_metadata() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("async function _loadEarlierHistory()", history_start)
    history_body = source[history_start:history_end]
    earlier_start = source.index("async function _loadEarlierHistory() {")
    earlier_end = source.index("function _renderHistoryMessages(", earlier_start)
    earlier_body = source[earlier_start:earlier_end]

    assert "const CHAT_HISTORY_PAGE_SIZE = 50;" in source
    assert "const requestSessionKey = _sessionKey;" in history_body
    assert "const requestSeq = ++_historyRequestSeq;" in history_body
    assert "sessionKey: requestSessionKey" in history_body
    assert "limit: CHAT_HISTORY_PAGE_SIZE" in history_body
    assert "includeCanonical: false" in history_body
    assert "includeCanonical: false" in earlier_body
    assert "includeCanonical: true" not in history_body
    assert "includeCanonical: true" not in earlier_body
    assert "includeSummaries: true" in history_body
    assert "requestSessionKey !== _sessionKey || requestSeq !== _historyRequestSeq" in history_body
    assert "_chatDiag('history.stale_response.drop'" in history_body


def test_chat_history_load_earlier_uses_cursor_and_preserves_scroll() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadEarlierHistory() {")
    end = source.index("function _renderHistoryMessages(", start)
    body = source[start:end]

    assert "!_historyOldestCursor || _historyLoadingEarlier" in body
    assert "const previousScrollHeight = _thread.scrollHeight;" in body
    assert "const previousScrollTop = _thread.scrollTop;" in body
    assert "before: _historyOldestCursor" in body
    assert "_mergeHistoryMessagePages(olderMessages, _historyLoadedMessages)" in body
    assert "preserveScroll: true" in body
    assert "_chatDiag('history.load_earlier.stale_response.drop'" in body


def test_chat_history_scope_row_surfaces_partial_compacted_and_error_states() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = source.index("function _renderHistoryScopeRow() {")
    end = source.index("async function _loadHistory(opts = {})", start)
    body = source[start:end]

    assert "chat-history-scope" in body
    assert "Showing latest ${_historyLoadedMessages.length} messages." in body
    assert "Older history is available." in body
    assert "Older context was compacted for the model." in body
    assert "Export the session for exact text." in body
    assert "Load earlier" in body
    assert "Retry history" in body
    assert "btn.addEventListener('click', () => _loadEarlierHistory());" in body
    assert ".chat-history-scope--partial" in css
    assert ".chat-history-scope--compacted" in css
    assert ".chat-history-scope--error" in css


def test_chat_history_render_preserves_visible_messages_on_errors() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    initial_start = source.index("async function _loadHistory(opts = {}) {")
    initial_end = source.index("async function _loadEarlierHistory()", initial_start)
    initial_body = source[initial_start:initial_end]
    earlier_start = source.index("async function _loadEarlierHistory() {")
    earlier_end = source.index("function _renderHistoryMessages(", earlier_start)
    earlier_body = source[earlier_start:earlier_end]

    assert "_historyError = 'Could not load chat history.'" in initial_body
    assert "_renderHistoryScopeRow();" in initial_body
    assert "_thread.innerHTML = ''" not in initial_body
    assert "_historyError = 'Could not load earlier history.'" in earlier_body
    assert "_renderHistoryScopeRow();" in earlier_body
    assert "_thread.innerHTML = ''" not in earlier_body


def test_chat_history_scope_row_is_not_a_message_node() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _renderHistoryScopeRow() {")
    end = source.index("async function _loadHistory(opts = {})", start)
    body = source[start:end]

    assert "row.className = `chat-history-scope chat-history-scope--${tone}`;" in body
    assert "row.className = `msg" not in body
    assert "_thread.querySelectorAll('.chat-history-scope').forEach((el) => el.remove());" in source


def test_router_fx_history_reuses_settled_strip_for_same_turn_identity() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]

    assert "function _routerFxUserMessageForAssistant(referenceAssistant) {" in source
    assert "const userMsg = _routerFxUserMessageForAssistant(div);" in history_body
    assert "const userMsg = _routerFxLastUserMessage();" not in history_body
    assert "el.dataset.sessionKey === (_sessionKey || '') && el.dataset.turnIndex" in source
    assert "const routerIdentity = _routerFxUsageIdentity(savedUsage);" in source
    assert "existingStrip.dataset.routerIdentity === routerIdentity" in source
    assert "if (existingStrip) _routerFxRemoveStrip(existingStrip);" in source
    assert "existingStrip.dataset.live" not in history_body
    assert "routerStrip.dataset.turnIndex = String(_histUserIdx);" in source


def test_router_fx_history_reanchors_stranded_strip() -> None:
    # _appendHistoryElementInOrder re-appends only .msg elements, stranding any
    # strip already rendered for a turn. The rebuild must match this turn's
    # strip(s) by (session, turn index) and router identity — NOT by the live
    # flag — keep the one whose identity matches, drop extras, and re-anchor the
    # survivor beneath its user message, so the first chat never shows two grids.
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]

    # Match by (session, turnIndex), independent of the data-live flag.
    assert (
        "const ownStrips = Array.from(_thread.querySelectorAll('.router-fx')).filter("
        in history_body
    )
    assert "el.dataset.turnIndex === String(_histUserIdx)" in history_body
    assert "el.dataset.routerIdentity === routerIdentity" in history_body
    # Drop duplicates, re-anchor the survivor, normalize it into history state.
    assert (
        "ownStrips.forEach((el) => { if (el !== keep) _routerFxRemoveStrip(el); });"
        in history_body
    )
    assert "_thread.insertBefore(keep, userMsg.nextSibling);" in history_body
    assert "_routerFxNormalizeSettledStrip(keep, 'history', savedUsage);" in history_body
    # The consolidation must precede the existingStrip probe so the relocated
    # strip is what the reuse check sees.
    assert history_body.index("const ownStrips =") < history_body.index(
        "const placed = userMsg && userMsg.nextSibling;"
    )
    # Positional orphan backstop: outside an active stream, any strip not
    # sitting directly beneath a user message (turn-index skew) is dropped so
    # a stranded grid can never linger at the top.
    assert "if (!_isStreaming) {" in history_body
    assert "const prev = el.previousElementSibling;" in history_body
    assert "if (!anchored) _routerFxRemoveStrip(el);" in history_body


def test_router_fx_uses_only_effective_real_candidates() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    builder_start = source.index("function _routerFxBuildGridCells(realEntries, seedKey) {")
    builder_end = source.index("  function _buildRouterFxElement", builder_start)
    builder_body = source[builder_start:builder_end]

    assert "const _ROUTER_FX_DECOY_POOL" not in source
    assert "_ROUTER_FX_REAL_ANCHOR_CELLS" not in source
    assert "_ROUTER_FX_GRID_CELLS" not in source
    assert "function _routerFxResolveLayoutSeed(sessionKey, hintTimestamp)" in source
    assert "function _routerFxVisualEntries(requestKind, decision) {" in source
    assert "const cachedSeed = _routerFxResolveLayoutSeed(_sessionKey, hint);" in source
    assert "const orderedRealEntries = realEntries.slice().sort" in builder_body
    assert "return orderedRealEntries.map((entry) => ({" in builder_body
    assert "kind: 'real'," in builder_body
    assert "kind: 'decoy'" not in builder_body
    assert "return _routerFxShuffle(cells, seedKey);" not in builder_body


def test_router_fx_cells_render_plain_model_names_only() -> None:
    # The panel intentionally shows the real candidates for this request. Cells
    # show only the user-facing model name: no S/M/L/XL, no provider labels, no
    # thinking badges, and no DOM roster metadata beyond the cell index needed
    # for the selector.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert "cell.dataset.kind" not in source
    assert "cell.dataset.tiers" not in source
    assert '[data-kind="real"]' not in css
    assert '[data-kind="decoy"]' not in css
    assert "router-fx-dot-idle" not in css
    cell_start = css.index(".router-fx-cell {")
    cell_end = css.index("}", cell_start)
    assert "color: var(--text);" in css[cell_start:cell_end]
    assert ".router-fx-cell.win {" in css
    win_after = css.index(".router-fx-cell.win::after {")
    win_after_end = css.index("}", win_after)
    assert "content: '';" in css[win_after:win_after_end]
    assert "const cells = wrap._fxGridCells || [];" in source
    assert "cells[i].kind === 'real'" in source
    assert "cell.dataset.cellIdx = String(i);" in source
    assert "cell.dataset.provider" not in source
    assert "cell.dataset.thinking" not in source
    for size_label in (">S<", ">M<", ">L<", ">XL<"):
        assert size_label not in source


def test_router_fx_config_caches_text_and_image_capability_flags() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    load_start = source.index("async function _loadFeatureToggles() {")
    load_end = source.index("  /* ── Session Chip", load_start)
    body = source[load_start:load_end]

    assert "const _routerFxTierConfigs = {};" in source
    assert "model: typeof rawTier?.model === 'string' ? rawTier.model : ''," in body
    assert "supportsImage: rawTier?.supports_image === true," in body
    assert "imageOnly: rawTier?.image_only === true," in body
    assert "_routerFxTierConfigs[lower] = tierConfig;" in body
    assert "delete _routerFxTierConfigs[tier];" in body


def test_router_fx_filters_text_and_image_candidates_by_request_kind() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _routerFxRequestKindFromAttachments(attachments) {" in source
    request_start = source.index("function _routerFxRequestKindFromAttachments(attachments) {")
    request_end = source.index("function _routerFxTierMatchesRequestKind", request_start)
    request_body = source[request_start:request_end]
    assert "return 'image';" in request_body
    assert "return 'text';" in request_body

    match_start = source.index("function _routerFxTierMatchesRequestKind")
    match_end = source.index("function _routerFxVisualEntries", match_start)
    match_body = source[match_start:match_end]
    assert "return !!(tierConfig.supportsImage || tierConfig.imageOnly);" in match_body
    assert "return !tierConfig.imageOnly;" in match_body

    send_start = source.index("async function _onSend()")
    send_end = source.index("    // Send", send_start)
    send_body = source[send_start:send_end]
    assert (
        "const routerFxRequestKind = "
        "_routerFxRequestKindFromAttachments(params.attachments || []);"
    ) in send_body
    assert "requestKind: routerFxRequestKind" in send_body


def test_router_fx_single_visual_candidate_renders_nothing_live_or_history() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    builder_start = source.index("function _buildRouterFxElement(decision, opts) {")
    builder_end = source.index("  function _routerFxWinnerCellIndex", builder_start)
    builder_body = source[builder_start:builder_end]
    assert "if (realEntries.length <= 1) return null;" in builder_body

    schedule_start = source.index("function _scheduleRouterFxBeginScan(anchorDiv, seedKey, opts) {")
    schedule_end = source.index("  // Render the routing visualisation", schedule_start)
    schedule_body = source[schedule_start:schedule_end]
    assert (
        "if (_routerFxConfigTiers !== null "
        "&& !_routerFxHasMultipleCandidates(requestKind, null)) {"
        in schedule_body
    )
    assert "_chatDiag('router_scan.schedule.skip.single_candidate'" in schedule_body

    pending_start = source.index("async function _finishPendingRouterFxScan() {")
    pending_end = source.index(
        "function _scheduleRouterFxBeginScan(anchorDiv, seedKey, opts) {",
        pending_start,
    )
    pending_body = source[pending_start:pending_end]
    assert pending_body.index("await _routerFxAwaitConfig();") < pending_body.index(
        "_routerFxBeginScan(pending.anchorDiv, pending.seedKey"
    )

    begin_start = source.index("function _routerFxBeginScan(anchorDiv, seedKey, opts) {")
    begin_end = source.index("function _routerFxScanRoam(", begin_start)
    begin_body = source[begin_start:begin_end]
    assert "if (!wrap) {" in begin_body
    assert "_chatDiag('router_scan.skip.single_candidate'" in begin_body

    history_start = source.index("function _buildRouterFxFromUsage(usage, seedKey, opts) {")
    history_end = source.index("  /* ── RPC Event Subscriptions", history_start)
    history_body = source[history_start:history_end]
    assert "requestKind: requestKind" in history_body
    assert "return _buildRouterFxElement(decision, {" in history_body


def test_router_fx_grid_labels_shrink_to_fit() -> None:
    # Long model names (e.g. "gemini-3.1-flash-lite") must show in full, not
    # clip at the cell edges: a post-insert measure shrinks the label font to
    # fit its cell. Runs for every inserted strip via _routerFxInsertAnchored.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _routerFxFitLabels(wrap) {" in source
    measure_start = source.index("function _routerFxMeasureLabels(wrap) {")
    measure_end = source.index("function _routerFxScheduleLabelFit(", measure_start)
    measure = source[measure_start:measure_end]
    assert "wrap.querySelectorAll('.router-fx-cell')" in measure
    assert "const w = nm.scrollWidth;" in measure
    assert "nm.style.fontSize = Math.max(7, base * (avail / w)).toFixed(1) + 'px';" in measure
    fit_start = source.index("function _routerFxInstallLabelFit(wrap) {")
    fit_end = source.index("function _routerFxInsertAnchored(", fit_start)
    fit = source[fit_start:fit_end]
    assert "new ResizeObserver(() => _routerFxScheduleLabelFit(wrap))" in fit
    assert "document.fonts.ready" in fit
    assert "_routerFxScheduleLabelFit(wrap);" in fit
    # Invoked from the shared insert path so both live and history strips fit.
    insert_start = source.index("function _routerFxInsertAnchored(")
    insert_end = source.index("}", source.index("_thread.appendChild(wrap);", insert_start))
    assert "_routerFxFitLabels(wrap);" in source[insert_start:insert_end]


def test_router_fx_scan_does_not_hide_waiting_indicator() -> None:
    # The "squilla · Watching · N.Ns" indicator must remain visible even while
    # the router panel is scanning. Provider first-byte waits can be minutes
    # long, so router animation must not suppress the only user-facing progress
    # signal.
    source = CHAT_JS.read_text(encoding="utf-8")
    # No longer suppressed.
    assert "if (_routerFx.enabled && _routerFeatureEnabled) return;" not in source
    now_start = source.index("function _showThinkingIndicatorNow() {")
    now_end = source.index("function _hideThinkingIndicator", now_start)
    body = source[now_start:now_end]
    assert "_thread.querySelector('.router-fx[data-scanning=\"true\"]')" not in body
    assert "thinking.defer.router_scan" not in body
    # The verb list (incl. "Watching") is unchanged.
    assert "const SQUILLA_VERBS = ['Watching'," in source


def test_router_fx_scan_to_lock_fills_the_wait() -> None:
    # The routing visualisation starts shortly after SEND and animates
    # continuously (JS-driven, ~170ms class/position swaps) until the decision
    # locks it onto the winner. The small delay lets request-time compaction
    # suppress the panel before a competing router flash appears.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    for fn in ("_routerFxBeginScan", "_routerFxScanRoam", "_routerFxStopScan",
               "_routerFxLock", "_routerFxLockGrid"):
        assert f"function {fn}(" in source
    # Scan is gated on BOTH the viz pref and routing actually being on.
    begin_start = source.index("function _routerFxBeginScan(")
    begin_end = source.index("function _routerFxScanRoam(", begin_start)
    begin = source[begin_start:begin_end]
    assert "if (!_thread || !_routerFx.enabled || !_routerFeatureEnabled) {" in begin
    assert "_chatDiag('router_scan.skip'" in begin
    assert "return false;" in begin
    assert "_routerFxHasMultipleCandidates(requestKind, null)" in begin
    # Scheduled from the send path.
    assert (
        "const routerScanStarted = _scheduleRouterFxBeginScan("
        "userDiv, _routerFxResolveLayoutSeed(_sessionKey), {"
    ) in source
    # The scan runs for a FIXED, hard-capped window (≤1s), then locks — not
    # "roam until the decision WS event lands".
    assert "const _ROUTER_FX_SCAN_MS = 600;" in source
    cap = "wrap._fxScanCap = setTimeout(() => _routerFxFinishScan(wrap), _ROUTER_FX_SCAN_MS);"
    assert cap in source
    assert "function _routerFxFinishScan(wrap) {" in source
    # The decision is CACHED on the in-flight strip; the cap (or output) locks it.
    assert "liveStrip._fxDecision = payload;" in source
    assert "if (liveStrip._fxFinished) {" in source
    assert "_routerFxLock(wrap, wrap._fxDecision);" in source  # finish locks the cached winner
    # Roam is JS-driven discrete selector hops across the real candidate cells.
    roam_start = source.index("function _routerFxScanRoam(")
    roam_end = source.index("function _routerFxStopScan(", roam_start)
    roam = source[roam_start:roam_end]
    assert "const grid = wrap.querySelector('.router-fx-grid');" in roam
    assert "const targets = grid.querySelectorAll('.router-fx-cell');" in roam
    assert "wrap._fxScanTimer = setTimeout(step, 190);" in roam
    assert ".router-fx-mote" not in css


def test_chat_compaction_suppresses_current_turn_router_wait_panel() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "let _compactSuppressedRouterTurnIndex = '';" in source
    assert "function _suppressRouterFxForCompaction(payload = {})" in source
    assert "const _ROUTER_FX_START_DELAY_MS = 280;" in source
    assert "function _scheduleRouterFxBeginScan(anchorDiv, seedKey, opts)" in source
    assert "function _cancelPendingRouterFxScan(reason = '')" in source

    toast_start = source.index("function _showCompactionToast(payload, meta = {})")
    started_start = source.index("if (status === 'started') {", toast_start)
    started_end = source.index("if (status === 'observed') {", started_start)
    started_body = source[started_start:started_end]
    assert "_suppressRouterFxForCompaction(payload || {});" in started_body

    observed_start = source.index("if (status === 'observed') {", toast_start)
    observed_end = source.index("if (status === 'emergency_ephemeral') {", observed_start)
    observed_body = source[observed_start:observed_end]
    assert "_suppressRouterFxForCompaction(payload || {});" in observed_body

    suppress_start = source.index("function _suppressRouterFxForCompaction(payload = {})")
    suppress_end = source.index("function _showCompactionToast(payload, meta = {})", suppress_start)
    suppress_body = source[suppress_start:suppress_end]
    assert "_cancelPendingRouterFxScan('compaction');" in suppress_body

    send_start = source.index("async function _onSend()")
    send_end = source.index("    // Send", send_start)
    send_body = source[send_start:send_end]
    assert (
        "_scheduleRouterFxBeginScan(userDiv, _routerFxResolveLayoutSeed(_sessionKey), {"
        in send_body
    )
    assert "_routerFxBeginScan(userDiv, _routerFxResolveLayoutSeed(_sessionKey))" not in send_body

    begin_start = source.index("function _routerFxBeginScan(")
    begin_end = source.index("function _routerFxScanRoam(", begin_start)
    begin_body = source[begin_start:begin_end]
    assert "_routerFxIsSuppressedForCompactionTurn(_routerFxCountUserMessages())" in begin_body

    handler_start = source.index("async function _handleRouterDecision(payload) {")
    handler_end = source.index("  // History-load entry point", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "_routerFxIsSuppressedForCompactionTurn(turnIndex)" in handler_body
    assert "router_decision.skip.compaction_suppressed" in handler_body


def test_chat_compaction_suppresses_current_turn_thinking_indicator() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    show_start = source.index("function _showThinkingIndicatorNow() {")
    show_end = source.index("function _hideThinkingIndicator", show_start)
    show_body = source[show_start:show_end]
    assert "thinking.defer.compaction_in_flight" in show_body
    assert "_isCompactInFlightForCurrentSession()" in show_body

    toast_start = source.index("function _showCompactionToast(payload, meta = {})")
    started_start = source.index("if (status === 'started') {", toast_start)
    started_end = source.index("if (status === 'observed') {", started_start)
    started_body = source[started_start:started_end]
    assert "_hideThinkingIndicator();" in started_body

    observed_start = source.index("if (status === 'observed') {", toast_start)
    observed_end = source.index("if (status === 'emergency_ephemeral') {", observed_start)
    observed_body = source[observed_start:observed_end]
    assert "_hideThinkingIndicator();" in observed_body

    settle_start = source.index("function _settleCompactInFlight(payload = {}, options = {})")
    settle_end = source.index("  // Programmatic textarea write", settle_start)
    settle_body = source[settle_start:settle_end]
    assert "if (_isStreaming && !_streamBubble) _showThinkingIndicator();" in settle_body


def test_chat_history_refresh_preserves_active_thinking_indicator() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _isCurrentSessionThinkingIndicator(el)" in source
    assert "_thinkingEl.dataset.sessionKey = _streamSessionKey || _sessionKey || '';" in source

    render_start = source.index("function _renderHistoryMessages(messages, opts = {})")
    render_end = source.index("function _appendHistoryDaySeparator", render_start)
    render_body = source[render_start:render_end]
    assert (
        "const liveThinking = _isCurrentSessionThinkingIndicator(_thinkingEl) "
        "? _thinkingEl : null;"
    ) in render_body
    assert (
        "if (el !== _streamBubble && el !== liveUserAnchor && el !== liveThinking) "
        "el.remove();"
    ) in render_body
    assert (
        "if (liveThinking && !liveThinking.isConnected) "
        "_thread.appendChild(liveThinking);"
    ) in render_body
    assert "if (_isStreaming && _isCurrentSessionThinkingIndicator(el)) return;" in render_body


def test_chat_history_reorders_before_live_thinking_indicator() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _historyLiveTailAnchor()" in source
    helper_start = source.index("function _historyLiveTailAnchor()")
    helper_end = source.index("function _appendHistoryDaySeparator", helper_start)
    helper_body = source[helper_start:helper_end]
    assert "if (!_isStreaming) return null;" in helper_body
    assert "if (_isCurrentSessionStreamBubble(_streamBubble)) return _streamBubble;" in helper_body
    assert "if (_isCurrentSessionThinkingIndicator(_thinkingEl)) return _thinkingEl;" in helper_body

    day_start = source.index("function _appendHistoryDaySeparator(timestamp)")
    day_end = source.index("function _appendHistoryElementInOrder(div)", day_start)
    day_body = source[day_start:day_end]
    assert "const liveTail = _historyLiveTailAnchor();" in day_body
    assert "_thread.insertBefore(sep, liveTail);" in day_body

    append_start = source.index("function _appendHistoryElementInOrder(div)")
    append_end = source.index("function _historyStableMessageIdentity", append_start)
    append_body = source[append_start:append_end]
    assert "const liveTail = _historyLiveTailAnchor();" in append_body
    assert "if (liveTail && div !== liveTail)" in append_body
    assert "_thread.insertBefore(div, liveTail);" in append_body


def test_router_fx_strip_survives_multistep_turn() -> None:
    # History reorder moves .msg nodes. The router strip is a sibling, so the
    # root fix is to move an attached strip together with its user message
    # instead of preserving a separate live-strip path inside _loadHistory().
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "delete settledStrip.dataset.live;" not in source
    assert "_routerFxFindAttachedStrip" not in source
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]
    assert "ownStrips.find((el) => el.dataset.live === 'true')" not in history_body
    assert "if (_isStreaming && el.dataset.live === 'true') return;" not in history_body
    assert "if (el.dataset.live === 'true') return;" not in history_body
    # The reorder path moves a user message's attached router strip with that
    # user message, so a long multi-step turn can't swap their positions.
    append_start = source.index("function _appendHistoryElementInOrder(div)")
    append_end = source.index("function _historyStableMessageIdentity", append_start)
    append_body = source[append_start:append_end]
    assert "const attachedRouterStrip = _routerFxStripImmediatelyAfterUser(div);" in append_body
    assert "_restoreRouterFxAfterHistoryUser(div, attachedRouterStrip);" in append_body
    assert "_thread.insertBefore(routerStrip, div.nextSibling);" in append_body
    assert (
        "const keep = ownStrips.find((el) => "
        "el.dataset.routerIdentity === routerIdentity)"
    ) in history_body
    assert "_routerFxNormalizeSettledStrip(keep, 'history', savedUsage);" in history_body


def test_router_decision_without_anchor_is_cached_for_history_replay() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "const _pendingRouterDecisions = new Map();" in source
    assert "let _historyHydrating = false;" in source
    assert "let _historyHasRendered = false;" in source
    assert "function _cachePendingRouterDecision(payload)" in source
    assert "function _flushPendingRouterDecisions()" in source

    handler_start = source.index("async function _handleRouterDecision(payload)")
    handler_end = source.index("    // No matching live scan means this decision", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "if (!_historyHasRendered || _historyHydrating) {" in handler_body
    assert "_chatDiag('router_decision.cached_during_history_hydration'" in handler_body
    assert "_cachePendingRouterDecision(payload);" in handler_body
    assert "_chatDiag('router_decision.cached_pending_anchor'" in source
    assert "_chatDiag('router_decision.skip.no_anchor_user'" not in handler_body

    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("function _appendHistoryDaySeparator", history_start)
    history_body = source[history_start:history_end]
    assert "_historyHydrating = true;" in history_body
    assert "_historyHydrating = false;" in history_body
    assert "_historyHasRendered = true;" in history_body
    assert history_body.index("_historyHasRendered = true;") < history_body.index(
        "_flushPendingRouterDecisions();"
    )
    assert "_flushPendingRouterDecisions();" in history_body


def test_router_fx_settled_cleanup_clears_live_animation_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _routerFxNormalizeSettledStrip(wrap, renderMode, decision) {" in source
    start = source.index("function _routerFxNormalizeSettledStrip(wrap, renderMode, decision) {")
    end = source.index("function _routerFxDisconnectLabelFit(wrap) {", start)
    body = source[start:end]

    assert "_routerFxStopScan(wrap);" in body
    assert "_routerFxClearAnimationTimers(wrap);" in body
    assert "_routerFxClearVisualResidue(wrap);" in body
    assert "wrap.dataset.state = 'settled';" in body
    assert "delete wrap.dataset.live;" in body
    assert "delete wrap.dataset.scanning;" in body
    assert "_routerFxApplySettledSemantics(wrap, decision, wrap.dataset.renderMode);" in body
    assert "_routerFxFitLabels(wrap);" in body

    clear_start = source.index("function _routerFxClearVisualResidue(wrap) {")
    clear_end = source.index("function _routerFxNormalizeSettledStrip", clear_start)
    clear = source[clear_start:clear_end]
    assert "selector.classList.remove('visible', 'lock', 'lock-impact')" in clear
    assert ".router-fx-cell.pinging" in clear
    assert ".router-fx-burst" in clear

    settle_start = source.index("function _settleRouterFxImmediate(wrap, winnerIdx, opts) {")
    settle_end = source.index("function _routerFxFireBurst(grid, cell) {", settle_start)
    settle = source[settle_start:settle_end]
    assert "delete wrap.dataset.live;" in settle
    assert "delete wrap.dataset.scanning;" in settle


def test_router_fx_config_refresh_prunes_stale_model_cache() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadFeatureToggles() {")
    end = source.index("  /* ── Session Chip", start)
    body = source[start:end]

    assert "Object.keys(_routerFxModels).forEach((tier) => {" in body
    assert "if (!configTierSet.has(tier)) delete _routerFxModels[tier];" in body
    assert "if (!configTierSet.has(tier)) delete _routerFxTierConfigs[tier];" in body
    assert "_routerFxConfigTiers = configTierSet;" in body


def test_router_fx_settled_semantics_expose_render_mode_and_result() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert (
        "wrap.dataset.renderMode = opts.renderMode || (opts.preSettled ? 'history' : 'live');"
        in source
    )
    start = source.index("function _routerFxApplySettledSemantics(wrap, decision, renderMode) {")
    end = source.index("function _routerFxClearVisualResidue(wrap) {", start)
    body = source[start:end]

    assert "wrap.dataset.renderMode = mode;" in body
    assert "wrap.setAttribute('role', mode === 'live' ? 'status' : 'group');" in body
    assert "wrap.setAttribute('aria-live', mode === 'live' ? 'polite' : 'off');" in body
    assert "winnerName ? `Router selected ${winnerName}` : 'Router settled'" in body


def test_done_stream_bubble_survives_until_history_persists_assistant() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "let _pendingFinalizedAssistantBubble = null;" in source
    assert "function _markPendingFinalizedAssistantBubble(bubble, text)" in source
    assert "function _isPendingFinalizedAssistantBubble(el)" in source
    assert "function _historyStillWaitingForAssistant(messages)" in source

    end_start = source.index("function _endStreaming(opts)")
    end_end = source.index("_attachHoverActions(_streamBubble, 'assistant');", end_start)
    end_body = source[end_start:end_end]
    assert "_markPendingFinalizedAssistantBubble(_streamBubble, cleanedText);" in end_body
    stamp_marker = "_stampHistoryElement(_streamBubble, '', 'assistant', cleanedText);"
    mark_marker = "_markPendingFinalizedAssistantBubble(_streamBubble, cleanedText);"
    assert end_body.index(stamp_marker) < end_body.index(mark_marker)

    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("function _appendHistoryDaySeparator", history_start)
    history_body = source[history_start:history_end]
    assert "_chatDiag('history.empty.keep_pending_finalized_assistant'" in history_body
    assert (
        "if (_isPendingFinalizedAssistantBubble(el) && "
        "_historyStillWaitingForAssistant(messages)) return;"
    ) in history_body
    assert "_clearPendingFinalizedAssistantBubble();" in history_body


def test_generic_duplicate_stream_seq_is_classified_as_exact_handler_replay() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _eventHasSpecificSessionHandler(event)" in source
    wildcard_start = source.index("_unsubs.push(_rpc.on('*', (rawEvent, rawPayload")
    wildcard_end = source.index(
        "      if (event.startsWith('session.event.task_group.')) return;",
        wildcard_start,
    )
    wildcard_body = source[wildcard_start:wildcard_end]
    assert "_eventHasSpecificSessionHandler(event)" in wildcard_body
    assert "_chatDiag('event.generic.skip.specific_handler_stream_seq'" in wildcard_body
    assert "_chatDiag('event.generic.drop.stream_seq'" in wildcard_body


def test_savings_popup_does_not_fire_for_replayed_done_frames() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    wildcard_start = source.index("_unsubs.push(_rpc.on('*'")
    wildcard_end = source.index("    // Connection state changes", wildcard_start)
    body = source[wildcard_start:wildcard_end]

    assert "(rawEvent, rawPayload, rawMeta = {})" in body
    assert "const isReplayedFrame = !!(rawMeta && rawMeta.replayed);" in body
    assert "_maybeFireSavingsPopup(_finishedBubble, u, { animate: !isReplayedFrame });" in body
    assert body.index("isReplayedFrame") < body.index("_maybeFireSavingsPopup(")


def test_tool_summary_exposes_visible_running_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _setToolSummaryStatus(details, status)" in source
    assert "function _visibleToolSummaryStatus(status)" in source
    assert "return status === 'running' ? 'running' : '';" in source
    build_start = source.index("function _buildToolCallDOM(")
    build_end = source.index("function _retitleToolCallDOM", build_start)
    build_body = source[build_start:build_end]
    assert "statusSpan.className = 'chat-tools-status';" in build_body
    assert "_applyToolSummaryStatus(statusSpan, isRunning ? 'running' : '');" in build_body
    result_start = source.index("function _appendToolResult(payload)")
    result_end = source.index(
        "  // \u2500\u2500 PR5: meta-skill user_input form rendering",
        result_start,
    )
    result_body = source[result_start:result_end]
    assert "_setToolSummaryStatus(details, isError ? 'error' : 'done');" in result_body
    assert "statusSpan.hidden = !visibleStatus;" in source


def test_live_clarify_form_closes_matching_tool_card_before_return() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    result_start = source.index("function _appendToolResult(payload)")
    clarify_start = source.index("if (\n      _args", result_start)
    clarify_end = source.index("    // Skipped user_input step", clarify_start)
    clarify_body = source[clarify_start:clarify_end]

    assert "_settleToolResultCard(payload, false);" in clarify_body
    assert clarify_body.index("_settleToolResultCard(payload, false);") < clarify_body.index(
        "_appendClarifyForm(payload, _args);"
    )


def test_historical_clarify_tool_results_reconstruct_form_not_raw_card() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _reconstructToolCalls(bubbleDiv, segments)")
    history_end = source.index("  function _renderMessageTags", history_start)
    history_body = source[history_start:history_end]

    assert "const clarifyArgs = _clarifyArgsFromHistoricalSegment(seg, details);" in history_body
    assert "_appendClarifyFormToBody(body, seg, clarifyArgs);" in history_body
    clarify_form_index = history_body.index(
        "_appendClarifyFormToBody(body, seg, clarifyArgs);"
    )
    raw_result_index = history_body.index("const resultDiv = _buildToolResultDOM(")
    assert clarify_form_index < raw_result_index


def test_clarify_form_renders_progress_summary_and_next_steps() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    form_start = source.index("function _appendClarifyFormToBody(body, payload, args)")
    form_end = source.index("  function _appendClarifySkipSummary", form_start)
    form_body = source[form_start:form_end]

    assert "const requiredFields = fields.filter((field) => field && field.required);" in form_body
    assert "clarify-form-progress" in form_body
    assert "clarify-form-progress-metric" in form_body
    assert "clarify-form-progress-next" in form_body
    assert "已收集" in form_body
    assert "补充" in form_body
    assert "Suggested next steps" in form_body

    assert ".clarify-form-progress" in css
    assert ".clarify-form-progress-metric" in css
    assert ".clarify-form-progress-next" in css


def test_clarify_form_keeps_internal_prompt_out_of_primary_labels() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    form_start = source.index("function _appendClarifyFormToBody(body, payload, args)")
    form_end = source.index("  function _appendClarifySkipSummary", form_start)
    form_body = source[form_start:form_end]

    assert "const clarifyFieldDisplayLabel = (field) => {" in form_body
    assert "script draft" in form_body
    assert "verbatim reply" in form_body
    assert "回复内容" in form_body
    assert "Reply" in form_body
    assert "missingRequiredFields.map(clarifyFieldDisplayLabel)" in form_body
    assert "label.textContent = clarifyFieldDisplayLabel(field) + requiredFlag;" in form_body
    assert "field.prompt && clarifyFieldDisplayLabel(field) !== fieldPromptText" in form_body
    assert "clarify-form-field-help" in form_body
    assert "填写要求" in form_body
    assert "Requirements" in form_body

    assert ".clarify-form-field-help" in css
    assert ".clarify-form-field-help-summary" in css
    assert ".clarify-form-field-help-body" in css


def test_clarify_form_submit_waits_for_connection_and_shows_pending_feedback() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    form_start = source.index("function _appendClarifyFormToBody(body, payload, args)")
    form_end = source.index("  function _appendClarifySkipSummary", form_start)
    form_body = source[form_start:form_end]
    call_index = form_body.index("_rpc.call('chat.clarify_submit'")

    assert "_rpc.waitForConnection()" in form_body
    assert form_body.index("_rpc.waitForConnection()") < call_index
    assert "clarify-form--submitting" in form_body
    assert "clarify-form--submitted" in form_body
    assert "clarify-form-submit-status" in form_body
    assert "已提交，正在继续流程" in form_body
    assert "Submitted, continuing" in form_body

    assert ".clarify-form--submitting" in css
    assert ".clarify-form-submit-status" in css


def test_clarify_submit_button_has_direct_click_fallback() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    form_start = source.index("function _appendClarifyFormToBody(body, payload, args)")
    form_end = source.index("  function _appendClarifySkipSummary", form_start)
    form_body = source[form_start:form_end]

    assert "let clarifySubmitInFlight = false;" in form_body
    assert "const submitClarifyForm = () => {" in form_body
    assert "const form = document.createElement('div');" in form_body
    assert "form.setAttribute('role', 'form');" in form_body
    assert "submitBtn.type = 'button';" in form_body
    assert "submitBtn.addEventListener('click', (evt) => {" in form_body
    assert "form.addEventListener('keydown', (evt) => {" in form_body
    assert "evt.key !== 'Enter'" in form_body
    assert "evt.preventDefault();" in form_body
    assert "submitClarifyForm();" in form_body


def test_clarify_submit_connection_wait_has_visible_timeout() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    form_start = source.index("function _appendClarifyFormToBody(body, payload, args)")
    form_end = source.index("  function _appendClarifySkipSummary", form_start)
    form_body = source[form_start:form_end]

    assert "const waitForClarifySubmitConnection = () => Promise.race([" in form_body
    assert "_rpc.waitForConnection()," in form_body
    assert "setTimeout(() => reject(new Error(clarifyText(" in form_body
    assert "连接超时，请刷新页面后重试。" in form_body
    assert "waitForClarifySubmitConnection()" in form_body


def test_router_fx_settles_but_preserves_winner_animation_when_output_begins() -> None:
    # The moment output renders, the panel should stop roaming, but the winner
    # lock/settle animation must remain visible instead of becoming a static
    # empty frame.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert "function _routerFxSettleForOutput() {" in source
    fz_start = source.index("function _routerFxSettleForOutput() {")
    fz = source[fz_start:source.index("// Lock an in-flight scanning strip", fz_start)]
    assert "_routerFxFinishScan(wrap);" in fz
    assert "_routerFxStopScan(wrap);" not in fz
    assert "wrap.dataset.frozen = 'true';" not in fz
    # It is invoked at the top of the stream-bubble (output) path.
    esb = source[source.index("function _ensureStreamBubble() {"):]
    esb = esb[:esb.index("function _newTextSegment")]
    assert "_routerFxSettleForOutput();" in esb
    assert '.router-fx[data-frozen="true"]' not in css


def test_router_fx_history_mode_has_no_motion_effects() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert "function _routerFxStaticizeCompletedStrips(sessionKey) {" in source
    end_start = source.index("function _endStreaming(opts) {")
    end_body = source[end_start:source.index("function _hasViewLocalStreamState()", end_start)]
    assert "_routerFxStaticizeCompletedStrips(_streamSessionKey || _sessionKey || '');" in end_body

    assert '.router-fx[data-render-mode="history"]' in css
    history_motion_start = css.index('.router-fx[data-render-mode="history"],')
    history_motion = css[history_motion_start:css.index("}", history_motion_start)]
    assert "animation: none !important;" in history_motion
    assert "transition: none !important;" in history_motion


def test_router_fx_history_and_turn_meta_preserve_observe_rollout_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _buildRouterFxFromUsage(usage, seedKey, opts) {")
    history_end = source.index("  /* ── RPC Event Subscriptions", history_start)
    history_body = source[history_start:history_end]
    store_start = source.index("_storeTurnMeta(_sessionKey, _metaIdx")
    store_end = source.index("          });", store_start)
    store_body = source[store_start:store_end]

    assert "routing_applied: usage.routing_applied !== false," in history_body
    assert "rollout_phase: usage.rollout_phase || 'full'," in history_body
    assert "const observeMode = decision && decision.routing_applied === false;" in source
    assert "routing_applied: u.routing_applied !== false," in store_body
    assert "rollout_phase: u.rollout_phase || 'full'," in store_body


def test_router_fx_mobile_grid_uses_dynamic_candidate_columns() -> None:
    """Mobile router-fx grid follows actual candidate count, not a fixed wall."""
    css = CHAT_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 640px)")
    tiny_start = css.index("@media (max-width: 380px)")
    mobile_body = css[mobile_start:tiny_start]
    tiny_body = css[tiny_start:]

    assert (
        "grid-template-columns: "
        "repeat(var(--router-fx-mobile-cols, var(--router-fx-cols, 2)), 1fr);"
    ) in mobile_body
    assert "grid-template-rows: none;" in mobile_body
    assert "grid-template-columns: repeat(var(--router-fx-mobile-cols, 2), 1fr);" in tiny_body
    assert "grid-template-rows: none;" in tiny_body


def test_router_fx_visualisation_pref_is_client_side_localstorage() -> None:
    # The router-fx ON/OFF state is a per-browser preference (theme.js style),
    # NOT a gateway config write — distinct from the operator squilla_router
    # toggle. Persisted under an opensquilla-* localStorage key, default ON.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _ROUTER_FX_PREF_KEY = 'opensquilla-router-fx';" in source
    assert "const _routerFx = { enabled: true, variant: 'default' };" in source
    assert "function _routerFxLoadPref() {" in source
    assert "function _routerFxSavePref() {" in source
    assert "localStorage.getItem(_ROUTER_FX_PREF_KEY)" in source
    assert "localStorage.setItem(_ROUTER_FX_PREF_KEY" in source
    # Hydrated + switch synced on every render (inherits visibility/focus refresh).
    assert "_routerFxLoadPref();" in source
    assert "if (routerFxToggle) routerFxToggle.checked = _routerFx.enabled;" in source

    # Load path: a stored pref must actually be PARSED and APPLIED back onto
    # _routerFx (a no-op loader would silently reset a saved OFF to default-ON),
    # validating types, and must swallow localStorage/JSON throws (private mode).
    load_start = source.index("function _routerFxLoadPref() {")
    load_end = source.index("function _routerFxSavePref() {", load_start)
    load_body = source[load_start:load_end]
    assert "const saved = JSON.parse(raw);" in load_body
    assert "if (typeof saved.enabled === 'boolean') _routerFx.enabled = saved.enabled;" in load_body
    assert "saved.variant" not in load_body
    assert "_routerFx.variant = 'default';" in load_body
    assert "} catch { /* keep defaults */ }" in load_body

    # Save path: serialize the live pref and swallow quota/availability throws.
    save_start = load_end
    save_end = source.index("function _routerFxSortTiers(", save_start)
    save_body = source[save_start:save_end]
    assert "localStorage.setItem(_ROUTER_FX_PREF_KEY, JSON.stringify({" in save_body
    assert "enabled: _routerFx.enabled," in save_body
    assert "variant:" not in save_body
    assert "} catch { /* preference is best-effort */ }" in save_body

    # The toggle handler is client-side: it saves the pref and does NOT write
    # gateway config (no config.patch.safe in the router-fx handler). ON re-renders
    # historical strips via the rebuild; both branches give toast feedback.
    fx_start = source.index("const routerFxToggle = _el.querySelector('#toggle-router-fx');")
    fx_end = source.index("// Re-pull router config", fx_start)
    fx_body = source[fx_start:fx_end]
    assert "_routerFx.enabled = routerFxToggle.checked;" in fx_body
    assert "_routerFxSavePref();" in fx_body
    assert "config.patch.safe" not in fx_body
    assert "_scheduleHistorySync();" in fx_body
    assert "if (window.SavingsFX) window.SavingsFX.setEnabled(_routerFx.enabled);" in fx_body
    assert "UI.toast('Visual effects: '" in fx_body


def test_router_effects_default_on_and_cloud_choice_hidden() -> None:
    chat_source = CHAT_JS.read_text(encoding="utf-8")
    savings_source = (
        Path("src/opensquilla/gateway/static/js/components/savings-fx.js")
        .read_text(encoding="utf-8")
    )

    assert "const _routerFx = { enabled: true, variant: 'default' };" in chat_source
    assert (
        "try { return window.localStorage.getItem(_PREF_KEY) !== '0'; } catch { return true; }"
        in savings_source
    )
    assert "if (window.SavingsFX) window.SavingsFX.setEnabled(_routerFx.enabled);" in chat_source
    assert 'id="toggle-savings-fx"' not in chat_source
    assert "Savings FX" not in chat_source
    assert "Visual effects" in chat_source
    assert "Show router and savings effects" in chat_source
    assert "Router effects" not in chat_source
    assert "Router animation" not in chat_source
    assert "Cloud view" not in chat_source


def test_router_fx_render_gated_in_both_live_and_history_paths() -> None:
    # The visualisation pref gates RENDER in both the live (router_decision) and
    # history (rebuild) paths, ahead of all test-pinned lines. Tier/model
    # bookkeeping stays warm in the live path; the gate sits after it and before
    # the config await so a disabled panel short-circuits the 1.5s wait too.
    source = CHAT_JS.read_text(encoding="utf-8")
    handler_start = source.index("async function _handleRouterDecision(payload) {")
    handler_end = source.index("  // History-load entry point", handler_start)
    handler_body = source[handler_start:handler_end]

    pre_gate = (
        "if (!_routerFx.enabled) {\n"
        "      _chatDiag('router_decision.skip.disabled_pre_config'"
    )
    post_gate = (
        "if (!_routerFx.enabled) {\n"
        "      _chatDiag('router_decision.skip.disabled_post_config'"
    )
    assert pre_gate in handler_body
    assert post_gate in handler_body
    assert handler_body.index("_routerFxRememberTierDecision(tier, payload.model || '');") < \
        handler_body.index(pre_gate)
    assert handler_body.index(pre_gate) < \
        handler_body.index("await _routerFxAwaitConfig();")
    # Re-checked AFTER the await as well — the user may flip OFF during the
    # cold-start config wait, so the gate is symmetric on both sides.
    assert handler_body.count("if (!_routerFx.enabled) {") >= 2
    assert handler_body.index(post_gate) > \
        handler_body.index("await _routerFxAwaitConfig();")
    # History path gate returns null ahead of the operator gate (caller null-checks).
    assert "if (!_routerFx.enabled) return null;" in source
    assert source.index("if (!_routerFx.enabled) return null;") < \
        source.index("if (_routerFxConfigTiers !== null && !_routerFeatureEnabled) return null;")


def test_router_fx_disable_removes_all_strips_without_live_spare_path() -> None:
    # Hiding the panel is a user-visible preference. The disabled path should
    # remove router visuals directly instead of preserving a separate live-strip
    # path that competes with history reorder repair.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert (
        "_thread.querySelectorAll('.router-fx').forEach((n) => _routerFxRemoveStrip(n));"
        in source
    )
    assert ".router-fx:not([data-live=\"true\"])" not in source
    history_start = source.index("async function _loadHistory(opts = {}) {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]
    assert "if (!_routerFx.enabled) {" in history_body
    sweep = history_body[history_body.index("if (!_routerFx.enabled) {"):]
    sweep = sweep[: sweep.index("_lastSavingsPopupIdentity")]
    assert (
        "_thread.querySelectorAll('.router-fx').forEach((el) => _routerFxRemoveStrip(el));"
        in sweep
    )
    assert "dataset.live" not in sweep


def test_router_toggle_off_immediately_stops_router_visuals() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("const routerToggle = _el.querySelector('#toggle-router');")
    end = source.index("// Router-fx visualisation toggle", start)
    body = source[start:end]

    assert "const previousRouterFeatureEnabled = _routerFeatureEnabled;" in body
    assert "_routerFeatureEnabled = enabled;" in body
    assert "if (!enabled) _clearRouterFxVisuals('router_disabled');" in body
    assert "_routerFeatureEnabled = previousRouterFeatureEnabled;" in body
    assert "_clearRouterFxVisuals('router_patch_reverted');" in body
    assert "_scheduleHistorySync();" in body

    assert "function _clearRouterFxVisuals(reason = '') {" in source
    clear_start = source.index("function _clearRouterFxVisuals(reason = '') {")
    clear_end = source.index("async function _finishPendingRouterFxScan", clear_start)
    clear_body = source[clear_start:clear_end]
    assert "_cancelPendingRouterFxScan(reason || 'clear_visuals');" in clear_body
    assert (
        "_thread.querySelectorAll('.router-fx').forEach((el) => "
        "_routerFxRemoveStrip(el));"
        in clear_body
    )


def test_router_fx_variant_seam_stamps_data_variant() -> None:
    # data-variant on the .router-fx root is the style-variant seam (same idiom
    # as data-state/source/observe). Only non-'default' is stamped, leaving the
    # base look attribute-free. A documented CSS scaffold marks the extension
    # point; no variant block ships yet.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    builder_start = source.index("function _buildRouterFxElement(decision, opts) {")
    builder_end = source.index("  function ", builder_start + 1)
    builder_body = source[builder_start:builder_end]

    assert ("const variant = (opts.variant != null ? opts.variant : _routerFx.variant)"
            " || 'default';") in builder_body
    assert "if (variant && variant !== 'default') wrap.dataset.variant = variant;" in builder_body
    assert "Router-fx style variants" in css
    assert '.router-fx[data-variant="<name>"]' in css


def test_router_fx_visualisation_toggle_markup_reuses_switch() -> None:
    # The user-facing switch lives in the composer 'Composer settings' popover,
    # reusing the existing .toggle-switch recipe verbatim (no fifth toggle CSS).
    source = CHAT_JS.read_text(encoding="utf-8")
    popover_start = source.index('id="chat-toolbar-popover"')
    popover_end = source.index('chat-input-wrap', popover_start)
    popover = source[popover_start:popover_end]

    assert 'id="toggle-router-fx"' in popover
    assert "Visual effects" in popover
    assert "Show router and savings effects" in popover
    assert "Router effects" not in popover
    assert 'id="toggle-savings-fx"' not in popover
    assert "Savings FX" not in popover
    assert 'class="toggle-switch"' in popover
    assert popover.count('class="toggle-track"') >= 2


def test_chat_history_replays_turn_meta_to_restore_combo_streak() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory(opts = {}) {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "function _historyTurnMeta(msg) {" in source
    assert "function _savedUsageFromMeta(meta) {" in source
    assert "function _turnSavingsIdentity(u) {" in source
    assert "if (window.SavingsFX) window.SavingsFX.resetStreak();" in body
    assert "let historySavingsIdentity = '';" in body
    assert "const m = _historyTurnMeta(msg) || _recallTurnMeta(_sessionKey, _histAsstIdx);" in body
    assert "const savedUsage = _savedUsageFromMeta(m);" in body
    assert "const identity = _turnSavingsIdentity(savedUsage);" in body
    assert "if (identityChanged) savedUsage.__savings_ui_suppressed = true;" in body
    assert "window.SavingsFX.noteTurn(savedUsage);" in body
    assert body.index("window.SavingsFX.noteTurn(savedUsage);") < body.index(
        "_attachTurnMeta(div, m.model, m.input, m.output, savedUsage || undefined);"
    )
    assert "_lastSavingsPopupIdentity = historySavingsIdentity;" in body


def test_chat_turn_meta_replaces_existing_footer_before_append() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _attachTurnMeta(")
    end = source.index("  function _normalizeAgentId", start)
    body = source[start:end]

    assert "bubble.querySelectorAll(':scope > .msg-meta')" in body
    assert "forEach((el) => el.remove())" in body
    assert body.index("bubble.querySelectorAll(':scope > .msg-meta')") < body.index(
        "bubble.appendChild(meta);"
    )


def test_chat_done_event_reconciles_final_text_before_ending_stream() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("if (event.endsWith('.done') || event === 'chat.done') {")
    end = source.index("        // Populate savings indicator", start)
    body = source[start:end]

    assert "const finalText = typeof u.text === 'string' ? u.text : '';" in body
    assert "if (finalText && finalText !== _streamRaw)" in body
    # _endStreaming now takes an optional {reason} so abort-vs-natural can be
    # distinguished; the ordering invariant (reconcile before end) is preserved.
    end_call_marker = "_endStreaming(_doneWasAborted ? { reason: 'aborted' } : undefined);"
    assert end_call_marker in body
    assert body.index("if (finalText && finalText !== _streamRaw)") < body.index(end_call_marker)


def test_chat_turn_complete_event_schedules_history_sync() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("_rpc.on('sessions.changed'")
    end = source.index("_rpc.on('task.queued'", start)
    body = source[start:end]

    assert "function _scheduleHistorySync()" in source
    assert "reason === 'turn_complete'" in source
    assert "_sessionChangeIsTerminal(payload)" in body
    helper = source[
        source.index("function _syncTerminalSessionChange(payload = {})") :
        source.index(
            "  function _activeTaskGroupRunState",
            source.index("function _syncTerminalSessionChange(payload = {})"),
        )
    ]
    assert "_scheduleHistorySync();" in helper


def test_chat_turn_complete_event_schedules_pending_queue_drain_fallback() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    helper = source[
        source.index("function _syncTerminalSessionChange(payload = {})") :
        source.index(
            "  function _activeTaskGroupRunState",
            source.index("function _syncTerminalSessionChange(payload = {})"),
        )
    ]
    scheduler = source[
        source.index("function _schedulePendingDrainAfterTerminal()") :
        source.index(
            "  // Programmatic textarea write",
            source.index("function _schedulePendingDrainAfterTerminal()"),
        )
    ]

    assert "_schedulePendingDrainAfterTerminal();" in helper
    assert "const recoverPending =" in helper
    assert "_recoverPendingAfterTerminal(state.status);" in helper
    assert (
        "if (_isStreaming || _isCompactInFlightForCurrentSession() || "
        "_pendingQueue.length === 0) return;"
        in scheduler
    )
    assert "_drainQueueHead();" in scheduler


def test_chat_failed_terminal_events_recover_pending_queue_to_composer() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    error_start = source.index("} else if (event.endsWith('.error')) {")
    error_end = source.index("      }\n    }));", error_start)
    error_body = source[error_start:error_end]
    terminal_start = source.index("const terminalStatus = _taskTerminalStatus(rawEvent);")
    terminal_end = source.index("      const normalized =", terminal_start)
    terminal_body = source[terminal_start:terminal_end]

    assert "function _recoverPendingAfterTerminal(status = 'failed')" in source
    assert "_recoverPendingAfterTerminal(_normalizeRunStatus" in error_body
    assert "_recoverPendingAfterTerminal(terminalRunStatus);" in terminal_body


def test_chat_approval_pending_has_distinct_run_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    approval_start = source.index("function _setStreamIdlePausedForApproval(paused)")
    approval_end = source.index("  function _resetStreamIdleTimer()", approval_start)
    approval_body = source[approval_start:approval_end]

    assert "approval_pending: 'Waiting for approval'" in source
    assert "approval_pending: 'chip-warn'" in source
    assert "_approvalPendingForCurrentSession" in source
    assert "run_status: 'approval_pending'" in approval_body
    assert "active_task: { status: 'approval_pending'" in approval_body


def test_chat_replayed_compaction_terminal_restores_separator_without_toast() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "function _compactionTerminalStatus(status)" in source
    assert "const isReplay = !!(meta && meta.replayed);" in body
    assert "if (isReplay && !_compactionTerminalStatus(status)) return;" in body
    assert "if (meta && meta.replayed) return;" not in body
    assert "if (!isReplay) UI.toast('Compact failed'" in body
    assert "if (!isReplay) {\n        UI.toast(\n          'Compact cancelled'" in body


def test_chat_terminal_compaction_separator_persists_for_completed_manual_and_auto() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    sync_start = source.index(
        "function _syncCompactionSeparator(payload, status, source, overrides = {})"
    )
    sync_end = source.index("function _clearCompactionSummarySeparators", sync_start)
    sync_body = source[sync_start:sync_end]

    assert "function _compactionSeparatorAnimated(status, overrides = {})" in source
    assert "function _shouldPersistCompactionSeparator(status, source, overrides = {})" in source
    assert "return status === 'completed';" in source
    assert "const liveClass = _compactionSeparatorAnimated(status, overrides)" in sync_body
    assert "filter(Boolean)" in sync_body
    assert "if (_shouldPersistCompactionSeparator(status, source, overrides)) return;" in sync_body
    assert "_scheduleCompactionSeparatorRemoval();" in sync_body


def test_rpc_client_passes_event_meta_without_polluting_payload() -> None:
    source = RPC_JS.read_text(encoding="utf-8")
    event_start = source.index("} else if (data.type === 'event') {")
    event_end = source.index("    };\n", event_start)
    event_body = source[event_start:event_end]

    assert "const meta = data.meta || {};" in event_body
    assert "h(data.payload, meta)" in event_body
    assert "h(data.event, data.payload, meta)" in event_body


def test_chat_history_reconciles_by_message_identity_without_clear_replace() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory(opts = {}) {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "function _historyStableMessageIdentity(msg)" in source
    assert "function _historyElementFallbackIdentity(el)" in source
    assert "function _historyFallbackText(role, text)" in source
    assert "const existingByStableIdentity = new Map();" in body
    assert "const existingByFallbackIdentity = new Map();" in body
    assert "const consumedHistoryElements = new Set();" in body
    assert "data-message-id" in source
    assert (
        "_stampHistoryElement(div, stableIdentity, msg.role, displayText, "
        "_messageTranscriptId(msg));"
    ) in body
    assert "let div = stableIdentity ? existingByStableIdentity.get(stableIdentity) : null;" in body
    assert "consumedHistoryElements," in body
    assert "consumedHistoryElements.add(div);" in body
    assert body.index("const messages = data.messages || [];") < body.index(
        "const existingByStableIdentity = new Map();"
    )
    assert "      _thread.innerHTML = '';" not in body[: body.index("if (messages.length === 0)")]
    assert "if (_isStreaming && _isCurrentSessionStreamBubble(el)) return;" in body
    assert "if (!consumedHistoryElements.has(el)) el.remove();" in body


def test_chat_history_reorders_reused_nodes_to_match_transcript_order() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory(opts = {}) {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "_thread.querySelectorAll('.chat-day-sep').forEach((el) => el.remove());" in body
    assert "function _appendHistoryElementInOrder(div)" in source
    assert "const liveTail = _historyLiveTailAnchor();" in source
    assert "if (liveTail && div !== liveTail)" in source
    assert "_thread.insertBefore(div, liveTail);" in source
    assert "_thread.appendChild(div);" in source
    stamp_idx = body.index(
        "_stampHistoryElement(div, stableIdentity, msg.role, displayText, "
        "_messageTranscriptId(msg));"
    )
    reorder_idx = body.index("_appendHistoryElementInOrder(div);")
    assert stamp_idx < reorder_idx


def test_chat_history_fallback_identity_consumes_duplicate_elements() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _pushIdentityElement(map, identity, el)" in source
    assert "function _shiftIdentityElement(map, identity, consumedElements = null)" in source
    assert "elements.push(el);" in source
    assert "if (!consumedElements || !consumedElements.has(el)) return el;" in source


def test_chat_history_fallback_identity_normalizes_assistant_directives() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _historyFallbackText")
    end = source.index("  function _pushIdentityElement", start)
    body = source[start:end]

    assert (
        "if (role === 'assistant') return "
        "_stripProtocolTextLeak("
        "_stripDirectiveTags(_stripGeneratedArtifactMarkers(text || ''))"
        ").trim();"
        in body
    )


def test_chat_first_delta_marks_render_dirty_before_flush() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _appendDelta(text) {")
    end = source.index("  function _flushRender()", start)
    body = source[start:end]

    assert "_renderDirty = true;\n      _flushRender();" in body


def test_chat_flushes_pending_text_before_tool_segment_boundary() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    helper_start = source.index("function _flushPendingTextSegment() {")
    helper_end = source.index("  function _flushRender()", helper_start)
    helper_body = source[helper_start:helper_end]
    tool_start = source.index("function _appendToolCall(payload) {")
    tool_end = source.index("  function _appendToolResult(payload) {", tool_start)
    tool_body = source[tool_start:tool_end]

    assert "if (!_renderDirty) return;" in helper_body
    assert "_flushRender();" in helper_body
    assert tool_body.index("_flushPendingTextSegment();") < tool_body.index(
        "_newTextSegment();"
    )


def test_chat_history_replacement_preserves_message_body_rendering() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    replace_start = source.index("function _replaceHistoryMessage")
    replace_end = source.index("  /* ── Send Message", replace_start)
    replace_body = source[replace_start:replace_end]
    render_start = source.index("function _renderMessageBody")
    render_end = source.index("  function _scrollToBottom", render_start)
    render_body = source[render_start:render_end]

    assert "_renderMessageBody(body, role, text, options);" in replace_body
    visible_text_assignment = (
        "const visibleText = role === 'assistant' "
        "? _stripGeneratedArtifactMarkers(text) : text;"
    )
    markdown_render = (
        "Markdown.render(_stripProtocolTextLeak(_stripDirectiveTags(visibleText)))"
    )
    assert visible_text_assignment in render_body
    assert markdown_render in render_body
    assert "Markdown.bindHighlight(body);" in render_body


def test_chat_history_replacement_rebuilds_role_header() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _syncMessageHeader(div, displayRole, timestamp, options = {}) {" in source

    helper_start = source.index(
        "function _syncMessageHeader(div, displayRole, timestamp, options = {}) {"
    )
    helper_end = source.index("function _replaceHistoryMessage", helper_start)
    helper_body = source[helper_start:helper_end]
    assert "const existing = div.querySelector(':scope > .msg-header');" in helper_body
    assert "_displayRoleLabel(displayRole)" in helper_body
    assert "_renderMessageTags(options)" in helper_body
    assert "div.insertBefore(header, div.firstChild);" in helper_body
    assert "if (sameGroup) {" in helper_body
    assert "if (existing) existing.remove();" in helper_body

    replace_start = source.index("function _replaceHistoryMessage")
    replace_end = source.index("  function _replaceStreamText", replace_start)
    replace_body = source[replace_start:replace_end]
    assert (
        "_syncMessageHeader(div, displayRole, options.timestamp || null, options);"
        in replace_body
    )

    history_start = source.index("const msgOptions = {")
    history_end = source.index("_messages.push({", history_start)
    history_body = source[history_start:history_end]
    assert "timestamp: msg.timestamp || msg.ts || null," in history_body


def test_chat_streaming_text_strips_generated_artifact_markers() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    flush_start = source.index("function _flushRender()")
    flush_end = source.index("  function _endStreaming", flush_start)
    flush_body = source[flush_start:flush_end]
    end_start = source.index("function _endStreaming")
    end_end = source.index("  /* ── Attachments", end_start)
    end_body = source[end_start:end_end]

    assert "function _stripGeneratedArtifactMarkers(text)" in source
    assert "_stripGeneratedArtifactMarkers(_activeTextRaw)" in flush_body
    assert "_stripGeneratedArtifactMarkers(_streamRaw)" in end_body
    assert "_stripGeneratedArtifactMarkers(seg.raw)" in end_body


def test_chat_history_text_segments_use_protocol_leak_guard() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    reconstruct_start = source.index("function _reconstructToolCalls")
    reconstruct_end = source.index("  /* ── Message Rendering", reconstruct_start)
    reconstruct_body = source[reconstruct_start:reconstruct_end]
    render_start = source.index("function _renderMessageBody")
    render_end = source.index("  function _scrollToBottom", render_start)
    render_body = source[render_start:render_end]

    assert "function _stripProtocolTextLeak" in source
    assert "_stripProtocolTextLeak(seg.text || '')" in reconstruct_body
    assert "_stripProtocolTextLeak(_stripDirectiveTags(visibleText))" in render_body
    assert "View areas around line" in source
    assert "effect_calls" in source
    assert "angle\\s+brackets" in source


def test_approval_monitor_uses_adaptive_timeout_backoff() -> None:
    source = Path("src/opensquilla/gateway/static/js/approval_monitor.js").read_text(
        encoding="utf-8"
    )

    assert "const POLL_MAX_MS = 30000;" in source
    assert "let _pollDelayMs = POLL_MS;" in source
    assert "function _schedulePoll(delayMs = _pollDelayMs)" in source
    assert "setTimeout(async () =>" in source
    assert "_increasePollBackoff();" in source
    assert "setInterval(_poll, POLL_MS)" not in source


def test_approval_monitor_sends_auth_headers() -> None:
    source = Path("src/opensquilla/gateway/static/js/approval_monitor.js").read_text(
        encoding="utf-8"
    )

    assert "function _authHeaders(extra)" in source
    assert "App.getAuthToken" in source
    assert "window.App && App.getAuthToken" not in source
    assert "typeof App !== 'undefined'" in source
    assert "headers['Authorization'] = `Bearer ${token}`;" in source
    assert "headers: _authHeaders()," in source
    assert "headers: _authHeaders({ 'Content-Type': 'application/json' })" in source


def test_approval_monitor_inline_button_opens_existing_modal_instead_of_page() -> None:
    source = Path("src/opensquilla/gateway/static/js/approval_monitor.js").read_text(
        encoding="utf-8"
    )
    start = source.index("inline.addEventListener('click'")
    handler = source[start : source.index("});", start) + 3]

    assert "Router.navigate('/approvals')" not in source
    assert "_openModal(pending[0], data.mode || 'prompt');" in source
    assert "_resetPollBackoff();" in handler
    assert "_poll();" in handler


def test_session_api_token_totals_load_independently_of_token_widget() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadCurrentSessionUsage() {")
    end = source.index("  function _relTime", start)
    body = source[start:end]

    assert "OPENSQUILLA_FEATURES?.tokenViz" not in body
    assert "const usage = await _rpc.call('usage.status', { sessionKey: _sessionKey });" in body
    assert "Turn — input:" in source


def test_chat_context_warning_uses_backend_context_status_not_lifetime_usage() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _updateCtxWarning()")
    end = source.index("  /* ── Chat History", start)
    body = source[start:end]

    assert "const _CTX_WARN_THRESHOLD" not in source
    assert "_totalTokens > _CTX_WARN_THRESHOLD" not in source
    assert "Context > 85%" not in source
    assert "_contextStatus" in body
    assert "contextTokens" in body
    assert "context_window_tokens" in body
    assert "Request ctx" in body


def test_chat_usage_status_applies_current_session_context_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadCurrentSessionUsage() {")
    end = source.index("  function _relTime", start)
    body = source[start:end]

    assert "_applyContextStatus(current.contextStatus || current.context_status || null);" in body
    assert "_clearContextStatus();" in body


def test_combo_display_requires_current_saved_turn_but_suppressed_savings_can_count() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    savings_source = SAVINGS_FX_JS.read_text(encoding="utf-8")

    assert "u.__savings_ui_suppressed = true;" in source
    assert "const savingsDetailSuppressed = !!u.__savings_ui_suppressed;" in source
    assert "const hasSaved = !savingsDetailSuppressed && hasTier && turnSavedPct > 0;" in source
    assert "const hasCombo = hasSaved && streak >= 2;" in source
    assert source.index("const hasSaved =") < source.index(
        "const hasCombo = hasSaved && streak >= 2;"
    )
    assert "if (suppressPopup) return;" in source
    assert source.index("window.SavingsFX.noteTurn(u);") < source.index(
        "if (suppressPopup) return;"
    )
    assert "let _streakIdentity = '';" in savings_source
    assert "function _turnIdentity(u) {" in savings_source
    assert "function _isComboTier(tier) {" in savings_source
    assert "if (numeric) return Number(numeric[1]) < 3;" in savings_source
    assert "_streak = (_streakIdentity === identity) ? _streak + 1 : 1;" in savings_source
    assert "_streakIdentity = identity;" in savings_source
    assert (
        "if (hasTier && savePct > 0 && identity && _isComboTier(u.routed_tier))"
        in savings_source
    )


def test_savings_fx_only_vibrates_after_browser_user_activation() -> None:
    savings_source = SAVINGS_FX_JS.read_text(encoding="utf-8")

    assert "function _canVibrate()" in savings_source
    assert "navigator.userActivation" in savings_source
    assert "activation.hasBeenActive || activation.isActive" in savings_source
    assert "if (_canVibrate()) {" in savings_source


def test_savings_fx_scores_prefer_comprehensive_totals() -> None:
    source = SAVINGS_FX_JS.read_text(encoding="utf-8")

    assert "const savingsUsd = (typeof u.total_savings_usd === 'number')" in source
    assert (
        "const rawPct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)"
        in source
    )


def test_chat_streaming_bubble_has_polite_live_region() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _ensureStreamBubble()")
    end = source.index("function ", start + 1)
    body = source[start:end]
    assert "_streamBubble.setAttribute('aria-live', 'polite');" in body


def test_chat_thread_does_not_duplicate_composer_bottom_clearance() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    assert "padding-bottom: max(var(--composer-h" not in css
    assert "padding-bottom: var(--composer-h" not in css
    assert "document.documentElement.style.setProperty('--composer-h'" in source


def test_chat_input_bar_tightens_desktop_bottom_padding_but_keeps_mobile_safe_area() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")
    desktop_padding = "padding: var(--sp-2) var(--sp-4) var(--sp-1);"
    mobile_safe_area = (
        "padding-bottom: calc(var(--sp-2) + env(safe-area-inset-bottom, 0px));"
    )

    assert ".content:has(> .chat)" in css
    assert "padding-bottom: 0;" in css
    assert desktop_padding in css
    assert mobile_safe_area in css
    assert css.rfind(mobile_safe_area) > css.index(desktop_padding)


def test_chat_task_lifecycle_events_are_session_scoped() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    runtime = TASK_RUNTIME_PY.read_text(encoding="utf-8")

    queued_start = source.index("_rpc.on('task.queued'")
    queued_end = source.index("_rpc.on('task.running'", queued_start)
    queued_body = source[queued_start:queued_end]
    running_start = queued_end
    running_end = source.index("_rpc.on('session.event.task_group.waiting'", running_start)
    running_body = source[running_start:running_end]
    terminal_start = source.index("const terminalStatus = _taskTerminalStatus(rawEvent);")
    terminal_end = source.index("      const normalized =", terminal_start)
    terminal_body = source[terminal_start:terminal_end]

    assert "if (!_isCurrentSessionPayload(payload)) return;" in queued_body
    assert "_currentRunStatus === 'running'" in queued_body
    assert "_currentRunStatus === 'approval_pending'" in queued_body
    assert "if (!_isCurrentSessionPayload(payload)) return;" in running_body
    assert "if (!_isCurrentSessionPayload(rawPayload)) return;" in terminal_body
    queued_emit_start = runtime.index('await self._emit(\n            envelope.session_key,')
    queued_emit_end = runtime.index("        return TaskHandle", queued_emit_start)
    queued_emit = runtime[queued_emit_start:queued_emit_end]
    running_emit_start = runtime.index('await self._emit(\n            task.envelope.session_key,')
    running_emit_end = runtime.index(
        "        await self._notify_task_lifecycle",
        running_emit_start,
    )
    running_emit = runtime[running_emit_start:running_emit_end]

    assert '"task.queued"' in queued_emit
    assert '"session_key": envelope.session_key' in queued_emit
    assert '"task.running"' in running_emit
    assert '"session_key": task.envelope.session_key' in running_emit
    assert '"session_key": task.envelope.session_key' in runtime


def test_chat_queue_drain_preserves_draft_typed_during_stream() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _drainQueueHead()")
    end = source.index("  function _popPendingTail", start)
    body = source[start:end]

    assert "const draftText = _textarea.value;" in body
    assert "const draftAttachments = _pendingAttachments.map" in body
    assert "const draftIntent = _pendingSessionIntent;" in body
    assert "_onSend();" in body
    assert "if (draftText.trim() || draftAttachments.length || draftIntent) {" in body
    assert "_textarea.value = draftText;" in body
    assert "_pendingAttachments = draftAttachments;" in body
    assert "_pendingSessionIntent = draftIntent;" in body
    assert body.index("_onSend();") < body.index("_textarea.value = draftText;")
