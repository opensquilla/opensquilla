from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
CHAT_CSS = Path("src/opensquilla/gateway/static/css/views/chat.css")
RPC_JS = Path("src/opensquilla/gateway/static/js/rpc.js")
SAVINGS_FX_JS = Path("src/opensquilla/gateway/static/js/components/savings-fx.js")


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
    assert "body.appendChild(_renderSubagentDisclosure(text));" in source
    assert "body.textContent = text;" in source


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
    assert "function _artifactPreviewUrl(artifact)" in source
    assert "class=\"msg-artifact-card msg-artifact-card--image\"" in render_body
    assert "<img class=\"msg-artifact-preview\"" in render_body
    assert "data-artifact-download" in render_body
    assert "_scheduleHistorySync();" in done_body
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
    assert 'label: \'New chat\'' in source
    assert 'title="New chat session in the current agent"' in source
    assert "New chat session in the current agent: " in source


def test_chat_maps_task_terminal_events_during_migration() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "function _taskTerminalAsSessionEvent(event, payload)" in source
    assert "task.failed" in source
    assert "task.timeout" in source
    assert "task.abandoned" in source
    assert "task.cancelled" in source


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
    assert "function _noteStreamSeq(payload)" in source
    assert "Session stream gap detected; reloading transcript." in source


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
    assert (
        "_lastStreamSeq = typeof res.current_stream_seq === 'number' "
        "? res.current_stream_seq : 0;"
    ) in body
    assert body.index("_lastStreamSeq = typeof res.current_stream_seq") < body.index(
        "_loadHistory();"
    )


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

    assert "function _savedUsageFromMeta(meta) {" in source
    assert "function _turnSavingsIdentity(u) {" in source
    assert "if (window.SavingsFX) window.SavingsFX.resetStreak();" in body
    assert "let historySavingsIdentity = '';" in body
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
    start = source.index("_unsubs.push(_rpc.on('*'")
    end = source.index("    // Connection state changes", start)
    body = source[start:end]

    assert "function _scheduleHistorySync()" in source
    assert "payload?.reason === 'turn_complete'" in body
    assert "_scheduleHistorySync();" in body


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

    assert "if (role === 'assistant') return _stripDirectiveTags(text || '').trim();" in body


def test_chat_first_delta_marks_render_dirty_before_flush() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("function _appendDelta(text) {")
    end = source.index("  function _flushRender()", start)
    body = source[start:end]

    assert "_renderDirty = true;\n      _flushRender();" in body


def test_chat_history_replacement_preserves_message_body_rendering() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")
    replace_start = source.index("function _replaceHistoryMessage")
    replace_end = source.index("  /* ── Send Message", replace_start)
    replace_body = source[replace_start:replace_end]
    render_start = source.index("function _renderMessageBody")
    render_end = source.index("  function _scrollToBottom", render_start)
    render_body = source[render_start:render_end]

    assert "_renderMessageBody(body, role, text, options);" in replace_body
    assert "Markdown.render(_stripDirectiveTags(text))" in render_body
    assert "Markdown.bindHighlight(body);" in render_body


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
    assert "const usage = await _rpc.call('usage.status');" in body
    assert "Session API total" in source


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
