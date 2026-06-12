"""meta-ribbon.js DOM 渲染契约（静态 / 基于读文件 + 简易 string assert）。

完整 DOM 行为由 E2E browser 测试覆盖；本测试锁结构与字符串。
"""

from pathlib import Path

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")
PREFLIGHT_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-preflight.js")
ARTIFACT_CARD_JS = Path("src/opensquilla/gateway/static/js/views/chat/artifact-card.js")
META_RUN_HISTORY_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-run-history.js")
RIBBON_CSS = Path("src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css")
CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")
INDEX_HTML = Path("src/opensquilla/gateway/templates/index.html")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ribbon_module_exists():
    assert RIBBON_JS.exists()
    text = _read_text(RIBBON_JS)
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert f"function {name}" in text, f"missing function {name}"


def test_ribbon_exposes_window_global():
    text = _read_text(RIBBON_JS)
    assert "root.MetaRibbon" in text or "window.MetaRibbon" in text


def test_ribbon_state_classes_are_normalized():
    text = _read_text(RIBBON_JS)

    assert "step.state = normalizeStateClass(stepStateEvent.state);" in text
    assert "state.runOutcome = normalizeRunOutcome(completedEvent.outcome);" in text
    assert "function normalizeRunOutcome" in text
    assert "outcome === 'ok'" in text
    assert "const safeStepState = normalizeStateClass(s.state);" in text
    assert 'class="chip ${safeStepState}"' in text
    assert "STATE_GLYPH[state]" in text
    assert "'substituted'," in text
    assert "paused: 'Ⅱ'" in text
    assert "cancelled: '−'" in text
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert name in text, f"window.MetaRibbon missing {name}"


def test_ribbon_glyph_table_covers_all_states():
    text = _read_text(RIBBON_JS)
    for state in (
        "pending",
        "running",
        "succeeded",
        "failed",
        "skipped",
        "substituted",
        "paused",
        "cancelled",
    ):
        assert f"{state}:" in text, f"STATE_GLYPH missing {state}"


def test_ribbon_css_has_chip_state_classes():
    text = _read_text(RIBBON_CSS)
    for cls in (
        "chip.pending",
        "chip.running",
        "chip.succeeded",
        "chip.failed",
        "chip.skipped",
        "chip.substituted",
        "chip.paused",
        "chip.cancelled",
    ):
        assert cls in text, f"CSS missing {cls}"


def test_ribbon_renders_accessible_compact_run_bar():
    js = _read_text(RIBBON_JS)
    css = _read_text(RIBBON_CSS)
    for token in (
        "meta-ribbon-shell",
        "meta-ribbon-icon",
        "meta-ribbon-current",
        "meta-ribbon-track",
        "meta-ribbon-fill",
        "progressPercent",
        "role=\"progressbar\"",
        "aria-valuenow",
        "aria-valuemin=\"0\"",
        "aria-valuemax=\"100\"",
        "aria-live=\"polite\"",
        "aria-expanded",
    ):
        assert token in js, f"ribbon render missing {token}"
    assert "MetaSkill</span>" not in js
    assert "const counterText = copy.counter(headerIndex, state.total);" in js
    for token in (
        "max-width: min(760px, 100%)",
        "margin: 10px auto",
        ".meta-ribbon-track",
        ".meta-ribbon-fill",
        "height: 2px",
        "box-shadow: 0 1px 2px",
        "prefers-reduced-motion: reduce",
    ):
        assert token in css, f"ribbon CSS missing polished progress treatment {token}"
    assert "min-width: 6px" not in css, "0% progress should not render a fake leading fill"


def test_preflight_uses_checkpoint_language_not_generic_confirmation():
    text = _read_text(PREFLIGHT_JS)
    assert "我准备运行" in text
    assert "开始运行" in text
    assert "Confirmation" not in text


def test_preflight_chrome_follows_request_language():
    text = _read_text(PREFLIGHT_JS)
    for token in (
        "detectLanguage",
        "preflightCopy",
        "state.language",
        "Before running",
        "I understood",
        "Start",
        "Cancel",
        "Use defaults",
        "Required",
        "Please fill this in.",
    ):
        assert token in text, f"preflight missing localized chrome token {token}"


def test_ribbon_chrome_follows_request_language():
    text = _read_text(RIBBON_JS)
    for token in (
        "language: detectLanguage(announce.language",
        "ribbonCopy(state.language)",
        "Collapse/expand steps",
        "Step ${index} of ${total}",
        "第 ${index} / ${total} 步",
        "Running…",
        "Retry whole run",
        "Switch meta-skill…",
        "View error details",
    ):
        assert token in text, f"ribbon missing localized chrome token {token}"


def test_preflight_collects_missing_fields_inline_instead_of_editing_composer():
    preflight = _read_text(PREFLIGHT_JS)
    chat = _read_text(CHAT_JS)
    for token in (
        "renderMissingFields",
        "collectFieldValues",
        "validateRequiredFields",
        "renderCollapsed",
        "setSubmitting",
        "setError",
        "meta-preflight-field",
        "data-field-name",
        "使用默认值运行",
        "取消",
        "知道了",
        "Dismiss",
    ):
        assert token in preflight, f"preflight missing inline field behavior {token}"
    assert 'data-action="edit"' not in preflight
    assert "补充到输入框" not in preflight
    assert "补充：" not in chat
    assert "renderCollapsed(card, detail, 'running')" in chat
    assert "setSubmitting(card, true)" in chat
    assert "setError(card, err" in chat


def test_index_html_loads_ribbon_before_chat():
    text = _read_text(INDEX_HTML)
    ribbon_pos = text.find("chat/meta-ribbon.js")
    preflight_pos = text.find("chat/meta-preflight.js")
    artifact_card_pos = text.find("chat/artifact-card.js")
    history_pos = text.find("chat/meta-run-history.js")
    chat_pos = text.find("views/chat.js")
    assert ribbon_pos != -1, "meta-ribbon.js not included"
    assert preflight_pos != -1, "meta-preflight.js not included"
    assert artifact_card_pos != -1, "artifact-card.js not included"
    assert history_pos != -1, "meta-run-history.js not included"
    assert chat_pos != -1, "chat.js not included"
    assert ribbon_pos < chat_pos, "meta-ribbon.js must load before chat.js"
    assert preflight_pos < chat_pos, "meta-preflight.js must load before chat.js"
    assert artifact_card_pos < chat_pos, "artifact-card.js must load before chat.js"
    assert history_pos < chat_pos, "meta-run-history.js must load before chat.js"


def test_index_html_loads_ribbon_css():
    text = _read_text(INDEX_HTML)
    assert "chat-meta-ribbon.css" in text


def test_chat_js_references_window_metaribbon():
    text = _read_text(CHAT_JS)
    assert "window.MetaRibbon" in text
    for name in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert name in text, f"chat.js missing {name} reference"


def test_preflight_module_exists():
    assert PREFLIGHT_JS.exists()
    text = _read_text(PREFLIGHT_JS)
    for name in ("createPreflight", "renderPreflight"):
        assert f"function {name}" in text, f"missing function {name}"
    assert "root.MetaPreflight" in text or "window.MetaPreflight" in text
    assert "我准备运行" in text
    assert 'data-action="continue"' in text
    assert 'data-action="dismiss"' in text
    assert "requiresGate: payload.requires_confirmation === true" in text
    assert "state.requiresGate ? copy.cancel : copy.dismiss" in text
    assert "state.requiresGate ? renderMissingFields(state) : ''" in text
    assert "fieldOptions(field)" in text
    assert "Array.isArray(field.choices)" in text
    assert "input.type !== 'checkbox'" in text


def test_clarify_form_enum_options_display_localized_labels():
    text = _read_text(CHAT_JS)
    assert "const optionByValue = new Map();" in text
    assert "Array.isArray(field.options)" in text
    assert "localizedChoiceLabel(choiceValue, schemaLang)" in text
    assert '"PRE_K": "学龄前（3-5 岁）"' in text
    assert '"MODEST": "适中预算"' in text


def test_chat_js_references_window_metapreflight():
    text = _read_text(CHAT_JS)
    assert "window.MetaPreflight" in text
    assert "session.event.meta_preflight" in text
    assert "_insertMetaPreflightElement" in text
    assert "meta-preflight-action" in text
    assert "meta_preflight_confirmed" in text
    assert "meta_preflight_run_id=${runId}" in text


def test_chat_pending_queue_keeps_hidden_preflight_control_out_of_composer():
    text = _read_text(CHAT_JS)

    assert "hiddenControl: preserveComposer === true" in text
    assert "if (head.hiddenControl)" in text
    assert "_sendTextOverride = head.text || '';" in text
    assert "tail.hiddenControl" in text
    assert "? (tail.displayText || '')" in text


def test_artifact_card_module_exists():
    assert ARTIFACT_CARD_JS.exists()
    text = _read_text(ARTIFACT_CARD_JS)
    assert "function renderArtifacts" in text
    assert "root.ArtifactCard" in text or "window.ArtifactCard" in text
    for label in ("Open", "Download"):
        assert label in text
    for field in ("name", "mime", "size"):
        assert field in text


def test_meta_run_history_module_exists():
    assert META_RUN_HISTORY_JS.exists()
    text = _read_text(META_RUN_HISTORY_JS)
    assert "root.MetaRunHistory" in text or "window.MetaRunHistory" in text
    for method in (
        "meta.runs.list",
        "meta.runs.show",
        "meta.runs.draft",
        "meta.runs.diff",
        "meta.runs.replay",
        "meta.runs.failures",
        "meta.runs.cost",
        "meta.runs.validate",
    ):
        assert method in text
    for name in ("renderRunHistoryPanel", "openRunHistory"):
        assert f"function {name}" in text
    assert "showRunError" in text
    assert "catch (err)" in text
    assert "run.validation || {}" in text
    assert "validation.available === true" in text
    assert "Validation available" in text
    assert "Validation unavailable" in text
    assert "meta-run-history__validate" in text
    for action in ("diff", "replay", "failures", "cost", "validate"):
        assert f"data-action=\"{action}\"" in text


def test_chat_js_renders_stream_artifacts_with_artifact_card_module():
    text = _read_text(CHAT_JS)
    assert "window.ArtifactCard" in text
    assert "renderArtifacts" in text
    assert "session.event.artifact" in text


def test_chat_js_references_meta_run_history_launcher():
    text = _read_text(CHAT_JS)
    assert "window.MetaRunHistory" in text
    assert "openRunHistory" in text
    assert "meta-run-history" in text
    assert "chat-btn-meta-history" in text
    assert "MetaSkill run history" in text
    assert "metaHistoryBtn.addEventListener('click', _openMetaRunHistory)" in text


def test_chat_js_uses_server_preflight_confirmation_rpc():
    text = _read_text(CHAT_JS)
    assert "meta.runs.confirm_preflight" in text
    assert "_confirmMetaPreflight" in text
    assert "confirmed.message" in text


def test_chat_js_dispatches_meta_events():
    text = _read_text(CHAT_JS)
    assert "session.event.meta_run_announced" in text
    assert "session.event.meta_step_state" in text
    assert "session.event.meta_run_completed" in text
    assert "_insertMetaRibbonElement" in text
    assert "insertBefore(el, _streamBubble)" in text


def test_chat_js_keeps_preflight_before_same_run_ribbon():
    text = _read_text(CHAT_JS)
    assert "_metaPreflightEl.get" in text
    assert "preflight.nextSibling" in text


def test_chat_js_handles_ribbon_action_events():
    text = _read_text(CHAT_JS)
    assert "meta-ribbon-action" in text
    for action in (
        "retry-run",
        "retry-step",
        "retry-with-partial-context",
        "switch-skill",
        "switch-meta-skill",
        "install-dependency",
        "continue-text-only",
        "show-detail",
    ):
        assert action in text, f"chat.js missing action {action}"
    assert "_retryMetaRibbonRun" in text
    assert "_replayMetaRibbonRun" in text
    assert "meta.runs.replay" in text
    assert "_onSend();" in text
