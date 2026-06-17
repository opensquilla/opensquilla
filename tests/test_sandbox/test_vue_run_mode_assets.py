from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "opensquilla-webui" / "src"
CHAT_VIEW = WEBUI / "views" / "ChatView.vue"
CHAT_COMPOSER = WEBUI / "components" / "chat" / "ChatComposer.vue"
CHAT_RUN_MODE = WEBUI / "components" / "chat" / "ChatRunModeMenu.vue"
CHAT_SEND = WEBUI / "composables" / "chat" / "useChatSend.ts"
CHAT_RUN_MODE_COMPOSABLE = WEBUI / "composables" / "chat" / "useChatRunMode.ts"
RPC_TYPES = WEBUI / "types" / "rpc.ts"
ICONS = WEBUI / "utils" / "icons.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_vue_composer_exposes_run_mode_picker_next_to_input() -> None:
    composer = _read(CHAT_COMPOSER)
    menu = _read(CHAT_RUN_MODE)
    icons = _read(ICONS)

    assert "ChatRunModeMenu" in composer
    assert ":run-mode=\"runMode\"" in composer
    assert "@set-run-mode=\"emit('setRunMode', $event)\"" in composer
    assert "sandboxSetupVisible" in composer
    assert "shield" in icons
    assert "Icon name=\"shield\"" in menu
    assert "Standard-Sandbox" in menu
    assert "Trusted-Sandbox" in menu
    assert "Full Host Access" in menu
    assert "composer-run-mode" in menu


def test_vue_run_mode_is_sent_as_chat_source_metadata() -> None:
    send = _read(CHAT_SEND)
    types = _read(RPC_TYPES)

    assert "runMode: Ref<RunMode>" in send
    assert "normalizeRunMode(options.runMode.value)" in send
    assert "params._source = { ...params._source, runMode }" in send
    assert "hiddenParams._source = { ...hiddenParams._source, runMode }" in send
    assert "_source?: { elevated?: string; runMode?: RunMode }" in types


def test_vue_sandbox_setup_prompt_is_loaded_on_first_chat_mount() -> None:
    view = _read(CHAT_VIEW)
    composable = _read(CHAT_RUN_MODE_COMPOSABLE)

    assert "useChatRunMode" in view
    assert "loadSandboxSetupStatus({ showPrompt: true })" in view
    assert "runMode" in view
    assert "setComposerRunMode" in view
    assert "sandbox.setup.status" in composable
    assert "sandbox.setup.ensure" in composable
    assert "sandboxSetupPromptDismissed" in composable
    assert "if (mode === 'full') return true" in composable
