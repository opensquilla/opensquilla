"""In-memory spawn-group lifecycle tracking for session-owned cleanup."""

from __future__ import annotations


class SpawnGroupTracker:
    """Tracks per-spawn-group close and wake state for parent-session announces.

    Spawn groups are keyed by ``(parent_session_key, parent_task_id)``. The
    tracker exposes an ``evict`` hook so session lifecycle cleanup can drop
    parent-session bookkeeping without depending on gateway modules.
    """

    def __init__(self) -> None:
        self._closed: set[tuple[str, str]] = set()
        self._woken: set[tuple[str, str]] = set()

    def mark_closed(self, parent_session_key: str, parent_task_id: str) -> None:
        self._closed.add((parent_session_key, parent_task_id))

    def is_closed(self, parent_session_key: str, parent_task_id: str) -> bool:
        return (parent_session_key, parent_task_id) in self._closed

    def mark_woken(self, group_key: tuple[str, str]) -> None:
        self._woken.add(group_key)

    def is_woken(self, group_key: tuple[str, str]) -> bool:
        return group_key in self._woken

    def discard_woken(self, group_key: tuple[str, str]) -> None:
        self._woken.discard(group_key)

    def evict(self, parent_session_key: str) -> int:
        """Drop all groups associated with ``parent_session_key``.

        Returns the count of removed entries (closed + woken).
        """
        removed = 0
        for bucket in (self._closed, self._woken):
            for entry in [e for e in bucket if e[0] == parent_session_key]:
                bucket.discard(entry)
                removed += 1
        return removed


spawn_group_tracker = SpawnGroupTracker()
