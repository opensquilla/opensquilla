from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli.tui.adapters import runtime_helpers
from opensquilla.cli.tui.backend.domain_events import (
    KIND_ROUTER_DECISION,
    TuiDomainEvent,
    now_ms,
)
from opensquilla.cli.tui.native import runtime as native_runtime
from opensquilla.cli.tui.native.renderer import status_markup
from opensquilla.cli.tui.plugins.router_hud import (
    ROUTER_HUD_SLOT,
    RouterHudSnapshot,
    build_router_hud_snapshot,
)
from opensquilla.engine.commands import Surface


class _FakeOutputHandle:
    approval_surface = Surface.CLI_GATEWAY

    def __init__(self) -> None:
        self.writes: list[str] = []

    async def write_through(self, payload: str) -> None:
        self.writes.append(payload)

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


class _FakeNativeSurface:
    def __init__(self) -> None:
        self.output_handle = _FakeOutputHandle()

    async def next_line(self) -> str | None:
        return None

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def emit_eof(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        await self.output_handle.write_through(payload)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return lambda: None


def _surface_factory_for(fake_surface: _FakeNativeSurface):
    @asynccontextmanager
    async def _factory() -> AsyncIterator[_FakeNativeSurface]:
        yield fake_surface

    return _factory


async def _dispatch(_value: str) -> bool:
    return True


def _router_event(payload: dict[str, object]) -> TuiDomainEvent:
    return TuiDomainEvent(
        kind=KIND_ROUTER_DECISION,
        source="gateway",
        payload=payload,
        turn_id="agent:main:test",
        timestamp_ms=now_ms(),
    )


@pytest.mark.asyncio
async def test_native_chat_runtime_exposes_tui_output_and_blocks_concurrent_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: dict[str, Any] = {"model": "model-a", "session_key": "session-a"}
    captured: dict[str, Any] = {}
    fake_surface = _FakeNativeSurface()

    async def fake_run_tui_runtime(**kwargs: Any) -> None:
        captured["runtime_kwargs"] = kwargs
        async with kwargs["surface_factory"]() as yielded:
            assert yielded is fake_surface
        captured["provider_during_run"] = scope.get("pending_input_provider")
        hooks = kwargs["hooks"]
        assert runtime_helpers.get_tui_output(scope) is None
        hooks.expose_surface(fake_surface)
        output = runtime_helpers.get_tui_output(scope)
        captured["output"] = output
        captured["manager"] = getattr(output, "plugin_manager", None)
        hooks.clear_exposed_surface()

    monkeypatch.setattr(native_runtime, "run_tui_runtime", fake_run_tui_runtime)

    await native_runtime.run_native_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=_dispatch,
        queue_max_size=8,
        surface_factory=_surface_factory_for(fake_surface),
    )

    config = captured["runtime_kwargs"]["config"]
    assert config.concurrent_input_during_turn is False
    assert config.task_name == "chat-turn-cli_gateway"
    assert config.queue_max_size == 8
    assert captured["runtime_kwargs"]["dispatch"] is _dispatch
    assert captured["provider_during_run"] is config.state
    assert "pending_input_provider" not in scope
    assert runtime_helpers.get_tui_output(scope) is None
    assert getattr(captured["output"], "_output_handle", None) is fake_surface.output_handle
    assert captured["manager"] is not None


@pytest.mark.asyncio
async def test_native_notice_before_surface_exposure_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: dict[str, Any] = {}
    fake_surface = _FakeNativeSurface()

    async def fake_run_tui_runtime(**kwargs: Any) -> None:
        kwargs["hooks"].notice("[yellow]too early[/yellow]")

    monkeypatch.setattr(native_runtime, "run_tui_runtime", fake_run_tui_runtime)

    await native_runtime.run_native_chat_runtime(
        surface=Surface.CLI_STANDALONE,
        scope=scope,
        dispatch=_dispatch,
        queue_max_size=4,
        surface_factory=_surface_factory_for(fake_surface),
    )

    assert fake_surface.output_handle.writes == []


@pytest.mark.asyncio
async def test_native_exit_notice_scheduled_without_await_is_flushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: dict[str, Any] = {}
    fake_surface = _FakeNativeSurface()

    async def fake_run_tui_runtime(**kwargs: Any) -> None:
        hooks = kwargs["hooks"]
        hooks.expose_surface(fake_surface)
        # Goodbye is emitted right before the backend returns, with no further
        # suspension point: the adapter must drain the scheduled write itself.
        hooks.notice("[yellow]Goodbye.[/yellow]")

    monkeypatch.setattr(native_runtime, "run_tui_runtime", fake_run_tui_runtime)

    await native_runtime.run_native_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=_dispatch,
        queue_max_size=8,
        surface_factory=_surface_factory_for(fake_surface),
    )

    assert fake_surface.output_handle.writes == ["[yellow]Goodbye.[/yellow]"]


@pytest.mark.asyncio
async def test_native_chat_runtime_drains_notices_and_pops_provider_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: dict[str, Any] = {}
    fake_surface = _FakeNativeSurface()

    async def fake_run_tui_runtime(**kwargs: Any) -> None:
        hooks = kwargs["hooks"]
        hooks.expose_surface(fake_surface)
        hooks.notice("[red]Input surface error[/red]")
        raise RuntimeError("surface crashed")

    monkeypatch.setattr(native_runtime, "run_tui_runtime", fake_run_tui_runtime)

    with pytest.raises(RuntimeError, match="surface crashed"):
        await native_runtime.run_native_chat_runtime(
            surface=Surface.CLI_GATEWAY,
            scope=scope,
            dispatch=_dispatch,
            queue_max_size=8,
            surface_factory=_surface_factory_for(fake_surface),
        )

    assert "pending_input_provider" not in scope
    assert fake_surface.output_handle.writes == ["[red]Input surface error[/red]"]


@pytest.mark.asyncio
async def test_native_router_decision_renders_status_line_through_output_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: dict[str, Any] = {}
    captured: dict[str, Any] = {}
    fake_surface = _FakeNativeSurface()

    async def fake_run_tui_runtime(**kwargs: Any) -> None:
        hooks = kwargs["hooks"]
        hooks.expose_surface(fake_surface)
        output = runtime_helpers.get_tui_output(scope)
        assert output is not None
        manager = output.plugin_manager
        # Canonical tier without tier_index: the gateway variant that used to
        # yield tier_index -1 must resolve through the shared tier helpers.
        manager.dispatch(
            _router_event(
                {
                    "tier": "c2",
                    "model": "provider-x/model-fast",
                    "baseline_model": "provider-x/model-big",
                    "source": "router",
                    "confidence": 0.7,
                    "savings_pct": 40.0,
                }
            )
        )
        captured["snapshot"] = manager.snapshot(ROUTER_HUD_SLOT)

    monkeypatch.setattr(native_runtime, "run_tui_runtime", fake_run_tui_runtime)

    await native_runtime.run_native_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=_dispatch,
        queue_max_size=8,
        surface_factory=_surface_factory_for(fake_surface),
    )

    snapshot = captured["snapshot"]
    assert isinstance(snapshot, RouterHudSnapshot)
    assert snapshot.tier_index == 2
    assert fake_surface.output_handle.writes == [
        "[default]route c2 -> model-fast 70% save 40%[/default]\n"
    ]


def test_router_snapshot_tier_index_accepts_canonical_and_legacy_tiers() -> None:
    assert build_router_hud_snapshot({"tier": "c2"}).tier_index == 2
    assert build_router_hud_snapshot({"tier": "C0"}).tier_index == 0
    assert build_router_hud_snapshot({"tier": "t1"}).tier_index == 1
    assert build_router_hud_snapshot({"tier": "mystery"}).tier_index == -1
    assert build_router_hud_snapshot({"tier": "c2", "tier_index": 3}).tier_index == 3


def test_status_markup_escapes_message_and_maps_styles() -> None:
    assert status_markup("route c2 -> m", style="normal") == "[default]route c2 -> m[/default]\n"
    assert status_markup("fallback [x]", style="warning") == "[yellow]fallback \\[x][/yellow]\n"
    assert status_markup("note", style="mystery") == "[dim]note[/dim]\n"


def test_tui_alias_surface_matches_disk_and_every_export_imports() -> None:
    import opensquilla.cli.tui as tui

    package_root = Path(tui.__file__).resolve().parent
    modules = {
        path.stem for path in package_root.glob("*.py") if path.name != "__init__.py"
    }
    subpackages = {
        path.name
        for path in package_root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }

    assert set(tui.__all__) == modules | subpackages
    assert "events" not in tui.__all__
    assert "runtime" not in tui.__all__
    for name in tui.__all__:
        assert importlib.import_module(f"opensquilla.cli.tui.{name}")
