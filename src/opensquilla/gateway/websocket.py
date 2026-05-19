"""WebSocket connection handler: handshake, frame parsing, event loop."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import structlog
from starlette.websockets import WebSocket, WebSocketDisconnect

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.protocol import (
    PREAUTH_TIMEOUT_MS,
    PROTOCOL_VERSION,
    HelloOk,
    PolicyInfo,
    ServerInfo,
    SnapshotInfo,
    make_error_res,
)
from opensquilla.gateway.rpc import RpcContext, RpcDispatcher
from opensquilla.gateway.websocket_connection import (
    _LOSSY_EVENTS,
    _SENTINEL_STOP,
    ConnectionRegistry,
    WsConnection,
    _OutboundFrame,
)

log = structlog.get_logger(__name__)

__all__ = [
    "ConnectionRegistry",
    "SubscriptionManager",
    "WsConnection",
    "_LOSSY_EVENTS",
    "_OutboundFrame",
    "_SENTINEL_STOP",
    "get_registry",
    "handle_ws_connection",
]


class SubscriptionManager:
    """Track which connections are subscribed to session-level and message-level events."""

    def __init__(self) -> None:
        self._session_subs: set[str] = set()  # conn_ids subscribed to session lifecycle
        self._message_subs: dict[str, set[str]] = {}  # session_key -> {conn_id}
        self._topic_subs: dict[str, set[str]] = {}  # topic -> {conn_id}

    # -- session-level (sessions.subscribe / sessions.unsubscribe) --

    def subscribe_sessions(self, conn_id: str) -> None:
        self._session_subs.add(conn_id)

    def unsubscribe_sessions(self, conn_id: str) -> None:
        self._session_subs.discard(conn_id)

    def get_session_subscribers(self) -> set[str]:
        return set(self._session_subs)

    # -- message-level (sessions.messages.subscribe / unsubscribe) --

    def subscribe_messages(self, conn_id: str, session_key: str) -> None:
        self._message_subs.setdefault(session_key, set()).add(conn_id)

    def unsubscribe_messages(self, conn_id: str, session_key: str) -> None:
        if session_key in self._message_subs:
            self._message_subs[session_key].discard(conn_id)

    def get_message_subscribers(self, session_key: str) -> set[str]:
        return set(self._message_subs.get(session_key, set()))

    # -- topic-level (cron.subscribe / cron.unsubscribe) --

    def subscribe_topic(self, conn_id: str, topic: str) -> None:
        self._topic_subs.setdefault(topic, set()).add(conn_id)

    def unsubscribe_topic(self, conn_id: str, topic: str) -> None:
        if topic in self._topic_subs:
            self._topic_subs[topic].discard(conn_id)
            if not self._topic_subs[topic]:
                del self._topic_subs[topic]

    def get_topic_subscribers(self, topic: str) -> set[str]:
        return set(self._topic_subs.get(topic, set()))

    def remove_connection(self, conn_id: str) -> None:
        """Clean up all subscriptions for a disconnected connection."""
        self._session_subs.discard(conn_id)
        for subs in self._message_subs.values():
            subs.discard(conn_id)
        empty_topics = []
        for topic, subs in self._topic_subs.items():
            subs.discard(conn_id)
            if not subs:
                empty_topics.append(topic)
        for topic in empty_topics:
            del self._topic_subs[topic]


# Module-level registry shared across connections
_registry = ConnectionRegistry()


def get_registry() -> ConnectionRegistry:
    return _registry


async def handle_ws_connection(
    ws: WebSocket,
    config: GatewayConfig,
    dispatcher: RpcDispatcher,
    session_manager: Any = None,
    provider_selector: Any = None,
    tool_registry: Any = None,
    subscription_manager: Any = None,
    channel_manager: Any = None,
    usage_tracker: Any = None,
    skill_loader: Any = None,
    cron_scheduler: Any = None,
    turn_runner: Any = None,
    task_runtime: Any = None,
    flush_service: Any = None,
    heartbeat_service: Any = None,
    heartbeat_loop: Any = None,
    agent_registry: Any = None,
    diagnostics_state: Any = None,
    memory_managers: dict[str, Any] | None = None,
    memory_stores: dict[str, Any] | None = None,
    memory_retrievers: dict[str, Any] | None = None,
) -> None:
    """Main WebSocket connection handler."""
    conn_id = str(uuid.uuid4())
    conn = WsConnection(conn_id=conn_id, ws=ws)
    registry = get_registry()

    await ws.accept()
    log.info("ws.connected", conn_id=conn_id, remote=str(ws.client))

    # Step 1: Send connect.challenge
    nonce = str(uuid.uuid4())
    try:
        await conn.send_event("connect.challenge", {"nonce": nonce})
    except WebSocketDisconnect:
        return

    # Step 2: Pre-auth timeout — client must send connect request
    try:
        preauth_timeout = PREAUTH_TIMEOUT_MS / 1000
        raw = await asyncio.wait_for(ws.receive_text(), timeout=preauth_timeout)
    except TimeoutError:
        log.warning("ws.preauth_timeout", conn_id=conn_id)
        await conn.close()
        return
    except WebSocketDisconnect:
        return

    # Step 3: Parse the connect request
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await conn.send_res(
            make_error_res("handshake", "INVALID_REQUEST", "Invalid JSON in connect frame")
        )
        await conn.close()
        return

    if data.get("type") != "req" or data.get("method") != "connect":
        await conn.send_res(
            make_error_res(
                data.get("id", "handshake"),
                "INVALID_REQUEST",
                "First message must be connect request",
            )
        )
        await conn.close()
        return

    req_id = data.get("id", "handshake")
    params_raw = data.get("params", {}) or {}

    # Step 4: Resolve auth via server-side ScopeResolver
    from opensquilla.gateway.auth import resolve_auth

    auth_params = params_raw.get("auth", {}) or {}
    peer_ip = ws.client.host if ws.client is not None else None
    principal = resolve_auth(
        config,
        auth_params=auth_params,
        role_claim=params_raw.get("role", "operator"),
        peer_ip=peer_ip,
    )
    if principal is None:
        await conn.send_res(make_error_res(req_id, "UNAUTHORIZED", "Authentication failed"))
        await conn.close()
        return

    # Step 5: Negotiate protocol version
    min_proto = params_raw.get("minProtocol", 1)
    max_proto = params_raw.get("maxProtocol", PROTOCOL_VERSION)
    negotiated = min(max_proto, PROTOCOL_VERSION)
    if negotiated < min_proto:
        await conn.send_res(
            make_error_res(req_id, "INVALID_REQUEST", "Unsupported protocol version range")
        )
        await conn.close()
        return

    # Assign principal
    conn.principal = principal

    # Step 6: Send HelloOk
    hello = HelloOk(
        protocol=negotiated,
        server=ServerInfo(version=config.version, conn_id=conn_id),
        features=_build_features(dispatcher),
        snapshot=SnapshotInfo(
            uptime_ms=int(time.time() * 1000),
            config_path=config.config_path,
            state_dir=config.state_dir,
            auth_mode=config.auth.mode,
        ),
        policy=PolicyInfo(
            agent_stream_heartbeat_interval_ms=int(
                max(0.0, float(getattr(config, "agent_stream_heartbeat_interval_seconds", 15.0)))
                * 1000
            ),
            agent_stream_idle_timeout_ms=int(
                max(0.0, float(getattr(config, "agent_stream_idle_timeout_seconds", 180.0)))
                * 1000
            ),
            webui_stream_idle_grace_ms=int(
                max(0.0, float(getattr(config, "webui_stream_idle_grace_seconds", 210.0)))
                * 1000
            ),
            client_ws_keepalive_timeout_ms=int(
                max(0.0, float(getattr(config, "client_ws_keepalive_timeout_s", 120.0)))
                * 1000
            ),
        ),
    )
    await ws.send_text(hello.model_dump_json())

    registry.register(conn)
    # Boundary: pre-auth direct-send ends here. After registry.register(conn),
    # conn._writer_task owns all post-auth sends. send_event/send_res route
    # through conn._outbox; WS-frame seq is minted at dequeue inside the
    # writer loop (NOT at enqueue), so dropped lossy frames never consume a
    # seq number. See Principle 2 in plans/ws-writer-queue.md for rationale.
    # Kill switch (config.ws_writer_queue_enabled) is read here at registration
    # time only — affects new connections only; existing connections retain
    # their startup-time behavior.
    conn._start_writer(
        maxsize=config.ws_writer_queue_maxsize,
        enabled=config.ws_writer_queue_enabled,
    )
    log.info("ws.authenticated", conn_id=conn_id, role=conn.role)

    # Step 7: Main message loop
    tick_task = asyncio.create_task(_tick_loop(conn, hello.policy.tick_interval_ms))
    try:
        await _message_loop(
            conn,
            config,
            dispatcher,
            session_manager,
            provider_selector,
            tool_registry,
            subscription_manager,
            channel_manager,
            usage_tracker,
            skill_loader,
            cron_scheduler,
            turn_runner,
            task_runtime,
            flush_service,
            heartbeat_service,
            heartbeat_loop,
            agent_registry,
            diagnostics_state,
            memory_managers,
            memory_stores,
            memory_retrievers,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.error("ws.error", conn_id=conn_id, error=str(exc))
    finally:
        # Stop the writer FIRST, before tick_task.cancel() and before
        # registry.unregister. Otherwise an EventBridge.emit on another
        # coroutine could still hold a reference to this connection while
        # the writer task is mid-cancel, producing a "zombie writer"
        # scenario (Pre-mortem #2 in plans/ws-writer-queue.md §Step 5).
        await conn._stop_writer()
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        registry.unregister(conn_id)
        if subscription_manager is not None:
            subscription_manager.remove_connection(conn_id)
        log.info("ws.disconnected", conn_id=conn_id)


async def _tick_loop(conn: WsConnection, tick_interval_ms: int) -> None:
    interval_s = max(1.0, tick_interval_ms / 1000)
    while True:
        await asyncio.sleep(interval_s)
        try:
            await conn.send_event("tick", {"time_ms": int(time.time() * 1000)})
        except Exception:
            log.debug("ws.tick_failed", conn_id=conn.conn_id, exc_info=True)
            return


async def _message_loop(
    conn: WsConnection,
    config: GatewayConfig,
    dispatcher: RpcDispatcher,
    session_manager: Any,
    provider_selector: Any = None,
    tool_registry: Any = None,
    subscription_manager: Any = None,
    channel_manager: Any = None,
    usage_tracker: Any = None,
    skill_loader: Any = None,
    cron_scheduler: Any = None,
    turn_runner: Any = None,
    task_runtime: Any = None,
    flush_service: Any = None,
    heartbeat_service: Any = None,
    heartbeat_loop: Any = None,
    agent_registry: Any = None,
    diagnostics_state: Any = None,
    memory_managers: dict[str, Any] | None = None,
    memory_stores: dict[str, Any] | None = None,
    memory_retrievers: dict[str, Any] | None = None,
) -> None:
    ws = conn.ws
    keepalive_timeout = max(0.0, float(getattr(config, "client_ws_keepalive_timeout_s", 0.0)))
    while True:
        try:
            if keepalive_timeout > 0.0:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=keepalive_timeout)
            else:
                raw = await ws.receive_text()
        except WebSocketDisconnect:
            return
        except TimeoutError:
            log.warning(
                "gateway.client_ws_keepalive_timeout",
                conn_id=conn.conn_id,
                timeout_s=keepalive_timeout,
            )
            try:
                await ws.close(code=1011)
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await conn.send_res(make_error_res("", "INVALID_REQUEST", "Invalid JSON"))
            continue

        frame_type = data.get("type")

        if frame_type == "ping":
            await ws.send_text('{"type":"pong"}')
            continue

        if frame_type == "pong":
            continue

        if frame_type == "req":
            req_id = data.get("id", "")
            method = data.get("method", "")
            params = data.get("params")

            ctx = RpcContext(
                conn_id=conn.conn_id,
                principal=conn.principal,
                session_manager=session_manager,
                config=config,
                provider_selector=provider_selector,
                tool_registry=tool_registry,
                subscription_manager=subscription_manager,
                channel_manager=channel_manager,
                usage_tracker=usage_tracker,
                skill_loader=skill_loader,
                cron_scheduler=cron_scheduler,
                turn_runner=turn_runner,
                task_runtime=task_runtime,
                flush_service=flush_service,
                heartbeat_service=heartbeat_service,
                heartbeat_loop=heartbeat_loop,
                agent_registry=agent_registry,
                diagnostics_state=diagnostics_state,
                memory_managers=memory_managers or {},
                memory_stores=memory_stores or {},
                memory_retrievers=memory_retrievers or {},
            )
            res = await dispatcher.dispatch(req_id, method, params, ctx)
            await conn.send_res(res)
        else:
            await conn.send_res(
                make_error_res("", "INVALID_REQUEST", f"Unknown frame type: {frame_type}")
            )


def _build_features(dispatcher: RpcDispatcher) -> Any:
    from opensquilla.gateway.protocol import FeaturesInfo

    methods = dispatcher.list_methods()
    events = [
        "connect.challenge",
        "agent",
        "session.message",
        "sessions.changed",
        "presence",
        "tick",
        "shutdown",
        "health",
        "heartbeat",
        "cron",
    ]
    return FeaturesInfo(methods=methods, events=events)
