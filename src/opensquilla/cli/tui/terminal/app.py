"""Long-lived prompt-toolkit Application driver for the chat REPL.

Owns a single
`prompt_toolkit.Application` per surface, exposes submitted lines through an
asyncio queue, and routes toolbar state updates through the existing
`_toolbar_context` dict in `prompt.py`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.auto_suggest import AutoSuggest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.formatted_text import HTML, to_formatted_text
from prompt_toolkit.history import FileHistory, History
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu

from opensquilla.cli.tui.terminal.paste import (
    pasted_content_summary,
    should_collapse_pasted_content,
)
from opensquilla.engine.commands import Surface


class LockedFileHistory(FileHistory):
    """FileHistory with a single-writer guard for concurrent producers.

    The chat REPL has multiple potential writers: the long-lived input task
    plus any auxiliary prompts spawned by tool flows. FileHistory.store_string
    opens, writes, and closes the file per call; without serialization two
    writers can interleave bytes on multi-threaded or yielding I/O paths.

    The guard is a threading.Lock because store_string is sync — sync I/O
    serialization is what is actually required, and a threading.Lock blocks
    at the syscall layer regardless of whether the call originates from the
    asyncio loop's thread or a worker thread. Within single-threaded asyncio
    two coroutines cannot interleave a sync call, but holding the lock makes
    the single-writer contract explicit in the API surface and guards against
    future multi-thread additions (e.g. running history writes via run_in_executor).
    """

    def __init__(self, filename) -> None:
        super().__init__(filename)
        self._write_lock = threading.Lock()

    def store_string(self, string: str) -> None:
        with self._write_lock:
            super().store_string(string)

if TYPE_CHECKING:
    from prompt_toolkit.input.base import Input
    from prompt_toolkit.output.base import Output


# Sentinel pushed onto the submit queue to signal Ctrl-D / EOF.
_EOF_SENTINEL: object = object()


# Time window for Ctrl-C double-press shutdown detection. A second
# Ctrl-C arriving within this many seconds of the previous one triggers
# the registered shutdown callback (drain + exit). Outside the window,
# Ctrl-C behaves as the existing single-press cancel-or-clear. Module-
# level so tests can monkeypatch it if they need a tighter window.
_DOUBLE_CTRL_C_WINDOW_S: float = 1.5
_ACTIVE_INPUT_PREFIX_WIDTH: int = 7


def _build_key_bindings() -> KeyBindings:
    """Key bindings shared with the legacy PromptSession driver.

    Ctrl-C clears the current buffer (matches `prompt.py:_key_bindings`).
    Ctrl-D exits the Application by emitting the EOF sentinel on the buffer's
    accept handler so the submit queue surfaces None upstream.
    Ctrl-G invokes the registered cancel callback so the chat REPL can
    cancel an in-flight turn task without tearing down the input surface.
    """
    bindings = KeyBindings()

    @bindings.add("c-c")
    def _ctrl_c(event) -> None:  # type: ignore[no-untyped-def]
        # Advertised contract (chat_cmd.py banners): "Ctrl+C cancels the
        # current turn or clears input". Invoke the registered cancel
        # callback first — when a turn is in flight the chat REPL cancels
        # it; when idle the callback is a no-op (the chat REPL guards on
        # `turn_task is None or turn_task.done()`). Either way, resetting
        # the buffer matches both advertised behaviors: a fresh prompt for
        # the next input after cancel, or clearing typed-but-unsent text
        # when idle.
        #
        # A SECOND Ctrl-C within `_DOUBLE_CTRL_C_WINDOW_S` of the
        # previous press triggers the registered shutdown callback, which
        # the chat REPL wires to drain the pending deque, finalize any
        # in-flight turn, and exit cleanly. The single-press behavior
        # (cancel + clear buffer) still runs first so the user's typed
        # text is cleared in both cases. When no shutdown callback is
        # registered the double-press detection falls back to single-
        # press behavior — there is no shutdown contract to fire.
        app = event.app
        chat_app = getattr(app, "_chat_application", None)
        if chat_app is not None:
            chat_app._invoke_cancel_callback()
            chat_app._clear_pasted_content()
        app.current_buffer.reset()
        if chat_app is not None:
            chat_app._record_ctrl_c_and_maybe_shutdown()

    @bindings.add("c-d")
    def _eof(event) -> None:  # type: ignore[no-untyped-def]
        # Signal EOF to the consumer; the Application keeps running so the
        # interactive_session() context manager owns lifecycle teardown.
        app = event.app
        chat_app = getattr(app, "_chat_application", None)
        if chat_app is not None:
            chat_app._clear_pasted_content()
            chat_app._emit_eof()
        # Reset the buffer so a fresh prompt repaints after the consumer
        # decides what to do with the EOF signal.
        event.app.current_buffer.reset()

    @bindings.add("c-g")
    def _cancel_turn(event) -> None:  # type: ignore[no-untyped-def]
        # Invoke the registered cancel callback. The chat REPL registers a
        # callable that cancels the in-flight turn task; if no callback is
        # registered this is a no-op so the binding is safe at idle.
        app = event.app
        chat_app = getattr(app, "_chat_application", None)
        if chat_app is not None:
            chat_app._invoke_cancel_callback()

    @bindings.add(Keys.BracketedPaste)
    def _bracketed_paste(event) -> None:  # type: ignore[no-untyped-def]
        app = event.app
        chat_app = getattr(app, "_chat_application", None)
        if chat_app is not None:
            chat_app._insert_pasted_content(event.current_buffer, event.data)
            return
        event.current_buffer.insert_text(event.data)

    return bindings


class ChatApplication:
    """Long-lived prompt-toolkit Application wrapping a single BufferControl.

    The Application stays attached to its event loop for the lifetime of the
    REPL surface. Submitted lines are pushed into an `asyncio.Queue` and
    yielded by `submit_iter()`. Toolbar state lives in a shared dict the
    Application's `bottom_toolbar` callable reads on every redraw, so the
    caller can mutate it via `set_toolbar(...)` without restarting the
    Application.
    """

    def __init__(
        self,
        *,
        surface: Surface = Surface.CLI_GATEWAY,
        toolbar_context: dict[str, object | None],
        bottom_toolbar,
        style=None,
        input: Input | None = None,
        output: Output | None = None,
        completer: Completer | None = None,
        auto_suggest: AutoSuggest | None = None,
        history: History | None = None,
        complete_while_typing: bool = True,
        input_header=None,
    ) -> None:
        self._surface = surface
        self._toolbar_context = toolbar_context
        self._submit_queue: asyncio.Queue[str | object] = asyncio.Queue()
        self._eof_seen = False
        # Set for the duration of the inline approval suspend window
        # (`prompt.py:prompt_approval_inline`). The output-lock acquirer
        # awaits the inverse before flushing turn-task output so concurrent
        # writes cannot collide with the inline approval `PromptSession`
        # while it owns the screen.
        self._approval_in_flight: asyncio.Event = asyncio.Event()
        # Inverse complement of `_approval_in_flight` — set when the
        # Application is idle (no approval in flight), cleared while an
        # approval owns the screen. Kept as an explicit Event (rather than
        # polling the inverse of `_approval_in_flight`) so consumers can
        # `await self._approval_idle.wait()` and yield to the event loop
        # without spinning. Starts set so the idle-by-default contract holds.
        self._approval_idle: asyncio.Event = asyncio.Event()
        self._approval_idle.set()
        # Serializes terminal write-and-flush only. Rich
        # rendering MUST happen outside this lock so panel rendering time
        # cannot starve concurrent input echo; callers render into a
        # `StringIO` first and acquire the lock for the microsecond
        # `write+flush` window. See `acquire_output` / `write_through`.
        self._output_lock: asyncio.Lock = asyncio.Lock()
        # Optional callback invoked by the Ctrl-G key binding so the chat
        # REPL can cancel an in-flight turn task without the binding needing
        # direct access to the task handle. Registered by the chat loop via
        # `set_cancel_callback`; `None` while no turn is in flight.
        self._cancel_callback: Callable[[], None] | None = None
        # Optional callback invoked when Ctrl-C is pressed twice within
        # `_DOUBLE_CTRL_C_WINDOW_S` of the previous press. The chat
        # REPL registers a callable that emits EOF on the submit queue so
        # the main loop's existing EOF path drains pending work and exits
        # cleanly. `None` falls back to single-press behavior — no double-
        # press detection runs because there is no shutdown contract.
        self._shutdown_callback: Callable[[], None] | None = None
        # Timestamp (`time.monotonic()`) of the most recent Ctrl-C press,
        # or `None` when no press has been seen this window. Used by
        # `_record_ctrl_c_and_maybe_shutdown` to decide whether the next
        # press is the "second of a double". Reset to `None` after a
        # double-press fires so a third press resets the window correctly.
        self._last_ctrl_c_at: float | None = None
        # Set while a streamed assistant turn owns one prompt-toolkit
        # terminal region. Related writes (slash output, approval resume
        # text, tool rows) reuse the same region instead of waiting behind
        # the stream's output lock and risking a deadlock before finalize.
        self._active_stream_writer: Callable[[str], None] | None = None
        # Large bracketed paste payloads are represented in the visible
        # input buffer by stable markers and expanded only when submitted.
        self._pasted_content: dict[str, str] = {}
        self._next_paste_index = 1

        self._buffer = Buffer(
            multiline=False,
            accept_handler=self._on_accept,
            completer=completer,
            auto_suggest=auto_suggest,
            history=history,
            complete_while_typing=complete_while_typing,
            enable_history_search=True,
        )

        def _toolbar_fragments():  # type: ignore[no-untyped-def]
            try:
                rendered = bottom_toolbar() if callable(bottom_toolbar) else bottom_toolbar
            except Exception:
                return []
            if rendered is None:
                return []
            return to_formatted_text(rendered)

        # Persistent left-side prompt prefix. Keep the current input row
        # identified as ``you`` even before text is typed; submitted transcript
        # rows are echoed separately by ``user_input_echo_payload``.
        from opensquilla.cli.ui import ACCENT  # noqa: PLC0415

        def _input_prefix_fragments():  # type: ignore[no-untyped-def]
            return to_formatted_text(
                HTML(
                    f"<style fg='{ACCENT}'>◢ </style>"
                    f"<style fg='{ACCENT}'><b>you</b></style>"
                    f"<style fg='{ACCENT}'>  </style>"
                )
            )

        def _input_prefix_width():  # type: ignore[no-untyped-def]
            return Dimension.exact(_ACTIVE_INPUT_PREFIX_WIDTH)

        input_window = VSplit(
            [
                Window(
                    FormattedTextControl(_input_prefix_fragments),
                    width=_input_prefix_width,
                ),
                Window(BufferControl(buffer=self._buffer), height=Dimension(min=1)),
            ]
        )
        toolbar_window = Window(
            FormattedTextControl(_toolbar_fragments),
            height=Dimension.exact(1),
            style="class:bottom-toolbar",
        )
        children: list = []
        if input_header is not None:
            def _header_fragments():  # type: ignore[no-untyped-def]
                try:
                    rendered = input_header() if callable(input_header) else input_header
                except Exception:
                    return []
                if rendered is None:
                    return []
                return to_formatted_text(rendered)

            children.append(
                Window(
                    FormattedTextControl(_header_fragments),
                    height=Dimension.exact(1),
                )
            )
        children.append(input_window)
        children.append(toolbar_window)
        root = FloatContainer(
            content=HSplit(children),
            floats=[
                Float(
                    left=_ACTIVE_INPUT_PREFIX_WIDTH,
                    ycursor=True,
                    content=CompletionsMenu(
                        max_height=8,
                        scroll_offset=1,
                        display_arrows=True,
                    ),
                )
            ],
        )
        layout = Layout(root)

        self._app: Application[None] = Application(
            layout=layout,
            key_bindings=_build_key_bindings(),
            style=style,
            full_screen=False,
            refresh_interval=0.1,
            input=input,
            output=output,
        )
        # Back-reference so key handlers can reach the ChatApplication.
        self._app._chat_application = self  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    @property
    def application(self) -> Application[None]:
        """Underlying prompt-toolkit Application (read-only handle)."""
        return self._app

    @property
    def surface(self) -> Surface:
        return self._surface

    def reset_session_state(self) -> None:
        """Reset state that belongs to one interactive-session lifetime.

        ``ChatApplication`` instances are cached per surface so prompt-toolkit
        wiring, history, and completion setup can be reused across repeated
        same-process ``interactive_session()`` entries. EOF/callback/paste
        state is different: it describes one active session and must not leak
        into the next cached use.
        """
        self._eof_seen = False
        self._cancel_callback = None
        self._shutdown_callback = None
        self._last_ctrl_c_at = None
        self._active_stream_writer = None
        self._clear_pasted_content()
        self._buffer.reset()
        self._next_paste_index = 1
        self.set_approval_in_flight(False)
        while True:
            try:
                self._submit_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def set_toolbar(self, key: str, value: str | None) -> None:
        """Mutate the shared toolbar dict in place.

        The Application's `bottom_toolbar` callable re-reads this dict on
        every redraw, so a follow-up `invalidate()` (or any user keystroke)
        will pick up the new value. Callers that need an immediate repaint
        should call `self.application.invalidate()` after this.
        """
        self._toolbar_context[key] = value

    @property
    def approval_in_flight(self) -> asyncio.Event:
        """Event surface for the output-lock acquirer.

        The Event is set for the duration of the inline approval suspend
        window and cleared on resume. The output-lock holder waits on the
        Event's "cleared" state before flushing turn-task output so writes
        cannot collide with the inline approval `PromptSession`.
        """
        return self._approval_in_flight

    def set_approval_in_flight(self, value: bool) -> None:
        """Toggle the approval-in-flight / approval-idle Event pair.

        Called by `prompt.py:prompt_approval_inline` immediately around the
        suspend/inline-session/resume window. `_approval_in_flight` and
        `_approval_idle` are kept as mirror complements: one is set iff the
        other is cleared. This lets `wait_approval_idle` block on a real
        `asyncio.Event.wait()` (set semantics) instead of polling the
        inverse of `_approval_in_flight`.
        """
        if value:
            self._approval_in_flight.set()
            self._approval_idle.clear()
        else:
            self._approval_in_flight.clear()
            self._approval_idle.set()

    async def wait_approval_idle(self) -> None:
        """Wait until no approval is in flight.

        Returns immediately when no approval is active (the idle-by-default
        contract). Used by the output-lock acquirer; kept here so the
        Event contract is owned by the Application that mutates it.
        """
        await self._approval_idle.wait()

    # ------------------------------------------------------------------ #
    # Cancel callback                                                     #
    # ------------------------------------------------------------------ #

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        """Register a callable invoked when Ctrl-G is pressed.

        The chat REPL registers a callable that cancels the in-flight turn
        task; passing `None` clears the registration so a stale binding
        cannot cancel a task that has already completed.
        """
        self._cancel_callback = cb

    def _invoke_cancel_callback(self) -> None:
        """Invoke the registered cancel callback if one is registered.

        Called from the Ctrl-G key binding; swallows any exception raised by
        the callback so a bad callback cannot kill the Application's run
        loop.
        """
        cb = self._cancel_callback
        if cb is None:
            return
        try:
            cb()
        except Exception:
            # The chat REPL surfaces its own diagnostics; the key binding
            # cannot afford to propagate exceptions or it will tear down the
            # input surface.
            pass

    # ------------------------------------------------------------------ #
    # Shutdown callback — Ctrl-C double-press                             #
    # ------------------------------------------------------------------ #

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        """Register a callable invoked on a Ctrl-C double-press.

        The chat REPL registers a callable that emits EOF on the submit
        queue so the main loop's existing EOF path drains pending work
        and finalizes any in-flight turn before exiting. Passing `None`
        clears the registration so the binding falls back to single-press
        behavior (no double-press detection runs).
        """
        self._shutdown_callback = cb

    def _invoke_shutdown_callback(self) -> None:
        """Invoke the registered shutdown callback if one is registered.

        Swallows any exception raised by the callback for the same reason
        `_invoke_cancel_callback` does — a bad callback cannot tear down
        the input surface.
        """
        cb = self._shutdown_callback
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass

    def _record_ctrl_c_and_maybe_shutdown(self) -> None:
        """Track Ctrl-C press timing; fire shutdown on the second press.

        Called from the Ctrl-C key binding AFTER the single-press cancel
        callback has fired and the input buffer has been reset, so both
        halves of the existing contract land before the shutdown path
        runs.

        Double-press detection only runs when a shutdown callback is
        registered — otherwise there is no shutdown contract to fire and
        the timestamp would just churn forever. The first press records
        `time.monotonic()`; a second press within
        `_DOUBLE_CTRL_C_WINDOW_S` of the recorded time invokes the
        shutdown callback and clears the timestamp so a third press
        resets the window (i.e. `_last_ctrl_c_at` becomes the third
        press's time, not the first press's). A late press (outside the
        window) becomes the start of a fresh window.
        """
        if self._shutdown_callback is None:
            return
        now = time.monotonic()
        last = self._last_ctrl_c_at
        if last is not None and (now - last) <= _DOUBLE_CTRL_C_WINDOW_S:
            # Second press inside the window — fire shutdown and reset
            # the window so a follow-up Ctrl-C starts a fresh pair.
            self._last_ctrl_c_at = None
            self._invoke_shutdown_callback()
            return
        # First press, or a late press outside the window — start a new
        # window from this timestamp.
        self._last_ctrl_c_at = now

    # ------------------------------------------------------------------ #
    # Output mutex                                                        #
    # ------------------------------------------------------------------ #

    @property
    def output_lock(self) -> asyncio.Lock:
        """Underlying `asyncio.Lock` for terminal write-and-flush.

        Exposed primarily for tests and advanced callers that need to
        compose the lock with custom logic. Routine callers should use
        `acquire_output()` (auto-gated on the approval-suspend window) or
        `write_through()` (full render-then-flush helper).
        """
        return self._output_lock

    @asynccontextmanager
    async def acquire_output(self):
        """Async context manager: acquire the output mutex with suspend gating.

        Contract:
          1. Awaits the output mutex.
          2. Inside the lock, awaits `wait_approval_idle()` so writes never
             collide with the inline approval `PromptSession` that owns the
             screen during the inline approval suspend window.
          3. Yields. The body MUST do write-and-flush only — Rich rendering
             belongs *outside* the lock (render into `StringIO` first) so a
             slow panel render cannot starve concurrent input echo.

        The order matters: we acquire the lock first so a concurrent writer
        cannot squeeze in between the idle wait and the lock acquisition;
        the idle wait runs while we already own the lock so we cannot let
        another writer through during the suspend window either.
        """
        async with self._output_lock:
            await self.wait_approval_idle()
            yield

    async def write_through(self, payload: str) -> None:
        """Write a pre-rendered payload to the terminal under the output lock.

        The payload is expected to be the result of rendering Rich content
        into a `StringIO` (or any other in-memory buffer) — this helper is
        the canonical "flush a rendered string to the terminal" entrypoint
        for any caller that wants the write-and-flush contract.

        Imports `console` lazily inside the function to avoid a top-level
        circular import with `cli.tui.stream`, which in turn pulls in
        `cli.tui.prompt` (which imports this module).
        """
        if not payload:
            return
        active_stream_writer = self._active_stream_writer
        if active_stream_writer is not None:
            await self.wait_approval_idle()
            if self._active_stream_writer is active_stream_writer:
                active_stream_writer(payload)
                return
        # Local import: `opensquilla.cli.ui` re-exports `console` from
        # `opensquilla.ui`. Lazy so the module-level import graph stays flat
        # and tests that monkeypatch `console.file` see the patched object.
        from prompt_toolkit.application.run_in_terminal import in_terminal  # noqa: PLC0415

        from opensquilla.cli.ui import console  # noqa: PLC0415

        async with self.acquire_output():
            if self._app.is_running:
                async with in_terminal():
                    self._app.output.write_raw(payload)
                    self._app.output.flush()
                return
            console.file.write(payload)
            console.file.flush()

    @asynccontextmanager
    async def stream_output(self):
        """Hold a single terminal region open for one streamed assistant turn.

        Token streams cannot safely enter/exit ``in_terminal()`` per chunk:
        each exit redraws the prompt and can erase a partial response line
        that has not ended with ``\n`` yet. This context hides the prompt once,
        yields a synchronous payload writer for the whole turn, and restores
        the prompt only after the renderer finalizes.
        """
        from prompt_toolkit.application.run_in_terminal import in_terminal  # noqa: PLC0415

        from opensquilla.cli.ui import console  # noqa: PLC0415

        async with self.acquire_output():
            if self._app.is_running:
                async with in_terminal():
                    def _write(payload: str) -> None:
                        if not payload:
                            return
                        self._app.output.write_raw(payload)
                        self._app.output.flush()

                    self._active_stream_writer = _write
                    try:
                        yield _write
                    finally:
                        if self._active_stream_writer is _write:
                            self._active_stream_writer = None
                    return

            def _write(payload: str) -> None:
                if not payload:
                    return
                console.file.write(payload)
                console.file.flush()

            self._active_stream_writer = _write
            try:
                yield _write
            finally:
                if self._active_stream_writer is _write:
                    self._active_stream_writer = None

    async def submit_iter(self) -> AsyncIterator[str]:
        """Yield each submitted line; terminates on Ctrl-D / EOF.

        Stops iteration when the EOF sentinel is dequeued so callers can
        write a natural `async for line in app.submit_iter():` loop.
        """
        while True:
            item = await self._submit_queue.get()
            if item is _EOF_SENTINEL:
                return
            assert isinstance(item, str)
            yield item

    async def next_line(self) -> str | None:
        """Return the next submitted line, or None on EOF.

        Mirrors the contract documented for the `interactive_session()`
        handle in `prompt.py`.
        """
        item = await self._submit_queue.get()
        if item is _EOF_SENTINEL:
            return None
        assert isinstance(item, str)
        return item

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _on_accept(self, buffer: Buffer) -> bool:
        text = self._expand_pasted_content(buffer.text)
        self._submit_queue.put_nowait(text)
        self._clear_pasted_content()
        # Returning False clears the buffer; the Application keeps running so
        # the next line can be accepted without re-entering an outer loop.
        return False

    def _insert_pasted_content(self, buffer: Buffer, text: str) -> None:
        if not should_collapse_pasted_content(text):
            buffer.insert_text(text)
            return
        marker = pasted_content_summary(text, index=self._next_paste_index)
        self._next_paste_index += 1
        self._pasted_content[marker] = text
        buffer.insert_text(marker)

    def _expand_pasted_content(self, text: str) -> str:
        for marker, content in self._pasted_content.items():
            text = text.replace(marker, content)
        return text

    def _clear_pasted_content(self) -> None:
        self._pasted_content.clear()

    def _emit_eof(self) -> None:
        if self._eof_seen:
            return
        self._eof_seen = True
        self._submit_queue.put_nowait(_EOF_SENTINEL)
