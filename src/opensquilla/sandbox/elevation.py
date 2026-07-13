"""Canonical, fingerprint-bound grants for one elevated tool invocation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from opensquilla.application.approval_queue import ApprovalQueue

SandboxPermissionIntent = Literal["use_default", "require_escalated"]
ApprovalReviewerName = Literal["user", "auto_review"]


@dataclass(frozen=True)
class ElevationAction:
    """The material side effects an approval is allowed to authorize."""

    tool_name: str
    action_kind: str
    argv: tuple[str, ...]
    cwd: str
    sandbox_permissions: SandboxPermissionIntent
    justification: str
    target_paths: tuple[tuple[str, str], ...] = ()
    network_targets: tuple[str, ...] = ()
    content_digest: str | None = None
    content_length: int | None = None
    risk_markers: tuple[str, ...] = ()
    tty: bool = False
    prefix_rule: tuple[str, ...] | None = None

    def canonical_payload(self) -> dict[str, object]:
        """Return the stable JSON-compatible representation used for review."""

        return {
            "tool_name": self.tool_name,
            "action_kind": self.action_kind,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "sandbox_permissions": self.sandbox_permissions,
            "justification": self.justification,
            "target_paths": [list(item) for item in self.target_paths],
            "network_targets": list(self.network_targets),
            "content_digest": self.content_digest,
            "content_length": self.content_length,
            "risk_markers": list(self.risk_markers),
            "tty": self.tty,
            "prefix_rule": list(self.prefix_rule) if self.prefix_rule is not None else None,
        }

    @classmethod
    def from_canonical_payload(cls, payload: dict[str, Any]) -> ElevationAction:
        """Validate and reconstruct a persisted canonical action."""

        sandbox_permissions = str(payload.get("sandbox_permissions") or "")
        if sandbox_permissions not in {"use_default", "require_escalated"}:
            raise ValueError("invalid_sandbox_permissions")
        target_paths: list[tuple[str, str]] = []
        raw_target_paths = payload.get("target_paths", [])
        if not isinstance(raw_target_paths, list):
            raise ValueError("invalid_target_paths")
        for item in raw_target_paths:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("invalid_target_path")
            path, access = (str(value) for value in item)
            if not path or access not in {"read", "write", "delete", "execute"}:
                raise ValueError("invalid_target_path")
            target_paths.append((path, access))

        raw_argv = payload.get("argv", [])
        raw_network_targets = payload.get("network_targets", [])
        raw_risk_markers = payload.get("risk_markers", [])
        raw_prefix_rule = payload.get("prefix_rule")
        if (
            not isinstance(raw_argv, list)
            or not isinstance(raw_network_targets, list)
            or not isinstance(raw_risk_markers, list)
        ):
            raise ValueError("invalid_elevation_action")
        if raw_prefix_rule is not None and not isinstance(raw_prefix_rule, list):
            raise ValueError("invalid_prefix_rule")
        raw_content_length = payload.get("content_length")
        if raw_content_length is not None and (
            isinstance(raw_content_length, bool)
            or not isinstance(raw_content_length, int)
            or raw_content_length < 0
        ):
            raise ValueError("invalid_content_length")

        return cls(
            tool_name=str(payload.get("tool_name") or ""),
            action_kind=str(payload.get("action_kind") or ""),
            argv=tuple(str(item) for item in raw_argv),
            cwd=str(payload.get("cwd") or ""),
            sandbox_permissions=cast("SandboxPermissionIntent", sandbox_permissions),
            justification=str(payload.get("justification") or ""),
            target_paths=tuple(target_paths),
            network_targets=tuple(str(item) for item in raw_network_targets),
            content_digest=(
                str(payload["content_digest"])
                if payload.get("content_digest") is not None
                else None
            ),
            content_length=(
                raw_content_length
                if raw_content_length is not None
                else None
            ),
            risk_markers=tuple(str(item) for item in raw_risk_markers),
            tty=bool(payload.get("tty", False)),
            prefix_rule=(
                tuple(str(item) for item in raw_prefix_rule)
                if raw_prefix_rule is not None
                else None
            ),
        )

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ElevationGateResult:
    requested: bool
    allowed: bool
    status: str
    approval_id: str | None = None
    reason: str | None = None

    def to_envelope(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "requested": self.requested,
            "allowed": self.allowed,
        }
        if self.approval_id:
            payload["approval_id"] = self.approval_id
        if self.reason:
            payload["message"] = self.reason
        return payload


def _pending_elevation_id(
    queue: ApprovalQueue,
    *,
    fingerprint: str,
    session_key: str | None,
) -> str | None:
    for pending in queue.list_pending("exec"):
        params = pending.get("params")
        if not isinstance(params, dict):
            continue
        if params.get("approvalKind") != "sandbox_elevation":
            continue
        if str(params.get("fingerprint") or "") != fingerprint:
            continue
        if str(params.get("sessionKey") or "") != str(session_key or ""):
            continue
        approval_id = str(pending.get("id") or "")
        if approval_id:
            return approval_id
    return None


def request_elevation(
    queue: ApprovalQueue,
    action: ElevationAction,
    *,
    session_key: str | None,
    reviewer: ApprovalReviewerName = "auto_review",
) -> ElevationGateResult:
    """Persist or reuse a pending review for one exact elevated action."""

    if action.sandbox_permissions != "require_escalated":
        raise ValueError("require_escalated_required")
    if not action.justification.strip():
        raise ValueError("justification_required")
    fingerprint = action.fingerprint()
    pending_id = _pending_elevation_id(
        queue,
        fingerprint=fingerprint,
        session_key=session_key,
    )
    if pending_id is not None:
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_pending",
            approval_id=pending_id,
        )

    approval_id = queue.request(
        namespace="exec",
        params={
            "approvalKind": "sandbox_elevation",
            "reviewer": reviewer,
            "humanActionable": reviewer == "user",
            "fingerprint": fingerprint,
            "action": action.canonical_payload(),
            "sessionKey": str(session_key or ""),
        },
    )
    return ElevationGateResult(
        requested=True,
        allowed=False,
        status="approval_required",
        approval_id=approval_id,
    )


def consume_approved_elevation(
    queue: ApprovalQueue,
    approval_id: str,
    action: ElevationAction,
) -> ElevationGateResult:
    """Validate and consume an approved grant before its side effect starts."""

    entry = queue.get(approval_id)
    if entry.namespace != "exec" or entry.params.get("approvalKind") != "sandbox_elevation":
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_action_mismatch",
            approval_id=approval_id,
            reason="approval_action_mismatch",
        )
    if str(entry.params.get("fingerprint") or "") != action.fingerprint():
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_action_mismatch",
            approval_id=approval_id,
            reason="approval_action_mismatch",
        )
    if not entry.resolved:
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_pending",
            approval_id=approval_id,
        )
    if not entry.approved:
        rationale = str(entry.params.get("reviewRationale") or "").strip()
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_denied",
            approval_id=approval_id,
            reason=rationale or "The elevated action was not approved.",
        )

    queue.consume(approval_id)
    return ElevationGateResult(
        requested=True,
        allowed=True,
        status="approved",
        approval_id=approval_id,
    )


def gate_elevated_action(
    action: ElevationAction,
    *,
    approval_id: str | None,
    session_key: str | None,
    queue: ApprovalQueue | None = None,
    reviewer: ApprovalReviewerName | None = None,
) -> ElevationGateResult:
    """Request or consume elevation according to one tool call's intent."""

    if action.sandbox_permissions != "require_escalated":
        return ElevationGateResult(
            requested=False,
            allowed=False,
            status="use_default",
        )
    if queue is None:
        from opensquilla.gateway.approval_queue import get_approval_queue

        queue = get_approval_queue()
    if reviewer is None:
        from opensquilla.sandbox.integration import get_runtime

        runtime = get_runtime()
        configured = getattr(getattr(runtime, "settings", None), "approvals_reviewer", None)
        reviewer = cast(
            "ApprovalReviewerName",
            configured if configured in {"user", "auto_review"} else "auto_review",
        )
    if approval_id:
        try:
            return consume_approved_elevation(queue, approval_id, action)
        except KeyError:
            reason = "approval not found"
        except ValueError as exc:
            reason = str(exc).split(":", 1)[0].strip().lower()
        return ElevationGateResult(
            requested=True,
            allowed=False,
            status="approval_invalid",
            approval_id=approval_id,
            reason=reason,
        )
    return request_elevation(
        queue,
        action,
        session_key=session_key,
        reviewer=reviewer,
    )


__all__ = [
    "ApprovalReviewerName",
    "ElevationAction",
    "ElevationGateResult",
    "SandboxPermissionIntent",
    "consume_approved_elevation",
    "gate_elevated_action",
    "request_elevation",
]
