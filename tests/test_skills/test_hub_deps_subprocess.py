from __future__ import annotations

import asyncio

import pytest

from opensquilla.skills.hub import deps


class _FakeProcess:
    def __init__(self, *, timeout: bool = False) -> None:
        self.returncode = 1
        self.timeout = timeout
        self.killed = False
        self.waited = False
        self.communicate_calls = 0

    async def communicate(self):
        self.communicate_calls += 1
        if self.timeout and self.communicate_calls == 1:
            raise TimeoutError
        return b"ok\xff", b"error\xfe"

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        await asyncio.Future()
        return self.returncode


@pytest.mark.asyncio
async def test_run_drains_pipes_after_timeout_without_wait_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(timeout=True)

    async def create(*args, **kwargs):
        return process

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", create)

    result = await asyncio.wait_for(deps._run(["tool"], timeout=0.01), timeout=0.1)

    assert result == (-1, "", "Timed out")
    assert process.killed is True
    assert process.communicate_calls == 2
    assert process.waited is False


@pytest.mark.asyncio
async def test_run_replaces_invalid_utf8_in_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()

    async def create(*args, **kwargs):
        return process

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", create)

    assert await deps._run(["tool"]) == (1, "ok�", "error�")
