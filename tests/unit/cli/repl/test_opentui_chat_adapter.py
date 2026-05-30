from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from opensquilla.engine.commands import Surface


class _FakeOutputHandle:
    approval_surface = Surface.CLI_GATEWAY

    async def write_through(self, payload: str) -> None:
        return None

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


class _FakeOpenTuiSurface:
    output_handle = _FakeOutputHandle()

    def __init__(self) -> None:
        self.writes: list[str] = []

    async def next_line(self) -> str | None:
        return None

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def emit_eof(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        self.writes.append(payload)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return lambda: None


@pytest.mark.asyncio
async def test_opentui_chat_runtime_exposes_tui_output_and_reuses_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.tui.opentui import runtime as opentui_runtime

    scope: dict[str, Any] = {"model": "model-a", "session_key": "session-a"}
    captured: dict[str, Any] = {}
    fake_surface = _FakeOpenTuiSurface()

    @asynccontextmanager
    async def fake_open_opentui_surface(**kwargs: Any):
        captured["surface_kwargs"] = kwargs
        yield fake_surface

    async def fake_run_tui_runtime(**kwargs: Any):
        captured["runtime_kwargs"] = kwargs
        async with kwargs["surface_factory"]() as yielded:
            assert yielded is fake_surface
        hooks = kwargs["hooks"]
        assert not opentui_runtime.get_tui_output(scope)
        hooks.expose_surface(fake_surface)
        output = opentui_runtime.get_tui_output(scope)
        captured["output"] = output
        captured["manager"] = getattr(output, "plugin_manager", None)
        hooks.clear_exposed_surface()
        return object()

    monkeypatch.setattr(opentui_runtime, "open_opentui_surface", fake_open_opentui_surface)
    monkeypatch.setattr(opentui_runtime, "run_tui_runtime", fake_run_tui_runtime)

    async def fake_dispatch(_value: str) -> bool:
        return True

    await opentui_runtime.run_opentui_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=fake_dispatch,
        queue_max_size=8,
    )

    assert captured["surface_kwargs"] == {
        "surface": Surface.CLI_GATEWAY,
        "model": "model-a",
        "session_id": "session-a",
    }
    assert captured["runtime_kwargs"]["dispatch"] is fake_dispatch
    assert captured["runtime_kwargs"]["config"].concurrent_input_during_turn is True
    assert opentui_runtime.get_tui_output(scope) is None
    assert getattr(captured["output"], "_output_handle", None) is fake_surface.output_handle
    assert captured["manager"] is not None


@pytest.mark.asyncio
async def test_opentui_chat_runtime_uses_footer_native_echo_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.tui.adapters import terminal_chat_adapter
    from opensquilla.cli.tui.opentui import runtime as opentui_runtime

    def fail_user_echo(_text: str) -> str:
        raise AssertionError("OpenTUI echo must not call terminal Rich echo payloads")

    def fail_queued_echo() -> str:
        raise AssertionError("OpenTUI queue echo must not call terminal Rich echo payloads")

    monkeypatch.setattr(terminal_chat_adapter, "user_input_echo_payload", fail_user_echo)
    monkeypatch.setattr(terminal_chat_adapter, "queued_input_start_payload", fail_queued_echo)

    scope: dict[str, Any] = {"model": "model-a", "session_key": "session-a"}
    fake_surface = _FakeOpenTuiSurface()

    @asynccontextmanager
    async def fake_open_opentui_surface(**_kwargs: Any):
        yield fake_surface

    async def fake_run_tui_runtime(**kwargs: Any):
        hooks = kwargs["hooks"]
        await hooks.on_user_input_echo(fake_surface, "hello opentui")
        await hooks.on_user_input_echo(fake_surface, "中文输入 CJK混合ASCII")
        await hooks.on_queued_turn_start(fake_surface)
        return object()

    monkeypatch.setattr(opentui_runtime, "open_opentui_surface", fake_open_opentui_surface)
    monkeypatch.setattr(opentui_runtime, "run_tui_runtime", fake_run_tui_runtime)

    async def fake_dispatch(_value: str) -> bool:
        return True

    await opentui_runtime.run_opentui_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=fake_dispatch,
        queue_max_size=8,
    )

    joined_writes = "".join(fake_surface.writes)
    assert "你 / you" not in joined_writes
    assert "hello opentui" in joined_writes
    assert "中文输入 CJK混合ASCII" in joined_writes
    assert "running queued input" in joined_writes


@pytest.mark.asyncio
async def test_opentui_notice_writes_to_active_output_handle() -> None:
    from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
    from opensquilla.cli.tui.opentui.runtime import opentui_notice

    writes: list[str] = []

    class Output:
        approval_surface = Surface.CLI_GATEWAY

        async def write_through(self, payload: str) -> None:
            writes.append(payload)

        def stream_output(self):
            raise AssertionError("stream_output should not be called")

    scope: dict[str, Any] = {}
    TuiOutputBinding(scope).expose(Output())

    opentui_notice(scope, "[yellow]Hello[/yellow]")
    await asyncio.sleep(0)

    assert writes == ["[yellow]Hello[/yellow]"]
