"""Tests for the OpenTUI stdout->notice capture used to keep command notices
inside the host frame instead of bleeding raw onto the terminal."""

from __future__ import annotations

import asyncio
import io
import sys
from typing import Any

import pytest

from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
from opensquilla.cli.tui.opentui.notice_capture import (
    NoticeForwardingStream,
    capture_stdout_as_notices,
    real_stderr,
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


def test_stream_keeps_only_latest_cr_frame_per_line() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("frame 1\rframe 2\rframe 3\n")

    assert lines == ["frame 3"]


def test_stream_crlf_is_a_plain_newline_even_split_across_writes() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("one\r\n")
    stream.write("two\r")
    stream.write("\nthree\n")

    assert lines == ["one", "two", "three"]


def test_stream_cr_repaints_do_not_accumulate_without_newline() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    for index in range(1000):
        stream.write(f"progress {index}\r")

    # superseded frames are dropped, not buffered for the whole session
    assert len(stream._buffer) < 64
    assert lines == []
    stream.flush()
    assert lines == ["progress 999"]


def test_stream_caps_buffer_for_newline_free_output() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("x" * 10_000)

    assert lines and lines[0].startswith("xxx")
    assert len(stream._buffer) <= 8192


def test_flush_holds_back_incomplete_escape_fragment() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("hello \x1b[3")
    stream.flush()
    # the dangling CSI prefix must not reach the host as raw control bytes
    assert lines == ["hello "]

    stream.write("1mred\x1b[0m\n")
    assert lines == ["hello ", "\x1b[31mred\x1b[0m"]


def test_flush_emits_complete_escape_sequences_verbatim() -> None:
    lines: list[str] = []
    stream = NoticeForwardingStream(lines.append)

    stream.write("\x1b[31mred\x1b[0m")
    stream.flush()

    assert lines == ["\x1b[31mred\x1b[0m"]


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


def test_capture_keeps_real_stderr_accessible_while_active() -> None:
    original_stderr = sys.stderr
    with capture_stdout_as_notices(lambda _line: None):
        assert sys.stderr is not original_stderr
        assert real_stderr() is original_stderr
    assert real_stderr() is sys.stderr


class _SendRecordingOutput:
    """Minimal handle satisfying the runtime-checkable TuiOutputHandle protocol."""

    def __init__(self) -> None:
        from opensquilla.engine.commands import Surface

        self.approval_surface = Surface.CLI_GATEWAY
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def write_through(self, payload: str) -> None:  # unused here
        raise AssertionError("notices must not go through write_through")

    def stream_output(self):  # pragma: no cover - never called
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm():
            raise AssertionError("stream_output should not be called")
            yield

        return _cm()

    async def send_message(self, message_type: str, payload: dict[str, Any]) -> None:
        self.sent.append((message_type, payload))


class _DeadBridgeOutput(_SendRecordingOutput):
    async def send_message(self, message_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("OpenTUI bridge is not started")


@pytest.mark.asyncio
async def test_forward_console_notice_sends_notice_write() -> None:
    output = _SendRecordingOutput()
    scope: dict[str, Any] = {}
    TuiOutputBinding(scope).expose(output)

    forward_console_notice(scope, "compact skipped")
    await asyncio.sleep(0)  # let the scheduled send run

    assert output.sent == [("notice.write", {"text": "compact skipped"})]


@pytest.mark.asyncio
async def test_forward_console_notice_retains_pending_task_references() -> None:
    output = _SendRecordingOutput()
    scope: dict[str, Any] = {}
    TuiOutputBinding(scope).expose(output)

    pending: set[asyncio.Task[None]] = set()
    forward_console_notice(scope, "queued line", pending_tasks=pending)

    assert len(pending) == 1
    await asyncio.gather(*pending)
    assert output.sent == [("notice.write", {"text": "queued line"})]


@pytest.mark.asyncio
async def test_forward_console_notice_without_output_falls_back_to_real_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No exposed output handle -> the line must still reach the terminal (and
    # never raise): after teardown this is the only way diagnostics survive.
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    forward_console_notice({}, "leftover diagnostic")
    await asyncio.sleep(0)

    assert "leftover diagnostic" in fake_stderr.getvalue()


@pytest.mark.asyncio
async def test_forward_console_notice_falls_back_when_bridge_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sidecar-crash sequence: the crash notice is scheduled, the bridge is
    # torn down before the task runs, and the send raises. The line must land
    # on the REAL stderr saved by the active capture, not the dead sink.
    output = _DeadBridgeOutput()
    scope: dict[str, Any] = {}
    TuiOutputBinding(scope).expose(output)

    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    with capture_stdout_as_notices(lambda _line: None):
        forward_console_notice(scope, "Input surface error: host exited with code 7")
        await asyncio.sleep(0)  # task runs while the capture is still active

    assert "Input surface error: host exited with code 7" in fake_stderr.getvalue()
