from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "opensquilla-webui" / "src"
CHAT_VIEW = WEBUI / "views" / "ChatView.vue"
APPROVALS_VIEW = WEBUI / "views" / "ApprovalsView.vue"
CHAT_COMPOSER = WEBUI / "components" / "chat" / "ChatComposer.vue"
CHAT_SETTINGS = WEBUI / "components" / "chat" / "ChatComposerSettings.vue"
CHAT_RUN_MODE = WEBUI / "components" / "chat" / "ChatRunModeMenu.vue"
CHAT_SEND = WEBUI / "composables" / "chat" / "useChatSend.ts"
CHAT_RPC_EVENT_HANDLERS = WEBUI / "composables" / "chat" / "useChatRpcEventHandlers.ts"
CHAT_ELEVATED_MODE_COMPOSABLE = WEBUI / "composables" / "chat" / "useChatElevatedMode.ts"
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
    assert "_source?: { runMode?: RunMode }" in types


def test_vue_chat_frontend_does_not_expose_legacy_execution_mode() -> None:
    sources = "\n".join(
        _read(path)
        for path in [
            CHAT_VIEW,
            CHAT_COMPOSER,
            CHAT_SETTINGS,
            CHAT_SEND,
            APPROVALS_VIEW,
            RPC_TYPES,
        ]
    )

    assert "Execution mode" not in sources
    assert "composer-execution-mode" not in sources
    assert "elevated-mode" not in sources
    assert "elevatedMode" not in sources
    assert "setElevatedMode" not in sources
    assert "normalizeElevatedMode" not in sources
    assert "_source?: { elevated?: string" not in sources
    assert "Bypass approvals" not in sources
    assert "Approval bypass enabled" not in sources
    assert "opensquilla.elevatedMode" not in sources
    assert "opensquilla:elevated-mode" not in sources
    assert not CHAT_ELEVATED_MODE_COMPOSABLE.exists()


def test_vue_chat_composer_overlays_are_mutually_exclusive() -> None:
    composer = _read(CHAT_COMPOSER)
    run_mode = _read(CHAT_RUN_MODE)

    assert '@click="toggleSettings"' in composer
    assert ':close-signal="runModeCloseSignal"' in composer
    assert '@open="settingsOpen = false"' in composer
    assert "runModeCloseSignal.value += 1" in composer

    assert "@click=\"toggleOpen\"" in run_mode
    assert "open: []" in run_mode
    assert "function toggleOpen()" in run_mode
    assert "if (open.value) emit('open')" in run_mode
    assert "watch(() => props.closeSignal" in run_mode
    assert "open.value = false" in run_mode


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


def test_vue_approval_resolved_events_do_not_keep_header_status_pending() -> None:
    handlers = _read(CHAT_RPC_EVENT_HANDLERS)

    assert "function rpcEventMarksApprovalPending" in handlers
    assert "rawEvent.endsWith('.approval.requested')" in handlers
    assert "rawEvent.endsWith('.approval.resolved')" in handlers
    resolved_event = "rawEvent.endsWith('.approval.resolved')"
    assert "return false" in handlers[
        handlers.index(resolved_event) :
        handlers.index("const terminalStatus =", handlers.index(resolved_event))
    ]
    assert "rawEvent.includes('approval') && isCurrentSessionPayload(payloadObj)" not in handlers


def test_vue_run_mode_policy_fails_closed_without_valid_policy() -> None:
    composable = _read(CHAT_RUN_MODE_COMPOSABLE)
    menu = _read(CHAT_RUN_MODE)

    assert "const SAFE_RUN_MODES: RunMode[] = ['standard', 'trusted']" in composable
    assert "if (!policyAllowed) return [...SAFE_RUN_MODES]" in composable
    assert "return allowed.length ? allowed : [...SAFE_RUN_MODES]" in composable
    assert "let lastDefaultRunMode = defaultRunMode.value" in composable
    assert "runMode.value = runMode.value === previousDefault" in composable
    assert "const safeRunModes: RunMode[] = ['standard', 'trusted']" in menu
    assert "return allowed.length ? allowed : [...safeRunModes]" in menu
