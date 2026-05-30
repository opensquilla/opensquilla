"""Chat runtime adapter for the OpenTUI footer surface."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from opensquilla.cli.tui.adapters.terminal_chat_adapter import (
    ChatAbortTurn,
    ChatRuntimeScope,
    TuiPluginOutputHandle,
    classify_chat_input,
    clear_current_cancel,
    default_tui_plugin_manager,
    surface_task_name,
)
from opensquilla.cli.tui.backend.contracts import (
    TuiOutputHandle,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurface,
)
from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
from opensquilla.cli.tui.backend.plugins import TuiPluginManager
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.opentui.surface import open_opentui_surface
from opensquilla.engine.commands import Surface

USER_ECHO_LABEL = "›"


async def _noop_abort_turn() -> None:
    return None


@dataclass
class OpenTuiChatRuntimeContext:
    """Typed OpenTUI-chat adapter state with a legacy scope mirror."""

    surface: Surface
    scope: ChatRuntimeScope
    plugin_manager: TuiPluginManager
    abort_active_turn: ChatAbortTurn | None = None

    @property
    def model(self) -> str | None:
        value = self.scope.get("model")
        return value if isinstance(value, str) else None

    @property
    def session_id(self) -> str | None:
        value = self.scope.get("session_key")
        return value if isinstance(value, str) else None

    def abort_turn(self) -> Awaitable[None]:
        if self.surface is not Surface.CLI_GATEWAY or self.abort_active_turn is None:
            return _noop_abort_turn()
        return self.abort_active_turn()

    def expose_surface(self, tui_surface: TuiSurface) -> None:
        output_handle = getattr(tui_surface, "output_handle", None)
        if isinstance(output_handle, TuiOutputHandle):
            TuiOutputBinding(self.scope).expose(
                TuiPluginOutputHandle(
                    output_handle,
                    plugin_manager=self.plugin_manager,
                )
            )

    def clear_output(self) -> None:
        TuiOutputBinding(self.scope).clear()


def get_tui_output(scope: MutableMapping[str, Any]) -> TuiOutputHandle | None:
    """Return the active typed TUI output handle from an OpenTUI runtime scope."""
    return TuiOutputBinding(scope).get()


def opentui_notice(scope: MutableMapping[str, Any], payload: str) -> None:
    """Write runtime notices through the active OpenTUI output handle."""
    output = get_tui_output(scope)
    if output is None:
        return

    async def _write() -> None:
        await output.write_through(payload)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_write())
        return
    loop.create_task(_write())


async def echo_opentui_user_input(tui_surface: TuiSurface, text: str) -> None:
    """Echo accepted user input above the OpenTUI footer."""
    if not text.strip():
        return
    await tui_surface.write_through(f"\n{USER_ECHO_LABEL}\n{text}\n")


async def echo_opentui_queued_turn_start(tui_surface: TuiSurface) -> None:
    """Render a queue marker through the OpenTUI scrollback surface."""
    await tui_surface.write_through("\n◢ squilla\nrunning queued input\n")


async def run_opentui_chat_runtime(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: ChatAbortTurn | None = None,
) -> None:
    """Compose the OpenTUI footer adapter with the TUI backend runtime."""
    context = OpenTuiChatRuntimeContext(
        surface=surface,
        scope=scope,
        plugin_manager=default_tui_plugin_manager(),
        abort_active_turn=abort_active_turn,
    )

    def _surface_factory():
        return open_opentui_surface(
            surface=surface,
            model=context.model,
            session_id=context.session_id,
        )

    def _notice(payload: str) -> None:
        opentui_notice(scope, payload)

    await run_tui_runtime(
        dispatch=dispatch,
        surface_factory=_surface_factory,
        config=TuiRuntimeConfig(
            task_name=surface_task_name(surface),
            queue_max_size=queue_max_size,
            concurrent_input_during_turn=True,
            classify_input=classify_chat_input,
        ),
        hooks=TuiRuntimeHooks(
            on_user_input_echo=echo_opentui_user_input,
            on_queued_turn_start=echo_opentui_queued_turn_start,
            clear_current_cancel=clear_current_cancel,
            notice=_notice,
            on_cancel_active_turn=context.abort_turn,
            expose_surface=context.expose_surface,
            clear_exposed_surface=context.clear_output,
        ),
    )
