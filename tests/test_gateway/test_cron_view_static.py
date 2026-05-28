from pathlib import Path

CRON_JS = Path("src/opensquilla/gateway/static/js/views/cron.js")
CRON_CSS = Path("src/opensquilla/gateway/static/css/views/cron.css")


def test_new_cron_jobs_default_to_static_reminders() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "localStorage.getItem('opensquilla_active_session')" in source
    assert '<option value="current">Current chat session</option>' in source
    assert "tpl.payloadKind || 'reminder'" in source
    assert "payloadKind === 'system_event' ? 'main' : 'isolated'" in source


def test_current_session_cron_payload_binds_target_and_origin_session() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "if (sessionTarget === 'current')" in source
    assert "payload.sessionKey = boundSessionKey;" in source
    assert "payload.targetSessionKey = boundSessionKey;" in source
    assert "payload.originSessionKey = boundSessionKey;" in source


def test_editing_cron_jobs_prefers_origin_before_target_session_key() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    origin_idx = source.index("job.originSessionKey")
    target_idx = source.index("job.targetSessionKey")
    session_idx = source.index("job.sessionKey")
    assert origin_idx < target_idx < session_idx


def test_editing_cron_jobs_uses_stable_panel_title_for_long_names() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "title.textContent = job ? 'Edit Schedule' : 'Create a job';" in source
    assert "title.textContent = job ? (job.name || job.id) : 'Create a job';" not in source
    assert "_el.querySelector('#cp-name').value = name;" in source


def test_agent_turn_session_target_does_not_remain_main_after_mode_switch() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "if (target === 'main')" in source
    assert "target = activeSessionKey ? 'current' : 'isolated';" in source
    assert "targetSelect.value = target;" in source


def test_cron_form_explains_main_vs_agent_task_session_targets() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "Static Reminder (no model)" in source
    assert "Background Agent Task (choose session)" in source
    assert "Static reminders deliver text directly" in source
    assert "Main is locked for system events." in source
    assert "runs in its own cron session, separate from Main" in source
    assert 'placeholder="agent:main:webchat:abc123"' in source


def test_cron_form_exposes_timezone_and_advanced_delivery() -> None:
    """Timezone field + Advanced fold (wake/delivery/failure-destination)
    must be present in the panel so the WebUI can reach scheduler features
    that the RPC and CLI already expose."""
    source = CRON_JS.read_text(encoding="utf-8")

    assert 'id="cp-tz"' in source
    assert 'id="cp-wake-mode"' in source
    assert 'id="cp-delivery-mode"' in source
    assert 'id="cp-delivery-webhook-url"' in source
    assert 'id="cp-delivery-best-effort"' in source
    assert 'id="cp-fd-mode"' in source
    assert 'id="cp-fd-webhook-url"' in source
    assert 'class="cron-advanced"' in source

    # _saveJob must forward the new fields onto the wire payload.
    assert "payload.tz = tz" in source
    assert "payload.wakeMode = wakeMode" in source
    assert "payload.delivery = delivery" in source


def test_cron_form_exposes_all_schedule_kinds_and_sends_schedule_object() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert '<option value="cron">Cron expression</option>' in source
    assert '<option value="every">Fixed interval</option>' in source
    assert '<option value="at">One-time ISO time</option>' in source
    assert "payload.schedule = { kind: 'cron'" in source
    assert "payload.schedule = { kind: 'every'" in source
    assert "payload.schedule = { kind: 'at'" in source
    assert "Only cron expressions are supported currently" not in source


def test_cron_countdowns_ignore_running_and_past_next_runs() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "function _isUpcomingRun(j, now = Date.now())" in source
    assert "if (j.status === 'running')" in source
    assert "ts.getTime() > now" in source
    assert ".filter(j => _isUpcomingRun(j))" in source
    assert "o.ts > Date.now()" in source


def test_cron_finished_event_refreshes_after_scheduler_state_persists() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "_scheduleCronReload()" in source
    assert "setTimeout(_loadData, 750)" in source


def test_cron_view_toggle_keeps_touch_friendly_hit_area() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    start = css.index(".cron-view-toggle__btn {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_cron_active_view_toggle_uses_theme_contrast_token() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    start = css.index(".cron-view-toggle__btn.is-active {")
    rule = css[start : css.index("}", start)]

    assert "color: var(--accent-foreground)" in rule


def test_cron_search_keeps_touch_friendly_hit_area() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    start = css.index(".cron-search-input {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_cron_cards_wrap_long_names_and_runtime_metadata() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    name_start = css.index(".cron-card__name {")
    name_rule = css[name_start : css.index("}", name_start)]
    meta_start = css.index(".cron-card__meta {")
    meta_rule = css[meta_start : css.index("}", meta_start)]
    value_start = css.index(".cron-card__meta dd {")
    value_rule = css[value_start : css.index("}", value_start)]

    assert "white-space: normal" in name_rule
    assert "overflow-wrap: anywhere" in name_rule
    assert "text-overflow: clip" in name_rule
    assert "repeat(auto-fit, minmax(140px, 1fr))" in meta_rule
    assert "max-width: 100%" in value_rule
    assert "min-width: 0" in value_rule
    assert "white-space: normal" in value_rule
    assert "overflow-wrap: anywhere" in value_rule
    assert "text-overflow: clip" in value_rule


def test_cron_mobile_actions_keep_search_usable() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 480px)")
    mobile_rule = css[mobile_start:]

    assert ".cron-stage__actions" in mobile_rule
    assert "display: grid" in mobile_rule
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in mobile_rule
    assert ".cron-search-wrap" in mobile_rule
    assert "grid-column: 1 / -1" in mobile_rule
    assert ".cron-stage__actions .btn" in mobile_rule
    assert "width: 100%" in mobile_rule
    assert "justify-content: center" in mobile_rule


def test_cron_empty_hints_keep_mobile_touch_targets() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width: 480px)")
    mobile_rule = css[mobile_start:]
    code_start = css.index(".cron-empty-hint code {")
    code_rule = css[code_start : css.index("}", code_start)]
    assert ".cron-empty-hint {" in mobile_rule
    hint_rule = mobile_rule[
        mobile_rule.index(".cron-empty-hint {") : mobile_rule.index(
            "}", mobile_rule.index(".cron-empty-hint {")
        )
    ]

    assert "min-height: 40px" in hint_rule
    assert "padding: 9px 14px" in hint_rule
    assert "white-space: nowrap" in code_rule


def test_cron_empty_hints_keep_desktop_hit_area() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    start = css.index(".cron-empty-hint {")
    rule = css[start : css.index("}", start)]

    assert "min-height: 40px" in rule


def test_cron_empty_hints_wrap_long_labels_inside_mobile_viewport() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")
    hints_start = css.index(".cron-empty__hints {")
    hints_rule = css[hints_start : css.index("}", hints_start)]
    hint_start = css.index(".cron-empty-hint {")
    hint_rule = css[hint_start : css.index("}", hint_start)]
    assert ".cron-empty-hint span {" in css
    label_start = css.index(".cron-empty-hint span {")
    label_rule = css[label_start : css.index("}", label_start)]

    assert "width: 100%" in hints_rule
    assert "max-width: 720px" in hints_rule
    assert "box-sizing: border-box" in hints_rule
    assert "max-width: 100%" in hint_rule
    assert "min-width: 0" in hint_rule
    assert "flex-wrap: wrap" in hint_rule
    assert "min-width: 0" in label_rule
    assert "overflow-wrap: anywhere" in label_rule


def test_cron_panel_actions_stay_reachable_on_mobile() -> None:
    css = CRON_CSS.read_text(encoding="utf-8")

    actions_start = css.index(".cron-panel__actions {")
    actions_rule = css[actions_start : css.index("}", actions_start)]
    assert "position: sticky" in actions_rule
    assert "bottom: calc(-1 * var(--sp-5))" in actions_rule
    assert "border-top: 1px solid var(--border)" in actions_rule

    mobile_start = css.index("@media (max-width: 480px)")
    mobile_rule = css[mobile_start:]
    assert ".cron-panel" in mobile_rule
    assert "width: 100vw" in mobile_rule
    assert "max-width: 100vw" in mobile_rule
    assert ".cron-panel__actions .btn" in mobile_rule
    assert "flex: 1 1 0" in mobile_rule
