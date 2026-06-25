from __future__ import annotations

from pathlib import Path

CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def test_web_chat_defaults_to_full_host_access() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "const _RUN_MODE_DEFAULT = 'full';" in source
    assert "Establish sandbox" in source


def test_web_chat_run_mode_switch_uses_setup_gate_for_sandbox_modes() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_requestSandboxSetupForMode" in source
    assert "_ensureSandboxSetupOnly" in source
    assert "_sandboxSetupReadyForMode" in source
    assert "sandbox.setup.status" in source
    assert "sandbox.setup.ensure" in source
    assert "if (mode === 'full') return true;" in source
    assert "if (!(await _requestSandboxSetupForMode(mode))) return;" in source


def test_web_chat_run_mode_is_not_loaded_from_gateway_or_session_context() -> None:
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_loadRunModeStatusFallback" not in source
    assert "sandbox.status" not in source
    assert "_loadRunContext" not in source
    assert "_syncRunMode" not in source
    assert "sandbox.run_context.get" not in source
    assert "sandbox.run_context.set" not in source
