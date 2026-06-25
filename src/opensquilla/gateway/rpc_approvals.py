"""Approvals domain RPC handlers backed by ApprovalQueue."""

from __future__ import annotations

from typing import Any

from opensquilla.application.approval_queue import get_approval_queue
from opensquilla.application.approval_rpc import (
    approval_forget_rpc_payload,
    approval_request_rpc_payload,
    approval_resolve_rpc_payload,
    approval_settings_rpc_payload,
    approval_snapshot_rpc_payload,
    approval_status_rpc_payload,
    approval_wait_decision_rpc_payload,
)
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.sandbox.escalation import (
    apply_sandbox_approval_choice,
    deny_matching_pending_sandbox_approvals,
    is_sandbox_approval_kind,
    remember_sandbox_approval_denial,
    validate_sandbox_approval_choice,
)

_d = get_dispatcher()


def _require_owner_for_sandbox_approval_resolution(ctx: RpcContext) -> None:
    if not getattr(ctx.principal, "is_owner", False):
        raise RpcHandlerError(
            "UNAUTHORIZED",
            "exec.approval.resolve requires owner principal.",
        )


def _complete_sandbox_resolution_claim(
    queue: Any,
    approval_id: str,
    claim_token: str,
    *,
    allow_always: bool,
    remember_intent: bool,
) -> None:
    try:
        queue.complete_claimed_resolution(
            approval_id,
            claim_token,
            allow_always=allow_always,
            remember_intent=remember_intent,
        )
    except Exception:
        queue.complete_claimed_resolution(
            approval_id,
            claim_token,
            allow_always=allow_always,
            remember_intent=remember_intent,
        )


@_d.method("exec.approvals.get", scope="operator.approvals")
async def _handle_exec_approvals_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    queue = get_approval_queue()
    return approval_settings_rpc_payload(queue.get_settings())


@_d.method("exec.approvals.set", scope="operator.approvals")
async def _handle_exec_approvals_set(params: dict | None, ctx: RpcContext) -> None:
    if not isinstance(params, dict) or "mode" not in params:
        raise ValueError("params.mode is required")
    queue = get_approval_queue()
    queue.set_settings(
        mode=params["mode"],
        allow_patterns=params.get("allowPatterns"),
        deny_patterns=params.get("denyPatterns"),
    )
    return None


@_d.method("exec.approvals.node.get", scope="operator.admin")
async def _handle_exec_approvals_node_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "nodeId" not in params:
        raise ValueError("params.nodeId is required")
    queue = get_approval_queue()
    node_id = params["nodeId"]
    return approval_settings_rpc_payload(
        queue.get_settings(node_id=node_id),
        node_id=node_id,
        inherited=not queue.has_node_settings(node_id),
    )


@_d.method("exec.approvals.node.set", scope="operator.admin")
async def _handle_exec_approvals_node_set(params: dict | None, ctx: RpcContext) -> None:
    if not isinstance(params, dict) or "nodeId" not in params:
        raise ValueError("params.nodeId is required")
    if "mode" not in params:
        raise ValueError("params.mode is required")
    queue = get_approval_queue()
    queue.set_settings(
        mode=params["mode"],
        allow_patterns=params.get("allowPatterns"),
        deny_patterns=params.get("denyPatterns"),
        node_id=params["nodeId"],
    )
    return None


@_d.method("exec.approval.request", scope="operator.approvals")
async def _handle_exec_approval_request(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params required: toolName, args, sessionKey")
    for field in ("toolName", "args", "sessionKey"):
        if field not in params:
            raise ValueError(f"params.{field} is required")
    return approval_request_rpc_payload(
        get_approval_queue(),
        namespace="exec",
        params=params,
        node_id=params.get("nodeId"),
    )


@_d.method("exec.approval.waitDecision", scope="operator.approvals")
async def _handle_exec_approval_wait_decision(
    params: dict | None, ctx: RpcContext
) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    queue = get_approval_queue()
    return await approval_wait_decision_rpc_payload(
        queue,
        params["id"],
        timeout_seconds=params.get("timeoutSeconds"),
    )


@_d.method("exec.approval.snapshot", scope="operator.approvals")
async def _handle_exec_approval_snapshot(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Return a diagnostic snapshot: current mode + cached intent count."""
    from opensquilla.application.intent_cache import get_intent_cache

    queue = get_approval_queue()
    cache = get_intent_cache()
    return approval_snapshot_rpc_payload(queue, cache)


@_d.method("exec.approval.forget", scope="operator.approvals")
async def _handle_exec_approval_forget(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Drop cached intent approvals.

    ``params.target`` (optional) — clear entries matching a single command/path.
    Omit to wipe the whole intent cache.
    """
    from opensquilla.application.intent_cache import get_intent_cache

    cache = get_intent_cache()
    if isinstance(params, dict):
        target = params.get("target")
    else:
        target = None
    return approval_forget_rpc_payload(cache, target)


@_d.method("exec.approval.resolve", scope="operator.approvals")
async def _handle_exec_approval_resolve(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    if "approved" not in params:
        raise ValueError("params.approved is required")
    allow_always = bool(params.get("allowAlways", False))
    remember_intent = bool(params.get("rememberIntent", False))
    choice = params.get("choice")
    queue = get_approval_queue()
    approved = bool(params["approved"])
    pending = queue.get(params["id"])
    normalized_choice = str(choice).strip() if isinstance(choice, str) and choice.strip() else None
    sandbox_approval = is_sandbox_approval_kind(pending.params.get("approvalKind"))
    if sandbox_approval and approved:
        _require_owner_for_sandbox_approval_resolution(ctx)

    validate_sandbox_approval_choice(
        pending.params,
        choice=normalized_choice,
        approved=approved,
    )

    if sandbox_approval and approved:
        claim_token = queue.claim_resolution(params["id"])
        try:
            queue.finalize_claimed_resolution(
                params["id"],
                claim_token,
                approved,
                allow_always=allow_always,
                remember_intent=remember_intent,
                elevated_mode=None,
            )
        except Exception:
            queue.release_resolution_claim(params["id"], claim_token)
            raise
        try:
            await apply_sandbox_approval_choice(
                pending.params,
                choice=normalized_choice,
                approved=True,
                session_manager=ctx.session_manager,
                config=ctx.config,
            )
        except Exception:
            queue.reopen_resolved_approval(params["id"], expected_approved=True)
            raise
        _complete_sandbox_resolution_claim(
            queue,
            params["id"],
            claim_token,
            allow_always=allow_always,
            remember_intent=remember_intent,
        )
        return approval_status_rpc_payload(queue, params["id"], queue.get_settings().mode)

    queue.resolve(
        params["id"],
        approved,
        allow_always=allow_always,
        remember_intent=remember_intent,
        elevated_mode=None,
        allow_idempotent=not sandbox_approval,
    )
    if sandbox_approval and not approved:
        remember_sandbox_approval_denial(pending.params, params["id"])
        deny_matching_pending_sandbox_approvals(
            queue,
            pending.params,
            exclude_approval_id=params["id"],
        )

    return approval_status_rpc_payload(queue, params["id"], queue.get_settings().mode)


@_d.method("plugin.approval.request", scope="operator.approvals")
async def _handle_plugin_approval_request(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params required: pluginId, version, permissions")
    for field in ("pluginId", "version", "permissions"):
        if field not in params:
            raise ValueError(f"params.{field} is required")
    return approval_request_rpc_payload(
        get_approval_queue(),
        namespace="plugin",
        params=params,
    )


@_d.method("plugin.approval.waitDecision", scope="operator.approvals")
async def _handle_plugin_approval_wait_decision(
    params: dict | None, ctx: RpcContext
) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    queue = get_approval_queue()
    return await approval_wait_decision_rpc_payload(
        queue,
        params["id"],
        timeout_seconds=params.get("timeoutSeconds"),
    )


@_d.method("plugin.approval.resolve", scope="operator.approvals")
async def _handle_plugin_approval_resolve(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    if "approved" not in params:
        raise ValueError("params.approved is required")
    queue = get_approval_queue()
    return approval_resolve_rpc_payload(queue, params["id"], bool(params["approved"]))
