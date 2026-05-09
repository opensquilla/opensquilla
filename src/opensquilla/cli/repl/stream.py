"""Shared Rich streaming renderer for chat responses."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from opensquilla.cli.ui import ACCENT, ACCENT_SOFT, console, error_panel


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
    baseline_model: str = ""
    routed_model: str = ""
    savings_usd: float = 0.0
    total_savings_usd: float = 0.0
    total_savings_pct: float = 0.0

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
            baseline_model=str(getattr(event, "baseline_model", "") or ""),
            routed_model=str(getattr(event, "routed_model", "") or ""),
            savings_usd=float(getattr(event, "savings_usd", 0.0) or 0.0),
            total_savings_usd=float(getattr(event, "total_savings_usd", 0.0) or 0.0),
            total_savings_pct=float(getattr(event, "total_savings_pct", 0.0) or 0.0),
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
            baseline_model=str(
                payload.get("baseline_model") or payload.get("baselineModel") or ""
            ),
            routed_model=str(
                payload.get("routed_model") or payload.get("routedModel") or ""
            ),
            savings_usd=float(
                payload.get("savings_usd") or payload.get("savingsUsd") or 0.0
            ),
            total_savings_usd=float(
                payload.get("total_savings_usd") or payload.get("totalSavingsUsd") or 0.0
            ),
            total_savings_pct=float(
                payload.get("total_savings_pct") or payload.get("totalSavingsPct") or 0.0
            ),
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
    total_savings_usd: float = 0.0
    baseline_model: str = ""

    def add(self, usage: UsageSummary | None) -> None:
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.cached_tokens += usage.cached_tokens
        self.cost_usd += usage.cost_usd
        self.total_savings_usd += usage.total_savings_usd
        if usage.baseline_model:
            self.baseline_model = usage.baseline_model

    def reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0
        self.cost_usd = 0.0
        self.total_savings_usd = 0.0
        self.baseline_model = ""

    def render(self) -> str:
        total = self.input_tokens + self.output_tokens
        line = (
            f"{total:,} tok ({self.input_tokens:,} in / {self.output_tokens:,} out)"
            f" · cache {self.cached_tokens:,}"
            f" · ${self.cost_usd:.6f}"
        )
        if self.total_savings_usd > 0:
            baseline_cost = self.cost_usd + self.total_savings_usd
            pct = (
                (self.total_savings_usd / baseline_cost) * 100
                if baseline_cost > 0
                else 0.0
            )
            tail = f"saved ~{pct:.0f}% vs ${baseline_cost:.6f}"
            if self.baseline_model:
                tail += f" if routed straight to {self.baseline_model}"
            line += " · " + tail
        return line


@dataclass
class TurnResult:
    text: str = ""
    usage: UsageSummary | None = None
    error: str | None = None
    cancelled: bool = False
    artifacts: list[dict[str, Any]] | None = None


class WaitingIndicator:
    """Small custom waiting indicator for the REPL pre-token state."""

    _verbs = (
        "Pondering",
        "Synthesizing",
        "Cooking",
        "Thinking",
        "Weighing",
        "Considering",
        "Brewing",
        "Sketching",
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
    """One live response renderer for gateway and standalone streams."""

    def __init__(self, *, title: str = "assistant") -> None:
        self.title = title
        self.buffer = ""
        self.started_at = time.monotonic()
        self._live: Live | None = None
        self._waiting_live: Live | None = None
        self._live_active = False

    def __enter__(self) -> StreamingRenderer:
        self.started_at = time.monotonic()
        self._waiting_live = Live(
            WaitingIndicator(self.started_at),
            console=console,
            refresh_per_second=12,
            transient=True,
        )
        self._waiting_live.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        self.stop()
        return False

    def _panel(self) -> Panel:
        content = Markdown(self.buffer) if self.buffer else ""
        return Panel(content, title=f"[{ACCENT_SOFT}]{self.title}[/]", border_style=ACCENT)

    def _ensure_live(self) -> None:
        self._stop_waiting()
        if self._live is None:
            # Manual refresh keeps the Markdown panel race-free: every paint is
            # driven by a buffer mutation on the asyncio thread, so the cursor
            # never moves up by a stale height (PowerShell + CJK exposes that).
            self._live = Live(self._panel(), console=console, auto_refresh=False)
            self._live.start()
            self._live_active = True
        elif not self._live_active:
            self._live.start()
            self._live_active = True

    def append_text(self, delta: str) -> None:
        if not delta:
            return
        self.buffer += delta
        self._ensure_live()
        assert self._live is not None
        self._live.update(self._panel(), refresh=True)

    def pulse(self) -> None:
        """Refresh visible feedback when the stream is alive but quiet."""
        if self._live is not None:
            self._ensure_live()
            assert self._live is not None
            self._live.update(self._panel(), refresh=True)
            return
        if self._waiting_live is None:
            self._waiting_live = Live(
                WaitingIndicator(self.started_at),
                console=console,
                refresh_per_second=12,
                transient=True,
            )
            self._waiting_live.start()

    def error(self, message: str) -> None:
        self.stop()
        console.print(error_panel(message))

    def status(self, message: str, *, style: str = "dim") -> None:
        self.stop()
        console.print(Text(message, style=style))

    def tool_call(self, name: str, args: Any | None = None) -> None:
        self.stop()
        suffix = f" {args}" if args else ""
        console.print(f"[{ACCENT}]tool[/] [dim]{name}{suffix}[/dim]")

    def finalize(self, usage: UsageSummary | None = None, *, cancelled: bool = False) -> None:
        self.stop()
        elapsed = time.monotonic() - self.started_at
        if cancelled:
            console.print("[yellow]turn cancelled[/yellow]")
        footer = self.footer(usage, elapsed)
        if footer:
            console.print(f"[dim]{footer}[/dim]")

    def footer(self, usage: UsageSummary | None, elapsed: float) -> str:
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
            parts.append(f"${usage.cost_usd:.6f}")
        if usage and usage.aggregate:
            parts.append("aggregate")
        parts.append(f"{elapsed:.1f}s")
        return " · ".join(parts)

    def stop(self) -> None:
        self._stop_waiting()
        if self._live is not None and self._live_active:
            self._live.stop()
            self._live_active = False

    def _stop_waiting(self) -> None:
        if self._waiting_live is not None:
            self._waiting_live.stop()
            self._waiting_live = None

    def start(self) -> None:
        if self._live is not None and not self._live_active:
            self._live.start()
            self._live_active = True

    @contextmanager
    def paused(self) -> Iterator[None]:
        was_live = self._live is not None and self._live_active
        self.stop()
        try:
            yield
        finally:
            if was_live:
                self.start()
