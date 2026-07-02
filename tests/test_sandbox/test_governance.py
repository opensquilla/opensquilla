from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.governance import (
    ApprovalGate,
    DenialLedger,
    action_fingerprint,
    gate_execution,
)
from opensquilla.sandbox.types import (
    ALLOW,
    DenialReason,
    DenialResult,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
    SuggestedNextStep,
)


class _NeverAskedQueue:
    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        raise AssertionError("approval queue should not be used by these policies")

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        raise AssertionError("approval queue should not be used by these policies")

    def resolve(self, approval_id: str, approved: bool) -> None:
        raise AssertionError("approval queue should not be used by these policies")


class _PolicyDenyingGate:
    async def gate(
        self,
        request: SandboxRequest,
        policy: SandboxPolicy,
        *,
        session_id: str,
        extra_params: dict[str, object] | None = None,
    ) -> DenialResult:
        return DenialResult(
            reason=DenialReason.POLICY_DENIED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=SecurityLevel.STANDARD,
            action_fingerprint=action_fingerprint(request),
            message="network is disabled",
        )


def _policy() -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=(),
        require_approval=False,
    )


def _request(action_kind: str, argv: tuple[str, ...], tmp_path: Path) -> SandboxRequest:
    policy = _policy()
    return SandboxRequest(
        argv=argv,
        cwd=tmp_path,
        action_kind=action_kind,
        policy=policy,
    )


@pytest.mark.asyncio
async def test_web_policy_denials_do_not_pause_unrelated_sandbox_actions(
    tmp_path: Path,
) -> None:
    ledger = DenialLedger(threshold=3)

    for i in range(3):
        decision = await gate_execution(
            _request("network.http", ("http_request", f"https://example.com/{i}"), tmp_path),
            _policy(),
            session_id="s1",
            ledger=ledger,
            approval_gate=_PolicyDenyingGate(),  # type: ignore[arg-type]
        )

        assert isinstance(decision, DenialResult)
        assert decision.reason == DenialReason.POLICY_DENIED

    decision = await gate_execution(
        _request("shell.exec", ("true",), tmp_path),
        _policy(),
        session_id="s1",
        ledger=ledger,
        approval_gate=ApprovalGate(_NeverAskedQueue()),
    )

    assert decision is ALLOW
