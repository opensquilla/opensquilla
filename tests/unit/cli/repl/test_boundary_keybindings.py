"""Boundary keybindings.

Covers the Ctrl-C double-press shutdown contract and the Ctrl-D drain-then-
exit contract.

- Ctrl-C single press: clears the input buffer and invokes the registered
  cancel callback. This contract is also pinned by
  ``test_concurrent_turn.test_ctrl_c_binding_invokes_cancel_callback_and_clears_buffer``;
  the duplicate here anchors boundary-key coverage in one file.
- Ctrl-C double press within ``_DOUBLE_CTRL_C_WINDOW_S`` (1.5s): invokes
  the registered shutdown callback AFTER the single-press cancel/clear
  semantics have run. Outside the window, no shutdown fires and a fresh
  window starts on the late press.
- Ctrl-D: emits EOF on the submit queue; the chat REPL's EOF path drains
  the pending deque, finalizes any in-flight turn, and exits.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.output import DummyOutput

from opensquilla.cli.repl.app import (
    _DOUBLE_CTRL_C_WINDOW_S,
    ChatApplication,
    _build_key_bindings,
)
from opensquilla.cli.repl.terminal_surface import TerminalSurface
from opensquilla.engine.commands import Surface

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _fresh_chat_app() -> ChatApplication:
    """Build a ChatApplication wired to DummyInput / DummyOutput."""
    return ChatApplication(
        surface=Surface.CLI_GATEWAY,
        toolbar_context={
            "model": None,
            "session_id": None,
            "suppress": None,
            "status": None,
        },
        bottom_toolbar=lambda: "",
        style=None,
        input=DummyInput(),
        output=DummyOutput(),
    )


def _ctrl_c_handler():
    """Return the bound Ctrl-C handler from `_build_key_bindings`."""
    bindings = _build_key_bindings()
    handlers = [binding for binding in bindings.bindings if tuple(binding.keys) == ("c-c",)]
    assert len(handlers) == 1, f"expected one c-c binding, got {len(handlers)}"
    return handlers[0].handler


def _ctrl_d_handler():
    """Return the bound Ctrl-D handler from `_build_key_bindings`."""
    bindings = _build_key_bindings()
    handlers = [binding for binding in bindings.bindings if tuple(binding.keys) == ("c-d",)]
    assert len(handlers) == 1, f"expected one c-d binding, got {len(handlers)}"
    return handlers[0].handler


class _FakeEvent:
    """Minimal stub mimicking prompt-toolkit's KeyPressEvent.app surface."""

    def __init__(self, chat_app: ChatApplication) -> None:
        self.app = chat_app.application


# --------------------------------------------------------------------------- #
# Ctrl-C single-press (boundary-key file coverage; duplicates a smaller       #
# test in test_concurrent_turn.py — left in place because the rest of the     #
# builds on the same _FakeEvent + handler harness)                            #
# --------------------------------------------------------------------------- #


def test_ctrl_c_single_press_clears_buffer_and_invokes_cancel() -> None:
    """One Ctrl-C resets the buffer AND invokes the cancel callback.

    Sibling test:
    ``test_concurrent_turn.test_ctrl_c_binding_invokes_cancel_callback_and_clears_buffer``
    covers the same surface; we keep a copy here so the boundary-key
    suite is self-contained.
    """
    handler = _ctrl_c_handler()
    chat_app = _fresh_chat_app()
    cancel_calls: list[None] = []
    chat_app.set_cancel_callback(lambda: cancel_calls.append(None))

    chat_app._buffer.text = "half-typed"
    handler(_FakeEvent(chat_app))

    assert cancel_calls == [None]
    assert chat_app._buffer.text == ""


# --------------------------------------------------------------------------- #
# Ctrl-C double-press shutdown                                                #
# --------------------------------------------------------------------------- #


def test_ctrl_c_double_press_within_1500ms_invokes_shutdown(monkeypatch) -> None:
    """A second Ctrl-C within the window invokes the shutdown callback.

    Drives the Ctrl-C handler twice and freezes `time.monotonic` to
    bracket the second press inside `_DOUBLE_CTRL_C_WINDOW_S`. Asserts
    the registered shutdown callback fires exactly once.
    """
    handler = _ctrl_c_handler()
    chat_app = _fresh_chat_app()
    shutdown_calls: list[None] = []
    chat_app.set_shutdown_callback(lambda: shutdown_calls.append(None))

    # Freeze the clock: first press at t=0, second press at t=1.0.
    times = iter([0.0, 1.0])
    monkeypatch.setattr("opensquilla.cli.repl.app.time.monotonic", lambda: next(times))

    # First press — records the timestamp, no shutdown yet.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == []
    assert chat_app._last_ctrl_c_at == 0.0

    # Second press inside the window — fires shutdown and clears timestamp.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == [None]
    assert chat_app._last_ctrl_c_at is None


def test_ctrl_c_double_press_outside_1500ms_does_not_invoke_shutdown(
    monkeypatch,
) -> None:
    """A second Ctrl-C OUTSIDE the window does NOT fire shutdown.

    A third press at t=3.5 then a fourth at t=4.0 form a valid pair
    relative to t=3.5 (delta = 0.5 ≤ 1.5) so shutdown fires there. This
    pins both halves of the window contract — late presses reset the
    window, they don't pair with the first press.
    """
    handler = _ctrl_c_handler()
    chat_app = _fresh_chat_app()
    shutdown_calls: list[None] = []
    chat_app.set_shutdown_callback(lambda: shutdown_calls.append(None))

    # 0.0 -> 2.0 (outside window) -> 3.5 (outside) -> 4.0 (inside vs 3.5)
    times = iter([0.0, 2.0, 3.5, 4.0])
    monkeypatch.setattr("opensquilla.cli.repl.app.time.monotonic", lambda: next(times))

    # Press 1 at t=0: record timestamp.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == []
    assert chat_app._last_ctrl_c_at == 0.0

    # Press 2 at t=2.0 (delta=2.0 > 1.5): outside window, reset window.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == [], "shutdown must not fire outside the window"
    assert chat_app._last_ctrl_c_at == 2.0

    # Press 3 at t=3.5 (delta=1.5 vs t=2.0): boundary case is INSIDE the
    # window because the contract uses <=. That fires shutdown and clears
    # the timestamp, then press 4 records a fresh start.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == [None], "press at delta == window must fire shutdown (<= boundary)"
    assert chat_app._last_ctrl_c_at is None

    # Press 4 at t=4.0: fresh window starts because the prior pair already
    # fired and the timestamp was cleared.
    handler(_FakeEvent(chat_app))
    assert shutdown_calls == [None], (
        "fourth press alone must not refire shutdown (window was reset)"
    )
    assert chat_app._last_ctrl_c_at == 4.0


def test_ctrl_c_double_press_clears_buffer_each_time() -> None:
    """Both single and double press leave the buffer empty.

    The Ctrl-C handler resets the buffer BEFORE the double-press
    detector runs, so the buffer is empty after every press regardless
    of whether the shutdown callback fires.
    """
    handler = _ctrl_c_handler()
    chat_app = _fresh_chat_app()
    chat_app.set_shutdown_callback(lambda: None)

    chat_app._buffer.text = "first draft"
    handler(_FakeEvent(chat_app))
    assert chat_app._buffer.text == ""

    chat_app._buffer.text = "second draft"
    handler(_FakeEvent(chat_app))
    assert chat_app._buffer.text == ""


def test_ctrl_c_double_press_with_no_shutdown_callback_is_no_op() -> None:
    """When no shutdown callback is registered, double-press is harmless.

    The contract: setting the shutdown callback to None makes Ctrl-C
    fall back to single-press behavior — no double-press detection runs
    because there is no shutdown contract to fire. This pins that the
    timestamp is not updated either, so existing single-press semantics
    are byte-for-byte equivalent to the previous single-press behavior.
    """
    handler = _ctrl_c_handler()
    chat_app = _fresh_chat_app()
    assert chat_app._shutdown_callback is None
    handler(_FakeEvent(chat_app))
    handler(_FakeEvent(chat_app))
    # No shutdown callback registered → _last_ctrl_c_at stays at its
    # initial None because the detector returns early.
    assert chat_app._last_ctrl_c_at is None


# --------------------------------------------------------------------------- #
# Ctrl-D drain-then-exit                                                      #
# --------------------------------------------------------------------------- #


class _FakeHandle:
    """Fake `interactive_session()` handle for `_run_concurrent_repl`."""

    def __init__(
        self,
        inputs: asyncio.Queue,
        captured_cancel: list[object],
        captured_shutdown: list[object],
    ) -> None:
        self._inputs = inputs
        self._captured_cancel = captured_cancel
        self._captured_shutdown = captured_shutdown

    async def next_line(self) -> str | None:
        return await self._inputs.get()

    def set_toolbar(self, key, value) -> None:
        return None

    def set_cancel_callback(self, cb) -> None:
        self._captured_cancel.append(cb)

    def set_shutdown_callback(self, cb) -> None:
        self._captured_shutdown.append(cb)

    def emit_eof(self) -> None:
        self._inputs.put_nowait(None)

    def invalidate(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        return None


def _install_fake_session(
    monkeypatch,
    inputs: asyncio.Queue,
    captured_cancel: list[object],
    captured_shutdown: list[object],
) -> None:
    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle(inputs, captured_cancel, captured_shutdown))

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )


@pytest.mark.asyncio
async def test_ctrl_d_drains_pending_queue_before_exit(monkeypatch) -> None:
    """Ctrl-D (EOF) must drain the pending deque before the loop exits.

    Pushes ``msg1`` (long-running turn), then queues ``msg2`` behind it,
    then sends EOF. Expected order: msg1 runs to completion, msg2 runs
    (drained from pending), then the loop returns.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    msg1_started = asyncio.Event()
    finish_msg1 = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "msg1":
            executed.append("msg1-start")
            msg1_started.set()
            await finish_msg1.wait()
            executed.append("msg1-end")
            return True
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cancel: list[object] = []
    captured_shutdown: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cancel, captured_shutdown)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("msg1")
    await asyncio.wait_for(msg1_started.wait(), timeout=2.0)

    # Queue msg2 behind msg1.
    await inputs.put("msg2")
    # Yield so the loop reads msg2 into the pending deque.
    for _ in range(20):
        await asyncio.sleep(0)

    # Send EOF — the loop's EOF path MUST drain msg2 before exiting.
    await inputs.put(None)
    # Yield so the loop picks up the EOF and starts draining.
    for _ in range(20):
        await asyncio.sleep(0)

    # Release msg1; the drain proceeds and msg2 runs.
    finish_msg1.set()
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert executed == ["msg1-start", "msg1-end", "msg2"], f"EOF drain order broke: {executed}"


@pytest.mark.asyncio
async def test_ctrl_d_finalizes_inflight_turn_before_exit(monkeypatch) -> None:
    """Ctrl-D awaits the in-flight turn — it does NOT cancel it.

    Push msg1 (slow turn) then EOF while msg1 is still in flight. The
    turn MUST complete normally; the loop's EOF path awaits it.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    msg1_started = asyncio.Event()
    msg1_cancelled: list[bool] = [False]

    async def _dispatch(user_input: str) -> bool:
        if user_input == "msg1":
            executed.append("msg1-start")
            msg1_started.set()
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                msg1_cancelled[0] = True
                raise
            executed.append("msg1-end")
            return True
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cancel: list[object] = []
    captured_shutdown: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cancel, captured_shutdown)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("msg1")
    await asyncio.wait_for(msg1_started.wait(), timeout=2.0)

    # Send EOF while msg1 is still parked on its sleep.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert msg1_cancelled[0] is False, "in-flight turn must not be cancelled on EOF"
    assert executed == ["msg1-start", "msg1-end"], (
        f"in-flight turn did not finalize before exit: {executed}"
    )


@pytest.mark.asyncio
async def test_run_concurrent_repl_registers_shutdown_callback(monkeypatch) -> None:
    """`_run_concurrent_repl` MUST register a shutdown callback with the
    ChatApplication so the Ctrl-C double-press path has somewhere to
    route EOF emission.

    Pins the wiring: when the loop runs, `set_shutdown_callback` is
    called with a non-None callable, and on shutdown the registration is
    cleared back to None. Bare wiring-only test — the actual EOF-drain
    semantics are covered by ``test_ctrl_d_drains_pending_queue_before_exit``
    and ``test_ctrl_d_finalizes_inflight_turn_before_exit``.
    """
    from opensquilla.cli import chat_cmd

    async def _dispatch(user_input: str) -> bool:
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cancel: list[object] = []
    captured_shutdown: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cancel, captured_shutdown)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    # Push EOF immediately so the loop exits cleanly.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    # The helper must register exactly one non-None shutdown callback at
    # entry, then clear it back to None in the finally block.
    non_none = [cb for cb in captured_shutdown if cb is not None]
    assert len(non_none) == 1, (
        f"expected one non-None shutdown callback registration, got {captured_shutdown}"
    )
    assert captured_shutdown[-1] is None, (
        f"shutdown callback was not cleared on teardown: {captured_shutdown}"
    )


def test_double_ctrl_c_window_constant_is_configurable() -> None:
    """The 1.5s window must live as a module-level constant.

    Pinned by the spec: tests can monkeypatch the constant to test
    edge cases without flaky real-clock waits.
    """
    assert isinstance(_DOUBLE_CTRL_C_WINDOW_S, float)
    assert _DOUBLE_CTRL_C_WINDOW_S == 1.5
