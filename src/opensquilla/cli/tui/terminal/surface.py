"""Terminal TUI surface adapter backed by the existing REPL application."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from opensquilla.cli.tui.terminal import prompt as terminal_prompt
from opensquilla.engine.commands import Surface

_DEFAULT_INTERACTIVE_SESSION = terminal_prompt.interactive_session
interactive_session = _DEFAULT_INTERACTIVE_SESSION


class _TerminalOutputSource(Protocol):
    async def write_through(self, payload: str) -> None: ...

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]: ...


class _TerminalSessionHandle(_TerminalOutputSource, Protocol):
    async def next_line(self) -> str | None: ...

    def invalidate(self) -> None: ...

    def set_cancel_callback(self, callback: Callable[[], None] | None) -> None: ...

    def set_shutdown_callback(self, callback: Callable[[], None] | None) -> None: ...

    def emit_eof(self) -> None: ...


class TerminalOutputHandle:
    """Typed output bridge over the current prompt-toolkit chat application."""

    def __init__(
        self,
        source: _TerminalOutputSource,
        *,
        approval_surface: Surface,
    ) -> None:
        self._source = source
        self.approval_surface = approval_surface

    async def write_through(self, payload: str) -> None:
        await self._source.write_through(payload)

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
        return self._source.stream_output()


class TerminalSurface:
    """Adapter exposing `InteractiveSessionHandle` through `TuiSurface`."""

    def __init__(
        self,
        handle: _TerminalSessionHandle,
        *,
        surface: Surface = Surface.CLI_GATEWAY,
    ) -> None:
        self._handle = handle
        self._surface = surface

    async def next_line(self) -> str | None:
        return await self._handle.next_line()

    @property
    def output_handle(self) -> TerminalOutputHandle:
        return TerminalOutputHandle(
            self._handle,
            approval_surface=self._surface,
        )

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._handle.invalidate

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._handle.set_cancel_callback(cb)

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._handle.set_shutdown_callback(cb)

    def emit_eof(self) -> None:
        self._handle.emit_eof()

    async def write_through(self, payload: str) -> None:
        await self._handle.write_through(payload)


@asynccontextmanager
async def open_terminal_surface(
    *,
    surface: Surface,
    model: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[TerminalSurface]:
    session_factory = interactive_session
    if session_factory is _DEFAULT_INTERACTIVE_SESSION:
        session_factory = terminal_prompt.interactive_session

    async with session_factory(
        surface=surface,
        model=model,
        session_id=session_id,
    ) as handle:
        yield TerminalSurface(handle, surface=surface)
