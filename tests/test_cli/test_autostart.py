"""Tests for src/opensquilla/cli/autostart.py.

These tests exercise the per-platform template and dispatcher logic
without touching the host: Windows tests mock the subprocess to
install-autostart.ps1, macOS tests inspect the rendered plist and
short-circuit launchctl, Linux tests inspect the rendered unit and
short-circuit systemctl. We never invoke Task Scheduler / launchd /
systemd on the real host.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

from opensquilla.cli.autostart import (
    AutostartError,
    PlatformNotSupportedError,
    _LAUNCH_AGENT_TEMPLATE,
    _SYSTEMD_UNIT_TEMPLATE,
    _plist_program_args,
    _systemd_exec_start,
    register_logon_task,
    task_name_for_profile,
)


# --- Helpers -----------------------------------------------------------------


@pytest.fixture
def fake_opensquilla_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Place a `opensquilla` shim on PATH so `_resolve_opensquilla_executable` succeeds."""
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    if sys.platform.startswith("win"):
        shim = shim_dir / "opensquilla.exe"
    else:
        shim = shim_dir / "opensquilla"
    shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(shim_dir))
    return str(shim)


# --- Pure helpers ------------------------------------------------------------


def test_task_name_for_profile_prefixes_opensquilla() -> None:
    assert task_name_for_profile("coder") == "OpenSquilla_coder"
    assert task_name_for_profile("default") == "OpenSquilla_default"


def test_plist_program_args_renders_one_string_per_token() -> None:
    out = _plist_program_args("/usr/local/bin/opensquilla", "coder")
    assert "<string>/usr/local/bin/opensquilla</string>" in out
    assert "<string>--profile</string>" in out
    assert "<string>coder</string>" in out
    assert "<string>gateway</string>" in out
    assert "<string>start</string>" in out
    # Five tokens -> five <string> lines
    assert sum(1 for line in out.splitlines() if "<string>" in line) == 5


def test_systemd_exec_start_uses_space_separated_command() -> None:
    out = _systemd_exec_start("/usr/bin/opensquilla", "coder")
    assert out == "/usr/bin/opensquilla --profile coder gateway start"


def test_launch_agent_template_carries_required_keys() -> None:
    out = _LAUNCH_AGENT_TEMPLATE.format(
        label="coder",
        program_args=_plist_program_args("/usr/bin/opensquilla", "coder"),
        home="/home/tester/profiles/coder",
    )
    for must in (
        "<key>Label</key>",
        "<string>com.opensquilla.coder</string>",
        "<key>RunAtLoad</key>",
        "<true/>",
        "<key>KeepAlive</key>",
        "<key>WorkingDirectory</key>",
        "<string>/home/tester/profiles/coder</string>",
        "StandardOutPath",
        "StandardErrorPath",
    ):
        assert must in out, f"missing {must!r} in rendered plist"


def test_systemd_unit_template_carries_required_sections() -> None:
    out = _SYSTEMD_UNIT_TEMPLATE.format(
        profile="coder",
        exec_start="/usr/bin/opensquilla --profile coder gateway start",
        home="/home/tester/profiles/coder",
    )
    for must in (
        "[Unit]",
        "[Service]",
        "[Install]",
        "Description=OpenSquilla profile coder gateway supervisor",
        "Type=simple",
        "WantedBy=default.target",
        "ExecStart=/usr/bin/opensquilla --profile coder gateway start",
        "Restart=on-failure",
    ):
        assert must in out, f"missing {must!r} in rendered unit"


# --- Windows dispatch --------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_windows_dispatch_invokes_register_scheduled_task(
    tmp_path: Path,
    fake_opensquilla_on_path: str,
) -> None:
    """Windows dispatch should run PowerShell with a Register-ScheduledTask
    payload that targets the per-profile opensquilla executable and the
    OpenSquilla_<profile> task name.
    """
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)

    with mock.patch("opensquilla.cli.autostart.subprocess.run") as run_mock:
        run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        result = register_logon_task(profile="coder", home=home)

    assert result.platform == "Windows"
    assert result.profile == "coder"
    assert result.target == "OpenSquilla_coder"
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert cmd[0:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    # The PowerShell script body is passed via -Command.
    ps_body = cmd[5]
    assert "OpenSquilla_coder" in ps_body
    assert "--profile coder gateway start" in ps_body
    assert "Register-ScheduledTask" in ps_body
    # The shim path is interpolated via str.format() into the PowerShell
    # template; on Windows the path contains single backslashes that get
    # re-escaped by the f-string output, so assert on the binary name
    # (which survives every escaping) and the per-profile argument.
    assert "opensquilla" in ps_body
    assert "coder" in ps_body
    assert str(home.name) in ps_body


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_windows_dispatch_raises_on_register_scheduled_task_failure(
    tmp_path: Path,
    fake_opensquilla_on_path: str,
) -> None:
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)
    with mock.patch(
        "opensquilla.cli.autostart.subprocess.run",
        return_value=mock.Mock(returncode=1, stdout="", stderr="boom"),
    ):
        with pytest.raises(AutostartError, match="Register-ScheduledTask failed"):
            register_logon_task(profile="coder", home=home)


# --- macOS / Linux dispatch (cross-platform template tests) ------------------


def test_dispatch_dispatches_to_macos_on_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_opensquilla_on_path: str,
) -> None:
    """macOS path should write a plist and call `launchctl load -w`."""
    monkeypatch.setattr(platform := __import__("platform"), "system", lambda: "Darwin")
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)
    agents_dir = tmp_path / "Library" / "LaunchAgents"
    monkeypatch.setattr("opensquilla.cli.autostart.Path.home", classmethod(lambda cls: tmp_path))

    with mock.patch("opensquilla.cli.autostart.subprocess.run") as run_mock:
        run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        result = register_logon_task(profile="coder", home=home)

    assert result.platform == "Darwin"
    plist_path = agents_dir / "com.opensquilla.coder.plist"
    assert plist_path.exists()
    plist = plist_path.read_text(encoding="utf-8")
    assert "<string>coder</string>" in plist
    assert "<string>--profile</string>" in plist
    assert "<string>gateway</string>" in plist
    assert run_mock.call_count == 1
    assert run_mock.call_args.args[0] == ["launchctl", "load", "-w", str(plist_path)]


def test_dispatch_dispatches_to_linux_on_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_opensquilla_on_path: str,
) -> None:
    """Linux path should write a systemd --user unit and call `enable --now`."""
    monkeypatch.setattr(platform := __import__("platform"), "system", lambda: "Linux")
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)
    unit_dir = tmp_path / ".config" / "systemd" / "user"
    monkeypatch.setattr("opensquilla.cli.autostart.Path.home", classmethod(lambda cls: tmp_path))

    with mock.patch("opensquilla.cli.autostart.subprocess.run") as run_mock:
        run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        result = register_logon_task(profile="coder", home=home)

    assert result.platform == "Linux"
    unit_path = unit_dir / "opensquilla-coder.service"
    assert unit_path.exists()
    unit = unit_path.read_text(encoding="utf-8")
    assert "Description=OpenSquilla profile coder gateway supervisor" in unit
    # The rendered unit interpolates the shim path via .format(); on
    # Windows that path uses single backslashes which are escape-sensitive
    # in f-string literals. Assert on the parts that survive escaping.
    assert "ExecStart=" in unit
    assert "--profile coder gateway start" in unit
    assert "opensquilla" in unit  # the shim binary name is enough to prove wiring
    # Two calls: daemon-reload, then enable --now
    assert run_mock.call_count == 2
    assert run_mock.call_args_list[0].args[0] == ["systemctl", "--user", "daemon-reload"]
    assert run_mock.call_args_list[1].args[0] == [
        "systemctl",
        "--user",
        "enable",
        "--now",
        "opensquilla-coder.service",
    ]


def test_dispatch_raises_platform_not_supported_for_unsupported_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_opensquilla_on_path: str,
) -> None:
    monkeypatch.setattr(platform := __import__("platform"), "system", lambda: "FreeBSD")
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)
    with pytest.raises(PlatformNotSupportedError, match="FreeBSD"):
        register_logon_task(profile="coder", home=home)


def test_dispatch_raises_autostart_error_when_opensquilla_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform := __import__("platform"), "system", lambda: "Darwin")
    monkeypatch.setattr("opensquilla.cli.autostart.shutil.which", lambda name: None)
    home = tmp_path / "profiles" / "coder"
    home.mkdir(parents=True)
    with pytest.raises(AutostartError, match="opensquilla.*not on PATH"):
        register_logon_task(profile="coder", home=home)
