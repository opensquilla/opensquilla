"""RPC payload helpers for session-facing surfaces."""

from __future__ import annotations

from typing import Any

from opensquilla.session.terminal_reply import build_terminal_reply


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def task_summary(row: Any) -> dict[str, Any]:
    summary = {
        "task_id": getattr(row, "task_id", None),
        "status": enum_value(getattr(row, "status", None)),
        "queue_mode": enum_value(getattr(row, "queue_mode", None)),
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


def sorted_task_rows(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda row: getattr(row, "created_at", 0) or 0, reverse=True)


def active_task_summary(rows: list[Any]) -> dict[str, Any] | None:
    active = [
        row for row in rows if enum_value(getattr(row, "status", None)) in {"queued", "running"}
    ]
    if not active:
        return None
    return task_summary(sorted_task_rows(active)[0])


def last_task_summary(rows: list[Any]) -> dict[str, Any] | None:
    if not rows:
        return None
    return task_summary(sorted_task_rows(rows)[0])


def task_run_status(
    active_task: dict[str, Any] | None,
    last_task: dict[str, Any] | None,
) -> str:
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


def task_state_summary(rows: list[Any]) -> dict[str, Any]:
    active_task = active_task_summary(rows)
    last_task = last_task_summary(rows)
    return {
        "tasks": [task_summary(row) for row in sorted_task_rows(rows)],
        "active_task": active_task,
        "last_task": last_task,
        "run_status": task_run_status(active_task, last_task),
    }


def messages_subscribe_response(
    *,
    key: str,
    subscribed: bool,
    replay: Any,
    replayed_count: int,
    task_rows: list[Any],
) -> dict[str, Any]:
    return {
        "subscribed": subscribed,
        "key": key,
        "current_stream_seq": getattr(replay, "current_stream_seq"),
        "replay_complete": getattr(replay, "replay_complete"),
        "replay_gap_reason": getattr(replay, "gap_reason"),
        "replayed_count": replayed_count,
        **task_state_summary(task_rows),
    }


def normalize_terminal_event_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
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


def session_source_metadata(session: Any) -> dict[str, Any]:
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


def session_list_row(
    session: Any,
    *,
    entry_count: int,
    task_rows: list[Any],
    now_ms: int,
) -> dict[str, Any]:
    row = {
        "key": session.session_key,
        "agent_id": getattr(session, "agent_id", None),
        "agentId": getattr(session, "agent_id", None),
        "status": getattr(session, "status", "unknown"),
        "model": getattr(session, "model", None),
        "updated_at": getattr(session, "updated_at", now_ms),
        "updatedAt": getattr(session, "updated_at", now_ms),
        "display_name": getattr(session, "display_name", None),
        "displayName": getattr(session, "display_name", None),
        "channel": getattr(session, "channel", None),
        "chat_type": getattr(session, "chat_type", None),
        "chatType": getattr(session, "chat_type", None),
        "group_id": getattr(session, "group_id", None),
        "groupId": getattr(session, "group_id", None),
        "subject": getattr(session, "subject", None),
        "last_channel": getattr(session, "last_channel", None),
        "lastChannel": getattr(session, "last_channel", None),
        "last_to": getattr(session, "last_to", None),
        "lastTo": getattr(session, "last_to", None),
        "last_account_id": getattr(session, "last_account_id", None),
        "lastAccountId": getattr(session, "last_account_id", None),
        "last_thread_id": getattr(session, "last_thread_id", None),
        "lastThreadId": getattr(session, "last_thread_id", None),
        "delivery_context": getattr(session, "delivery_context", None),
        "deliveryContext": getattr(session, "delivery_context", None),
        "parent_session_key": getattr(session, "parent_session_key", None),
        "parentSessionKey": getattr(session, "parent_session_key", None),
        "spawned_by": getattr(session, "spawned_by", None),
        "spawnedBy": getattr(session, "spawned_by", None),
        "origin": getattr(session, "origin", None),
        "message_count": entry_count,
        "entry_count": entry_count,
        "size_bytes": None,
    }
    row.update(session_source_metadata(session))
    row.update(task_state_summary(task_rows))
    return row


def session_preview_last_message(entries: list[Any], *, max_chars: int = 120) -> str:
    for entry in reversed(entries):
        if enum_value(getattr(entry, "role", None)) in ("user", "assistant"):
            content = getattr(entry, "content", None)
            if content:
                return str(content)[:max_chars]
    return ""


def session_preview_row(
    session: Any,
    *,
    transcript: list[Any],
    now_ms: int,
) -> dict[str, Any]:
    title = (
        getattr(session, "display_name", None)
        or getattr(session, "derived_title", None)
        or session.session_id[:8]
    )
    return {
        "key": session.session_key,
        "title": title,
        "lastMessage": session_preview_last_message(transcript),
        "updatedAt": getattr(session, "updated_at", now_ms),
    }


def session_resolve_response(session: Any) -> dict[str, Any]:
    return {
        "session_key": session.session_key,
        "session_id": session.session_id,
        "status": session.status,
        "agent_id": session.agent_id,
        "model": getattr(session, "model", None),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def session_create_stub_response(
    key: str,
    *,
    note: str = "session manager not available",
) -> dict[str, Any]:
    return {
        "key": key,
        "sessionId": key.rsplit(":", 1)[-1],
        "note": note,
    }


def session_create_response(session: Any, *, seeded_message: bool = False) -> dict[str, Any]:
    response = {"key": session.session_key, "sessionId": session.session_id}
    if seeded_message:
        response["seededMessage"] = True
    return response


def session_patch_response(key: str, updated_fields: list[str]) -> dict[str, Any]:
    return {"key": key, "updated": updated_fields}


def session_delete_response(deleted: list[str], errors: list[str]) -> dict[str, Any]:
    return {"deleted": deleted, "errors": errors}


def session_reset_response(
    key: str,
    rotated: bool,
    previous_session_id: str,
    session_id: str,
    *,
    epoch: int = 0,
    receipt: Any | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "key": key,
        "reset": True,
        "rotated": rotated,
        "previous_session_id": previous_session_id,
        "session_id": session_id,
        "epoch": epoch,
    }
    if receipt is not None:
        response["flush_receipt"] = receipt.to_dict()
    return response


def session_context_compact_response(
    key: str,
    *,
    removed_count: int,
    summary: str,
    summary_source: str,
    context_window_tokens: int,
) -> dict[str, Any]:
    return {
        "key": key,
        "compacted": removed_count > 0,
        "mode": "summary",
        "summary_len": len(summary),
        "summary_source": summary_source,
        "context_window_tokens": context_window_tokens,
    }


def session_compact_response(
    key: str,
    result: dict[str, Any],
    *,
    receipt: Any | None = None,
) -> dict[str, Any]:
    payload = {
        "key": key,
        "compacted": result["truncated"],
        "before_count": result["before_count"],
        "after_count": result["after_count"],
    }
    if receipt is not None:
        payload["flush_receipt"] = receipt.to_dict()
    return payload


__all__ = [
    "active_task_summary",
    "enum_value",
    "last_task_summary",
    "messages_subscribe_response",
    "normalize_terminal_event_payload",
    "session_compact_response",
    "session_context_compact_response",
    "session_create_response",
    "session_create_stub_response",
    "session_delete_response",
    "session_list_row",
    "session_patch_response",
    "session_preview_last_message",
    "session_preview_row",
    "session_reset_response",
    "session_resolve_response",
    "session_source_metadata",
    "sorted_task_rows",
    "task_run_status",
    "task_state_summary",
    "task_summary",
]
