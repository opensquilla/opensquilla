from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)

_WINDOWS_PROCESS_ENV = (
    "PATH",
    "COMSPEC",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PSModulePath",
)


def _native_appcontainer_ready() -> bool:
    if not sys.platform.startswith("win"):
        return False
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend

    return WindowsAppContainerBackend().available()


pytestmark = pytest.mark.skipif(
    not _native_appcontainer_ready(),
    reason="native Windows AppContainer smoke requires an available backend",
)


def _policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=workspace,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=5.0),
        env_allowlist=_WINDOWS_PROCESS_ENV,
        require_approval=False,
    )


def _powershell() -> str:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return str(
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


@pytest.mark.asyncio
async def test_native_windows_appcontainer_blocks_write_outside_workspace(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend

    workspace = tmp_path / "workspace"
    inside = workspace / "inside.txt"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    script = (
        f"Set-Content -LiteralPath '{inside}' -Value inside; "
        f"Set-Content -LiteralPath '{outside}' -Value escape -ErrorAction Stop"
    )
    request = SandboxRequest(
        argv=(
            _powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ),
        cwd=workspace,
        action_kind="shell.exec",
        policy=_policy(workspace),
        env=dict(os.environ),
    )

    result = await WindowsAppContainerBackend().run(request)

    assert result.returncode != 0
    assert "cannot enforce" not in result.stderr.lower()
    assert "access to the path" in result.stderr.lower()
    assert "unauthorizedaccess" in result.stderr.lower()
    assert inside.read_text(encoding="utf-8").strip() == "inside"
    assert outside.exists() is False


@pytest.mark.asyncio
async def test_native_windows_appcontainer_echo(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend

    request = SandboxRequest(
        argv=(
            _powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "Write-Output ok",
        ),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env=dict(os.environ),
    )

    result = await WindowsAppContainerBackend().run(request)

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
