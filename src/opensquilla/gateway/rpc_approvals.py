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
    approval_wait_decision_rpc_payload,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


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
    elevated_mode = params.get("elevatedMode")
    if elevated_mode not in ("on", "bypass", "full") or not ctx.principal.is_owner:
        elevated_mode = None
    queue = get_approval_queue()
    return approval_resolve_rpc_payload(
        queue,
        params["id"],
        bool(params["approved"]),
        allow_always=allow_always,
        remember_intent=remember_intent,
        elevated_mode=elevated_mode,
    )


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
