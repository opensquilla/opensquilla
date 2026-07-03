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
    assert "gatewayStartPromise = startGateway().finally" in main_ts
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
    assert "app.on('second-instance', () => {\n    void openOrResumeDesktopApp()" in main_ts
    assert "void app.whenReady().then" in main_ts
    assert "void openOrResumeDesktopApp()" in _section(
        main_ts,
        "void app.whenReady().then",
        "})\n}",
    )

    assert "!gatewayStartPromise && !ready && gatewayProcess && gatewayState.owned" in retry
    assert "stopGateway()" in retry
    assert "void openOrResumeDesktopApp()" in retry


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
    assert "const reusableGateway = await reuseHealthyGatewayState()" in start
    assert start.index("const reusableGateway = await reuseHealthyGatewayState()") < start.index(
        "const overrideUrl"
    )
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

    assert "child.killed" not in stop
    assert "hasGatewayProcessExited(child)" in stop
    assert "if (hasGatewayProcessExited(child)) return" in stop
    assert "if (!hasGatewayProcessExited(child)) child.kill('SIGKILL')" in stop
    assert "let exited = false" in stop
    assert "child.once('exit', () => {\n      exited = true\n    })" in stop


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
    assert "'[privacy]'" in config_writer
    assert (
        "`disable_network_observability = "
        "${credential.disableNetworkObservability ? 'true' : 'false'}`"
        in config_writer
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
    assert "return parseDesktopNetworkObservabilityPrivacyConfig(raw)" in read_config
    assert "return true" in read_config


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
        "prereleases must use 0.5.0-rc1 style, not 0.5.0rc1",
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
    assert "installed app itself will remain" in cleanup
    assert "does not remove the installed app bundle itself" in panel_vue

    en_runtime = en_locale["setup"]["runtime"]
    zh_runtime = zh_locale["setup"]["runtime"]
    assert "desktop data cleanup" in en_runtime["uninstallLabel"]
    assert "uninstalled" not in en_runtime["uninstallDone"].lower()
    assert "remove OpenSquilla through your OS" in en_runtime["uninstallDone"]
    assert "清理桌面本地数据" in zh_runtime["uninstallLabel"]
    assert "已卸载" not in zh_runtime["uninstallDone"]
