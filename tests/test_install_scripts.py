import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PS1 = ROOT / "install.ps1"
RELEASE_SH = ROOT / "install.sh"
SOURCE_PS1 = ROOT / "scripts" / "install_source.ps1"
SOURCE_SH = ROOT / "scripts" / "install_source.sh"
CURRENT_RELEASE_TAG = "v0.3.1"


def test_source_install_scripts_force_refresh_local_uv_tool_package() -> None:
    ps1 = SOURCE_PS1.read_text(encoding="utf-8")
    sh = SOURCE_SH.read_text(encoding="utf-8")

    assert "'--force', '--reinstall-package', 'opensquilla'" in ps1
    assert "--force --reinstall-package opensquilla" in sh


def test_install_scripts_do_not_run_onboarding_or_gateway() -> None:
    scripts = [
        RELEASE_PS1.read_text(encoding="utf-8"),
        RELEASE_SH.read_text(encoding="utf-8"),
        SOURCE_PS1.read_text(encoding="utf-8"),
        SOURCE_SH.read_text(encoding="utf-8"),
    ]

    for script in scripts:
        assert "onboard --if-needed" not in script
        assert "& opensquilla onboard" not in script
        assert "& opensquilla gateway run" not in script
        assert '"opensquilla onboard"' not in script
        assert '"opensquilla gateway run"' not in script


def test_release_installers_install_version_pinned_wheel_with_uv() -> None:
    ps1 = RELEASE_PS1.read_text(encoding="utf-8")
    sh = RELEASE_SH.read_text(encoding="utf-8")

    for script in (ps1, sh):
        assert CURRENT_RELEASE_TAG in script
        assert "opensquilla-$releaseVersion-py3-none-any.whl" in script or (
            "opensquilla-${release_version}-py3-none-any.whl" in script
        )
        assert "opensquilla-latest-py3-none-any.whl" not in script
        assert "releases/latest/download" not in script
        assert "--python" in script
        assert "--force" in script
        assert "--reinstall-package" in script
        assert "recommended" in script
        assert "https://astral.sh/uv/install" in script
        assert "Next steps:" in script


def test_release_installer_rejects_non_release_selectors() -> None:
    ps1 = RELEASE_PS1.read_text(encoding="utf-8")

    if not sys.platform.startswith("win"):
        result = subprocess.run(
            ["bash", "install.sh", "--version", "main"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0
        assert "only supports latest, stable, or release versions" in result.stderr
        assert "scripts/install_source.sh" in result.stderr
    assert "only supports latest, stable, or release versions" in ps1
    assert "scripts/install_source.ps1" in ps1


def test_windows_installer_stops_when_native_install_command_fails() -> None:
    ps1 = SOURCE_PS1.read_text(encoding="utf-8")

    assert 'if ($LASTEXITCODE -ne 0) {' in ps1
    assert "install_source.ps1: install command failed with exit code $LASTEXITCODE." in ps1
    assert (
        "Close any running OpenSquilla gateway or shell using the existing "
        "tool environment, then retry."
        in ps1
    )
    assert "exit $LASTEXITCODE" in ps1


def test_install_script_banners_are_ascii_for_windows_terminals() -> None:
    scripts = [
        RELEASE_PS1.read_text(encoding="utf-8"),
        RELEASE_SH.read_text(encoding="utf-8"),
        SOURCE_PS1.read_text(encoding="utf-8"),
        SOURCE_SH.read_text(encoding="utf-8"),
    ]

    for script in scripts:
        assert "OpenSquilla installed" in script
        assert "----" in script
        assert "→" not in script
        assert "─" not in script
        assert "⚠" not in script


def test_install_scripts_support_optional_extras() -> None:
    scripts = [
        RELEASE_PS1.read_text(encoding="utf-8"),
        RELEASE_SH.read_text(encoding="utf-8"),
        SOURCE_PS1.read_text(encoding="utf-8"),
        SOURCE_SH.read_text(encoding="utf-8"),
    ]

    for script in scripts:
        assert "OPENSQUILLA_INSTALL_EXTRAS" in script
        for legacy_extra in ("feishu", "telegram", "dingtalk", "wecom", "qq"):
            assert legacy_extra not in script
        assert "matrix" in script
        assert "matrix-e2e" in script
        assert "document-extras" in script
        assert "msteams" not in script


def test_windows_installer_bootstraps_vc_redist_for_router_runtime() -> None:
    scripts = [
        RELEASE_PS1.read_text(encoding="utf-8"),
        SOURCE_PS1.read_text(encoding="utf-8"),
    ]

    for ps1 in scripts:
        assert "Install-WindowsVCRedistIfNeeded" in ps1
        assert "OPENSQUILLA_SKIP_VC_REDIST" in ps1
        assert "Microsoft.VCRedist.2015+.x64" in ps1
        assert "https://aka.ms/vs/17/release/vc_redist.x64.exe" in ps1
        assert "safe router fallback" in ps1
        assert "If automatic installation fails, install it manually" in ps1
        assert "After installing, reopen PowerShell and restart OpenSquilla" in ps1
