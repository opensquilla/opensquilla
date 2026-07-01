"""Native-backend Ctrl+C handling: a SIGINT handler cancels the in-flight turn
and never exits the session (Ctrl+D still owns exit), fixing the old behavior
where a single Ctrl+C at the prompt was treated as EOF and quit chat."""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from opensquilla.cli.tui.adapters import native_bridge
from opensquilla.cli.tui.adapters.native_bridge import (
    NativeTerminalSurface,
    open_native_terminal_surface,
)
from opensquilla.engine.commands import Surface


@pytest.mark.asyncio
async def test_ctrl_d_ends_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_input(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(native_bridge.console, "input", fake_input)
    surface = NativeTerminalSurface(approval_surface=Surface.CLI_GATEWAY)
    shutdown: list[bool] = []
    surface.set_shutdown_callback(lambda: shutdown.append(True))

    assert await surface.next_line() is None
    assert shutdown == [True]


@pytest.mark.asyncio
async def test_keyboardinterrupt_fallback_cancels_and_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fallback path (used where add_signal_handler is unavailable): a
    # KeyboardInterrupt must cancel the in-flight turn and re-prompt, never exit.
    calls = 0

    def fake_input(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return "after the interrupt"

    monkeypatch.setattr(native_bridge.console, "input", fake_input)
    surface = NativeTerminalSurface(approval_surface=Surface.CLI_GATEWAY)
    cancelled: list[bool] = []
    shutdown: list[bool] = []
    surface.set_cancel_callback(lambda: cancelled.append(True))
    surface.set_shutdown_callback(lambda: shutdown.append(True))

    assert await surface.next_line() == "after the interrupt"
    assert cancelled == [True]
    assert shutdown == []  # never shuts down on Ctrl+C


def test_on_sigint_cancels_turn_without_exiting() -> None:
    surface = NativeTerminalSurface(approval_surface=Surface.CLI_GATEWAY)
    cancelled: list[bool] = []
    shutdown: list[bool] = []
    surface.set_cancel_callback(lambda: cancelled.append(True))
    surface.set_shutdown_callback(lambda: shutdown.append(True))

    surface._on_sigint()

    assert cancelled == [True]
    assert shutdown == []


@pytest.mark.asyncio
async def test_real_sigint_cancels_turn_and_does_not_exit() -> None:
    cancelled: list[bool] = []
    shutdown: list[bool] = []
    async with open_native_terminal_surface(surface=Surface.CLI_GATEWAY) as surface:
        surface.set_cancel_callback(lambda: cancelled.append(True))
        surface.set_shutdown_callback(lambda: shutdown.append(True))
        os.kill(os.getpid(), signal.SIGINT)  # the real Ctrl+C signal
        await asyncio.sleep(0.05)  # let the loop run the installed handler

    assert cancelled == [True]  # the turn was cancelled
    assert shutdown == []  # the session did NOT exit
