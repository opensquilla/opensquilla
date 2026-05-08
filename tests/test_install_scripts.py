from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_scripts_force_refresh_local_uv_tool_package() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "'--force', '--reinstall-package', 'opensquilla'" in ps1
    assert "--force --reinstall-package opensquilla" in sh


def test_install_scripts_support_optional_extras() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "OPENSQUILLA_INSTALL_EXTRAS" in ps1
    assert "[string[]]$Extras" in ps1
    assert "'feishu'" in ps1
    assert "OPENSQUILLA_INSTALL_EXTRAS" in sh
    assert "--extras" in sh
    assert "feishu telegram dingtalk wecom qq msteams matrix matrix-e2e document-extras" in sh
