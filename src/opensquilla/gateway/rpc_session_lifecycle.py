"""Session lifecycle RPC behavior for the gateway sessions domain."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError
from opensquilla.gateway.rpc_compaction_inputs import (
    build_gateway_compaction_config,
    context_window_tokens,
)
from opensquilla.memory.session_flush import FlushReceipt
from opensquilla.session.compaction import call_compact_with_optional_config
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
from opensquilla.session.models import SessionIntent
from opensquilla.session.rpc_payload import (
    session_abort_response,
    session_compact_response,
    session_context_compact_response,
    session_delete_response,
    session_flush_error_details,
    session_flush_unavailable_details,
    session_permission_denied_details,
    session_reset_response,
)
from opensquilla.session.services import get_session_lock, get_session_storage

log = structlog.get_logger(__name__)
_RESET_RUNTIME_SETTLE_SECONDS = 0.25
_RESET_RUNTIME_CANCEL_DRAIN_SECONDS = 2.0
_ACTIVE_TASK_STATUSES = frozenset({"queued", "running"})

EpochEmitter = Callable[[RpcContext, Any, str], Awaitable[int]]
EventEmitter = Callable[[RpcContext, str, str, dict], Awaitable[None]]
ResetDrain = Callable[[Any, str], Awaitable[None]]


def require_session_key(params: dict | None) -> str:
    if not isinstance(params, dict) or "key" not in params:
        raise ValueError("params.key is required")
    key = params["key"]
    if not isinstance(key, str):
        raise ValueError("params.key must be a string")
    return canonicalize_session_key(key)


def _task_status_value(status: Any) -> str:
    return str(getattr(status, "value", status) or "")


async def drain_task_runtime_for_reset(task_runtime: Any, session_key: str) -> None:
    """Cancel live runtime work without racing a just-finished turn."""

    has_runtime_listing = hasattr(task_runtime, "list") and hasattr(task_runtime, "wait")

    if has_runtime_listing:
        try:
            rows = await task_runtime.list(session_key=session_key)
            for row in rows:
                if _task_status_value(getattr(row, "status", None)) != "running":
                    continue
                try:
                    await asyncio.wait_for(
                        task_runtime.wait(row.task_id),
                        timeout=_RESET_RUNTIME_SETTLE_SECONDS,
                    )
                except TimeoutError:
                    pass
        except Exception:
            log.warning("sessions.reset.task_runtime_settle_failed", session_key=session_key)

    await task_runtime.cancel(session_key=session_key)

    if not has_runtime_listing:
        return

    try:
        rows = await task_runtime.list(session_key=session_key)
        for row in rows:
            if _task_status_value(getattr(row, "status", None)) in _ACTIVE_TASK_STATUSES:
                await asyncio.wait_for(
                    task_runtime.wait(row.task_id),
                    timeout=_RESET_RUNTIME_CANCEL_DRAIN_SECONDS,
                )
    except TimeoutError:
        log.warning("sessions.reset.task_runtime_drain_timeout", session_key=session_key)
    except Exception:
        log.warning("sessions.reset.task_runtime_drain_failed", session_key=session_key)


async def _emit_to_session_subscribers(
    ctx: RpcContext,
    session_key: str,
    event_name: str,
    payload: dict,
) -> None:
    from opensquilla.gateway.rpc_session_events import emit_to_session_subscribers

    await emit_to_session_subscribers(ctx, session_key, event_name, payload, logger=log)


async def _increment_and_emit_epoch(ctx: RpcContext, storage: Any, session_key: str) -> int:
    from opensquilla.gateway.rpc_session_events import increment_and_emit_epoch

    return await increment_and_emit_epoch(ctx, storage, session_key, logger=log)


async def handle_sessions_abort(
    params: dict | None,
    ctx: RpcContext,
    *,
    emit_to_subscribers: EventEmitter | None = None,
) -> dict:
    key = require_session_key(params)
    emit = emit_to_subscribers or _emit_to_session_subscribers

    if ctx.session_manager is None:
        return session_abort_response(key, aborted=False)

    storage = get_session_storage(ctx.session_manager)
    if storage:
        session = await storage.get_session(key)
        if session is None:
            raise KeyError(f"Session not found: {key}")

    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        cancelled_count = await task_runtime.cancel(session_key=key)
        return session_abort_response(key, aborted=cancelled_count > 0)

    registry = get_agent_task_registry()
    task = registry.get(key)
    cancelled = registry.cancel(key)

    if (
        cancelled
        and task is not None
        and not getattr(task, "_opensquilla_started", True)
        and not getattr(task, "_opensquilla_terminal_emitted", False)
    ):
        setattr(task, "_opensquilla_terminal_emitted", True)
        await emit(ctx, key, "session.event.done", {"reason": "aborted"})

    return session_abort_response(key, aborted=cancelled)


async def handle_sessions_reset(
    params: dict | None,
    ctx: RpcContext,
    *,
    drain_task_runtime: ResetDrain = drain_task_runtime_for_reset,
    increment_and_emit_epoch: EpochEmitter = _increment_and_emit_epoch,
) -> dict[str, Any]:
    key = require_session_key(params)

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        await drain_task_runtime(task_runtime, key)

    force = bool((params or {}).get("force", False))

    if ctx.flush_service is None:
        session = await storage.get_session(key)
        if session is None:
            raise KeyError(f"Session not found: {key}")
        previous_session_id = session.session_id

        transcript = await ctx.session_manager.get_transcript(key)
        if transcript and not force:
            raise RpcHandlerError(
                code="flush_unavailable",
                message=(
                    "Reset aborted: flush service is unavailable and the "
                    "transcript is non-empty. Re-run with force=true (admin) "
                    "to discard without backup."
                ),
                details=session_flush_unavailable_details(
                    key,
                    previous_session_id,
                    message_count=len(transcript),
                ),
            )
        if transcript and force and "operator.admin" not in ctx.principal.scopes:
            raise RpcHandlerError(
                code="permission_denied",
                message="force=true on sessions.reset requires operator.admin scope.",
                details=session_permission_denied_details(key, previous_session_id),
            )

        updated, rotated = await ctx.session_manager.apply_intent(key, SessionIntent.RESET_SAME_KEY)
        new_epoch = await increment_and_emit_epoch(ctx, storage, key)
        return session_reset_response(
            key,
            rotated,
            previous_session_id,
            updated.session_id,
            epoch=new_epoch,
        )

    registry = get_agent_task_registry()
    active = registry.get(key)
    if active is not None and not active.done():
        registry.cancel(key)
        try:
            await asyncio.wait_for(active, timeout=2.0)
        except TimeoutError:
            log.warning("sessions.reset.drain_timeout", session_key=key)
        except asyncio.CancelledError:
            log.debug("sessions.reset.drain_cancelled", session_key=key)
        except Exception as exc:  # noqa: BLE001
            log.warning("sessions.reset.drain_failed", session_key=key, error=str(exc))

    turn_runner = ctx.turn_runner
    lock = get_session_lock(turn_runner, key)

    async def _run_locked() -> dict[str, Any]:
        session = await storage.get_session(key)
        if session is None:
            raise KeyError(f"Session not found: {key}")
        previous_session_id = session.session_id
        agent_id = normalize_agent_id(getattr(session, "agent_id", None) or "main")

        transcript = await ctx.session_manager.get_transcript(key)

        if not transcript:
            updated, rotated = await ctx.session_manager.apply_intent(
                key, SessionIntent.RESET_SAME_KEY
            )
            new_epoch = await increment_and_emit_epoch(ctx, storage, key)
            receipt = FlushReceipt(
                mode="skipped",
                flushed_paths=[],
                slug=None,
                message_count=0,
                duration_ms=0,
                raw_reason=None,
                error=None,
            )
            return session_reset_response(
                key,
                rotated,
                previous_session_id,
                updated.session_id,
                receipt=receipt,
                epoch=new_epoch,
            )

        try:
            receipt = await ctx.flush_service.execute(
                transcript,
                key,
                agent_id=agent_id,
                timeout=30.0,
                message_window=0,
                segment_mode="auto",
            )
        except Exception as exc:  # noqa: BLE001
            receipt = FlushReceipt(
                mode="error",
                flushed_paths=[],
                slug=None,
                message_count=len(transcript),
                duration_ms=0,
                raw_reason=None,
                error=str(exc),
            )
            raise RpcHandlerError(
                code="flush_disk_error",
                message=f"Reset aborted: flush failed ({receipt.error})",
                details=session_flush_error_details(key, previous_session_id, receipt),
            ) from exc

        if receipt.mode == "error":
            raise RpcHandlerError(
                code="flush_disk_error",
                message=f"Reset aborted: flush failed ({receipt.error or 'unknown error'})",
                details=session_flush_error_details(key, previous_session_id, receipt),
            )

        updated, rotated = await ctx.session_manager.apply_intent(key, SessionIntent.RESET_SAME_KEY)
        new_epoch = await increment_and_emit_epoch(ctx, storage, key)
        return session_reset_response(
            key,
            rotated,
            previous_session_id,
            updated.session_id,
            receipt=receipt,
            epoch=new_epoch,
        )

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()


async def handle_sessions_delete(params: dict | None, ctx: RpcContext) -> dict:
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    keys: list[str] = []
    if isinstance(params, dict):
        if "keys" in params:
            keys = params["keys"]
        elif "key" in params:
            keys = [params["key"]]

    if not keys:
        raise ValueError("params.key or params.keys is required")

    deleted: list[str] = []
    errors: list[str] = []
    for key in keys:
        try:
            await storage.delete_session(key)
            deleted.append(key)
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    return session_delete_response(deleted, errors)


async def handle_sessions_context_compact(params: dict | None, ctx: RpcContext) -> dict:
    key = require_session_key(params)
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    compact_tokens = context_window_tokens(params, ctx)
    turn_runner = ctx.turn_runner
    lock = get_session_lock(turn_runner, key)

    async def _run_locked() -> dict[str, Any]:
        storage = get_session_storage(ctx.session_manager)
        session = None
        if storage is not None and await storage.get_session(key) is None:
            raise KeyError(f"Session not found: {key}")
        if storage is not None:
            session = await storage.get_session(key)

        compaction_config = build_gateway_compaction_config(ctx, session)

        compact_with_result = getattr(ctx.session_manager, "compact_with_result", None)
        if callable(compact_with_result):
            result = await compact_with_result(key, compact_tokens, compaction_config)
            summary = getattr(result, "summary", "") or ""
            removed_count = int(getattr(result, "removed_count", 0) or 0)
            summary_source = getattr(result, "summary_source", "unknown") or "unknown"
        else:
            compact = ctx.session_manager.compact
            summary = await call_compact_with_optional_config(
                compact,
                key,
                compact_tokens,
                compaction_config,
            )
            removed_count = 1 if summary else 0
            summary_source = "unknown"
        return session_context_compact_response(
            key,
            removed_count=removed_count,
            summary=summary,
            summary_source=summary_source,
            context_window_tokens=compact_tokens,
        )

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()


async def handle_sessions_compact(params: dict | None, ctx: RpcContext) -> dict:
    key = require_session_key(params)
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    max_messages = (params or {}).get("maxMessages", 20)
    force = bool((params or {}).get("force", False))

    turn_runner = ctx.turn_runner
    lock = get_session_lock(turn_runner, key)

    async def _run_locked() -> dict[str, Any]:
        receipt: FlushReceipt | None = None
        storage = get_session_storage(ctx.session_manager)
        session = None
        if storage is not None:
            session = await storage.get_session(key)
        previous_session_id = getattr(session, "session_id", None) if session else None

        if ctx.flush_service is None:
            transcript = await ctx.session_manager.get_transcript(key)
            if transcript and not force:
                raise RpcHandlerError(
                    code="flush_unavailable",
                    message=(
                        "Compact aborted: flush service is unavailable and "
                        "the transcript is non-empty. Re-run with force=true "
                        "(admin) to truncate without backup."
                    ),
                    details=session_flush_unavailable_details(
                        key,
                        previous_session_id,
                        message_count=len(transcript),
                    ),
                )
            if transcript and force and "operator.admin" not in ctx.principal.scopes:
                raise RpcHandlerError(
                    code="permission_denied",
                    message="force=true on sessions.compact requires operator.admin scope.",
                    details=session_permission_denied_details(key, previous_session_id),
                )
        else:
            if storage is None:
                raise KeyError("No session storage available")
            if session is None:
                raise KeyError(f"Session not found: {key}")
            agent_id = normalize_agent_id(getattr(session, "agent_id", None) or "main")
            transcript = await ctx.session_manager.get_transcript(key)
            if transcript:
                try:
                    receipt = await ctx.flush_service.execute(
                        transcript,
                        key,
                        agent_id=agent_id,
                        timeout=30.0,
                        message_window=0,
                        segment_mode="auto",
                    )
                except Exception as exc:  # noqa: BLE001
                    receipt = FlushReceipt(
                        mode="error",
                        flushed_paths=[],
                        slug=None,
                        message_count=len(transcript),
                        duration_ms=0,
                        raw_reason=None,
                        error=str(exc),
                    )
                    raise RpcHandlerError(
                        code="flush_disk_error",
                        message=f"Compact aborted: flush failed ({receipt.error})",
                        details=session_flush_error_details(key, previous_session_id, receipt),
                    ) from exc

                if receipt.mode == "error":
                    raise RpcHandlerError(
                        code="flush_disk_error",
                        message=(
                            f"Compact aborted: flush failed ({receipt.error or 'unknown error'})"
                        ),
                        details=session_flush_error_details(key, previous_session_id, receipt),
                    )
            else:
                receipt = FlushReceipt(
                    mode="skipped",
                    flushed_paths=[],
                    slug=None,
                    message_count=0,
                    duration_ms=0,
                    raw_reason=None,
                    error=None,
                )

        result = await ctx.session_manager.truncate(key, max_messages=max_messages)
        return session_compact_response(key, result, receipt=receipt)

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()
