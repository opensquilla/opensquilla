"""Typed bridge from REPL runtimes to the stable terminal chat adapter."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from opensquilla.cli.tui.adapters.runtime_helpers import (
    ChatRuntimeScope,
    clear_current_cancel,
    get_tui_output,
)
from opensquilla.cli.tui.backend.contracts import TuiSurface
from opensquilla.cli.tui.native.runtime import run_native_chat_runtime
from opensquilla.cli.ui import ACCENT_SOFT, console
from opensquilla.engine.commands import Surface


class NativeTerminalOutputHandle:
    approval_surface: Surface

    def __init__(self, *, approval_surface: Surface) -> None:
        self.approval_surface = approval_surface

    async def write_through(self, payload: str) -> None:
        console.print(payload, end="")

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
        return _native_stream_output()

    def set_toolbar(self, key: str, value: object | None) -> None:
        return None

    def invalidate(self) -> None:
        return None


class NativeTerminalSurface:
    def __init__(self, *, approval_surface: Surface) -> None:
        self._eof_emitted = False
        self._cancel_callback: Callable[[], None] | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._output_handle = NativeTerminalOutputHandle(
            approval_surface=approval_surface,
        )

    @property
    def output_handle(self) -> NativeTerminalOutputHandle:
        return self._output_handle

    async def next_line(self) -> str | None:
        if self._eof_emitted:
            return None
        try:
            return await asyncio.to_thread(console.input, f"[bold {ACCENT_SOFT}]>[/] ")
        except (EOFError, KeyboardInterrupt):
            self._eof_emitted = True
            if self._shutdown_callback is not None:
                self._shutdown_callback()
            return None

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._cancel_callback = cb

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._shutdown_callback = cb

    def emit_eof(self) -> None:
        self._eof_emitted = True

    async def write_through(self, payload: str) -> None:
        await self._output_handle.write_through(payload)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return lambda: None


@asynccontextmanager
async def open_native_terminal_surface(
    *,
    surface: Surface,
) -> AsyncIterator[TuiSurface]:
    yield NativeTerminalSurface(approval_surface=surface)


@asynccontextmanager
async def _native_stream_output() -> AsyncIterator[Callable[[str], None]]:
    def _write(delta: str) -> None:
        if delta:
            sys.stdout.write(delta)
            sys.stdout.flush()

    yield _write


async def run_concurrent_repl(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Run stable terminal chat without requiring OpenTUI sidecar assets."""
    await run_native_chat_runtime(
        surface=surface,
        scope=scope,
        dispatch=dispatch,
        queue_max_size=queue_max_size,
        abort_active_turn=abort_active_turn,
        surface_factory=lambda: open_native_terminal_surface(surface=surface),
    )


__all__ = [
    "ChatRuntimeScope",
    "clear_current_cancel",
    "get_tui_output",
    "open_native_terminal_surface",
    "run_concurrent_repl",
]
