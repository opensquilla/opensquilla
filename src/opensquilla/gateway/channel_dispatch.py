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
import json
import re
import weakref
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, cast

import structlog

from opensquilla.agents.scope import resolve_agent_model
from opensquilla.artifacts import artifact_payload
from opensquilla.channels._util import ChannelAccessPolicy, evaluate_policy
from opensquilla.channels.artifact_delivery import (
    artifact_delivery_key as _artifact_delivery_key,
)
from opensquilla.channels.artifact_delivery import (
    artifact_fallback_lines as _artifact_fallback_lines,
)
from opensquilla.channels.artifact_delivery import (
    can_deliver_channel_files as _can_deliver_channel_files,
)
from opensquilla.channels.artifact_delivery import (
    deliver_artifacts_as_channel_files as _deliver_artifacts_as_channel_files,
)
from opensquilla.channels.artifact_delivery import (
    strip_artifact_markers_from_channel_text as _strip_artifact_markers_from_channel_text,
)
from opensquilla.channels.artifact_delivery import (
    strip_delivered_artifact_image_references as _strip_delivered_artifact_image_references,
)
from opensquilla.channels.contract import channel_capability_profile
from opensquilla.channels.stream_policy import resolve_channel_stream_policy
from opensquilla.channels.types import IncomingMessage, OutgoingMessage
from opensquilla.engine.start_turn import start_turn_via_runtime
from opensquilla.engine.types import (
    ArtifactEvent,
    ErrorEvent,
    RouterDecisionEvent,
    RunHeartbeatEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.execution_status import normalize_execution_status
from opensquilla.gateway.attachment_ingest import AttachmentIngestResult, ingest_attachments
from opensquilla.gateway.session_events import build_sessions_changed_payload
from opensquilla.paths import media_root_from_config
from opensquilla.permissions import configured_default_elevated
from opensquilla.session.terminal_reply import build_terminal_reply

if TYPE_CHECKING:
    from opensquilla.gateway.event_bridge import EventBridge

log = structlog.get_logger(__name__)


def _terminal_payload_from_exception(exc: BaseException) -> dict[str, str]:
    is_timeout = isinstance(exc, TimeoutError)
    return {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": "timeout" if is_timeout else "error",
        "error_class": exc.__class__.__name__,
        "error_message": str(exc),
    }


def _terminal_payload_from_error_event(event: ErrorEvent) -> dict[str, str | None]:
    code = (event.code or "").lower()
    is_timeout = "timeout" in code or "stream_idle" in code
    return {
        "status": "timeout" if is_timeout else "failed",
        "terminal_reason": "timeout" if is_timeout else "error",
        "error_class": event.code,
        "error_message": event.message,
    }


def _terminal_reply_suffix(message: str) -> str:
    return f"\n\n({message})"


def _emit_metric(name: str, value: int = 1, **labels: Any) -> None:
    """Emit a structured log line for a core metric (mirrors task_runtime._emit_metric).

    Format: event=<name> metric=<name> value=<int> [labels...]
    Used here for channel-adapter-level counters (queue_full_errors_total,
    turn_cancellations_total) that originate outside task_runtime.  Kept as a
    local copy to avoid a routing→task_runtime→channel_dispatch import cycle.
    """
    log.info(name, metric=name, value=value, **labels)


def _resolve_channel_overflow_policy(channel: Any, config: Any) -> str | None:
    """Resolve the per-channel overflow policy override (if any).

    Reads ``config.task_runtime.pending_overflow_policy_per_channel`` keyed
    by ``channel.channel_id``. Returns ``None`` when the channel has no
    explicit override so ``runtime.enqueue`` falls back to its constructor
    default (typically the global ``pending_overflow_policy``).
    """
    if config is None:
        return None
    runtime_cfg = getattr(config, "task_runtime", None)
    overrides = getattr(runtime_cfg, "pending_overflow_policy_per_channel", None)
    if not overrides:
        return None
    channel_id = getattr(channel, "channel_id", None)
    if not isinstance(channel_id, str) or not channel_id:
        return None
    value = overrides.get(channel_id)
    if not isinstance(value, str) or not value:
        return None
    return value


class _ChannelInFlightSet:
    """Per-channel in-flight reply task tracker with a configurable cap.

    This is a SEPARATE second-layer semaphore from ``task_runtime._global_sem``.
    ``task_runtime._global_sem`` gates how many turns run concurrently across
    all sessions; this cap gates how many *channel reply deliveries* are
    outstanding on a single channel adapter concurrently.  The two semaphores
    are independent: a turn can be enqueued in task_runtime but its reply
    delivery may still be queued here waiting for an in-flight slot.

    Cap formula: ``min(channel_inflight_cap, max(2 × max_concurrency, 1))``
    This prevents the channel adapter layer from exhausting the global semaphore
    by ensuring the channel cap never exceeds twice the global concurrency budget.

    Env variable: ``OPENSQUILLA_CHANNEL_INFLIGHT_CAP`` (default 8) is
    surfaced through ``config.task_runtime.channel_inflight_cap``.
    """

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def cap(self) -> int:
        return self._cap

    def full(self) -> bool:
        return len(self._tasks) >= self._cap

    def add(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)

    def discard(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)

    def try_acquire(self, token: object) -> bool:
        """Atomically check cap and reserve a slot using *token* as the key.

        Returns True and adds *token* to the set if the cap is not yet reached;
        returns False (no mutation) if the set is already full.  Because asyncio
        runs on a single thread, this check-then-add pair is atomic — no await
        occurs between the guard and the mutation.
        """
        if len(self._tasks) >= self._cap:  # type: ignore[arg-type]
            return False
        self._tasks.add(token)  # type: ignore[arg-type]
        return True

    def release(self, token: object) -> None:
        """Release a reservation previously acquired via try_acquire."""
        self._tasks.discard(token)  # type: ignore[arg-type]

    async def cancel_all(self) -> None:
        """Cancel every in-flight task and await completion (for shutdown)."""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


def _compute_channel_cap(config: Any) -> int:
    """Compute the effective per-channel in-flight cap.

    Formula: ``min(channel_inflight_cap, max(2 × max_concurrency, 1))``

    This avoids the channel adapter layer monopolising the global semaphore
    (``task_runtime._global_sem``) whose size equals ``max_concurrency``.
    """
    task_runtime_cfg = getattr(config, "task_runtime", None) if config is not None else None
    raw_cap: int = getattr(task_runtime_cfg, "channel_inflight_cap", 8)
    max_concurrency: int = getattr(task_runtime_cfg, "max_concurrency", 4)
    formula_cap = max(2 * max_concurrency, 1)
    return min(raw_cap, formula_cap)

_DIRECTIVE_TAG_RE = re.compile(
    r"\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*"
)
_INTERNAL_COMPACTION_MARKER_RE = re.compile(
    r"(?m)^[ \t]*\["
    r"(?:opensquilla_compacted:[^\]\r\n]*|"
    r"provider_request_[^\]\r\n]*compacted:[^\]\r\n]*)"
    r"\][ \t]*(?:\r?\n)?"
    r"|\[(?:opensquilla_compacted:[^\]\r\n]*|"
    r"provider_request_[^\]\r\n]*compacted:[^\]\r\n]*)\]"
)
_INTERNAL_COMPACTION_MARKER_PREFIXES = (
    "[opensquilla_compacted:",
    "[provider_request_",
)
_DIRECTIVE_TAG_BUFFER_LIMIT = 256
_DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
_DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 600.0


def _strip_inline_directive_tags(content: str) -> str:
    return _DIRECTIVE_TAG_RE.sub("", content)


def _strip_internal_compaction_markers(content: str) -> str:
    return _INTERNAL_COMPACTION_MARKER_RE.sub("", content)


def _split_pending_internal_compaction_marker(content: str) -> tuple[str, str]:
    start = content.rfind("[")
    if start == -1:
        return content, ""
    suffix = content[start:]
    if "\n" in suffix or "\r" in suffix or "]" in suffix:
        return content, ""
    if len(suffix) > _DIRECTIVE_TAG_BUFFER_LIMIT:
        return content, ""
    if any(
        prefix.startswith(suffix) or suffix.startswith(prefix)
        for prefix in _INTERNAL_COMPACTION_MARKER_PREFIXES
    ):
        return content[:start], suffix
    return content, ""


def _sanitize_outgoing_message(message: OutgoingMessage) -> OutgoingMessage:
    cleaned = _strip_internal_compaction_markers(
        _strip_inline_directive_tags(message.content)
    )
    if cleaned == message.content:
        return message
    return message.model_copy(update={"content": cleaned})


class _DirectiveTagStreamSanitizer:
    """Strip inline reply directives even when a tag is split across chunks."""

    def __init__(self) -> None:
        self._pending = ""

    def clean(self, chunk: str) -> str:
        text = self._pending + chunk
        self._pending = ""
        cleaned = _strip_internal_compaction_markers(
            _strip_inline_directive_tags(text)
        )
        start = cleaned.rfind("[[")
        if start == -1:
            cleaned, pending_marker = _split_pending_internal_compaction_marker(
                cleaned
            )
            if pending_marker:
                self._pending = pending_marker
            return cleaned
        suffix = cleaned[start:]
        if (
            "]]" not in suffix
            and "\n" not in suffix
            and len(suffix) <= _DIRECTIVE_TAG_BUFFER_LIMIT
        ):
            self._pending = suffix
            return cleaned[:start]
        cleaned, pending_marker = _split_pending_internal_compaction_marker(cleaned)
        if pending_marker:
            self._pending = pending_marker
            return cleaned
        return cleaned

    def flush(self) -> str:
        pending = self._pending
        self._pending = ""
        return _strip_internal_compaction_markers(_strip_inline_directive_tags(pending))


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
                await _dispatch_combined_message_after_debounce(channel, combined, turn_runner, session_manager, key, session_prefix, task_runtime, config, event_bridge, _ifl, channel_rpc_context_factory=channel_rpc_context_factory)  # noqa: E501

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
                    _route_envelope_reply_message(
                        "Server busy, please retry",
                        route_envelope,
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
                    channel_overflow_policy = _resolve_channel_overflow_policy(
                        channel, config
                    )
                    if channel_overflow_policy is not None:
                        apply_policy = getattr(
                            task_runtime, "apply_overflow_policy", None
                        )
                        if callable(apply_policy):
                            await apply_policy(
                                session_key, policy=channel_overflow_policy
                            )
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
                    _route_envelope_reply_message(
                        (
                            "The session task queue is full. "
                            f"Try again after queued work completes. ({exc})"
                        ),
                        route_envelope,
                    )
                )
            else:
                await status_reactor.running(msg)

                typing_task = _start_typing_keepalive(channel, msg)

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
        typing_task = _start_typing_keepalive(channel, msg)
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
        return _route_envelope_reply_message(
            f"Unsupported command: {head}. Try /help.",
            route_envelope,
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

    reply = await DEFAULT_COMMAND_REGISTRY.dispatch(
        envelope=route_envelope,
        message_content=msg.content,
        rpc_dispatcher=rpc_dispatcher,
        context_factory=context_factory,
    )
    if reply is None:
        return None
    return _preserve_route_channel_metadata(reply, route_envelope)


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
        return _route_envelope_reply_message(
            (
                "/new denied: Insufficient scope for method: "
                f"sessions.reset{detail}"
            ),
            route_envelope,
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
        return _route_envelope_reply_message(
            "/new failed: command unavailable",
            route_envelope,
            metadata={"command": "new", "method": "sessions.reset", "denied": False},
        )
    return _preserve_route_channel_metadata(reply, route_envelope)


# fmt: off
async def _dispatch_combined_message_after_debounce(channel: Any, combined: Any, turn_runner: Any, session_manager: Any, session_key: str, session_prefix: str, task_runtime: Any, config: Any = None, event_bridge: EventBridge | None = None, _in_flight: _ChannelInFlightSet | None = None, channel_rpc_context_factory: Callable[[Any], Any] | None = None) -> None:  # noqa: E501
    from opensquilla.gateway.routing import build_channel_route_envelope

    msg = combined.message
    route_envelope = build_channel_route_envelope(msg, session_key=session_key, session_prefix=session_prefix)  # noqa: E501
    _get_lock = getattr(turn_runner, "_get_session_lock", None)
    session_lock = _get_lock(session_key) if callable(_get_lock) else None
    async with _maybe_lock(session_lock):
        await _record_delivery_context(session_manager, session_key, msg, session_prefix, route_envelope=route_envelope)  # noqa: E501

        if _should_skip_unmentioned(channel, msg, session_key):
            return

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
                _route_envelope_reply_message(
                    "Server busy, please retry",
                    route_envelope,
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
            channel_overflow_policy = _resolve_channel_overflow_policy(channel, config)
            if channel_overflow_policy is not None:
                apply_policy = getattr(task_runtime, "apply_overflow_policy", None)
                if callable(apply_policy):
                    await apply_policy(session_key, policy=channel_overflow_policy)
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
            await channel.send(_route_envelope_reply_message("Your messages couldn't be processed because the queue is full. Please retry.", route_envelope))  # noqa: E501
            return
        log.exception("channel_dispatch.debounce_enqueue_failed", session_key=session_key, reason="unexpected")  # noqa: E501
        await status_reactor.failed(msg)
        return

    # Enqueue succeeded — release the placeholder reservation now that the real
    # reply delivery will proceed (it doesn't use _in_flight in this path).
    if _in_flight is not None and _reservation_token is not None:
        _in_flight.release(_reservation_token)

    await status_reactor.running(msg)
    typing_task = _start_typing_keepalive(channel, msg)
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


def _start_typing_keepalive(
    channel: Any,
    inbound: IncomingMessage | None = None,
    interval: float = 8.0,
) -> asyncio.Task | None:
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
                if inbound is not None and _accepts_keyword_arg(send_typing, "channel_id"):
                    await send_typing(channel_id=inbound.channel_id)
                else:
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
    from opensquilla.engine.stream_wrappers import wrap_stream

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


def _is_channel_admin_sender(config: Any, envelope: Any) -> bool:
    admin_senders = getattr(config, "channel_admin_senders", None)
    if not isinstance(admin_senders, dict):
        return False

    source_name = getattr(envelope, "source_name", None)
    sender_id = getattr(envelope, "sender_id", None)
    if not isinstance(source_name, str) or not source_name:
        return False
    if not isinstance(sender_id, str) or not sender_id:
        return False

    configured = admin_senders.get(source_name)
    if isinstance(configured, str):
        return sender_id == configured
    if not isinstance(configured, list | tuple | set | frozenset):
        return False
    return sender_id in {str(item) for item in configured}


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
    from opensquilla.agents.scope import resolve_agent_workspace_dir
    from opensquilla.gateway.routing import build_channel_route_envelope, tool_context_from_envelope
    from opensquilla.session.keys import parse_agent_id

    agent_id = parse_agent_id(session_key)
    workspace_dir = resolve_agent_workspace_dir(agent_id, config)
    workspace_strict = getattr(config, "workspace_strict", None)
    if not isinstance(workspace_strict, bool):
        workspace_strict = bool(workspace_dir)
    envelope = route_envelope or build_channel_route_envelope(
        msg,
        session_key=session_key,
        session_prefix=getattr(channel, "channel_id", None) or "unknown",
        agent_id=agent_id,
    )
    tool_ctx = tool_context_from_envelope(
        envelope,
        is_owner=_is_channel_admin_sender(config, envelope),
        workspace_dir=str(workspace_dir),
        workspace_strict=workspace_strict,
        default_elevated=configured_default_elevated(config),
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


def _route_envelope_reply_message(
    content: str,
    route_envelope: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> OutgoingMessage:
    """Build a reply that preserves channel id when targeting a thread id."""
    channel_id = getattr(route_envelope, "channel_id", None)
    thread_id = getattr(route_envelope, "thread_id", None)
    merged_metadata = dict(metadata or {})
    if thread_id and channel_id:
        merged_metadata.setdefault("channel", channel_id)
    return _sanitize_outgoing_message(
        OutgoingMessage(
            content=content,
            reply_to=thread_id or channel_id,
            metadata=merged_metadata,
        )
    )


def _preserve_route_channel_metadata(
    reply: OutgoingMessage,
    route_envelope: Any,
) -> OutgoingMessage:
    """Add route channel metadata to thread-targeted replies when needed."""
    channel_id = getattr(route_envelope, "channel_id", None)
    thread_id = getattr(route_envelope, "thread_id", None)
    if not channel_id or not thread_id or reply.reply_to != thread_id:
        return _sanitize_outgoing_message(reply)
    metadata = dict(reply.metadata or {})
    metadata.setdefault("channel", channel_id)
    return _sanitize_outgoing_message(
        OutgoingMessage(
            content=reply.content,
            attachments=list(reply.attachments),
            metadata=metadata,
            reply_to=reply.reply_to,
        )
    )


def _status_reactor(channel: Any) -> Any:
    from opensquilla.channels._reactions import NULL_STATUS_REACTOR

    return getattr(channel, "status_reactor", NULL_STATUS_REACTOR)


def _streaming_reply_kwargs(channel: Any, msg: IncomingMessage) -> dict[str, Any]:
    builder = getattr(channel, "streaming_reply_kwargs", None)
    if not callable(builder):
        return {}
    return dict(builder(msg))


_STREAM_DONE = object()

# Coalescing window for consecutive text deltas in the relay queue. The
# relay yields a batched chunk once either threshold is reached. Both
# defaults are 0 so the relay preserves its historical one-chunk-per-delta
# behaviour out of the box; tuning either via ``config.task_runtime``
# enables coalescing for adapters that incur a per-call cost on
# ``send_streaming`` updates.
_STREAM_RELAY_DEFAULT_COALESCE_MS = 0.0
_STREAM_RELAY_DEFAULT_COALESCE_CHARS = 0


def _resolve_stream_relay_coalesce(config: Any) -> tuple[float, int]:
    """Return ``(window_seconds, char_threshold)`` for stream relay batching.

    ``None`` config or absent fields fall back to the module defaults so
    legacy call sites (tests, embedded use) keep their historical behaviour.
    """
    window_ms = _STREAM_RELAY_DEFAULT_COALESCE_MS
    char_threshold = _STREAM_RELAY_DEFAULT_COALESCE_CHARS
    runtime_cfg = getattr(config, "task_runtime", None) if config is not None else None
    cfg_window = getattr(runtime_cfg, "stream_relay_coalesce_ms", None)
    if isinstance(cfg_window, int | float) and cfg_window >= 0:
        window_ms = float(cfg_window)
    cfg_chars = getattr(runtime_cfg, "stream_relay_coalesce_chars", None)
    if isinstance(cfg_chars, int) and cfg_chars >= 0:
        char_threshold = cfg_chars
    return window_ms / 1000.0, char_threshold


class _RuntimeChannelStreamRelay:
    """Bridge one runtime task's stream events into a channel streaming adapter.

    The relay coalesces consecutive text deltas into larger chunks before
    handing them to ``send_streaming`` — adapters that incur a per-call cost
    (rate-limited message edits, network round trips) benefit from batching
    micro-deltas.  When ``send_streaming`` fails mid-stream the relay falls
    back to a single ``channel.send`` carrying the not-yet-delivered text so
    the user still sees the rest of the reply.
    """

    def __init__(self, channel: Any, inbound: IncomingMessage, config: Any = None) -> None:
        self._channel = channel
        self._inbound = inbound
        self._config = config
        self._queue: asyncio.Queue[str | object] = asyncio.Queue()
        self._artifacts: list[dict[str, Any]] = []
        self.delivered_artifact_keys: set[str] = set()
        self._task: asyncio.Task[Any] | None = None
        self._closed = False
        self.text_emitted = False
        self.stream_error: BaseException | None = None
        # Buffer of chunks already yielded to ``send_streaming``. If the
        # adapter raises mid-stream the relay falls back to ``channel.send``
        # with the chunks that never made it through.
        self._yielded_chunks: list[str] = []
        self._undelivered_index = 0
        coalesce_window_s, coalesce_chars = _resolve_stream_relay_coalesce(config)
        self._coalesce_window_s = coalesce_window_s
        self._coalesce_chars = coalesce_chars

    @classmethod
    def maybe_start(
        cls,
        channel: Any,
        inbound: IncomingMessage,
        task_runtime: Any,
        config: Any = None,
    ) -> _RuntimeChannelStreamRelay | None:
        if not resolve_channel_stream_policy(channel).relay_stream:
            return None
        enqueue = getattr(task_runtime, "enqueue", None)
        if not callable(enqueue) or not _accepts_keyword_arg(enqueue, "stream_event_sink"):
            return None
        relay = cls(channel, inbound, config)
        relay._task = asyncio.create_task(relay._run())
        return relay

    async def _run(self) -> Any:
        try:
            return await self._channel.send_streaming(
                self._chunks(),
                **_streaming_reply_kwargs(self._channel, self._inbound),
            )
        except Exception as exc:  # noqa: BLE001 - streaming is best-effort fallback.
            self.stream_error = exc
            log.warning(
                "channel_dispatch.runtime_streaming_failed",
                channel_type=type(self._channel).__name__,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None

    async def _coalesce_next_batch(
        self,
        first_text: str,
    ) -> tuple[str, object | None]:
        """Aggregate consecutive text items until window or char threshold.

        Returns ``(batched_text, sentinel_or_none)`` — when the trailing
        sentinel is ``_STREAM_DONE`` the caller flushes and exits.
        """
        if self._coalesce_window_s <= 0 and self._coalesce_chars <= 0:
            return first_text, None
        buffer = [first_text]
        size = len(first_text)
        deadline = (
            asyncio.get_event_loop().time() + self._coalesce_window_s
            if self._coalesce_window_s > 0
            else None
        )
        while True:
            if self._coalesce_chars and size >= self._coalesce_chars:
                return "".join(buffer), None
            remaining = (
                deadline - asyncio.get_event_loop().time()
                if deadline is not None
                else None
            )
            if remaining is not None and remaining <= 0:
                return "".join(buffer), None
            try:
                if remaining is None:
                    item = self._queue.get_nowait()
                else:
                    item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except (asyncio.QueueEmpty, TimeoutError):
                return "".join(buffer), None
            if item is _STREAM_DONE:
                return "".join(buffer), _STREAM_DONE
            if isinstance(item, str):
                buffer.append(item)
                size += len(item)

    async def _chunks(self) -> AsyncIterator[str]:
        sanitizer = _DirectiveTagStreamSanitizer()
        while True:
            item = await self._queue.get()
            if item is _STREAM_DONE:
                tail = sanitizer.flush()
                if tail:
                    self._yielded_chunks.append(tail)
                    yield tail
                    # Only advance the delivered watermark when the consumer
                    # accepted the chunk (yield returned). If yield raises,
                    # the consumer failed to process it and the chunk must
                    # be replayed via the close() fallback path.
                    self._undelivered_index = len(self._yielded_chunks)
                return
            if not isinstance(item, str):
                continue
            batched, sentinel = await self._coalesce_next_batch(item)
            chunk = sanitizer.clean(batched)
            if chunk:
                self._yielded_chunks.append(chunk)
                yield chunk
                self._undelivered_index = len(self._yielded_chunks)
            if sentinel is _STREAM_DONE:
                tail = sanitizer.flush()
                if tail:
                    self._yielded_chunks.append(tail)
                    yield tail
                    self._undelivered_index = len(self._yielded_chunks)
                return

    async def emit(self, event: Any) -> None:
        artifact = _artifact_event_payload(event)
        if artifact is not None:
            self._artifacts.append(artifact)
            return
        text = _text_delta_from_event(event)
        if not text:
            return
        text = _strip_artifact_markers_from_channel_text(text)
        if not text:
            return
        self.text_emitted = True
        await self._queue.put(text)

    async def close(self, timeout: float = 10.0) -> None:
        if self._closed:
            return
        self._closed = True
        artifact_lines = (
            []
            if _can_deliver_channel_files(self._channel)
            else _artifact_fallback_lines(self._artifacts)
        )
        if artifact_lines:
            prefix = "\n\n" if self.text_emitted else ""
            artifact_text = "\n".join(artifact_lines)
            await self._queue.put(f"{prefix}{artifact_text}")
            self.text_emitted = True
        await self._queue.put(_STREAM_DONE)
        if self._task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
        except TimeoutError as exc:
            self.stream_error = exc
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        except Exception as exc:  # noqa: BLE001 - error already becomes batch fallback.
            self.stream_error = exc

        # Per-event delivery fallback: when send_streaming raised mid-stream,
        # any chunk that was queued but never reached the consumer must
        # still land via channel.send. Drain the relay queue for queued
        # text items, concatenate with chunks already yielded but not
        # delivered, and send as a single batch reply. Successful streams
        # (stream_error is None) skip this branch.
        if self.stream_error is not None:
            queued_remainder: list[str] = []
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is _STREAM_DONE:
                    continue
                if isinstance(item, str):
                    queued_remainder.append(item)
            undelivered_yielded = "".join(
                self._yielded_chunks[self._undelivered_index :]
            )
            fallback_text = undelivered_yielded + "".join(queued_remainder)
            if fallback_text:
                try:
                    await self._channel.send(
                        _build_reply_message(
                            self._channel,
                            fallback_text,
                            self._inbound,
                        )
                    )
                except Exception as send_exc:  # noqa: BLE001 - log only.
                    log.warning(
                        "channel_dispatch.stream_relay_batch_fallback_failed",
                        channel_type=type(self._channel).__name__,
                        error_type=type(send_exc).__name__,
                        error=str(send_exc),
                    )
                self._undelivered_index = len(self._yielded_chunks)

        if _can_deliver_channel_files(self._channel):
            undelivered = await _deliver_artifacts_as_channel_files(
                self._channel,
                self._inbound,
                self._artifacts,
                self._config,
            )
            undelivered_keys = {
                key for artifact in undelivered if (key := _artifact_delivery_key(artifact))
            }
            self.delivered_artifact_keys.update(
                key
                for artifact in self._artifacts
                if (key := _artifact_delivery_key(artifact)) and key not in undelivered_keys
            )
            fallback_lines = _artifact_fallback_lines(undelivered)
            if fallback_lines:
                await self._channel.send(
                    _build_reply_message(
                        self._channel,
                        "\n".join(fallback_lines),
                        self._inbound,
                    )
                )


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


def _artifact_event_payload(event: Any) -> dict[str, Any] | None:
    if isinstance(event, ArtifactEvent):
        return artifact_payload(event)
    if isinstance(event, dict) and event.get("kind") == "artifact":
        return artifact_payload(event)
    if getattr(event, "kind", None) == "artifact":
        return artifact_payload(event)
    return None


def _router_decision_payload(event: RouterDecisionEvent) -> dict[str, Any]:
    return {
        "tier": event.tier,
        "tier_index": event.tier_index,
        "model": event.model,
        "baseline_model": event.baseline_model,
        "source": event.source,
        "confidence": event.confidence,
        "probs": list(event.probs),
        "savings_pct": event.savings_pct,
        "fallback": event.fallback,
        "thinking_mode": event.thinking_mode,
        "prompt_policy": event.prompt_policy,
        "routing_applied": event.routing_applied,
        "rollout_phase": event.rollout_phase,
    }


def _tool_use_start_payload(event: ToolUseStartEvent) -> dict[str, Any]:
    return {
        "tool_use_id": event.tool_use_id,
        "tool_name": event.tool_name,
        "name": event.tool_name,
        "synthetic_from_text": event.synthetic_from_text,
    }


def _tool_result_payload(event: ToolResultEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_use_id": event.tool_use_id,
        "tool_name": event.tool_name,
        "name": event.tool_name,
        "result": event.result,
        "is_error": event.is_error,
    }
    if event.arguments is not None:
        payload["arguments"] = event.arguments
    if event.execution_status is not None:
        payload["execution_status"] = normalize_execution_status(event.execution_status)
    return payload


def _clarify_tool_arguments(event: ToolResultEvent) -> dict[str, Any] | None:
    args = event.arguments
    if not isinstance(args, dict):
        return None
    schema = args.get("clarify_schema")
    if (
        args.get("kind") == "user_input"
        and args.get("paused") is True
        and isinstance(schema, dict)
    ):
        return args
    return None


def _channel_accepts_metadata_card(channel: Any) -> bool:
    profile = channel_capability_profile(channel)
    if profile is None:
        return bool(getattr(channel, "supports_clarify_cards", False))
    if not (profile.cards or profile.interactive_cards or profile.card_actions):
        return False
    return profile.channel_type == "feishu" or bool(
        getattr(channel, "supports_clarify_cards", False)
    )


def _clarify_field_label(field: dict[str, Any]) -> str:
    name = str(field.get("name") or "").strip()
    prompt = str(field.get("prompt") or "").strip()
    if prompt and prompt != name:
        return f"{name} - {prompt}"
    return name or prompt or "field"


def _clarify_field_required_text(field: dict[str, Any]) -> str:
    if field.get("required") is True:
        return "required"
    if field.get("default") not in (None, ""):
        return f"default: {field['default']}"
    return "optional"


def _clarify_field_element(field: dict[str, Any]) -> dict[str, Any] | None:
    name = str(field.get("name") or "").strip()
    if not name:
        return None
    label = _clarify_field_label(field)
    placeholder = {
        "tag": "plain_text",
        "content": label,
    }
    field_type = str(field.get("type") or "string").lower()
    if field_type == "enum" and isinstance(field.get("choices"), list):
        options: list[dict[str, Any]] = []
        for choice in field["choices"]:
            rendered = str(choice)
            options.append(
                {
                    "text": {"tag": "plain_text", "content": rendered},
                    "value": rendered,
                }
            )
        return {
            "tag": "select_static",
            "name": name,
            "placeholder": placeholder,
            "options": options,
        }
    if field_type == "bool":
        return {
            "tag": "select_static",
            "name": name,
            "placeholder": placeholder,
            "options": [
                {"text": {"tag": "plain_text", "content": "true"}, "value": "true"},
                {"text": {"tag": "plain_text", "content": "false"}, "value": "false"},
            ],
        }
    return {
        "tag": "input",
        "name": name,
        "placeholder": placeholder,
    }


def _build_clarify_channel_card(args: dict[str, Any], msg: IncomingMessage) -> dict[str, Any]:
    schema = cast(dict[str, Any], args["clarify_schema"])
    fields = schema.get("fields")
    if not isinstance(fields, list):
        fields = []
    intro = str(schema.get("intro") or "").strip()
    elements: list[dict[str, Any]] = []
    if intro:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": intro}})

    rows: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        rows.append(f"- **{_clarify_field_label(field)}** ({_clarify_field_required_text(field)})")
    if rows:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**Fields**\n" + "\n".join(rows),
                },
            }
        )
    for field in fields:
        if isinstance(field, dict) and (element := _clarify_field_element(field)):
            elements.append(element)

    value: dict[str, Any] = {
        "opensquilla_action": "clarify_submit",
        "channel_id": msg.channel_id,
    }
    is_group = msg.metadata.get("is_group")
    if isinstance(is_group, bool):
        value["is_group"] = is_group
    chat_type = msg.metadata.get("chat_type")
    if isinstance(chat_type, str) and chat_type:
        value["chat_type"] = chat_type
    if isinstance(args.get("run_id"), str) and args["run_id"]:
        value["run_id"] = args["run_id"]
    if isinstance(args.get("step"), str) and args["step"]:
        value["step"] = args["step"]

    cancel_keywords = schema.get("cancel_keywords")
    if isinstance(cancel_keywords, list) and cancel_keywords:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "Cancel: " + " / ".join(str(item) for item in cancel_keywords),
                    }
                ],
            }
        )

    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Submit"},
                    "type": "primary",
                    "value": value,
                }
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "需要补充信息"},
        },
        "elements": elements,
    }


async def _maybe_send_clarify_channel_card(
    channel: Any,
    msg: IncomingMessage,
    event: ToolResultEvent,
) -> bool:
    args = _clarify_tool_arguments(event)
    if args is None or not _channel_accepts_metadata_card(channel):
        return False
    card = _build_clarify_channel_card(args, msg)
    try:
        await channel.send(
            OutgoingMessage(
                content="OpenSquilla clarification form",
                reply_to=msg.channel_id,
                metadata={"card": card},
            )
        )
    except Exception as exc:  # noqa: BLE001 - keep text fallback available
        log.warning(
            "channel_dispatch.clarify_card_send_failed",
            channel_type=type(channel).__name__,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False
    return True


async def _read_transcript_rows(session_manager: Any, session_key: str) -> list[Any]:
    read_transcript = getattr(session_manager, "read_transcript", None)
    if not callable(read_transcript):
        return []
    try:
        rows = await read_transcript(session_key)
    except Exception:
        log.warning("channel_dispatch.read_transcript_failed", session_key=session_key)
        return []
    return list(rows or [])


async def _transcript_watermark(session_manager: Any, session_key: str) -> int:
    return len(await _read_transcript_rows(session_manager, session_key))


def _dump_attachment(attachment: Any) -> dict[str, Any] | None:
    if isinstance(attachment, dict):
        return dict(attachment)
    model_dump = getattr(attachment, "model_dump", None)
    if callable(model_dump):
        # Keep Pydantic's Python-mode default so bytes remain bytes for shared ingest.
        dumped = model_dump()
        return dict(dumped) if isinstance(dumped, dict) else None
    return None


async def _materialize_channel_attachments(channel: Any, attachments: list[Any]) -> list[Any]:
    resolver = getattr(channel, "resolve_inbound_attachment", None)
    if not callable(resolver):
        return list(attachments or [])

    materialized: list[Any] = []
    for attachment in attachments or []:
        try:
            resolved = resolver(attachment)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            materialized.append(resolved if resolved is not None else attachment)
        except Exception as exc:  # noqa: BLE001 - failure degrades via shared ingest marker
            item = _dump_attachment(attachment) or {"name": "attachment"}
            item["_ingest_error"] = str(exc)
            materialized.append(item)
    return materialized


async def _ingest_channel_message_attachments(
    *,
    channel: Any,
    msg: IncomingMessage,
) -> AttachmentIngestResult:
    materialized = await _materialize_channel_attachments(
        channel,
        list(getattr(msg, "attachments", []) or []),
    )
    result = await ingest_attachments(
        msg.content,
        materialized,
        failure_mode="mark",
        mark_bytes_as_staged=True,
    )
    for failure in result.failures:
        log.warning(
            "channel.attachment_ingest_failed",
            channel=getattr(channel, "channel_id", None) or type(channel).__name__,
            attachment_index=failure.index,
            attachment_name=failure.name,
            reason=failure.reason,
            detail=failure.detail,
        )
    return result


async def _append_channel_user_message(
    *,
    session_manager: Any,
    session_key: str,
    text: str,
    attachments: list[dict[str, Any]],
    config: Any,
) -> tuple[Any, str]:
    if attachments:
        from opensquilla.gateway.transcripts import build_transcript_attachment_envelope

        stamped_text = text
        if hasattr(session_manager, "stamp_user_text"):
            stamped = session_manager.stamp_user_text(text)
            if isinstance(stamped, str):
                stamped_text = stamped

        attachments_cfg = getattr(config, "attachments", None)
        persist_enabled = bool(getattr(attachments_cfg, "persist_transcripts", True))
        media_root = media_root_from_config(config)
        disk_budget = getattr(attachments_cfg, "transcript_disk_budget_bytes", None)
        session_id = session_key.split(":")[-1] or session_key
        envelope, _writes = build_transcript_attachment_envelope(
            text=stamped_text,
            attachments=attachments,
            session_id=session_id,
            media_root=media_root,
            persist_enabled=persist_enabled,
            disk_budget_bytes=disk_budget if isinstance(disk_budget, int) else None,
        )
        persisted = await session_manager.append_message(session_key, role="user", content=envelope)
        return persisted, stamped_text

    persisted = await session_manager.append_message(session_key, role="user", content=text)
    if persisted is not None and isinstance(persisted.content, str):
        return persisted, persisted.content
    return persisted, text


async def _latest_assistant_text_after(
    session_manager: Any,
    session_key: str,
    start_index: int,
) -> str:
    rows = await _read_transcript_rows(session_manager, session_key)
    for row in reversed(rows[start_index:]):
        role = row.get("role") if isinstance(row, dict) else getattr(row, "role", None)
        content = row.get("content") if isinstance(row, dict) else getattr(row, "content", None)
        if role == "assistant" and isinstance(content, str) and content:
            return content
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


def _split_assistant_artifact_content(content: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return content, []
    if not isinstance(parsed, dict):
        return content, []
    text = parsed.get("text")
    artifacts_raw = parsed.get("artifacts")
    if not isinstance(text, str) or not isinstance(artifacts_raw, list):
        return content, []
    artifacts: list[dict[str, Any]] = []
    for artifact in artifacts_raw:
        try:
            payload = artifact_payload(artifact)
        except Exception:
            continue
        if payload:
            artifacts.append(payload)
    return text, artifacts


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
    clarify_card_sent = False

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
                if clarify_card_sent:
                    continue
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
            elif isinstance(event, RouterDecisionEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.router_decision",
                        _router_decision_payload(event),
                    )
            elif isinstance(event, ToolUseStartEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.tool_use_start",
                        _tool_use_start_payload(event),
                    )
            elif isinstance(event, ToolResultEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.tool_result",
                        _tool_result_payload(event),
                    )
                if await _maybe_send_clarify_channel_card(channel, msg, event):
                    clarify_card_sent = True
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
    stream_task_error: BaseException | None = None
    yielded_stream_chunks: list[str] = []
    stream_delivered_index = 0
    artifacts: list[dict[str, Any]] = []
    stream_sanitizer = _DirectiveTagStreamSanitizer()
    clarify_card_sent = False

    async def _chunk_iter() -> AsyncIterator[str]:
        """Async iterator that yields text chunks from the queue."""
        nonlocal stream_delivered_index
        while True:
            chunk = await queue.get()
            if chunk is None:
                tail = stream_sanitizer.flush()
                if tail:
                    yielded_stream_chunks.append(tail)
                    yield tail
                    stream_delivered_index = len(yielded_stream_chunks)
                return
            cleaned = stream_sanitizer.clean(chunk)
            if cleaned:
                yielded_stream_chunks.append(cleaned)
                yield cleaned
                stream_delivered_index = len(yielded_stream_chunks)

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
                if clarify_card_sent:
                    continue
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
            elif isinstance(event, RouterDecisionEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.router_decision",
                        _router_decision_payload(event),
                    )
            elif isinstance(event, ToolUseStartEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.tool_use_start",
                        _tool_use_start_payload(event),
                    )
            elif isinstance(event, ToolResultEvent):
                if event_bridge is not None:
                    await event_bridge.emit(
                        session_key,
                        "session.event.tool_result",
                        _tool_result_payload(event),
                    )
                if await _maybe_send_clarify_channel_card(channel, msg, event):
                    clarify_card_sent = True
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
        except TimeoutError as exc:
            stream_task_error = exc
            log.warning(
                "channel_dispatch.direct_streaming_failed",
                channel_type=type(channel).__name__,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            stream_task.cancel()
        except Exception as exc:  # noqa: BLE001 - streaming adapter fallback below
            stream_task_error = exc
            log.warning(
                "channel_dispatch.direct_streaming_failed",
                channel_type=type(channel).__name__,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            stream_task.cancel()

    if stream_task_error is not None and text_emitted:
        queued_remainder: list[str] = []
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(item, str):
                cleaned = stream_sanitizer.clean(item)
                if cleaned:
                    queued_remainder.append(cleaned)
        tail = stream_sanitizer.flush()
        if tail:
            queued_remainder.append(tail)
        undelivered_yielded = "".join(
            yielded_stream_chunks[stream_delivered_index:]
        )
        fallback_text = undelivered_yielded + "".join(queued_remainder)
        if fallback_text:
            try:
                await channel.send(_build_reply_message(channel, fallback_text, msg))
            except Exception as exc:  # noqa: BLE001 - best-effort fallback
                log.warning(
                    "channel_dispatch.direct_streaming_batch_fallback_failed",
                    channel_type=type(channel).__name__,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

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
        build_sessions_changed_payload(session_key, reason),
    )
