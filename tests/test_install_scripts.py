from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_scripts_force_refresh_local_uv_tool_package() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "'--force', '--reinstall-package', 'opensquilla'" in ps1
    assert "--force --reinstall-package opensquilla" in sh


def test_source_install_scripts_do_not_run_onboarding() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    for script in (ps1, sh):
        assert "onboard --if-needed" not in script
        assert "opensquilla onboard" not in script


def test_windows_installer_stops_when_native_install_command_fails() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert 'if ($LASTEXITCODE -ne 0) {' in ps1
    assert "install.ps1: install command failed with exit code $LASTEXITCODE." in ps1
    assert (
        "Close any running OpenSquilla gateway or shell using the existing "
        "tool environment, then retry."
        in ps1
    )
    assert "exit $LASTEXITCODE" in ps1


def test_install_script_banners_are_ascii_for_windows_terminals() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    for script in (ps1, sh):
        assert "OpenSquilla installed via" in script
        assert "->" in script
        assert "----" in script
        assert "→" not in script
        assert "─" not in script
        assert "⚠" not in script


def test_install_scripts_support_optional_extras() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "OPENSQUILLA_INSTALL_EXTRAS" in ps1
    assert "[string[]]$Extras" in ps1
    assert "'feishu'" in ps1
    assert "OPENSQUILLA_INSTALL_EXTRAS" in sh
    assert "--extras" in sh
    assert "feishu telegram dingtalk wecom qq msteams matrix matrix-e2e document-extras" in sh


def test_windows_installer_bootstraps_vc_redist_for_router_runtime() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "Install-WindowsVCRedistIfNeeded" in ps1
    assert "OPENSQUILLA_SKIP_VC_REDIST" in ps1
    assert "Microsoft.VCRedist.2015+.x64" in ps1
    assert "https://aka.ms/vs/17/release/vc_redist.x64.exe" in ps1


def test_readme_splits_user_paths_and_documents_preview_release_package() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    release_section = readme.split("### Preview release package", 1)[1]
    release_section = release_section.split("### Install from source", 1)[0]
    release_section_normalized = " ".join(release_section.split())

    assert (
        "| New user | [Preview release package](#preview-release-package) | "
        "Recommended |"
        in readme
    )
    assert (
        "| Command-line user | [Install from source](#install-from-source) | "
        "Available now |"
        in readme
    )
    assert "| Developer | [Develop from source](#develop-from-source) | Available now |" in readme
    assert (
        "Download the preview package if you want to try OpenSquilla as a "
        "local app without cloning the repository or installing Git, Git LFS, "
        "or `uv`." in normalized
    )
    assert "Current preview packages:" in readme
    assert "windows-x64-py312-recommended-portable.zip" in readme
    assert "macos-arm64-py312-recommended-portable.zip" not in readme
    assert "recommended-wheelhouse.zip" not in release_section
    assert "Public release packages are not published yet." not in readme
    assert (
        "For a source checkout instead of a package, use the next section."
        in release_section_normalized
    )
    assert release_section.count("Install from source") == 0


def test_readme_documents_router_defaults_and_feishu_as_channel_extra() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "SquillaRouter is included by default in the preview release packages" in readme
    assert "the normal source install path" in readme
    assert "The normal install commands above already install SquillaRouter." in readme
    assert (
        "The install scripts default to the `recommended` profile, which "
        "installs `.[recommended]`."
        in normalized
    )
    assert "recommended` enables SquillaRouter" in readme
    assert "Install channel extras into the same user-local command" in readme
    assert "The recommended portable zip includes Feishu websocket support by default." in readme
    assert "Feishu websocket channel support" in readme
    assert "Optional: add a channel adapter only if you need one." in readme
    assert "powershell -ExecutionPolicy Bypass -File .\\install.ps1 -Extras feishu" in readme
    assert "OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh" in readme
    assert "Supported channel extras include `dingtalk`, `feishu`" in readme
    assert "The optional non-channel extra is `document-extras`." in normalized
    assert "Most users do not need every chat platform SDK." in normalized


def test_readme_keeps_prerequisite_install_commands_in_optional_details() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "<summary>Optional: install prerequisites from a terminal</summary>" in readme
    assert "winget install --id Git.Git -e" in readme
    assert "winget install --id GitHub.GitLFS -e" in readme
    windows_prereq = readme.split("Windows PowerShell:", 1)[1]
    windows_prereq = windows_prereq.split(
        "macOS, if you already use Homebrew:",
        1,
    )[0]

    assert "git lfs install" in windows_prereq
    assert "brew install git git-lfs uv" in readme
    assert "sudo apt install -y git git-lfs" in readme
    assert "sudo dnf install -y git git-lfs" in readme
    assert "sudo pacman -S --needed git git-lfs" in readme
    assert "https://brew.sh/" in readme
    assert "PATH changes from these installers apply to new terminal sessions." in normalized
    assert (
        "The LFS pull is idempotent: it fetches missing model assets and "
        "exits quietly when the checkout is already complete."
        in normalized
    )
    assert (
        "If `winget` is not present, download and run the Visual C++ installer "
        "manually."
        in normalized
    )
    assert (
        "To persist the key on macOS or Linux, add the same `export` line to "
        "your shell profile."
        in normalized
    )


def test_readme_quickstart_covers_path_key_and_gateway_runtime_gotchas() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    quickstart_config = readme.split("4. Configure.", 1)[1].split("5. Run the gateway:", 1)[0]
    quickstart_config_normalized = " ".join(quickstart_config.split())

    assert "Open a new terminal if `opensquilla` is not found after installation." in readme
    assert "Recommended for beginners:" in readme
    assert "The wizard asks you to choose a provider and enter or reference its API key." in readme
    assert "For automation, this OpenRouter example is copy-pasteable." in readme
    assert (
        "OpenRouter is only an example; substitute any supported provider and "
        "its API key variable."
        in normalized
    )
    assert (
        "If you choose OpenRouter, create a key at "
        "<https://openrouter.ai/docs/api-keys>"
        in normalized
    )
    assert "replace `sk-...` with the real key value" in normalized
    assert (
        "The `export` and `$env:` examples below set the key for the current "
        "terminal only."
        in normalized
    )
    assert quickstart_config_normalized.index(
        "opensquilla onboard"
    ) < quickstart_config_normalized.index("If you choose OpenRouter")
    assert "Press `Ctrl+C` to stop the foreground gateway." in normalized
    assert "Wait until the gateway says it is running before opening the Web UI" in normalized
    assert (
        "the gateway still starts but the bundled router falls back to a safe "
        "direct route"
        in normalized
    )
    assert "If Windows prints an `onnxruntime` or `DLL load failed` warning" in normalized


def test_readme_explains_setup_details_vs_development_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "## Setup details and troubleshooting" in readme
    assert (
        "Setup details expands the Quick start paths; it is not a separate "
        "install path."
        in normalized
    )
    assert "Use the preview release package when you only want to run OpenSquilla." in normalized
    assert (
        "Use Install from source when a package is not available for your "
        "platform or when you want to run the current source tree."
        in normalized
    )
    assert (
        "Use Develop from source only when you want to edit, test, or debug "
        "the code."
        in normalized
    )
    assert "`git lfs install` is idempotent and safe to run again." in readme
    assert "If `opensquilla` is not on `PATH`, use the command path check above." in normalized
    assert "For `uv` installs, refresh the shell with `uv tool update-shell`" in normalized
    assert (
        "for the `pip --user` fallback, add the Python user scripts directory "
        "to `PATH`."
        in normalized
    )
    assert "To check which command your shell will run:" in readme
    assert "where.exe opensquilla" in readme
    assert "command -v opensquilla" in readme
    assert "opensquilla onboard --provider openai --api-key-env OPENAI_API_KEY" in readme


def test_readme_keeps_windows_powershell_commands_restart_safe() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "pwsh -ExecutionPolicy Bypass -File .\\install.ps1" in readme
    assert (
        "If you used only `$env:OPENROUTER_API_KEY`, set it again in the new "
        "PowerShell window."
        in normalized
    )


def test_readme_marks_python_and_pip_as_fallback_prerequisites() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    quickstart_prereqs = readme.split("1. Install prerequisites:", 1)[1]
    quickstart_prereqs = quickstart_prereqs.split("2. Clone with LFS assets:", 1)[0]

    assert "Git and Git LFS. The recommended installer is `uv`." in readme
    assert "Install prerequisites: Git, Git LFS, and uv." not in readme
    assert (
        "If `uv` is unavailable, the installer falls back to Python 3.12+ "
        "with `pip >= 23`."
        in normalized
    )
    assert "Python 3.12+" in quickstart_prereqs
    assert "pip >= 23" in quickstart_prereqs
    assert (
        "not required for the normal `uv` install path. Install it only when "
        "you use the `pip --user` fallback or develop from source."
        in normalized
    )
    assert "**`uv`** — recommended for normal source installs." in readme
    assert "**`pip` >= 23** — fallback only when `uv` is unavailable." in readme
    assert (
        "Unlike Install from source, this development path requires `uv`."
        in readme
    )
