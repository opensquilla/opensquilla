"""Chat-command adapter for the backend TUI runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from opensquilla.cli.tui.adapters.slash_policy import SlashCategory, classify
from opensquilla.cli.tui.backend.contracts import (
    TuiInputKind,
    TuiOutputHandle,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurface,
)
from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.terminal.prompt import (
    queued_input_start_payload,
    user_input_echo_payload,
)
from opensquilla.cli.tui.terminal.signals import install_chat_signal_handlers
from opensquilla.cli.tui.terminal.surface import open_terminal_surface
from opensquilla.cli.ui import console
from opensquilla.engine.commands import Surface

ChatRuntimeScope = MutableMapping[str, Any]
ChatAbortTurn = Callable[[], Awaitable[None]]


async def _noop_abort_turn() -> None:
    return None


@dataclass
class TerminalChatRuntimeContext:
    """Typed terminal-chat adapter state with a legacy scope mirror."""

    surface: Surface
    scope: ChatRuntimeScope
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

    def get_output(self) -> TuiOutputHandle | None:
        return TuiOutputBinding(self.scope).get()

    def expose_surface(self, tui_surface: TuiSurface) -> None:
        TuiOutputBinding(self.scope).expose_from_surface(tui_surface)

    def clear_output(self) -> None:
        TuiOutputBinding(self.scope).clear()


def clear_current_cancel() -> None:
    """Keep one Ctrl+C scoped to the active turn under asyncio.run."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return
    if task is not None and hasattr(task, "uncancel"):
        task.uncancel()


def map_slash_category(category: SlashCategory) -> TuiInputKind:
    """Map REPL slash policy into runtime-owned input kinds."""
    if category is SlashCategory.DESTRUCTIVE:
        return TuiInputKind.DESTRUCTIVE
    if category is SlashCategory.EXIT:
        return TuiInputKind.EXIT
    return TuiInputKind.NORMAL


def classify_chat_input(user_input: str) -> TuiInputKind:
    """Classify chat input without leaking slash policy into the runtime."""
    return map_slash_category(classify(user_input))


def surface_task_name(surface: Surface | str) -> str:
    """Name chat adapter tasks without putting engine surfaces in TUI contracts."""
    value = surface.value if isinstance(surface, Surface) else str(surface)
    return f"chat-turn-{value}"


def get_tui_output(scope: ChatRuntimeScope) -> TuiOutputHandle | None:
    """Return the active typed TUI output handle from a chat runtime scope."""
    return TuiOutputBinding(scope).get()


def expose_tui_output(scope: ChatRuntimeScope, output_handle: TuiOutputHandle) -> None:
    """Expose the active output handle to chat turn dispatch code."""
    TuiOutputBinding(scope).expose(output_handle)


def clear_tui_output(scope: ChatRuntimeScope) -> None:
    """Clear the active TUI output handle after the runtime exits."""
    TuiOutputBinding(scope).clear()


async def _write_payload(tui_surface: TuiSurface, payload: str) -> None:
    await tui_surface.write_through(payload)


async def echo_user_input(tui_surface: TuiSurface, text: str) -> None:
    """Echo accepted user input through the active terminal surface."""
    payload = user_input_echo_payload(text)
    if payload:
        await _write_payload(tui_surface, payload)


async def echo_queued_turn_start(tui_surface: TuiSurface) -> None:
    """Render a marker when queued input becomes the active turn."""
    await _write_payload(tui_surface, queued_input_start_payload())


async def run_terminal_chat_runtime(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: ChatAbortTurn | None = None,
) -> None:
    """Compose the terminal chat adapter with the TUI backend runtime."""
    context = TerminalChatRuntimeContext(
        surface=surface,
        scope=scope,
        abort_active_turn=abort_active_turn,
    )

    def _surface_factory():
        return open_terminal_surface(
            surface=surface,
            model=context.model,
            session_id=context.session_id,
        )

    def _expose_surface(tui_surface: TuiSurface) -> None:
        context.expose_surface(tui_surface)

    await run_tui_runtime(
        dispatch=dispatch,
        surface_factory=_surface_factory,
        config=TuiRuntimeConfig(
            task_name=surface_task_name(surface),
            queue_max_size=queue_max_size,
            classify_input=classify_chat_input,
            install_signal_handlers=install_chat_signal_handlers,
        ),
        hooks=TuiRuntimeHooks(
            on_user_input_echo=echo_user_input,
            on_queued_turn_start=echo_queued_turn_start,
            clear_current_cancel=clear_current_cancel,
            notice=console.print,
            on_cancel_active_turn=context.abort_turn,
            expose_surface=_expose_surface,
            clear_exposed_surface=context.clear_output,
        ),
    )
