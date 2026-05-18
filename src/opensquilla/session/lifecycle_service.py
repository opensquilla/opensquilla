"""Reusable session lifecycle helpers.

This module deliberately stays Gateway-free so reset/delete/compact RPC handlers
can share session-domain access rules without adding package edges.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from opensquilla.session.services import get_session_lock, get_session_storage


def require_session_storage(session_manager: Any) -> Any:
    storage = get_session_storage(session_manager)
    if storage is None:
        raise KeyError("No session storage available")
    return storage


async def require_existing_session(storage: Any, session_key: str) -> Any:
    session = await storage.get_session(session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    return session


async def run_with_session_lock[T](
    turn_runner: Any,
    session_key: str,
    operation: Callable[[], Awaitable[T]],
) -> T:
    lock = get_session_lock(turn_runner, session_key)
    if lock is None:
        return await operation()
    async with lock:
        return await operation()
