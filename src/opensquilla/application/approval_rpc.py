"""RPC payload helpers for approval queue surfaces."""

from __future__ import annotations

from typing import Any

from opensquilla.application.approval_queue import ApprovalQueue, ApprovalSettings


def approval_settings_rpc_payload(
    settings: ApprovalSettings,
    *,
    node_id: str | None = None,
    inherited: bool | None = None,
) -> dict[str, Any]:
    """Build the RPC wire payload for approval settings."""

    payload: dict[str, Any] = {
        "mode": settings.mode,
        "allowPatterns": list(settings.allow_patterns),
        "denyPatterns": list(settings.deny_patterns),
    }
    if node_id is not None:
        payload["nodeId"] = node_id
    if inherited is not None:
        payload["inherited"] = inherited
    return payload


def approval_status_rpc_payload(
    queue: ApprovalQueue,
    approval_id: str,
    mode: str,
) -> dict[str, Any]:
    """Build the RPC wire payload for one approval status."""

    status = queue.status(approval_id)
    resolved_mode = status["params"].get("approvalMode", mode)
    return {
        "id": status["id"],
        "mode": resolved_mode,
        "approved": status["approved"],
        "resolved": status["resolved"],
        "resolution": status.get("resolution", ""),
        "deadline": status.get("deadline"),
        "consumed": status["consumed"],
        "pending": not status["resolved"],
    }


def approval_request_rpc_payload(
    queue: ApprovalQueue,
    *,
    namespace: str,
    params: dict[str, Any],
    node_id: str | None = None,
) -> dict[str, Any]:
    """Create an approval request and return its status payload."""

    settings = queue.get_settings(node_id=node_id)
    request_params = dict(params)
    request_params["approvalMode"] = settings.mode
    approval_id = queue.request(namespace=namespace, params=request_params)
    if settings.mode == "auto-approve":
        queue.resolve(approval_id, True)
    elif settings.mode == "auto-deny":
        queue.resolve(approval_id, False)
    return approval_status_rpc_payload(queue, approval_id, settings.mode)


async def approval_wait_decision_rpc_payload(
    queue: ApprovalQueue,
    approval_id: str,
    *,
    timeout_seconds: Any = None,
) -> dict[str, Any]:
    """Wait for an approval decision and return its status payload."""

    status = queue.status(approval_id)
    if not status["resolved"]:
        await queue.wait(
            approval_id,
            timeout=float(timeout_seconds) if timeout_seconds is not None else None,
        )
    return approval_status_rpc_payload(queue, approval_id, queue.get_settings().mode)


def approval_snapshot_rpc_payload(queue: ApprovalQueue, intent_cache: Any) -> dict[str, Any]:
    """Build the diagnostic snapshot payload for approval state."""

    return {
        "mode": queue.get_settings().mode,
        "intent_cache_size": len(intent_cache._entries),  # noqa: SLF001 - diagnostic
        "intent_cache_entries": [
            {"kind": kind, "target": target, "scope": scope}
            for (kind, target), (_expires, scope) in intent_cache._entries.items()  # noqa: SLF001
        ],
    }


def approval_forget_rpc_payload(intent_cache: Any, target: Any = None) -> dict[str, Any]:
    """Forget cached intent approvals and return the RPC wire payload."""

    if isinstance(target, str) and target.strip():
        stripped = target.strip()
        intent_cache.forget(f"rm {stripped}")
        intent_cache.forget(stripped)
        return {"scope": "target", "target": stripped}
    intent_cache.clear()
    return {"scope": "all"}


def approval_extend_rpc_payload(
    queue: ApprovalQueue,
    approval_id: str,
    seconds: float,
) -> dict[str, Any]:
    """Push a pending approval's deadline out and return its status payload."""

    deadline = queue.extend(approval_id, seconds)
    payload = approval_status_rpc_payload(queue, approval_id, queue.get_settings().mode)
    payload["deadline"] = deadline
    return payload


def approval_resolve_rpc_payload(
    queue: ApprovalQueue,
    approval_id: str,
    approved: bool,
    *,
    allow_always: bool = False,
    remember_intent: bool = False,
    elevated_mode: str | None = None,
) -> dict[str, Any]:
    """Resolve an approval and return its status payload."""

    del elevated_mode
    queue.resolve(
        approval_id,
        approved,
        allow_always=allow_always,
        remember_intent=remember_intent,
        elevated_mode=None,
    )
    return approval_status_rpc_payload(queue, approval_id, queue.get_settings().mode)


__all__ = [
    "approval_extend_rpc_payload",
    "approval_forget_rpc_payload",
    "approval_request_rpc_payload",
    "approval_resolve_rpc_payload",
    "approval_settings_rpc_payload",
    "approval_snapshot_rpc_payload",
    "approval_status_rpc_payload",
    "approval_wait_decision_rpc_payload",
]
