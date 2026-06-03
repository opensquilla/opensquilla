"""Backend runtime for OpenSquilla interactive TUI surfaces."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import Any

from opensquilla.cli.tui.backend.contracts import (
    TuiDispatch,
    TuiInputKind,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurfaceFactory,
)
from opensquilla.cli.tui.backend.events import TuiEvent, TuiEventKind, TuiEventSink
from opensquilla.cli.tui.backend.state import TuiRuntimeState


def _emit(event_sink: TuiEventSink | None, event: TuiEvent) -> None:
    if event_sink is not None:
        event_sink(event)


async def run_tui_runtime(
    *,
    dispatch: TuiDispatch,
    surface_factory: TuiSurfaceFactory,
    config: TuiRuntimeConfig,
    hooks: TuiRuntimeHooks = TuiRuntimeHooks(),
) -> TuiRuntimeState:
    """Run the concurrent submitted-line/turn loop for one TUI surface."""
    runtime_state = config.state or TuiRuntimeState()

    async with surface_factory() as tui_surface:
        if hooks.expose_surface is not None:
            hooks.expose_surface(tui_surface)
        turn_task: asyncio.Task[bool] | None = None

        async def _schedule_abort(abort_turn: Awaitable[None]) -> None:
            with contextlib.suppress(Exception):
                await abort_turn

        def _cancel_inflight_turn() -> asyncio.Task[None] | None:
            task = turn_task
            if task is not None and not task.done():
                abort_task: asyncio.Task[None] | None = None
                with contextlib.suppress(Exception):
                    abort_turn = hooks.on_cancel_active_turn()
                    abort_task = asyncio.create_task(_schedule_abort(abort_turn))
                task.cancel()
                return abort_task
            return None

        def _cancel_callback() -> None:
            _cancel_inflight_turn()

        tui_surface.set_cancel_callback(_cancel_callback)

        def _shutdown_drain_then_exit() -> None:
            tui_surface.emit_eof()

        tui_surface.set_shutdown_callback(_shutdown_drain_then_exit)

        def _is_turn_in_flight() -> bool:
            return turn_task is not None and not turn_task.done()

        uninstall_signals = config.install_signal_handlers(
            loop=asyncio.get_running_loop(),
            on_resize=tui_surface.redraw_callback,
            is_turn_in_flight=_is_turn_in_flight,
        )

        task_name = config.task_name

        async def _run_dispatch(user_input: str) -> bool:
            runtime_state.mark_turn_started(user_input)
            _emit(config.event_sink, TuiEvent(TuiEventKind.TURN_STARTED, input_text=user_input))
            try:
                return await dispatch(user_input)
            finally:
                runtime_state.mark_turn_finished()
                _emit(
                    config.event_sink,
                    TuiEvent(TuiEventKind.TURN_FINISHED, input_text=user_input),
                )

        async def _await_turn_or_cancel() -> bool:
            nonlocal turn_task
            current = turn_task
            if current is None:
                return True
            try:
                keep_going = await current
            except asyncio.CancelledError:
                hooks.clear_current_cancel()
                _emit(config.event_sink, TuiEvent(TuiEventKind.TURN_CANCELLED))
                if hooks.notice is not None:
                    hooks.notice("[yellow]Cancelled.[/yellow]")
                keep_going = True
            finally:
                turn_task = None
            return keep_going

        async def _run_shutdown_drain() -> bool:
            nonlocal turn_task
            while runtime_state.pending_size:
                queued = runtime_state.promote_next()
                if queued is None:
                    break
                await hooks.on_queued_turn_start(tui_surface)
                _emit(
                    config.event_sink,
                    TuiEvent(TuiEventKind.QUEUED_INPUT_PROMOTED, input_text=queued),
                )
                turn_task = asyncio.create_task(_run_dispatch(queued), name=task_name)
                keep_going = await _await_turn_or_cancel()
                if not keep_going:
                    return False
            return True

        next_line_task: asyncio.Task[str | None] | None = None

        async def _drop_next_line() -> None:
            nonlocal next_line_task
            if next_line_task is None:
                return
            if not next_line_task.done():
                next_line_task.cancel()
                try:
                    await next_line_task
                except BaseException:  # noqa: BLE001 - shutdown path
                    pass
            next_line_task = None

        try:
            while True:
                if next_line_task is None:
                    next_line_task = asyncio.create_task(
                        tui_surface.next_line(),
                        name=f"chat-input-{task_name}",
                    )

                waitables: set[asyncio.Task[Any]] = {next_line_task}
                if turn_task is not None and not turn_task.done():
                    waitables.add(turn_task)
                await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED)

                if turn_task is not None and turn_task.done():
                    keep_going = await _await_turn_or_cancel()
                    if not keep_going:
                        await _drop_next_line()
                        return runtime_state
                    queued = runtime_state.promote_next()
                    if queued is not None:
                        await hooks.on_queued_turn_start(tui_surface)
                        _emit(
                            config.event_sink,
                            TuiEvent(TuiEventKind.QUEUED_INPUT_PROMOTED, input_text=queued),
                        )
                        turn_task = asyncio.create_task(_run_dispatch(queued), name=task_name)
                        continue
                    if not next_line_task.done():
                        continue

                if not next_line_task.done():
                    continue
                user_input = next_line_task.result()
                next_line_task = None

                if user_input is None:
                    if turn_task is not None and not turn_task.done():
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                        turn_task = None
                    if not await _run_shutdown_drain():
                        return runtime_state
                    if hooks.notice is not None:
                        hooks.notice("[yellow]Goodbye.[/yellow]")
                    return runtime_state

                await hooks.on_user_input_echo(tui_surface, user_input)
                _emit(
                    config.event_sink,
                    TuiEvent(TuiEventKind.USER_INPUT_ACCEPTED, input_text=user_input),
                )

                category = config.classify_input(user_input)

                if category is TuiInputKind.DESTRUCTIVE:
                    runtime_state.clear_pending()
                    if turn_task is not None and not turn_task.done():
                        abort_task = _cancel_inflight_turn()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            hooks.clear_current_cancel()
                        if abort_task is not None:
                            await abort_task
                        turn_task = None
                    keep_going = await _run_dispatch(user_input)
                    if not keep_going:
                        return runtime_state
                    continue

                if category is TuiInputKind.EXIT:
                    if turn_task is not None and not turn_task.done():
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            hooks.clear_current_cancel()
                        turn_task = None
                    if not await _run_shutdown_drain():
                        return runtime_state
                    keep_going = await _run_dispatch(user_input)
                    if not keep_going:
                        return runtime_state
                    continue

                if turn_task is not None and not turn_task.done():
                    if runtime_state.pending_size >= config.queue_max_size:
                        if hooks.notice is not None:
                            hooks.notice(
                                f"[yellow]Queue full ({config.queue_max_size} items)."
                                " Wait for the current turn to complete.[/yellow]"
                            )
                        continue
                    runtime_state.enqueue(user_input)
                    continue

                turn_task = asyncio.create_task(_run_dispatch(user_input), name=task_name)
        finally:
            if hooks.clear_exposed_surface is not None:
                hooks.clear_exposed_surface()
            tui_surface.set_cancel_callback(None)
            tui_surface.set_shutdown_callback(None)
            await _drop_next_line()
            with contextlib.suppress(Exception):
                uninstall_signals()
