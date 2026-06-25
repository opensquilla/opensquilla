from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE") != "1",
    reason="set OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE=1 to run native Windows sandbox smoke tests",
)


def _policy() -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=20),
        env_allowlist=(
            "PATH",
            "TEMP",
            "TMP",
            "PIP_CACHE_DIR",
            "SystemRoot",
            "WINDIR",
            "ComSpec",
        ),
        require_approval=False,
    )


def _request(
    tmp_path: Path,
    argv: tuple[str, ...],
    *,
    run_mode: RunMode = RunMode.TRUSTED,
) -> SandboxRequest:
    return SandboxRequest(
        argv=argv,
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(),
        env=dict(os.environ),
        run_mode=run_mode.value,
    )


@pytest.mark.asyncio
async def test_windows_default_python_can_execute(tmp_path: Path) -> None:
    backend = WindowsDefaultBackend()
    assert backend.available()

    result = await backend.run(_request(tmp_path, (sys.executable, "-c", "print('python-ok')")))

    assert result.returncode == 0
    assert "python-ok" in result.stdout


@pytest.mark.asyncio
async def test_windows_default_workspace_write_succeeds(tmp_path: Path) -> None:
    backend = WindowsDefaultBackend()
    target = tmp_path / "created.txt"

    result = await backend.run(
        _request(
            tmp_path,
            (
                sys.executable,
                "-c",
                f"from pathlib import Path; Path(r'{target}').write_text('ok', encoding='utf-8')",
            ),
        )
    )

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_windows_default_workspace_venv_creation_succeeds(tmp_path: Path) -> None:
    backend = WindowsDefaultBackend()

    result = await backend.run(
        _request(tmp_path, (sys.executable, "-m", "venv", str(tmp_path / ".venv")))
    )

    assert result.returncode == 0
    assert (tmp_path / ".venv").exists()


@pytest.mark.asyncio
async def test_windows_default_proxy_allowlist_without_proxy_fails_closed(
    tmp_path: Path,
) -> None:
    policy = _policy()
    proxy_policy = SandboxPolicy(
        level=policy.level,
        network=NetworkMode.PROXY_ALLOWLIST,
        mounts=policy.mounts,
        workspace_rw=policy.workspace_rw,
        tmp_writable=policy.tmp_writable,
        limits=policy.limits,
        env_allowlist=policy.env_allowlist,
        require_approval=policy.require_approval,
    )
    request = SandboxRequest(
        argv=(sys.executable, "-c", "print('should-not-run')"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=proxy_policy,
        env=dict(os.environ),
        run_mode=RunMode.TRUSTED.value,
    )

    result = await WindowsDefaultBackend().run(request)

    assert result.returncode != 0
    assert "requires network_proxy endpoint" in result.stderr
