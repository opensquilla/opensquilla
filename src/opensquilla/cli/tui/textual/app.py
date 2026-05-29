"""Live Textual chat application shell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static


class TextualChatApp(App[None]):
    """Minimal Textual app surface for the backend TUI runtime."""

    BINDINGS = [
        ("ctrl+c", "cancel_turn", "Cancel"),
        ("ctrl+d", "request_shutdown", "Exit"),
    ]

    CSS = """
    #status {
        height: 1;
    }

    #transcript {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        model: str | None,
        session_id: str | None,
        ready_marker: str | None,
        print_ready_marker: bool,
    ) -> None:
        super().__init__()
        self.model = model
        self.session_id = session_id
        self.ready_marker = ready_marker
        self.print_ready_marker = print_ready_marker
        self._submitted_lines: asyncio.Queue[str | None] = asyncio.Queue()
        self._eof_emitted = False
        self._cancel_callback: Callable[[], None] | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._status_text = self._initial_status()
        self._transcript_text = ""
        self._status_widget: Static | None = None
        self._transcript_log: RichLog | None = None
        self._input: Input | None = None

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def transcript_text(self) -> str:
        return self._transcript_text

    def compose(self) -> ComposeResult:
        yield Header()
        self._status_widget = Static(self._status_text, id="status")
        yield self._status_widget
        self._transcript_log = RichLog(id="transcript", wrap=True)
        yield self._transcript_log
        self._input = Input(placeholder="you", id="input")
        yield self._input
        yield Footer()

    def on_mount(self) -> None:
        if self._input is not None:
            self._input.focus()
        if self.ready_marker:
            self.append_output(self.ready_marker)
            if self.print_ready_marker:
                print(self.ready_marker, flush=True)

    @on(Input.Submitted)
    def _handle_input_submitted(self, event: Input.Submitted) -> None:
        submitted_text = event.value
        event.input.clear()
        self.submit_text(submitted_text)

    def submit_text(self, text: str) -> None:
        self._submitted_lines.put_nowait(text)

    async def next_submitted_line(self) -> str | None:
        return await self._submitted_lines.get()

    def emit_eof(self) -> None:
        if self._eof_emitted:
            return
        self._eof_emitted = True
        self._submitted_lines.put_nowait(None)

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._cancel_callback = cb

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._shutdown_callback = cb

    def action_cancel_turn(self) -> None:
        if self._cancel_callback is not None:
            self._cancel_callback()

    def action_request_shutdown(self) -> None:
        if self._shutdown_callback is not None:
            self._shutdown_callback()
            return
        self.emit_eof()

    def append_output(self, payload: str) -> None:
        self._transcript_text += payload
        if self._transcript_log is not None:
            self._transcript_log.write(payload)

    def set_status(self, status: str | None = None) -> None:
        self._status_text = status if status is not None else self._initial_status()
        self.refresh_ui()

    def refresh_ui(self) -> None:
        if self._status_widget is not None:
            self._status_widget.update(self._status_text)
        self.refresh()

    def _initial_status(self) -> str:
        model = self.model or "default model"
        session = self.session_id or "new session"
        return f"model {model} | session {session}"
