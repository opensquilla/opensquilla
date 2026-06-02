"""TUI surface adapter backed by the OpenTUI footer host."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from opensquilla.cli.tui.backend.contracts import TuiSurface
from opensquilla.cli.tui.opentui.bridge import OpenTuiBridge
from opensquilla.cli.tui.opentui.messages import (
    ComposerState,
    HostError,
    HostInputCancel,
    HostInputEof,
    HostInputSubmit,
    HostReady,
    HostResize,
    RouterPluginState,
    ScrollbackWrite,
)
from opensquilla.engine.commands import Surface

_ROUTER_LABEL_RE = re.compile(
    r"^(?P<mode>route|forced|observe)\s+(?P<tier>\S+)\s+->\s+"
    r"(?P<model>\S+)(?:\s+(?P<confidence>\d+%))?"
    r"(?:\s+save\s+(?P<saving>\d+%))?"
)
_FALLBACK_LABEL_RE = re.compile(r"^fallback\s+->\s+(?P<model>\S+)")


class _OpenTuiBridgeLike(Protocol):
    async def send(self, message_type: str, payload: object | None = None) -> None: ...

    async def next_message(self) -> object | None: ...


class OpenTuiOutputHandle:
    """Typed output handle that writes transcript data through OpenTUI scrollback."""

    def __init__(
        self,
        bridge: _OpenTuiBridgeLike,
        *,
        approval_surface: Surface,
    ) -> None:
        self._bridge = bridge
        self.approval_surface = approval_surface
        self._toolbar: dict[str, object] = {}

    async def write_through(self, payload: str) -> None:
        await self._bridge.send("scrollback.write", ScrollbackWrite(text=payload))

    async def send_message(self, message_type: str, payload: dict[str, object]) -> None:
        await self._bridge.send(message_type, payload)

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
        return _opentui_stream_output(self)

    def set_toolbar(self, key: str, value: object | None) -> None:
        if value is None:
            self._toolbar.pop(key, None)
            return
        self._toolbar[key] = value

    def invalidate(self) -> None:
        router_state = _router_plugin_state_from_toolbar(self._toolbar)
        _send_bridge_message(self._bridge, "router.update", router_state)


class OpenTuiSurface:
    """Adapter exposing the OpenTUI footer host through `TuiSurface`."""

    def __init__(
        self,
        bridge: _OpenTuiBridgeLike,
        *,
        approval_surface: Surface = Surface.CLI_GATEWAY,
    ) -> None:
        self._bridge = bridge
        self._cancel_callback: Callable[[], None] | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._eof_emitted = False
        self._output_handle = OpenTuiOutputHandle(
            bridge,
            approval_surface=approval_surface,
        )

    async def next_line(self) -> str | None:
        if self._eof_emitted:
            return None
        while True:
            message = await self._bridge.next_message()
            if message is None:
                return None
            if isinstance(message, HostInputSubmit):
                return message.text
            if isinstance(message, HostInputCancel):
                if self._cancel_callback is not None:
                    self._cancel_callback()
                continue
            if isinstance(message, HostInputEof):
                self._eof_emitted = True
                if self._shutdown_callback is not None:
                    self._shutdown_callback()
                return None
            if isinstance(message, HostError):
                raise RuntimeError(f"OpenTUI host error: {message.message}")
            if isinstance(message, (HostReady, HostResize)):
                continue

    @property
    def output_handle(self) -> OpenTuiOutputHandle:
        return self._output_handle

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._output_handle.invalidate

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._cancel_callback = cb

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._shutdown_callback = cb

    def emit_eof(self) -> None:
        self._eof_emitted = True

    async def write_through(self, payload: str) -> None:
        await self._output_handle.write_through(payload)

    async def send_message(self, message_type: str, payload: dict[str, object]) -> None:
        await self._output_handle.send_message(message_type, payload)


@asynccontextmanager
async def _opentui_stream_output(
    output: OpenTuiOutputHandle,
) -> AsyncIterator[Callable[[str], None]]:
    pending: list[asyncio.Task[None]] = []

    def _write(delta: str) -> None:
        if not delta:
            return
        pending.append(asyncio.create_task(output.write_through(delta)))

    try:
        yield _write
    finally:
        if pending:
            await asyncio.gather(*pending)


@asynccontextmanager
async def open_opentui_surface(
    *,
    surface: Surface,
    model: str | None = None,
    session_id: str | None = None,
    ready_marker: str | None = None,
    print_ready_marker: bool = True,
    bridge: OpenTuiBridge | None = None,
) -> AsyncIterator[TuiSurface]:
    del model, session_id
    active_bridge = bridge or OpenTuiBridge()
    await active_bridge.start()
    try:
        marker = (
            os.environ.get("OPENSQUILLA_TUI_READY_MARKER", "OPEN_SQUILLA_TUI_READY")
            if ready_marker is None
            else ready_marker
        )
        if print_ready_marker and marker:
            await active_bridge.send("scrollback.write", ScrollbackWrite(text=f"{marker}\n"))
        await active_bridge.send(
            "composer.set",
            ComposerState(placeholder="send a message"),
        )
        yield OpenTuiSurface(active_bridge, approval_surface=surface)
    finally:
        await active_bridge.close()


def _send_bridge_message(
    bridge: _OpenTuiBridgeLike,
    message_type: str,
    payload: object,
) -> None:
    send_nowait = getattr(bridge, "send_nowait", None)
    if callable(send_nowait):
        send_nowait(message_type, payload)
        return

    async def _send() -> None:
        await bridge.send(message_type, payload)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_send())
        return
    loop.create_task(_send())


def _router_plugin_state_from_toolbar(toolbar: dict[str, object]) -> RouterPluginState:
    label = str(toolbar.get("router_hud") or "")
    style = str(toolbar.get("router_hud_style") or "dim")
    context = str(toolbar.get("router_usage") or "-")
    baseline_model = str(toolbar.get("router_baseline_model") or "")
    source = str(toolbar.get("router_source") or "")
    routing_applied = bool(toolbar.get("router_routing_applied", True))
    rollout_phase = str(toolbar.get("router_rollout_phase") or "full")
    match = _ROUTER_LABEL_RE.match(label)
    if match:
        tier = match.group("tier")
        confidence = match.group("confidence")
        return RouterPluginState(
            model=match.group("model"),
            route=f"{tier} {confidence}" if confidence else tier,
            saving=match.group("saving") or "-",
            context=context,
            style=_normalize_router_style(style),
            baseline_model=baseline_model,
            source=source,
            routing_applied=routing_applied,
            rollout_phase=rollout_phase,
        )

    fallback = _FALLBACK_LABEL_RE.match(label)
    if fallback:
        return RouterPluginState(
            model=fallback.group("model"),
            route="fallback",
            saving="-",
            context=context,
            style="warning",
            baseline_model=baseline_model,
            source=source or "fallback",
            routing_applied=routing_applied,
            rollout_phase=rollout_phase,
        )

    return RouterPluginState(
        model="pending",
        route="pending",
        saving="-",
        context=context,
        style="dim",
    )


def _normalize_router_style(style: str) -> str:
    if style in {"dim", "normal", "warning", "error"}:
        return style
    return "normal"
