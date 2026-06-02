"""Chat runtime adapter for the OpenTUI footer surface."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import asdict, dataclass
from typing import Any

from opensquilla.cli.tui.adapters.runtime_helpers import (
    ChatAbortTurn,
    ChatRuntimeContext,
    ChatRuntimeScope,
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
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.backend.state import TuiRuntimeState
from opensquilla.cli.tui.opentui.messages import ModelText, PromptEcho
from opensquilla.cli.tui.opentui.surface import open_opentui_surface
from opensquilla.engine.commands import Surface


@dataclass
class OpenTuiChatRuntimeContext(ChatRuntimeContext):
    """Typed OpenTUI-chat adapter state with a legacy scope mirror."""

    @property
    def workspace_dir(self) -> str | None:
        value = self.scope.get("workspace_dir")
        if isinstance(value, str) and value:
            return value
        tool_ctx = self.scope.get("tool_ctx")
        ctx_workspace = getattr(tool_ctx, "workspace_dir", None)
        if isinstance(ctx_workspace, str) and ctx_workspace:
            return ctx_workspace
        return None


def get_tui_output(scope: MutableMapping[str, Any]) -> TuiOutputHandle | None:
    """Return the active typed TUI output handle from an OpenTUI runtime scope."""
    return TuiOutputBinding(scope).get()


def opentui_notice(scope: MutableMapping[str, Any], payload: str) -> None:
    """Write runtime notices through the active OpenTUI output handle."""
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


async def echo_opentui_user_input(tui_surface: TuiSurface, text: str) -> None:
    """Echo accepted user input as a structured prompt block."""
    if not text.strip():
        return
    send = getattr(tui_surface, "send_message", None)
    if send is not None:
        await send("prompt.echo", asdict(PromptEcho(text=text)))


async def echo_opentui_queued_turn_start(tui_surface: TuiSurface) -> None:
    """Render a queue marker as a model.text line."""
    send = getattr(tui_surface, "send_message", None)
    if send is not None:
        await send("model.text", asdict(ModelText(text="running queued input")))


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
        kwargs: dict[str, Any] = {
            "surface": surface,
            "model": context.model,
            "session_id": context.session_id,
        }
        if context.workspace_dir is not None:
            kwargs["workspace_dir"] = context.workspace_dir
        return open_opentui_surface(**kwargs)

    def _notice(payload: str) -> None:
        opentui_notice(scope, payload)

    runtime_state = TuiRuntimeState()
    scope["pending_input_provider"] = runtime_state
    try:
        await run_tui_runtime(
            dispatch=dispatch,
            surface_factory=_surface_factory,
            config=TuiRuntimeConfig(
                task_name=surface_task_name(surface),
                queue_max_size=queue_max_size,
                concurrent_input_during_turn=True,
                classify_input=classify_chat_input,
                state=runtime_state,
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
    finally:
        if scope.get("pending_input_provider") is runtime_state:
            scope.pop("pending_input_provider", None)
