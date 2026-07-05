from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.governance import ALLOW, ApprovalGate
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


class _RecordingQueue:
    """Fake approval queue that records whether an approval was enqueued."""

    def __init__(self) -> None:
        self.requested = False

    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        self.requested = True
        return "approval-1"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        raise AssertionError("approval should not be awaited in this test")

    def resolve(self, approval_id: str, approved: bool) -> None:  # pragma: no cover
        raise AssertionError("resolve should not be called in this test")


def _policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(MountSpec(host_path=workspace, sandbox_path=Path("/workspace"), mode="rw"),),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=5.0),
        env_allowlist=("PATH",),
        require_approval=True,
    )


@pytest.mark.asyncio
async def test_gate_enqueues_when_approval_required(tmp_path: Path) -> None:
    # Every approval-requiring action enqueues a fresh approval and allows only
    # after a human approves — there is no intent-level suppression ("Allow
    # always" was a removed no-op).
    request = SandboxRequest(
        argv=("shell.exec", f"rm {tmp_path / 'x'}"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
    )

    class _ResolvingQueue(_RecordingQueue):
        async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
            return True

    queue = _ResolvingQueue()
    gate = ApprovalGate(queue)

    decision = await gate.gate(request, request.policy, session_id="s1")

    assert decision is ALLOW
    assert queue.requested is True
