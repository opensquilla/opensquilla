"""Tests for the OpenTUI stdout->notice capture used to keep command notices
inside the host frame instead of bleeding raw onto the terminal."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
from opensquilla.cli.tui.opentui.notice_capture import (
    NoticeForwardingStream,
    capture_stdout_as_notices,
)
from opensquilla.cli.tui.opentui.runtime import forward_console_notice


def test_stream_forwards_only_complete_lines() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("compact")
    assert lines == []  # partial line buffered, not forwarded
    stream.write(" skipped\nnext line\npartial")
    assert lines == ["compact skipped", "next line"]
    stream.flush()
    assert lines == ["compact skipped", "next line", "partial"]


def test_stream_reports_tty_so_rich_keeps_color() -> None:
    stream = NoticeForwardingStream(lambda _line: None)
    # isatty must be True or Rich would strip the ANSI the host needs to recolor.
    assert stream.isatty() is True
    assert stream.writable() is True


def test_capture_restores_stdout_and_forwards_console_output() -> None:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    lines: list[str] = []

    from opensquilla.cli.ui import console

    with capture_stdout_as_notices(lines.append):
        assert sys.stdout is not original_stdout
        console.print("[yellow]hello world[/yellow]")

    # Restored on exit...
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    # ...and the markup was rendered out, not forwarded verbatim.
    joined = "".join(lines)
    assert "hello world" in joined
    assert "[yellow]" not in joined


def test_capture_restores_stdout_on_exception() -> None:
    original_stdout = sys.stdout
    with pytest.raises(RuntimeError):
        with capture_stdout_as_notices(lambda _line: None):
            raise RuntimeError("boom")
    assert sys.stdout is original_stdout


@pytest.mark.asyncio
async def test_forward_console_notice_sends_notice_write() -> None:
    from contextlib import asynccontextmanager

    from opensquilla.engine.commands import Surface

    sent: list[tuple[str, dict[str, Any]]] = []

    class Output:
        # Satisfy the runtime-checkable TuiOutputHandle protocol so the binding
        # returns this handle.
        approval_surface = Surface.CLI_GATEWAY

        async def write_through(self, payload: str) -> None:  # unused here
            raise AssertionError("notices must not go through write_through")

        @asynccontextmanager
        async def stream_output(self):  # pragma: no cover - never called
            raise AssertionError("stream_output should not be called")
            yield

        async def send_message(self, message_type: str, payload: dict[str, Any]) -> None:
            sent.append((message_type, payload))

    scope: dict[str, Any] = {}
    TuiOutputBinding(scope).expose(Output())

    forward_console_notice(scope, "compact skipped")
    await asyncio.sleep(0)  # let the scheduled send run

    assert sent == [("notice.write", {"text": "compact skipped"})]


@pytest.mark.asyncio
async def test_forward_console_notice_is_noop_without_output() -> None:
    # No exposed output handle -> silently drop (must never raise).
    forward_console_notice({}, "anything")
    await asyncio.sleep(0)
