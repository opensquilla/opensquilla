"""Channel-to-agent bridge: receive-dispatch-respond loop with helpers.

The main ``run_channel_dispatch`` function is a thin orchestrator (~25 lines)
that delegates to private helpers for each concern:

- ``_record_delivery_context`` — persist routing fields on session (Gap 1)
- ``_should_skip_unmentioned`` — mention gating for groups (Gap 2)
- ``_start_typing_keepalive`` — background typing indicator (Gap 3)
- ``_run_turn_with_streaming`` — streaming or batch reply (Gap 4)
- ``_emit_events`` — broadcast session events to WS subscribers (Gap 5)
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import weakref
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, cast

import structlog

from opensquilla.agents.scope import resolve_agent_model
from opensquilla.channels._util import ChannelAccessPolicy, evaluate_policy
from opensquilla.channels.stream_policy import resolve_channel_stream_policy
from opensquilla.channels.types import IncomingMessage, OutgoingMessage
from opensquilla.engine.start_turn import start_turn_via_runtime
from opensquilla.engine.types import ErrorEvent, RunHeartbeatEvent, TextDeltaEvent
from opensquilla.gateway import channel_message_io as _channel_message_io
from opensquilla.gateway.channel_artifacts import (
    artifact_delivery_key as _artifact_delivery_key,
)
from opensquilla.gateway.channel_artifacts import (
    artifact_event_payload as _artifact_event_payload,
)
from opensquilla.gateway.channel_artifacts import (
    artifact_fallback_lines as _artifact_fallback_lines,
)
from opensquilla.gateway.channel_artifacts import (
    can_deliver_channel_files as _can_deliver_channel_files,
)
from opensquilla.gateway.channel_artifacts import (
    deliver_artifacts_as_channel_files as _deliver_artifacts_as_channel_files,
)
from opensquilla.gateway.channel_artifacts import (
    split_assistant_artifact_content as _split_assistant_artifact_content,
)
from opensquilla.gateway.channel_artifacts import (
    strip_artifact_markers_from_channel_text as _strip_artifact_markers_from_channel_text,
)
from opensquilla.gateway.channel_artifacts import (
    strip_delivered_artifact_image_references as _strip_delivered_artifact_image_references,
)
from opensquilla.gateway.channel_inflight import (
    ChannelInFlightSet as _ChannelInFlightSet,
)
from opensquilla.gateway.channel_inflight import (
    compute_channel_cap as _compute_channel_cap,
)
from opensquilla.gateway.channel_replies import (
    DirectiveTagStreamSanitizer as _DirectiveTagStreamSanitizer,
)
from opensquilla.gateway.channel_replies import (
    sanitize_outgoing_message as _sanitize_outgoing_message,
)
from opensquilla.gateway.channel_replies import (
    terminal_payload_from_error_event as _terminal_payload_from_error_event,
)
from opensquilla.gateway.channel_replies import (
    terminal_payload_from_exception as _terminal_payload_from_exception,
)
from opensquilla.gateway.channel_replies import (
    terminal_reply_suffix as _terminal_reply_suffix,
)
from opensquilla.gateway.channel_streaming import (
    RuntimeChannelStreamRelay as _RuntimeChannelStreamRelay,
)
from opensquilla.session.terminal_reply import build_terminal_reply

if TYPE_CHECKING:
    from opensquilla.gateway.event_bridge import EventBridge

log = structlog.get_logger(__name__)

_append_channel_user_message = _channel_message_io.append_channel_user_message
_dump_attachment = _channel_message_io.dump_attachment
_ingest_channel_message_attachments = _channel_message_io.ingest_channel_message_attachments
_latest_assistant_text_after = _channel_message_io.latest_assistant_text_after
_materialize_channel_attachments = _channel_message_io.materialize_channel_attachments
_read_transcript_rows = _channel_message_io.read_transcript_rows
_transcript_watermark = _channel_message_io.transcript_watermark


def _emit_metric(name: str, value: int = 1, **labels: Any) -> None:
    """Emit a structured log line for a core metric (mirrors task_runtime._emit_metric).

    Format: event=<name> metric=<name> value=<int> [labels...]
    Used here for channel-adapter-level counters (queue_full_errors_total,
    turn_cancellations_total) that originate outside task_runtime.  Kept as a
    local copy to avoid a routing→task_runtime→channel_dispatch import cycle.
    """
    log.info(name, metric=name, value=value, **labels)


_DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
_DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 180.0


def _accepts_keyword_arg(callable_obj: Any, name: str) -> bool:
    try:
        params = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


@contextlib.asynccontextmanager
async def _maybe_lock(lock: asyncio.Lock | None) -> AsyncIterator[None]:
    """Yield under ``lock`` if provided; otherwise yield unlocked.

    Defensive helper for paths where ``turn_runner`` may be ``None`` (test
    shims). Mirrors the pattern in ``rpc_sessions._handle_sessions_send``.
    """
    if lock is None:
        yield
        return
    async with lock:
        yield


# ── Main dispatch loop (thin orchestrator) ───────────────────────────────


async def run_channel_dispatch(
    channel: Any,
    turn_runner: Any,
    session_manager: Any,
    session_key_builder: Callable[[Any], str],
    session_prefix: str,
    event_bridge: EventBridge | None = None,
    config: Any = None,
    task_runtime: Any = None,
    rpc_dispatcher: Any = None,
    channel_rpc_context_factory: Callable[[Any], Any] | None = None,
    debounce_coordinator: Any = None,
    debounce_window_s: float = 0.0,
    _in_flight: _ChannelInFlightSet | None = None,
) -> None:
    """Receive-dispatch-respond loop for a channel adapter.

    Runs forever, processing one message at a time.  Each concern is
    handled by a private helper to keep this function under ~25 lines.

    Reply delivery is fire-and-forget via ``asyncio.create_task``; the
    per-channel ``_ChannelInFlightSet`` (a SEPARATE second-layer semaphore
    from ``task_runtime._global_sem``) caps concurrent deliveries.
    """
    if _in_flight is None:
        cap = _compute_channel_cap(config)
        _in_flight = _ChannelInFlightSet(cap)
    while True:
        msg = await channel.receive()
        session_key = session_key_builder(msg)
        raw_content = msg.content
        from opensquilla.gateway.routing import build_channel_route_envelope

        route_envelope = build_channel_route_envelope(
            msg,
            session_key=session_key,
            session_prefix=session_prefix,
        )
        # fmt: off
        if getattr(channel, "supports_slash_commands", False) and rpc_dispatcher is not None and channel_rpc_context_factory is not None:  # noqa: E501
            command_reply = await _dispatch_channel_slash_command(
                route_envelope=route_envelope, msg=msg, session_manager=session_manager, session_key=session_key, session_prefix=session_prefix, rpc_dispatcher=rpc_dispatcher, context_factory=channel_rpc_context_factory  # noqa: E501
            )
            if command_reply is not None:
                emit = log.warning if command_reply.metadata.get("denied") else log.info
                if command_reply.metadata.get("denied"):
                    event = "channel.command_denied"
                elif command_reply.metadata.get("unsupported"):
                    event = "channel.command_unsupported"
                else:
                    event = "channel.command_intercepted"
                emit(event, command=command_reply.metadata.get("command"), method=command_reply.metadata.get("method"), session_key=session_key)  # noqa: E501
                await channel.send(command_reply)
                continue
        # fmt: on

        # fmt: off
        if task_runtime is not None and debounce_window_s > 0.0 and debounce_coordinator is not None:  # noqa: E501
            async def _on_debounce_fire(
                combined: Any,
                key: str = session_key,
                _ifl: _ChannelInFlightSet = cast(_ChannelInFlightSet, _in_flight),
            ) -> None:
                await _dispatch_combined_message_after_debounce(channel, combined, turn_runner, session_manager, key, session_prefix, task_runtime, config, event_bridge, _ifl)  # noqa: E501

            await debounce_coordinator.schedule(session_key, msg, window_s=debounce_window_s, on_fire=_on_debounce_fire)  # noqa: E501
            continue
        # fmt: on

        # Tier 2 (ADR 008): per-session keyed-async-queue. The same
        # ``turn_runner._get_session_lock(key)`` registry used by
        # ``rpc_sessions.{send,reset}`` gates channel delivery context and
        # transcript append. Remote attachment downloads intentionally run
        # outside this lock; adapter resolvers enforce bounded reads before
        # the locked persistence step.
        _get_lock = getattr(turn_runner, "_get_session_lock", None)
        session_lock = _get_lock(session_key) if callable(_get_lock) else None
        if session_lock is not None and session_lock.locked():
            log.info("channel_dispatch.session_lock_wait", session_key=session_key)

        async with _maybe_lock(session_lock):
            # Gap 1: Record delivery context + ensure session exists
            _session, _created = await _record_delivery_context(
                session_manager,
                session_key,
                msg,
                session_prefix,
                route_envelope=route_envelope,
            )

            # Gap 2: Skip unmentioned group messages
            if _should_skip_unmentioned(channel, msg, session_key):
                continue

        ingested = await _ingest_channel_message_attachments(channel=channel, msg=msg)

        async with _maybe_lock(session_lock):
            await _record_delivery_context(
                session_manager,
                session_key,
                msg,
                session_prefix,
                route_envelope=route_envelope,
            )

        status_reactor = _status_reactor(channel)
        await status_reactor.received(msg)

        if task_runtime is not None:
            from opensquilla.gateway.task_runtime import TaskQueueFullError

            # Cap check BEFORE enqueue/append: reject early so no transcript
            # entry is written and no runtime turn is started when the channel
            # adapter is already at capacity (accept-then-drop fix).
            if _in_flight.full():
                _emit_metric(
                    "queue_full_errors_total",
                    value=1,
                    session_key=session_key,
                )
                log.warning(
                    "channel_dispatch.inflight_cap_reached",
                    session_key=session_key,
                    cap=_in_flight.cap,
                )
                await channel.send(
                    OutgoingMessage(
                        content="Server busy, please retry",
                        reply_to=route_envelope.thread_id or route_envelope.channel_id,
                    )
                )
                await status_reactor.completed(msg)
                continue

            transcript_watermark = await _transcript_watermark(session_manager, session_key)
            stream_relay = _RuntimeChannelStreamRelay.maybe_start(
                channel,
                msg,
                task_runtime,
                config,
            )
            # Ghost-turn fix: enqueue BEFORE appending to transcript.
            # If enqueue raises TaskQueueFullError the user message is never
            # written, so no orphaned "ghost" turn is left in the transcript.
            # Both enqueue and append run inside the per-session lock so that
            # concurrent senders cannot interleave between the two steps.
            try:
                async with _maybe_lock(session_lock):
                    handle = await start_turn_via_runtime(
                        task_runtime,
                        route_envelope,
                        msg.content,
                        attachments=ingested.attachments,
                        mode="followup",
                        run_kind="channel_turn",
                        semantic_message=raw_content,
                        stream_event_sink=stream_relay.emit if stream_relay is not None else None,
                    )
                    _persisted, persisted_content = await _append_channel_user_message(
                        session_manager=session_manager,
                        session_key=session_key,
                        text=ingested.text,
                        attachments=ingested.attachments,
                        config=config,
                    )
                    msg.content = persisted_content
            except Exception as exc:
                if stream_relay is not None:
                    await stream_relay.close()

                if not isinstance(exc, TaskQueueFullError):
                    raise
                await status_reactor.failed(msg)
                await channel.send(
                    OutgoingMessage(
                        content=(
                            "The session task queue is full. "
                            f"Try again after queued work completes. ({exc})"
                        ),
                        reply_to=route_envelope.thread_id or route_envelope.channel_id,
                    )
                )
            else:
                await status_reactor.running(msg)

                typing_task = _start_typing_keepalive(channel)

                async def _reply_task_body(
                    _channel: Any = channel,
                    _task_runtime: Any = task_runtime,
                    _session_manager: Any = session_manager,
                    _session_key: str = session_key,
                    _task_id: str = handle.task_id,
                    _route_envelope: Any = route_envelope,
                    _inbound: Any = msg,
                    _transcript_watermark: int = transcript_watermark,
                    _stream_relay: Any = stream_relay,
                    _typing_task: Any = typing_task,
                    _event_bridge: Any = event_bridge,
                    _status_reactor: Any = status_reactor,
                ) -> None:
                    try:
                        await _deliver_runtime_channel_reply(
                            channel=_channel,
                            task_runtime=_task_runtime,
                            session_manager=_session_manager,
                            session_key=_session_key,
                            task_id=_task_id,
                            route_envelope=_route_envelope,
                            inbound=_inbound,
                            transcript_watermark=_transcript_watermark,
                            config=config,
                            stream_relay=_stream_relay,
                        )
                    finally:
                        if _typing_task is not None:
                            _typing_task.cancel()
                        if _event_bridge is not None:
                            await _emit_events(
                                _event_bridge,
                                _session_key,
                                "turn_complete",
                            )
                        await _status_reactor.completed(_inbound)

                reply_task = asyncio.create_task(
                    _reply_task_body(),
                    name=f"channel_reply:{session_key}",
                )
                _in_flight.add(reply_task)

                def _reply_done(t: asyncio.Task[Any], _sk: str = session_key) -> None:
                    _in_flight.discard(t)
                    exc = t.exception() if not t.cancelled() else None
                    if exc is not None:
                        log.error(
                            "channel_dispatch.reply_task_error",
                            session_key=_sk,
                            error_type=type(exc).__name__,
                            error=str(exc),
                            exc_info=exc,
                        )
                        _emit_metric(
                            "turn_cancellations_total",
                            value=1,
                            reason="reply_task_error",
                            session_key=_sk,
                        )

                reply_task.add_done_callback(_reply_done)
            continue

        # Gap 3: Start typing indicator (background task)
        typing_task = _start_typing_keepalive(channel)
        try:
            # Gap 4: Run agent turn with streaming (or batch fallback)
            await _run_turn_with_streaming(
                channel,
                turn_runner,
                msg,
                session_key,
                event_bridge,
                semantic_message=raw_content,
                config=config,
                route_envelope=route_envelope,
                attachments=ingested.attachments,
            )
        finally:
            if typing_task is not None:
                typing_task.cancel()

        # Gap 5: Emit turn-complete event
        if event_bridge is not None:
            await _emit_events(
                event_bridge,
                session_key,
                "turn_complete",
            )


def _slash_command_head(content: str) -> str | None:
    stripped = content.strip()
    if not stripped or not stripped.startswith("/") or stripped in {"/", "//"}:
        return None
    if stripped.startswith("//"):
        return None
    return stripped.split(maxsplit=1)[0]


async def _dispatch_channel_slash_command(
    *,
    route_envelope: Any,
    msg: IncomingMessage,
    session_manager: Any,
    session_key: str,
    session_prefix: str,
    rpc_dispatcher: Any,
    context_factory: Callable[[Any], Any],
) -> OutgoingMessage | None:
    from opensquilla.channels.command_registry import DEFAULT_COMMAND_REGISTRY

    match = DEFAULT_COMMAND_REGISTRY.match(route_envelope, msg.content)
    if match is None:
        head = _slash_command_head(msg.content)
        if head is None:
            return None
        return OutgoingMessage(
            content=f"Unsupported command: {head}. Try /help.",
            reply_to=route_envelope.thread_id or route_envelope.channel_id,
            metadata={"command": head[1:].lower(), "method": None, "unsupported": True},
        )

    name, method, _params_factory = match
    if name == "new" and method == "sessions.reset":
        return await _dispatch_channel_new_command(
            route_envelope=route_envelope,
            msg=msg,
            session_manager=session_manager,
            session_key=session_key,
            session_prefix=session_prefix,
            rpc_dispatcher=rpc_dispatcher,
            context_factory=context_factory,
        )

    return await DEFAULT_COMMAND_REGISTRY.dispatch(
        envelope=route_envelope,
        message_content=msg.content,
        rpc_dispatcher=rpc_dispatcher,
        context_factory=context_factory,
    )


async def _dispatch_channel_new_command(
    *,
    route_envelope: Any,
    msg: IncomingMessage,
    session_manager: Any,
    session_key: str,
    session_prefix: str,
    rpc_dispatcher: Any,
    context_factory: Callable[[Any], Any],
) -> OutgoingMessage:
    from opensquilla.channels.command_registry import DEFAULT_COMMAND_REGISTRY
    from opensquilla.gateway.scopes import WRITE_SCOPE, authorize_call

    ctx = context_factory(route_envelope)
    principal = getattr(ctx, "principal", None)
    allowed, missing = authorize_call(
        "sessions.reset",
        WRITE_SCOPE,
        getattr(principal, "role", ""),
        getattr(principal, "scopes", frozenset()),
    )
    if not allowed:
        detail = f": missing {missing}" if missing else ""
        return OutgoingMessage(
            content=(
                "/new denied: Insufficient scope for method: "
                f"sessions.reset{detail}"
            ),
            reply_to=route_envelope.thread_id or route_envelope.channel_id,
            metadata={"command": "new", "method": "sessions.reset", "denied": True},
        )

    await _record_delivery_context(
        session_manager,
        session_key,
        msg,
        session_prefix,
        route_envelope=route_envelope,
    )
    reply = await DEFAULT_COMMAND_REGISTRY.dispatch(
        envelope=route_envelope,
        message_content=msg.content,
        rpc_dispatcher=rpc_dispatcher,
        context_factory=lambda _envelope: ctx,
    )
    if reply is None:
        return OutgoingMessage(
            content="/new failed: command unavailable",
            reply_to=route_envelope.thread_id or route_envelope.channel_id,
            metadata={"command": "new", "method": "sessions.reset", "denied": False},
        )
    return reply


# fmt: off
async def _dispatch_combined_message_after_debounce(channel: Any, combined: Any, turn_runner: Any, session_manager: Any, session_key: str, session_prefix: str, task_runtime: Any, config: Any = None, event_bridge: EventBridge | None = None, _in_flight: _ChannelInFlightSet | None = None) -> None:  # noqa: E501
    from opensquilla.gateway.routing import build_channel_route_envelope

    msg = combined.message
    route_envelope = build_channel_route_envelope(msg, session_key=session_key, session_prefix=session_prefix)  # noqa: E501
    _get_lock = getattr(turn_runner, "_get_session_lock", None)
    session_lock = _get_lock(session_key) if callable(_get_lock) else None
    async with _maybe_lock(session_lock):
        await _record_delivery_context(session_manager, session_key, msg, session_prefix, route_envelope=route_envelope)  # noqa: E501

    ingested = await _ingest_channel_message_attachments(channel=channel, msg=msg)

    async with _maybe_lock(session_lock):
        await _record_delivery_context(session_manager, session_key, msg, session_prefix, route_envelope=route_envelope)  # noqa: E501

    status_reactor = _status_reactor(channel)
    await status_reactor.received(msg)
    raw_content = getattr(combined, "raw_content", None) or msg.content
    from opensquilla.gateway.task_runtime import TaskQueueFullError

    # Cap check BEFORE enqueue/append: reject early so no transcript entry is
    # written and no runtime turn is started (accept-then-drop fix).
    # try_acquire atomically checks + reserves a slot so that two concurrent
    # debounce callbacks racing through this path cannot both pass the guard.
    _reservation_token = object()
    if _in_flight is not None:
        if not _in_flight.try_acquire(_reservation_token):
            _emit_metric(
                "queue_full_errors_total",
                value=1,
                session_key=session_key,
            )
            log.warning(
                "channel_dispatch.inflight_cap_reached",
                session_key=session_key,
                cap=_in_flight.cap,
            )
            await channel.send(
                OutgoingMessage(
                    content="Server busy, please retry",
                    reply_to=route_envelope.thread_id or route_envelope.channel_id,
                )
            )
            await status_reactor.completed(msg)
            return
    else:
        _reservation_token = None  # type: ignore[assignment]

    transcript_watermark = await _transcript_watermark(session_manager, session_key)
    stream_relay = _RuntimeChannelStreamRelay.maybe_start(channel, msg, task_runtime, config)
    # Ghost-turn fix: enqueue BEFORE appending to transcript (same as
    # run_channel_dispatch). On TaskQueueFullError, transcript is not written.
    # Reservation is released in the finally block below regardless of outcome.
    try:
        async with _maybe_lock(session_lock):
            handle = await start_turn_via_runtime(task_runtime, route_envelope, msg.content, attachments=ingested.attachments, mode="followup", run_kind="channel_turn", semantic_message=raw_content, stream_event_sink=stream_relay.emit if stream_relay is not None else None)  # noqa: E501
            _persisted, persisted_content = await _append_channel_user_message(
                session_manager=session_manager,
                session_key=session_key,
                text=ingested.text,
                attachments=ingested.attachments,
                config=config,
            )
            msg.content = persisted_content
    except Exception as exc:
        if _in_flight is not None and _reservation_token is not None:
            _in_flight.release(_reservation_token)
        if stream_relay is not None:
            await stream_relay.close()

        if isinstance(exc, TaskQueueFullError):
            await status_reactor.failed(msg)
            log.warning("channel_dispatch.debounce_enqueue_failed", session_key=session_key, reason="queue_full", coalesced_count=combined.coalesced_count)  # noqa: E501
            await channel.send(OutgoingMessage(content="Your messages couldn't be processed because the queue is full. Please retry.", reply_to=route_envelope.thread_id or route_envelope.channel_id))  # noqa: E501
            return
        log.exception("channel_dispatch.debounce_enqueue_failed", session_key=session_key, reason="unexpected")  # noqa: E501
        await status_reactor.failed(msg)
        return

    # Enqueue succeeded — release the placeholder reservation now that the real
    # reply delivery will proceed (it doesn't use _in_flight in this path).
    if _in_flight is not None and _reservation_token is not None:
        _in_flight.release(_reservation_token)

    await status_reactor.running(msg)
    typing_task = _start_typing_keepalive(channel)
    try:
        await _deliver_runtime_channel_reply(channel=channel, task_runtime=task_runtime, session_manager=session_manager, session_key=session_key, task_id=handle.task_id, route_envelope=route_envelope, inbound=msg, transcript_watermark=transcript_watermark, config=config, stream_relay=stream_relay)  # noqa: E501
    finally:
        if typing_task is not None:
            typing_task.cancel()
    if event_bridge is not None:
        await _emit_events(event_bridge, session_key, "turn_complete")
    await status_reactor.completed(msg)
# fmt: on


# ── Gap 1: Delivery context ─────────────────────────────────────────────


async def _record_delivery_context(
    session_manager: Any,
    session_key: str,
    msg: IncomingMessage,
    session_prefix: str,
    route_envelope: Any = None,
) -> tuple[Any, bool]:
    """Ensure session exists and record delivery routing fields.

    On first message (created=True), fields are set at creation time.
    On subsequent messages, fields are updated via session_manager.update().
    Returns (session, created).
    """
    from opensquilla.gateway.routing import (
        build_channel_route_envelope,
        delivery_fields_from_envelope,
    )

    envelope = route_envelope or build_channel_route_envelope(
        msg,
        session_key=session_key,
        session_prefix=session_prefix,
    )
    delivery_fields = delivery_fields_from_envelope(envelope)

    from opensquilla.session.keys import build_main_key, parse_agent_id

    agent_id = parse_agent_id(session_key)
    main_session_key = build_main_key(agent_id)

    session, created = await session_manager.get_or_create(
        session_key,
        agent_id=agent_id,
        **delivery_fields,
    )

    if not created:
        await session_manager.update(session_key, **delivery_fields)

    if main_session_key != session_key:
        _main_session, main_created = await session_manager.get_or_create(
            main_session_key,
            agent_id=agent_id,
            **delivery_fields,
        )
        if not main_created:
            await session_manager.update(main_session_key, **delivery_fields)

    return session, created


async def resolve_delivery_target(
    session_manager: Any,
    session_key: str,
) -> dict[str, Any] | None:
    """Read delivery routing from a session for outbound use (e.g. cron).

    Returns ``{"channel": ..., "to": ..., "thread_id": ...}`` or None
    if the session has no delivery context.
    """
    try:
        node = await session_manager.resume(session_key)
    except KeyError:
        return None

    if not node.last_channel:
        return None

    return {
        "channel": node.last_channel,
        "to": node.last_to,
        "account_id": node.last_account_id,
        "thread_id": node.last_thread_id,
        "delivery_context": node.delivery_context,
    }


# ── Gap 2: Mention gating ────────────────────────────────────────────────


_MENTION_GATE_WARNED: dict[int, weakref.ReferenceType[Any] | None] = {}


def _warn_missing_mention_hook(channel: Any) -> None:
    """Emit one warning per channel instance for adapters lacking the hook."""
    key = id(channel)
    existing = _MENTION_GATE_WARNED.get(key)
    if existing is None and key in _MENTION_GATE_WARNED:
        return
    if existing is not None:
        existing_channel = existing()
        if existing_channel is channel:
            return
        if existing_channel is None:
            _MENTION_GATE_WARNED.pop(key, None)

    def _forget_warned_channel(_ref: weakref.ReferenceType[Any], key: int = key) -> None:
        _MENTION_GATE_WARNED.pop(key, None)

    try:
        _MENTION_GATE_WARNED[key] = weakref.ref(channel, _forget_warned_channel)
    except TypeError:
        _MENTION_GATE_WARNED[key] = None
    log.warning(
        "channel.mention_gate_default_deny",
        channel_type=type(channel).__name__,
    )


def _should_skip_unmentioned(
    channel: Any,
    msg: IncomingMessage,
    session_key: str,
) -> bool:
    """Return True when channel policy says to skip this inbound message.

    Adapters that declare ``ChannelAccessPolicy`` can choose closed groups,
    open groups, or mention-only groups. Mention-only groups still fail closed
    if the adapter forgot to implement ``is_group_mentioned``.
    """
    from opensquilla.session.keys import derive_chat_type

    is_group = derive_chat_type(session_key) == "group"
    policy = getattr(channel, "policy", None)
    if isinstance(policy, ChannelAccessPolicy):
        if not is_group:
            decision = evaluate_policy(
                policy,
                is_group=False,
                mentioned=False,
                sender_id=msg.sender_id,
            )
            return not decision.admit
        if not policy.group_allowed:
            decision = evaluate_policy(
                policy,
                is_group=True,
                mentioned=False,
                sender_id=msg.sender_id,
            )
            return not decision.admit
        if not policy.mention_required_in_group:
            decision = evaluate_policy(
                policy,
                is_group=True,
                mentioned=True,
                sender_id=msg.sender_id,
            )
            return not decision.admit

    if not is_group:
        return False  # DMs always processed for legacy adapters.

    hook = getattr(channel, "is_group_mentioned", None)
    if not callable(hook):
        _warn_missing_mention_hook(channel)
        return True  # fail-closed: missing mention hook on a group channel

    mentioned = bool(hook(msg))
    if isinstance(policy, ChannelAccessPolicy):
        decision = evaluate_policy(
            policy,
            is_group=True,
            mentioned=mentioned,
            sender_id=msg.sender_id,
        )
        return not decision.admit
    return not mentioned


# ── Gap 3: Typing indicator ──────────────────────────────────────────────


def _start_typing_keepalive(channel: Any, interval: float = 8.0) -> asyncio.Task | None:
    """Start a background task that re-sends typing every ``interval`` seconds.

    Uses ``asyncio.create_task`` so typing continues even during long tool calls
    where no events are yielded (a timestamp-in-loop approach would fail here).

    Returns None if the adapter has no ``send_typing`` method (e.g. Feishu, Terminal).
    The caller MUST cancel the returned task in a ``finally`` block.
    """
    if not resolve_channel_stream_policy(channel).typing_keepalive:
        return None
    send_typing = getattr(channel, "send_typing", None)
    if not callable(send_typing):
        return None

    async def _keepalive() -> None:
        while True:
            try:
                await send_typing()
            except Exception:
                pass  # typing is best-effort, never crash the loop
            await asyncio.sleep(interval)

    return asyncio.create_task(_keepalive())


# ── Gap 4: Streaming / batch turn execution ──────────────────────────────


def _optional_positive_config_float(config: Any, attr: str, default: float) -> float | None:
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


def _wrap_channel_turn_stream(stream: Any, config: Any) -> Any:
    from opensquilla.runtime.stream_wrappers import wrap_stream

    return wrap_stream(
        stream,
        idle_timeout=_optional_positive_config_float(
            config,
            "agent_stream_idle_timeout_seconds",
            _DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
        ),
        heartbeat_interval=_optional_positive_config_float(
            config,
            "agent_stream_heartbeat_interval_seconds",
            _DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS,
        ),
        heartbeat_phase="channel",
        heartbeat_message="Still working",
    )


async def _emit_run_heartbeat(
    event_bridge: EventBridge | None,
    session_key: str,
    event: RunHeartbeatEvent,
) -> None:
    if event_bridge is None:
        return
    await event_bridge.emit(
        session_key,
        "session.event.run_heartbeat",
        {
            "phase": event.phase,
            "elapsed_ms": event.elapsed_ms,
            "idle_ms": event.idle_ms,
            "message": event.message,
        },
    )


async def _run_turn_with_streaming(
    channel: Any,
    turn_runner: Any,
    msg: IncomingMessage,
    session_key: str,
    event_bridge: EventBridge | None = None,
    semantic_message: str | None = None,
    config: Any = None,
    route_envelope: Any = None,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Run the agent turn, sending reply via streaming or batch.

    If the adapter has ``send_streaming``, text deltas are fed through
    an async iterator that the adapter consumes (post + throttled edits).
    Otherwise falls back to batch mode (accumulate all text, send once).

    Error recovery: if an ErrorEvent occurs mid-stream, the existing
    message is edited to append "(Error: ...)" rather than leaving partial
    text visible.  Pre-stream errors send a standalone error message.
    """
    from opensquilla.gateway.routing import (
        build_channel_route_envelope,
        tool_context_from_route_envelope,
    )
    from opensquilla.session.keys import parse_agent_id

    agent_id = parse_agent_id(session_key)
    envelope = route_envelope or build_channel_route_envelope(
        msg,
        session_key=session_key,
        session_prefix=getattr(channel, "channel_id", None) or "unknown",
        agent_id=agent_id,
    )
    tool_ctx = tool_context_from_route_envelope(
        envelope,
        config,
    )
    use_streaming = resolve_channel_stream_policy(channel).relay_stream

    if use_streaming:
        await _run_turn_streaming_path(
            channel,
            turn_runner,
            msg,
            session_key,
            tool_ctx,
            event_bridge,
            semantic_message,
            config,
            attachments,
        )
    else:
        await _run_turn_batch_path(
            channel,
            turn_runner,
            msg,
            session_key,
            tool_ctx,
            event_bridge,
            semantic_message,
            config,
            attachments,
        )


def _build_reply_message(channel: Any, content: str, msg: IncomingMessage) -> OutgoingMessage:
    builder = getattr(channel, "build_reply_message", None)
    if callable(builder):
        reply = builder(content, msg)
        if isinstance(reply, OutgoingMessage):
            return _sanitize_outgoing_message(reply)
    return _sanitize_outgoing_message(OutgoingMessage(content=content))


def _status_reactor(channel: Any) -> Any:
    from opensquilla.channels._reactions import NULL_STATUS_REACTOR

    return getattr(channel, "status_reactor", NULL_STATUS_REACTOR)


def _streaming_reply_kwargs(channel: Any, msg: IncomingMessage) -> dict[str, Any]:
    builder = getattr(channel, "streaming_reply_kwargs", None)
    if not callable(builder):
        return {}
    return dict(builder(msg))


def _text_delta_from_event(event: Any) -> str:
    if isinstance(event, TextDeltaEvent):
        return event.text
    kind = getattr(event, "kind", None)
    if kind == "text_delta":
        text = getattr(event, "text", "")
        return text if isinstance(text, str) else ""
    if isinstance(event, dict) and event.get("kind") == "text_delta":
        text = event.get("text", "")
        return text if isinstance(text, str) else ""
    return ""


def _status_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _build_runtime_reply_message(
    channel: Any,
    content: str,
    inbound: IncomingMessage,
    route_envelope: Any,
) -> OutgoingMessage:
    builder = getattr(channel, "build_reply_message", None)
    if callable(builder):
        reply = builder(content, inbound)
        if isinstance(reply, OutgoingMessage):
            return _sanitize_outgoing_message(reply)

    target = getattr(route_envelope, "reply_target", None)
    if target is not None and getattr(target, "kind", None) == "channel":
        channel_name = getattr(target, "channel_name", None)
        channel_id = getattr(target, "to", None)
        thread_id = getattr(target, "thread_id", None)
        if channel_name == "slack":
            metadata = {"channel": channel_id} if channel_id else {}
            if thread_id:
                return _sanitize_outgoing_message(
                    OutgoingMessage(content=content, reply_to=thread_id, metadata=metadata)
                )
            if channel_id:
                return _sanitize_outgoing_message(
                    OutgoingMessage(
                        content=content,
                        reply_to=None,
                        metadata={**metadata, "thread_ts": None},
                    )
                )
        return _sanitize_outgoing_message(
            OutgoingMessage(content=content, reply_to=thread_id or channel_id)
        )

    return _build_reply_message(channel, content, inbound)


async def _deliver_runtime_channel_reply(
    *,
    channel: Any,
    task_runtime: Any,
    session_manager: Any,
    session_key: str,
    task_id: str,
    route_envelope: Any,
    inbound: IncomingMessage,
    transcript_watermark: int,
    config: Any = None,
    stream_relay: _RuntimeChannelStreamRelay | None = None,
) -> None:
    """Await a task_runtime result and send the channel reply.

    ``stream_relay.close()`` is always called in the ``finally`` block so that
    the streaming task is properly terminated even when this coroutine is
    cancelled or raises an unexpected exception (pitfall d).
    """
    wait = getattr(task_runtime, "wait", None)
    if not callable(wait):
        raise RuntimeError("task runtime does not support wait()")

    record = None
    wait_exc: Exception | None = None
    try:
        record = await wait(task_id)
    except Exception as exc:
        wait_exc = exc
        log.warning("channel_dispatch.runtime_wait_failed", session_key=session_key, exc_info=True)
    finally:
        if stream_relay is not None:
            await stream_relay.close()

    if wait_exc is not None:
        await channel.send(
            _build_runtime_reply_message(
                channel,
                build_terminal_reply(_terminal_payload_from_exception(wait_exc)),
                inbound,
                route_envelope,
            )
        )
        return

    status = _status_value(getattr(record, "status", None))
    if status == "succeeded":
        if (
            stream_relay is not None
            and stream_relay.text_emitted
            and stream_relay.stream_error is None
        ):
            return
        content = await _latest_assistant_text_after(
            session_manager,
            session_key,
            transcript_watermark,
        )
    else:
        content = build_terminal_reply(record)
        if (
            stream_relay is not None
            and stream_relay.text_emitted
            and stream_relay.stream_error is None
        ):
            content = _terminal_reply_suffix(content)

    if content:
        content, artifacts = _split_assistant_artifact_content(content)
        if stream_relay is not None and stream_relay.delivered_artifact_keys:
            artifacts = [
                artifact
                for artifact in artifacts
                if _artifact_delivery_key(artifact) not in stream_relay.delivered_artifact_keys
            ]
        content = _strip_artifact_markers_from_channel_text(content)
        content = _strip_delivered_artifact_image_references(content, artifacts)
        if _can_deliver_channel_files(channel):
            if content:
                await channel.send(
                    _build_runtime_reply_message(
                        channel,
                        content,
                        inbound,
                        route_envelope,
                    )
                )
            undelivered = await _deliver_artifacts_as_channel_files(
                channel,
                inbound,
                artifacts,
                config,
            )
            fallback_lines = _artifact_fallback_lines(undelivered)
            if fallback_lines:
                await channel.send(
                    _build_runtime_reply_message(
                        channel,
                        "\n".join(fallback_lines),
                        inbound,
                        route_envelope,
                    )
                )
        else:
            fallback_lines = _artifact_fallback_lines(artifacts)
            if fallback_lines:
                content = "\n\n".join(part for part in (content, "\n".join(fallback_lines)) if part)
            if content:
                await channel.send(
                    _build_runtime_reply_message(
                        channel,
                        content,
                        inbound,
                        route_envelope,
                    )
                )


async def _run_turn_batch_path(
    channel: Any,
    turn_runner: Any,
    msg: IncomingMessage,
    session_key: str,
    tool_ctx: Any,
    event_bridge: EventBridge | None,
    semantic_message: str | None,
    config: Any,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Batch mode: accumulate all text, send once at the end."""
    text_parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    error_occurred = False

    run_kwargs: dict[str, Any] = {
        "tool_context": tool_ctx,
        "agent_id": tool_ctx.agent_id,
    }
    model = resolve_agent_model(tool_ctx.agent_id, config)
    if model is not None and _accepts_keyword_arg(turn_runner.run, "model"):
        run_kwargs["model"] = model
    if _accepts_keyword_arg(turn_runner.run, "semantic_message"):
        run_kwargs["semantic_message"] = semantic_message
    if attachments and _accepts_keyword_arg(turn_runner.run, "attachments"):
        run_kwargs["attachments"] = attachments
    try:
        stream = turn_runner.run(
            msg.content,
            session_key,
            **run_kwargs,
        )
        async for event in _wrap_channel_turn_stream(stream, config):
            if isinstance(event, TextDeltaEvent):
                text_parts.append(event.text)
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.text_delta",
                        {"text": event.text},
                    )
            elif artifact := _artifact_event_payload(event):
                artifacts.append(artifact)
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.artifact",
                        artifact,
                    )
            elif isinstance(event, RunHeartbeatEvent):
                await _emit_run_heartbeat(event_bridge, session_key, event)
            elif isinstance(event, ErrorEvent):
                log.error(
                    "channel_dispatch.agent_error",
                    session_key=session_key,
                    code=event.code,
                    message=event.message,
                )
                await channel.send(
                    _build_reply_message(
                        channel,
                        build_terminal_reply(_terminal_payload_from_error_event(event)),
                        msg,
                    )
                )
                text_parts.clear()
                error_occurred = True
                break
    except TimeoutError as exc:
        log.error("channel_dispatch.agent_stream_timeout", session_key=session_key)
        await channel.send(
            _build_reply_message(
                channel,
                build_terminal_reply(_terminal_payload_from_exception(exc)),
                msg,
            )
        )
        text_parts.clear()
        error_occurred = True

    if not error_occurred:
        content = "".join(text_parts)
        content = _strip_artifact_markers_from_channel_text(content)
        content = _strip_delivered_artifact_image_references(content, artifacts)
        if _can_deliver_channel_files(channel):
            if content:
                await channel.send(_build_reply_message(channel, content, msg))
            undelivered = await _deliver_artifacts_as_channel_files(channel, msg, artifacts, config)
            artifact_lines = _artifact_fallback_lines(undelivered)
            if artifact_lines:
                await channel.send(_build_reply_message(channel, "\n".join(artifact_lines), msg))
        else:
            artifact_lines = _artifact_fallback_lines(artifacts)
            if artifact_lines:
                content = "\n\n".join(part for part in (content, "\n".join(artifact_lines)) if part)
            if content:
                await channel.send(_build_reply_message(channel, content, msg))


async def _run_turn_streaming_path(
    channel: Any,
    turn_runner: Any,
    msg: IncomingMessage,
    session_key: str,
    tool_ctx: Any,
    event_bridge: EventBridge | None,
    semantic_message: str | None,
    config: Any,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Streaming mode: feed text deltas through an async queue to send_streaming.

    Uses a queue + consumer task pattern so the turn runner and the
    channel streamer run concurrently.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    text_emitted = False
    stream_error: str | None = None
    artifacts: list[dict[str, Any]] = []

    async def _chunk_iter() -> AsyncIterator[str]:
        """Async iterator that yields text chunks from the queue."""
        sanitizer = _DirectiveTagStreamSanitizer()
        while True:
            chunk = await queue.get()
            if chunk is None:
                tail = sanitizer.flush()
                if tail:
                    yield tail
                return
            cleaned = sanitizer.clean(chunk)
            if cleaned:
                yield cleaned

    # Start the streaming consumer as a background task
    stream_task = asyncio.create_task(
        channel.send_streaming(
            _chunk_iter(),
            **_streaming_reply_kwargs(channel, msg),
        ),
    )

    try:
        run_kwargs: dict[str, Any] = {
            "tool_context": tool_ctx,
            "agent_id": tool_ctx.agent_id,
        }
        model = resolve_agent_model(tool_ctx.agent_id, config)
        if model is not None and _accepts_keyword_arg(turn_runner.run, "model"):
            run_kwargs["model"] = model
        if _accepts_keyword_arg(turn_runner.run, "semantic_message"):
            run_kwargs["semantic_message"] = semantic_message
        if attachments and _accepts_keyword_arg(turn_runner.run, "attachments"):
            run_kwargs["attachments"] = attachments
        stream = turn_runner.run(
            msg.content,
            session_key,
            **run_kwargs,
        )
        async for event in _wrap_channel_turn_stream(stream, config):
            if isinstance(event, TextDeltaEvent):
                cleaned = _strip_artifact_markers_from_channel_text(event.text)
                if cleaned:
                    text_emitted = True
                    await queue.put(cleaned)
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.text_delta",
                        {"text": event.text},
                    )
            elif artifact := _artifact_event_payload(event):
                artifacts.append(artifact)
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.artifact",
                        artifact,
                    )
            elif isinstance(event, RunHeartbeatEvent):
                await _emit_run_heartbeat(event_bridge, session_key, event)
            elif isinstance(event, ErrorEvent):
                log.error(
                    "channel_dispatch.agent_error",
                    session_key=session_key,
                    code=event.code,
                    message=event.message,
                )
                stream_error = build_terminal_reply(_terminal_payload_from_error_event(event))
                break
    except TimeoutError as exc:
        log.error("channel_dispatch.agent_stream_timeout", session_key=session_key)
        stream_error = build_terminal_reply(_terminal_payload_from_exception(exc))
    finally:
        # Signal end-of-stream to the consumer
        await queue.put(None)
        # Wait for the streaming task to finish
        try:
            await asyncio.wait_for(stream_task, timeout=10.0)
        except (TimeoutError, Exception):
            stream_task.cancel()

    # Error recovery
    if stream_error is not None:
        if text_emitted:
            # Mid-stream: edit the existing message to append error
            try:
                await channel.send(
                    _build_reply_message(channel, _terminal_reply_suffix(stream_error), msg),
                )
            except Exception:
                pass  # best-effort error append
        else:
            # Pre-stream: standalone error message
            await channel.send(
                _build_reply_message(channel, stream_error, msg),
            )
    elif artifacts:
        if _can_deliver_channel_files(channel):
            undelivered = await _deliver_artifacts_as_channel_files(channel, msg, artifacts, config)
        else:
            undelivered = artifacts
        fallback_lines = _artifact_fallback_lines(undelivered)
        if fallback_lines:
            await channel.send(
                _build_reply_message(channel, "\n".join(fallback_lines), msg),
            )


# ── Gap 5: Event emission ────────────────────────────────────────────────


async def _emit_events(
    event_bridge: EventBridge,
    session_key: str,
    reason: str,
) -> None:
    """Broadcast session events to WebSocket subscribers.

    Placeholder: emits ``sessions.changed`` with the given reason.
    A richer implementation will follow once the EventBridge is created.
    """
    await event_bridge.emit(
        session_key,
        "sessions.changed",
        {"key": session_key, "reason": reason},
    )
