"""Per-profile logon autostart on Windows, macOS, and Linux.

Issue #193 asks for OpenSquilla to register a startup entry on Windows
when a new agent profile is created. This module extends the same
contract to macOS (LaunchAgent) and Linux (systemd --user unit) so
the surface is consistent across the three host platforms the CLI
advertises as supported.

The dispatch table is deliberately small:

* Windows: subprocess-out to ``scripts/supervisor/install-autostart.ps1``
  with a per-profile ``-TaskName``. The script writes a Task Scheduler
  logon task that runs the per-profile ``opensquilla --profile <name>
  gateway start`` command on the next interactive logon.
* macOS:   drop a LaunchAgent plist in ``~/Library/LaunchAgents/`` and
  ``launchctl load -w`` it. The plist invokes the same ``opensquilla
  --profile <name> gateway start`` command at load time.
* Linux:   drop a systemd --user unit in
  ``~/.config/systemd/user/`` and ``systemctl --user enable --now`` it.

All three paths require the ``opensquilla`` executable on ``PATH``
(``uv tool install opensquilla`` for end users; the dev install
wrapper installs the editable shim). When the binary is missing the
caller is expected to surface a clear error from the
``AutostartError`` raised here, rather than silently leaving the
profile un-autostarted.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Name of the per-profile logon task. Used on Windows (Task Scheduler
# task name) and as a prefix on the unit / plist filename on Linux and
# macOS so operators can grep for it during debugging.
TASK_NAME_PREFIX = "OpenSquilla_"


def task_name_for_profile(profile: str) -> str:
    """Return the platform-friendly autostart name for a profile."""
    return f"{TASK_NAME_PREFIX}{profile}"


class AutostartError(RuntimeError):
    """Raised when an autostart registration fails for any reason."""


class PlatformNotSupportedError(AutostartError, NotImplementedError):
    """Raised when the host OS is not one of {Windows, Darwin, Linux}."""


@dataclass(frozen=True)
class AutostartResult:
    """A successful per-profile autostart registration."""

    platform: str
    profile: str
    target: str  # Task name (Windows) or absolute path (macOS / Linux)
    command: str  # The exact command the host will run on next logon

    def summary(self) -> str:
        return (
            f"{self.platform} autostart registered for profile {self.profile!r}: "
            f"target={self.target}; command={self.command}"
        )


def _supervisor_dir() -> Path:
    """Locate scripts/supervisor/ relative to this file."""
    here = Path(__file__).resolve()
    # .../src/opensquilla/cli/autostart.py -> .../scripts/supervisor/
    repo_root = here.parents[3]
    return repo_root / "scripts" / "supervisor"


def _resolve_opensquilla_executable() -> str:
    """Return the absolute path to the `opensquilla` binary on PATH.

    Raises AutostartError with a clear remediation hint if the binary
    is not installed.
    """
    found = shutil.which("opensquilla")
    if found is None:
        raise AutostartError(
            "`opensquilla` is not on PATH. Install it first "
            "(`uv tool install opensquilla` for release, or run "
            "`bash scripts/dev-install.sh` from the repo checkout) "
            "and then re-run the autostart registration."
        )
    return found


def _per_profile_command(opensquilla_path: str, profile: str) -> list[str]:
    """The command line the host will run on next logon / load."""
    return [
        opensquilla_path,
        "--profile",
        profile,
        "gateway",
        "start",
    ]


# --- Windows -----------------------------------------------------------------


_WINDOWS_PS_REGISTER_TASK = """\
$ErrorActionPreference = 'Stop'
$taskName = '{task_name}'
$opensquillaPath = '{opensquilla_path}'
$profile = '{profile}'
$home = '{home}'

$action = New-ScheduledTaskAction `
    -Execute $opensquillaPath `
    -Argument "--profile {profile} gateway start" `
    -WorkingDirectory $home

$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "OpenSquilla profile {profile} gateway supervisor (auto-start at logon)" `
    -Force | Out-Null
"""


def _register_windows(profile: str, home: Path) -> AutostartResult:
    """Register a per-profile Task Scheduler logon task via Register-ScheduledTask.

    Why not scripts/supervisor/install-autostart.ps1? That script
    always invokes start-all.ps1 (one task, all profiles). Per-profile
    autostart (issue #193) wants one task per profile, so we call the
    underlying PowerShell cmdlet directly. The behaviour is otherwise
    the same as install-autostart.ps1 (AtLogOn trigger, no UAC prompt,
    RunOnly-If-LoggedOn via the Interactive task setting, 10-minute
    execution time limit).
    """
    task_name = task_name_for_profile(profile)
    opensquilla_path = _resolve_opensquilla_executable()

    script = _WINDOWS_PS_REGISTER_TASK.format(
        task_name=task_name,
        opensquilla_path=opensquilla_path,
        profile=profile,
        home=str(home),
    )
    completed = subprocess.run(  # noqa: S603 — intentional external invocation
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AutostartError(
            f"Register-ScheduledTask failed (exit {completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return AutostartResult(
        platform="Windows",
        profile=profile,
        target=task_name,
        command=(
            f"Register-ScheduledTask -TaskName {task_name} -Action "
            f"{opensquilla_path} --profile {profile} gateway start ..."
        ),
    )


# --- macOS -------------------------------------------------------------------


_LAUNCH_AGENT_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.opensquilla.{label}</string>
  <key>ProgramArguments</key>
  <array>
{program_args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>{home}</string>
  <key>StandardOutPath</key>
  <string>{home}/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>{home}/logs/launchd.err.log</string>
</dict>
</plist>
"""


def _plist_program_args(opensquilla_path: str, profile: str) -> str:
    args = _per_profile_command(opensquilla_path, profile)
    return "\n".join(f"    <string>{arg}</string>" for arg in args)


def _register_macos(profile: str, home: Path) -> AutostartResult:
    """Write a per-profile LaunchAgent plist and `launchctl load -w` it."""
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    target = agents_dir / f"com.opensquilla.{profile}.plist"

    opensquilla_path = _resolve_opensquilla_executable()
    plist = _LAUNCH_AGENT_TEMPLATE.format(
        label=profile,
        program_args=_plist_program_args(opensquilla_path, profile),
        home=str(home),
    )
    target.write_text(plist, encoding="utf-8")

    load = subprocess.run(  # noqa: S603
        ["launchctl", "load", "-w", str(target)],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if load.returncode != 0:
        raise AutostartError(
            f"launchctl load -w failed (exit {load.returncode}): "
            f"{(load.stderr or load.stdout).strip()}"
        )
    return AutostartResult(
        platform="Darwin",
        profile=profile,
        target=str(target),
        command=f"launchctl load -w {target}",
    )


# --- Linux -------------------------------------------------------------------


_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=OpenSquilla profile {profile} gateway supervisor
After=network-online.target

[Service]
Type=simple
WorkingDirectory={home}
ExecStart={exec_start}
StandardOutput=append:{home}/logs/systemd.out.log
StandardError=append:{home}/logs/systemd.err.log
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
"""


def _systemd_exec_start(opensquilla_path: str, profile: str) -> str:
    args = _per_profile_command(opensquilla_path, profile)
    return " ".join(args)


def _register_linux(profile: str, home: Path) -> AutostartResult:
    """Write a per-profile systemd --user unit and `enable --now` it."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    target = unit_dir / f"opensquilla-{profile}.service"

    opensquilla_path = _resolve_opensquilla_executable()
    unit = _SYSTEMD_UNIT_TEMPLATE.format(
        profile=profile,
        exec_start=_systemd_exec_start(opensquilla_path, profile),
        home=str(home),
    )
    target.write_text(unit, encoding="utf-8")

    reload = subprocess.run(  # noqa: S603
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if reload.returncode != 0:
        raise AutostartError(
            f"systemctl --user daemon-reload failed (exit {reload.returncode}): "
            f"{(reload.stderr or reload.stdout).strip()}"
        )
    on = subprocess.run(  # noqa: S603
        ["systemctl", "--user", "enable", "--now", target.name],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if on.returncode != 0:
        raise AutostartError(
            f"systemctl --user enable --now failed (exit {on.returncode}): "
            f"{(on.stderr or on.stdout).strip()}"
        )
    return AutostartResult(
        platform="Linux",
        profile=profile,
        target=str(target),
        command=f"systemctl --user enable --now {target.name}",
    )


# --- Dispatch ----------------------------------------------------------------


def register_logon_task(*, profile: str, home: Path) -> AutostartResult:
    """Register a per-profile startup entry on the host platform.

    See the module docstring for the per-platform contract.
    """
    system = platform.system()
    if system == "Windows":
        return _register_windows(profile, home)
    if system == "Darwin":
        return _register_macos(profile, home)
    if system == "Linux":
        return _register_linux(profile, home)
    raise PlatformNotSupportedError(
        f"per-profile autostart is not implemented for host platform "
        f"{system!r}; supported: Windows, Darwin, Linux."
    )
