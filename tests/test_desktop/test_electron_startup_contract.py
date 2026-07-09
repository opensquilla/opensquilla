import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def test_desktop_resume_is_visible_first_and_single_flight() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    resume = _section(
        main_ts,
        "async function openOrResumeDesktopApp",
        "function stopGateway",
    )

    assert "let gatewayStartPromise: Promise<GatewayState> | null = null" in main_ts
    assert "startupInProgress" not in main_ts
    assert "function ensureGatewayStarted(): Promise<GatewayState>" in main_ts
    assert "gatewayStartPromise = startGatewayWithPortRecovery().finally" in main_ts
    assert "gatewayStartPromise = null" in main_ts
    assert (
        "function isCurrentWindowAtControlUi(window: BrowserWindow, gatewayUrl: string): boolean"
        in main_ts
    )

    assert resume.index("await createMainWindow()") < resume.index("ensureGatewayStarted()")
    assert "focusMainWindow()" in resume
    assert "reuseHealthyGatewayState()" in resume
    assert "loadControlUiIntoCurrentWindow(gateway.url)" in resume


def test_desktop_gateway_completion_uses_current_live_window() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    load_current = _section(
        main_ts,
        "async function loadControlUiIntoCurrentWindow",
        "async function openOrResumeDesktopApp",
    )

    assert "function currentMainWindow(): BrowserWindow | null" in main_ts
    assert "const window = currentMainWindow()" in load_current
    assert "if (!window) return" in load_current
    assert "if (window.isDestroyed()) return" in load_current
    assert "isCurrentWindowAtControlUi(window, gatewayUrl)" in load_current
    guard_index = load_current.index("isCurrentWindowAtControlUi(window, gatewayUrl)")
    load_index = load_current.index("await loadControlUi(window, gatewayUrl)")
    assert guard_index < load_index
    assert "current.pathname === '/control'" in main_ts
    assert "current.pathname.startsWith('/control/')" in main_ts
    assert "if (mainWindow === window) mainWindow = null" in main_ts


def test_desktop_activation_retry_and_second_instance_share_resume_helper() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    retry = _section(
        main_ts,
        "ipcMain.handle('desktop:boot:retry'",
        "ipcMain.handle('desktop:boot:quit'",
    )

    assert "if (process.platform !== 'darwin') app.quit()" in main_ts
    assert "app.on('activate', () => {\n  void openOrResumeDesktopApp()" in main_ts
    # second-instance resumes the app via the shared helper (a diagnostic log
    # line precedes the resume call — see the #446 relaunch-retry contract).
    second_instance = _section(
        main_ts,
        "app.on('second-instance', () => {",
        "void app.whenReady().then",
    )
    assert "void openOrResumeDesktopApp()" in second_instance
    assert "void app.whenReady().then" in main_ts
    assert "void openOrResumeDesktopApp()" in _section(
        main_ts,
        "void app.whenReady().then",
        "})\n}",
    )

    # Retry backs both the boot-error button and the Control UI "Restart runtime"
    # action, so it forces a real restart: an in-flight start is joined (clearing
    # the stale error), otherwise an owned gateway is torn down and awaited before
    # respawn rather than reused, so a healthy-but-misbehaving runtime can restart.
    assert "if (gatewayStartPromise)" in retry
    assert "stopGateway()" in retry
    assert "await waitForGatewayProcessExit(previousChild)" in retry
    assert "clearReusableGatewayState()" in retry
    assert "void openOrResumeDesktopApp()" in retry


def test_boot_error_panel_exposes_reset_setup_recovery() -> None:
    boot_html = _read("desktop/electron/src/boot.html")
    reset_flow = _section(
        boot_html,
        "async function resetSetup()",
        "setInterval",
    )

    assert 'id="resetSetup"' in boot_html
    assert "Reset setup" in boot_html
    assert 'data-i18n="resetSetup"' in boot_html
    assert "function resetSetup()" in boot_html
    assert "api.resetDesktopSettings" in boot_html
    assert "window.confirm(" in boot_html
    assert "msg.resetConfirm" in boot_html
    assert "msg.resetPhase" in boot_html
    assert "msg.resetProgress" in boot_html
    assert "msg.resetFailed" in boot_html
    assert "saved desktop credential and generated gateway config" in boot_html
    assert "await api.resetDesktopSettings()" in reset_flow
    assert "await api.retryStartup()" in reset_flow
    assert reset_flow.index("await api.resetDesktopSettings()") < reset_flow.index(
        "await api.retryStartup()"
    )
    assert "errorPanel.classList.add('visible')" in reset_flow


def test_reset_desktop_settings_forces_onboarding_before_gateway_reuse() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )
    resume = _section(
        main_ts,
        "async function openOrResumeDesktopApp",
        "function stopGateway",
    )
    reset = _section(
        main_ts,
        "ipcMain.handle('desktop:settings:reset'",
        "ipcMain.handle('desktop:artifact:open'",
    )

    assert "let forceOnboardingOnNextStartup = false" in main_ts
    assert "function clearReusableGatewayState(): void" in main_ts
    reuse_guard = (
        "const reusableGateway = forceOnboardingOnNextStartup ? null : "
        "await reuseHealthyGatewayState()"
    )
    assert reuse_guard in start
    assert "forceOnboardingOnNextStartup = false" in start
    assert reuse_guard in resume
    assert "forceOnboardingOnNextStartup = true" in reset
    assert "const child = gatewayProcess && gatewayState.owned ? gatewayProcess : null" in reset
    assert "await waitForGatewayProcessExit(child)" in reset
    assert "clearReusableGatewayState()" in reset


def test_desktop_gateway_port_selection_is_bind_aware_and_bounded() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    port_selection = _section(
        main_ts,
        "const GATEWAY_PORT_FIRST = 18791",
        "async function healthCheck",
    )
    recovery = _section(
        main_ts,
        "async function startGatewayWithPortRecovery",
        "async function loadControlUi",
    )
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    assert "const GATEWAY_PORT_LAST = 18830" in port_selection
    assert "function isPortBindable(port: number): Promise<boolean>" in port_selection
    assert "net.createServer()" in port_selection
    assert "server.listen({ host: '127.0.0.1', port, exclusive: true })" in port_selection
    assert "await isPortBindable(port)" in port_selection
    assert "gatewayPortCursor = nextGatewayPortAfter(port)" in port_selection
    assert "OPENSQUILLA_DESKTOP_GATEWAY_PORT" in port_selection
    assert "function gatewayExitLooksLikePortInUse(output: string): boolean" in main_ts
    assert "OPENSQUILLA_GATEWAY_PORT_IN_USE" in main_ts
    assert "gateway port is already in use" in main_ts
    assert (
        "const maxAttempts = hasExplicitGatewayPort() ? 1 : "
        "GATEWAY_PORT_LAST - GATEWAY_PORT_FIRST + 1"
    ) in recovery
    assert "gatewayExitLooksLikePortInUse(message)" in recovery
    assert "desktopLog('gateway_port_retry'" in recovery
    assert "if (portConflictExit && !hasExplicitGatewayPort())" in start
    assert "sendBootError(gatewayState.error)" in start


def test_windows_gateway_hard_terminate_clears_pid_without_unlinking_lock() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    cleanup = _section(
        main_ts,
        "async function clearKnownOwnedGatewayPidFile",
        "function stopGateway",
    )

    assert "gateway.pid.lock" in cleanup
    assert "join(desktopStateDir(), 'gateway.pid')" in cleanup
    assert "join(desktopStateDir(), 'gateway.pid.lock')" not in cleanup
    assert "void clearKnownOwnedGatewayPidFile()" in cleanup


def test_windows_quit_rejected_shutdown_uses_short_hard_kill_backstop() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    before_quit = _section(
        main_ts,
        "app.on('before-quit'",
        "function shutdownFromSignal",
    )

    rejected = _section(
        before_quit,
        "if (!accepted)",
        "} else {",
    )

    assert "hardTerminateGatewayProcess(child)" in rejected
    assert "GATEWAY_HARD_KILL_BACKSTOP_MS" in rejected
    assert "await clearKnownOwnedGatewayPidFile()" in rejected
    assert "UPDATE_GATEWAY_EXIT_TIMEOUT_MS" not in rejected


def test_windows_uninstall_can_clear_app_data() -> None:
    package_json = json.loads(_read("desktop/electron/package.json"))

    assert package_json["build"]["nsis"]["deleteAppDataOnUninstall"] is True


def test_desktop_onboarding_is_owned_modal_child_of_main_window() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    onboarding = _section(
        main_ts,
        "async function runOnboarding",
        "async function pathExists",
    )

    assert "const parentWindow = currentMainWindow()" in onboarding
    assert "parent: parentWindow ?? undefined" in onboarding
    assert "modal: Boolean(parentWindow)" in onboarding
    assert "onboardingWindow?.focus()" in onboarding


def test_desktop_focus_prefers_open_onboarding_window() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    focus = _section(
        main_ts,
        "function focusMainWindow",
        "function installEditingContextMenu",
    )

    assert "function currentOnboardingWindow(): BrowserWindow | null" in main_ts
    assert "function focusOnboardingWindow(): boolean" in main_ts
    assert "if (focusOnboardingWindow()) return true" in focus
    onboarding_index = focus.index("if (focusOnboardingWindow()) return true")
    main_index = focus.index("if (!mainWindow || mainWindow.isDestroyed()) return false")
    assert onboarding_index < main_index


def test_start_gateway_reuses_healthy_gateway_before_spawn() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    reuse = _section(
        main_ts,
        "async function reuseHealthyGatewayState",
        "async function startGateway",
    )
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    assert "await healthCheck(gatewayState.url)" in reuse
    assert "gatewayState.status = 'ready'" in reuse
    reuse_guard = (
        "const reusableGateway = forceOnboardingOnNextStartup ? null : "
        "await reuseHealthyGatewayState()"
    )
    assert reuse_guard in start
    assert start.index(reuse_guard) < start.index("const overrideUrl")
    assert "if (reusableGateway) return reusableGateway" in start
    assert "hasGatewayProcessExited(gatewayProcess)" in start
    assert "stopGateway()" in start


def test_start_gateway_does_not_attach_to_unrequested_default_dev_gateway() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    assert "const overrideUrl = process.env.OPENSQUILLA_DESKTOP_GATEWAY_URL" in start
    assert "await healthCheck('http://127.0.0.1:18791')" not in start
    assert "gatewayState.url = 'http://127.0.0.1:18791'" not in start


def test_desktop_blocks_macos_app_translocation_without_forcing_applications() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    assert "const MAC_APP_TRANSLOCATION_SEGMENT = '/AppTranslocation/'" in main_ts
    assert "function macDesktopInstallContext(): MacInstallContext" in main_ts
    assert "function assertSupportedMacInstallLocation(): void" in main_ts
    assert "process.platform !== 'darwin' || !app.isPackaged" in main_ts
    assert "blocked: translocated" in main_ts
    assert "translocated || !inApplications" not in main_ts
    assert "drag OpenSquilla.app from the DMG into Applications" in main_ts
    assert "then open OpenSquilla again" in main_ts
    assert "assertSupportedMacInstallLocation()" in start
    assert start.index("if (reusableGateway) return reusableGateway") < start.index(
        "assertSupportedMacInstallLocation()"
    )
    assert start.index("assertSupportedMacInstallLocation()") < start.index("const overrideUrl")


def test_desktop_gateway_exit_classifies_newer_config_validation_errors() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )
    wait = _section(
        main_ts,
        "async function waitForGateway",
        "async function waitForControlUi",
    )

    assert "const GATEWAY_OUTPUT_TAIL_MAX_CHARS = 12_000" in main_ts
    assert "const NEWER_CONFIG_DIAGNOSTIC_FIELDS = [" in main_ts
    for field in ["'llm_ensemble'", "'privacy'", "'sandbox.auto_setup'", "'llm_profiles'"]:
        assert field in main_ts
    assert (
        "function classifyGatewayExitMessage(message: string, outputTail: string): string"
        in main_ts
    )
    assert "settings written by a newer OpenSquilla version" in main_ts
    assert "let gatewayOutputTail = ''" in start
    assert "let childExitMessage: string | null = null" in start
    assert "appendGatewayOutputTail(gatewayOutputTail, chunk)" in start
    assert "classifyGatewayExitMessage(exitMessage, gatewayOutputTail)" in start
    assert "await waitForGateway(url, () => childExitMessage)" in start
    assert "earlyExitMessage?: () => string | null" in wait
    assert "if (earlyExit) throw new Error(earlyExit)" in wait


def test_start_gateway_enriches_child_path_for_code_task_builds() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    assert "function desktopChildPath" in main_ts
    assert "function desktopNodeBinCandidates" in main_ts
    assert "packagedRuntimeRoot(), 'node', 'bin'" in main_ts
    assert "OPENSQUILLA_NODE_BIN_DIR" in start
    assert "PATH: childPath" in start


def test_desktop_python_children_force_utf8_stdio() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )
    uninstall = _section(
        main_ts,
        "async function runUninstallCli",
        "ipcMain.handle('desktop:uninstall:summary'",
    )

    for section in (start, uninstall):
        assert "PYTHONUNBUFFERED: '1'" in section
        assert "PYTHONUTF8: '1'" in section
        assert "PYTHONIOENCODING: 'utf-8:replace'" in section


def test_stop_gateway_sigkill_fallback_uses_real_child_exit_state() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    stop = _section(
        main_ts,
        "function stopGateway(): void",
        "// ── Auto-update",
    )
    hard_terminate = _section(
        main_ts,
        "function hardTerminateGatewayProcess",
        "function stopGateway",
    )

    assert "child.killed" not in stop
    assert "hasGatewayProcessExited(child)" in hard_terminate
    assert "if (hasGatewayProcessExited(child)) return" in hard_terminate
    assert "if (!hasGatewayProcessExited(child))" in hard_terminate
    assert "terminateGatewayProcess(child, 'SIGKILL')" in hard_terminate
    assert "child.kill(signal)" in hard_terminate
    assert "let exited = false" in stop
    assert "child.once('exit', () => {\n      exited = true\n    })" in stop


def test_dev_gateway_runtime_is_process_tree_aware_on_termination() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function startGatewayWithPortRecovery",
    )
    terminate = _section(
        main_ts,
        "function terminateGatewayProcess",
        "function stopGateway",
    )

    assert "mode: 'dev'" in main_ts
    assert "const gatewayProcessTreeChildren = new WeakSet" in main_ts
    assert "detached: runtime.mode === 'dev' && process.platform !== 'win32'" in start
    assert "if (runtime.mode === 'dev') gatewayProcessTreeChildren.add(child)" in start
    assert "gatewayProcessTreeChildren.has(child)" in terminate
    assert "spawnSync('taskkill', ['/pid', String(pid), '/t', '/f']" in terminate
    assert "process.kill(-pid, signal)" in terminate
    assert "child.kill(signal)" in terminate


def test_desktop_update_menu_exposes_pending_downloaded_update_relaunch() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    menu = _section(
        main_ts,
        "function createApplicationMenu(): void",
        "function focusMainWindow",
    )

    assert "let downloadedUpdateVersion: string | null = null" in main_ts
    assert "downloadedUpdateVersion" in menu
    assert "desktopT('menu.relaunchToUpdate')" in menu
    assert "void applyDownloadedUpdate()" in menu
    assert "desktopT('menu.checkForUpdates')" in menu
    assert "void checkForUpdates(true)" in menu


def test_desktop_update_state_bridge_exposes_nonblocking_renderer_api() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    preload = _read("desktop/electron/src/preload.cts")

    assert "type DesktopUpdateStatus =" in main_ts
    assert "interface DesktopUpdateState" in main_ts
    assert "function desktopUpdateSnapshot()" in main_ts
    assert "function publishDesktopUpdateState()" in main_ts
    assert "ipcMain.handle('desktop:update:state'" in main_ts
    assert "ipcMain.handle('desktop:update:check'" in main_ts
    assert "ipcMain.handle('desktop:update:download'" in main_ts
    assert "ipcMain.handle('desktop:update:relaunch'" in main_ts
    assert "ipcMain.handle('desktop:update:dismiss'" in main_ts
    assert "getUpdateState" in preload
    assert "checkForUpdates" in preload
    assert "downloadUpdate" in preload
    assert "relaunchToUpdate" in preload
    assert "dismissUpdate" in preload
    assert "onUpdateState" in preload
    assert "desktop:update:state-changed" in preload


def test_native_update_events_publish_state_without_startup_dialogs() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    update_available = _section(
        main_ts,
        "autoUpdater.on('update-available'",
        "autoUpdater.on('update-not-available'",
    )
    update_downloaded = _section(
        main_ts,
        "autoUpdater.on('update-downloaded'",
        "autoUpdater.on('error'",
    )

    assert "setDesktopUpdateState" in update_available
    assert "status: 'available'" in update_available
    assert "showUpdateDialog" not in update_available
    assert "downloadUpdate" not in update_available

    assert "setDesktopUpdateState" in update_downloaded
    assert "status: 'downloaded'" in update_downloaded
    assert "downloadedUpdateVersion = version" in update_downloaded
    assert "createApplicationMenu()" in update_downloaded
    assert "showUpdateDialog" not in update_downloaded


def test_desktop_mock_update_is_dev_only_and_uses_native_update_surface() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    mock_version = _section(
        main_ts,
        "function mockUpdateVersion",
        "function desktopUpdateMenuEnabled",
    )
    native_gate = _section(
        main_ts,
        "function nativeAutoUpdateEnabled",
        "// macOS Squirrel",
    )
    startup = _section(main_ts, "void app.whenReady().then", "})\n}")

    assert "const MOCK_UPDATE_VERSION_ENV = 'OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION'" in main_ts
    assert "if (app.isPackaged) return null" in mock_version
    assert "process.env[MOCK_UPDATE_VERSION_ENV]" in mock_version
    assert "mockUpdateVersion() !== null" in native_gate
    assert "autoUpdateSupported() && macUpdateLocationOk()" in native_gate
    assert "desktopUpdateMenuEnabled()" in main_ts
    assert "mockUpdateVersion() !== null" in startup
    assert "void checkForUpdates(false)" in startup


def test_desktop_mock_update_flow_is_nonblocking_until_renderer_downloads() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    mock_flow = _section(
        main_ts,
        "async function runMockUpdateFlow",
        "async function downloadDesktopUpdate",
    )
    mock_download = _section(
        main_ts,
        "async function downloadDesktopUpdate",
        "function initAutoUpdater",
    )
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    assert "setDesktopUpdateState" in mock_flow
    assert "status: 'available'" in mock_flow
    assert "showUpdateDialog" not in mock_flow
    assert "downloadedUpdateVersion = version" not in mock_flow
    assert "mockDownloadedUpdate = true" not in mock_flow

    assert "setDesktopUpdateState" in mock_download
    assert "status: 'downloading'" in mock_download
    assert "status: 'downloaded'" in mock_download
    assert "downloadedUpdateVersion = version" in mock_download
    assert "mockDownloadedUpdate = true" in mock_download
    assert "createApplicationMenu()" in mock_download
    assert "autoUpdater" not in mock_flow
    assert "quitAndInstall" not in mock_flow

    assert "if (mockDownloadedUpdate)" in apply_update
    mock_apply = _section(
        apply_update,
        "if (mockDownloadedUpdate)",
        "const pendingVersion = downloadedUpdateVersion",
    )
    assert "showUpdateDialog" in mock_apply
    assert "desktopT('update.mockInstallTitle')" in mock_apply
    assert "autoUpdater.quitAndInstall" not in mock_apply


def test_desktop_update_actions_are_guarded_against_reentry() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    download_update = _section(
        main_ts,
        "async function downloadDesktopUpdate",
        "function initAutoUpdater",
    )
    check_update = _section(
        main_ts,
        "async function checkForUpdates",
        "function gatewayProcessForUpdateInstall",
    )
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    reentry_guard = (
        "if (updateDownloadInProgress || updateApplying || "
        "desktopUpdateStatus === 'downloaded')"
    )
    assert reentry_guard in download_update
    assert download_update.index("updateDownloadInProgress || updateApplying") < (
        download_update.index("const mockVersion = mockUpdateVersion()")
    )
    assert "if (updateDownloadInProgress || updateApplying) return" in check_update
    assert "if (!mockDownloadedUpdate && !downloadedUpdateVersion) return" in apply_update
    assert apply_update.index("if (updateApplying) return") < apply_update.index(
        "if (!mockDownloadedUpdate && !downloadedUpdateVersion) return"
    )
    assert apply_update.index(
        "if (!mockDownloadedUpdate && !downloadedUpdateVersion) return"
    ) < apply_update.index("if (mockDownloadedUpdate)")


def test_desktop_mock_update_dialog_auto_responder_is_mock_only() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    responder = _section(
        main_ts,
        "function nextMockUpdateDialogResponse",
        "async function runMockUpdateFlow",
    )
    show_dialog = _section(
        main_ts,
        "function showUpdateDialog",
        "function showUpdateError",
    )

    assert (
        "const MOCK_UPDATE_DIALOG_RESPONSES_ENV = "
        "'OPENSQUILLA_DESKTOP_MOCK_UPDATE_DIALOG_RESPONSES'"
    ) in main_ts
    assert "if (mockUpdateVersion() === null) return null" in responder
    assert "process.env[MOCK_UPDATE_DIALOG_RESPONSES_ENV]" in responder
    assert "Number.isInteger(response)" in responder
    assert "const mockResponse = nextMockUpdateDialogResponse()" in show_dialog
    assert "response: mockResponse" in show_dialog
    assert "dialog.showMessageBox" in show_dialog


def test_desktop_mock_update_flow_has_automated_e2e_script() -> None:
    package_json = json.loads(_read("desktop/electron/package.json"))
    script = _read("desktop/electron/scripts/test-mock-update-flow.mjs")

    assert package_json["scripts"]["test:mock-update-flow"] == (
        "npm run build && node scripts/test-mock-update-flow.mjs"
    )
    assert "_electron" in script
    assert "OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION" in script
    assert "OPENSQUILLA_DESKTOP_MOCK_UPDATE_DIALOG_RESPONSES" in script
    assert "window.opensquillaDesktop.isAutoUpdateEnabled()" in script
    assert "window.opensquillaDesktop.getUpdateState" in script
    assert "data-testid=\"desktop-update-download\"" in script
    assert "data-testid=\"update-banner\"" in script
    assert "Menu.getApplicationMenu()" in script
    assert "Relaunch to Update" in script


def test_update_downloaded_records_pending_version_and_rebuilds_menu() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    update_downloaded = _section(
        main_ts,
        "autoUpdater.on('update-downloaded'",
        "autoUpdater.on('error'",
    )
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    assert "downloadedUpdateVersion = version" in update_downloaded
    assert update_downloaded.index("downloadedUpdateVersion = version") < update_downloaded.index(
        "createApplicationMenu()"
    )
    assert "setDesktopUpdateState" in update_downloaded
    assert "status: 'downloaded'" in update_downloaded
    assert "showUpdateDialog" not in update_downloaded
    assert "if (response === 0) void applyDownloadedUpdate()" not in update_downloaded
    assert "downloadedUpdateVersion = null" in apply_update
    assert apply_update.index("downloadedUpdateVersion = null") < apply_update.index(
        "autoUpdater.quitAndInstall(false, true)"
    )


def test_generic_update_error_preserves_pending_downloaded_update_menu() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    show_error = _section(
        main_ts,
        "function showUpdateError",
        "async function runMockUpdateFlow",
    )

    assert "downloadedUpdateVersion = null" not in show_error
    assert "createApplicationMenu()" not in show_error
    assert "setDesktopUpdateState" in show_error
    assert "status: 'error'" in show_error
    assert "hadDownloadedUpdate" not in show_error


def test_silent_startup_update_error_is_not_published_as_visible_error() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    show_error = _section(
        main_ts,
        "function showUpdateError",
        "async function runMockUpdateFlow",
    )

    assert "const shouldNotify = manualUpdateCheck || updateDownloadInProgress" in show_error
    assert "if (!shouldNotify)" in show_error
    assert "status: downloadedUpdateVersion ? 'downloaded' : 'idle'" in show_error
    assert "error: null" in show_error
    assert show_error.index("if (!shouldNotify)") < show_error.index("status: 'error'")


def test_apply_downloaded_update_waits_for_actual_gateway_exit_before_install() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    wait_helper = _section(
        main_ts,
        "async function waitForGatewayProcessExit",
        "async function applyDownloadedUpdate",
    )
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    assert "hasGatewayProcessExited(child)" in wait_helper
    assert "child.once('exit', () => finish(true))" in wait_helper
    assert "setTimeout(resolve" not in apply_update
    assert "waitForGatewayProcessExit(child)" in apply_update
    assert apply_update.index("waitForGatewayProcessExit(child)") < apply_update.index(
        "autoUpdater.quitAndInstall(false, true)"
    )


def test_apply_downloaded_update_timeout_restores_retry_state_before_returning() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    assert "const pendingVersion = downloadedUpdateVersion" in apply_update
    assert "const exited = await waitForGatewayProcessExit(child)" in apply_update
    assert "if (!exited)" in apply_update
    timeout_branch = _section(
        apply_update,
        "if (!exited)",
        "autoUpdater.quitAndInstall(false, true)",
    )
    assert "restoreDownloadedUpdateRetryState(pendingVersion)" in timeout_branch
    assert "return" in timeout_branch
    assert timeout_branch.index("return") < apply_update.index(
        "autoUpdater.quitAndInstall(false, true)"
    )


def test_apply_downloaded_update_handoff_error_restores_retry_state() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    restore = _section(
        main_ts,
        "function restoreDownloadedUpdateRetryState",
        "// Stop the owned gateway child",
    )
    apply_update = _section(
        main_ts,
        "async function applyDownloadedUpdate(): Promise<void>",
        "// Lets the gateway-served Control UI",
    )

    assert "downloadedUpdateVersion = pendingVersion" in restore
    assert "updateApplying = false" in restore
    assert "isQuitting = false" in restore
    assert "createApplicationMenu()" in restore
    assert "try {\n    autoUpdater.quitAndInstall(false, true)\n  } catch (err)" in apply_update
    handoff_error = _section(
        apply_update,
        "} catch (err)",
        "}\n}",
    )
    assert "restoreDownloadedUpdateRetryState(pendingVersion)" in handoff_error
    assert "showUpdateDialog" in handoff_error


def test_desktop_persists_network_observability_privacy_setting() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    types_ts = _read("opensquilla-webui/src/platform/types.ts")
    vite_env = _read("opensquilla-webui/src/vite-env.d.ts")
    connection = _section(
        main_ts,
        "interface DesktopConnection",
        "interface OnboardingPayload",
    )
    onboarding_payload = _section(
        main_ts,
        "interface OnboardingPayload",
        "interface DesktopSettingsPayload",
    )
    settings_payload = _section(
        main_ts,
        "interface DesktopSettingsPayload",
        "interface DesktopSettingsSnapshot",
    )
    snapshot = _section(main_ts, "interface DesktopSettingsSnapshot", "interface RuntimeLaunch")
    save = _section(
        main_ts,
        "async function saveDesktopCredential",
        "async function writeDesktopConfig",
    )
    config_writer = _section(
        main_ts,
        "async function writeDesktopConfig",
        "function settingsSnapshot",
    )
    web_settings = _section(
        types_ts,
        "export interface DesktopSettings",
        "export interface ProviderOption",
    )
    web_payload = _section(
        types_ts,
        "export interface DesktopSettingsPayload",
        "export interface PlatformCapabilities",
    )
    desktop_api = _section(vite_env, "interface OpenSquillaDesktopApi", "interface Window")

    assert "disableNetworkObservability: boolean" in connection
    assert "disableNetworkObservability?: unknown" in onboarding_payload
    assert "disableNetworkObservability?: unknown" not in settings_payload
    assert "interface DesktopSettingsPayload extends OnboardingPayload {}" in settings_payload
    assert "disableNetworkObservability: boolean" in snapshot
    assert "disableNetworkObservability: boolean" in web_settings
    assert "disableNetworkObservability?: boolean" in web_payload
    assert (
        "saveDesktopSettings: (payload: DesktopSettingsPayload) => Promise<DesktopSettings>"
        in desktop_api
    )

    assert "normalizeBooleanSetting(" in main_ts
    assert "payload.disableNetworkObservability" in save
    assert "existing?.disableNetworkObservability" in save
    assert "disableNetworkObservability," in save
    assert "privacyConfigTomlLines(credential)" in config_writer
    assert "function privacyConfigTomlLines" in main_ts
    assert "function desktopConfigShouldWritePrivacySection" in main_ts
    assert (
        "credential.disableNetworkObservability || "
        "readDesktopConfigNetworkObservabilitySetting() !== null"
    ) in main_ts
    assert (
        "`disable_network_observability = "
        "${credential.disableNetworkObservability ? 'true' : 'false'}`"
        in main_ts
    )


def test_desktop_credential_save_preserves_config_privacy_without_payload_setting() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    save = _section(
        main_ts,
        "async function saveDesktopCredential",
        "async function writeDesktopConfig",
    )
    read_config = _section(
        main_ts,
        "function readDesktopConfigNetworkObservabilitySetting",
        "function desktopConfigNetworkObservabilityDisabled",
    )

    assert (
        "const configDisableNetworkObservability = "
        "readDesktopConfigNetworkObservabilitySetting()"
    ) in save
    assert (
        ": configDisableNetworkObservability ?? existing?.disableNetworkObservability ?? false"
        in save
    )
    assert "if (!existsSync(path)) return null" in read_config
    assert "parseDesktopNetworkObservabilityPrivacyConfig(raw)" in read_config
    assert "return true" in read_config


def test_desktop_config_writer_does_not_emit_new_privacy_section_by_default() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    config_writer = _section(
        main_ts,
        "async function writeDesktopConfig",
        "function settingsSnapshot",
    )
    privacy_lines = _section(
        main_ts,
        "function privacyConfigTomlLines",
        "function plainSecret",
    )

    assert "'[privacy]'" not in config_writer
    assert "'[llm_ensemble]'" not in config_writer
    assert "if (!desktopConfigShouldWritePrivacySection(credential)) return []" in privacy_lines
    assert (
        "credential.disableNetworkObservability || "
        "readDesktopConfigNetworkObservabilitySetting() !== null"
        in main_ts
    )


def test_desktop_network_observability_disable_gates_native_update_and_gateway_env() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    auto_supported = _section(
        main_ts,
        "function autoUpdateSupported(): boolean",
        "function nativeAutoUpdateEnabled",
    )
    startup = _section(main_ts, "void app.whenReady().then", "})\n}")
    start = _section(main_ts, "async function startGateway", "async function loadControlUi")
    persisted_gate = _section(
        main_ts,
        "function desktopPersistedNetworkObservabilityDisabled(): boolean",
        "function parseDesktopNetworkObservabilityPrivacyConfig",
    )
    config_gate = _section(
        main_ts,
        "function desktopConfigNetworkObservabilityDisabled(): boolean",
        "function desktopNetworkObservabilityDisabled(): boolean",
    )
    read_config = _section(
        main_ts,
        "function readDesktopConfigNetworkObservabilitySetting",
        "function desktopConfigNetworkObservabilityDisabled",
    )
    network_gate = _section(
        main_ts,
        "function desktopNetworkObservabilityDisabled(): boolean",
        "function autoUpdateSupported",
    )

    assert "function desktopPersistedNetworkObservabilityDisabled(): boolean" in main_ts
    assert "function desktopConfigNetworkObservabilityDisabled(): boolean" in main_ts
    assert "function desktopNetworkObservabilityDisabled(): boolean" in main_ts
    assert "const path = credentialPath()" in persisted_gate
    assert "if (!existsSync(path)) return false" in persisted_gate
    assert "readFileSync(path, 'utf8')" in persisted_gate
    assert "return true" in persisted_gate
    assert "const path = desktopConfigPath()" in read_config
    assert "readDesktopConfigNetworkObservabilitySetting() ?? false" in config_gate
    assert "return true" in read_config
    assert "desktopPersistedNetworkObservabilityDisabled()" in main_ts
    assert "desktopConfigNetworkObservabilityDisabled()" in main_ts
    assert (
        "return desktopPersistedNetworkObservabilityDisabled() || "
        "desktopConfigNetworkObservabilityDisabled()"
        in network_gate
    )
    assert "OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY" in main_ts
    assert "OPENSQUILLA_TELEMETRY_DISABLED" in main_ts
    assert "OPENSQUILLA_UPDATE_CHECK_DISABLED" in main_ts
    assert "if (desktopNetworkObservabilityDisabled()) return false" in auto_supported
    assert auto_supported.index("desktopNetworkObservabilityDisabled()") < auto_supported.index(
        "process.env.OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE"
    )
    assert "if (autoUpdateSupported())" in startup
    assert "void checkForUpdates(false)" in startup
    assert "connection.disableNetworkObservability" in start
    assert "OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY: '1'" in start


def test_package_verifier_hard_fails_stale_runtime_and_boot_contract() -> None:
    verifier = _read("desktop/electron/scripts/verify-package.mjs")
    package_json = json.loads(_read("desktop/electron/package.json"))

    assert package_json["scripts"]["verify:icons"] == "node scripts/verify-icon-config.mjs"
    assert (
        package_json["scripts"]["verify:package"]
        == "npm run verify:icons && node scripts/verify-package.mjs"
    )
    for expected in [
        "runtime is empty",
        "_AsyncConnection.create_function",
        "app.asar",
        "gatewayStartPromise",
        "openOrResumeDesktopApp",
        "create the desktop window before gateway startup",
        "first-run onboarding an owned modal child window",
        "does not prefer the onboarding window when focusing",
        "app.asar package.json version is not npm semver",
        "prereleases must use 0.5.0-rc2 style, not 0.5.0rc2",
        "process.exit(1)",
    ]:
        assert expected in verifier

def test_desktop_gateway_build_and_verifier_cover_runtime_capabilities() -> None:
    build_gateway = _read("desktop/electron/scripts/build-gateway.mjs")
    verifier = _read("desktop/electron/scripts/verify-package.mjs")

    for extra in ["recommended", "mcp", "msg", "matrix", "document-extras"]:
        assert f"'{extra}'" in build_gateway
    for module in ["joblib", "sklearn", "lightgbm", "tokenizers", "tiktoken", "onnxruntime", "mcp"]:
        assert f"'{module}'" in build_gateway
    assert "'--collect-all',\n  'sklearn'" not in build_gateway
    assert "'--collect-all',\n  'lightgbm'" not in build_gateway
    assert "'--collect-binaries',\n  'sklearn'" in build_gateway
    assert "join('bin', 'lib_lightgbm.dll')" in build_gateway
    assert "platformLightgbmBundleDir()" in build_gateway
    assert "'lightgbm/bin'" in build_gateway
    assert "lib_lightgbm.dylib" in build_gateway
    assert "libomp.dylib" in build_gateway
    assert "Git LFS pointer file, not the real router artifact" in build_gateway
    assert "git lfs pull --include=" in build_gateway
    assert "findFilesByName(runtimeGatewayDir, 'libomp.dylib')" in build_gateway
    assert "install_name_tool" in build_gateway
    assert "codesign" in build_gateway
    assert "'--force', '--sign', '-'" in build_gateway
    assert "@loader_path/libomp.dylib" in build_gateway
    assert "verifyMacLightgbmRuntime" in verifier
    assert "lightgbm/lib/lib_lightgbm.dylib" in verifier
    assert "bundled libomp.dylib" in verifier
    assert "otool" in verifier
    assert "@loader_path/libomp.dylib" in verifier
    assert "code-task', 'stage-task-file'" in verifier
    assert "code-task', 'smoke-imports'" in verifier
    assert "code-task', 'smoke-router'" in verifier
    assert "timeout: 120000" in verifier
    assert "OPENSQUILLA_GATEWAY_SMOKE_TIMEOUT_MS" in _read(
        "desktop/electron/scripts/smoke-gateway.mjs"
    )
    assert "'90000'" in _read("desktop/electron/scripts/smoke-gateway.mjs")


def test_windows_release_workflow_fails_fast_after_gateway_build_failure() -> None:
    workflow = _read(".github/workflows/wheelhouse-release.yml")
    windows_build = _section(
        workflow,
        "      - name: Build unsigned Windows installer",
        "      - name: Verify Electron package",
    )

    assert "shell: bash" in windows_build
    assert "set -euo pipefail" in windows_build
    assert windows_build.index("npm run build:gateway") < windows_build.index(
        "          npm run build\n"
    )


def test_desktop_native_artifact_open_allows_active_documents_with_file_extensions() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    artifact_list_vue = _read("opensquilla-webui/src/components/chat/ChatArtifactList.vue")
    mime_extensions = _section(main_ts, "const MIME_EXTENSIONS", "}\n\n")
    native_open = _section(
        main_ts,
        "async function openArtifactWithDefaultApp",
        "function createApplicationMenu",
    )

    assert "'text/html': '.html'" in mime_extensions
    assert "'application/xhtml+xml': '.xhtml'" in mime_extensions
    assert "function isActiveDocumentArtifactRequest" not in main_ts
    assert "shell.openPath(filePath)" in native_open
    assert "isActiveDocumentArtifact(artifact, fetched.blob)" not in artifact_list_vue


def test_desktop_cleanup_does_not_claim_os_app_uninstall() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    panel_vue = _read("opensquilla-webui/src/components/settings/DesktopRuntimePanel.vue")
    en_locale = json.loads(_read("opensquilla-webui/src/locales/en.json"))
    zh_locale = json.loads(_read("opensquilla-webui/src/locales/zh-Hans.json"))

    cleanup = _section(
        main_ts,
        "// ── Desktop data cleanup",
        "ipcMain.handle('desktop:boot:state'",
    )

    assert "OPENSQUILLA_INSTALL_METHOD: 'desktop'" in cleanup
    assert "OPENSQUILLA_STATE_DIR: desktopHome()" in cleanup
    assert "remove the installed .app / NSIS application" in cleanup
    # The purge confirmation is localized via desktopT; the "app remains"
    # guarantee now lives in the (localized) message catalog rather than inline.
    assert "desktopT('uninstall.confirmDetail')" in cleanup
    assert "installed app itself will remain" in main_ts
    assert "does not remove the installed app bundle itself" in panel_vue

    en_runtime = en_locale["setup"]["runtime"]
    zh_runtime = zh_locale["setup"]["runtime"]
    assert "desktop data cleanup" in en_runtime["uninstallLabel"]
    assert "uninstalled" not in en_runtime["uninstallDone"].lower()
    assert "remove OpenSquilla through your OS" in en_runtime["uninstallDone"]
    assert "清理桌面本地数据" in zh_runtime["uninstallLabel"]
    assert "已卸载" not in zh_runtime["uninstallDone"]


def test_desktop_second_launch_retries_lock_and_logs_instead_of_silent_quit() -> None:
    # Issue #446: a relaunch right after closing must not silently no-op. The
    # single-instance lock is retried for a bounded window, and both success and
    # failure are recorded to a main-process launch log.
    main_ts = _read("desktop/electron/src/main.ts")

    assert "function acquireSingleInstanceLockWithRetry(): boolean" in main_ts
    assert "function desktopLog(" in main_ts
    assert "desktop.log" in main_ts
    # Bounded retry, not a single attempt.
    retry = _section(
        main_ts,
        "function acquireSingleInstanceLockWithRetry(): boolean",
        "desktopLog('launch',",
    )
    assert "Date.now() + 5_000" in retry
    assert "app.requestSingleInstanceLock()" in retry
    # On give-up: explicit dialog + quit, not a bare silent app.quit().
    giveup = _section(main_ts, "if (!gotSingleInstanceLock) {", "app.on('second-instance'")
    assert "launch_aborted_lock_held" in giveup
    assert "showErrorBox" in giveup


def test_desktop_windows_quit_drains_gateway_before_exit() -> None:
    # Issue: the daily Windows close path must give the gateway its graceful
    # drain (like the update/uninstall paths), not a bare TerminateProcess.
    main_ts = _read("desktop/electron/src/main.ts")

    before_quit = _section(main_ts, "app.on('before-quit'", "function shutdownFromSignal")
    assert "process.platform === 'win32'" in before_quit
    assert "event.preventDefault()" in before_quit
    assert "requestGatewayShutdown(" in before_quit
    assert "waitForGatewayProcessExit(child)" in before_quit
    assert "app.exit(0)" in before_quit
    # The drain runs once, then the re-issued quit falls through.
    assert "windowsQuitDrainDone" in before_quit


def test_desktop_macos_prerelease_update_resolver_wires_generic_feed() -> None:
    # Issue #485: PEP440 rc git tags (v0.5.0rc2) are not npm-semver, so
    # electron-updater's GitHub provider skips them and a packaged prerelease
    # discovers no updates. A resolver selects the candidate release and points a
    # generic feed at its latest-mac.yml; stable tags keep the default provider.
    main_ts = _read("desktop/electron/src/main.ts")
    resolver = _read("desktop/electron/src/update-feed-resolver.ts")
    package_json = json.loads(_read("desktop/electron/package.json"))
    check = _section(
        main_ts,
        "async function checkForUpdates",
        "function gatewayProcessForUpdateInstall",
    )

    assert "export function parseOpenSquillaReleaseTag" in resolver
    assert "export function selectMacPrereleaseCandidate" in resolver
    assert "latest-mac.yml" in resolver
    # Only same-base upgrades; a different base is not crossed automatically.
    assert "parsed.base !== current.base" in resolver

    assert "async function configureDesktopUpdateFeed()" in main_ts
    assert "if (process.platform !== 'darwin' || !app.isPackaged) return 'default'" in main_ts
    assert "provider: 'generic', url: candidate.feedUrl, channel: 'latest'" in main_ts
    # Numeric rc order can disagree with electron-updater's string-based semver
    # gate (0.5.0-rc10 sorts below rc9), so the resolved-candidate path allows the
    # "downgrade"; the default path forbids it so stable users never regress.
    resolver_feed = _section(
        main_ts,
        "async function configureDesktopUpdateFeed()",
        "async function checkForUpdates",
    )
    assert "autoUpdater.allowDowngrade = false" in resolver_feed
    assert "autoUpdater.allowDowngrade = true" in resolver_feed
    # checkForUpdates consults the resolver and reports up-to-date without a
    # spurious GitHub-provider error when no newer same-base release exists.
    assert "const feed = await configureDesktopUpdateFeed()" in check
    assert "if (feed === 'up-to-date')" in check

    assert package_json["scripts"]["test:update-resolver"] == (
        "npm run build && node scripts/test-update-resolver.mjs"
    )


def test_gateway_spawn_state_dir_is_the_desktop_home_root() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )

    # OPENSQUILLA_STATE_DIR names the OpenSquilla HOME ROOT on the Python side
    # (paths.default_opensquilla_home); runtime state lives in its state/
    # subdir. The gateway child must receive desktopHome(), not the state
    # subdir, or home-derived data (managed skills, workspace/MEMORY.md,
    # session-archive, .env) nests one level too deep — the pre-0.5.x layout
    # bug that relocateLegacyDesktopStateLayout() heals.
    assert "OPENSQUILLA_STATE_DIR: desktopHome()," in start
    assert "OPENSQUILLA_STATE_DIR: desktopStateDir()" not in main_ts
    # The generated TOML keeps pinning the runtime state dir to <home>/state so
    # database paths (sessions.db, scheduler.db, agents/) never move.
    assert "state_dir = ${tomlString(desktopStateDir())}" in main_ts


def test_copyable_desktop_cli_targets_the_desktop_home_root() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    cli_invocation = _section(
        main_ts,
        "ipcMain.handle('gateway:cli-invocation'",
        "ipcMain.handle('gateway:reveal-log'",
    )

    # The copyable CLI prefix must resolve the same home-derived files as the
    # gateway child. Passing <home>/state would nest workspace, skills, and
    # other home data one level too deep for pasted commands.
    assert "stateDir: desktopHome()," in cli_invocation
    assert "stateDir: desktopStateDir()," not in cli_invocation


def test_legacy_desktop_layout_relocation_runs_before_gateway_spawn() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function loadControlUi",
    )
    relocation = _section(
        main_ts,
        "function relocateLegacyDesktopStateLayout",
        "function bootPagePath",
    )

    # The one-time relocation must run inside startGateway before onboarding
    # and before the child spawn, while no owned gateway is running.
    relocate_index = start.index("relocateLegacyDesktopStateLayout()")
    assert relocate_index < start.index("await runOnboarding()")
    assert relocate_index < start.index("const child = spawn(")

    # It moves exactly the home-derived legacy entries and flattens the nested
    # state/state tree; the config-pinned databases are never in its move list.
    for entry in (
        "'skills'",
        "'skills-taps.json'",
        "'skills-lock.json'",
        "'workspace'",
        "'session-archive'",
        "'router'",
        "'.env'",
    ):
        assert entry in main_ts
    assert "const nested = join(state, 'state')" in relocation
    for forbidden in ("'sessions.db'", "'scheduler.db'", "'agents'"):
        assert forbidden not in relocation

    # Idempotency and failure semantics: marker short-circuits reruns, and a
    # failed move defers (no marker) instead of stranding half the layout.
    # rindex: the first marker write is the fresh-profile early stamp; the
    # failure gate must precede the final (post-move) marker write.
    assert "const DESKTOP_LAYOUT_MARKER = 'desktop-layout-v2.json'" in main_ts
    assert "if (existsSync(markerPath)) return" in relocation
    assert relocation.index("if (failed)") < relocation.rindex("writeFileSync(markerPath")
    # Collisions are parked, never merged or overwritten.
    assert ".pre-relocation" in relocation


def test_onboarding_migration_ipc_is_guarded_and_prefills_from_imported_config() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    preview = _section(
        main_ts,
        "ipcMain.handle('desktop:onboarding:migrate:preview'",
        "ipcMain.handle('desktop:onboarding:migrate:apply'",
    )
    apply_handler = _section(
        main_ts,
        "ipcMain.handle('desktop:onboarding:migrate:apply'",
        "// Set once the Windows graceful-drain",
    )

    # Same trust boundary as desktop:onboarding:save: the preload bridge is also
    # attached to the Control UI window, so both handlers must refuse outside an
    # awaiting onboarding flow, and must take source path/kind from the main
    # process's own detection rather than the renderer payload.
    for handler in (preview, apply_handler):
        assert "if (!resolveOnboarding) return { ok: false" in handler
        assert "onboardingMigrationCandidate" in handler
        assert "'--source', candidate.path, '--kind', candidate.kind" in handler
        assert "migrateSummaryJson([" in handler
    assert "'--apply'" not in preview
    assert "'--apply'," in apply_handler
    assert "readMigratedProviderPrefill()" in apply_handler
    assert "prefill" in apply_handler

    # Detection happens on the no-credential path only, before the onboarding
    # window is created, and the result is JSON-injected into the page.
    onboarding = _section(main_ts, "async function runOnboarding", "async function pathExists")
    assert (
        "onboardingMigrationCandidate = pendingProviderSetup ? null : "
        "detectLegacyImportCandidate()"
    ) in onboarding
    assert onboarding.index("detectLegacyImportCandidate()") < onboarding.index(
        "new BrowserWindow"
    )
    assert "onboardingHtml(onboardingMigrationCandidate, pendingProviderSetup)" in onboarding


def test_run_migrate_cli_targets_desktop_home_via_bundled_cli() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    migrate = _section(
        main_ts,
        "async function runMigrateCli",
        "async function migrateSummaryJson",
    )

    assert "'migrate', 'opensquilla'" in migrate
    assert "runtime.args.slice(0, -2)" in migrate
    # OPENSQUILLA_STATE_DIR names the OpenSquilla HOME ROOT (the migrator's
    # import target) and must match the gateway spawn: desktopHome(), never the
    # state subdir.
    assert "OPENSQUILLA_STATE_DIR: desktopHome()," in migrate
    assert "OPENSQUILLA_GATEWAY_CONFIG_PATH: desktopConfigPath()," in migrate
    assert "OPENSQUILLA_INSTALL_METHOD: 'desktop'," in migrate
    for env in ("PYTHONUNBUFFERED: '1'", "PYTHONUTF8: '1'", "PYTHONIOENCODING: 'utf-8:replace'"):
        assert env in migrate

    summary_json = _section(
        main_ts,
        "async function migrateSummaryJson",
        "type DesktopMigrationPhase",
    )
    assert "[...extraArgs, '--json']" in summary_json


def test_desktop_migration_run_quiesces_then_restarts_without_forcing_onboarding() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    summary = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:summary'",
        "ipcMain.handle('desktop:migration:run'",
    )
    run = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:run'",
        "ipcMain.handle('desktop:boot:state'",
    )

    # The dry-run summary is read-only and must not touch the running gateway.
    assert "detectLegacyImportCandidate()" in summary
    assert "{ ok: true, candidate: null, report: null }" in summary
    assert "stopGateway" not in summary

    # The apply path quiesces the owned gateway BEFORE the CLI runs, refuses an
    # unmanaged gateway that still serves the profile, then restarts via the
    # boot splash — without forcing onboarding on the next startup.
    assert "stopGateway()" in run
    assert "await waitForGatewayProcessExit(child)" in run
    assert "const exited = await waitForGatewayProcessExit(child)" in run
    assert "if (!exited)" in run
    assert run.index("stopGateway()") < run.index("await runMigrateCli(")
    assert "A gateway is still serving this profile" in run
    assert run.index("(!gatewayProcess || !gatewayState.owned)") < run.index(
        "isQuitting = true"
    )
    assert run.index("A gateway is still serving this profile") < run.index(
        "await runMigrateCli("
    )
    assert "'--apply'" in run
    assert "'--overwrite'" in run
    assert "'--json'" in run
    assert "forceOnboardingOnNextStartup" not in run
    assert "bootError = null" in run
    assert "loadFile(bootPagePath())" in run
    assert "await openOrResumeDesktopApp()" in run
    # The restart happens after the CLI finished, regardless of the outcome.
    assert run.index("await runMigrateCli(") < run.index("loadFile(bootPagePath())")


def test_desktop_migration_detection_respects_matching_completion_marker() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    detection = _section(
        main_ts,
        "function detectLegacyImportCandidate",
        "function bootPagePath",
    )

    assert "sourceWasImportedToTarget" in main_ts
    assert "!sourceWasImportedToTarget(cliHome, desktopHome())" in detection
    assert "sourceWasImportedToTarget(candidate, desktopHome())" in detection
    assert "'.opensquilla-imported.json'" in main_ts
    assert "payload.transaction_id" in main_ts
    assert "join(target, 'migration', 'opensquilla', transactionId, 'report.json')" in main_ts


def test_desktop_boot_recovers_interrupted_import_before_profile_use() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    start = _section(
        main_ts,
        "async function startGateway",
        "async function startGatewayWithPortRecovery",
    )

    assert "function recoverInterruptedDesktopImport" in main_ts
    assert "recoverInterruptedDesktopImport()" in start
    assert "await recoverPendingMigrationReconciliation()" in start
    assert start.index("recoverInterruptedDesktopImport()") < start.index(
        "relocateLegacyDesktopStateLayout()"
    )
    assert start.index("recoverInterruptedDesktopImport()") < start.index("runOnboarding()")


def test_desktop_migration_run_requires_valid_report_and_restarts_in_finally() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    run = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:run'",
        "ipcMain.handle('desktop:boot:state'",
    )

    assert "migrationReportValidationError(report" in run
    assert "migrationReportErrors(report)" in run
    assert "findAppliedReceiptForIntent(intent)" in run
    receipt_branch = run.split("if (receipt)", 1)[1]
    assert "report = receipt.report" in receipt_branch
    assert "migrationVerified = true" in receipt_branch
    assert "finally" in run
    finally_body = run.split("finally", 1)[1]
    assert "isQuitting = false" in finally_body
    assert "await openOrResumeDesktopApp()" in finally_body
    assert "restartOk" in run


def test_desktop_migration_apply_is_bound_to_one_trusted_preview_and_native_overwrite() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    summary = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:summary'",
        "ipcMain.handle('desktop:migration:run'",
    )
    run = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:run'",
        "ipcMain.handle('desktop:migration:last-result'",
    )

    assert "trustedDesktopMigrationPreview = preview" in summary
    assert "payload?.previewId !== preview.id" in run
    assert "DESKTOP_MIGRATION_PREVIEW_TTL_MS" in run
    assert "migrationPreviewAllowsApply(preview.report, overwrite)" in run
    assert "dialog.showMessageBox" in run
    assert "trustedDesktopMigrationPreview = null" in run


def test_desktop_migration_writes_reconciliation_intent_before_apply() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    run = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:run'",
        "ipcMain.handle('desktop:migration:last-result'",
    )
    onboarding_apply = _section(
        main_ts,
        "ipcMain.handle('desktop:onboarding:migrate:apply'",
        "// Set once the Windows graceful-drain",
    )

    for handler, invocation in (
        (run, "await runMigrateCli(["),
        (onboarding_apply, "migrateSummaryJson(["),
    ):
        assert "beginMigrationReconciliationIntent(candidate)" in handler
        assert handler.index("beginMigrationReconciliationIntent(candidate)") < handler.index(
            invocation
        )
        assert "findAppliedReceiptForIntent(intent)" in handler


def test_settings_import_reconciles_or_prompts_for_imported_provider() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    run = _section(
        main_ts,
        "ipcMain.handle('desktop:migration:run'",
        "ipcMain.handle('desktop:boot:state'",
    )
    onboarding = _section(main_ts, "async function runOnboarding", "async function pathExists")
    save = _section(
        main_ts,
        "ipcMain.handle('desktop:onboarding:save'",
        "ipcMain.handle('desktop:onboarding:cancel'",
    )

    assert "reconcileImportedDesktopCredential" in run
    assert "loadPendingMigrationProviderSetup" in onboarding
    assert "pendingProviderSetup" in onboarding
    assert "clearPendingMigrationProviderSetup" in save
    assert "scrubImportedProviderEnvEntry" in save
    assert "onboardingHtml(onboardingMigrationCandidate, pendingProviderSetup)" in onboarding
    assert "desktopSecretStoragePolicyBackend() === 'safeStorage'" in onboarding

    reconcile = _section(
        main_ts,
        "async function reconcileImportedDesktopCredential",
        "async function recoverPendingMigrationReconciliation",
    )
    assert reconcile.index("await saveDesktopCredential(prefill)") < reconcile.index(
        "await scrubImportedProviderEnvEntry(prefill.apiKeyEnv)"
    )
    assert reconcile.index("await scrubImportedProviderEnvEntry") < reconcile.index(
        "await clearPendingMigrationProviderSetup()"
    )

    encryption = _section(main_ts, "function encryptSecret", "function decryptSecret")
    assert "desktopSecretStoragePolicyBackend()" in encryption
    assert "if (availableBackend !== 'safeStorage')" in encryption
    assert "The OS keychain is unavailable" in encryption
    assert "catch {\n      return plainSecret(secret)" not in encryption


def test_migration_locale_keys_exist_in_all_six_locale_blocks() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    desktop_catalog = _section(
        main_ts,
        "const DESKTOP_MESSAGES: Record<DesktopLocale, Record<string, string>> = {",
        "// Runtime string bag",
    )
    script_catalog = _section(
        main_ts,
        "const ONBOARDING_SCRIPT_MESSAGES",
        "function desktopT",
    )

    desktop_keys = [
        "migration.nav.title",
        "migration.nav.sub",
        "migration.step.badge",
        "migration.step.heading",
        "migration.step.subtitle",
        "migration.step.sourceLabel",
        "migration.step.preview",
        "migration.step.import",
        "migration.step.skip",
        "migration.overwriteTitle",
        "migration.overwriteMessage",
        "migration.overwriteDetail",
        "migration.overwriteCancel",
        "migration.overwriteConfirm",
    ]
    for key in desktop_keys:
        assert desktop_catalog.count(f"'{key}':") == 6, key

    script_keys = [
        "migrationPreviewRunning",
        "migrationApplyRunning",
        "migrationItems",
        "migrationPausedJobs",
        "migrationDisk",
        "migrationNotesLabel",
        "migrationPreviewFailed",
        "migrationApplyFailed",
        "migrationDone",
    ]
    for key in script_keys:
        assert script_catalog.count(f"{key}:") == 6, key


def test_onboarding_route_prepends_migration_step_only_when_detected() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    html = _section(main_ts, "function onboardingHtml", "async function runOnboarding")
    route = _section(html, "function routeSteps()", "function routePosition")

    # The detection result is JSON-injected like the message bags; the migration
    # step (screen 5) leads every route only when a legacy home was detected.
    assert "detection: LegacyImportCandidate | null = null" in html
    assert "const migrationCandidate = ${JSON.stringify(detection)};" in html
    assert "return migrationCandidate ? [5, ...base] : base;" in route
    assert 'data-screen="5"' in html
    assert 'data-step-label="5"' in html
    assert "let step = ${detection ? 5 : 0};" in html


def test_migration_preload_bridge_and_progress_channel() -> None:
    main_ts = _read("desktop/electron/src/main.ts")
    preload = _read("desktop/electron/src/preload.cts")

    assert "'desktop:migration:summary'" in preload
    assert "'desktop:migration:run'" in preload
    assert "'desktop:migration:last-result'" in preload
    assert "'desktop:onboarding:migrate:preview'" in preload
    assert "'desktop:onboarding:migrate:apply'" in preload
    assert "onMigrationProgress" in preload
    assert "'desktop:migration:progress'" in preload

    assert "function publishDesktopMigrationProgress" in main_ts
    assert "webContents.send('desktop:migration:progress', payload)" in main_ts
    assert "persistDesktopMigrationResult" in main_ts
