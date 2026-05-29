"""TUI backend surface adapter for the live Textual app."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from opensquilla.cli.tui.textual.app import TextualChatApp
from opensquilla.cli.tui.textual.stream import textual_stream_output
from opensquilla.engine.commands import Surface


class TextualOutputHandle:
    """Typed output bridge over the live Textual chat app."""

    def __init__(
        self,
        app: TextualChatApp,
        *,
        approval_surface: Surface,
    ) -> None:
        self._app = app
        self.approval_surface = approval_surface
        self._toolbar: dict[str, object] = {}

    async def write_through(self, payload: str) -> None:
        self._app.append_output(payload)

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
        return textual_stream_output(self._app)

    def set_toolbar(self, key: str, value: object | None) -> None:
        if value is None:
            self._toolbar.pop(key, None)
            return
        self._toolbar[key] = value

    def invalidate(self) -> None:
        router_hud = self._toolbar.get("router_hud")
        if router_hud is not None:
            self._app.set_status(str(router_hud))
            return
        self._app.refresh_ui()


class TextualSurface:
    """Adapter exposing `TextualChatApp` through `TuiSurface`."""

    def __init__(
        self,
        app: TextualChatApp,
        *,
        approval_surface: Surface = Surface.CLI_GATEWAY,
    ) -> None:
        self._app = app
        self._output_handle = TextualOutputHandle(
            app,
            approval_surface=approval_surface,
        )

    async def next_line(self) -> str | None:
        return await self._app.next_submitted_line()

    @property
    def output_handle(self) -> TextualOutputHandle:
        return self._output_handle

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._app.refresh_ui

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._app.set_cancel_callback(cb)

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._app.set_shutdown_callback(cb)

    def emit_eof(self) -> None:
        self._app.emit_eof()

    async def write_through(self, payload: str) -> None:
        await self._output_handle.write_through(payload)


@asynccontextmanager
async def open_textual_surface(
    *,
    surface: Surface,
    model: str | None = None,
    session_id: str | None = None,
    ready_marker: str | None = "OPEN_SQUILLA_TUI_READY",
    print_ready_marker: bool = True,
) -> AsyncIterator[TextualSurface]:
    app = TextualChatApp(
        model=model,
        session_id=session_id,
        ready_marker=ready_marker,
        print_ready_marker=print_ready_marker,
    )
    run_task = asyncio.create_task(app.run_async())
    try:
        await asyncio.sleep(0)
        yield TextualSurface(app, approval_surface=surface)
    finally:
        app.exit()
        await run_task
