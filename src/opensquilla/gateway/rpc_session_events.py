"""Session event delivery helpers for gateway RPC handlers."""

from __future__ import annotations

from typing import Any

import structlog

from opensquilla.gateway.session_streams import SessionStreamRegistry, get_session_streams
from opensquilla.session.services import (
    get_session_epoch,
    get_session_storage,
    set_session_epoch,
)

log = structlog.get_logger(__name__)


def optional_stream_seq(params: dict | None) -> int | None:
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


def buffer_session_event(
    session_key: str,
    event_name: str,
    payload: dict[str, Any] | None,
    *,
    stream_registry: SessionStreamRegistry | None = None,
) -> dict[str, Any]:
    if event_name.startswith("session.event."):
        registry = stream_registry or get_session_streams()
        return registry.record(session_key, event_name, payload)
    return dict(payload or {})


async def emit_to_session_subscribers(
    ctx: Any,
    session_key: str,
    event_name: str,
    payload: dict[str, Any],
    *,
    stream_registry: SessionStreamRegistry | None = None,
    logger: Any | None = None,
) -> None:
    """Send a session event to current message/session subscribers."""
    from opensquilla.gateway.websocket import get_registry

    active_logger = logger or log

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
                    set_session_epoch(session_manager, session_key, epoch)
                    payload = {**payload, "epoch": epoch}
                except Exception:
                    pass

    send_payload = buffer_session_event(
        session_key,
        event_name,
        payload,
        stream_registry=stream_registry,
    )

    sub_mgr = getattr(ctx, "subscription_manager", None)
    if sub_mgr is None:
        return

    registry = get_registry()
    conn_ids = sub_mgr.get_message_subscribers(session_key)

    if event_name.startswith("sessions."):
        conn_ids = conn_ids | sub_mgr.get_session_subscribers()

    for conn_id in conn_ids:
        conn = registry.get(conn_id)
        if conn is not None:
            try:
                await conn.send_event(event_name, send_payload)
            except Exception:
                active_logger.warning("emit.send_failed", conn_id=conn_id, event=event_name)


async def increment_and_emit_epoch(
    ctx: Any,
    storage: Any,
    session_key: str,
    *,
    logger: Any | None = None,
) -> int:
    """Increment session epoch and broadcast the best-effort epoch_changed event."""
    active_logger = logger or log
    increment_fn = getattr(storage, "increment_epoch", None)
    if not callable(increment_fn):
        return 0
    try:
        new_epoch = int(await increment_fn(session_key))
    except Exception:
        active_logger.warning("sessions.reset.epoch_increment_failed", session_key=session_key)
        return 0

    session_manager = getattr(ctx, "session_manager", None)
    set_session_epoch(session_manager, session_key, new_epoch)
    try:
        await emit_to_session_subscribers(
            ctx,
            session_key,
            "session.epoch_changed",
            {"key": session_key, "epoch": new_epoch},
            logger=active_logger,
        )
    except Exception:
        active_logger.warning(
            "sessions.reset.epoch_emit_failed",
            session_key=session_key,
            new_epoch=new_epoch,
        )
    return new_epoch
