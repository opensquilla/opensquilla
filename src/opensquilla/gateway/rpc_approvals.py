"""Approvals domain RPC handlers backed by ApprovalQueue."""

from __future__ import annotations

from typing import Any

from opensquilla.application.approval_queue import get_approval_queue
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


def _settings_payload(
    settings, node_id: str | None = None, inherited: bool | None = None
) -> dict[str, Any]:
    payload = {
        "mode": settings.mode,
        "allowPatterns": list(settings.allow_patterns),
        "denyPatterns": list(settings.deny_patterns),
    }
    if node_id is not None:
        payload["nodeId"] = node_id
    if inherited is not None:
        payload["inherited"] = inherited
    return payload


def _status_payload(queue, approval_id: str, mode: str) -> dict[str, Any]:
    status = queue.status(approval_id)
    resolved_mode = status["params"].get("approvalMode", mode)
    return {
        "id": status["id"],
        "mode": resolved_mode,
        "approved": status["approved"],
        "resolved": status["resolved"],
        "consumed": status["consumed"],
        "pending": not status["resolved"],
    }


def _request_approval(
    namespace: str, params: dict[str, Any], node_id: str | None = None
) -> dict[str, Any]:
    queue = get_approval_queue()
    settings = queue.get_settings(node_id=node_id)
    request_params = dict(params)
    request_params["approvalMode"] = settings.mode
    approval_id = queue.request(namespace=namespace, params=request_params)
    if settings.mode == "auto-approve":
        queue.resolve(approval_id, True)
    elif settings.mode == "auto-deny":
        queue.resolve(approval_id, False)
    return _status_payload(queue, approval_id, settings.mode)


@_d.method("exec.approvals.get", scope="operator.approvals")
async def _handle_exec_approvals_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    queue = get_approval_queue()
    return _settings_payload(queue.get_settings())


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
    return _settings_payload(
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
    return _request_approval("exec", params, node_id=params.get("nodeId"))


@_d.method("exec.approval.waitDecision", scope="operator.approvals")
async def _handle_exec_approval_wait_decision(
    params: dict | None, ctx: RpcContext
) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    queue = get_approval_queue()
    approval_id = params["id"]
    timeout = params.get("timeoutSeconds")
    status = queue.status(approval_id)
    if not status["resolved"]:
        await queue.wait(approval_id, timeout=float(timeout) if timeout is not None else None)
        status = queue.status(approval_id)
    return _status_payload(queue, approval_id, queue.get_settings().mode)


@_d.method("exec.approval.snapshot", scope="operator.approvals")
async def _handle_exec_approval_snapshot(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Return a diagnostic snapshot: current mode + cached intent count."""
    from opensquilla.application.intent_cache import get_intent_cache

    queue = get_approval_queue()
    mode = queue.get_settings().mode
    cache = get_intent_cache()
    return {
        "mode": mode,
        "intent_cache_size": len(cache._entries),  # noqa: SLF001 — diagnostic
        "intent_cache_entries": [
            {"kind": k, "target": t, "scope": scope}
            for (k, t), (_expires, scope) in cache._entries.items()  # noqa: SLF001
        ],
    }


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
    if isinstance(target, str) and target.strip():
        cache.forget(f"rm {target.strip()}")
        cache.forget(target.strip())
        return {"scope": "target", "target": target.strip()}
    cache.clear()
    return {"scope": "all"}


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
    queue.resolve(
        params["id"],
        bool(params["approved"]),
        allow_always=allow_always,
        remember_intent=remember_intent,
        elevated_mode=elevated_mode,
    )
    return _status_payload(queue, params["id"], queue.get_settings().mode)


@_d.method("plugin.approval.request", scope="operator.approvals")
async def _handle_plugin_approval_request(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params required: pluginId, version, permissions")
    for field in ("pluginId", "version", "permissions"):
        if field not in params:
            raise ValueError(f"params.{field} is required")
    return _request_approval("plugin", params)


@_d.method("plugin.approval.waitDecision", scope="operator.approvals")
async def _handle_plugin_approval_wait_decision(
    params: dict | None, ctx: RpcContext
) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    queue = get_approval_queue()
    approval_id = params["id"]
    timeout = params.get("timeoutSeconds")
    status = queue.status(approval_id)
    if not status["resolved"]:
        await queue.wait(approval_id, timeout=float(timeout) if timeout is not None else None)
        status = queue.status(approval_id)
    return _status_payload(queue, approval_id, queue.get_settings().mode)


@_d.method("plugin.approval.resolve", scope="operator.approvals")
async def _handle_plugin_approval_resolve(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    if "approved" not in params:
        raise ValueError("params.approved is required")
    queue = get_approval_queue()
    queue.resolve(params["id"], bool(params["approved"]))
    return _status_payload(queue, params["id"], queue.get_settings().mode)
