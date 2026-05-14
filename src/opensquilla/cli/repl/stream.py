"""Shared Rich streaming renderer for chat responses."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from rich.live import Live
from rich.text import Text

from opensquilla.cli.ui import ACCENT, ACCENT_SOFT, console, error_panel

# ESC-introduced terminal sequences: CSI (cursor / SGR / mode), OSC (title,
# clipboard via OSC 52, hyperlink), DCS (programmable strings), plus 2-char
# ESC sequences (e.g. ESC c full reset, ESC 7 save cursor). Stripped before
# any model text reaches the terminal so the response cannot drive the
# emulator — clear screen, hide cursor, write to clipboard, change title,
# emit DA queries that the terminal answers back as input, etc.
_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"          # CSI ... final byte
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL or ST
    r"|P[^\x1b]*\x1b\\"            # DCS ... ST
    r"|[@-Z\\-_]"                  # 2-char ESC (RIS, IND, NEL, ...)
    r")"
)
# C0 control bytes minus tab/newline; line-feed and tab are kept because
# Markdown content legitimately uses them. Carriage return is dropped
# (overwrite-line attack), as are backspace, bell, and form feed.
_C0_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _sanitize_stream_text(delta: str) -> str:
    """Strip ANSI escapes and dangerous C0 controls from streamed model text.

    The token stream is written straight to ``console.file`` so the terminal
    can render long CJK content without Live's cursor-up overflow bug. That
    bypasses Rich's Markdown layer, which previously did the escaping for us,
    so untrusted model output could otherwise execute terminal control
    sequences (OSC 52 clipboard writes, title rewrites, ``\\r`` line
    overwrites, mode toggles, DA queries that the terminal answers back as
    user input). Keep ``\\n`` and ``\\t`` since Markdown bullets and tables
    rely on them.
    """
    return _C0_RE.sub("", _ANSI_RE.sub("", delta))


@dataclass
class UsageSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    billed_cost: float = 0.0
    cost_source: str = "none"
    model: str = ""
    aggregate: bool = False

    @classmethod
    def from_done_event(cls, event: object) -> UsageSummary:
        return cls(
            input_tokens=int(getattr(event, "input_tokens", 0) or 0),
            output_tokens=int(getattr(event, "output_tokens", 0) or 0),
            reasoning_tokens=int(getattr(event, "reasoning_tokens", 0) or 0),
            cached_tokens=int(getattr(event, "cached_tokens", 0) or 0),
            cost_usd=float(getattr(event, "cost_usd", 0.0) or 0.0),
            billed_cost=float(getattr(event, "billed_cost", 0.0) or 0.0),
            cost_source=str(getattr(event, "cost_source", "none") or "none"),
            model=str(getattr(event, "model", "") or ""),
        )

    @classmethod
    def from_gateway_payload(cls, payload: dict[str, Any]) -> UsageSummary:
        return cls(
            input_tokens=int(payload.get("input_tokens") or payload.get("inputTokens") or 0),
            output_tokens=int(payload.get("output_tokens") or payload.get("outputTokens") or 0),
            reasoning_tokens=int(
                payload.get("reasoning_tokens") or payload.get("reasoningTokens") or 0
            ),
            cached_tokens=int(payload.get("cached_tokens") or payload.get("cachedTokens") or 0),
            cost_usd=float(payload.get("cost_usd") or payload.get("costUsd") or 0.0),
            billed_cost=float(payload.get("billed_cost") or payload.get("billedCost") or 0.0),
            cost_source=str(
                payload.get("cost_source") or payload.get("costSource") or "none"
            ),
            model=str(payload.get("model") or ""),
        )

    def has_values(self) -> bool:
        return bool(
            self.input_tokens
            or self.output_tokens
            or self.reasoning_tokens
            or self.cached_tokens
            or self.cost_usd
            or self.billed_cost
            or self.model
        )


@dataclass
class UsageCounter:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, usage: UsageSummary | None) -> None:
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.cached_tokens += usage.cached_tokens
        self.cost_usd += usage.cost_usd

    def reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0
        self.cost_usd = 0.0

    def render(self) -> str:
        total = self.input_tokens + self.output_tokens
        return (
            f"{total:,} tok ({self.input_tokens:,} in / {self.output_tokens:,} out)"
            f" · cache {self.cached_tokens:,}"
            f" · ${self.cost_usd:.6f}"
        )


@dataclass
class TurnResult:
    text: str = ""
    usage: UsageSummary | None = None
    error: str | None = None
    cancelled: bool = False
    artifacts: list[dict[str, Any]] | None = None
    model_after: str | None = None


def _summarize_args(name: str, args: dict | None) -> str:
    """Return a short human-readable summary of a tool call's key argument.

    Only the tool names that actually exist in the builtin registry are handled;
    all others return an empty string so unknown tools still show correctly.
    """
    if not args:
        return ""
    if name in {"exec_command", "background_process"}:
        cmd = args.get("command") or args.get("cmd") or ""
        return str(cmd)[:60] if cmd else ""
    if name == "execute_code":
        code = args.get("code") or args.get("source") or ""
        first_line = str(code).split("\n", 1)[0]
        return first_line[:60] if first_line else ""
    if name in {"read_file", "write_file", "list_dir", "apply_patch"}:
        path = (
            args.get("path")
            or args.get("file_path")
            or args.get("target")
            or ""
        )
        return str(path)[-50:] if path else ""
    if name == "web_search":
        query = args.get("query") or ""
        return str(query)[:60] if query else ""
    if name == "web_fetch":
        url = args.get("url") or args.get("uri") or ""
        return str(url)[:60] if url else ""
    return ""


class _ToolCallStrip:
    """Coalesces repeated tool calls of the same name into a summary line.

    Rules:
    - Calls 1 and 2 in a run of the same name print normally.
    - On call 3: print "· {name} ×3 (cumulative)" once; suppress further
      prints for that run while counting.
    - On name-change, finalize(), or error: if count >= 3, flush a
      "· {prev} ×{count} total {sec}s" row.
    """

    def __init__(self) -> None:
        self._pending: dict[str, tuple[str, str, float]] = {}  # id → (name, summary, start_ts)
        self._run_name: str | None = None
        self._run_count: int = 0
        self._run_start: float = 0.0
        self._coalesced: bool = False  # True once the ×3 line has been printed

    def _flush_run(self) -> None:
        if self._run_name is not None and self._run_count >= 3:
            elapsed = time.monotonic() - self._run_start
            console.print(
                f"[{ACCENT}]·[/] [dim]{self._run_name} "
                f"×{self._run_count} total {elapsed:.1f}s[/dim]"
            )
        self._run_name = None
        self._run_count = 0
        self._run_start = 0.0
        self._coalesced = False

    def record_start(self, name: str, summary: str, tool_use_id: str | None) -> None:
        ts = time.monotonic()
        tid = tool_use_id or f"_anon_{ts}"
        self._pending[tid] = (name, summary, ts)

        if self._run_name != name:
            self._flush_run()
            self._run_name = name
            self._run_count = 0
            self._run_start = ts

        self._run_count += 1

        if self._run_count <= 2:
            suffix = f" {summary}" if summary else ""
            console.print(f"[{ACCENT}]·[/] [dim]{name}{suffix}[/dim]")
        elif self._run_count == 3:
            self._coalesced = True
            console.print(
                f"[{ACCENT}]·[/] [dim]{name} ×3 (cumulative)[/dim]"
            )
        # count > 3 and already coalesced: suppress output, keep counting

    def record_finish(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None:
        entry = self._pending.pop(tool_use_id or "", None)
        if error:
            # Flush any active run, then print an error row.
            if self._run_name is not None and self._run_count >= 3:
                self._flush_run()
            name = entry[0] if entry else (tool_use_id or "tool")
            console.print(f"[red]✗[/] [dim]{name}: {error}[/dim]")

    def flush(self) -> None:
        """Call before finalizing the turn to close any open coalesced run."""
        self._flush_run()


class WaitingIndicator:
    """Small custom waiting indicator for the REPL pre-token state."""

    # kept in sync with chat.js _showThinkingIndicatorNow
    _verbs = (
        "Burrowing", "Lurking", "Scanning", "Stalking",
        "Coiling", "Striking", "Snapping", "Surfacing",
    )
    _verb_dwell_seconds = 2.5

    def __init__(self, started_at: float) -> None:
        # Owner of the wait clock is the host StreamingRenderer so the elapsed
        # counter survives a pulse() restart of the underlying Live.
        self._started = started_at

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)

    def _verb(self, elapsed: float) -> str:
        idx = int(elapsed / self._verb_dwell_seconds) % len(self._verbs)
        return self._verbs[idx]

    def __rich__(self) -> Text:
        elapsed = self._elapsed()
        return Text.assemble(
            ("· ", ACCENT),
            (self._verb(elapsed), ACCENT_SOFT),
            (f" · {elapsed:0.1f}s", "dim"),
            ("  ·  Ctrl+C cancels", "dim"),
        )


class StreamingRenderer:
    """One streaming renderer for gateway and standalone responses.

    Strategy: a transient ``Live`` waiting indicator before the first token,
    then a plain-text token stream that writes deltas straight to the
    terminal. There is no post-stream re-render — the streamed text is the
    final view, matching how Claude Code, codex, aider, and other agent
    CLIs present model output. This avoids the Rich ``Live`` + ``Markdown``
    + ``Panel`` update loop, which leaked ghost panel borders on Windows
    PowerShell and other terminals whenever the rendered height grew past
    the visible viewport (CJK width-measurement made the overflow common),
    and it also avoids the doubled output a one-shot re-render produces.
    """

    def __init__(self, *, title: str = "assistant") -> None:
        self.title = title
        self.buffer = ""
        self.started_at = time.monotonic()
        self._waiting_live: Live | None = None
        self._stream_started = False
        self._strip = _ToolCallStrip()

    def __enter__(self) -> StreamingRenderer:
        self.started_at = time.monotonic()
        self._start_waiting()
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        self.stop()
        return False

    def _start_waiting(self) -> None:
        if self._waiting_live is None:
            self._waiting_live = Live(
                WaitingIndicator(self.started_at),
                console=console,
                refresh_per_second=12,
                transient=True,
            )
            self._waiting_live.start()

    def _stop_waiting(self) -> None:
        if self._waiting_live is not None:
            self._waiting_live.stop()
            self._waiting_live = None

    def _begin_stream(self) -> None:
        """Drop the waiting indicator and print the assistant section header.

        Called the first time a text delta lands, before any plain-text write,
        so the header sits flush against the streamed content.
        """
        if self._stream_started:
            return
        self._stop_waiting()
        console.print(f"[{ACCENT_SOFT}]{self.title}[/]")
        self._stream_started = True

    def _end_stream_line(self) -> None:
        """Ensure subsequent console.print starts on a fresh line."""
        if self._stream_started and self.buffer and not self.buffer.endswith("\n"):
            console.file.write("\n")
            console.file.flush()

    def append_text(self, delta: str) -> None:
        if not delta:
            return
        safe = _sanitize_stream_text(delta)
        if not safe:
            return
        # Sanitized text becomes the source of truth for the live stream
        # and for ``TurnResult.text`` (used by ``/save`` and transcript
        # markdown), so raw model bytes that contain ANSI cannot resurface
        # via downstream consumers.
        self.buffer += safe
        self._begin_stream()
        # Write straight to the underlying stream: no Rich markup parsing
        # (model output may contain ``[bracket]`` sequences), no auto-wrap
        # cursor math, no Live repaint loop. The terminal handles wrapping.
        console.file.write(safe)
        console.file.flush()

    def pulse(self) -> None:
        """Refresh visible feedback when the stream is alive but quiet.

        Pre-token: the waiting indicator's own refresh loop keeps the elapsed
        counter alive; we just make sure it is still mounted. Mid-stream the
        arriving tokens are the progress signal, so pulse is a no-op.
        """
        if not self._stream_started:
            self._start_waiting()

    def error(self, message: str) -> None:
        self._end_stream_line()
        self.stop()
        console.print(error_panel(message))

    def status(self, message: str, *, style: str = "dim") -> None:
        self._end_stream_line()
        self._stop_waiting()
        console.print(Text(message, style=style))

    def tool_start(
        self,
        name: str,
        args: dict | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        self._end_stream_line()
        self._stop_waiting()
        summary = _summarize_args(name, args)
        self._strip.record_start(name, summary, tool_use_id)

    def tool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None:
        self._strip.record_finish(tool_use_id, success=success, elapsed=elapsed, error=error)

    def tool_call(self, name: str, args: Any | None = None) -> None:
        """Backward-compatible shim — delegates to tool_start."""
        self.tool_start(name, args if isinstance(args, dict) else None, None)

    def finalize(
        self,
        usage: UsageSummary | None = None,
        *,
        cancelled: bool = False,
        cumulative_cost: float | None = None,
    ) -> None:
        self._strip.flush()
        self._end_stream_line()
        self.stop()
        elapsed = time.monotonic() - self.started_at
        if cancelled:
            console.print("[yellow]turn cancelled[/yellow]")
        footer = self.footer(usage, elapsed, cumulative_cost=cumulative_cost)
        if footer:
            console.print(f"[dim]{footer}[/dim]")

    def footer(
        self,
        usage: UsageSummary | None,
        elapsed: float,
        *,
        cumulative_cost: float | None = None,
    ) -> str:
        parts: list[str] = []
        if usage and usage.model:
            parts.append(usage.model)
        if usage and (usage.input_tokens or usage.output_tokens):
            parts.append(f"{usage.input_tokens:,} in / {usage.output_tokens:,} out")
        if usage and usage.cached_tokens:
            parts.append(f"{usage.cached_tokens:,} cached")
        if usage and usage.reasoning_tokens:
            parts.append(f"{usage.reasoning_tokens:,} reasoning")
        if usage and usage.cost_usd:
            cost_part = f"${usage.cost_usd:.6f}"
            # ∑ marker is reserved for gateway-authoritative session totals so
            # users can distinguish "single-turn snapshot" from "session total".
            # Absent ∑ = no cumulative source (standalone mode or RPC failure).
            if cumulative_cost is not None and cumulative_cost > 0:
                cost_part += f" (∑${cumulative_cost:.6f})"
            parts.append(cost_part)
        if usage and usage.aggregate:
            parts.append("aggregate")
        parts.append(f"{elapsed:.1f}s")
        return " · ".join(parts)

    def stop(self) -> None:
        self._stop_waiting()

    def start(self) -> None:
        """Resume visible feedback after an external pause (e.g. approvals).

        If no content has streamed yet, bring back the waiting indicator so
        the user still sees that work is in progress. Once token streaming
        has begun the next ``append_text`` resumes naturally, so there is
        nothing to restart here.
        """
        if not self._stream_started:
            self._start_waiting()

    @contextmanager
    def paused(self) -> Iterator[None]:
        had_waiting = self._waiting_live is not None
        self.stop()
        try:
            yield
        finally:
            if had_waiting and not self._stream_started:
                self._start_waiting()
