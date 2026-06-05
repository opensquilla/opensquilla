from __future__ import annotations

from opensquilla.cli.tui.opentui.bridge import check_opentui_host_available


def test_missing_opentui_host_dependencies_report_install_command(tmp_path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    availability = check_opentui_host_available(package_dir=package_dir, runtime_bin="bun")

    assert availability.available is False
    assert availability.reason is not None
    assert "@opentui/core" in availability.reason
    assert f"npm install --prefix {package_dir}" in availability.reason
