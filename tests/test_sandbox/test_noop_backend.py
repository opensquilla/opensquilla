from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.safety.sandbox import HAS_RESOURCE
from opensquilla.sandbox.backend.noop import NoopBackend
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(MountSpec(host_path=workspace, sandbox_path=Path("/workspace"), mode="rw"),),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=5.0),
        env_allowlist=("PATH",),
        require_approval=False,
    )


@pytest.mark.skipif(not HAS_RESOURCE, reason="noop backend safety runner is POSIX-only")
@pytest.mark.asyncio
async def test_noop_backend_preserves_request_stdin(tmp_path: Path) -> None:
    request = SandboxRequest(
        argv=(
            sys.executable,
            "-c",
            "import sys; print('STDIN:' + sys.stdin.read())",
        ),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        stdin=b"payload",
    )

    result = await NoopBackend().run(request)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["STDIN:payload"]


@pytest.mark.skipif(not HAS_RESOURCE, reason="noop backend safety runner is POSIX-only")
@pytest.mark.asyncio
async def test_noop_backend_preserves_binary_request_stdin(tmp_path: Path) -> None:
    request = SandboxRequest(
        argv=(
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.buffer.read().hex())",
        ),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        stdin=b"\xff\x00abc",
    )

    result = await NoopBackend().run(request)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["ff00616263"]
