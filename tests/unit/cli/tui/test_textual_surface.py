from __future__ import annotations

import asyncio

import pytest

from opensquilla.cli.tui.backend.contracts import TuiOutputHandle, TuiSurface
from opensquilla.cli.tui.textual import (
    TextualChatApp,
    TextualOutputHandle,
    TextualSurface,
)
from opensquilla.engine.commands import Surface


@pytest.mark.asyncio
async def test_textual_surface_exposes_submitted_lines_and_eof() -> None:
    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    surface = TextualSurface(app, approval_surface=Surface.CLI_GATEWAY)

    assert isinstance(surface, TuiSurface)

    app.submit_text("hello textual")

    assert await surface.next_line() == "hello textual"

    surface.emit_eof()

    assert await surface.next_line() is None


@pytest.mark.asyncio
async def test_textual_shutdown_action_delegates_eof_to_registered_callback() -> None:
    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    shutdown_calls: list[str] = []

    def _shutdown() -> None:
        shutdown_calls.append("shutdown")
        app.emit_eof()

    app.set_shutdown_callback(_shutdown)
    app.action_request_shutdown()

    assert shutdown_calls == ["shutdown"]
    assert await app.next_submitted_line() is None

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(app.next_submitted_line(), timeout=0.01)


@pytest.mark.asyncio
async def test_textual_output_handle_writes_and_streams_to_transcript() -> None:
    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    output = TextualOutputHandle(app, approval_surface=Surface.CLI_GATEWAY)

    assert isinstance(output, TuiOutputHandle)
    assert output.approval_surface is Surface.CLI_GATEWAY

    await output.write_through("one-shot payload")
    async with output.stream_output() as write:
        write("chunk-a")
        write("chunk-b")

    assert "one-shot payload" in app.transcript_text
    assert "chunk-achunk-b" in app.transcript_text


def test_textual_output_toolbar_invalidates_status() -> None:
    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    output = TextualOutputHandle(app, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "route standard -> fake-textual")
    output.set_toolbar("router_hud_style", "normal")
    output.invalidate()

    assert "route standard -> fake-textual" in app.status_text
