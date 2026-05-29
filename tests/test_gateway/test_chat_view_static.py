import re
from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
CHAT_CSS = Path("src/opensquilla/gateway/static/css/views/chat.css")
RPC_JS = Path("src/opensquilla/gateway/static/js/rpc.js")
SAVINGS_FX_JS = Path("src/opensquilla/gateway/static/js/components/savings-fx.js")
TASK_RUNTIME_PY = Path("src/opensquilla/gateway/task_runtime.py")


def test_chat_history_passes_subagent_completion_provenance_to_renderer() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "provenanceSourceTool: msg.provenance_source_tool || ''" in source
    assert "provenanceSourceSessionKey: msg.provenance_source_session_key || ''" in source


def test_chat_toolbar_has_no_tool_compress_selector() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "Tool " + "Compress" not in source
    assert "tool" + "Compress" not in source
    assert "tool-compress" not in source


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


def test_chat_artifact_images_render_as_preview_cards_and_refresh_on_done() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    render_start = source.index("function _renderArtifacts(artifacts)")
    render_end = source.index("  async function _downloadArtifact", render_start)
    render_body = source[render_start:render_end]
    done_start = source.index("if (event.endsWith('.done') || event === 'chat.done') {")
    done_end = source.index("        // On natural completion", done_start)
    done_body = source[done_start:done_end]

    assert "function _isImageArtifact(artifact)" in source
    assert "function _artifactCategory(artifact)" in source
    assert "function _artifactPreviewUrl(artifact)" in source
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

    assert "function _agentIdFromSessionKey(key)" in source
    assert "return _webchatSessionKey(_agentIdFromSessionKey(_sessionKey)," in source
    assert 'title="New chat session in the current agent"' in source
    assert "New chat session in the current agent: " in source


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
    assert "if (!isLiteralSlash && text.startsWith('/')) {" in send_prefix
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
    streaming_idx = send_prefix.index(
        "if (_isStreaming || _isCompactInFlightForCurrentSession()) {"
    )
    execute_idx = send_prefix.index("await _executeSlashCommand(text)")
    real_slash_guard = "if (!isLiteralSlash && text.startsWith('/')) {"
    streaming_block_end = send_prefix.index(f"\n\n    {real_slash_guard}", streaming_idx)
    streaming_block = send_prefix[streaming_idx:streaming_block_end]

    assert flag_idx < literal_idx < streaming_idx
    assert literal_idx < flag_set_idx < streaming_idx
    assert "text = text.slice(1);" in send_prefix[literal_idx:streaming_idx]
    assert real_slash_guard in streaming_block
    assert "const waitReason = _isCompactInFlightForCurrentSession()" in streaming_block
    assert "Wait for ${waitReason} before running" in streaming_block
    assert "_executeSlashCommand" not in streaming_block
    assert streaming_idx < execute_idx
    assert real_slash_guard in send_prefix[streaming_idx:execute_idx]


def test_chat_slash_executor_handles_unknown_without_chat_send() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    exec_start = source.index("async function _executeSlashCommand(text)")
    exec_end = source.index("  /* ── Send Message", exec_start)
    executor = source[exec_start:exec_end]

    assert "_slashCommandMap.get(_slashCommandKey(cmdText))" in executor
    assert "Unsupported command" in executor
    assert "return true;" in executor
    assert "chat.send" not in executor


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
    assert source.count("_pendingSessionIntent = 'new_chat'") == 2
    assert "params.intent = _pendingSessionIntent;" in source


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
    assert "Session stream gap detected; reloading transcript." in source


def test_chat_stream_handlers_drop_replayed_duplicate_frames() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _subscribeRpcEvents() {")
    end = source.index("  /* ── Chat History", start)
    body = source[start:end]

    assert "function _acceptStreamSeq(payload)" in source
    assert "if (!_acceptStreamSeq(payload)) return;" in body
    assert "_noteStreamSeq(payload);" not in body


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
    assert body.index("_setSessionStreamSeq(subscribeKey, res.current_stream_seq);") < body.index(
        "_loadHistory();"
    )


def test_chat_empty_history_preserves_live_stream_bubble() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _renderHistoryMessages(messages")
    end = source.index("    const existingByStableIdentity = new Map();", start)
    body = source[start:end]

    assert "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');" in body
    assert "if (_isStreaming && (_isCurrentSessionStreamBubble(_streamBubble) || liveRouterStrips.length > 0 || liveUserAnchor))" in body
    assert "if (liveUserAnchor && !liveUserAnchor.isConnected) _thread.appendChild(liveUserAnchor);" in body
    assert "_thread.appendChild(_streamBubble);" in body
    assert "return;" in body[body.index("if (_isStreaming && (_isCurrentSessionStreamBubble(_streamBubble) || liveRouterStrips.length > 0 || liveUserAnchor))") :]


def test_chat_live_stream_bubble_is_session_scoped() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "let _streamSessionKey = '';" in source
    assert "function _isCurrentSessionStreamBubble(el)" in source
    assert "streamKey === currentKey" in source
    assert "_streamBubble.dataset.streamSessionKey = _streamSessionKey || _sessionKey || '';" in source
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
    assert "_currentSessionLiveRouterStrips(_streamSessionKey || _sessionKey || '').length" in has_body
    assert "_thinkingEl" in has_body
    assert "_thinkingDelayTimer" in has_body

    restore_start = source.index("function _restoreLiveStreamStateForSession(key)")
    restore_end = source.index("function _clearViewLocalStreamState(reason)", restore_start)
    restore_body = source[restore_start:restore_end]
    assert "const routerStrips = Array.isArray(state.routerStrips) ? state.routerStrips : [];" in restore_body
    assert "const liveUserAnchor = state.liveUserAnchor || null;" in restore_body
    assert "if (_thread && liveUserAnchor && !liveUserAnchor.isConnected)" in restore_body
    assert "_insertLiveRouterStripForAnchor(el, liveUserAnchor, _streamBubble);" in restore_body
    assert "_routerFxResumeLiveStrip(el);" in restore_body


def test_chat_empty_history_keeps_live_router_only_running_view() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _renderHistoryMessages(messages")
    history_end = source.index("const existingByStableIdentity = new Map();", history_start)
    history_body = source[history_start:history_end]

    assert "const liveRouterStrips = _currentSessionLiveRouterStrips(_sessionKey || '');" in history_body
    assert "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');" in history_body
    assert "_isCurrentSessionStreamBubble(_streamBubble) || liveRouterStrips.length > 0 || liveUserAnchor" in history_body
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

    assert "const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');" in history_body
    assert "if (_isStreaming && el === liveUserAnchor) return;" in history_body


def test_chat_router_restore_does_not_auto_settle_without_cached_decision() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    resume_start = source.index("function _routerFxResumeLiveStrip(wrap)")
    resume_end = source.index("  // When output begins", resume_start)
    resume_body = source[resume_start:resume_end]
    assert "if (wrap._fxDecision) {" in resume_body
    assert "wrap._fxScanCap = setTimeout(() => _routerFxFinishScan(wrap), _ROUTER_FX_SCAN_MS);" in resume_body
    assert "_chatDiag('router_scan.resume_without_decision'" in resume_body
    assert resume_body.index("if (wrap._fxDecision) {") < resume_body.index("wrap._fxScanCap = setTimeout")

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


def test_chat_surfaces_compaction_lifecycle_toasts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    compact_block = source[
        source.index("case 'compact_context':") : source.index("case 'usage_status':")
    ]
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "_setCompactInFlight(true, compactKey);" in compact_block
    assert "Compacting context..." in body
    assert "Already within context budget; no compact was applied." in body
    assert "if (compactKey !== _sessionKey) return;" in compact_block
    assert (
        "_showCompactionToast({ ...(result || {}), key: compactKey, source: 'manual'"
        in compact_block
    )
    assert "session.event.compaction" in source
    assert "Context compacted older messages to keep this session within budget" in source
    assert "Compact cancelled" in source


def test_chat_surfaces_persistent_compaction_status_row() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert 'id="chat-compact-status"' in source
    assert "let _compactStatusEl = null;" in source
    assert "let _compactStatusTimer = null;" in source
    assert "function _setCompactStatus(status, message, options = {})" in source
    assert "function _hideCompactStatus()" in source
    assert "_compactStatusEl = _el.querySelector('#chat-compact-status');" in source
    assert "_setCompactStatus('started', 'Compacting context...'" in body
    assert (
        "_setCompactStatus('skipped', 'Already within context budget; no compact was applied.'"
        in body
    )
    assert "_setCompactStatus('completed', 'Context compacted' + details" in body
    assert "_setCompactStatus('failed', 'Compact failed' + msg + pendingSuffix" in body
    assert "_setCompactStatus('cancelled', 'Compact cancelled'" in body
    assert "_hideCompactStatus();" in source[source.index("function destroy()") :]
    assert ".chat-compact-status" in css
    assert ".chat-compact-status__spinner" in css


def test_chat_compaction_token_details_are_success_only() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]
    stats_start = source.index("function _compactionTokenStats(payload)")
    stats_end = source.index("function _showCompactionToast(payload, meta = {})", stats_start)
    stats_body = source[stats_start:stats_end]
    skipped_start = body.index("if (status === 'skipped')")
    skipped_end = body.index("if (status === 'failed'", skipped_start)
    skipped_block = body[skipped_start:skipped_end]

    assert "UI.toast('Already within context budget; no compact was applied.'" in skipped_block
    assert "_compactionTokenStats" not in skipped_block
    assert "payload && payload.tokens_after || 0" not in stats_body
    assert body.index("_compactionTokenStats(payload || {})") > body.index(
        "if (status === 'cancelled')"
    )


def test_chat_semantic_memory_degraded_is_non_blocking_and_path_safe() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _compactSemanticMemoryNotice(payload)" in source
    assert "payload.semanticMemory || payload.semantic_memory" in source
    assert "Memory saved; organizing" in source
    assert "UI.toast(semanticNotice, 'info', 3500);" in body
    assert body.index("const semanticNotice = _compactSemanticMemoryNotice") < body.index(
        "if (status === 'failed' || status === 'error')"
    )
    assert "function _compactSafeMessageDetail(payload)" in source
    assert "[memory checkpoint]" in source
    assert "const detail = _compactSafeMessageDetail(payload || {});" in body
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
    assert "preservePending," in toast_body
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
    assert (
        "if (!cacheHit && now - _savingsPopupLastTs < _SAVINGS_POPUP_COOLDOWN_MS) return;"
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


def test_router_fx_header_names_ai_model_router() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert '<span class="title">AI model router</span>' in source
    assert '<span class="title">model router</span>' not in source


def test_router_fx_live_routes_keep_random_chase_animation() -> None:
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
    assert "if (observeMode)" in handler_body
    assert "_animateRouterFx(wrap, winnerIdx)" in handler_body
    assert handler_body.index("if (observeMode)") < handler_body.index(
        "_animateRouterFx(wrap, winnerIdx)"
    )


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


def test_chat_history_requests_canonical_paginated_metadata() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("async function _loadEarlierHistory()", history_start)
    history_body = source[history_start:history_end]

    assert "const CHAT_HISTORY_PAGE_SIZE = 50;" in source
    assert "const requestSessionKey = _sessionKey;" in history_body
    assert "const requestSeq = ++_historyRequestSeq;" in history_body
    assert "sessionKey: requestSessionKey" in history_body
    assert "limit: CHAT_HISTORY_PAGE_SIZE" in history_body
    assert "includeCanonical: true" in history_body
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
    end = source.index("async function _loadHistory()", start)
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
    initial_start = source.index("async function _loadHistory() {")
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
    end = source.index("async function _loadHistory()", start)
    body = source[start:end]

    assert "row.className = `chat-history-scope chat-history-scope--${tone}`;" in body
    assert "row.className = `msg" not in body
    assert "_thread.querySelectorAll('.chat-history-scope').forEach((el) => el.remove());" in source


def test_router_fx_history_reuses_settled_strip_for_same_turn_identity() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]

    assert "function _routerFxUserMessageForAssistant(referenceAssistant) {" in source
    assert "const userMsg = _routerFxUserMessageForAssistant(div);" in history_body
    assert "const userMsg = _routerFxLastUserMessage();" not in history_body
    assert "el.dataset.sessionKey === (_sessionKey || '') && el.dataset.turnIndex" in source
    assert "const routerIdentity = _routerFxUsageIdentity(savedUsage);" in source
    assert "existingStrip.dataset.routerIdentity === routerIdentity" in source
    assert "if (existingStrip) existingStrip.remove();" in source
    assert "existingStrip.dataset.live" not in history_body
    assert "routerStrip.dataset.turnIndex = String(_histUserIdx);" in source


def test_router_fx_history_reanchors_stranded_strip() -> None:
    # _appendHistoryElementInOrder re-appends only .msg elements, stranding any
    # strip already rendered for a turn. The rebuild must match this turn's
    # strip(s) by (session, turn index) and router identity — NOT by the live
    # flag — keep the one whose identity matches, drop extras, and re-anchor the
    # survivor beneath its user message, so the first chat never shows two grids.
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]

    # Match by (session, turnIndex), independent of the data-live flag.
    assert (
        "const ownStrips = Array.from(_thread.querySelectorAll('.router-fx')).filter("
        in history_body
    )
    assert "el.dataset.turnIndex === String(_histUserIdx)" in history_body
    assert "el.dataset.routerIdentity === routerIdentity" in history_body
    # Drop duplicates, re-anchor the survivor, promote it out of live state.
    assert "ownStrips.forEach((el) => { if (el !== keep) el.remove(); });" in history_body
    assert "_thread.insertBefore(keep, userMsg.nextSibling);" in history_body
    assert "delete keep.dataset.live;" in history_body
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
    assert "if (!anchored) el.remove();" in history_body


def test_router_fx_uses_fixed_model_slots_and_keeps_decoy_seed() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    builder_start = source.index("function _routerFxBuildGridCells(realEntries, seedKey) {")
    builder_end = source.index("  function _buildRouterFxElement", builder_start)
    builder_body = source[builder_start:builder_end]
    live_start = source.index("async function _handleRouterDecision(payload) {")
    live_end = source.index("  // History-load entry point", live_start)
    live_body = source[live_start:live_end]

    assert "const _ROUTER_FX_REAL_ANCHOR_CELLS = [1, 6, 8, 13, 11" in source
    assert "function _routerFxResolveLayoutSeed(sessionKey, hintTimestamp)" in source
    assert "const liveSeed = _routerFxResolveLayoutSeed(_sessionKey);" in live_body
    assert "const cachedSeed = _routerFxResolveLayoutSeed(_sessionKey, hint);" in source
    assert "const orderedRealEntries = realEntries.slice().sort" in builder_body
    assert "const anchor = _ROUTER_FX_REAL_ANCHOR_CELLS[i];" in builder_body
    assert "const orderedDecoys = _routerFxShuffle(decoys," in builder_body
    assert "return _routerFxShuffle(cells, seedKey);" not in builder_body


def test_router_fx_cells_have_equal_prominence_and_hide_roster() -> None:
    # Every model cell must render identically; the panel must not reveal which
    # names are the operator's actually-configured (active) models. So the old
    # real/decoy visual distinction is gone (no breathing accent dot, no
    # dimmed/italic decoys) AND the DOM no longer carries data-kind/data-tiers.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    # No DOM attribute leaks the real/decoy split.
    assert "cell.dataset.kind" not in source
    assert "cell.dataset.tiers" not in source
    # No CSS differentiates real vs decoy cells; the "on the dial" dot is gone.
    assert '[data-kind="real"]' not in css
    assert '[data-kind="decoy"]' not in css
    assert "router-fx-dot-idle" not in css
    # Cells share one uniform colour; only the winner is emphasised.
    cell_start = css.index(".router-fx-cell {")
    cell_end = css.index("}", cell_start)
    assert "color: var(--text);" in css[cell_start:cell_end]
    assert ".router-fx-cell.win {" in css
    # Winner keeps a self-contained lock dot (no longer inherited from a
    # real-cell dot that no longer exists).
    win_after = css.index(".router-fx-cell.win::after {")
    win_after_end = css.index("}", win_after)
    assert "content: '';" in css[win_after:win_after_end]
    # Winner detection reads the in-memory grid-cell array, not a DOM attribute,
    # so it still lands on the routed cell without exposing the rest. Pin the
    # predicate (reads .kind off the array) and the cell-idx stamping that the
    # positional DOM lookup relies on — so a refactor that broke landing fails.
    assert "const cells = wrap._fxGridCells || [];" in source
    assert "cells[i].kind === 'real'" in source
    assert "cell.dataset.cellIdx = String(i);" in source


def test_router_fx_decoy_pool_doubled_with_current_models() -> None:
    # Roster expanded to >= 2x the previous 16, sourced from OpenRouter's
    # highest-usage models (ordered by volume, highest first).
    source = CHAT_JS.read_text(encoding="utf-8")
    pool_start = source.index("const _ROUTER_FX_DECOY_POOL = [")
    pool_end = source.index("];", pool_start)
    pool = source[pool_start:pool_end]
    names = re.findall(r"'([^']+)'", pool)
    assert len(names) >= 32, f"expected >= 32 pooled models, found {len(names)}"
    # Ordered by usage, highest first — the documented #1 leads.
    assert names[0] == "deepseek-v4-flash"
    for name in ("claude-sonnet-4.6", "glm-5.1", "qwen3.6-plus"):
        assert name in names


def test_router_fx_cloud_variant_renders_seeded_depth_field() -> None:
    # The cloud variant builds a focal-depth nebula: each mote gets a seeded
    # depth driving blur/scale/opacity TOGETHER (coherent optical depth, not a
    # random tag cloud), deterministic per layout seed for history rebuilds.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _routerFxBuildCloud(wrap, decision, seedKey) {" in source
    build_start = source.index("function _routerFxBuildCloud(wrap, decision, seedKey) {")
    build_end = source.index("function _settleRouterFxCloud(wrap) {", build_start)
    body = source[build_start:build_end]
    # Seeded RNG keyed off the layout seed → reproducible nebula.
    assert "_routerFxMulberry32(_routerFxHashSeed((seedKey || '') + ':cloud'))" in body
    # blur, scale, opacity all derive from the same depth d.
    assert "const d = rng();" in body
    assert "const blur = (d * 3.4).toFixed(2);" in body
    assert "const scale = (1.22 - d * 0.62).toFixed(3);" in body
    assert "const op = (0.92 - d * 0.64).toFixed(3);" in body
    # Organic elliptical scatter (area-uniform radius at a random angle).
    assert "const rad = Math.sqrt(rng());" in body
    assert "Math.cos(ang)" in body and "Math.sin(ang)" in body
    # Two layers so drift (outer) and rack-focus (inner) never fight.
    assert "inner.className = 'router-fx-mote-i';" in body
    assert "mote.appendChild(inner);" in body
    assert "mote.classList.add('router-fx-mote--winner');" in body
    assert "wrap._fxCloud = true;" in body
    assert "wrap._fxWinnerEl = winnerEl;" in body
    # Builder branches to the cloud and returns before the grid build.
    assert "if (variant === 'cloud') {" in source
    assert "_routerFxBuildCloud(wrap, decision, seedKey);" in source


def test_router_fx_cloud_shows_pool_plus_winner_not_roster() -> None:
    # Privacy: the cloud field is the public decoy pool + the (already-public)
    # routed winner only — it must NOT render the operator's configured roster.
    source = CHAT_JS.read_text(encoding="utf-8")
    build_start = source.index("function _routerFxBuildCloud(wrap, decision, seedKey) {")
    build_end = source.index("function _settleRouterFxCloud(wrap) {", build_start)
    body = source[build_start:build_end]

    assert "_ROUTER_FX_DECOY_POOL.forEach(" in body
    assert "const winnerName = _routerFxWinnerName(decision);" in body
    # The roster builder is never consulted inside the cloud build.
    assert "_routerFxRealEntries" not in body
    assert "function _routerFxWinnerName(decision) {" in source


def test_router_fx_cloud_rack_focus_dispatch_is_motion_opt_in() -> None:
    # Live + history dispatch branch on wrap._fxCloud; the rack-focus is a
    # defocus(playing) -> snap(settled) phase flip. The animation is an
    # explicit opt-in (the toggle), so it does NOT gate on OS reduce-motion;
    # it only settles directly when there is no winner to focus.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _animateRouterFxCloud(wrap) {" in source
    assert "function _settleRouterFxCloud(wrap) {" in source
    anim_start = source.index("function _animateRouterFxCloud(wrap) {")
    anim_end = source.index("// Anchor invariant", anim_start)
    anim = source[anim_start:anim_end]
    assert "if (!wrap._fxWinnerEl) { _settleRouterFxCloud(wrap); return; }" in anim
    assert "prefers-reduced-motion" not in anim   # decoupled from OS reduce-motion
    assert "wrap.dataset.state = 'playing';" in anim
    assert "wrap.dataset.state = 'settled';" in anim
    assert anim.index("'playing'") < anim.index("'settled'")
    # Live path dispatches to the cloud animator when the strip is a cloud.
    assert "wrap._fxCloud" in source
    assert "? _animateRouterFxCloud(wrap)" in source
    assert "? _settleRouterFxCloud(wrap)" in source


def test_router_fx_cloud_css_rack_focus_states() -> None:
    css = CHAT_CSS.read_text(encoding="utf-8")

    # Borderless/organic: no rigid box — a radial mask dissolves the edges,
    # and content-visibility keeps off-screen history strips cheap.
    cloud_start = css.index('.router-fx[data-variant="cloud"] .router-fx-cloud {')
    cloud_block = css[cloud_start:css.index("}", cloud_start)]
    assert "border:" not in cloud_block          # no rigid rectangular boundary
    assert "mask-image: radial-gradient(" in cloud_block
    # content-visibility was removed — it paused animation on auto-scroll.
    assert "content-visibility" not in cloud_block
    # Two layers: OUTER owns position + (winner) glide; INNER owns the optics.
    # NO perpetual motion — the panel must be still once settled / when output
    # renders (the absolute red line), so there is no drift/breathe loop.
    mote_start = css.index('.router-fx[data-variant="cloud"] .router-fx-mote {')
    mote_block = css[mote_start:css.index("}", mote_start)]
    assert "animation:" not in mote_block               # no perpetual drift
    assert "will-change" not in mote_block              # not pinned permanently (perf)
    assert "@keyframes router-fx-drift" not in css      # drift loop removed
    assert "router-fx-winner-breathe" not in css        # breathe loop removed
    assert '.router-fx[data-variant="cloud"] .router-fx-mote-i {' in css
    # Defocus (ease-IN) and the winner resolve target the INNER; the winner's
    # glide to focus is on the OUTER (left/top), so it travels, never teleports.
    assert '.router-fx[data-variant="cloud"][data-state="playing"] .router-fx-mote-i {' in css
    assert ('.router-fx[data-variant="cloud"][data-state="settled"] '
            '.router-fx-mote--winner .router-fx-mote-i {') in css
    assert '.router-fx[data-variant="cloud"] .router-fx-reticle {' in css
    # Output start no longer freezes the winner-lock animation; once settled,
    # the grid hides only the chase hammer.
    assert '.router-fx[data-frozen="true"]' not in css
    selector_hide = (".router-fx[data-state=\"settled\"] .router-fx-selector"
                     " { opacity: 0 !important; }")
    assert selector_hide in css
    # Motion is opt-in via the toggle, so the cloud does NOT honour OS
    # reduce-motion (no @media block suppressing the cloud motes).
    assert "deliberately does NOT honour prefers-reduced-motion" in css


def test_router_fx_cloud_view_toggle_selects_variant() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    popover_start = source.index('id="chat-toolbar-popover"')
    popover_end = source.index("chat-input-wrap", popover_start)
    popover = source[popover_start:popover_end]

    assert 'id="toggle-router-cloud"' in popover
    assert "Cloud view" in popover
    # Handler flips the persisted variant client-side and re-renders.
    assert "_routerFx.variant = routerCloudToggle.checked ? 'cloud' : 'default';" in source
    assert "routerCloudToggle.checked = _routerFx.variant === 'cloud';" in source


def test_router_fx_grid_labels_shrink_to_fit() -> None:
    # Long model names (e.g. "gemini-3.1-flash-lite") must show in full, not
    # clip at the cell edges: a post-insert measure shrinks the label font to
    # fit its cell. Runs for every inserted strip via _routerFxInsertAnchored.
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _routerFxFitLabels(wrap) {" in source
    fit_start = source.index("function _routerFxFitLabels(wrap) {")
    fit_end = source.index("function _routerFxInsertAnchored(", fit_start)
    fit = source[fit_start:fit_end]
    assert "wrap.querySelectorAll('.router-fx-cell')" in fit
    assert "const w = nm.scrollWidth;" in fit
    assert "nm.style.fontSize = Math.max(7, base * (avail / w)).toFixed(1) + 'px';" in fit
    # Invoked from the shared insert path so both live and history strips fit.
    insert_start = source.index("function _routerFxInsertAnchored(")
    insert_end = source.index("}", source.index("_thread.appendChild(wrap);", insert_start))
    assert "_routerFxFitLabels(wrap);" in source[insert_start:insert_end]


def test_router_fx_watching_indicator_deferred_until_panel_settles() -> None:
    # The "squilla · Watching · N.Ns" indicator is RETAINED, but DEFERRED until
    # the router panel has settled — so routing animates first and "Watching…"
    # only shows afterwards (while the model is still generating). The timer
    # starts at send so it reads total elapsed.
    source = CHAT_JS.read_text(encoding="utf-8")
    # No longer suppressed.
    assert "if (_routerFx.enabled && _routerFeatureEnabled) return;" not in source
    # _showThinkingIndicatorNow defers while the panel is still scanning.
    now_start = source.index("function _showThinkingIndicatorNow() {")
    now_end = source.index("function _hideThinkingIndicator", now_start)
    body = source[now_start:now_end]
    assert "_thread.querySelector('.router-fx[data-scanning=\"true\"]')" in body
    assert "_thinkingDelayTimer = setTimeout(_showThinkingIndicatorNow, 150);" in body
    # The verb list (incl. "Watching") is unchanged.
    assert "const SQUILLA_VERBS = ['Watching'," in source


def test_router_fx_scan_to_lock_fills_the_wait() -> None:
    # The routing visualisation renders on SEND and animates continuously
    # (JS-driven, ~170ms class/position swaps) until the decision locks it onto
    # the winner — so the routing animation leads instead of trailing, and it
    # shows regardless of CSS-animation suppression in the environment.
    source = CHAT_JS.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8")

    for fn in ("_routerFxBeginScan", "_routerFxScanRoam", "_routerFxStopScan",
               "_routerFxLock", "_routerFxLockCloud", "_routerFxLockGrid"):
        assert f"function {fn}(" in source
    # Scan is gated on BOTH the viz pref and routing actually being on.
    begin_start = source.index("function _routerFxBeginScan(")
    begin_end = source.index("function _routerFxScanRoam(", begin_start)
    begin = source[begin_start:begin_end]
    assert "if (!_thread || !_routerFx.enabled || !_routerFeatureEnabled) {" in begin
    assert "_chatDiag('router_scan.skip'" in begin
    assert "return false;" in begin
    # Started from the send path.
    assert "const routerScanStarted = _routerFxBeginScan(userDiv, _routerFxResolveLayoutSeed(_sessionKey));" in source
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
    # Roam is JS-driven discrete swaps (cloud: .is-scan; grid: hammer hop).
    roam_start = source.index("function _routerFxScanRoam(")
    roam_end = source.index("function _routerFxStopScan(", roam_start)
    roam = source[roam_start:roam_end]
    assert "m.classList.toggle('is-scan', idx === i)" in roam
    assert "wrap._fxScanTimer = setTimeout(step, isCloud ? 170 : 190);" in roam
    # CSS gives the roaming focus a sharp accent pop.
    scan_css = ('.router-fx[data-variant="cloud"][data-state="scanning"] '
                '.router-fx-mote.is-scan .router-fx-mote-i {')
    assert scan_css in css


def test_router_fx_strip_survives_multistep_turn() -> None:
    # History reorder moves .msg nodes. The router strip is a sibling, so the
    # root fix is to move an attached strip together with its user message
    # instead of preserving a separate live-strip path inside _loadHistory().
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "delete settledStrip.dataset.live;" not in source
    assert "_routerFxFindAttachedStrip" not in source
    history_start = source.index("async function _loadHistory() {")
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
    assert "const keep = ownStrips.find((el) => el.dataset.routerIdentity === routerIdentity)" in history_body
    assert "delete keep.dataset.live;" in history_body


def test_router_decision_without_anchor_is_cached_for_history_replay() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "const _pendingRouterDecisions = new Map();" in source
    assert "function _cachePendingRouterDecision(payload)" in source
    assert "function _flushPendingRouterDecisions()" in source

    handler_start = source.index("async function _handleRouterDecision(payload)")
    handler_end = source.index("    // Resolve a seed that's deterministic", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "_cachePendingRouterDecision(payload);" in handler_body
    assert "_chatDiag('router_decision.cached_pending_anchor'" in source
    assert "_chatDiag('router_decision.skip.no_anchor_user'" not in handler_body

    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("function _appendHistoryDaySeparator", history_start)
    history_body = source[history_start:history_end]
    assert "_flushPendingRouterDecisions();" in history_body


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
    assert end_body.index("_stampHistoryElement(_streamBubble, '', 'assistant', cleanedText);") < end_body.index(
        "_markPendingFinalizedAssistantBubble(_streamBubble, cleanedText);"
    )

    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("function _appendHistoryDaySeparator", history_start)
    history_body = source[history_start:history_end]
    assert "_chatDiag('history.empty.keep_pending_finalized_assistant'" in history_body
    assert "if (_isPendingFinalizedAssistantBubble(el) && _historyStillWaitingForAssistant(messages)) return;" in history_body
    assert "_clearPendingFinalizedAssistantBubble();" in history_body


def test_generic_duplicate_stream_seq_is_classified_as_exact_handler_replay() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _eventHasSpecificSessionHandler(event)" in source
    wildcard_start = source.index("_unsubs.push(_rpc.on('*', (rawEvent, rawPayload) => {")
    wildcard_end = source.index("      if (event.startsWith('session.event.task_group.')) return;", wildcard_start)
    wildcard_body = source[wildcard_start:wildcard_end]
    assert "_eventHasSpecificSessionHandler(event)" in wildcard_body
    assert "_chatDiag('event.generic.skip.specific_handler_stream_seq'" in wildcard_body
    assert "_chatDiag('event.generic.drop.stream_seq'" in wildcard_body


def test_tool_summary_exposes_visible_running_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "function _setToolSummaryStatus(details, status)" in source
    build_start = source.index("function _buildToolCallDOM(")
    build_end = source.index("function _retitleToolCallDOM", build_start)
    build_body = source[build_start:build_end]
    assert "statusSpan.className = 'chat-tools-status';" in build_body
    assert "statusSpan.textContent = isRunning ? 'running' : 'ready';" in build_body
    result_start = source.index("function _appendToolResult(payload)")
    result_end = source.index("  // \u2500\u2500 PR5: meta-skill user_input form rendering", result_start)
    result_body = source[result_start:result_end]
    assert "_setToolSummaryStatus(details, isError ? 'error' : 'done');" in result_body


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


def test_router_fx_history_and_turn_meta_preserve_observe_rollout_state() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    history_start = source.index("function _buildRouterFxFromUsage(usage, seedKey) {")
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


def test_router_fx_mobile_grid_matches_explicit_cell_count() -> None:
    """Mobile router-fx grid rows×cols stays in lockstep with the JS cell count.

    The JS constant ``_ROUTER_FX_GRID_CELLS`` is 15 (5 cols × 3 rows on desktop);
    mobile and tiny breakpoints collapse to 3×5 so no row ends short.
    """
    css = CHAT_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 640px)")
    tiny_start = css.index("@media (max-width: 380px)")
    mobile_body = css[mobile_start:tiny_start]
    tiny_body = css[tiny_start:]

    assert "grid-template-columns: repeat(3, 1fr);" in mobile_body
    assert "grid-template-rows: repeat(5, 28px);" in mobile_body
    assert "grid-template-columns: repeat(3, 1fr);" in tiny_body
    assert "grid-template-rows: repeat(5, 26px);" in tiny_body


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
    variant_apply = (
        "if (typeof saved.variant === 'string' && saved.variant) "
        "_routerFx.variant = saved.variant;"
    )
    assert variant_apply in load_body
    assert "} catch { /* keep defaults */ }" in load_body

    # Save path: serialize the live pref and swallow quota/availability throws.
    save_start = load_end
    save_end = source.index("function _routerFxSortTiers(", save_start)
    save_body = source[save_start:save_end]
    assert "localStorage.setItem(_ROUTER_FX_PREF_KEY, JSON.stringify({" in save_body
    assert "enabled: _routerFx.enabled," in save_body
    assert "variant: _routerFx.variant," in save_body
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
    assert "UI.toast('Router animation: '" in fx_body


def test_router_fx_render_gated_in_both_live_and_history_paths() -> None:
    # The visualisation pref gates RENDER in both the live (router_decision) and
    # history (rebuild) paths, ahead of all test-pinned lines. Tier/model
    # bookkeeping stays warm in the live path; the gate sits after it and before
    # the config await so a disabled panel short-circuits the 1.5s wait too.
    source = CHAT_JS.read_text(encoding="utf-8")
    handler_start = source.index("async function _handleRouterDecision(payload) {")
    handler_end = source.index("  // History-load entry point", handler_start)
    handler_body = source[handler_start:handler_end]

    pre_gate = "if (!_routerFx.enabled) {\n      _chatDiag('router_decision.skip.disabled_pre_config'"
    post_gate = "if (!_routerFx.enabled) {\n      _chatDiag('router_decision.skip.disabled_post_config'"
    assert pre_gate in handler_body
    assert post_gate in handler_body
    assert handler_body.index("_routerFxModels[tier.toLowerCase()] = String(payload.model);") < \
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

    assert "_thread.querySelectorAll('.router-fx').forEach((n) => n.remove());" in source
    assert ".router-fx:not([data-live=\"true\"])" not in source
    history_start = source.index("async function _loadHistory() {")
    history_end = source.index("  /* ── Send Message", history_start)
    history_body = source[history_start:history_end]
    assert "if (!_routerFx.enabled) {" in history_body
    sweep = history_body[history_body.index("if (!_routerFx.enabled) {"):]
    sweep = sweep[: sweep.index("_lastSavingsPopupIdentity")]
    assert "_thread.querySelectorAll('.router-fx').forEach((el) => el.remove());" in sweep
    assert "dataset.live" not in sweep


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
    assert "Router animation" in popover
    assert 'class="toggle-switch"' in popover
    assert popover.count('class="toggle-track"') >= 2


def test_chat_history_replays_turn_meta_to_restore_combo_streak() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory() {")
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
    assert "if (interrupted)" in helper
    assert "_popAllPendingIntoComposer();" in helper
    assert (
        "if (_isStreaming || _isCompactInFlightForCurrentSession() || "
        "_pendingQueue.length === 0) return;"
        in scheduler
    )
    assert "_drainQueueHead();" in scheduler


def test_chat_ignores_replayed_compaction_toasts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "if (meta && meta.replayed) return;" in body
    assert body.index("meta.replayed") < body.index("'Compact failed'")


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
    start = source.index("async function _loadHistory() {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "function _historyStableMessageIdentity(msg)" in source
    assert "function _historyElementFallbackIdentity(el)" in source
    assert "function _historyFallbackText(role, text)" in source
    assert "const existingByStableIdentity = new Map();" in body
    assert "const existingByFallbackIdentity = new Map();" in body
    assert "const consumedHistoryElements = new Set();" in body
    assert "data-message-id" in source
    assert "_stampHistoryElement(div, stableIdentity, msg.role, displayText);" in body
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
    start = source.index("async function _loadHistory() {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "_thread.querySelectorAll('.chat-day-sep').forEach((el) => el.remove());" in body
    assert "function _appendHistoryElementInOrder(div)" in source
    assert "if (_isStreaming && _isCurrentSessionStreamBubble(_streamBubble) && div !== _streamBubble)" in source
    assert "_thread.insertBefore(div, _streamBubble);" in source
    assert "_thread.appendChild(div);" in source
    stamp_idx = body.index("_stampHistoryElement(div, stableIdentity, msg.role, displayText);")
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


def test_approvals_view_sends_auth_headers() -> None:
    source = Path("src/opensquilla/gateway/static/js/views/approvals.js").read_text(
        encoding="utf-8"
    )

    assert "function _authHeaders(extra)" in source
    assert "App.getAuthToken" in source
    assert "headers['Authorization'] = `Bearer ${token}`;" in source
    assert "fetch('/api/approvals', { headers: _authHeaders() })" in source
    assert "headers: _authHeaders({ 'Content-Type': 'application/json' })" in source


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
