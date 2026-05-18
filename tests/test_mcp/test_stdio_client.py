from __future__ import annotations

import asyncio

import pytest

from opensquilla.mcp.stdio import MCPStdioClient
from opensquilla.mcp.types import MCPServerConfig


class _FakeProcess:
    def __init__(self, *, exits_on_terminate: bool = True) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_calls = 0
        self.exits_on_terminate = exits_on_terminate

    def terminate(self) -> None:
        self.terminated = True
        if self.exits_on_terminate:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            await asyncio.sleep(3600)
        return self.returncode


def _client_with_process(process: _FakeProcess) -> MCPStdioClient:
    client = MCPStdioClient(MCPServerConfig(name="demo", transport="stdio", command="demo"))
    client._process = process  # type: ignore[assignment]
    return client


@pytest.mark.asyncio
async def test_close_waits_for_terminated_stdio_process() -> None:
    process = _FakeProcess(exits_on_terminate=True)

    await _client_with_process(process).close()

    assert process.terminated is True
    assert process.killed is False
    assert process.wait_calls == 1


@pytest.mark.asyncio
async def test_close_kills_stdio_process_when_terminate_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(exits_on_terminate=False)
    client = _client_with_process(process)
    monkeypatch.setattr(client, "_CLOSE_TIMEOUT_SECONDS", 0.001)

    await client.close()

    assert process.terminated is True
    assert process.killed is True
    assert process.wait_calls == 2
