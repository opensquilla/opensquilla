"""Structured-message renderer for the OpenTUI footer backend.

Implements the async TUI renderer protocol by emitting one structured timeline
message per call so the JS host can render each block by type. The renderer's
lifetime equals one turn, so turn.begin/status/end are driven by
enter/method-calls/afinalize, with aclose as the teardown safety net for turns
that end on an error path without reaching afinalize.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import asdict
from itertools import count
from typing import Any, Literal

from opensquilla.cli.tui.backend.directives import StreamDirectiveFilter
from opensquilla.cli.tui.backend.render_summary import summarize_args, summarize_result
from opensquilla.cli.tui.opentui.messages import (
    BlockAppend,
    BlockBegin,
    BlockEnd,
    BlockUpdate,
    TurnBegin,
    TurnEnd,
    TurnStatusState,
)

_turn_ids = count(1)


class OpenTuiStreamRenderer:
    """Async renderer that emits structured OpenTUI timeline messages."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        self.title = title
        self.output_handle = output_handle
        self.buffer = ""
        self._turn_id = ""
        self._began = False
        self._finalized = False
        # Phase currently shown on the composer pill; None after a transient
        # status label so the next delta restores the phase label.
        self._pill_phase: str | None = None
        self._block_seq = 0
        self._open_text_id: str | None = None
        self._open_text_presentation: str = "answer"
        self._open_reasoning_id: str | None = None
        self._tool_block_ids: dict[str, str] = {}
        self._last_tool_block_id: str | None = None
        self._open_tool_ids: set[str] = set()
        # Per-tool start times so atool_finished can surface a " · 0.2s" duration
        # like opencode/codex even when the caller does not pass `elapsed`.
        self._tool_start_times: dict[str, float] = {}
        # Strips [[reply_to_current]]-style routing directives from streamed
        # text; per open text block, reset on block close.
        self._directive_filter = StreamDirectiveFilter()

    async def aturn_started(self) -> None:
        """Announce the turn before the first provider event.

        The stream loop calls this right after the renderer is created, so the
        pill flips to a pulsing "thinking" the moment the user submits instead
        of the UI sitting visibly dead until the first token arrives.
        """
        await self._ensure_begin()

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
        self._set_router_session_input(None)
        self._set_router_usage(None)
        await self._emit("turn.begin", TurnBegin(id=self._turn_id))
        await self._emit(
            "turn.status", TurnStatusState(phase="thinking", label="thinking", active=True)
        )
        self._pill_phase = "thinking"
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

    def _next_block_id(self) -> str:
        self._block_seq += 1
        return f"{self._turn_id}-b{self._block_seq}"

    async def aappend_text(self, delta: str, *, presentation: str = "answer") -> None:
        if not delta:
            return
        await self._ensure_begin()
        if self._pill_phase != "output":
            # Re-emitted whenever text resumes (e.g. the final answer streaming
            # after a tool call) so the pill never sticks on a finished tool.
            self._pill_phase = "output"
            await self._emit(
                "turn.status", TurnStatusState(phase="output", label="output", active=True)
            )
        # The agent tells us, per text segment, whether it is the turn's answer
        # (-> cyan card) or intermediate narration between tool calls (-> purple ✱
        # thinking line), and we open the matching block kind from the first delta.
        # A single block never changes kind, but a call CAN switch presentation:
        # text streams live as the answer until a tool appears, after which later
        # text in the same call is intermediate (the agent streams rather than
        # buffering — see agent.py / issue #358). When that happens the open block
        # is closed and a fresh block of the new kind is opened (below), so each
        # segment stays its own correctly-typed block.
        kind = "answer" if presentation == "answer" else "thinking"
        # A reasoning stream that was open must close before assistant text.
        await self._close_reasoning()
        # If the presentation flips mid-stream, close the old block so each
        # segment is its own block of the correct kind.
        if self._open_text_id is not None and self._open_text_presentation != kind:
            await self._close_text()
        self.buffer += delta
        # Routing directives are for channel delivery, not the transcript; a
        # tag-only delta opens no block at all (blocking an empty card).
        visible = self._directive_filter.feed(delta)
        if not visible:
            return
        if self._open_text_id is None:
            self._open_text_id = self._next_block_id()
            self._open_text_presentation = kind
            await self._emit(
                "block.begin", BlockBegin(id=self._open_text_id, kind=kind, meta={})
            )
        await self._emit("block.append", BlockAppend(id=self._open_text_id, delta=visible))

    async def aappend_reasoning(self, delta: str) -> None:
        # Reasoning is the model's extended-thinking PROCESS. The first delta
        # opens a "reasoning" block whose header pulses "Thinking · Ns"; the
        # text itself streams as block.append so the host can show a live,
        # dim rolling peek of the latest reasoning lines. When the stream ends
        # the host collapses the block to a one-line "Thought for Ns" record,
        # so the process is visible while it happens without cluttering the
        # finished transcript.
        if not delta:
            return
        await self._ensure_begin()
        if self._open_reasoning_id is None:
            self._open_reasoning_id = self._next_block_id()
            await self._emit(
                "block.begin",
                BlockBegin(id=self._open_reasoning_id, kind="reasoning", meta={}),
            )
        await self._emit(
            "block.append", BlockAppend(id=self._open_reasoning_id, delta=delta)
        )

    async def _close_text(self) -> None:
        # A held tail that never completed into a directive tag is ordinary
        # text and belongs to this segment — even when the segment consisted
        # of nothing else (no block opened yet).
        tail = self._directive_filter.flush()
        self._directive_filter = StreamDirectiveFilter()
        if self._open_text_id is None and tail:
            self._open_text_id = self._next_block_id()
            await self._emit(
                "block.begin",
                BlockBegin(id=self._open_text_id, kind=self._open_text_presentation, meta={}),
            )
        if self._open_text_id is None:
            return
        block_id = self._open_text_id
        if tail:
            await self._emit("block.append", BlockAppend(id=block_id, delta=tail))
        self._open_text_id = None
        await self._emit("block.end", BlockEnd(id=block_id))

    async def _close_reasoning(self) -> None:
        if self._open_reasoning_id is None:
            return
        block_id = self._open_reasoning_id
        self._open_reasoning_id = None
        await self._emit("block.end", BlockEnd(id=block_id))

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        # Status lines carry real user-facing information (artifact saved, task
        # group progress, warnings): mirror the native backend by rendering a
        # dim in-card line, and surface the message transiently on the pill.
        # The pill phase is cleared so the next delta restores the phase label.
        await self._ensure_begin()
        text = message.strip()
        if not text:
            return
        await self._emit(
            "turn.status",
            TurnStatusState(phase=self._pill_phase or "thinking", label=text, active=True),
        )
        self._pill_phase = None
        block_id = self._next_block_id()
        await self._emit(
            "block.begin",
            BlockBegin(id=block_id, kind="status", meta={"text": text, "style": style}),
        )
        await self._emit("block.end", BlockEnd(id=block_id))

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        await self._ensure_begin()
        await self._close_reasoning()
        await self._close_text()
        summary = summarize_args(name, args)
        block_id = tool_use_id or self._next_block_id()
        if tool_use_id:
            self._tool_block_ids[tool_use_id] = block_id
        self._last_tool_block_id = block_id
        self._tool_start_times[block_id] = time.monotonic()
        await self._emit(
            "turn.status", TurnStatusState(phase="tool", label=name, active=True)
        )
        self._pill_phase = "tool"
        await self._emit(
            "block.begin",
            BlockBegin(id=block_id, kind="tool", meta={"name": name, "args": summary}),
        )
        self._open_tool_ids.add(block_id)

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        if tool_use_id:
            block_id = self._tool_block_ids.get(tool_use_id)
        else:
            block_id = self._last_tool_block_id
        if block_id is None:
            block_id = self._next_block_id()
            await self._emit(
                "block.begin", BlockBegin(id=block_id, kind="tool", meta={"name": "", "args": ""})
            )
        detail = summarize_result(error) if (not success and error) else summarize_result(result)
        if detail:
            # Collapse the result to a SINGLE preview line (the host renders one
            # "└ …" corner); join the first few non-blank lines with " · " and let
            # the host clip to width. Avoids a wall of dim text with no expander.
            lines = [line.strip() for line in detail.split("\n") if line.strip()]
            preview = " · ".join(lines[:3])[:240]
            if preview:
                await self._emit("block.append", BlockAppend(id=block_id, delta=preview))
        patch: dict[str, Any] = {"status": "ok" if success else "error"}
        start = self._tool_start_times.pop(block_id, None)
        if elapsed is None and start is not None:
            elapsed = time.monotonic() - start
        if elapsed is not None:
            patch["duration"] = f"{elapsed:.1f}s"
        await self._emit("block.update", BlockUpdate(id=block_id, patch=patch))
        await self._emit("block.end", BlockEnd(id=block_id))
        self._open_tool_ids.discard(block_id)

    async def aerror(self, message: str) -> None:
        await self._ensure_begin()
        block_id = self._next_block_id()
        await self._emit(
            "block.begin", BlockBegin(id=block_id, kind="error", meta={"text": message})
        )
        await self._emit("block.end", BlockEnd(id=block_id))

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        self._finalized = True
        await self._ensure_begin()
        await self._close_reasoning()
        await self._close_text()
        # Force-close any tool blocks still open (e.g. a turn cancelled mid-tool
        # never reaches atool_finished). They resolve to ✗: a cancelled in-flight
        # tool did not succeed, so error is the honest status.
        for block_id in list(self._open_tool_ids):
            await self._emit("block.update", BlockUpdate(id=block_id, patch={"status": "error"}))
            await self._emit("block.end", BlockEnd(id=block_id))
        self._open_tool_ids.clear()
        # Emit usage BEFORE turn.end so it attaches to the still-active turn view
        # (turn.end marks the turn ended; a later block would spawn an orphan turn).
        usage_id = self._next_block_id()
        await self._emit(
            "block.begin",
            BlockBegin(id=usage_id, kind="usage", meta={"text": _format_usage(usage)}),
        )
        await self._emit("block.end", BlockEnd(id=usage_id))
        await self._emit("turn.end", TurnEnd(id=self._turn_id, cancelled=cancelled))
        await self._emit(
            "turn.status", TurnStatusState(phase="idle", label="ready", active=False)
        )
        self._pill_phase = "idle"
        await self._emit_raw("composer.set", {"disabled": False})
        self._publish_usage_to_router_toolbar(usage)

    def _publish_usage_to_router_toolbar(self, usage: Any | None) -> None:
        # Surface this turn's token in/out in the router panel's ctx row. The
        # router panel reads its data from the output handle's toolbar and
        # repaints on invalidate(); defensively guard both methods so test
        # recording handles (which expose neither) never crash the turn.
        if usage is None:
            return
        in_tok = getattr(usage, "input_tokens", None)
        out_tok = getattr(usage, "output_tokens", None)
        if in_tok is None and out_tok is None:
            return
        self._set_router_session_input(_session_input_tokens(usage))
        self._set_router_usage(f"{_format_tokens(in_tok)}/{_format_tokens(out_tok)}")

    def _set_router_session_input(self, value: object | None) -> None:
        set_toolbar = getattr(self.output_handle, "set_toolbar", None)
        if callable(set_toolbar):
            set_toolbar("router_session_input", value)

    def _set_router_usage(self, value: object | None) -> None:
        set_toolbar = getattr(self.output_handle, "set_toolbar", None)
        if not callable(set_toolbar):
            return
        set_toolbar("router_usage", value)
        invalidate = getattr(self.output_handle, "invalidate", None)
        if callable(invalidate):
            invalidate()

    async def aclose(self) -> None:
        # The stream callers guarantee aclose via finally even on error paths
        # that never reach afinalize (provider errors, timeouts, error frames).
        # Without teardown the host pill would pulse forever, the composer
        # would stay disabled-colored, and the next turn would merge into the
        # unfinished card — so emit the minimal turn-teardown sequence here.
        if not self._began or self._finalized:
            return
        self._finalized = True
        # Best-effort: the bridge may already be gone, and teardown must never
        # mask the error that ended the turn.
        with contextlib.suppress(Exception):
            await self._close_reasoning()
            await self._close_text()
            for block_id in list(self._open_tool_ids):
                await self._emit(
                    "block.update", BlockUpdate(id=block_id, patch={"status": "error"})
                )
                await self._emit("block.end", BlockEnd(id=block_id))
            self._open_tool_ids.clear()
            await self._emit("turn.end", TurnEnd(id=self._turn_id))
            await self._emit(
                "turn.status", TurnStatusState(phase="idle", label="ready", active=False)
            )
            self._pill_phase = "idle"
            await self._emit_raw("composer.set", {"disabled": False})


def _format_tokens(value: Any) -> str:
    count = int(value or 0)
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def _session_input_tokens(usage: Any) -> Any | None:
    session_totals = getattr(usage, "session_totals", None)
    if session_totals is None:
        return None
    return getattr(session_totals, "input_tokens", None)


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
