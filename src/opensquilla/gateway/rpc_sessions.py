"""RPC handlers for the sessions domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway import rpc_session_lifecycle as _session_lifecycle
from opensquilla.gateway import rpc_session_management as _session_management
from opensquilla.gateway import rpc_session_read_queries as _session_read_queries
from opensquilla.gateway import rpc_session_send as _session_send
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


@_d.method("sessions.list", scope="operator.read")
async def _handle_sessions_list(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_list(params, ctx)


@_d.method("sessions.create", scope="operator.write")
async def _handle_sessions_create(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_management.handle_sessions_create(params, ctx)


@_d.method("sessions.send", scope="operator.write")
async def _handle_sessions_send(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_send.handle_sessions_send(params, ctx)


@_d.method("sessions.abort", scope="operator.write")
async def _handle_sessions_abort(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_lifecycle.handle_sessions_abort(params, ctx)


@_d.method("sessions.patch", scope="operator.admin")
async def _handle_sessions_patch(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_management.handle_sessions_patch(params, ctx)


@_d.method("sessions.reset", scope="operator.write")
async def _handle_sessions_reset(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await _session_lifecycle.handle_sessions_reset(
        params,
        ctx,
        drain_task_runtime=_session_lifecycle.drain_task_runtime_for_reset,
    )


@_d.method("sessions.delete", scope="operator.admin")
async def _handle_sessions_delete(params: dict | None, ctx: RpcContext) -> dict:
    """Delete one or more sessions. Accepts {key} for single or {keys} for bulk."""
    return await _session_lifecycle.handle_sessions_delete(params, ctx)


@_d.method("sessions.contextCompact", scope="operator.write")
async def _handle_sessions_context_compact(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_lifecycle.handle_sessions_context_compact(params, ctx)


@_d.method("sessions.compact", scope="operator.write")
async def _handle_sessions_compact(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_lifecycle.handle_sessions_compact(params, ctx)


@_d.method("sessions.subscribe", scope="operator.read")
async def _handle_sessions_subscribe(params: dict | None, ctx: RpcContext) -> None:
    return await _session_read_queries.handle_sessions_subscribe(params, ctx)


@_d.method("sessions.unsubscribe", scope="operator.read")
async def _handle_sessions_unsubscribe(params: dict | None, ctx: RpcContext) -> None:
    return await _session_read_queries.handle_sessions_unsubscribe(params, ctx)


@_d.method("sessions.messages.subscribe", scope="operator.read")
async def _handle_sessions_messages_subscribe(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_messages_subscribe(params, ctx)


@_d.method("sessions.messages.unsubscribe", scope="operator.read")
async def _handle_sessions_messages_unsubscribe(params: dict | None, ctx: RpcContext) -> None:
    return await _session_read_queries.handle_sessions_messages_unsubscribe(params, ctx)


@_d.method("sessions.preview", scope="operator.read")
async def _handle_sessions_preview(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_preview(params, ctx)


@_d.method("sessions.resolve", scope="operator.read")
async def _handle_sessions_resolve(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_resolve(params, ctx)
