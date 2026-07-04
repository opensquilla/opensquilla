import asyncio
from types import SimpleNamespace

import pytest

from opensquilla.engine.agent import Agent


class _BlockingProviderStream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    def __aiter__(self) -> "_BlockingProviderStream":
        return self

    async def __anext__(self) -> object:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_provider_next_event_is_cancelled_when_turn_stream_is_cancelled() -> None:
    agent = Agent.__new__(Agent)
    agent.config = SimpleNamespace(iteration_timeout=60.0, timeout=60.0)
    stream = _BlockingProviderStream()

    async def consume() -> None:
        async for _event in Agent._stream_provider_events_with_deadline(
            agent,
            stream,
            loop=asyncio.get_running_loop(),
            total_deadline=None,
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(stream.started.wait(), timeout=0.25)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    try:
        await asyncio.wait_for(stream.cancelled.wait(), timeout=0.25)
    finally:
        stream.release.set()
