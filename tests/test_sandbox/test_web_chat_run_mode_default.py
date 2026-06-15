from __future__ import annotations

from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def test_web_chat_defaults_to_full_host_access() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_DEFAULT = 'full';" in source
    assert "Establish sandbox" not in source


def test_web_chat_run_mode_switch_is_not_setup_gated() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_requestSandboxSetupForMode" not in source
    assert "_ensureSandboxSetupOnly" not in source
    assert "_sandboxSetupReadyForMode" not in source
    assert "sandbox.setup.status" not in source
    assert "sandbox.setup.ensure" not in source
    assert "_setRunMode(mode, { toast: true, sync: true });" in source


def test_web_chat_run_context_failure_falls_back_to_sandbox_status() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    load_context = source.split("async function _loadRunContext()", 1)[1].split(
        "async function _syncRunMode",
        1,
    )[0]

    assert "async function _loadRunModeStatusFallback" in source
    assert "await _loadRunModeStatusFallback(sessionKey)" in load_context
    assert "_setRunMode(_RUN_MODE_DEFAULT, { toast: false, sync: false });" not in load_context
