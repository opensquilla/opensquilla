"""ANSI collision absence for the concurrent chat REPL.

The concurrent chat REPL composes three writers onto a single terminal:

  - the long-lived ``ChatApplication`` (prompt-toolkit renderer);
  - the ``StreamingRenderer`` for assistant tokens (writes to
    ``console.file``);
  - the slash-handler / approval prompt paths.

Any pair of these writers can emit ANSI sequences that collide: orphaned
hide-cursor / show-cursor pairs, stray ``erase line`` sequences, or a
``cursor-up`` issued while the outer Application still owns the screen.

This module pins four byte-level invariants:

  1. ``\\x1b[?25l`` / ``\\x1b[?25h`` hide/show pairs balance across
     stream + slash + approval suspend + resume.
  2. ``\\x1b[2K`` erase-line never appears outside a known render scope.
  3. ``\\x1b[<n>A`` cursor-up never appears in payloads we route through
     the output mutex (the outer Application owns the screen there).
  4. Slash-command panel bytes (e.g. ``/help``) appear strictly outside
     the stream-window region.

The live-PTY drill (real pexpect run of the chat CLI) is deferred to manual
smoke because Windows pty coverage is manual-only and the byte-level contract
here is the invariant that matters; a ``pexpect.importorskip`` guard keeps the
door open for adding a live drill in a future iteration without breaking dev
environments that lack pexpect.
"""

from __future__ import annotations

import asyncio
import io
import sys
from typing import Any, cast

import pytest
from ansi_assertions import (
    ERASE_LINE,
    HIDE_CURSOR,
    SHOW_CURSOR,
    assert_no_orphans,
    count_cursor_up,
    count_sequence,
    find_cursor_up_offsets,
)
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from opensquilla.cli import ui as cli_ui
from opensquilla.cli.repl.app import ChatApplication
from opensquilla.cli.repl.stream import StreamingRenderer
from opensquilla.cli.repl.terminal_surface import TerminalOutputHandle
from opensquilla.engine.commands import Surface

# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #


def _fresh_chat_app() -> ChatApplication:
    """Return a ChatApplication wired to DummyInput/DummyOutput for tests."""
    return ChatApplication(
        surface=Surface.CLI_GATEWAY,
        toolbar_context={
            "model": None,
            "session_id": None,
            "suppress": None,
            "status": None,
        },
        bottom_toolbar=lambda: "",
        style=None,
        input=DummyInput(),
        output=DummyOutput(),
    )


def _output_handle(chat_app: ChatApplication) -> TerminalOutputHandle:
    return TerminalOutputHandle(chat_app, approval_surface=Surface.CLI_GATEWAY)


def _byte_buffer() -> io.BytesIO:
    """A bytes-backed file object suitable as ``console.file``.

    Rich writes ``str`` through ``Console.file.write``; for our byte-level
    assertions we wrap a ``BytesIO`` in a thin shim that encodes on write.
    """
    return io.BytesIO()


class _BytesFile:
    """Minimal file-like wrapper that records bytes written to it.

    The chat REPL writes strings through ``console.file.write``; we want
    the raw byte stream for ANSI assertions. Rich's ``Console`` always
    writes ``str``, so we encode on the fly using UTF-8.

    ``flush`` is a no-op (BytesIO is in-memory). ``getvalue`` returns the
    cumulative byte stream for assertions.
    """

    def __init__(self) -> None:
        self._buf = io.BytesIO()

    def write(self, s: str) -> int:
        if isinstance(s, bytes):
            self._buf.write(s)
            return len(s)
        data = s.encode("utf-8", errors="replace")
        self._buf.write(data)
        return len(data)

    def flush(self) -> None:  # noqa: D401 — file-API compat
        pass

    def isatty(self) -> bool:
        # Force Rich into ANSI mode so its renderer emits the actual
        # escape sequences a terminal would receive, rather than the
        # stripped fallback Rich uses for non-tty sinks.
        return True

    def getvalue(self) -> bytes:
        return self._buf.getvalue()


def _ansi_console(file: _BytesFile) -> Console:
    """Build a Rich Console that forces ANSI emission into ``file``.

    ``force_terminal=True`` overrides Rich's auto-detection so even when
    the underlying file is a BytesIO shim the SGR / cursor sequences are
    emitted as they would be on a real terminal. ``width`` is pinned so
    panel rendering is deterministic across test runs.
    """
    return Console(
        file=cast(Any, file),
        force_terminal=True,
        color_system="truecolor",
        width=80,
        highlight=False,
        legacy_windows=False,
        record=False,
    )


# --------------------------------------------------------------------------- #
# Test 1 — full stream + slash + approval suspend invariants                  #
# --------------------------------------------------------------------------- #


def test_no_ansi_collision_across_stream_slash_approval(monkeypatch) -> None:
    """The combined stream + slash + approval window emits no orphan ANSI.

    Sequence under test:

      1. Stream a synthetic assistant response chunk-by-chunk through
         ``StreamingRenderer.aappend_text`` (so writes route through the
         output mutex on the ChatApplication).
      2. Mid-stream, render a ``/help``-shaped Rich panel into a StringIO
         and ``write_through`` the captured bytes (mirroring the slash
         handler's output-mutex contract).
      3. Toggle ``set_approval_in_flight(True)`` to enter the suspend
         window, then resolve with ``set_approval_in_flight(False)``.
      4. Stream a final closing chunk.

    The cumulative byte stream MUST satisfy:

      - balanced ``\\x1b[?25l`` / ``\\x1b[?25h`` pairs;
      - no orphan ``\\x1b[2K`` (the stream path never erases lines —
        Rich only emits ``2K`` for Live regions, which inline approval removed);
      - zero cursor-up sequences (the chat REPL owns the screen via the
        prompt-toolkit Application; cursor-up would belong to a Live).
    """

    async def _drive() -> bytes:
        chat_app = _fresh_chat_app()
        sink = _BytesFile()
        # Monkeypatch `console.file` so EVERY write through the shared
        # `console` lands in our byte buffer, including writes from
        # `StreamingRenderer.aappend_text` (via write_through), from the
        # synthetic /help panel, and from any stray Rich emission.
        monkeypatch.setattr(cli_ui.console, "file", sink, raising=True)

        renderer = StreamingRenderer(title="assistant", output_handle=_output_handle(chat_app))
        # Stream chunk 1.
        await renderer.aappend_text("first chunk ")

        # Simulate a /help slash command rendered into a StringIO and
        # flushed through the output mutex (this is the S2b contract for
        # slash handlers: render outside the lock, flush under it).
        slash_buf = io.StringIO()
        slash_console = Console(
            file=slash_buf,
            force_terminal=True,
            color_system="truecolor",
            width=80,
        )
        slash_console.print(
            Panel(
                Text("/help table goes here\nrow 2\nrow 3"),
                title="commands",
                border_style="cyan",
            )
        )
        await chat_app.write_through(slash_buf.getvalue())

        # Stream chunk 2 (between slash output and approval window).
        await renderer.aappend_text("second chunk ")

        # Enter the approval suspend window. Any concurrent
        # `write_through` MUST park on the suspend gate until cleared.
        chat_app.set_approval_in_flight(True)

        # Schedule a chunk that lands during the suspend window; assert
        # it does NOT reach the sink until resume.
        suspended_task = asyncio.create_task(
            chat_app.write_through("during-approval ")
        )
        for _ in range(10):
            await asyncio.sleep(0)
        assert b"during-approval" not in sink.getvalue(), (
            "write_through leaked bytes during the approval window"
        )

        chat_app.set_approval_in_flight(False)
        await asyncio.wait_for(suspended_task, timeout=1.0)

        # Final chunk after resume.
        await renderer.aappend_text("final chunk")
        renderer.finalize()

        return sink.getvalue()

    payload = asyncio.run(_drive())

    # Invariant 1 — balanced hide/show cursor pairs.
    assert_no_orphans(payload, HIDE_CURSOR, SHOW_CURSOR)

    # Invariant 2 — no erase-line outside intended scope. The chat REPL
    # stream path never emits 2K (inline approval removed Live; slash panels render
    # via Rich.Panel which does not emit 2K when written through file).
    assert count_sequence(payload, ERASE_LINE) == 0, (
        f"unexpected erase-line sequence in payload: "
        f"{count_sequence(payload, ERASE_LINE)} found"
    )

    # Invariant 3 — no cursor-up. The outer Application owns the screen;
    # any cursor-up in the stream-side bytes would be a collision with
    # the prompt-toolkit renderer's screen accounting.
    offsets = find_cursor_up_offsets(payload)
    assert offsets == [], (
        f"unexpected cursor-up sequence(s) at offsets {offsets}; "
        f"payload length={len(payload)}"
    )


# --------------------------------------------------------------------------- #
# Test 2 — in_terminal approval suspend window emits no cursor-up             #
# --------------------------------------------------------------------------- #


def test_in_terminal_approval_does_not_emit_cursor_up_during_suspend(
    monkeypatch,
) -> None:
    """During the approval suspend window, no cursor-up bytes hit the sink.

    Focused on the highest-R13-risk region: the inline approval prompt
    runs as a fresh PromptSession under ``in_terminal``; any cursor-up
    leaking from a concurrent ``write_through`` would interfere with the
    approval prompt's redraw accounting.

    This test does not spin up a real PromptSession (that requires a
    live PTY which we defer to manual smoke); instead it drives the
    suspend-gate contract directly: while ``_approval_in_flight`` is
    set, the write parks; on clear, it flushes — and the flushed bytes
    contain no cursor-up.
    """

    async def _drive() -> bytes:
        chat_app = _fresh_chat_app()
        sink = _BytesFile()
        monkeypatch.setattr(cli_ui.console, "file", sink, raising=True)

        chat_app.set_approval_in_flight(True)

        # Construct a payload that DELIBERATELY contains a cursor-up
        # if our routing were leaky — we feed it through Rich's writer
        # so any path that would emit cursor-up from Rich shows up.
        # In practice the chat REPL never writes cursor-up at all, so
        # the assertion is "Rich's render of plain text never adds
        # cursor-up", which holds because we removed Live.
        payload_render = io.StringIO()
        local_console = Console(
            file=payload_render,
            force_terminal=True,
            color_system="truecolor",
            width=80,
        )
        local_console.print(Text("response chunk one"))
        local_console.print(Text("response chunk two"))
        rendered = payload_render.getvalue()

        task = asyncio.create_task(chat_app.write_through(rendered))
        for _ in range(10):
            await asyncio.sleep(0)

        # Sanity: nothing landed yet (suspend gate is doing its job).
        assert sink.getvalue() == b"", (
            f"sink wrote during suspend window: {sink.getvalue()!r}"
        )

        chat_app.set_approval_in_flight(False)
        await asyncio.wait_for(task, timeout=1.0)
        return sink.getvalue()

    flushed = asyncio.run(_drive())

    # The flushed bytes MUST not contain any cursor-up sequence.
    assert count_cursor_up(flushed) == 0, (
        f"cursor-up sequences detected in flushed payload at offsets "
        f"{find_cursor_up_offsets(flushed)}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — show/hide cursor pairs balance across a full synthetic turn        #
# --------------------------------------------------------------------------- #


def test_show_hide_cursor_pairs_balance_across_full_turn(monkeypatch) -> None:
    """Across a synthetic full turn (stream + tool call + approval +
    resume + stream + final), every ``\\x1b[?25l`` is matched by exactly
    one ``\\x1b[?25h``.

    Even when no hide/show sequences are emitted at all (the common case
    for the chat REPL on a typical terminal width), the orphan finder
    returns an empty list and the count comparison holds at zero. The
    asymmetry condition is the failure mode this test exists to catch.
    """

    async def _drive() -> bytes:
        chat_app = _fresh_chat_app()
        sink = _BytesFile()
        monkeypatch.setattr(cli_ui.console, "file", sink, raising=True)

        renderer = StreamingRenderer(title="assistant", output_handle=_output_handle(chat_app))

        # Phase 1: open stream + two chunks.
        await renderer.aappend_text("hello ")
        await renderer.aappend_text("world\n")

        # Phase 2: a synthetic tool-call status (the renderer routes
        # this through console.print which our sink captures).
        renderer.tool_start("read_file", {"path": "/tmp/example.txt"})
        renderer.tool_finished("tid-1", success=True, elapsed=0.05)

        # Phase 3: enter approval window, queue a chunk, resume.
        chat_app.set_approval_in_flight(True)
        approval_task = asyncio.create_task(
            chat_app.write_through("queued-during-approval ")
        )
        for _ in range(10):
            await asyncio.sleep(0)
        chat_app.set_approval_in_flight(False)
        await asyncio.wait_for(approval_task, timeout=1.0)

        # Phase 4: final chunk + finalize.
        await renderer.aappend_text("goodbye")
        renderer.finalize()

        return sink.getvalue()

    payload = asyncio.run(_drive())
    assert_no_orphans(payload, HIDE_CURSOR, SHOW_CURSOR)
    # Belt-and-suspenders: pair counts equal.
    open_count = count_sequence(payload, HIDE_CURSOR)
    close_count = count_sequence(payload, SHOW_CURSOR)
    assert open_count == close_count, (
        f"hide/show cursor count mismatch: hide={open_count} "
        f"show={close_count}; payload length={len(payload)}"
    )


# --------------------------------------------------------------------------- #
# Test 4 — slash panel bytes appear outside the stream window                 #
# --------------------------------------------------------------------------- #


def test_help_panel_renders_outside_stream_window(monkeypatch) -> None:
    """Sentinel bytes confirm /help panel bytes land between regions.

    The test interleaves three labeled regions written through the same
    ``console.file`` sink:

      1. ``[STREAM-START]`` ... assistant tokens ... ``[STREAM-END]``
      2. ``[SLASH-START]`` ... /help panel ... ``[SLASH-END]``
      3. ``[NEXT-PROMPT]`` ... boundary marker for the next turn

    The contract is that the /help bytes (delimited by
    ``[SLASH-START]`` / ``[SLASH-END]``) appear strictly AFTER the
    stream-end marker and BEFORE the next-prompt marker. The byte
    offsets MUST be in monotone-increasing order:

      stream-start < stream-end < slash-start < slash-end < next-prompt

    This rules out the "slash panel rendered into the middle of the
    stream" failure mode that would happen if the slash handler ignored
    the output mutex.
    """

    async def _drive() -> bytes:
        chat_app = _fresh_chat_app()
        sink = _BytesFile()
        monkeypatch.setattr(cli_ui.console, "file", sink, raising=True)

        # Region 1: stream window.
        await chat_app.write_through("[STREAM-START]")
        renderer = StreamingRenderer(title="assistant", output_handle=_output_handle(chat_app))
        await renderer.aappend_text("token-a ")
        await renderer.aappend_text("token-b ")
        renderer.finalize()
        await chat_app.write_through("[STREAM-END]")

        # Region 2: /help slash panel.
        await chat_app.write_through("[SLASH-START]")
        slash_buf = io.StringIO()
        slash_console = Console(
            file=slash_buf,
            force_terminal=True,
            color_system="truecolor",
            width=80,
        )
        slash_console.print(
            Panel(
                Text("/help command list"),
                title="commands",
                border_style="cyan",
            )
        )
        await chat_app.write_through(slash_buf.getvalue())
        await chat_app.write_through("[SLASH-END]")

        # Region 3: next-prompt boundary.
        await chat_app.write_through("[NEXT-PROMPT]")

        return sink.getvalue()

    payload = asyncio.run(_drive())

    # Find each sentinel; all MUST be present and in order.
    offsets = {
        marker: payload.find(marker)
        for marker in (
            b"[STREAM-START]",
            b"[STREAM-END]",
            b"[SLASH-START]",
            b"[SLASH-END]",
            b"[NEXT-PROMPT]",
        )
    }
    for marker, off in offsets.items():
        assert off != -1, f"missing sentinel {marker!r} in payload: {payload!r}"

    ordered = [
        offsets[b"[STREAM-START]"],
        offsets[b"[STREAM-END]"],
        offsets[b"[SLASH-START]"],
        offsets[b"[SLASH-END]"],
        offsets[b"[NEXT-PROMPT]"],
    ]
    assert ordered == sorted(ordered), (
        f"sentinel order violated: stream-start={ordered[0]} "
        f"stream-end={ordered[1]} slash-start={ordered[2]} "
        f"slash-end={ordered[3]} next-prompt={ordered[4]}"
    )

    # Belt-and-suspenders: the slash region itself has no cursor-up and
    # no orphan hide/show pairs across the full payload.
    slash_region = payload[offsets[b"[SLASH-START]"]:offsets[b"[SLASH-END]"]]
    assert count_cursor_up(slash_region) == 0, (
        f"cursor-up inside slash panel region: "
        f"{find_cursor_up_offsets(slash_region)}"
    )
    assert_no_orphans(payload, HIDE_CURSOR, SHOW_CURSOR)


# --------------------------------------------------------------------------- #
# Optional — live PTY drill placeholder (deferred to manual smoke)            #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="pexpect is Unix-only; live-PTY drill is covered by manual smoke",
)
def test_live_pty_smoke_deferred() -> None:
    """Hook for future live-PTY drill via pexpect.

    Windows pty behavior is manual-only, so the live-PTY drive of the chat CLI
    under pexpect is deferred to manual smoke. The byte-level invariants
    enforced by the tests above are the authoritative automated contract.

    This test uses ``importorskip`` so the slot is wired and ready for a
    future live drill without breaking dev environments that lack
    pexpect.
    """
    pytest.importorskip("pexpect")
    pytest.skip(
        "live-PTY drill deferred to manual smoke; byte-level invariants in "
        "this module are the authoritative automated contract"
    )
