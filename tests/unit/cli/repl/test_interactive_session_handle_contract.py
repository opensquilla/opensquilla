"""Contract tests for the typed session handle exposed to TUI adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from opensquilla.cli.repl.prompt import InteractiveSessionHandle
from opensquilla.engine.commands import Surface


def test_interactive_session_handle_delegates_runtime_contract() -> None:
    events: list[str] = []

    class _FakePromptApplication:
        def __init__(self) -> None:
            self.invalidations = 0

        def invalidate(self) -> None:
            self.invalidations += 1

    class _FakeApplication:
        def __init__(self) -> None:
            self.surface = Surface.CLI_STANDALONE
            self.application = _FakePromptApplication()
            self.toolbar_updates: list[tuple[str, str | None]] = []
            self.writes: list[str] = []
            self.cancel_callback: Callable[[], None] | None = None
            self.shutdown_callback: Callable[[], None] | None = None
            self.eof_emitted = False

        async def next_line(self) -> str:
            events.append("next_line")
            return "hello"

        def set_toolbar(self, key: str, value: str | None) -> None:
            self.toolbar_updates.append((key, value))

        async def write_through(self, payload: str) -> None:
            self.writes.append(payload)

        def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
            @asynccontextmanager
            async def _stream():
                events.append("stream_open")

                def _write(payload: str) -> None:
                    self.writes.append(f"stream:{payload}")

                try:
                    yield _write
                finally:
                    events.append("stream_close")

            return _stream()

        def set_cancel_callback(self, callback: Callable[[], None] | None) -> None:
            self.cancel_callback = callback

        def set_shutdown_callback(self, callback: Callable[[], None] | None) -> None:
            self.shutdown_callback = callback

        def _emit_eof(self) -> None:
            self.eof_emitted = True

    app = _FakeApplication()
    handle = InteractiveSessionHandle(app)  # type: ignore[arg-type]

    async def _drive() -> None:
        assert handle.surface is Surface.CLI_STANDALONE
        assert await handle.next_line() == "hello"
        handle.set_toolbar("status", "thinking")
        await handle.write_through("payload")
        async with handle.stream_output() as write:
            write("chunk")

    asyncio.run(_drive())
    handle.set_cancel_callback(lambda: None)
    handle.set_shutdown_callback(lambda: None)
    handle.emit_eof()
    handle.invalidate()

    assert app.toolbar_updates == [("status", "thinking")]
    assert app.writes == ["payload", "stream:chunk"]
    assert events == ["next_line", "stream_open", "stream_close"]
    assert app.cancel_callback is not None
    assert app.shutdown_callback is not None
    assert app.eof_emitted is True
    assert app.application.invalidations == 2
