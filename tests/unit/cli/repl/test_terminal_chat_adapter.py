from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from opensquilla.cli.repl.terminal_chat_adapter import (
    clear_current_cancel,
    echo_user_input,
    get_tui_output,
    map_slash_category,
    run_terminal_chat_runtime,
)
from opensquilla.cli.tui.contracts import TuiInputKind
from opensquilla.engine.commands import Surface


class _FakeSurface:
    def __init__(
        self,
        inputs: asyncio.Queue[str | None],
        writes: list[str] | None = None,
        output_handle: object | None = None,
    ) -> None:
        self._inputs = inputs
        self._writes = writes if writes is not None else []
        self._output_handle = output_handle
        self.cancel_callbacks: list[Any] = []
        self.shutdown_callbacks: list[Any] = []
        self.redraw_count = 0

    async def next_line(self) -> str | None:
        return await self._inputs.get()

    def set_cancel_callback(self, cb) -> None:  # noqa: ANN001
        self.cancel_callbacks.append(cb)

    def set_shutdown_callback(self, cb) -> None:  # noqa: ANN001
        self.shutdown_callbacks.append(cb)

    def emit_eof(self) -> None:
        self._inputs.put_nowait(None)

    async def write_through(self, payload: str) -> None:
        self._writes.append(payload)

    @property
    def output_handle(self) -> object | None:
        return self._output_handle

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._redraw

    def _redraw(self) -> None:
        self.redraw_count += 1


class _FakeOutputHandle:
    approval_surface = Surface.CLI_GATEWAY

    async def write_through(self, payload: str) -> None:
        return None

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


def test_map_slash_category_keeps_runtime_independent_from_slash_policy() -> None:
    from opensquilla.cli.repl.slash_policy import SlashCategory

    assert map_slash_category(SlashCategory.DESTRUCTIVE) is TuiInputKind.DESTRUCTIVE
    assert map_slash_category(SlashCategory.EXIT) is TuiInputKind.EXIT
    assert map_slash_category(SlashCategory.NON_SLASH) is TuiInputKind.NORMAL
    assert map_slash_category(SlashCategory.PURE_INFO) is TuiInputKind.NORMAL
    assert map_slash_category(SlashCategory.STATE_MUTATION) is TuiInputKind.NORMAL


@pytest.mark.asyncio
async def test_echo_user_input_uses_surface_write_through_not_raw_application() -> None:
    writes: list[str] = []

    class _Surface:
        async def next_line(self) -> str | None:
            return None

        def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
            return None

        def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
            return None

        def emit_eof(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            writes.append(payload)

        @property
        def redraw_callback(self) -> Callable[[], None]:
            return lambda: None

    await echo_user_input(_Surface(), "hello")

    assert writes
    assert "hello" in writes[0]


@pytest.mark.asyncio
async def test_terminal_chat_runtime_exposes_tui_output_handle_not_raw_chat_app(
    monkeypatch,
) -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    writes: list[str] = []
    opened: list[dict[str, Any]] = []
    exposed: list[object | None] = []
    legacy_exposed: list[object | None] = []

    output_handle = _FakeOutputHandle()

    @asynccontextmanager
    async def _fake_surface(**kwargs: Any) -> AsyncIterator[_FakeSurface]:
        opened.append(kwargs)
        yield _FakeSurface(inputs, writes, output_handle)

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_surface,
    )

    async def _dispatch(user_input: str) -> bool:
        exposed.append(get_tui_output(scope))
        legacy_exposed.append(scope.get("chat_app"))
        return user_input != "/exit"

    scope: dict[str, Any] = {"model": "model-a", "session_key": "session-a"}

    task = asyncio.create_task(
        run_terminal_chat_runtime(
            surface=Surface.CLI_GATEWAY,
            scope=scope,
            dispatch=_dispatch,
            queue_max_size=8,
        )
    )

    await inputs.put("hello")
    await inputs.put("/exit")
    await asyncio.wait_for(task, timeout=2.0)

    assert opened == [
        {
            "surface": Surface.CLI_GATEWAY,
            "model": "model-a",
            "session_id": "session-a",
        }
    ]
    assert exposed == [output_handle, output_handle]
    assert legacy_exposed == [None, None]
    assert "chat_app" not in scope
    assert "tui_output" not in scope
    assert any("hello" in payload for payload in writes)


@pytest.mark.asyncio
async def test_terminal_chat_runtime_aborts_gateway_session_on_cancel(monkeypatch) -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    cancel_callbacks: list[Any] = []
    abort_calls: list[str] = []
    dispatch_started = asyncio.Event()

    @asynccontextmanager
    async def _fake_surface(**_kwargs: Any) -> AsyncIterator[_FakeSurface]:
        surface = _FakeSurface(inputs)
        original = surface.set_cancel_callback

        def _capture(cb) -> None:  # noqa: ANN001
            cancel_callbacks.append(cb)
            original(cb)

        surface.set_cancel_callback = _capture  # type: ignore[method-assign]
        yield surface

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_surface,
    )

    async def _dispatch(_user_input: str) -> bool:
        dispatch_started.set()
        await asyncio.sleep(5)
        return True

    async def _abort_active_turn() -> None:
        abort_calls.append("agent:main:test")

    task = asyncio.create_task(
        run_terminal_chat_runtime(
            surface=Surface.CLI_GATEWAY,
            scope={
                "model": None,
                "session_key": "agent:main:test",
            },
            dispatch=_dispatch,
            queue_max_size=8,
            abort_active_turn=_abort_active_turn,
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    active_cb = next(cb for cb in reversed(cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert abort_calls == ["agent:main:test"]


def test_clear_current_cancel_is_safe_outside_cancelled_task() -> None:
    clear_current_cancel()
