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
