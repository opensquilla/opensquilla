from __future__ import annotations

import pytest

from opensquilla.skills.hub import deps


class _FakeProcess:
    def __init__(self, *, timeout: bool = False) -> None:
        self.returncode = 1
        self.timeout = timeout
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self.timeout:
            raise TimeoutError
        return b"ok\xff", b"error\xfe"

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return self.returncode


@pytest.mark.asyncio
async def test_run_reaps_process_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(timeout=True)

    async def create(*args, **kwargs):
        return process

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", create)

    assert await deps._run(["tool"], timeout=0.01) == (-1, "", "Timed out")
    assert process.killed is True
    assert process.waited is True


@pytest.mark.asyncio
async def test_run_replaces_invalid_utf8_in_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()

    async def create(*args, **kwargs):
        return process

    monkeypatch.setattr(deps.asyncio, "create_subprocess_exec", create)

    assert await deps._run(["tool"]) == (1, "ok�", "error�")
