from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import (
    configure_runtime,
    escalate_backend_denial,
    reset_runtime,
)
from opensquilla.sandbox.run_context import RunContext
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
    DenialReason,
    DenialResult,
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    SecurityLevel,
)
from opensquilla.tools.types import ToolContext, current_tool_context


def _policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(MountSpec(host_path=workspace, sandbox_path=Path("/workspace"), mode="rw"),),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=("PATH",),
        require_approval=False,
    )


def _request(workspace: Path, policy: SandboxPolicy) -> SandboxRequest:
    return SandboxRequest(
        argv=("sh", "-c", "echo hi"),
        cwd=workspace,
        action_kind="shell.exec",
        policy=policy,
    )


def _result_with_notes(notes: tuple[str, ...]) -> SandboxResult:
    return SandboxResult(
        returncode=1,
        stdout="",
        stderr="sandbox-exec: execvp() of '/opt/brew/bin/uv' failed: Operation not permitted",
        wall_time_s=0.1,
        backend_used="seatbelt",
        backend_notes=notes,
    )


class _ApproveQueue:
    def __init__(self, approve: bool) -> None:
        self._approve = approve
        self.last_params: dict | None = None

    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        self.last_params = params
        return "approval:test"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        return self._approve

    def resolve(self, approval_id: str, approved: bool) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset() -> None:
    yield
    reset_runtime()


@pytest.mark.asyncio
async def test_sandbox_backend_denial_does_not_route_to_host_once(tmp_path: Path) -> None:
    queue = _ApproveQueue(approve=True)
    configure_runtime(
        SandboxSettings(sandbox=True, backend="noop", security_grading=False),
        approval_queue=queue,
        workspace=tmp_path,
    )
    policy = _policy(tmp_path)
    request = _request(tmp_path, policy)
    result = _result_with_notes(("execve.denied: sandbox blocked execve of /opt/brew/bin/uv",))

    decision = await escalate_backend_denial(result, request, policy)

    assert isinstance(decision, DenialResult)
    assert decision.reason == DenialReason.SEATBELT_DENIED
    assert decision.retryable is False
    assert queue.last_params is None


@pytest.mark.asyncio
async def test_full_host_access_does_not_route_backend_failure_to_host_once(
    tmp_path: Path,
) -> None:
    queue = _ApproveQueue(approve=True)
    configure_runtime(
        SandboxSettings(
            sandbox=False,
            backend="noop",
            security_grading=False,
            run_mode="full",
        ),
        approval_queue=queue,
        workspace=tmp_path,
    )
    policy = _policy(tmp_path)
    request = _request(tmp_path, policy)
    result = _result_with_notes(("execve.denied: sandbox blocked execve of /bin/sh",))

    decision = await escalate_backend_denial(result, request, policy)

    assert isinstance(decision, DenialResult)
    assert queue.last_params is None


@pytest.mark.asyncio
async def test_current_run_context_full_host_access_skips_backend_host_once(
    tmp_path: Path,
) -> None:
    queue = _ApproveQueue(approve=True)
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            backend="noop",
            security_grading=True,
            run_mode="standard",
        ),
        approval_queue=queue,
        workspace=tmp_path,
    )
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(tmp_path),
            sandbox_run_context=RunContext(run_mode=RunMode.FULL),
        )
    )
    try:
        policy = _policy(tmp_path)
        request = _request(tmp_path, policy)
        result = _result_with_notes(("execve.denied: sandbox blocked execve of /bin/sh",))

        decision = await escalate_backend_denial(result, request, policy)
    finally:
        current_tool_context.reset(token)

    assert isinstance(decision, DenialResult)
    assert queue.last_params is None


@pytest.mark.asyncio
async def test_current_tool_context_full_host_access_skips_backend_host_once(
    tmp_path: Path,
) -> None:
    queue = _ApproveQueue(approve=True)
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            backend="noop",
            security_grading=True,
            run_mode="standard",
        ),
        approval_queue=queue,
        workspace=tmp_path,
    )
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(tmp_path),
            run_mode="full",
        )
    )
    try:
        policy = _policy(tmp_path)
        request = _request(tmp_path, policy)
        result = _result_with_notes(("execve.denied: sandbox blocked execve of /bin/sh",))

        decision = await escalate_backend_denial(result, request, policy)
    finally:
        current_tool_context.reset(token)

    assert isinstance(decision, DenialResult)
    assert queue.last_params is None


@pytest.mark.asyncio
async def test_escalate_returns_denial_without_host_once_prompt(tmp_path: Path) -> None:
    configure_runtime(
        SandboxSettings(sandbox=True, backend="noop", security_grading=False),
        approval_queue=_ApproveQueue(approve=True),
        workspace=tmp_path,
    )
    policy = _policy(tmp_path)
    result = _result_with_notes(("execve.denied: sandbox blocked execve of /bin/sh",))

    decision = await escalate_backend_denial(result, _request(tmp_path, policy), policy)

    assert isinstance(decision, DenialResult)
    assert decision.reason == DenialReason.SEATBELT_DENIED


@pytest.mark.asyncio
async def test_escalate_returns_seatbelt_denied_on_rejection(tmp_path: Path) -> None:
    configure_runtime(
        SandboxSettings(sandbox=True, backend="noop", security_grading=False),
        approval_queue=_ApproveQueue(approve=False),
        workspace=tmp_path,
    )
    policy = _policy(tmp_path)
    result = _result_with_notes(("filesystem.read: sandbox blocked access to /etc/ssl/cert.pem",))

    decision = await escalate_backend_denial(result, _request(tmp_path, policy), policy)

    assert isinstance(decision, DenialResult)
    assert decision.reason == DenialReason.SEATBELT_DENIED
    assert decision.retryable is False


@pytest.mark.asyncio
async def test_escalate_no_runtime_returns_seatbelt_denied(tmp_path: Path) -> None:
    reset_runtime()
    policy = _policy(tmp_path)
    result = _result_with_notes(("execve.denied: sandbox blocked execve of /bin/uv",))

    decision = await escalate_backend_denial(result, _request(tmp_path, policy), policy)

    assert isinstance(decision, DenialResult)
    assert decision.reason == DenialReason.SEATBELT_DENIED
    assert decision.retryable is False
