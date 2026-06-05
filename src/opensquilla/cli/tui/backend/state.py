"""Runtime-owned state for interactive terminal UI loops."""

from __future__ import annotations

import collections
from dataclasses import dataclass, field


@dataclass
class TuiRuntimeState:
    """Explicit state for pending input and the active turn."""

    _pending: collections.deque[str] = field(default_factory=collections.deque)
    active_input: str | None = None

    @property
    def pending_size(self) -> int:
        return len(self._pending)

    @property
    def pending_items(self) -> tuple[str, ...]:
        return tuple(self._pending)

    @property
    def has_active_turn(self) -> bool:
        return self.active_input is not None

    def enqueue(self, user_input: str) -> None:
        self._pending.append(user_input)

    def promote_next(self) -> str | None:
        if not self._pending:
            return None
        return self._pending.popleft()

    def clear_pending(self) -> tuple[str, ...]:
        dropped = tuple(self._pending)
        self._pending.clear()
        return dropped

    def drain_pending(self) -> list[str]:
        """Return and clear queued inputs for in-turn agent injection."""

        return list(self.clear_pending())

    def mark_turn_started(self, user_input: str) -> None:
        self.active_input = user_input

    def mark_turn_finished(self) -> None:
        self.active_input = None
