"""RPC handlers for the sessions domain."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, replace
from typing import Any

import structlog

from opensquilla.gateway import attachment_ingest as _attachment_ingest
from opensquilla.gateway import rpc_session_events as _session_events
from opensquilla.gateway import rpc_session_lifecycle as _session_lifecycle
from opensquilla.gateway import rpc_session_read_queries as _session_read_queries
from opensquilla.gateway import rpc_session_send_inputs as _session_send_inputs
from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, RpcUnavailableError, get_dispatcher
from opensquilla.gateway.rpc_compaction_inputs import (
    context_window_tokens,
    effective_compaction_model,
    resolve_compaction_provider,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    normalize_memory_capture_controls,
    resolve_session_attachments,
    trusted_elevated_hint,
    validate_session_attachments,
)
from opensquilla.gateway.rpc_session_turn_runtime import enqueue_session_turn_via_runtime
from opensquilla.gateway.session_services import (
    get_session_lock,
    get_session_storage,
)
from opensquilla.paths import media_root_from_config
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
from opensquilla.session.rpc_payload import (
    normalize_terminal_event_payload,
    session_agent_not_found_details,
    session_create_response,
    session_create_stub_response,
    session_patch_response,
    session_send_accepted_response,
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
_STREAM_IDLE_TIMEOUT_CODE = "stream_idle_timeout"
_STREAM_IDLE_TIMEOUT_MESSAGE = "Session event stream idle before terminal event"
_drain_task_runtime_for_reset = _session_lifecycle.drain_task_runtime_for_reset


def _optional_positive_timeout(config: Any, attr: str, default: float) -> float | None:
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


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
    if not isinstance(params, dict) or "key" not in params:
        raise ValueError("params.key is required")
    key = params["key"]
    if not isinstance(key, str):
        raise ValueError("params.key must be a string")
    return canonicalize_session_key(key)


def _context_window_tokens(params: dict | None, ctx: RpcContext) -> int:
    return context_window_tokens(params, ctx)


def _effective_compaction_model(session: Any | None) -> str | None:
    return effective_compaction_model(session)


def _resolve_compaction_provider(ctx: RpcContext, session: Any | None) -> Any | None:
    return resolve_compaction_provider(ctx, session)


def _model_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _agent_registry_model(ctx: RpcContext, agent_id: str) -> str | None:
    registry = getattr(ctx, "agent_registry", None)
    getter = getattr(registry, "get_agent_model", None)
    if not callable(getter):
        return None
    try:
        return _model_value(getter(agent_id))
    except Exception:  # noqa: BLE001 - registry lookup must not break legacy sessions
        log.warning("sessions.agent_model_lookup_failed", agent_id=agent_id)
        return None


async def _agent_registry_has(ctx: RpcContext, agent_id: str) -> bool:
    """Return True iff *agent_id* exists in the registry (built-in main always True).

    Returns ``True`` when no registry is wired so legacy code paths that ran
    without an agent registry continue to work — the validation only kicks in
    when a registry is available to consult.
    """
    if normalize_agent_id(agent_id) == "main":
        return True
    registry = getattr(ctx, "agent_registry", None)
    lister = getattr(registry, "list_agents", None)
    if not callable(lister):
        return True
    try:
        agents = await lister(include_builtin=True)
    except Exception:  # noqa: BLE001 - never block session create on registry hiccups
        log.warning("sessions.agent_registry_list_failed", agent_id=agent_id)
        return True
    target = normalize_agent_id(agent_id)
    for entry in agents:
        if normalize_agent_id(str(entry.get("id", ""))) == target:
            return True
    return False


def _session_turn_model(ctx: RpcContext, session: Any | None, agent_id: str) -> str | None:
    return _model_value(getattr(session, "model", None)) or _agent_registry_model(ctx, agent_id)


async def _list_task_rows(ctx: RpcContext, storage: Any | None, session_key: str) -> list[Any]:
    return await _session_read_queries.list_task_rows(ctx, storage, session_key)


async def _list_task_rows_by_session(
    ctx: RpcContext,
    storage: Any | None,
    session_keys: list[str],
) -> dict[str, list[Any]]:
    return await _session_read_queries.list_task_rows_by_session(ctx, storage, session_keys)


def _create_session_key(agent_id: str, kind: object = None) -> str:
    short_id = uuid.uuid4().hex[:8]
    normalized_kind = str(kind or "").strip().lower().replace("_", "-")
    if normalized_kind == "web":
        normalized_kind = "webchat"
    if normalized_kind in {"cli", "webchat"}:
        return f"agent:{agent_id}:{normalized_kind}:{short_id}"
    return f"agent:{agent_id}:{short_id}"


async def _resolve_session_node(storage: Any, key: str) -> Any:
    return await _session_read_queries.resolve_session_node(storage, key)


@_d.method("sessions.list", scope="operator.read")
async def _handle_sessions_list(params: dict | None, ctx: RpcContext) -> dict:
    return await _session_read_queries.handle_sessions_list(params, ctx)


@_d.method("sessions.create", scope="operator.write")
async def _handle_sessions_create(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        params = {}
    agent_id = normalize_agent_id(params.get("agentId", "main"))
    display_name = params.get("displayName")
    message = params.get("message")
    model = _model_value(params.get("model")) or _agent_registry_model(ctx, agent_id)
    kind = params.get("kind") or params.get("sessionKind")
    if message is not None and not isinstance(message, str):
        raise ValueError("params.message must be a string")

    if not await _agent_registry_has(ctx, agent_id):
        raise RpcHandlerError(
            "agent.not_found",
            f"Agent '{agent_id}' does not exist",
            details=session_agent_not_found_details(agent_id),
        )

    if ctx.session_manager is None:
        if message:
            raise RpcUnavailableError("sessions.create(message=...) requires a session manager")
        key = _create_session_key(agent_id, kind)
        return session_create_stub_response(key)

    session = await ctx.session_manager.create(
        session_key=_create_session_key(agent_id, kind),
        agent_id=agent_id,
        display_name=display_name,
        model=model,
    )
    seeded_message = False

    if message:
        _persisted = await ctx.session_manager.append_message(
            session.session_key,
            role="user",
            content=message,
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            message = _persisted.content
        seeded_message = True

    return session_create_response(session, seeded_message=seeded_message)


@_d.method("sessions.send", scope="operator.write")
async def _handle_sessions_send(params: dict | None, ctx: RpcContext) -> dict:
    key = _require_key(params)
    if not isinstance(params, dict) or "message" not in params:
        raise ValueError("params.message is required")

    message_text: str = params["message"]
    semantic_message_text = message_text
    attachments_cfg = getattr(ctx.config, "attachments", None)
    persist_enabled = bool(getattr(attachments_cfg, "persist_transcripts", True))
    media_root = media_root_from_config(ctx.config)
    session_id = key.split(":")[-1] or key
    disk_budget = getattr(attachments_cfg, "transcript_disk_budget_bytes", None)
    ingested_attachments = await _attachment_ingest.ingest_attachments(
        message_text,
        params.get("attachments", []),
        failure_mode="raise",
        material_root=media_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget if isinstance(disk_budget, int) else None,
    )
    message_text = ingested_attachments.text
    raw_attachments = ingested_attachments.attachments
    # Evict consumed uuids only after the turn is accepted.
    _consumed_file_uuids: list[str] = list(ingested_attachments.consumed_file_uuids)
    from opensquilla.session.models import SessionIntent

    try:
        session_intent = SessionIntent(params.get("intent", SessionIntent.CONTINUE.value))
    except ValueError as exc:
        raise ValueError(f"Invalid session intent: {params.get('intent')}") from exc
    log.info(
        "sessions.send.params",
        session_key=key,
        message_len=len(message_text),
        attachments_count=len(raw_attachments),
    )

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    session = await storage.get_session(key)
    if session is None and session_intent is SessionIntent.CONTINUE:
        raise KeyError(f"Session not found: {key}")

    if "apply_intent" in dir(ctx.session_manager):
        session, _intent_applied = await ctx.session_manager.apply_intent(
            key,
            session_intent,
            agent_id=normalize_agent_id(session.agent_id if session is not None else "main"),
        )
    elif session_intent is not SessionIntent.CONTINUE:
        raise RuntimeError("Session intent handling requires SessionManager.apply_intent")

    source_hint = params.get("_source") if isinstance(params, dict) else None
    if not isinstance(source_hint, dict):
        source_hint = {}

    from opensquilla.gateway.routing import (
        build_cli_route_envelope,
        build_web_route_envelope,
    )

    agent_id = normalize_agent_id(session.agent_id if session is not None else "main")
    if source_hint.get("caller_kind") == "cli" or source_hint.get("channel_kind") == "cli":
        route_envelope = build_cli_route_envelope(
            session_key=key,
            agent_id=agent_id,
            source_name=source_hint.get("source_name") or "rpc",
            channel_id=source_hint.get("channel_id") or "cli:rpc",
            sender_id=source_hint.get("sender_id"),
            session_id=getattr(session, "session_id", None),
            principal_is_owner=ctx.principal.is_owner,
        )
    else:
        route_envelope = build_web_route_envelope(
            session_key=key,
            agent_id=agent_id,
            conn_id=ctx.conn_id,
            sender_id=source_hint.get("sender_id"),
            channel_id=source_hint.get("channel_id") or f"web:{ctx.conn_id}",
            source_name=source_hint.get("source_name") or "RPC",
            tool_source_kind=source_hint.get("source_kind"),
            session_id=getattr(session, "session_id", None),
            principal_is_owner=ctx.principal.is_owner,
        )
    elevated_hint = trusted_elevated_hint(ctx.principal.is_owner, source_hint)
    if elevated_hint is not None:
        route_envelope.metadata["elevated"] = elevated_hint

    capture_controls = normalize_memory_capture_controls(params)
    if capture_controls["input_provenance"] is not None:
        route_envelope = replace(
            route_envelope,
            input_provenance=capture_controls["input_provenance"],
        )
    run_kind = capture_controls["run_kind"] or "session_turn"

    # 1. Persist user message to transcript (include attachment metadata).
    # Hold the per-session lock used by /reset so a concurrent reset cannot
    # tear the append and leak an orphan user turn into the cleared transcript.
    _persist_lock = get_session_lock(ctx.turn_runner, key)
    persisted_entry: Any = None

    async def _persist_user_message() -> None:
        nonlocal message_text, persisted_entry
        if raw_attachments:
            from opensquilla.gateway.transcripts import (
                build_transcript_attachment_envelope,
            )

            # Stamp up-front so both the stored envelope and the LLM path agree.
            if hasattr(ctx.session_manager, "stamp_user_text"):
                _stamped = ctx.session_manager.stamp_user_text(message_text)
                if isinstance(_stamped, str):
                    message_text = _stamped

            persist_content, _writes = build_transcript_attachment_envelope(
                text=message_text,
                attachments=raw_attachments,
                session_id=session_id,
                media_root=media_root,
                persist_enabled=persist_enabled,
                disk_budget_bytes=disk_budget if isinstance(disk_budget, int) else None,
            )
            persisted_entry = await ctx.session_manager.append_message(
                key, role="user", content=persist_content
            )
        else:
            persisted_entry = await ctx.session_manager.append_message(
                key, role="user", content=message_text
            )
            if persisted_entry is not None and isinstance(persisted_entry.content, str):
                message_text = persisted_entry.content

    if _persist_lock is None:
        await _persist_user_message()
    else:
        async with _persist_lock:
            await _persist_user_message()

    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        requested_mode = (
            params.get("queueMode")
            or params.get("queue_mode")
            or getattr(session, "queue_mode", None)
            or "followup"
        )
        runtime_mode = "interrupt" if requested_mode == "steer" else requested_mode
        return await enqueue_session_turn_via_runtime(
            task_runtime,
            route_envelope=route_envelope,
            message_text=message_text,
            raw_attachments=raw_attachments,
            runtime_mode=runtime_mode,
            run_kind=run_kind,
            no_memory_capture=bool(capture_controls["no_memory_capture"]),
            semantic_message_text=semantic_message_text,
            session_manager=ctx.session_manager,
            session_key=key,
            persisted_entry=persisted_entry,
            consumed_file_uuids=_consumed_file_uuids,
        )

    # 2. Run agent turn in background via TurnRunner
    async def _run() -> None:
        _terminal_emitted = False

        def _current_task() -> asyncio.Task | None:
            task = asyncio.current_task()
            return task if isinstance(task, asyncio.Task) else None

        def _mark_started() -> None:
            task = _current_task()
            if task is not None:
                setattr(task, "_opensquilla_started", True)

        async def _emit_terminal_once(event_name: str, payload: dict[str, Any]) -> None:
            nonlocal _terminal_emitted
            task = _current_task()
            if _terminal_emitted or (
                task is not None and getattr(task, "_opensquilla_terminal_emitted", False)
            ):
                return
            _terminal_emitted = True
            if task is not None:
                setattr(task, "_opensquilla_terminal_emitted", True)
            payload = normalize_terminal_event_payload(event_name, payload)
            await _emit_to_subscribers(ctx, key, event_name, payload)

        try:
            _mark_started()
            # A new user turn invalidates any "once" intent approvals from the
            # previous turn. "always" entries survive per IntentApprovalCache
            # scope semantics.
            try:
                from opensquilla.application.intent_cache import get_intent_cache

                get_intent_cache().clear_scope("once")
            except Exception:  # pragma: no cover — never block turn start
                pass
            if ctx.turn_runner is None:
                log.error("sessions.send.no_turn_runner", session_key=key)
                await ctx.session_manager.append_message(
                    key, role="system", content="Error: No turn runner available"
                )
                await _emit_terminal_once(
                    "session.event.error",
                    {"message": "No turn runner available", "code": "no_turn_runner"},
                )
                return

            from opensquilla.agents.scope import resolve_agent_workspace_dir
            from opensquilla.gateway.routing import tool_context_from_envelope
            from opensquilla.runtime.stream_wrappers import wrap_stream

            workspace_dir = resolve_agent_workspace_dir(agent_id, ctx.config)
            workspace_strict = getattr(ctx.config, "workspace_strict", None)
            if not isinstance(workspace_strict, bool):
                workspace_strict = bool(workspace_dir)
            tool_ctx = tool_context_from_envelope(
                route_envelope,
                is_owner=ctx.principal.is_owner,
                workspace_dir=str(workspace_dir),
                workspace_strict=workspace_strict,
            )
            raw_stream = ctx.turn_runner.run(
                message_text,
                key,
                tool_context=tool_ctx,
                agent_id=agent_id,
                model=_session_turn_model(ctx, session, agent_id),
                attachments=raw_attachments,
                session_intent=session_intent.value,
                input_provenance=route_envelope.input_provenance,
                run_kind=run_kind,
                no_memory_capture=capture_controls["no_memory_capture"],
                semantic_message=semantic_message_text,
            )
            stream_idle_timeout = _optional_positive_timeout(
                ctx.config, "agent_stream_idle_timeout_seconds", 180.0
            )
            heartbeat_interval = _optional_positive_timeout(
                ctx.config, "agent_stream_heartbeat_interval_seconds", 15.0
            )
            async for event in wrap_stream(
                raw_stream,
                idle_timeout=stream_idle_timeout,
                heartbeat_interval=heartbeat_interval,
                heartbeat_message="Agent run is still active",
            ):
                event_dict = asdict(event)
                event_kind = event_dict.pop("kind", event.__class__.__name__)
                if event_kind in ("done", "error"):
                    await _emit_terminal_once(f"session.event.{event_kind}", event_dict)
                else:
                    await _emit_to_subscribers(ctx, key, f"session.event.{event_kind}", event_dict)

            await _emit_to_subscribers(
                ctx, key, "sessions.changed", {"key": key, "reason": "turn_complete"}
            )
        except asyncio.CancelledError:
            log.info("sessions.send.aborted", session_key=key)
            try:
                await _emit_terminal_once("session.event.done", {"reason": "aborted"})
            except Exception:
                pass
        except TimeoutError:
            log.warning("sessions.send.stream_idle_timeout", session_key=key)
            await ctx.session_manager.append_message(
                key, role="system", content=f"Error: {_STREAM_IDLE_TIMEOUT_MESSAGE}"
            )
            await _emit_terminal_once(
                "session.event.error",
                {"message": _STREAM_IDLE_TIMEOUT_MESSAGE, "code": _STREAM_IDLE_TIMEOUT_CODE},
            )
        except Exception as exc:
            log.error("sessions.send.agent_failed", session_key=key, error=str(exc), exc_info=True)
            await ctx.session_manager.append_message(key, role="system", content=f"Error: {exc}")
            await _emit_terminal_once(
                "session.event.error",
                {"message": str(exc), "code": "agent_error"},
            )
        finally:
            if not _terminal_emitted:
                try:
                    await _emit_terminal_once(
                        "session.event.error",
                        {"message": "Agent task terminated unexpectedly", "code": "task_cancelled"},
                    )
                except Exception:
                    pass

    task = asyncio.create_task(_run())
    setattr(task, "_opensquilla_started", False)
    setattr(task, "_opensquilla_terminal_emitted", False)
    get_agent_task_registry().register(key, task)
    # Same eviction semantic as the task_runtime success path: the turn was
    # accepted into a background TurnRunner task, so consumed uuids can be
    # evicted from the upload store rather than waiting out the TTL window.
    if _consumed_file_uuids:
        from opensquilla.gateway.uploads import get_upload_store

        _store = get_upload_store()
        for _u in _consumed_file_uuids:
            try:
                await _store.evict(_u)
            except Exception:  # noqa: BLE001 — eviction is best-effort
                log.warning("uploads.evict_failed_post_turn uuid=%s", _u[:8])
    return session_send_accepted_response(key)


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
    key = _require_key(params)

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    session = await storage.get_session(key)
    if session is None:
        raise KeyError(f"Session not found: {key}")

    update_values: dict[str, Any] = {}
    assert isinstance(params, dict)
    field_map = {
        "displayName": "display_name",
        "model": "model",
        "thinkingLevel": "thinking_level",
        "metadata": "meta",
    }
    updated_fields: list[str] = []
    for field, attr in field_map.items():
        if field in params and hasattr(session, attr):
            update_values[attr] = params[field]
            updated_fields.append(field)

    if update_values:
        update = getattr(ctx.session_manager, "update", None)
        if update is not None:
            await update(key, **update_values)
        else:
            for attr, value in update_values.items():
                setattr(session, attr, value)
            upsert = getattr(storage, "upsert_session", None)
            if upsert is not None:
                await upsert(session)

    return session_patch_response(key, updated_fields)


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
