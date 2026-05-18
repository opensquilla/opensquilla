"""Gateway-owned cron result delivery helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opensquilla.gateway.session_streams import SessionStreamRegistry, get_session_streams
from opensquilla.gateway.websocket import get_registry


def build_cron_result_payload(
    origin_session_key: str,
    text: str,
    entry: Any,
) -> dict[str, Any]:
    """Build the WS payload for a ``session.event.cron_result`` broadcast."""
    return {
        "sessionKey": origin_session_key,
        "message": {
            "role": "assistant",
            "text": text,
            "timestamp": getattr(entry, "created_at", None),
            "provenanceKind": getattr(entry, "provenance_kind", None),
            "provenanceSourceTool": getattr(entry, "provenance_source_tool", None),
            "provenanceSourceSessionKey": getattr(entry, "provenance_source_session_key", None),
        },
    }


def build_sessions_changed_payload(session_key: str, reason: str) -> dict[str, str]:
    """Build the WS payload for a ``sessions.changed`` broadcast."""
    return {"key": session_key, "reason": reason}


def make_cron_ws_emitter(
    *,
    subscription_manager: Any,
    connection_registry_getter: Callable[[], Any] = get_registry,
) -> Callable[[str, str, dict[str, Any]], Any]:
    """Create targeted cron topic fanout with per-connection error isolation."""

    async def _cron_ws_emitter(topic: str, event: str, payload: dict[str, Any]) -> int:
        if subscription_manager is None:
            return 0
        registry = connection_registry_getter()
        conn_ids = subscription_manager.get_topic_subscribers(topic)
        conn_ids |= subscription_manager.get_topic_subscribers("cron:*")
        sent = 0
        for conn_id in conn_ids:
            conn = registry.get(conn_id)
            if conn:
                try:
                    await conn.send_event(event, payload)
                    sent += 1
                except Exception:
                    pass
        return sent

    return _cron_ws_emitter


def make_session_forwarder(
    *,
    session_manager: Any,
    subscription_manager: Any,
    connection_registry_getter: Callable[[], Any] = get_registry,
    stream_registry: SessionStreamRegistry | None = None,
) -> Callable[..., Any]:
    """Create the origin-session cron-result forwarder used by scheduler delivery."""

    async def _session_forwarder(
        origin_session_key: str,
        text: str,
        provenance: dict[str, Any],
    ) -> None:
        if session_manager is None:
            return

        entry = await session_manager.append_message(
            origin_session_key,
            role="assistant",
            content=text,
            provenance=provenance,
        )

        if subscription_manager is None:
            return

        payload = build_cron_result_payload(origin_session_key, text, entry)
        registry = connection_registry_getter()
        streams = stream_registry or get_session_streams()
        stream_payload = streams.record(
            origin_session_key,
            "session.event.cron_result",
            payload,
        )
        for conn_id in subscription_manager.get_message_subscribers(origin_session_key):
            conn = registry.get(conn_id)
            if conn:
                try:
                    await conn.send_event("session.event.cron_result", stream_payload)
                except Exception:
                    pass

        sessions_changed_payload = build_sessions_changed_payload(
            origin_session_key, "cron_result"
        )
        for conn_id in (
            subscription_manager.get_message_subscribers(origin_session_key)
            | subscription_manager.get_session_subscribers()
        ):
            conn = registry.get(conn_id)
            if conn:
                try:
                    await conn.send_event("sessions.changed", sessions_changed_payload)
                except Exception:
                    pass

    return _session_forwarder


def build_cron_delivery_chain(
    *,
    channel_manager_ref: Callable[[], Any] | None,
    subscription_manager: Any,
    session_manager: Any,
) -> Any:
    """Build scheduler delivery with gateway-owned WS and session forwarding."""
    from opensquilla.scheduler.delivery import DeliveryChain

    return DeliveryChain(
        channel_manager_ref=channel_manager_ref,
        ws_emitter=make_cron_ws_emitter(subscription_manager=subscription_manager),
        session_forwarder=make_session_forwarder(
            session_manager=session_manager,
            subscription_manager=subscription_manager,
        ),
    )
