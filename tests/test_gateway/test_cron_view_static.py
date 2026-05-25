from pathlib import Path

CRON_JS = Path("src/opensquilla/gateway/static/js/views/cron.js")


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
