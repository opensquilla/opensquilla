"""Runtime stream relay helpers for channel adapters."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import AsyncIterator
from typing import Any

import structlog

from opensquilla.channels.stream_policy import resolve_channel_stream_policy
from opensquilla.channels.types import IncomingMessage, OutgoingMessage
from opensquilla.engine.types import TextDeltaEvent
from opensquilla.gateway.channel_artifacts import (
    artifact_delivery_key,
    artifact_event_payload,
    artifact_fallback_lines,
    can_deliver_channel_files,
    deliver_artifacts_as_channel_files,
    strip_artifact_markers_from_channel_text,
)
from opensquilla.gateway.channel_replies import (
    DirectiveTagStreamSanitizer,
    sanitize_outgoing_message,
)

log = structlog.get_logger(__name__)

_STREAM_DONE = object()


def _accepts_keyword_arg(callable_obj: Any, name: str) -> bool:
    try:
        params = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _streaming_reply_kwargs(channel: Any, msg: IncomingMessage) -> dict[str, Any]:
    builder = getattr(channel, "streaming_reply_kwargs", None)
    if not callable(builder):
        return {}
    return dict(builder(msg))


def _build_reply_message(
    channel: Any, content: str, msg: IncomingMessage
) -> OutgoingMessage:
    builder = getattr(channel, "build_reply_message", None)
    if callable(builder):
        reply = builder(content, msg)
        if isinstance(reply, OutgoingMessage):
            return sanitize_outgoing_message(reply)
    return sanitize_outgoing_message(OutgoingMessage(content=content))


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


class RuntimeChannelStreamRelay:
    """Bridge one runtime task's stream events into a channel streaming adapter."""

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

    @classmethod
    def maybe_start(
        cls,
        channel: Any,
        inbound: IncomingMessage,
        task_runtime: Any,
        config: Any = None,
    ) -> RuntimeChannelStreamRelay | None:
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

    async def _chunks(self) -> AsyncIterator[str]:
        sanitizer = DirectiveTagStreamSanitizer()
        while True:
            item = await self._queue.get()
            if item is _STREAM_DONE:
                tail = sanitizer.flush()
                if tail:
                    yield tail
                return
            if isinstance(item, str):
                chunk = sanitizer.clean(item)
                if chunk:
                    yield chunk

    async def emit(self, event: Any) -> None:
        artifact = artifact_event_payload(event)
        if artifact is not None:
            self._artifacts.append(artifact)
            return
        text = _text_delta_from_event(event)
        if not text:
            return
        text = strip_artifact_markers_from_channel_text(text)
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
            if can_deliver_channel_files(self._channel)
            else artifact_fallback_lines(self._artifacts)
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

        if can_deliver_channel_files(self._channel):
            undelivered = await deliver_artifacts_as_channel_files(
                self._channel,
                self._inbound,
                self._artifacts,
                self._config,
            )
            undelivered_keys = {
                key for artifact in undelivered if (key := artifact_delivery_key(artifact))
            }
            self.delivered_artifact_keys.update(
                key
                for artifact in self._artifacts
                if (key := artifact_delivery_key(artifact)) and key not in undelivered_keys
            )
            fallback_lines = artifact_fallback_lines(undelivered)
            if fallback_lines:
                await self._channel.send(
                    _build_reply_message(
                        self._channel,
                        "\n".join(fallback_lines),
                        self._inbound,
                    )
                )
