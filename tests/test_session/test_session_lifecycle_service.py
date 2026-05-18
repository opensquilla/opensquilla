from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from opensquilla.session.lifecycle_service import (
    require_existing_session,
    require_session_storage,
    run_with_session_lock,
)


class _SessionStorage:
    def __init__(self, session: object | None) -> None:
        self.session = session
        self.requested_keys: list[str] = []

    async def get_session(self, key: str) -> object | None:
        self.requested_keys.append(key)
        return self.session


def test_require_session_storage_prefers_public_storage_surface() -> None:
    storage = object()
    manager = SimpleNamespace(storage=storage)

    assert require_session_storage(manager) is storage


def test_require_session_storage_keeps_private_fallback_error_message() -> None:
    manager = SimpleNamespace()

    with pytest.raises(KeyError, match="No session storage available"):
        require_session_storage(manager)


@pytest.mark.asyncio
async def test_require_existing_session_returns_storage_session() -> None:
    session = object()
    storage = _SessionStorage(session)

    assert await require_existing_session(storage, "agent:main:one") is session
    assert storage.requested_keys == ["agent:main:one"]


@pytest.mark.asyncio
async def test_require_existing_session_keeps_not_found_error_message() -> None:
    storage = _SessionStorage(None)

    with pytest.raises(KeyError, match="Session not found: agent:main:missing"):
        await require_existing_session(storage, "agent:main:missing")


@pytest.mark.asyncio
async def test_run_with_session_lock_uses_runtime_session_lock() -> None:
    lock = asyncio.Lock()
    runner = SimpleNamespace(get_session_lock=lambda _key: lock)
    observed_locked: list[bool] = []

    async def operation() -> str:
        observed_locked.append(lock.locked())
        return "ok"

    result = await run_with_session_lock(runner, "agent:main:one", operation)

    assert result == "ok"
    assert observed_locked == [True]


@pytest.mark.asyncio
async def test_run_with_session_lock_runs_without_lock_when_unavailable() -> None:
    runner = SimpleNamespace()

    async def operation() -> str:
        return "ok"

    assert await run_with_session_lock(runner, "agent:main:one", operation) == "ok"
