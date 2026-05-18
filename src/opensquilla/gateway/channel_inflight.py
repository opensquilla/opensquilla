"""Per-channel in-flight tracking for channel dispatch."""

from __future__ import annotations

import asyncio
from typing import Any

__all__ = ["ChannelInFlightSet", "compute_channel_cap"]


class ChannelInFlightSet:
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


def compute_channel_cap(config: Any) -> int:
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
