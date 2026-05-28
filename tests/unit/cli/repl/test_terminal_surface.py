from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from opensquilla.engine.commands import Surface


async def test_terminal_surface_wraps_existing_interactive_session(monkeypatch) -> None:
    yielded: list[dict[str, Any]] = []
    redraw_count: list[int] = []

    class _FakePromptApp:
        def invalidate(self) -> None:
            redraw_count.append(1)

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return None

        def invalidate(self) -> None:
            _FakePromptApp().invalidate()

    @asynccontextmanager
    async def _fake_session(**kwargs: Any) -> AsyncIterator[_FakeHandle]:
        yielded.append(kwargs)
        yield _FakeHandle()

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_surface.interactive_session",
        _fake_session,
    )

    from opensquilla.cli.repl.terminal_surface import open_terminal_surface

    async with open_terminal_surface(
        surface=Surface.CLI_STANDALONE,
        model="model-a",
        session_id="session-a",
    ) as tui_surface:
        assert await tui_surface.next_line() is None
        tui_surface.redraw_callback()

    assert yielded == [
        {
            "surface": Surface.CLI_STANDALONE,
            "model": "model-a",
            "session_id": "session-a",
        }
    ]
    assert redraw_count == [1]


async def test_terminal_surface_honors_legacy_prompt_session_monkeypatch(
    monkeypatch,
) -> None:
    from opensquilla.cli.repl.terminal_surface import open_terminal_surface

    yielded: list[dict[str, Any]] = []

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return "patched"

        def invalidate(self) -> None:
            return None

    @asynccontextmanager
    async def _fake_session(**kwargs: Any) -> AsyncIterator[_FakeHandle]:
        yielded.append(kwargs)
        yield _FakeHandle()

    monkeypatch.setattr(
        "opensquilla.cli.repl.prompt.interactive_session",
        _fake_session,
    )

    def _fail_if_original_session_runs(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("open_terminal_surface used the original prompt session")

    monkeypatch.setattr(
        "opensquilla.cli.repl.prompt._get_or_create_chat_app",
        _fail_if_original_session_runs,
    )

    async with open_terminal_surface(
        surface=Surface.CLI_STANDALONE,
        model="model-a",
        session_id="session-a",
    ) as tui_surface:
        assert await tui_surface.next_line() == "patched"

    assert yielded == [
        {
            "surface": Surface.CLI_STANDALONE,
            "model": "model-a",
            "session_id": "session-a",
        }
    ]


async def test_terminal_surface_fails_fast_for_missing_output_contract() -> None:
    from opensquilla.cli.repl.terminal_surface import TerminalSurface

    class _IncompleteHandle:
        async def next_line(self) -> str | None:
            return None

        def invalidate(self) -> None:
            return None

    surface = TerminalSurface(cast(Any, _IncompleteHandle()), surface=Surface.CLI_GATEWAY)

    try:
        await surface.write_through("payload")
    except AttributeError as exc:
        assert "write_through" in str(exc)
    else:  # pragma: no cover - this is the regression being pinned
        raise AssertionError("missing TUI output contract was silently ignored")
