from pathlib import Path

CRON_JS = Path("src/opensquilla/gateway/static/js/views/cron.js")


def test_new_cron_jobs_can_default_to_current_chat_session() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "localStorage.getItem('opensquilla_active_session')" in source
    assert '<option value="current">Current chat session</option>' in source
    assert "activeSessionKey ? 'agent_turn' : 'system_event'" in source
    assert "activeSessionKey ? 'current' : 'main'" in source


def test_current_session_cron_payload_binds_target_and_origin_session() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "if (sessionTarget === 'current')" in source
    assert "payload.sessionKey = boundSessionKey;" in source
    assert "payload.targetSessionKey = boundSessionKey;" in source
    assert "payload.originSessionKey = boundSessionKey;" in source


def test_cron_view_uses_domain_view_state_helper_for_session_targets() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "const CronDomainViewState = Object.freeze" in source
    assert "CronDomainViewState.defaultPayloadKind" in source
    assert "CronDomainViewState.defaultSessionTarget" in source
    assert "CronDomainViewState.jobSessionKey" in source
    assert "CronDomainViewState.bindCurrentSessionPayload" in source
    assert "WebUiRpc.client()" in source
    assert "App.getRpc(" not in source


def test_editing_cron_jobs_prefers_origin_before_target_session_key() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    origin_idx = source.index("job.originSessionKey")
    target_idx = source.index("job.targetSessionKey")
    session_idx = source.index("job.sessionKey")
    assert origin_idx < target_idx < session_idx


def test_agent_turn_session_target_does_not_remain_main_after_mode_switch() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "if (target === 'main')" in source
    assert "target = activeSessionKey ? 'current' : 'isolated';" in source
    assert "targetSelect.value = target;" in source


def test_cron_form_explains_main_vs_agent_task_session_targets() -> None:
    source = CRON_JS.read_text(encoding="utf-8")

    assert "Reminder / System Event (Main)" in source
    assert "Background Agent Task (choose session)" in source
    assert "Main is locked for reminders." in source
    assert "runs in its own cron session, separate from Main" in source
    assert 'placeholder="agent:main:webchat:abc123"' in source
