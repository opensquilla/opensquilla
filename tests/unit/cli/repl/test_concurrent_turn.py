"""Turn-as-child-task + Ctrl+G cancel + pending FIFO.

Turn execution moves off the main REPL coroutine onto a child task so the
input task keeps accepting keystrokes during streaming. Ctrl+G cancels the
in-flight turn task via the registered cancel callback; the engine treats
`asyncio.CancelledError` as the abort signal at the next `await` point
(`engine/runtime.py:2318-2366`) so no engine modification is required.

These tests pin:
  - The ChatApplication's buffer accepts keystrokes while a turn task is in
    flight (the load-bearing UX invariant).
  - The Ctrl+G cancel callback cancels the turn task.
  - `ChatApplication.set_cancel_callback` / `_invoke_cancel_callback` route
    a registered callable as expected.
  - Pending inputs received while a turn task is in flight are processed in
    FIFO order after the in-flight turn finishes.
  - Ctrl+D / EOF surfaces cleanly even when a turn task is in flight (no
    orphan tasks left on the loop).
"""

from __future__ import annotations

import asyncio

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.output import DummyOutput

from opensquilla.cli.repl.app import ChatApplication
from opensquilla.cli.repl.terminal_surface import TerminalSurface
from opensquilla.engine.commands import Surface


def _fresh_chat_app(*, pipe_input=None) -> ChatApplication:
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
        input=pipe_input if pipe_input is not None else DummyInput(),
        output=DummyOutput(),
    )


# --------------------------------------------------------------------------- #
# Cancel-callback unit surface                                                #
# --------------------------------------------------------------------------- #


def test_chat_application_invokes_cancel_callback() -> None:
    """`_invoke_cancel_callback` MUST invoke the registered callable.

    The Ctrl+G key binding (`app.py:_build_key_bindings`) routes through
    this method, so the chat REPL can register a turn-cancel handler
    without the binding needing direct access to the task handle.
    """
    chat_app = _fresh_chat_app()
    sentinel: list[bool] = [False]

    def _cb() -> None:
        sentinel[0] = True

    chat_app.set_cancel_callback(_cb)
    chat_app._invoke_cancel_callback()
    assert sentinel[0] is True


def test_chat_application_cancel_callback_clears_to_none() -> None:
    """Passing None to `set_cancel_callback` deregisters the callable."""
    chat_app = _fresh_chat_app()
    fired: list[bool] = [False]

    chat_app.set_cancel_callback(lambda: fired.append(True))
    chat_app.set_cancel_callback(None)
    chat_app._invoke_cancel_callback()
    assert fired == [False]


def test_chat_application_cancel_callback_swallows_exceptions() -> None:
    """A bad callback must not propagate out of the key binding.

    Exceptions raised by the callback would otherwise tear down the
    Application's run loop — the binding therefore swallows them.
    """
    chat_app = _fresh_chat_app()

    def _boom() -> None:
        raise RuntimeError("boom")

    chat_app.set_cancel_callback(_boom)
    # Must not raise.
    chat_app._invoke_cancel_callback()


# --------------------------------------------------------------------------- #
# Turn-task lifecycle                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ctrl_g_callback_cancels_inflight_turn() -> None:
    """Registered cancel callback cancels the in-flight turn task.

    The chat REPL registers a callable that calls `turn_task.cancel()`;
    cancellation lands at the next `await` point so a synthetic turn that
    just sleeps cancels promptly.
    """
    chat_app = _fresh_chat_app()
    turn_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(5))

    def _cancel() -> None:
        if not turn_task.done():
            turn_task.cancel()

    chat_app.set_cancel_callback(_cancel)

    # Yield once so the synthetic turn parks on its sleep.
    await asyncio.sleep(0)

    # Simulate the Ctrl+G keypress firing.
    chat_app._invoke_cancel_callback()

    with pytest.raises(asyncio.CancelledError):
        await turn_task
    assert turn_task.cancelled() is True


def test_ctrl_c_binding_invokes_cancel_callback_and_clears_buffer() -> None:
    """Ctrl+C must match the advertised banner contract.

    `chat_cmd.py` banners advertise: "Ctrl+C cancels the current turn or
    clears input". The Application's Ctrl+C key handler therefore invokes
    the registered cancel callback (no-op when no turn is in flight) AND
    resets the input buffer. Both halves of the contract land regardless
    of whether a turn is in flight; the cancel callback itself is
    responsible for guarding on `turn_task is None or turn_task.done()`.
    """
    from prompt_toolkit.key_binding import KeyBindings

    from opensquilla.cli.repl.app import _build_key_bindings

    bindings = _build_key_bindings()
    assert isinstance(bindings, KeyBindings)

    # Find the Ctrl+C binding handler. prompt-toolkit key bindings are stored
    # as a list of Binding objects; locate the one whose key sequence is
    # ("c-c",).
    ctrl_c_handlers = [binding for binding in bindings.bindings if tuple(binding.keys) == ("c-c",)]
    assert len(ctrl_c_handlers) == 1, (
        f"expected exactly one c-c binding, found {len(ctrl_c_handlers)}"
    )
    handler = ctrl_c_handlers[0].handler

    chat_app = _fresh_chat_app()
    cancel_calls: list[None] = []
    chat_app.set_cancel_callback(lambda: cancel_calls.append(None))

    # Pre-load the buffer to verify the reset half of the contract.
    chat_app._buffer.text = "half-typed input"
    assert chat_app._buffer.text == "half-typed input"

    # Build a minimal event stub mimicking prompt-toolkit's KeyPressEvent.
    class _FakeEvent:
        def __init__(self, app):
            self.app = app

    handler(_FakeEvent(chat_app.application))

    assert cancel_calls == [None], (
        "Ctrl+C must invoke the registered cancel callback so the "
        "advertised `cancels the current turn` semantics hold."
    )
    assert chat_app._buffer.text == "", (
        "Ctrl+C must also clear the input buffer so the advertised `clears input` semantics hold."
    )


def test_ctrl_c_binding_safe_with_no_callback_registered() -> None:
    """Ctrl+C at idle (no registered callback) is a clean clear-buffer.

    Default state has no cancel callback. Pressing Ctrl+C must NOT raise;
    it must just clear the buffer.
    """
    from opensquilla.cli.repl.app import _build_key_bindings

    bindings = _build_key_bindings()
    handler = next(b.handler for b in bindings.bindings if tuple(b.keys) == ("c-c",))

    chat_app = _fresh_chat_app()
    chat_app._buffer.text = "draft"
    assert chat_app._cancel_callback is None

    class _FakeEvent:
        def __init__(self, app):
            self.app = app

    handler(_FakeEvent(chat_app.application))  # MUST NOT raise

    assert chat_app._buffer.text == ""


# --------------------------------------------------------------------------- #
# Concurrent input during stream                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_user_can_type_during_stream() -> None:
    """Input buffer accepts keystrokes while a synthetic turn task runs.

    Drives the ChatApplication via `create_pipe_input`; feeds characters
    into the pipe while a synthetic slow turn is awake. The buffer text
    must accumulate the typed characters as the Application's input loop
    services them in parallel with the turn task.
    """
    with create_pipe_input() as pipe:
        chat_app = _fresh_chat_app(pipe_input=pipe)
        app_task = asyncio.create_task(chat_app.application.run_async())
        # Give the Application time to attach to its input/output pair.
        await asyncio.sleep(0.05)

        async def _slow_turn() -> None:
            # Simulate a streaming turn: small chunks with yield points so
            # the Application's run loop can interleave key processing.
            for _ in range(10):
                await asyncio.sleep(0.02)

        turn_task = asyncio.create_task(_slow_turn())

        # While the turn task is in flight, feed characters into the pipe.
        # The Application MUST surface them on `_buffer.text`.
        pipe.send_text("hello")
        # Drain the input event a few times so prompt-toolkit definitely
        # processes the bytes.
        for _ in range(20):
            await asyncio.sleep(0.01)
            if chat_app._buffer.text == "hello":
                break

        try:
            assert chat_app._buffer.text == "hello", (
                f"buffer did not accept keystrokes during streaming: got {chat_app._buffer.text!r}"
            )
        finally:
            await turn_task
            chat_app.application.exit()
            try:
                await asyncio.wait_for(app_task, timeout=1.0)
            except (TimeoutError, asyncio.CancelledError):
                app_task.cancel()


# --------------------------------------------------------------------------- #
# Pending-commands FIFO via _run_concurrent_repl                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pending_commands_queue_during_turn(monkeypatch) -> None:
    """Inputs that arrive during a turn process in FIFO order after it ends.

    Drives the `_run_concurrent_repl` helper directly with a fake
    `interactive_session` whose `next_line()` releases inputs paced to
    expose the ordering invariant. The dispatch records each call in
    order; the assertion is that the 2nd and 3rd inputs run after the 1st
    turn completes and in arrival order.
    """
    from contextlib import asynccontextmanager

    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    in_first_turn = asyncio.Event()
    finish_first_turn = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        if user_input == "first":
            in_first_turn.set()
            await finish_first_turn.wait()
        return True

    # Pipeline inputs through an asyncio.Queue so we can interleave.
    inputs: asyncio.Queue[str | None] = asyncio.Queue()

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return await inputs.get()

        def set_toolbar(self, key, value) -> None:
            return None

        def set_cancel_callback(self, cb) -> None:
            return None

        def set_shutdown_callback(self, cb) -> None:
            return None

        def emit_eof(self) -> None:
            inputs.put_nowait(None)

        def invalidate(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            return None

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle())

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    # Feed first input; wait until the first turn parks.
    await inputs.put("first")
    await asyncio.wait_for(in_first_turn.wait(), timeout=2.0)

    # Now queue two more inputs while the first turn is still in flight.
    await inputs.put("second")
    await inputs.put("third")
    # Yield so the loop reads them and stashes them in pending_commands.
    for _ in range(10):
        await asyncio.sleep(0)

    # Release the first turn; the pending commands must drain in order.
    finish_first_turn.set()

    # Feed a quit sentinel so the loop exits cleanly after draining.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert executed == ["first", "second", "third"], (
        f"pending commands did not drain in FIFO order: {executed}"
    )


@pytest.mark.asyncio
async def test_queued_turn_announces_when_promoted(monkeypatch) -> None:
    """A queued input gets a short scrollback marker when it becomes active."""
    from contextlib import asynccontextmanager

    from opensquilla.cli import chat_cmd

    events: list[tuple[str, str]] = []
    in_first_turn = asyncio.Event()
    finish_first_turn = asyncio.Event()
    second_started = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        events.append(("dispatch", user_input))
        if user_input == "first":
            in_first_turn.set()
            await finish_first_turn.wait()
        if user_input == "second":
            second_started.set()
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return await inputs.get()

        def set_toolbar(self, key, value) -> None:
            return None

        def set_cancel_callback(self, cb) -> None:
            return None

        def set_shutdown_callback(self, cb) -> None:
            return None

        def emit_eof(self) -> None:
            inputs.put_nowait(None)

        def invalidate(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            events.append(("write", payload))

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle())

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(in_first_turn.wait(), timeout=2.0)
    await inputs.put("second")
    for _ in range(10):
        await asyncio.sleep(0)

    finish_first_turn.set()
    await asyncio.wait_for(second_started.wait(), timeout=2.0)
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    queued_markers = [
        i
        for i, event in enumerate(events)
        if event[0] == "write" and "running queued input" in event[1]
    ]
    assert queued_markers, events
    second_echo = next(
        i for i, event in enumerate(events) if event[0] == "write" and "second" in event[1]
    )
    second_dispatch = events.index(("dispatch", "second"))
    assert second_echo < queued_markers[0] < second_dispatch


@pytest.mark.asyncio
async def test_loop_exits_cleanly_on_eof(monkeypatch) -> None:
    """Ctrl+D / EOF mid-idle exits the loop without leaving stray tasks."""
    from contextlib import asynccontextmanager

    from opensquilla.cli import chat_cmd

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return None  # immediate EOF

        def set_toolbar(self, key, value) -> None:
            return None

        def set_cancel_callback(self, cb) -> None:
            return None

        def set_shutdown_callback(self, cb) -> None:
            return None

        def emit_eof(self) -> None:
            return None

        def invalidate(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            return None

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle())

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )

    async def _dispatch(user_input: str) -> bool:
        # Should never be reached — the handle returns None immediately.
        raise AssertionError("dispatch was called on EOF")

    await asyncio.wait_for(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        ),
        timeout=2.0,
    )

    # Nothing else to assert — clean exit IS the assertion. If a task were
    # left dangling, asyncio.wait_for would either timeout (above) or the
    # next test's event loop would surface a "Task was destroyed but it is
    # pending" warning.


# --------------------------------------------------------------------------- #
# End-to-end Ctrl+G cancel through the helper                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ctrl_g_cancels_inflight_turn_through_helper(monkeypatch) -> None:
    """`_run_concurrent_repl` registers a Ctrl+G cancel callback that
    actually cancels the spawned dispatch task.

    Drives the helper with a fake interactive_session whose handle exposes
    a captured cancel callback; the test invokes it while a synthetic slow
    dispatch is in flight and asserts the cancellation surfaces as a
    "Cancelled." notice in the console output (helper handles
    CancelledError and keeps the loop alive).
    """
    from contextlib import asynccontextmanager

    from opensquilla.cli import chat_cmd

    captured_cb: list[object] = []
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    dispatch_started = asyncio.Event()
    dispatch_cancelled: list[bool] = [False]

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return await inputs.get()

        def set_toolbar(self, key, value) -> None:
            return None

        def set_cancel_callback(self, cb) -> None:
            captured_cb.append(cb)

        def set_shutdown_callback(self, cb) -> None:
            return None

        def emit_eof(self) -> None:
            inputs.put_nowait(None)

        def invalidate(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            return None

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle())

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )

    async def _slow_dispatch(user_input: str) -> bool:
        dispatch_started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            dispatch_cancelled[0] = True
            raise
        return True

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope={"model": None, "session_key": None},
            dispatch=_slow_dispatch,
        )
    )

    await inputs.put("trigger")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)

    # The helper should have registered a cancel callback that fires
    # turn_task.cancel(); the latest captured non-None callback is the
    # active one.
    active_cb = next((cb for cb in reversed(captured_cb) if cb is not None), None)
    assert active_cb is not None, "no cancel callback registered"
    active_cb()  # type: ignore[misc]

    # Send EOF so the loop exits after handling the cancellation.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert dispatch_cancelled[0] is True


@pytest.mark.asyncio
async def test_ctrl_g_gateway_turn_schedules_remote_abort(monkeypatch) -> None:
    """Gateway Ctrl+G must abort the server-side turn, not just local streaming."""
    from contextlib import asynccontextmanager

    from opensquilla.cli import chat_cmd

    captured_cb: list[object] = []
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    dispatch_started = asyncio.Event()
    abort_calls: list[str] = []

    class _FakeHandle:
        async def next_line(self) -> str | None:
            return await inputs.get()

        def set_toolbar(self, key, value) -> None:
            return None

        def set_cancel_callback(self, cb) -> None:
            captured_cb.append(cb)

        def set_shutdown_callback(self, cb) -> None:
            return None

        def emit_eof(self) -> None:
            inputs.put_nowait(None)

        def invalidate(self) -> None:
            return None

        async def write_through(self, payload: str) -> None:
            return None

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle())

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )

    async def _slow_dispatch(_user_input: str) -> bool:
        dispatch_started.set()
        await asyncio.sleep(5)
        return True

    async def _abort_active_turn() -> None:
        abort_calls.append("agent:main:cli-test")

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_GATEWAY,
            scope={
                "model": None,
                "session_key": "agent:main:cli-test",
            },
            dispatch=_slow_dispatch,
            abort_active_turn=_abort_active_turn,
        )
    )

    await inputs.put("trigger")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)

    active_cb = next((cb for cb in reversed(captured_cb) if cb is not None), None)
    assert active_cb is not None, "no cancel callback registered"
    active_cb()  # type: ignore[misc]

    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert abort_calls == ["agent:main:cli-test"]


# --------------------------------------------------------------------------- #
# Slash classification routing through _run_concurrent_repl                   #
# --------------------------------------------------------------------------- #


from contextlib import asynccontextmanager  # noqa: E402


class _FakeHandle:
    """Reusable fake `interactive_session` handle for slash-routing tests.

    Reads inputs from an injected asyncio.Queue and captures cancel
    callbacks so the test driver can inspect them. Mirrors the surface
    used by ``test_pending_commands_queue_during_turn``.
    """

    def __init__(self, inputs: asyncio.Queue, captured_cb: list[object]) -> None:
        self._inputs = inputs
        self._captured_cb = captured_cb

    async def next_line(self) -> str | None:
        return await self._inputs.get()

    def set_toolbar(self, key, value) -> None:
        return None

    def set_cancel_callback(self, cb) -> None:
        self._captured_cb.append(cb)

    def set_shutdown_callback(self, cb) -> None:
        return None

    def emit_eof(self) -> None:
        self._inputs.put_nowait(None)

    def invalidate(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        return None


def _install_fake_session(monkeypatch, inputs, captured_cb) -> None:
    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield TerminalSurface(_FakeHandle(inputs, captured_cb))

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.open_terminal_surface",
        _fake_session,
    )


@pytest.mark.asyncio
async def test_clear_cancels_inflight_turn(monkeypatch) -> None:
    """`/clear` mid-turn cancels the active turn task and runs the handler.

    Drives ``_run_concurrent_repl`` with a fake dispatch that records
    each call and parks a "hello" turn on an asyncio.Event. Sending
    ``/clear`` mid-stream must:

    1. Cancel the in-flight ``"hello"`` turn task (CancelledError lands).
    2. Execute the ``/clear`` handler synchronously to completion.
    3. Leave the REPL ready for the next prompt.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    hello_started = asyncio.Event()
    hello_cancelled = asyncio.Event()
    clear_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "hello":
            executed.append("hello-start")
            hello_started.set()
            try:
                # Sleep long enough that the test's `/clear` arrives mid-turn.
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                hello_cancelled.set()
                raise
            executed.append("hello-end")
            return True
        if user_input == "/clear":
            executed.append("/clear")
            clear_completed.set()
            return True
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(hello_started.wait(), timeout=2.0)
    await inputs.put("/clear")

    # `/clear` should cancel the in-flight hello turn, then run the handler.
    await asyncio.wait_for(hello_cancelled.wait(), timeout=2.0)
    await asyncio.wait_for(clear_completed.wait(), timeout=2.0)

    # End the loop cleanly so the test does not hang on a pending Queue.get.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert "hello-start" in executed
    assert "hello-end" not in executed, "hello turn must have been cancelled before completing"
    assert "/clear" in executed


@pytest.mark.asyncio
async def test_clear_purges_pending_queue(monkeypatch) -> None:
    """`/clear` mid-turn drops everything queued behind it AND cancels the turn.

    Slash-routing criterion `test_clear_purges_pending_queue`: when a slow turn
    is streaming and B, C, D are queued behind it, `/clear` arriving must
    drop all three queued items, cancel the current turn, and run only
    the `/clear` handler.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    a_started = asyncio.Event()
    a_cancelled = asyncio.Event()
    clear_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            a_started.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                a_cancelled.set()
                raise
            executed.append("A-end")
            return True
        executed.append(user_input)
        if user_input == "/clear":
            clear_completed.set()
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    # Spawn the long-running turn A.
    await inputs.put("A")
    await asyncio.wait_for(a_started.wait(), timeout=2.0)

    # Queue B, C, D behind A while A is still parked.
    await inputs.put("/new")
    await inputs.put("/model gpt-5")
    await inputs.put("hello world")
    # Yield so the loop reads them and stashes them in pending_commands.
    for _ in range(20):
        await asyncio.sleep(0)

    # Now send /clear — must purge the deque AND cancel A.
    await inputs.put("/clear")
    await asyncio.wait_for(a_cancelled.wait(), timeout=2.0)
    await asyncio.wait_for(clear_completed.wait(), timeout=2.0)

    # End the loop.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert "A-start" in executed
    assert "A-end" not in executed
    assert "/clear" in executed
    # None of the queued commands were dispatched.
    assert "/new" not in executed, f"/new should have been purged; executed={executed}"
    assert "/model gpt-5" not in executed
    assert "hello world" not in executed


@pytest.mark.asyncio
async def test_model_command_queued_until_turn_ends(monkeypatch) -> None:
    """`/model gpt-5` mid-turn enqueues — it runs AFTER the current turn ends.

    The state-mutation set MUST NOT cancel the active turn. The slash policy
    locks `/model` to the enqueue path.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    a_started = asyncio.Event()
    finish_a = asyncio.Event()
    a_cancelled: list[bool] = [False]
    model_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            a_started.set()
            try:
                await finish_a.wait()
            except asyncio.CancelledError:
                a_cancelled[0] = True
                raise
            executed.append("A-end")
            return True
        executed.append(user_input)
        if user_input == "/model gpt-5":
            model_completed.set()
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("A")
    await asyncio.wait_for(a_started.wait(), timeout=2.0)
    await inputs.put("/model gpt-5")
    # Yield so the loop reads /model and stashes it in pending_commands.
    for _ in range(20):
        await asyncio.sleep(0)

    # /model should NOT have run yet — A is still parked.
    assert "/model gpt-5" not in executed
    assert a_cancelled[0] is False

    # Now release A; the queued /model must run after A finishes.
    finish_a.set()
    await asyncio.wait_for(model_completed.wait(), timeout=2.0)

    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    # Order must be A-start → A-end → /model gpt-5.
    assert executed.index("A-end") < executed.index("/model gpt-5")
    assert a_cancelled[0] is False


@pytest.mark.asyncio
async def test_help_during_turn_is_queued_not_immediate(monkeypatch) -> None:
    """`/help` mid-turn is queued, not immediate-executed.

    Open Question #4 is locked to ALWAYS enqueue pure-info slash
    commands — no threshold, no immediate-execute branch. This pins the
    behavior: `/help` arriving during a slow turn runs only after the
    current turn finishes.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    a_started = asyncio.Event()
    finish_a = asyncio.Event()
    help_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            a_started.set()
            await finish_a.wait()
            executed.append("A-end")
            return True
        executed.append(user_input)
        if user_input == "/help":
            help_completed.set()
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("A")
    await asyncio.wait_for(a_started.wait(), timeout=2.0)
    await inputs.put("/help")
    # Yield so the loop reads /help into the pending deque.
    for _ in range(20):
        await asyncio.sleep(0)

    # /help MUST NOT have run yet; the slash policy always enqueues.
    assert "/help" not in executed, "/help must enqueue, not run immediately"

    # Release A; /help must now run from the drained deque.
    finish_a.set()
    await asyncio.wait_for(help_completed.wait(), timeout=2.0)

    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    # Order: A-start → A-end → /help.
    assert executed == ["A-start", "A-end", "/help"]


@pytest.mark.asyncio
async def test_exit_drains_queue_then_terminates(monkeypatch) -> None:
    """`/exit` drains the pending queue, then terminates the loop.

    The slash policy locks `/exit` / `/quit` to drain-then-exit semantics.
    Queued user inputs MUST run before the loop terminates so the user
    does not lose work to an exit.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    a_started = asyncio.Event()
    finish_a = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            a_started.set()
            await finish_a.wait()
            executed.append("A-end")
            return True
        if user_input in {"/exit", "/quit"}:
            executed.append(user_input)
            return False  # terminate the loop
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    await inputs.put("A")
    await asyncio.wait_for(a_started.wait(), timeout=2.0)
    await inputs.put("B")
    await inputs.put("C")
    # Yield so the loop reads B and C into the pending deque.
    for _ in range(20):
        await asyncio.sleep(0)
    await inputs.put("/exit")
    # Yield so the loop reads the /exit input and starts draining.
    for _ in range(20):
        await asyncio.sleep(0)

    # Release A so the drain can proceed.
    finish_a.set()

    # Loop should exit after draining queued B, C and running /exit. The repl
    # task returns on its own — no EOF sentinel needed.
    await asyncio.wait_for(repl_task, timeout=2.0)

    # Order: A ran first, then B, C drained, then /exit terminated.
    assert executed[0] == "A-start"
    assert executed[-1] == "/exit"
    # B and C must both have run.
    assert "B" in executed
    assert "C" in executed
    # A-end must precede B and C (drain runs after the turn finishes).
    assert executed.index("A-end") < executed.index("B")
    assert executed.index("B") < executed.index("C")
    assert executed.index("C") < executed.index("/exit")


@pytest.mark.asyncio
async def test_pending_queue_caps_at_max_size(monkeypatch) -> None:
    """The pending deque is capped at runtime_bridge.PENDING_QUEUE_MAX_SIZE.

    Once full, further inputs are
    rejected with a console toast and the rejected input is dropped.

    The drained queue MUST contain exactly the first cap-worth of
    inputs (FIFO), confirming the policy is reject-newer-on-overflow,
    not silently-evict-oldest.
    """
    from opensquilla.cli import chat_cmd
    from opensquilla.cli import ui as cli_ui
    from opensquilla.cli.repl import runtime_bridge

    # Tighten the cap for a tractable test. The contract under test is
    # the policy itself, not the specific cap of 8.
    monkeypatch.setattr(runtime_bridge, "PENDING_QUEUE_MAX_SIZE", 3)

    captured_prints: list[str] = []

    class _FakeConsole:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, attr):
            return getattr(self._real, attr)

        def print(self, *args, **kwargs):
            for a in args:
                captured_prints.append(str(a))
            return None

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_chat_adapter.console",
        _FakeConsole(cli_ui.console),
    )

    executed: list[str] = []
    finish_a = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            await finish_a.wait()
            executed.append("A-end")
            return True
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    # Start the slow turn so subsequent inputs all hit the enqueue path.
    await inputs.put("A")
    # Give the loop a chance to dispatch A and arm next_line.
    for _ in range(20):
        await asyncio.sleep(0)
        if "A-start" in executed:
            break

    # Now flood: cap is 3 so B, C, D fit; E and F are rejected.
    for name in ("B", "C", "D", "E", "F"):
        await inputs.put(name)
    # Let the loop drain all 5 puts.
    for _ in range(50):
        await asyncio.sleep(0)

    finish_a.set()
    await inputs.put(None)  # EOF — exit after drain.
    await asyncio.wait_for(repl_task, timeout=2.0)

    # B, C, D ran (the cap-worth, in order). E and F never ran.
    assert "B" in executed and "C" in executed and "D" in executed
    assert "E" not in executed
    assert "F" not in executed
    # The reject toast fired exactly twice (one per dropped input).
    rejects = [p for p in captured_prints if "Queue full" in p]
    assert len(rejects) == 2, f"expected 2 queue-full toasts, got {len(rejects)}: {captured_prints}"


# --------------------------------------------------------------------------- #
# Promote-and-race drain (preemptible queued turns)                           #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_clear_cancels_queued_turn_during_drain(monkeypatch) -> None:
    """Promote-and-race: a queued turn that was promoted post-completion of
    its predecessor is itself cancellable by a destructive `/clear`.

    Pre-fix the post-turn drain was a private loop that awaited each
    queued item to completion before re-entering the main `asyncio.wait`
    race. A `/clear` typed while the drain processed item N sat in
    `next_line_task` unread until the entire drain finished — so the
    destructive command could not preempt a queued-then-promoted slow
    turn. This test enqueues A (slow) + B (slow); A finishes; B is
    promoted as the new turn_task; while B runs the user types `/clear`,
    and that `/clear` MUST cancel B and run.
    """
    from opensquilla.cli import chat_cmd

    executed: list[str] = []
    a_started = asyncio.Event()
    finish_a = asyncio.Event()
    b_started = asyncio.Event()
    b_cancelled = asyncio.Event()
    clear_completed = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "A":
            executed.append("A-start")
            a_started.set()
            await finish_a.wait()
            executed.append("A-end")
            return True
        if user_input == "B":
            executed.append("B-start")
            b_started.set()
            try:
                # Park indefinitely; the test cancels via `/clear`.
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                b_cancelled.set()
                raise
            executed.append("B-end")
            return True
        if user_input == "/clear":
            executed.append("/clear")
            clear_completed.set()
            return True
        executed.append(user_input)
        return True

    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    captured_cb: list[object] = []
    _install_fake_session(monkeypatch, inputs, captured_cb)

    repl_task = asyncio.create_task(
        chat_cmd._run_concurrent_repl(
            surface=Surface.CLI_STANDALONE,
            scope={"model": None, "session_key": None},
            dispatch=_dispatch,
        )
    )

    # Start A.
    await inputs.put("A")
    await asyncio.wait_for(a_started.wait(), timeout=2.0)

    # Queue B behind A while A is still parked.
    await inputs.put("B")
    # Yield enough times so the loop reads B into pending_commands.
    for _ in range(20):
        await asyncio.sleep(0)
    assert "B-start" not in executed, "B must remain queued until A finishes"

    # Release A; B is promoted as the new turn_task.
    finish_a.set()
    await asyncio.wait_for(b_started.wait(), timeout=2.0)
    assert "A-end" in executed, "A must complete before B is promoted"

    # While B (promoted from the queue) runs, send `/clear`. The promote-
    # and-race path returns to the main `asyncio.wait` race so this input
    # is observed promptly and `/clear` preempts B.
    await inputs.put("/clear")
    await asyncio.wait_for(b_cancelled.wait(), timeout=2.0)
    await asyncio.wait_for(clear_completed.wait(), timeout=2.0)

    # End the loop cleanly.
    await inputs.put(None)
    await asyncio.wait_for(repl_task, timeout=2.0)

    assert "B-end" not in executed, "promoted B turn must have been cancelled by destructive /clear"
    assert "/clear" in executed


def test_drain_pending_helper_removed() -> None:
    """Lock the contract: the private `_drain_pending` helper is gone.

    Pre-fix that helper awaited each queued item to completion inside
    its own loop, making queued turns un-preemptible by destructive
    commands. The promote-and-race rewrite removes it entirely; this
    source-level assertion prevents a future regression that reintroduces
    the un-preemptible drain.
    """
    import inspect as _inspect

    from opensquilla.cli.tui.runtime import run_tui_runtime

    source = _inspect.getsource(run_tui_runtime)
    assert "_drain_pending" not in source, (
        "_drain_pending must remain deleted — its presence indicates "
        "the un-preemptible drain regressed"
    )
    assert source.count("await _run_shutdown_drain()") == 2, (
        "expected exactly two shutdown drains (EOF + EXIT)"
    )
    assert "queued = runtime_state.promote_next()" in source
    assert "turn_task = asyncio.create_task(_run_dispatch(queued), name=task_name)" in source, (
        "steady-state queued work must promote into a new raced turn task "
        "instead of looping over the queue inline"
    )
