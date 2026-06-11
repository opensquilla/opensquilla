from __future__ import annotations

import os
import sys
import uuid
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

_RUN_WINDOWS_NATIVE_SMOKE = os.environ.get("OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE") == "1"


def _native_restricted_token_ready() -> bool:
    if not sys.platform.startswith("win") or not _RUN_WINDOWS_NATIVE_SMOKE:
        return False
    try:
        from opensquilla.sandbox.backend.windows_restricted_token import (
            WindowsRestrictedTokenBackend,
        )

        return WindowsRestrictedTokenBackend().available()
    except Exception:
        return False


_native_restricted_token_smoke = pytest.mark.skipif(
    not _native_restricted_token_ready(),
    reason=(
        "native Windows restricted-token smoke requires "
        "OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE=1 and restricted-token readiness"
    ),
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


@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_echo(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    request = SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env=dict(os.environ),
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode == 0
    assert "ok" in result.stdout.lower()


@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_can_write_workspace(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    target = tmp_path / "created.txt"
    request = SandboxRequest(
        argv=("cmd", "/c", f"echo ok>{target}"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env=dict(os.environ),
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8").strip().lower() == "ok"


@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_blocks_write_outside_workspace(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.txt"
    request = SandboxRequest(
        argv=("cmd", "/c", f"echo bad>{outside}"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env=dict(os.environ),
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode != 0 or not outside.exists()
