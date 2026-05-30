"""Structured-message renderer for the OpenTUI footer backend.

Mirrors the ``TerminalRenderer`` async protocol but, instead of formatting
content into Rich text, emits one structured timeline message per call so the
JS host can render each block by type. The renderer's lifetime equals one turn,
so turn.begin/status/end are driven by enter/method-calls/afinalize.
"""

from __future__ import annotations

from dataclasses import asdict
from itertools import count
from typing import Any, Literal

from opensquilla.cli.tui.opentui.messages import (
    AnswerText,
    ModelText,
    ToolCall,
    ToolDetail,
    TurnBegin,
    TurnEnd,
    TurnStatusState,
    Usage,
)
from opensquilla.cli.tui.terminal.stream import _summarize_args, _summarize_result

_turn_ids = count(1)


class OpenTuiStreamRenderer:
    """Async renderer that emits structured OpenTUI timeline messages."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        self.title = title
        self.output_handle = output_handle
        self.buffer = ""
        self._turn_id = ""
        self._began = False
        self._saw_output = False
        self._tool_calls: dict[str, tuple[str, str]] = {}

    async def _emit(self, message_type: str, payload: Any) -> None:
        await self._emit_raw(message_type, asdict(payload))

    async def _emit_raw(self, message_type: str, payload: dict[str, Any]) -> None:
        handle = self.output_handle
        if handle is None:
            return
        send = getattr(handle, "send_message", None)
        if send is None:
            return
        await send(message_type, payload)

    async def _ensure_begin(self) -> None:
        if self._began:
            return
        self._began = True
        self._turn_id = f"t{next(_turn_ids)}"
        await self._emit("turn.begin", TurnBegin(id=self._turn_id))
        await self._emit(
            "turn.status", TurnStatusState(phase="thinking", label="thinking", active=True)
        )
        await self._emit_raw("composer.set", {"disabled": True})

    def __enter__(self) -> OpenTuiStreamRenderer:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def pulse(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def start(self) -> None:
        return None

    async def aappend_text(self, delta: str) -> None:
        if not delta:
            return
        await self._ensure_begin()
        if not self._saw_output:
            self._saw_output = True
            await self._emit(
                "turn.status", TurnStatusState(phase="output", label="output", active=True)
            )
        self.buffer += delta
        await self._emit("answer.text", AnswerText(text=delta))

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        await self._ensure_begin()
        await self._emit("model.text", ModelText(text=message))

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        await self._ensure_begin()
        summary = _summarize_args(name, args)
        if tool_use_id:
            self._tool_calls[tool_use_id] = (name, summary)
        await self._emit(
            "turn.status", TurnStatusState(phase="tool", label=name, active=True)
        )
        await self._emit(
            "tool.call",
            ToolCall(name=name, summary=summary, status="running", id=tool_use_id),
        )

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        name, summary = self._tool_calls.get(tool_use_id or "", ("", ""))
        await self._emit(
            "tool.call",
            ToolCall(
                name=name,
                summary=summary,
                status="ok" if success else "error",
                id=tool_use_id,
            ),
        )
        if not success and error:
            detail = _summarize_result(error)
        else:
            detail = _summarize_result(result)
        if detail:
            await self._emit("tool.detail", ToolDetail(text=detail))

    async def aerror(self, message: str) -> None:
        await self._ensure_begin()
        await self._emit("tool.detail", ToolDetail(text=message))

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        await self._ensure_begin()
        # turn.end closes the answer card (JS draws the bottom border) BEFORE
        # the usage line, so usage renders outside/below the card frame.
        await self._emit("turn.end", TurnEnd(id=self._turn_id, cancelled=cancelled))
        await self._emit("usage", Usage(text=_format_usage(usage)))
        await self._emit(
            "turn.status", TurnStatusState(phase="idle", label="ready", active=False)
        )
        await self._emit_raw("composer.set", {"disabled": False})

    async def aclose(self) -> None:
        return None


def _format_usage(usage: Any) -> str:
    model = getattr(usage, "model", None)
    in_tok = getattr(usage, "input_tokens", None)
    out_tok = getattr(usage, "output_tokens", None)
    parts: list[str] = []
    if in_tok is not None or out_tok is not None:
        parts.append(f"in {in_tok or 0} / out {out_tok or 0}")
    if model:
        parts.append(str(model))
    return " · ".join(parts) if parts else "done"
