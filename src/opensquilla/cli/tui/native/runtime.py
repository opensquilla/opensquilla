"""Chat runtime adapter for the stable terminal surface."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from opensquilla.cli.tui.adapters.runtime_helpers import (
    ChatAbortTurn,
    ChatRuntimeContext,
    ChatRuntimeScope,
    classify_chat_input,
    clear_current_cancel,
    default_tui_plugin_manager,
    get_tui_output,
    surface_task_name,
)
from opensquilla.cli.tui.backend.contracts import (
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurface,
)
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.backend.state import TuiRuntimeState
from opensquilla.engine.commands import Surface


@dataclass
class NativeChatRuntimeContext(ChatRuntimeContext):
    """Typed stable terminal-chat adapter state with a legacy scope mirror."""


async def run_native_chat_runtime(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    surface_factory: Callable[[], AbstractAsyncContextManager[TuiSurface]],
    abort_active_turn: ChatAbortTurn | None = None,
) -> None:
    """Compose a Python-native terminal surface with the TUI backend runtime."""
    context = NativeChatRuntimeContext(
        surface=surface,
        scope=scope,
        plugin_manager=default_tui_plugin_manager(),
        abort_active_turn=abort_active_turn,
    )

    def _notice(payload: str) -> None:
        output = get_tui_output(scope)
        if output is None:
            return

        async def _write() -> None:
            with contextlib.suppress(Exception):
                await output.write_through(payload)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_write())
            return
        loop.create_task(_write())

    runtime_state = TuiRuntimeState()
    scope["pending_input_provider"] = runtime_state
    try:
        await run_tui_runtime(
            dispatch=dispatch,
            surface_factory=surface_factory,
            config=TuiRuntimeConfig(
                task_name=surface_task_name(surface),
                queue_max_size=queue_max_size,
                concurrent_input_during_turn=False,
                classify_input=classify_chat_input,
                state=runtime_state,
            ),
            hooks=TuiRuntimeHooks(
                clear_current_cancel=clear_current_cancel,
                notice=_notice,
                on_cancel_active_turn=context.abort_turn,
                expose_surface=context.expose_surface,
                clear_exposed_surface=context.clear_output,
            ),
        )
    finally:
        if scope.get("pending_input_provider") is runtime_state:
            scope.pop("pending_input_provider", None)
