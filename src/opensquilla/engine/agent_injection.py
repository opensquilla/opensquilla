"""In-process pending-input provider for mid-turn prompt injection."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PendingInputProvider(Protocol):
    """Port for draining prompts queued for injection into the active agent turn.

    Implementations must be accessed from the same asyncio event loop as the
    agent. This is the in-process injection channel contract: append and drain
    occur under single-threaded cooperative scheduling, so a synchronous
    ``drain_pending`` call has atomic semantics without locks or awaits.
    """

    def drain_pending(self) -> list[str]:
        """Return all pending injection text and clear the provider."""


class ListPendingInputProvider:
    """Default in-process pending-input provider backed by a list."""

    def __init__(self) -> None:
        self._pending: list[str] = []

    def append(self, text: str) -> None:
        """Queue one pending input, ignoring empty or whitespace-only text."""

        if not text.strip():
            return
        self._pending.append(text)

    def drain_pending(self) -> list[str]:
        """Return queued inputs in order and reset the provider."""

        pending = list(self._pending)
        self._pending = []
        return pending

    def __len__(self) -> int:
        return len(self._pending)

    def __bool__(self) -> bool:
        return bool(self._pending)
