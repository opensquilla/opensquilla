"""Session send RPC orchestration for the gateway sessions domain."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from typing import Any

import structlog

from opensquilla.gateway import attachment_ingest
from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_session_send_inputs import (
    normalize_memory_capture_controls,
    trusted_elevated_hint,
)
from opensquilla.gateway.rpc_session_turn_runtime import enqueue_session_turn_via_runtime
from opensquilla.paths import media_root_from_config
from opensquilla.session.keys import normalize_agent_id
from opensquilla.session.management_service import (
    require_session_key,
    session_turn_model,
)
from opensquilla.session.rpc_payload import (
    normalize_terminal_event_payload,
    session_send_accepted_response,
)
from opensquilla.session.services import get_session_lock, get_session_storage

log = structlog.get_logger(__name__)
STREAM_IDLE_TIMEOUT_CODE = "stream_idle_timeout"
STREAM_IDLE_TIMEOUT_MESSAGE = "Session event stream idle before terminal event"


def optional_positive_timeout(config: Any, attr: str, default: float) -> float | None:
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


async def _emit_to_subscribers(
    ctx: RpcContext,
    session_key: str,
    event_name: str,
    payload: dict,
) -> None:
    from opensquilla.gateway.rpc_session_events import emit_to_session_subscribers

    await emit_to_session_subscribers(ctx, session_key, event_name, payload, logger=log)


async def handle_sessions_send(params: dict | None, ctx: RpcContext) -> dict:
    key = require_session_key(params)
    if not isinstance(params, dict) or "message" not in params:
        raise ValueError("params.message is required")

    message_text: str = params["message"]
    semantic_message_text = message_text
    attachments_cfg = getattr(ctx.config, "attachments", None)
    persist_enabled = bool(getattr(attachments_cfg, "persist_transcripts", True))
    media_root = media_root_from_config(ctx.config)
    session_id = key.split(":")[-1] or key
    disk_budget = getattr(attachments_cfg, "transcript_disk_budget_bytes", None)
    ingested_attachments = await attachment_ingest.ingest_attachments(
        message_text,
        params.get("attachments", []),
        failure_mode="raise",
        material_root=media_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget if isinstance(disk_budget, int) else None,
    )
    message_text = ingested_attachments.text
    raw_attachments = ingested_attachments.attachments
    consumed_file_uuids: list[str] = list(ingested_attachments.consumed_file_uuids)
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

    persist_lock = get_session_lock(ctx.turn_runner, key)
    persisted_entry: Any = None

    async def _persist_user_message() -> None:
        nonlocal message_text, persisted_entry
        if raw_attachments:
            from opensquilla.gateway.transcripts import (
                build_transcript_attachment_envelope,
            )

            if hasattr(ctx.session_manager, "stamp_user_text"):
                stamped = ctx.session_manager.stamp_user_text(message_text)
                if isinstance(stamped, str):
                    message_text = stamped

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

    if persist_lock is None:
        await _persist_user_message()
    else:
        async with persist_lock:
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
            consumed_file_uuids=consumed_file_uuids,
        )

    async def _run() -> None:
        terminal_emitted = False

        def _current_task() -> asyncio.Task | None:
            task = asyncio.current_task()
            return task if isinstance(task, asyncio.Task) else None

        def _mark_started() -> None:
            task = _current_task()
            if task is not None:
                setattr(task, "_opensquilla_started", True)

        async def _emit_terminal_once(event_name: str, payload: dict[str, Any]) -> None:
            nonlocal terminal_emitted
            task = _current_task()
            if terminal_emitted or (
                task is not None and getattr(task, "_opensquilla_terminal_emitted", False)
            ):
                return
            terminal_emitted = True
            if task is not None:
                setattr(task, "_opensquilla_terminal_emitted", True)
            payload = normalize_terminal_event_payload(event_name, payload)
            await _emit_to_subscribers(ctx, key, event_name, payload)

        try:
            _mark_started()
            try:
                from opensquilla.application.intent_cache import get_intent_cache

                get_intent_cache().clear_scope("once")
            except Exception:  # pragma: no cover - never block turn start
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

            from opensquilla.gateway.routing import tool_context_from_route_envelope
            from opensquilla.runtime.stream_wrappers import wrap_stream

            tool_ctx = tool_context_from_route_envelope(
                route_envelope,
                ctx.config,
                is_owner=ctx.principal.is_owner,
            )
            raw_stream = ctx.turn_runner.run(
                message_text,
                key,
                tool_context=tool_ctx,
                agent_id=agent_id,
                model=session_turn_model(ctx, session, agent_id),
                attachments=raw_attachments,
                session_intent=session_intent.value,
                input_provenance=route_envelope.input_provenance,
                run_kind=run_kind,
                no_memory_capture=capture_controls["no_memory_capture"],
                semantic_message=semantic_message_text,
            )
            stream_idle_timeout = optional_positive_timeout(
                ctx.config, "agent_stream_idle_timeout_seconds", 180.0
            )
            heartbeat_interval = optional_positive_timeout(
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
                key, role="system", content=f"Error: {STREAM_IDLE_TIMEOUT_MESSAGE}"
            )
            await _emit_terminal_once(
                "session.event.error",
                {"message": STREAM_IDLE_TIMEOUT_MESSAGE, "code": STREAM_IDLE_TIMEOUT_CODE},
            )
        except Exception as exc:
            log.error("sessions.send.agent_failed", session_key=key, error=str(exc), exc_info=True)
            await ctx.session_manager.append_message(key, role="system", content=f"Error: {exc}")
            await _emit_terminal_once(
                "session.event.error",
                {"message": str(exc), "code": "agent_error"},
            )
        finally:
            if not terminal_emitted:
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
    if consumed_file_uuids:
        from opensquilla.gateway.uploads import get_upload_store

        upload_store = get_upload_store()
        for upload_uuid in consumed_file_uuids:
            try:
                await upload_store.evict(upload_uuid)
            except Exception:  # noqa: BLE001 - eviction is best-effort
                log.warning("uploads.evict_failed_post_turn uuid=%s", upload_uuid[:8])
    return session_send_accepted_response(key)
