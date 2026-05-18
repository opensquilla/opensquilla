"""Session lifecycle RPC behavior for the gateway sessions domain."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, NoReturn

import structlog

from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError
from opensquilla.gateway.rpc_compaction_inputs import (
    build_gateway_compaction_config,
    context_window_tokens,
)
from opensquilla.session.compaction import call_compact_with_optional_config
from opensquilla.session.lifecycle_flush import (
    SessionLifecycleFlushFailure,
)
from opensquilla.session.lifecycle_memory import preserve_lifecycle_memory
from opensquilla.session.lifecycle_service import (
    require_existing_session,
    require_session_storage,
    run_with_session_lock,
)
from opensquilla.session.management_service import require_session_key
from opensquilla.session.models import SessionIntent
from opensquilla.session.rpc_payload import (
    session_abort_response,
    session_compact_response,
    session_context_compact_response,
    session_delete_response,
    session_reset_response,
)
from opensquilla.session.services import get_session_storage

log = structlog.get_logger(__name__)
_RESET_RUNTIME_SETTLE_SECONDS = 0.25
_RESET_RUNTIME_CANCEL_DRAIN_SECONDS = 2.0
_ACTIVE_TASK_STATUSES = frozenset({"queued", "running"})

EpochEmitter = Callable[[RpcContext, Any, str], Awaitable[int]]
EventEmitter = Callable[[RpcContext, str, str, dict], Awaitable[None]]
ResetDrain = Callable[[Any, str], Awaitable[None]]


def _raise_lifecycle_flush_failure(
    failure: SessionLifecycleFlushFailure,
    *,
    from_exc: BaseException | None = None,
) -> NoReturn:
    error = RpcHandlerError(
        code=failure.code,
        message=failure.message,
        details=failure.details,
    )
    cause = from_exc or failure.cause
    if cause is not None:
        raise error from cause
    raise error


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

    storage = require_session_storage(ctx.session_manager)

    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        await drain_task_runtime(task_runtime, key)

    force = bool((params or {}).get("force", False))

    if ctx.flush_service is None:
        session = await require_existing_session(storage, key)
        preservation = await preserve_lifecycle_memory(
            "reset",
            ctx.session_manager,
            ctx.flush_service,
            key,
            session,
            force=force,
            principal_scopes=ctx.principal.scopes,
        )
        if preservation.failure is not None:
            _raise_lifecycle_flush_failure(preservation.failure)
        previous_session_id = preservation.previous_session_id or session.session_id

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

    async def _run_locked() -> dict[str, Any]:
        session = await require_existing_session(storage, key)
        preservation = await preserve_lifecycle_memory(
            "reset",
            ctx.session_manager,
            ctx.flush_service,
            key,
            session,
            force=force,
            principal_scopes=ctx.principal.scopes,
        )
        if preservation.failure is not None:
            _raise_lifecycle_flush_failure(preservation.failure)
        previous_session_id = preservation.previous_session_id or session.session_id

        updated, rotated = await ctx.session_manager.apply_intent(key, SessionIntent.RESET_SAME_KEY)
        new_epoch = await increment_and_emit_epoch(ctx, storage, key)
        return session_reset_response(
            key,
            rotated,
            previous_session_id,
            updated.session_id,
            receipt=preservation.receipt,
            epoch=new_epoch,
        )

    return await run_with_session_lock(ctx.turn_runner, key, _run_locked)


async def handle_sessions_delete(params: dict | None, ctx: RpcContext) -> dict:
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = require_session_storage(ctx.session_manager)

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
    async def _run_locked() -> dict[str, Any]:
        storage = get_session_storage(ctx.session_manager)
        session = None
        if storage is not None:
            session = await require_existing_session(storage, key)

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

    return await run_with_session_lock(ctx.turn_runner, key, _run_locked)


async def handle_sessions_compact(params: dict | None, ctx: RpcContext) -> dict:
    key = require_session_key(params)
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    max_messages = (params or {}).get("maxMessages", 20)
    force = bool((params or {}).get("force", False))

    async def _run_locked() -> dict[str, Any]:
        receipt: Any | None = None
        storage = get_session_storage(ctx.session_manager)
        session = None
        if storage is not None:
            session = await storage.get_session(key)

        if ctx.flush_service is None:
            preservation = await preserve_lifecycle_memory(
                "compact",
                ctx.session_manager,
                ctx.flush_service,
                key,
                session,
                force=force,
                principal_scopes=ctx.principal.scopes,
            )
            if preservation.failure is not None:
                _raise_lifecycle_flush_failure(preservation.failure)
        else:
            storage = require_session_storage(ctx.session_manager)
            session = await require_existing_session(storage, key)
            preservation = await preserve_lifecycle_memory(
                "compact",
                ctx.session_manager,
                ctx.flush_service,
                key,
                session,
                force=force,
                principal_scopes=ctx.principal.scopes,
            )
            if preservation.failure is not None:
                _raise_lifecycle_flush_failure(preservation.failure)
            receipt = preservation.receipt

        result = await ctx.session_manager.truncate(key, max_messages=max_messages)
        return session_compact_response(key, result, receipt=receipt)

    return await run_with_session_lock(ctx.turn_runner, key, _run_locked)
