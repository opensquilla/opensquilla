"""Channel message debounce coordinator."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any, Protocol

import structlog

from opensquilla.channels.types import IncomingMessage

log = structlog.get_logger(__name__)


class DebounceCoordinator(Protocol):
    async def schedule(
        self,
        session_key: str,
        message: IncomingMessage,
        *,
        window_s: float,
        on_fire: Any,
    ) -> None:
        """Schedule an inbound channel message for debounce coalescing."""
        ...


class _DefaultDebounceCoordinator:
    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def schedule(
        self,
        session_key: str,
        message: IncomingMessage,
        *,
        window_s: float,
        on_fire: Any,
    ) -> None:
        async with self._lock:
            if state := self._pending.get(session_key):
                state.buffer.append(message)
                return
            task = asyncio.create_task(
                self._fire(session_key, window_s),
                name=f"channel-debounce:{session_key}",
            )
            self._pending[session_key] = SimpleNamespace(
                buffer=[message],
                on_fire=on_fire,
                task=task,
            )

    async def cancel(self, session_key: str) -> None:
        async with self._lock:
            state = self._pending.pop(session_key, None)
        if state is None or state.task.done():
            return
        log.info("channel.debounce_cancelled", session_key=session_key)
        state.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.task

    async def cancel_all(self) -> None:
        await asyncio.gather(
            *(self.cancel(k) for k in list(self._pending)),
            return_exceptions=True,
        )

    async def _fire(self, session_key: str, window_s: float) -> None:
        try:
            await asyncio.sleep(window_s)
            async with self._lock:
                state = self._pending.pop(session_key, None)
            if state is None:
                return
            first = state.buffer[0]
            content = "\n".join(m.content for m in state.buffer)
            attachments = [a for m in state.buffer for a in (m.attachments or [])]
            msg = IncomingMessage(
                sender_id=first.sender_id,
                channel_id=first.channel_id,
                content=content,
                attachments=attachments,
                metadata=dict(first.metadata or {}),
            )
            combined = SimpleNamespace(
                content=content,
                attachments=attachments,
                message=msg,
                coalesced_count=len(state.buffer),
            )
            log.info(
                "channel.debounce_coalesced",
                session_key=session_key,
                coalesced_count=combined.coalesced_count,
            )
            await state.on_fire(combined)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("channel_dispatch.debounce_enqueue_failed", reason="unexpected")
