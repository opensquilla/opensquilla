from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from opensquilla.application.approval_queue import ApprovalQueue
from opensquilla.sandbox.elevation import (
    ElevationAction,
    consume_approved_elevation,
    gate_elevated_action,
    request_elevation,
)


def _shell_action(command: str, *, cwd: str = "/home/lrk/opensquilla") -> ElevationAction:
    return ElevationAction(
        tool_name="exec_command",
        action_kind="shell.exec",
        argv=("sh", "-lc", command),
        cwd=cwd,
        sandbox_permissions="require_escalated",
        justification="Perform the exact operation requested by the user.",
        target_paths=(("/home/lrk/Desktop/probe", "write"),),
    )


def test_elevation_action_fingerprint_binds_side_effect_fields() -> None:
    action = _shell_action("touch /home/lrk/Desktop/probe")

    assert action.fingerprint() == action.fingerprint()
    assert replace(action, cwd="/tmp").fingerprint() != action.fingerprint()
    assert (
        replace(action, argv=("sh", "-lc", "rm /home/lrk/Desktop/probe")).fingerprint()
        != action.fingerprint()
    )
    assert (
        replace(action, target_paths=(("/home/lrk/Desktop/other", "write"),)).fingerprint()
        != action.fingerprint()
    )


def test_elevation_action_round_trips_canonical_payload() -> None:
    action = replace(
        _shell_action("touch /home/lrk/Desktop/probe"),
        network_targets=("example.com",),
        content_digest="sha256:abc",
        tty=True,
        prefix_rule=("touch",),
    )

    restored = ElevationAction.from_canonical_payload(action.canonical_payload())

    assert restored == action
    assert restored.fingerprint() == action.fingerprint()


def test_request_elevation_is_non_human_actionable_for_auto_review(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    action = _shell_action("touch /home/lrk/Desktop/probe")
    try:
        pending = request_elevation(
            queue,
            action,
            session_key="session-1",
            reviewer="auto_review",
        )

        entry = queue.get(pending.approval_id or "")
        assert pending.status == "approval_required"
        assert entry.params["approvalKind"] == "sandbox_elevation"
        assert entry.params["reviewer"] == "auto_review"
        assert entry.params["humanActionable"] is False
        assert entry.params["fingerprint"] == action.fingerprint()
        assert "touch /home/lrk/Desktop/probe" in entry.params["action"]["argv"]
    finally:
        queue.close()


def test_duplicate_pending_elevation_reuses_approval(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    action = _shell_action("touch /home/lrk/Desktop/probe")
    try:
        first = request_elevation(queue, action, session_key="session-1")
        second = request_elevation(queue, action, session_key="session-1")

        assert second.status == "approval_pending"
        assert second.approval_id == first.approval_id
        assert len(queue.list_pending("exec")) == 1
    finally:
        queue.close()


def test_approved_elevation_is_consumed_once(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    action = _shell_action("touch /home/lrk/Desktop/probe")
    try:
        pending = request_elevation(queue, action, session_key="session-1")
        queue.resolve(pending.approval_id or "", True)

        decision = consume_approved_elevation(queue, pending.approval_id or "", action)

        assert decision.allowed is True
        assert decision.status == "approved"
        assert queue.get(pending.approval_id or "").consumed is True
        with pytest.raises(ValueError, match="already consumed"):
            consume_approved_elevation(queue, pending.approval_id or "", action)
    finally:
        queue.close()


def test_approved_elevation_rejects_changed_action_without_consuming(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    original = _shell_action("touch /home/lrk/Desktop/probe")
    changed = _shell_action("rm -rf /home/lrk/Desktop")
    try:
        pending = request_elevation(queue, original, session_key="session-1")
        queue.resolve(pending.approval_id or "", True)

        decision = consume_approved_elevation(queue, pending.approval_id or "", changed)

        assert decision.allowed is False
        assert decision.reason == "approval_action_mismatch"
        assert queue.get(pending.approval_id or "").consumed is False
    finally:
        queue.close()


def test_denied_elevation_returns_reviewer_rationale(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    action = _shell_action("rm -rf /home/lrk/Desktop")
    try:
        pending = request_elevation(queue, action, session_key="session-1")
        entry = queue.get(pending.approval_id or "")
        entry.params["reviewRationale"] = "The recursive delete has an uncertain target."
        queue.update_params(entry.approval_id, entry.params)
        queue.resolve(entry.approval_id, False)

        decision = consume_approved_elevation(queue, entry.approval_id, action)

        assert decision.allowed is False
        assert decision.status == "approval_denied"
        assert decision.reason == "The recursive delete has an uncertain target."
    finally:
        queue.close()


def test_request_elevation_requires_justification(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    try:
        with pytest.raises(ValueError, match="justification_required"):
            request_elevation(
                queue,
                replace(_shell_action("true"), justification=""),
                session_key="session-1",
            )
    finally:
        queue.close()


def test_gate_elevated_action_ignores_default_sandbox_intent(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    try:
        decision = gate_elevated_action(
            replace(_shell_action("true"), sandbox_permissions="use_default"),
            approval_id=None,
            session_key="session-1",
            queue=queue,
        )

        assert decision.requested is False
        assert decision.allowed is False
        assert decision.status == "use_default"
        assert queue.list_pending() == []
    finally:
        queue.close()


def test_gate_elevated_action_requests_then_consumes_exact_approval(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    action = _shell_action("touch /home/lrk/Desktop/probe")
    try:
        pending = gate_elevated_action(
            action,
            approval_id=None,
            session_key="session-1",
            queue=queue,
            reviewer="auto_review",
        )
        queue.resolve(pending.approval_id or "", True)

        approved = gate_elevated_action(
            action,
            approval_id=pending.approval_id,
            session_key="session-1",
            queue=queue,
            reviewer="auto_review",
        )

        assert approved.allowed is True
        assert queue.get(pending.approval_id or "").consumed is True
    finally:
        queue.close()
