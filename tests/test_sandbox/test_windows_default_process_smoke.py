from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32"
    or os.environ.get("OPENSQUILLA_RUN_WINDOWS_SANDBOX_SMOKE") != "1",
    reason="Windows sandbox native smoke tests require explicit opt-in",
)


def _policy() -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=10),
        env_allowlist=(
            "PATH",
            "SystemRoot",
            "WINDIR",
            "ComSpec",
            "TEMP",
            "TMP",
            "ProgramData",
            "ProgramFiles",
            "ProgramFiles(x86)",
        ),
        require_approval=False,
    )


def _request(
    tmp_path: Path, argv: tuple[str, ...], stdin: bytes | None = None
) -> SandboxRequest:
    return SandboxRequest(
        argv=argv,
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(),
        stdin=stdin,
        env=dict(os.environ),
        run_mode=RunMode.TRUSTED.value,
    )


@pytest.mark.asyncio
async def test_windows_default_runs_powershell_write_output(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    result = await WindowsDefaultBackend().run(
        _request(
            tmp_path,
            (
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Write-Output ok",
            ),
        )
    )

    assert result.returncode == 0
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_windows_default_runs_cmd_echo(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    cmd = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    result = await WindowsDefaultBackend().run(
        _request(tmp_path, (str(cmd), "/c", "echo ok"))
    )

    assert result.returncode == 0
    assert "ok" in result.stdout.lower()


@pytest.mark.asyncio
async def test_windows_default_passes_stdin(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    result = await WindowsDefaultBackend().run(
        _request(
            tmp_path,
            (
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$input | ForEach-Object { Write-Output $_ }",
            ),
            stdin=b"stdin-ok\r\n",
        )
    )

    assert result.returncode == 0
    assert "stdin-ok" in result.stdout


@pytest.mark.asyncio
async def test_windows_default_runs_shell_host_nested_powershell_env_probe(
) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend
    from opensquilla.tools.builtin import shell

    workspace = Path.home() / ".opensquilla" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    runtime = SimpleNamespace(backend=SimpleNamespace(name="windows_default"))
    command = (
        "powershell -NoProfile -Command "
        "\"Write-Output ('HTTP_PROXY=' + $env:HTTP_PROXY); "
        "Write-Output ('HTTPS_PROXY=' + $env:HTTPS_PROXY); "
        "Write-Output ('NO_PROXY=' + $env:NO_PROXY); "
        "Write-Output ('OPENSQUILLA_SANDBOX_NETWORK=' + "
        "$env:OPENSQUILLA_SANDBOX_NETWORK); "
        "Write-Output ('PWD=' + (Get-Location).Path)\""
    )
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=20),
        env_allowlist=(
            "PATH",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "OPENSQUILLA_SANDBOX_NETWORK",
        ),
        require_approval=False,
    )
    policy = shell._policy_with_windows_shell_runtime_mounts(policy, runtime)
    result = await WindowsDefaultBackend().run(
        SandboxRequest(
            argv=shell._sandbox_shell_backend_argv(command, runtime, cwd=workspace),
            cwd=workspace,
            action_kind="shell.exec",
            policy=policy,
            env={
                **os.environ,
                "HTTP_PROXY": "http://127.0.0.1:48123",
                "HTTPS_PROXY": "http://127.0.0.1:48123",
                "NO_PROXY": "localhost,127.0.0.1",
                "OPENSQUILLA_SANDBOX_NETWORK": "proxy_allowlist",
            },
            run_mode=RunMode.TRUSTED.value,
        )
    )

    assert result.returncode == 0
    assert "HTTP_PROXY=http://127.0.0.1:48123" in result.stdout
    assert "HTTPS_PROXY=http://127.0.0.1:48123" in result.stdout
    assert "OPENSQUILLA_SANDBOX_NETWORK=proxy_allowlist" in result.stdout
    assert f"PWD={workspace}" in result.stdout
    assert result.stderr == ""
