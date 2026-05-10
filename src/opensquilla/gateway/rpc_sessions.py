"""RPC handlers for the sessions domain."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, replace
from typing import Any

import structlog

from opensquilla.engine.start_turn import start_turn_via_runtime
from opensquilla.gateway import attachment_ingest as _attachment_ingest
from opensquilla.gateway.agent_tasks import get_agent_task_registry
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, RpcUnavailableError, get_dispatcher
from opensquilla.gateway.session_services import (
    get_session_epoch,
    get_session_lock,
    get_session_storage,
    set_session_epoch,
)
from opensquilla.gateway.session_streams import get_session_streams
from opensquilla.paths import media_root_from_config
from opensquilla.session.compaction import (
    build_compaction_config_from_provider,
    call_compact_with_optional_config,
)
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
from opensquilla.session.terminal_reply import build_terminal_reply

_d = get_dispatcher()
log = structlog.get_logger(__name__)
_ELEVATED_MODES = frozenset({"on", "bypass", "full"})

_ALLOWED_MEDIA_TYPES = _attachment_ingest.ALLOWED_MEDIA_TYPES
_MAX_ATTACHMENT_BYTES = _attachment_ingest.MAX_ATTACHMENT_BYTES
_MAX_STAGED_PDF_BYTES = _attachment_ingest.MAX_STAGED_PDF_BYTES
_MAX_TEXT_ATTACHMENT_BYTES = _attachment_ingest.TEXT_ATTACHMENT_BYTES
_MAX_TOTAL_ATTACHMENT_BYTES = _attachment_ingest.MAX_TOTAL_ATTACHMENT_BYTES
_MAX_ATTACHMENTS = _attachment_ingest.MAX_ATTACHMENTS
_attachment_media_type = _attachment_ingest.attachment_media_type
_normalize_attachments = _attachment_ingest.normalize_attachments
_sniff_mime_from_bytes = _attachment_ingest.sniff_mime_from_bytes


def _trusted_elevated_hint(ctx: RpcContext, source_hint: dict[str, Any]) -> str | None:
    """Return an operator-owned elevated hint, or None."""

    value = source_hint.get("elevated")
    if isinstance(value, str) and value in _ELEVATED_MODES and ctx.principal.is_owner:
        return value
    return None


_STREAM_IDLE_TIMEOUT_CODE = "stream_idle_timeout"
_STREAM_IDLE_TIMEOUT_MESSAGE = "Session event stream idle before terminal event"
_RESET_RUNTIME_SETTLE_SECONDS = 0.25
_RESET_RUNTIME_CANCEL_DRAIN_SECONDS = 2.0
_ACTIVE_TASK_STATUSES = frozenset({"queued", "running"})


def _task_status_value(status: Any) -> str:
    return str(getattr(status, "value", status) or "")


async def _drain_task_runtime_for_reset(task_runtime: Any, session_key: str) -> None:
    """Cancel live runtime work without racing a just-finished turn.

    The task runtime emits ``session.event.done`` from inside the turn handler,
    then marks the runtime task terminal immediately after the handler returns.
    A client that calls reset on the done event can arrive during that narrow
    post-done/pre-terminal window. Give running tasks a short chance to settle
    before issuing cancellation so reset does not append a false
    ``[interrupted]`` marker into the transcript being flushed.
    """
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

def _optional_positive_timeout(config: Any, attr: str, default: float) -> float | None:
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


def _optional_stream_seq(params: dict | None) -> int | None:
    if not isinstance(params, dict):
        return None
    raw = params.get("since_stream_seq", params.get("sinceStreamSeq"))
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _buffer_session_event(
    session_key: str,
    event_name: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if event_name.startswith("session.event."):
        return get_session_streams().record(session_key, event_name, payload)
    return dict(payload or {})


async def _resolve_attachments(
    validated: list[dict[str, Any]],
    store: Any | None = None,
    *,
    material_root: Any | None = None,
    session_id: str | None = None,
    disk_budget_bytes: int | None = None,
) -> list[dict[str, Any]]:
    resolved, _consumed = await _attachment_ingest.resolve_attachments(
        validated,
        store=store,
        material_root=material_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget_bytes,
    )
    return resolved


def _validate_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    validated, _failures = _attachment_ingest.validate_attachments(
        raw_attachments,
        logger=log,
    )
    return validated


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _first_dict_value(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return None


def _normalize_memory_capture_controls(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize RPC/chat memory-capture controls onto snake_case fields."""

    source_hint = params.get("_source")
    if not isinstance(source_hint, dict):
        source_hint = {}

    no_memory_capture = _coerce_optional_bool(
        params.get("no_memory_capture", params.get("noMemoryCapture"))
    )
    if no_memory_capture is None:
        no_memory_capture = _coerce_optional_bool(
            source_hint.get("no_memory_capture", source_hint.get("noMemoryCapture"))
        )

    input_provenance = _first_dict_value(
        params.get("input_provenance"),
        params.get("inputProvenance"),
        source_hint.get("input_provenance"),
        source_hint.get("inputProvenance"),
    )
    provenance_kind = (
        params.get("input_provenance_kind")
        or params.get("inputProvenanceKind")
        or params.get("provenance_kind")
        or source_hint.get("input_provenance_kind")
        or source_hint.get("inputProvenanceKind")
        or source_hint.get("provenance_kind")
    )
    if input_provenance is None and provenance_kind:
        input_provenance = {"kind": str(provenance_kind)}
    elif input_provenance is not None and "kind" not in input_provenance and provenance_kind:
        input_provenance["kind"] = str(provenance_kind)

    run_kind = params.get("run_kind", params.get("runKind"))
    if run_kind is None:
        run_kind = source_hint.get("run_kind", source_hint.get("runKind"))

    return {
        "no_memory_capture": bool(no_memory_capture),
        "input_provenance": input_provenance,
        "run_kind": str(run_kind) if run_kind is not None and str(run_kind) else None,
    }


def _require_key(params: dict | None) -> str:
    if not isinstance(params, dict) or "key" not in params:
        raise ValueError("params.key is required")
    key = params["key"]
    if not isinstance(key, str):
        raise ValueError("params.key must be a string")
    return canonicalize_session_key(key)


def _context_window_tokens(params: dict | None, ctx: RpcContext) -> int:
    raw: Any = None
    if isinstance(params, dict):
        raw = params.get("contextWindowTokens", params.get("context_window_tokens"))
    if raw is None:
        raw = getattr(ctx.config, "context_budget_tokens", 100_000)
    if isinstance(raw, bool):
        raise ValueError("contextWindowTokens must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("contextWindowTokens must be a positive integer") from exc
    if value <= 0:
        raise ValueError("contextWindowTokens must be a positive integer")
    return value


def _effective_compaction_model(session: Any | None) -> str | None:
    if session is None:
        return None
    return getattr(session, "model_override", None) or getattr(session, "model", None)


def _resolve_compaction_provider(ctx: RpcContext, session: Any | None) -> Any | None:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None:
        return None

    resolved_selector = selector
    clone = getattr(selector, "clone", None)
    if callable(clone):
        try:
            resolved_selector = clone()
        except Exception:  # noqa: BLE001
            resolved_selector = selector

    model = _effective_compaction_model(session)
    if model and resolved_selector is not selector:
        override = getattr(resolved_selector, "override_model", None)
        if callable(override):
            try:
                override(model)
            except Exception:  # noqa: BLE001
                pass

    resolver = getattr(resolved_selector, "resolve", None)
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:  # noqa: BLE001
        return None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


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


def _task_summary(row: Any) -> dict[str, Any]:
    summary = {
        "task_id": getattr(row, "task_id", None),
        "status": _enum_value(getattr(row, "status", None)),
        "queue_mode": _enum_value(getattr(row, "queue_mode", None)),
        "run_kind": getattr(row, "run_kind", None),
        "source_kind": getattr(row, "source_kind", None),
        "created_at": getattr(row, "created_at", None),
        "started_at": getattr(row, "started_at", None),
    }
    finished_at = getattr(row, "finished_at", None)
    if finished_at is not None:
        summary["finished_at"] = finished_at
    terminal_reason = getattr(row, "terminal_reason", None)
    if terminal_reason is not None:
        summary["terminal_reason"] = terminal_reason
    if summary.get("status") in {"failed", "timeout", "abandoned", "cancelled"}:
        summary["terminal_message"] = build_terminal_reply(
            {
                "status": summary.get("status"),
                "terminal_reason": terminal_reason,
                "error_class": getattr(row, "error_class", None),
                "error_message": getattr(row, "error_message", None),
            }
        )
    return summary


def _normalize_terminal_event_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_name != "session.event.error":
        return payload

    message = payload.get("message")
    error_message = payload.get("error_message")
    raw_message = error_message if isinstance(error_message, str) and error_message else message
    raw_text = raw_message if isinstance(raw_message, str) and raw_message else "Agent error"
    code = payload.get("code")
    code_text = str(code or "").lower()
    is_timeout = "timeout" in code_text or "stream idle" in raw_text.lower()
    terminal_payload = {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": payload.get("terminal_reason")
        or ("timeout" if is_timeout else "error"),
        "error_class": code,
        "error_message": raw_text,
        **payload,
    }
    terminal_message = build_terminal_reply(terminal_payload)
    return {
        **payload,
        "message": terminal_message,
        "terminal_message": terminal_message,
        "terminal_reason": terminal_payload["terminal_reason"],
        "error_message": raw_text,
    }


def _sorted_task_rows(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda row: getattr(row, "created_at", 0) or 0, reverse=True)


def _active_task_summary(rows: list[Any]) -> dict[str, Any] | None:
    active = [
        row for row in rows if _enum_value(getattr(row, "status", None)) in {"queued", "running"}
    ]
    if not active:
        return None
    return _task_summary(_sorted_task_rows(active)[0])


def _last_task_summary(rows: list[Any]) -> dict[str, Any] | None:
    if not rows:
        return None
    return _task_summary(_sorted_task_rows(rows)[0])


def _task_run_status(active_task: dict[str, Any] | None, last_task: dict[str, Any] | None) -> str:
    if active_task is not None:
        status = active_task.get("status")
        return str(status or "running")
    if last_task is None:
        return "idle"
    status = str(last_task.get("status") or "")
    if status == "abandoned":
        return "interrupted"
    if status in {"failed", "timeout", "cancelled"}:
        return status
    return "idle"


def _task_state_summary(rows: list[Any]) -> dict[str, Any]:
    active_task = _active_task_summary(rows)
    last_task = _last_task_summary(rows)
    return {
        "tasks": [_task_summary(row) for row in _sorted_task_rows(rows)],
        "active_task": active_task,
        "last_task": last_task,
        "run_status": _task_run_status(active_task, last_task),
    }


async def _list_task_rows(ctx: RpcContext, storage: Any | None, session_key: str) -> list[Any]:
    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        runtime_list = getattr(task_runtime, "list", None)
        if callable(runtime_list):
            try:
                return list(await runtime_list(session_key=session_key))
            except Exception:
                log.warning("sessions.task_runtime_state_failed", session_key=session_key)

    if storage is None:
        return []
    storage_list = getattr(storage, "list_agent_tasks", None)
    if not callable(storage_list):
        return []
    try:
        return list(await storage_list(session_key=session_key))
    except Exception:
        log.warning("sessions.agent_task_storage_state_failed", session_key=session_key)
        return []


async def _list_task_rows_by_session(
    ctx: RpcContext,
    storage: Any | None,
    session_keys: list[str],
) -> dict[str, list[Any]]:
    keys = [canonicalize_session_key(key) for key in session_keys]
    if not keys:
        return {}

    if storage is not None:
        storage_batch = getattr(storage, "list_agent_tasks_for_sessions", None)
        if callable(storage_batch):
            try:
                grouped = await storage_batch(keys)
                return {key: list(grouped.get(key, [])) for key in keys}
            except Exception:
                log.warning("sessions.agent_task_storage_batch_state_failed")

    return {key: await _list_task_rows(ctx, storage, key) for key in keys}


def _create_session_key(agent_id: str, kind: object = None) -> str:
    short_id = uuid.uuid4().hex[:8]
    normalized_kind = str(kind or "").strip().lower().replace("_", "-")
    if normalized_kind == "web":
        normalized_kind = "webchat"
    if normalized_kind in {"cli", "webchat"}:
        return f"agent:{agent_id}:{normalized_kind}:{short_id}"
    return f"agent:{agent_id}:{short_id}"


def _derive_source_metadata(session: Any) -> dict[str, Any]:
    key = str(getattr(session, "session_key", "") or "")
    origin = getattr(session, "origin", None)
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None
    last_channel = getattr(session, "last_channel", None)
    channel = getattr(session, "channel", None)
    source_kind = origin_kind
    channel_kind = last_channel or channel
    if ":webchat:" in key:
        source_kind = source_kind or "webui"
        channel_kind = channel_kind or "webchat"
    elif ":cli:" in key or ":standalone:" in key:
        source_kind = source_kind or "cli"
        channel_kind = channel_kind or "cli"
    elif ":subagent:" in key:
        source_kind = source_kind or "subagent"
        channel_kind = channel_kind or "subagent"
    elif key.startswith("cron:") or ":cron:" in key:
        source_kind = source_kind or "cron"
        channel_kind = channel_kind or "cron"
    elif last_channel:
        source_kind = source_kind or "channel"
    return {
        "source_kind": source_kind,
        "sourceKind": source_kind,
        "channel_kind": channel_kind,
        "channelKind": channel_kind,
        "channel_id": getattr(session, "last_to", None),
        "channelId": getattr(session, "last_to", None),
    }


async def _resolve_session_node(storage: Any, key: str) -> Any:
    session = await storage.get_session(key)
    if session is not None:
        return session

    sessions = await storage.list_sessions(limit=500)
    matches: list[Any] = []
    for candidate in sessions:
        values = [
            getattr(candidate, "session_key", ""),
            getattr(candidate, "session_id", ""),
            getattr(candidate, "display_name", "") or "",
            getattr(candidate, "derived_title", "") or "",
        ]
        if any(str(value) == key or str(value).startswith(key) for value in values if value):
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = ", ".join(str(getattr(match, "session_key", "")) for match in matches[:5])
        raise ValueError(f"Ambiguous session id {key!r}; matches: {candidates}")
    raise KeyError(f"Session not found: {key}")


@_d.method("sessions.list", scope="operator.read")
async def _handle_sessions_list(params: dict | None, ctx: RpcContext) -> dict:
    """List all sessions."""
    now_ms = int(time.time() * 1000)

    if ctx.session_manager is None:
        return {"sessions": [], "count": 0, "ts": now_ms}

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        return {"sessions": [], "count": 0, "ts": now_ms}

    limit = (params or {}).get("limit", 50)
    sessions = await storage.list_sessions(limit=limit)
    task_rows_by_session = await _list_task_rows_by_session(
        ctx,
        storage,
        [s.session_key for s in sessions],
    )

    result = []
    for s in sessions:
        # Fetch entry count for metadata
        entry_count = 0
        try:
            entry_count = await storage.count_transcript_entries(s.session_id)
        except Exception:
            pass

        row = {
            "key": s.session_key,
            "agent_id": getattr(s, "agent_id", None),
            "agentId": getattr(s, "agent_id", None),
            "status": getattr(s, "status", "unknown"),
            "model": getattr(s, "model", None),
            "updated_at": getattr(s, "updated_at", now_ms),
            "updatedAt": getattr(s, "updated_at", now_ms),
            "display_name": getattr(s, "display_name", None),
            "displayName": getattr(s, "display_name", None),
            "channel": getattr(s, "channel", None),
            "chat_type": getattr(s, "chat_type", None),
            "chatType": getattr(s, "chat_type", None),
            "group_id": getattr(s, "group_id", None),
            "groupId": getattr(s, "group_id", None),
            "subject": getattr(s, "subject", None),
            "last_channel": getattr(s, "last_channel", None),
            "lastChannel": getattr(s, "last_channel", None),
            "last_to": getattr(s, "last_to", None),
            "lastTo": getattr(s, "last_to", None),
            "last_account_id": getattr(s, "last_account_id", None),
            "lastAccountId": getattr(s, "last_account_id", None),
            "last_thread_id": getattr(s, "last_thread_id", None),
            "lastThreadId": getattr(s, "last_thread_id", None),
            "delivery_context": getattr(s, "delivery_context", None),
            "deliveryContext": getattr(s, "delivery_context", None),
            "parent_session_key": getattr(s, "parent_session_key", None),
            "parentSessionKey": getattr(s, "parent_session_key", None),
            "spawned_by": getattr(s, "spawned_by", None),
            "spawnedBy": getattr(s, "spawned_by", None),
            "origin": getattr(s, "origin", None),
            "message_count": entry_count,
            "entry_count": entry_count,
            "size_bytes": None,
        }
        row.update(_derive_source_metadata(s))
        task_rows = task_rows_by_session.get(canonicalize_session_key(s.session_key), [])
        row.update(_task_state_summary(task_rows))
        result.append(row)

    return {"sessions": result, "count": len(result), "ts": now_ms}


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
            details={"agentId": agent_id},
        )

    if ctx.session_manager is None:
        if message:
            raise RpcUnavailableError("sessions.create(message=...) requires a session manager")
        key = _create_session_key(agent_id, kind)
        return {
            "key": key,
            "sessionId": key.rsplit(":", 1)[-1],
            "note": "session manager not available",
        }

    session = await ctx.session_manager.create(
        session_key=_create_session_key(agent_id, kind),
        agent_id=agent_id,
        display_name=display_name,
        model=model,
    )
    result = {"key": session.session_key, "sessionId": session.session_id}

    if message:
        _persisted = await ctx.session_manager.append_message(
            session.session_key,
            role="user",
            content=message,
        )
        if _persisted is not None and isinstance(_persisted.content, str):
            message = _persisted.content
        result["seededMessage"] = True

    return result


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
    elevated_hint = _trusted_elevated_hint(ctx, source_hint)
    if elevated_hint is not None:
        route_envelope.metadata["elevated"] = elevated_hint

    capture_controls = _normalize_memory_capture_controls(params)
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
        try:
            handle = await start_turn_via_runtime(
                task_runtime,
                route_envelope,
                message_text,
                attachments=raw_attachments,
                mode=runtime_mode,
                run_kind=run_kind,
                no_memory_capture=bool(capture_controls["no_memory_capture"]),
                semantic_message=semantic_message_text,
            )
        except Exception as exc:
            # Ensure the uuid eviction does NOT fire on this
            # path. The locked semantic mandates that any rejection /
            # rollback / queue-full leaves the uuid alive until TTL so
            # the user can retry against the same uuid.
            _consumed_file_uuids = []  # noqa: F841 — explicit no-evict marker
            from opensquilla.gateway.task_runtime import TaskQueueFullError

            if not isinstance(exc, TaskQueueFullError):
                raise

            # Roll back the just-appended user turn so a retry doesn't leave
            # a ghost message in the transcript. If rollback fails (e.g.
            # storage error under load), surface a non-retryable error and
            # hand the orphan message_id to the client as an idempotency
            # token — clients must dedup before retrying.
            orphan_id = getattr(persisted_entry, "message_id", None)
            rollback_ok = False
            if orphan_id and hasattr(ctx.session_manager, "remove_message"):
                try:
                    rollback_ok = await ctx.session_manager.remove_message(key, orphan_id)
                except Exception as rb_exc:  # noqa: BLE001 — rollback is best-effort
                    log.warning(
                        "sessions.send.rollback_failed",
                        session_key=key,
                        message_id=orphan_id,
                        error=str(rb_exc),
                    )
                    rollback_ok = False

            if rollback_ok:
                raise RpcHandlerError(
                    "QUEUE_FULL",
                    "The session task queue is full. Try again after queued work completes.",
                    details={
                        "session_key": exc.session_key,
                        "max_pending": exc.max_pending,
                        "rollback_message_id": orphan_id,
                    },
                    retryable=True,
                ) from exc
            raise RpcHandlerError(
                "QUEUE_FULL_DIRTY",
                (
                    "The session task queue is full and the just-appended user "
                    "turn could not be rolled back. The transcript now contains "
                    "an orphan message; clients must dedup by orphan_message_id "
                    "before retrying."
                ),
                details={
                    "session_key": exc.session_key,
                    "max_pending": exc.max_pending,
                    "orphan_message_id": orphan_id,
                    "remediation": "client must dedup by message_id before retry",
                },
                retryable=False,
            ) from exc
        # Eviction hook: turn was accepted into the runtime,
        # post-resolution + post-engine-acceptance. Evict consumed uuids
        # so memory does not linger for the full TTL window. Locked
        # semantic mandates this fires ONLY here on the success path.
        if _consumed_file_uuids:
            from opensquilla.gateway.uploads import get_upload_store

            _store = get_upload_store()
            for _u in _consumed_file_uuids:
                try:
                    await _store.evict(_u)
                except Exception:  # noqa: BLE001 — eviction is best-effort
                    log.warning("uploads.evict_failed_post_turn uuid=%s", _u[:8])
        return {"status": "accepted", "key": key, "task_id": handle.task_id}

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
            payload = _normalize_terminal_event_payload(event_name, payload)
            await _emit_to_subscribers(ctx, key, event_name, payload)

        try:
            _mark_started()
            # A new user turn invalidates any "once" intent approvals from the
            # previous turn. "always" entries survive per IntentApprovalCache
            # scope semantics.
            try:
                from opensquilla.sandbox.intent_cache import get_intent_cache

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
            from opensquilla.engine.stream_wrappers import wrap_stream
            from opensquilla.gateway.routing import tool_context_from_envelope

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
    return {"status": "accepted", "key": key}


async def _emit_to_subscribers(
    ctx: RpcContext,
    session_key: str,
    event_name: str,
    payload: dict,
) -> None:
    """Send an event to all connections subscribed to a session's messages."""
    from opensquilla.gateway.websocket import get_registry

    # Inject current epoch into session.event.* and sessions.changed
    # payloads so the frontend _isStaleEpoch guard can filter pre-reset frames.
    # Read from the in-process cache on SessionManager (populated by reset path) to
    # avoid a DB SELECT on every high-frequency event such as text_delta.
    if event_name.startswith("session.event.") or event_name == "sessions.changed":
        session_manager = getattr(ctx, "session_manager", None)
        cached_epoch = get_session_epoch(session_manager, session_key)
        if cached_epoch is not None:
            payload = {**payload, "epoch": cached_epoch}
        else:
            storage = get_session_storage(session_manager)
            if storage is not None and hasattr(storage, "get_epoch"):
                try:
                    epoch = await storage.get_epoch(session_key)
                    # Populate cache for subsequent emits.
                    set_session_epoch(session_manager, session_key, epoch)
                    payload = {**payload, "epoch": epoch}
                except Exception:
                    pass  # best-effort; never block event delivery

    send_payload = _buffer_session_event(session_key, event_name, payload)

    sub_mgr = getattr(ctx, "subscription_manager", None)
    if sub_mgr is None:
        return

    registry = get_registry()
    conn_ids = sub_mgr.get_message_subscribers(session_key)

    # For session-level events, also include session subscribers
    if event_name.startswith("sessions."):
        conn_ids = conn_ids | sub_mgr.get_session_subscribers()

    for conn_id in conn_ids:
        conn = registry.get(conn_id)
        if conn is not None:
            try:
                await conn.send_event(event_name, send_payload)
            except Exception:
                log.warning("emit.send_failed", conn_id=conn_id, event=event_name)


@_d.method("sessions.abort", scope="operator.write")
async def _handle_sessions_abort(params: dict | None, ctx: RpcContext) -> dict:
    key = _require_key(params)

    if ctx.session_manager is None:
        return {"aborted": False, "key": key}

    storage = get_session_storage(ctx.session_manager)
    if storage:
        session = await storage.get_session(key)
        if session is None:
            raise KeyError(f"Session not found: {key}")

    task_runtime = getattr(ctx, "task_runtime", None)
    if task_runtime is not None:
        cancelled_count = await task_runtime.cancel(session_key=key)
        return {"aborted": cancelled_count > 0, "key": key}

    # Cancel running agent task via registry
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
        await _emit_to_subscribers(ctx, key, "session.event.done", {"reason": "aborted"})

    return {"aborted": cancelled, "key": key}


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

    return {"key": key, "updated": updated_fields}


@_d.method("sessions.reset", scope="operator.write")
async def _handle_sessions_reset(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Synchronous session reset with FlushReceipt.

    Sequence when ``ctx.flush_service`` is wired:
    1. Drain any in-flight turn task so the per-session lock is free.
    2. Acquire the per-session lock for the whole snapshot → flush → rotate
       window (prevents a late turn write after flush).
    3. Snapshot the transcript, execute the flush, then rotate via
       ``apply_intent(RESET_SAME_KEY)``.

    When ``ctx.flush_service`` is None (kill-switch path), falls back to
    PR2-pre behavior: no flush, no ``flush_receipt`` field in the response.
    """
    from opensquilla.gateway.rpc import RpcHandlerError
    from opensquilla.memory.session_flush import FlushReceipt
    from opensquilla.session.models import SessionIntent

    key = _require_key(params)

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    task_runtime = getattr(ctx, "task_runtime", None)
    # Drain MUST run before any branch that clears session state — including the
    # flush_service=None (kill-switch) path.  Skipping drain here would let a
    # still-running turn write its final message into the transcript *after*
    # apply_intent has rotated the session_id, producing an orphaned transcript
    # entry that is never flushed and never visible to the new session.
    # force=True does not bypass this: the operator wants a clean slate, not a
    # corrupted one.  drain() is idempotent when no task is running.
    if task_runtime is not None:
        await _drain_task_runtime_for_reset(task_runtime, key)

    force = bool((params or {}).get("force", False))

    if ctx.flush_service is None:
        session = await storage.get_session(key)
        if session is None:
            raise KeyError(f"Session not found: {key}")
        previous_session_id = session.session_id

        # Fail-closed when flush is unavailable: refuse to clear a non-empty
        # transcript without an explicit admin override. Empty transcripts are
        # always safe to rotate (nothing to lose).
        transcript = await ctx.session_manager.get_transcript(key)
        if transcript and not force:
            raise RpcHandlerError(
                code="flush_unavailable",
                message=(
                    "Reset aborted: flush service is unavailable and the "
                    "transcript is non-empty. Re-run with force=true (admin) "
                    "to discard without backup."
                ),
                details={
                    "key": key,
                    "session_id": previous_session_id,
                    "reason": "flush_service_disabled",
                    "message_count": len(transcript),
                },
            )
        if transcript and force and "operator.admin" not in ctx.principal.scopes:
            raise RpcHandlerError(
                code="permission_denied",
                message="force=true on sessions.reset requires operator.admin scope.",
                details={"key": key, "session_id": previous_session_id},
            )

        updated, rotated = await ctx.session_manager.apply_intent(key, SessionIntent.RESET_SAME_KEY)
        new_epoch = await _increment_and_emit_epoch(ctx, storage, key)
        return {
            "key": key,
            "reset": True,
            "rotated": rotated,
            "previous_session_id": previous_session_id,
            "session_id": updated.session_id,
            "epoch": new_epoch,
        }

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
            new_epoch = await _increment_and_emit_epoch(ctx, storage, key)
            receipt = FlushReceipt(
                mode="skipped",
                flushed_paths=[],
                slug=None,
                message_count=0,
                duration_ms=0,
                raw_reason=None,
                error=None,
            )
            return _reset_response(
                key,
                rotated,
                previous_session_id,
                updated.session_id,
                receipt,
                new_epoch,
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
        except Exception as exc:  # noqa: BLE001 — both LLM and raw-dump failed
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
                details={
                    "flush_receipt": receipt.to_dict(),
                    "key": key,
                    "session_id": previous_session_id,
                },
            ) from exc

        # ``flush_service.execute`` can return ``mode="error"`` (no raise) when
        # both the LLM path and the raw-dump fallback fail. Treat that as a
        # hard failure so the transcript is preserved instead of cleared.
        if receipt.mode == "error":
            raise RpcHandlerError(
                code="flush_disk_error",
                message=f"Reset aborted: flush failed ({receipt.error or 'unknown error'})",
                details={
                    "flush_receipt": receipt.to_dict(),
                    "key": key,
                    "session_id": previous_session_id,
                },
            )

        updated, rotated = await ctx.session_manager.apply_intent(key, SessionIntent.RESET_SAME_KEY)
        new_epoch = await _increment_and_emit_epoch(ctx, storage, key)
        return _reset_response(
            key,
            rotated,
            previous_session_id,
            updated.session_id,
            receipt,
            new_epoch,
        )

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()


async def _increment_and_emit_epoch(
    ctx: RpcContext,
    storage: Any,
    session_key: str,
) -> int:
    """Atomically increment epoch and broadcast session.epoch_changed to WS subscribers.

    increment_epoch commits the UPDATE before returning, so new_epoch
    is durable before we attempt the WS emit.  If the emit fails the epoch is
    still committed — WS delivery is best-effort and the client will re-sync on
    reconnect.
    """
    increment_fn = getattr(storage, "increment_epoch", None)
    if not callable(increment_fn):
        return 0
    try:
        # Durable commit happens inside increment_epoch before it returns.
        new_epoch = int(await increment_fn(session_key))
    except Exception:
        log.warning("sessions.reset.epoch_increment_failed", session_key=session_key)
        return 0
    # Invalidate / update the in-process epoch cache so subsequent _emit_to_subscribers
    # calls read the new epoch without hitting the DB.
    session_manager = getattr(ctx, "session_manager", None)
    set_session_epoch(session_manager, session_key, new_epoch)
    # Emit after the storage commit — failure here is non-fatal; epoch is already
    # persisted and the client will re-sync on next reconnect.
    try:
        await _emit_to_subscribers(
            ctx,
            session_key,
            "session.epoch_changed",
            {"key": session_key, "epoch": new_epoch},
        )
    except Exception:
        log.warning(
            "sessions.reset.epoch_emit_failed",
            session_key=session_key,
            new_epoch=new_epoch,
        )
    return new_epoch


def _reset_response(
    key: str,
    rotated: bool,
    previous_session_id: str,
    session_id: str,
    receipt: Any,
    epoch: int = 0,
) -> dict[str, Any]:
    return {
        "key": key,
        "reset": True,
        "rotated": rotated,
        "previous_session_id": previous_session_id,
        "session_id": session_id,
        "epoch": epoch,
        "flush_receipt": receipt.to_dict(),
    }


@_d.method("sessions.delete", scope="operator.admin")
async def _handle_sessions_delete(params: dict | None, ctx: RpcContext) -> dict:
    """Delete one or more sessions. Accepts {key} for single or {keys} for bulk."""
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    # Support both single key and bulk keys
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
    for k in keys:
        try:
            await storage.delete_session(k)
            deleted.append(k)
        except Exception as exc:
            errors.append(f"{k}: {exc}")

    return {"deleted": deleted, "errors": errors}


@_d.method("sessions.contextCompact", scope="operator.write")
async def _handle_sessions_context_compact(params: dict | None, ctx: RpcContext) -> dict:
    key = _require_key(params)
    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    context_window_tokens = _context_window_tokens(params, ctx)
    turn_runner = ctx.turn_runner
    lock = get_session_lock(turn_runner, key)

    async def _run_locked() -> dict[str, Any]:
        storage = get_session_storage(ctx.session_manager)
        session = None
        if storage is not None and await storage.get_session(key) is None:
            raise KeyError(f"Session not found: {key}")
        if storage is not None:
            session = await storage.get_session(key)

        compaction_config = build_compaction_config_from_provider(
            _resolve_compaction_provider(ctx, session),
            model_override=_effective_compaction_model(session),
            compaction_config=getattr(getattr(ctx, "config", None), "compaction", None),
        )

        compact_with_result = getattr(ctx.session_manager, "compact_with_result", None)
        if callable(compact_with_result):
            result = await compact_with_result(key, context_window_tokens, compaction_config)
            summary = getattr(result, "summary", "") or ""
            removed_count = int(getattr(result, "removed_count", 0) or 0)
            summary_source = getattr(result, "summary_source", "unknown") or "unknown"
        else:
            compact = ctx.session_manager.compact
            summary = await call_compact_with_optional_config(
                compact,
                key,
                context_window_tokens,
                compaction_config,
            )
            removed_count = 1 if summary else 0
            summary_source = "unknown"
        return {
            "key": key,
            "compacted": removed_count > 0,
            "mode": "summary",
            "summary_len": len(summary),
            "summary_source": summary_source,
            "context_window_tokens": context_window_tokens,
        }

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()


@_d.method("sessions.compact", scope="operator.write")
async def _handle_sessions_compact(params: dict | None, ctx: RpcContext) -> dict:
    from opensquilla.memory.session_flush import FlushReceipt

    key = _require_key(params)
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
            # Fail-closed: refuse to truncate a non-empty transcript without
            # an admin force override. Empty transcripts are safe to truncate.
            transcript = await ctx.session_manager.get_transcript(key)
            if transcript and not force:
                raise RpcHandlerError(
                    code="flush_unavailable",
                    message=(
                        "Compact aborted: flush service is unavailable and "
                        "the transcript is non-empty. Re-run with force=true "
                        "(admin) to truncate without backup."
                    ),
                    details={
                        "key": key,
                        "session_id": previous_session_id,
                        "reason": "flush_service_disabled",
                        "message_count": len(transcript),
                    },
                )
            if transcript and force and "operator.admin" not in ctx.principal.scopes:
                raise RpcHandlerError(
                    code="permission_denied",
                    message="force=true on sessions.compact requires operator.admin scope.",
                    details={"key": key, "session_id": previous_session_id},
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
                except Exception as exc:  # noqa: BLE001 — both LLM and raw-dump failed
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
                        details={
                            "flush_receipt": receipt.to_dict(),
                            "key": key,
                            "session_id": previous_session_id,
                        },
                    ) from exc

                # ``flush_service.execute`` can return ``mode="error"`` (no
                # raise) when both LLM and raw-dump fallbacks fail. Treat as
                # hard failure so the transcript is preserved.
                if receipt.mode == "error":
                    raise RpcHandlerError(
                        code="flush_disk_error",
                        message=(
                            f"Compact aborted: flush failed ({receipt.error or 'unknown error'})"
                        ),
                        details={
                            "flush_receipt": receipt.to_dict(),
                            "key": key,
                            "session_id": previous_session_id,
                        },
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
        payload = {
            "key": key,
            "compacted": result["truncated"],
            "before_count": result["before_count"],
            "after_count": result["after_count"],
        }
        if receipt is not None:
            payload["flush_receipt"] = receipt.to_dict()
        return payload

    if lock is None:
        return await _run_locked()
    async with lock:
        return await _run_locked()


@_d.method("sessions.subscribe", scope="operator.read")
async def _handle_sessions_subscribe(params: dict | None, ctx: RpcContext) -> None:
    subscription_mgr = getattr(ctx, "subscription_manager", None)
    if subscription_mgr is not None:
        subscription_mgr.subscribe_sessions(ctx.conn_id)
    return None


@_d.method("sessions.unsubscribe", scope="operator.read")
async def _handle_sessions_unsubscribe(params: dict | None, ctx: RpcContext) -> None:
    subscription_mgr = getattr(ctx, "subscription_manager", None)
    if subscription_mgr is not None:
        subscription_mgr.unsubscribe_sessions(ctx.conn_id)
    return None


@_d.method("sessions.messages.subscribe", scope="operator.read")
async def _handle_sessions_messages_subscribe(params: dict | None, ctx: RpcContext) -> dict:
    key = _require_key(params)
    subscription_mgr = getattr(ctx, "subscription_manager", None)
    if subscription_mgr is not None:
        subscription_mgr.subscribe_messages(ctx.conn_id, key)

    replay = get_session_streams().replay(key, _optional_stream_seq(params))
    replayed_count = 0
    if subscription_mgr is not None and replay.events:
        from opensquilla.gateway.websocket import get_registry

        conn = get_registry().get(ctx.conn_id)
        if conn is not None:
            for event in replay.events:
                await conn.send_event(event.event_name, event.payload)
                replayed_count += 1

    storage = get_session_storage(getattr(ctx, "session_manager", None))
    task_rows = await _list_task_rows(ctx, storage, key)
    task_state = _task_state_summary(task_rows)

    return {
        "subscribed": subscription_mgr is not None,
        "key": key,
        "current_stream_seq": replay.current_stream_seq,
        "replay_complete": replay.replay_complete,
        "replay_gap_reason": replay.gap_reason,
        "replayed_count": replayed_count,
        **task_state,
    }


@_d.method("sessions.messages.unsubscribe", scope="operator.read")
async def _handle_sessions_messages_unsubscribe(params: dict | None, ctx: RpcContext) -> None:
    key = _require_key(params)
    subscription_mgr = getattr(ctx, "subscription_manager", None)
    if subscription_mgr is not None:
        subscription_mgr.unsubscribe_messages(ctx.conn_id, key)
    return None


@_d.method("sessions.preview", scope="operator.read")
async def _handle_sessions_preview(params: dict | None, ctx: RpcContext) -> dict:
    keys = (params or {}).get("keys")
    limit = (params or {}).get("limit", 50)
    now_ms = int(time.time() * 1000)

    if ctx.session_manager is None:
        return {"ts": now_ms, "previews": []}

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        return {"ts": now_ms, "previews": []}

    if keys:
        sessions = []
        for k in keys:
            s = await storage.get_session(k)
            if s is not None:
                sessions.append(s)
    else:
        sessions = await storage.list_sessions(limit=limit)

    previews = []
    for s in sessions:
        title = (
            getattr(s, "display_name", None)
            or getattr(s, "derived_title", None)
            or s.session_id[:8]
        )
        last_msg = ""
        try:
            transcript = await storage.get_transcript(s.session_id, limit=-1)
            if transcript:
                # Find the last user or assistant message for preview
                for entry in reversed(transcript):
                    if entry.role in ("user", "assistant") and entry.content:
                        last_msg = entry.content[:120]
                        break
        except Exception:
            pass
        previews.append(
            {
                "key": s.session_key,
                "title": title,
                "lastMessage": last_msg,
                "updatedAt": getattr(s, "updated_at", now_ms),
            }
        )

    return {"ts": now_ms, "previews": previews}


@_d.method("sessions.resolve", scope="operator.read")
async def _handle_sessions_resolve(params: dict | None, ctx: RpcContext) -> dict:
    key = _require_key(params)

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    session = await _resolve_session_node(storage, key)

    return {
        "session_key": session.session_key,
        "session_id": session.session_id,
        "status": session.status,
        "agent_id": session.agent_id,
        "model": getattr(session, "model", None),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }
