"""Live Textual chat application shell."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Literal

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Paste
from textual.geometry import Region
from textual.widgets import Input, RichLog, Static

CHAT_INPUT_PLACEHOLDER = "输入消息 / Type a message"
ROUTER_HUD_DEFAULT = "Router: pending"
USER_ECHO_LABEL = "你 / you"

TextualOutputKind = Literal[
    "empty",
    "ready",
    "user_label",
    "user_text",
    "assistant_label",
    "assistant_text",
    "thinking",
    "tool_call",
    "tool_detail",
    "usage",
    "error",
]

_OUTPUT_STYLE: dict[TextualOutputKind, str] = {
    "empty": "",
    "ready": "dim #8290a3",
    "user_label": "#ff8a4c bold",
    "user_text": "#ffd08a",
    "assistant_label": "#e7edf4 bold",
    "assistant_text": "#e7edf4",
    "thinking": "italic #c9964b",
    "tool_call": "bold #38bdf8",
    "tool_detail": "dim #7d8794",
    "usage": "dim #8fa0b2",
    "error": "bold #ef6461",
}

_ERROR_RE = re.compile(r"(?:^|[\s:])(error|failed|exception|traceback|denied)\b|✗", re.I)
_THINKING_RE = re.compile(r"\b(thinking|reasoning|analy[sz]ing|plan|router|route)\b", re.I)
_TOOL_CALL_RE = re.compile(
    r"^\s*▸|(?:^|\s)(?:tool_call|tool call|function_call|fake_tool|approval requested)\b",
    re.I,
)
_TOOL_DETAIL_RE = re.compile(
    r"\b(tool_output|tool output|stdout|stderr)\b|\b\d+\s+lines?\b|^[│|]",
    re.I,
)
_USAGE_RE = re.compile(
    r"^\d+\s+in\s*/\s*\d+\s+out$|"
    r"\b\d+(?:\.\d+)?s\b|"
    r"\b(tokens?|cost|spent|save\s+\d+(?:\.\d+)?%)\b",
    re.I,
)
_ROUTER_MODEL_RE = re.compile(r"->\s*(?P<model>[^\s|]+)")
_ROUTER_SAVE_RE = re.compile(r"\bsave\s+(?P<save>\d+(?:\.\d+)?%)", re.I)
_PERCENT_RE = re.compile(r"(?P<percent>\d+(?:\.\d+)?%)")


def normalize_pasted_chat_text(text: str) -> str:
    """Flatten terminal paste payloads for the single-line chat composer."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(part.strip() for part in normalized.split("\n") if part.strip())


def normalize_textual_output_payload(payload: str) -> str:
    """Trim Rich console right-padding before writing into Textual panels."""
    cleaned: list[str] = []
    for line in payload.splitlines(keepends=True):
        if line.endswith("\r\n"):
            cleaned.append(f"{line[:-2].rstrip()}\r\n")
        elif line.endswith("\n"):
            cleaned.append(f"{line[:-1].rstrip()}\n")
        else:
            cleaned.append(line)
    return "".join(cleaned)


def classify_textual_output_line(line: str) -> TextualOutputKind:
    """Classify transcript rows so the Textual surface can draw a custom UI."""
    stripped = line.strip()
    if not stripped:
        return "empty"
    if stripped == "OPEN_SQUILLA_TUI_READY":
        return "ready"
    if stripped == USER_ECHO_LABEL:
        return "user_label"
    if stripped.startswith("◢"):
        return "assistant_label"
    if _ERROR_RE.search(stripped):
        return "error"
    if _THINKING_RE.search(stripped):
        return "thinking"
    if _TOOL_CALL_RE.search(stripped):
        return "tool_call"
    if _TOOL_DETAIL_RE.search(stripped):
        return "tool_detail"
    if _USAGE_RE.search(stripped):
        return "usage"
    return "assistant_text"


def render_textual_output_line(line: str, *, kind: TextualOutputKind | None = None) -> Text:
    """Render one transcript row with semantic color rather than raw Rich markup."""
    output_kind = kind or classify_textual_output_line(line)
    return Text(line.rstrip(), style=_OUTPUT_STYLE[output_kind])


def render_textual_output_payload(payload: str) -> list[Text]:
    """Render a transcript payload while preserving user/assistant block context."""
    payload = normalize_textual_output_payload(payload)
    rendered: list[Text] = []
    active_block: Literal["none", "user", "assistant"] = "none"
    for line in payload.splitlines():
        output_kind = classify_textual_output_line(line)
        if output_kind == "user_label":
            active_block = "user"
        elif output_kind == "assistant_label":
            active_block = "assistant"
        elif output_kind == "empty":
            active_block = "none"
        elif active_block == "user":
            output_kind = "user_text"

        rendered.append(render_textual_output_line(line, kind=output_kind))
    if payload.endswith(("\n", "\r")) and not rendered:
        rendered.append(Text(""))
    return rendered


def format_router_hud_label(label: str | None) -> str:
    """Compact router labels for the lower-right HUD capsule."""
    compact = " ".join(str(label or "").split())
    if not compact:
        return ROUTER_HUD_DEFAULT
    if compact.lower().startswith("router:"):
        return compact

    model_match = _ROUTER_MODEL_RE.search(compact)
    save_match = _ROUTER_SAVE_RE.search(compact)
    percent = _first_router_confidence(compact, save_match.group("save") if save_match else None)
    save = save_match.group("save") if save_match else None

    if model_match is None:
        return f"Router: {compact}"

    parts = [model_match.group("model")]
    if percent:
        parts.append(percent)
    if save:
        parts.append(f"save {save}")
    return f"Router: {' | '.join(parts)}"


def _first_router_confidence(compact_label: str, savings_percent: str | None) -> str | None:
    for match in _PERCENT_RE.finditer(compact_label):
        percent = match.group("percent")
        if percent != savings_percent:
            return percent
    return None


class ChatInput(Input):
    """Input that keeps CJK/multiline paste intact in Textual terminals."""

    def on_paste(self, event: Paste) -> None:
        pasted = normalize_pasted_chat_text(event.text)
        if pasted:
            self.insert_text_at_cursor(pasted)
            self.scroll_to_region(
                Region(self._cursor_offset, 0, width=1, height=1),
                force=True,
                animate=False,
            )
        event.prevent_default()
        event.stop()


class TextualChatApp(App[None]):
    """Custom Textual app surface for the backend TUI runtime."""

    BINDINGS = [
        ("ctrl+c", "cancel_turn", "Cancel"),
        ("ctrl+d", "request_shutdown", "Exit"),
    ]
    TITLE = "OpenSquilla"

    CSS = """
    Screen {
        background: #0b0f14;
        color: #e7edf4;
    }

    #shell {
        height: 100%;
        layout: vertical;
        background: #0b0f14;
    }

    #brand {
        height: 1;
        padding: 0 1;
        content-align: left middle;
        background: #10161d;
        color: #f56600;
        text-style: bold;
    }

    #workspace {
        height: 1fr;
        padding: 0 1;
        background: #0b0f14;
    }

    #transcript {
        height: 1fr;
        padding: 0 1;
        border: none;
        background: #0b0f14;
        color: #e7edf4;
        scrollbar-visibility: hidden;
    }

    #active-stream {
        height: auto;
        margin: 0;
        padding: 0 1;
        border: solid #f56600;
        background: #17110d;
        color: #ffd3b8;
    }

    #bottom-row {
        height: 3;
        padding: 0 1;
        background: #0b0f14;
    }

    #composer {
        width: 1fr;
        height: 3;
        padding: 0 1;
        border: solid #293641;
        background: #10161d;
    }

    #input-label {
        width: 9;
        content-align: left middle;
        color: #ff8a4c;
        text-style: bold;
    }

    #input {
        width: 1fr;
        height: 1;
        margin: 0;
        border: none;
        background: #10161d;
        color: #f4f7fb;
    }

    #input:focus {
        background: #10161d;
        color: #ffffff;
    }

    #router-hud {
        width: 43;
        height: 3;
        margin-left: 1;
        padding: 0 1;
        border: solid #365b48;
        background: #0d1712;
        color: #86efac;
        content-align: left middle;
    }

    #router-hud.dim {
        border: solid #293641;
        background: #10161d;
        color: #8fa0b2;
    }

    #router-hud.warning {
        border: solid #7c5f1c;
        background: #17130a;
        color: #fbbf24;
    }

    #status {
        height: 1;
        padding: 0 2;
        background: #080b0f;
        color: #8fa0b2;
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
        self._router_hud_text = ROUTER_HUD_DEFAULT
        self._router_hud_style = "dim"
        self._transcript_text = ""
        self._active_stream_text = ""
        self._status_widget: Static | None = None
        self._router_hud_widget: Static | None = None
        self._transcript_log: RichLog | None = None
        self._active_stream_widget: Static | None = None
        self._input: Input | None = None

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def router_hud_text(self) -> str:
        return self._router_hud_text

    @property
    def router_hud_style(self) -> str:
        return self._router_hud_style

    @property
    def transcript_text(self) -> str:
        return self._transcript_text

    @property
    def active_stream_text(self) -> str:
        return self._active_stream_text

    def compose(self) -> ComposeResult:
        with Container(id="shell"):
            yield Static("OpenSquilla", id="brand")
            with Vertical(id="workspace"):
                self._transcript_log = RichLog(
                    id="transcript",
                    min_width=1,
                    wrap=True,
                    highlight=False,
                    markup=False,
                )
                yield self._transcript_log
                self._active_stream_widget = Static("", id="active-stream", markup=False)
                self._active_stream_widget.display = False
                yield self._active_stream_widget
            with Horizontal(id="bottom-row"):
                with Horizontal(id="composer"):
                    yield Static(USER_ECHO_LABEL, id="input-label", markup=False)
                    self._input = ChatInput(
                        placeholder=CHAT_INPUT_PLACEHOLDER,
                        id="input",
                        select_on_focus=False,
                        compact=True,
                    )
                    yield self._input
                self._router_hud_widget = Static(
                    self._router_hud_text,
                    id="router-hud",
                    markup=False,
                )
                self._router_hud_widget.set_class(True, self._router_hud_style)
                yield self._router_hud_widget
            self._status_widget = Static(self._status_text, id="status", markup=False)
            yield self._status_widget

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
        payload = normalize_textual_output_payload(payload)
        self._transcript_text += payload
        self._write_transcript_payload(payload)

    def append_stream_output(self, payload: str) -> None:
        payload = normalize_textual_output_payload(payload)
        self._transcript_text += payload
        self._active_stream_text += payload
        if self._active_stream_widget is not None:
            self._active_stream_widget.display = True
            self._active_stream_widget.update(self._active_stream_text)
            self._active_stream_widget.refresh(layout=True)
        self.refresh(layout=True)

    def flush_stream_output(self) -> None:
        if not self._active_stream_text:
            return
        self._write_transcript_payload(self._active_stream_text)
        self._active_stream_text = ""
        if self._active_stream_widget is not None:
            self._active_stream_widget.update("")
            self._active_stream_widget.display = False
            self._active_stream_widget.refresh(layout=True)
        self.refresh(layout=True)

    def set_status(self, status: str | None = None) -> None:
        self._status_text = status if status is not None else self._initial_status()
        self.refresh_ui()

    def set_router_hud(self, label: str | None = None, *, style: str | None = None) -> None:
        self._router_hud_text = format_router_hud_label(label)
        self._router_hud_style = _normalize_router_hud_style(style) if label else "dim"
        self.refresh_ui()

    def refresh_ui(self) -> None:
        if self._status_widget is not None:
            self._status_widget.update(self._status_text)
        if self._router_hud_widget is not None:
            self._router_hud_widget.update(self._router_hud_text)
            for style_name in ("dim", "normal", "warning"):
                self._router_hud_widget.set_class(
                    style_name == self._router_hud_style,
                    style_name,
                )
        self.refresh()

    def _write_transcript_payload(self, payload: str) -> None:
        if self._transcript_log is None:
            return
        for line in render_textual_output_payload(payload):
            self._transcript_log.write(line)

    def _initial_status(self) -> str:
        model = self.model or "default model"
        session = self.session_id or "new session"
        return f"model {model} | session {session}"


def _normalize_router_hud_style(style: str | None) -> str:
    if style in {"dim", "normal", "warning"}:
        return style
    return "dim" if style is None else "normal"
