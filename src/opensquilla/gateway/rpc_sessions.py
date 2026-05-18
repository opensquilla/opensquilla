"""RPC handlers for the sessions domain."""

from __future__ import annotations

from typing import Any

import structlog

from opensquilla.gateway import rpc_session_events as _session_events
from opensquilla.gateway import rpc_session_lifecycle as _session_lifecycle
from opensquilla.gateway import rpc_session_management as _session_management
from opensquilla.gateway import rpc_session_read_queries as _session_read_queries
from opensquilla.gateway import rpc_session_send as _session_send
from opensquilla.gateway import rpc_session_send_inputs as _session_send_inputs
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_compaction_inputs import (
    context_window_tokens,
    effective_compaction_model,
    resolve_compaction_provider,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    resolve_session_attachments,
    validate_session_attachments,
)

_d = get_dispatcher()
log = structlog.get_logger(__name__)
_ALLOWED_MEDIA_TYPES = _session_send_inputs.ALLOWED_MEDIA_TYPES
_MAX_ATTACHMENT_BYTES = _session_send_inputs.MAX_ATTACHMENT_BYTES
_MAX_STAGED_PDF_BYTES = _session_send_inputs.MAX_STAGED_PDF_BYTES
_MAX_TEXT_ATTACHMENT_BYTES = _session_send_inputs.MAX_TEXT_ATTACHMENT_BYTES
_MAX_TOTAL_ATTACHMENT_BYTES = _session_send_inputs.MAX_TOTAL_ATTACHMENT_BYTES
_MAX_ATTACHMENTS = _session_send_inputs.MAX_ATTACHMENTS
_attachment_media_type = _session_send_inputs.attachment_media_type
_normalize_attachments = _session_send_inputs.normalize_attachments
_sniff_mime_from_bytes = _session_send_inputs.sniff_mime_from_bytes
_drain_task_runtime_for_reset = _session_lifecycle.drain_task_runtime_for_reset


def _optional_stream_seq(params: dict | None) -> int | None:
    return _session_events.optional_stream_seq(params)


def _buffer_session_event(
    session_key: str,
    event_name: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return _session_events.buffer_session_event(session_key, event_name, payload)


async def _resolve_attachments(
    validated: list[dict[str, Any]],
    store: Any | None = None,
    *,
    material_root: Any | None = None,
    session_id: str | None = None,
    disk_budget_bytes: int | None = None,
) -> list[dict[str, Any]]:
    return await resolve_session_attachments(
        validated,
        store=store,
        material_root=material_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget_bytes,
    )


def _validate_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    return validate_session_attachments(
        raw_attachments,
        logger=log,
    )


def _require_key(params: dict | None) -> str:
    return _session_management.require_session_key(params)


def _context_window_tokens(params: dict | None, ctx: RpcContext) -> int:
    return context_window_tokens(params, ctx)


def _effective_compaction_model(session: Any | None) -> str | None:
    return effective_compaction_model(session)


def _resolve_compaction_provider(ctx: RpcContext, session: Any | None) -> Any | None:
    return resolve_compaction_provider(ctx, session)


def _model_value(value: Any) -> str | None:
    return _session_management.model_value(value)


def _agent_registry_model(ctx: RpcContext, agent_id: str) -> str | None:
    return _session_management.agent_registry_model(ctx, agent_id)


async def _agent_registry_has(ctx: RpcContext, agent_id: str) -> bool:
    return await _session_management.agent_registry_has(ctx, agent_id)


def _session_turn_model(ctx: RpcContext, session: Any | None, agent_id: str) -> str | None:
    return _session_management.session_turn_model(ctx, session, agent_id)


async def _list_task_rows(ctx: RpcContext, storage: Any | None, session_key: str) -> list[Any]:
    return await _session_read_queries.list_task_rows(ctx, storage, session_key)


async def _list_task_rows_by_session(
    ctx: RpcContext,
    storage: Any | None,
    session_keys: list[str],
) -> dict[str, list[Any]]:
    return await _session_read_queries.list_task_rows_by_session(ctx, storage, session_keys)


def _create_session_key(agent_id: str, kind: object = None) -> str:
    return _session_management.create_session_key(agent_id, kind)


async def _resolve_session_node(storage: Any, key: str) -> Any:
    return await _session_read_queries.resolve_session_node(storage, key)


@_d.method("sessions.list", scope="operator.read")
async def _handle_sessions_list(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_list(params, ctx)


@_d.method("sessions.create", scope="operator.write")
async def _handle_sessions_create(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_management.handle_sessions_create(params, ctx)


@_d.method("sessions.send", scope="operator.write")
async def _handle_sessions_send(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_send.handle_sessions_send(params, ctx)


async def _emit_to_subscribers(
    ctx: RpcContext,
    session_key: str,
    event_name: str,
    payload: dict,
) -> None:
    await _session_events.emit_to_session_subscribers(
        ctx,
        session_key,
        event_name,
        payload,
        logger=log,
    )


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
        drain_task_runtime=_drain_task_runtime_for_reset,
        increment_and_emit_epoch=_increment_and_emit_epoch,
    )


async def _increment_and_emit_epoch(
    ctx: RpcContext,
    storage: Any,
    session_key: str,
) -> int:
    return await _session_events.increment_and_emit_epoch(
        ctx,
        storage,
        session_key,
        logger=log,
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
