from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from opensquilla.cli.tui.backend.contracts import (
    TuiInputKind,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
)
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.backend.state import TuiRuntimeState
from opensquilla.engine.agent_injection import PendingInputProvider


class _FakeSurface:
    def __init__(
        self,
        inputs: asyncio.Queue[str | None],
        *,
        on_next_line: Callable[[], None] | None = None,
    ) -> None:
        self._inputs = inputs
        self._on_next_line = on_next_line
        self.next_line_calls = 0
        self.cancel_callbacks: list[Any] = []
        self.shutdown_callbacks: list[Any] = []
        self.writes: list[str] = []
        self.eof_count = 0
        self.redraw_count = 0

    async def next_line(self) -> str | None:
        self.next_line_calls += 1
        if self._on_next_line is not None:
            self._on_next_line()
        return await self._inputs.get()

    def set_cancel_callback(self, cb) -> None:  # noqa: ANN001
        self.cancel_callbacks.append(cb)

    def set_shutdown_callback(self, cb) -> None:  # noqa: ANN001
        self.shutdown_callbacks.append(cb)

    def emit_eof(self) -> None:
        self.eof_count += 1
        self._inputs.put_nowait(None)

    async def write_through(self, payload: str) -> None:
        self.writes.append(payload)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._invalidate

    def _invalidate(self) -> None:
        self.redraw_count += 1


def _surface_factory(surface: _FakeSurface):
    @asynccontextmanager
    async def _factory() -> AsyncIterator[_FakeSurface]:
        yield surface

    return _factory


async def _noop_echo(surface: Any, text: str) -> None:
    await surface.write_through(f"echo:{text}")


async def _queued_echo(surface: Any) -> None:
    await surface.write_through("queued")


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("timed out waiting for runtime condition")
        await asyncio.sleep(0)


def _runtime_config(**kwargs: Any) -> TuiRuntimeConfig:
    return TuiRuntimeConfig(task_name="chat-turn-test", **kwargs)


def _runtime_hooks(**kwargs: Any) -> TuiRuntimeHooks:
    return TuiRuntimeHooks(
        on_user_input_echo=_noop_echo,
        on_queued_turn_start=_queued_echo,
        **kwargs,
    )


def test_runtime_state_drains_pending_inputs_for_agent_injection() -> None:
    state = TuiRuntimeState()
    state.enqueue("second")
    state.enqueue("third")

    assert isinstance(state, PendingInputProvider)
    assert state.drain_pending() == ["second", "third"]
    assert state.pending_items == ()


@pytest.mark.asyncio
async def test_runtime_allows_active_turn_to_drain_mid_turn_input() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    state = TuiRuntimeState()
    executed: list[str] = []
    drained: list[str] = []
    first_started = asyncio.Event()
    drain_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        if user_input == "first":
            first_started.set()
            await _wait_until(lambda: state.pending_items == ("second",))
            drained.extend(state.drain_pending())
            drain_completed.set()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(state=state),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("second")
    await asyncio.wait_for(drain_completed.wait(), timeout=2.0)
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert drained == ["second"]
    assert executed == ["first"]
    assert state.pending_items == ()
    assert "queued" not in surface.writes


@pytest.mark.asyncio
async def test_runtime_dispatches_single_input_against_fake_surface() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("hello")
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["hello"]
    assert surface.writes == ["echo:hello"]
    assert surface.cancel_callbacks[-1] is None
    assert surface.shutdown_callbacks[-1] is None


@pytest.mark.asyncio
async def test_runtime_queues_pending_input_and_promotes_fifo() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    first_started = asyncio.Event()
    finish_first = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        if user_input == "first":
            first_started.set()
            await finish_first.wait()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("second")
    await inputs.put("third")
    for _ in range(20):
        await asyncio.sleep(0)
    finish_first.set()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first", "second", "third"]
    assert surface.writes.count("queued") == 2


@pytest.mark.asyncio
async def test_runtime_can_defer_next_input_until_turn_finishes() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    first_started = asyncio.Event()
    finish_first = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        first_started.set()
        await finish_first.wait()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(concurrent_input_during_turn=False),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    for _ in range(20):
        await asyncio.sleep(0)

    assert surface.next_line_calls == 1

    finish_first.set()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first"]
    assert surface.next_line_calls == 2


@pytest.mark.asyncio
async def test_runtime_can_keep_bottom_input_live_during_turn() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    second_input_started = asyncio.Event()
    surface = _FakeSurface(
        inputs,
        on_next_line=lambda: second_input_started.set()
        if surface.next_line_calls >= 2
        else None,
    )
    first_started = asyncio.Event()
    finish_first = asyncio.Event()
    executed: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        first_started.set()
        await finish_first.wait()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(concurrent_input_during_turn=True),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await asyncio.wait_for(second_input_started.wait(), timeout=2.0)

    assert surface.next_line_calls >= 2

    await inputs.put(None)
    finish_first.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first"]


@pytest.mark.asyncio
async def test_runtime_starts_next_input_before_dispatch_when_concurrent() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    events: list[str] = []

    def _record_next_line() -> None:
        events.append(f"input-{surface.next_line_calls}")

    surface = _FakeSurface(inputs, on_next_line=_record_next_line)
    dispatch_started = asyncio.Event()
    finish_dispatch = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        events.append(f"dispatch-{user_input}")
        dispatch_started.set()
        await finish_dispatch.wait()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(concurrent_input_during_turn=True),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)

    assert events.index("input-2") < events.index("dispatch-first")

    await inputs.put(None)
    finish_dispatch.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_runtime_destructive_slash_cancels_active_turn_and_purges_queue() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    clear_completed = asyncio.Event()
    cancel_calls: list[str] = []
    clear_cancel_snapshots: list[list[str]] = []

    async def _dispatch(user_input: str) -> bool:
        if user_input == "first":
            executed.append("first-start")
            first_started.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                first_cancelled.set()
                raise
            executed.append("first-end")
            return True
        executed.append(user_input)
        if user_input == "/clear":
            clear_cancel_snapshots.append(list(cancel_calls))
            clear_completed.set()
        return True

    async def _cancel_active_turn() -> None:
        await asyncio.sleep(0)
        cancel_calls.append("cancel")

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(
                classify_input=lambda text: (
                    TuiInputKind.DESTRUCTIVE if text == "/clear" else TuiInputKind.NORMAL
                )
            ),
            hooks=_runtime_hooks(on_cancel_active_turn=_cancel_active_turn),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("second")
    await inputs.put("third")
    for _ in range(20):
        await asyncio.sleep(0)
    await inputs.put("/clear")

    await asyncio.wait_for(first_cancelled.wait(), timeout=2.0)
    await asyncio.wait_for(clear_completed.wait(), timeout=2.0)
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first-start", "/clear"]
    assert cancel_calls == ["cancel"]
    assert clear_cancel_snapshots == [["cancel"]]


@pytest.mark.asyncio
async def test_runtime_exit_drains_pending_work_before_dispatching_exit() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    first_started = asyncio.Event()
    finish_first = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "first":
            executed.append("first-start")
            first_started.set()
            await finish_first.wait()
            executed.append("first-end")
            return True
        executed.append(user_input)
        return user_input != "/exit"

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(
                classify_input=lambda text: (
                    TuiInputKind.EXIT if text == "/exit" else TuiInputKind.NORMAL
                )
            ),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("second")
    await inputs.put("third")
    for _ in range(20):
        await asyncio.sleep(0)
    await inputs.put("/exit")
    for _ in range(20):
        await asyncio.sleep(0)
    finish_first.set()

    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first-start", "first-end", "second", "third", "/exit"]


@pytest.mark.asyncio
async def test_runtime_cancel_invokes_adapter_cancel_hook() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    dispatch_started = asyncio.Event()
    dispatch_cancelled = asyncio.Event()
    cancel_calls: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        dispatch_started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            dispatch_cancelled.set()
            raise
        return True

    async def _cancel_active_turn() -> None:
        cancel_calls.append("cancel")

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(on_cancel_active_turn=_cancel_active_turn),
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    active_cb = next(cb for cb in reversed(surface.cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert cancel_calls == ["cancel"]
    assert dispatch_cancelled.is_set() is True


@pytest.mark.asyncio
async def test_runtime_cancel_drops_pending_inputs_from_active_turn() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    state = TuiRuntimeState()
    executed: list[str] = []
    first_started = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "first":
            executed.append("first-start")
            first_started.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                executed.append("first-cancelled")
                raise
        executed.append(user_input)
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(state=state),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("second")
    await inputs.put("third")
    await _wait_until(lambda: state.pending_items == ("second", "third"))
    active_cb = next(cb for cb in reversed(surface.cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["first-start", "first-cancelled"]
    assert state.pending_items == ()
    assert "queued" not in surface.writes


@pytest.mark.asyncio
async def test_runtime_cancel_suppresses_adapter_cancel_hook_errors() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    dispatch_started = asyncio.Event()
    dispatch_cancelled = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        dispatch_started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            dispatch_cancelled.set()
            raise
        return True

    def _cancel_active_turn() -> Awaitable[None]:
        raise RuntimeError("abort hook failed")

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(on_cancel_active_turn=_cancel_active_turn),
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    active_cb = next(cb for cb in reversed(surface.cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert dispatch_cancelled.is_set() is True


@pytest.mark.asyncio
async def test_runtime_installs_surface_redraw_callback_for_resize() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    installed = asyncio.Event()
    captured_resize_callbacks: list[Callable[[], None]] = []

    def _install_signal_handlers(
        *,
        loop: asyncio.AbstractEventLoop,
        on_resize: Callable[[], None],
        is_turn_in_flight: Callable[[], bool],
    ) -> Callable[[], None]:
        del loop, is_turn_in_flight
        captured_resize_callbacks.append(on_resize)
        installed.set()
        return lambda: None

    async def _dispatch(user_input: str) -> bool:
        raise AssertionError(f"dispatch should not run: {user_input}")

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(install_signal_handlers=_install_signal_handlers),
        )
    )

    await asyncio.wait_for(installed.wait(), timeout=2.0)
    captured_resize_callbacks[0]()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert surface.redraw_count == 1
