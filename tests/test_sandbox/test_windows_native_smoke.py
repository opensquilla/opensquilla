from __future__ import annotations

import os
import shutil
import sys
import uuid
from dataclasses import replace
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


_RUN_WINDOWS_NATIVE_SMOKE = os.environ.get("OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE") == "1"
_RUN_WINDOWS_WFP_SMOKE = os.environ.get("OPENSQUILLA_RUN_WINDOWS_WFP_SMOKE") == "1"

_native_appcontainer_smoke = pytest.mark.skipif(
    not (_RUN_WINDOWS_NATIVE_SMOKE and _native_appcontainer_ready()),
    reason=(
        "native Windows AppContainer smoke requires "
        "OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE=1 and an available backend"
    ),
)
_native_wfp_smoke = pytest.mark.skipif(
    not (sys.platform.startswith("win") and _RUN_WINDOWS_WFP_SMOKE),
    reason="native Windows WFP smoke requires OPENSQUILLA_RUN_WINDOWS_WFP_SMOKE=1",
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


class _WindowsShellRuntime:
    backend = type("Backend", (), {"name": "windows_appcontainer"})()


@_native_appcontainer_smoke
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


@_native_appcontainer_smoke
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


@_native_appcontainer_smoke
@pytest.mark.asyncio
async def test_native_windows_shell_can_remove_workspace_file() -> None:
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend
    from opensquilla.tools.builtin import shell

    workspace = Path.cwd() / ".tmp" / f"native-windows-shell-remove-{uuid.uuid4().hex}"
    try:
        workspace.mkdir(parents=True)

        async def run_shell_delete(name: str, command_template: str) -> object:
            target = workspace / f"{name}.txt"
            target.write_text("hello", encoding="utf-8")
            argv = shell._sandbox_shell_backend_argv(
                command_template.format(path=target),
                _WindowsShellRuntime(),
            )
            request = SandboxRequest(
                argv=argv,
                cwd=workspace,
                action_kind="shell.exec",
                policy=_policy(workspace),
                env=dict(os.environ),
            )

            result = await WindowsAppContainerBackend().run(request)

            assert result.returncode == 0
            assert result.stderr == ""
            assert target.exists() is False
            return result

        await run_shell_delete(
            "delete-me",
            "Remove-Item -LiteralPath '{path}' -Force -ErrorAction Stop",
        )
        await run_shell_delete(
            "nested-delete-me",
            "powershell -Command \"Remove-Item '{path}'\"",
        )
        await run_shell_delete(
            "bare-path-delete",
            "Remove-Item {path} -Force",
        )
        await run_shell_delete(
            "bare-literal-delete",
            "Remove-Item -LiteralPath {path} -Force",
        )
        await run_shell_delete(
            "nested-bare-delete",
            "powershell -Command \"Remove-Item {path} -Force\"",
        )
        echoed = await run_shell_delete(
            "delete-then-echo",
            "Remove-Item -LiteralPath '{path}' -Force -ErrorAction Stop; "
            "Write-Output deleted",
        )
        assert getattr(echoed, "stdout").strip() == "deleted"
        await run_shell_delete(
            "test-path-delete",
            "if (Test-Path -LiteralPath '{path}') {{ "
            "Remove-Item -LiteralPath '{path}' -Force "
            "}}",
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@_native_appcontainer_smoke
@pytest.mark.asyncio
async def test_native_windows_appcontainer_can_create_missing_file_mount(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend
    from opensquilla.tools.builtin import shell

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside-create.txt"
    policy = _policy(workspace)
    policy = replace(
        policy,
        mounts=policy.mounts
        + (
            MountSpec(
                host_path=target,
                sandbox_path=target,
                mode="rw",
                required=False,
            ),
        ),
    )
    request = SandboxRequest(
        argv=shell._sandbox_shell_backend_argv(
            f'echo hello > "{target}"',
            _WindowsShellRuntime(),
        ),
        cwd=workspace,
        action_kind="shell.exec",
        policy=policy,
        env=dict(os.environ),
    )

    result = await WindowsAppContainerBackend().run(request)

    assert result.returncode == 0
    assert result.stderr == ""
    assert target.read_text(encoding="utf-16").strip() == "hello"


@_native_wfp_smoke
def test_windows_broker_only_egress_native_smoke() -> None:
    from opensquilla.sandbox.backend.windows_wfp import broker_only_egress_smoke_check

    assert broker_only_egress_smoke_check() is True
