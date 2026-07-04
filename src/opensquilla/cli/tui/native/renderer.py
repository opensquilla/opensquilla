"""Plain terminal stream renderer for the stable chat backend.

The renderer writes assistant output through a Rich console that has markup
enabled (so backend notices such as ``[yellow]Cancelled.[/yellow]`` keep their
styling). Model- and tool-provided text is therefore *untrusted markup*: it is
escaped here before it reaches the console so bracketed content (file paths like
``[/usr/bin]``, code, or markup-like tokens) renders literally instead of being
parsed — which would otherwise corrupt styling or raise ``MarkupError`` and tear
down the session.
"""

from __future__ import annotations

from typing import Any, Literal

from rich.markup import escape as _escape

from opensquilla.ui import ACCENT

# Map renderer-internal status styles onto Rich styles for the plain terminal.
_STATUS_STYLES = {
    "dim": "dim",
    "normal": "default",
    "warning": "yellow",
    "error": "red",
}


class NativeStreamRenderer:
    """Async renderer that writes assistant output directly to the terminal."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        del title
        self.output_handle = output_handle
        self.buffer = ""
        self._saw_output = False
        self._saw_reasoning = False
        self._reasoning_open = False
        # True when the last write left the cursor mid-line (no trailing newline),
        # e.g. streamed answer prose. Block-level rows (tool start) use it to break
        # to a fresh line so a glyph never collides with preceding text.
        self._line_open = False
        self._tool_names: dict[str, str] = {}

    def __enter__(self) -> NativeStreamRenderer:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def _write(self, payload: str) -> None:
        if not payload:
            return
        handle = self.output_handle
        if handle is None:
            return
        await handle.write_through(payload)
        self._line_open = not payload.endswith("\n")

    async def _close_reasoning(self) -> None:
        """Separate the dim reasoning section from following answer/tool output."""
        if self._reasoning_open:
            self._reasoning_open = False
            await self._write("\n")

    async def _ensure_line_start(self) -> None:
        """Break to a fresh line if the last write left the cursor mid-line."""
        if self._line_open:
            await self._write("\n")

    async def aappend_text(self, delta: str, *, presentation: str = "answer") -> None:
        del presentation
        if not delta:
            return
        await self._close_reasoning()
        # ``buffer`` is the logical assistant text consumed by ``TurnResult``;
        # keep it raw and only escape what is sent to the markup-enabled console.
        self.buffer += delta
        self._saw_output = True
        await self._write(_escape(delta))

    async def aappend_reasoning(self, delta: str) -> None:
        if not delta:
            return
        if not self._saw_reasoning:
            self._saw_reasoning = True
            self._reasoning_open = True
            await self._write("[dim]✻ Thinking[/dim]\n")
        await self._write(f"[dim]{_escape(delta)}[/dim]")

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        del args
        await self._close_reasoning()
        # Separate the tool row from any preceding answer prose that streamed
        # without a trailing newline ("I'll check…" + tool call), so the glyph
        # doesn't render on the same line as the text.
        await self._ensure_line_start()
        if tool_use_id is not None:
            self._tool_names[tool_use_id] = name
        await self._write(f"[{ACCENT}]⚙ {_escape(name)}[/]\n")

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        del result
        name = self._tool_names.pop(tool_use_id, None) if tool_use_id is not None else None
        label = f" {_escape(name)}" if name else ""
        took = f" [dim]({elapsed:.1f}s)[/dim]" if elapsed is not None else ""
        if success:
            await self._write(f"[dim]  ✓{label}[/dim]{took}\n")
            return
        detail = _escape(error or "failed")
        await self._write(f"[red]  ✗{label}: {detail}[/red]{took}\n")

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        if not message:
            return
        await self._close_reasoning()
        rich_style = _STATUS_STYLES.get(style, "dim")
        await self._write(f"[{rich_style}]{_escape(message)}[/{rich_style}]\n")

    async def aerror(self, message: str) -> None:
        await self._close_reasoning()
        await self._write(f"\n[red]{_escape(message)}[/red]\n")

    def pulse(self) -> None:
        """Heartbeat tick for long, quiet turns.

        The plain terminal renderer has no live region to refresh, so this is a
        no-op. It exists because the shared turn-stream loop calls ``pulse()``
        unconditionally on every ``RunHeartbeatEvent``; without it a turn that
        stays quiet past the heartbeat interval would raise ``AttributeError``
        and tear down the chat session.
        """
        return None

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        del usage
        await self._close_reasoning()
        if cancelled:
            await self._write("\n[yellow]✋ Cancelled[/yellow]\n")
            return
        if self._saw_output:
            await self._write("\n")

    async def aclose(self) -> None:
        return None
