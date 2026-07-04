from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import build_request, configure_runtime, reset_runtime
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import NetworkMode, SecurityLevel


class _FakeApprovalQueue:
    def request(self, namespace: str = "exec.approval", params: dict | None = None) -> str:
        return "approval:test"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        return False

    def resolve(self, approval_id: str, approved: bool) -> None:
        return None


def teardown_function() -> None:
    reset_runtime()


def test_build_request_uses_runtime_run_mode_when_no_context(tmp_path: Path) -> None:
    settings = SandboxSettings(run_mode="trusted", backend="noop")
    runtime = configure_runtime(
        settings,
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        runtime.settings,
        trusted=True,
    )

    request = build_request(
        action_kind="shell.exec",
        argv=("cmd", "/c", "echo ok"),
        cwd=tmp_path,
        policy=policy,
    )

    assert request.run_mode == RunMode.TRUSTED.value


def test_managed_network_env_preserves_run_mode(tmp_path: Path) -> None:
    from opensquilla.sandbox.integration import request_with_managed_network_proxy_env
    from opensquilla.sandbox.types import (
        NetworkProxySpec,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
    )

    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=("HTTP_PROXY",),
        require_approval=False,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
    )
    request = SandboxRequest(
        argv=("python", "-c", "print('ok')"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        run_mode=RunMode.STANDARD.value,
    )

    updated = request_with_managed_network_proxy_env(request, backend_name="windows_default")

    assert updated.run_mode == RunMode.STANDARD.value
