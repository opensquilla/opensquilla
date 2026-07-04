from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from opensquilla.asyncio_utils import create_background_task


async def _return_value(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_create_background_task_returns_real_task() -> None:
    task = create_background_task(_return_value("done"))

    assert isinstance(task, asyncio.Task)
    assert await task == "done"


@pytest.mark.asyncio
async def test_create_background_task_closes_unconsumed_coroutine_for_stubbed_non_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> object:
        return sentinel

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    coro = _return_value("unused")
    assert coro.cr_frame is not None

    result = create_background_task(coro)

    assert result is sentinel
    assert coro.cr_frame is None


@pytest.mark.asyncio
async def test_create_background_task_closes_unconsumed_coroutine_when_create_task_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CreateTaskError(RuntimeError):
        pass

    def fake_create_task(coro: Coroutine[Any, Any, Any]) -> object:
        raise CreateTaskError("task creation failed")

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    coro = _return_value("unused")
    assert coro.cr_frame is not None

    with pytest.raises(CreateTaskError, match="task creation failed"):
        create_background_task(coro)

    assert coro.cr_frame is None
