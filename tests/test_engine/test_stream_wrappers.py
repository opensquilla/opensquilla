import asyncio

import pytest

from opensquilla.engine.stream_wrappers import heartbeat_stream, idle_timeout_stream
from opensquilla.engine.types import RunHeartbeatEvent, TextDeltaEvent


@pytest.mark.asyncio
async def test_heartbeat_stream_emits_while_upstream_is_quiet() -> None:
    async def source():
        await asyncio.sleep(0.08)
        yield TextDeltaEvent(text="done")

    events = [event async for event in heartbeat_stream(source(), interval=0.02)]

    assert any(isinstance(event, RunHeartbeatEvent) for event in events)
    assert isinstance(events[-1], TextDeltaEvent)
    assert events[-1].text == "done"


@pytest.mark.asyncio
async def test_heartbeat_stream_preserves_upstream_idle_timeout() -> None:
    async def source():
        await asyncio.sleep(0.2)
        yield TextDeltaEvent(text="late")

    wrapped = heartbeat_stream(idle_timeout_stream(source(), timeout=0.06), interval=0.02)
    events = []
    with pytest.raises(TimeoutError):
        async for event in wrapped:
            events.append(event)

    assert any(isinstance(event, RunHeartbeatEvent) for event in events)


@pytest.mark.asyncio
async def test_upstream_run_heartbeat_resets_idle_timeout_stream() -> None:
    async def source():
        await asyncio.sleep(0.04)
        yield RunHeartbeatEvent(phase="tool", message="tool still running")
        await asyncio.sleep(0.04)
        yield TextDeltaEvent(text="done")

    events = [event async for event in idle_timeout_stream(source(), timeout=0.06)]

    assert [event.kind for event in events] == ["run_heartbeat", "text_delta"]
