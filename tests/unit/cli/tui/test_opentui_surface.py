from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest

from opensquilla.cli.tui.opentui.messages import (
    HostInputCancel,
    HostInputEof,
    HostInputSubmit,
    RouterPluginState,
    ScrollbackWrite,
)
from opensquilla.cli.tui.opentui.surface import OpenTuiOutputHandle, OpenTuiSurface
from opensquilla.engine.commands import Surface


class FakeOpenTuiBridge:
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
async def test_opentui_surface_returns_submitted_lines_and_eof() -> None:
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)

    bridge.messages.put_nowait(HostInputSubmit(text="中文 prompt"))
    assert await surface.next_line() == "中文 prompt"

    bridge.messages.put_nowait(HostInputEof())
    assert await surface.next_line() is None


@pytest.mark.asyncio
async def test_opentui_surface_delegates_cancel_and_keeps_waiting() -> None:
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)
    cancelled: list[str] = []

    surface.set_cancel_callback(lambda: cancelled.append("cancel"))
    bridge.messages.put_nowait(HostInputCancel())
    bridge.messages.put_nowait(HostInputSubmit(text="after cancel"))

    assert await surface.next_line() == "after cancel"
    assert cancelled == ["cancel"]


@pytest.mark.asyncio
async def test_opentui_output_handle_writes_to_scrollback() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    await output.write_through("tool output\nfinal answer")

    assert bridge.sent == [
        (
            "scrollback.write",
            asdict(ScrollbackWrite(text="tool output\nfinal answer")),
        )
    ]


def test_opentui_output_toolbar_invalidates_router_plugin() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "route standard -> fake-terminal 99% save 42%")
    output.set_toolbar("router_hud_style", "normal")
    output.invalidate()

    assert bridge.sent == [
        (
            "router.update",
            asdict(
                RouterPluginState(
                    model="fake-terminal",
                    route="standard 99%",
                    saving="42%",
                    context="-",
                    style="normal",
                )
            ),
        )
    ]


@pytest.mark.asyncio
async def test_output_handle_send_message_forwards_to_bridge() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    await output.send_message("turn.begin", {"id": "t1"})
    await output.send_message("model.text", {"text": "hi"})

    assert bridge.sent == [
        ("turn.begin", {"id": "t1"}),
        ("model.text", {"text": "hi"}),
    ]
