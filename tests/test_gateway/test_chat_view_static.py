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
    streaming_idx = send_prefix.index("if (_isStreaming) {")
    execute_idx = send_prefix.index("await _executeSlashCommand(text)")
    real_slash_guard = "if (!isLiteralSlash && text.startsWith('/')) {"
    streaming_block_end = send_prefix.index(f"\n\n    {real_slash_guard}", streaming_idx)
    streaming_block = send_prefix[streaming_idx:streaming_block_end]

    assert flag_idx < literal_idx < streaming_idx
    assert literal_idx < flag_set_idx < streaming_idx
    assert "text = text.slice(1);" in send_prefix[literal_idx:streaming_idx]
    assert real_slash_guard in streaming_block
    assert "Wait for the current response before running" in streaming_block
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
    assert "params.since_stream_seq = _lastStreamSeq;" in source
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
    assert "_lastStreamSeq = typeof res.current_stream_seq === 'number'" in body
    assert "? Math.max(_lastStreamSeq, res.current_stream_seq)" in body
    assert ": _lastStreamSeq;" in body
    assert body.index("_lastStreamSeq = typeof res.current_stream_seq") < body.index(
        "_loadHistory();"
    )


def test_chat_empty_history_preserves_live_stream_bubble() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory() {")
    end = source.index("      const existingByStableIdentity = new Map();", start)
    body = source[start:end]

    assert "if (_isStreaming && _streamBubble)" in body
    assert "_thread.appendChild(_streamBubble);" in body
    assert "return;" in body[body.index("if (_isStreaming && _streamBubble)") :]


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


def test_chat_surfaces_compaction_outcome_toasts_without_noop_chatter() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    compact_block = source[
        source.index("case 'compact_context':") : source.index("case 'usage_status':")
    ]
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "Checking whether compaction is needed..." not in compact_block
    assert "Checking whether compaction is needed..." not in body
    assert "No compaction needed" not in body
    assert "_showCompactionToast({ ...(result || {}), source: 'manual'" not in compact_block
    assert "session.event.compaction" in source
    assert "Context compacted older messages to keep this session within budget" in source
    assert "Compact cancelled" in source


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

    assert "UI.toast(" not in skipped_block
    assert "No compaction needed' + details" not in skipped_block
    assert "payload && payload.tokens_after || 0" not in stats_body
    assert body.index("_compactionTokenStats(payload || {})") > body.index(
        "if (status === 'cancelled')"
    )


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


def test_chat_ignores_replayed_compaction_toasts() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _showCompactionToast(payload, meta = {})")
    end = source.index("  /* ── RPC Event Subscriptions", start)
    body = source[start:end]

    assert "function _showCompactionToast(payload, meta = {})" in source
    assert "if (meta && meta.replayed) return;" in body
    assert body.index("meta.replayed") < body.index("UI.toast('Compact failed'")


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
    assert "if (_isStreaming && el === _streamBubble) return;" in body
    assert "if (!consumedHistoryElements.has(el)) el.remove();" in body


def test_chat_history_reorders_reused_nodes_to_match_transcript_order() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("async function _loadHistory() {")
    end = source.index("  /* ── Send Message", start)
    body = source[start:end]

    assert "_thread.querySelectorAll('.chat-day-sep').forEach((el) => el.remove());" in body
    assert "function _appendHistoryElementInOrder(div)" in source
    assert "if (_isStreaming && _streamBubble && div !== _streamBubble)" in source
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
