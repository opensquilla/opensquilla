from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest

from opensquilla.cli.tui.adapters import native_bridge
from opensquilla.cli.tui.adapters.native_bridge import NativeTerminalSurface
from opensquilla.cli.tui.opentui.messages import HostInputEof, HostInputSubmit
from opensquilla.cli.tui.opentui.surface import OpenTuiSurface
from opensquilla.engine.commands import Surface


class _FakeOpenTuiBridge:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[tuple[str, dict[str, Any] | None]] = []

    async def send(self, message_type: str, payload: object | None = None) -> None:
        if payload is None:
            self.sent.append((message_type, None))
            return
        self.sent.append(
            (message_type, payload if isinstance(payload, dict) else asdict(payload))
        )

    async def next_message(self) -> object | None:
        return await self.messages.get()


@pytest.mark.asyncio
async def test_opentui_eof_state_is_per_surface_instance() -> None:
    bridge = _FakeOpenTuiBridge()
    first = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)

    bridge.messages.put_nowait(HostInputEof())
    assert await first.next_line() is None

    bridge.messages.put_nowait(HostInputSubmit(text="fresh input"))
    assert await first.next_line() is None

    second = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)
    assert await second.next_line() == "fresh input"


@pytest.mark.asyncio
async def test_native_eof_state_is_per_surface_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_input(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EOFError
        return "fresh input"

    monkeypatch.setattr(native_bridge.console, "input", fake_input)

    first = NativeTerminalSurface(approval_surface=Surface.CLI_GATEWAY)
    assert await first.next_line() is None
    assert await first.next_line() is None

    second = NativeTerminalSurface(approval_surface=Surface.CLI_GATEWAY)
    assert await second.next_line() == "fresh input"
