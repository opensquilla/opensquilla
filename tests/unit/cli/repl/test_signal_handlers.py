"""SIGWINCH + SIGTSTP handlers for the chat REPL.

The signal-handlers module owns two pieces of behavior:

* SIGWINCH (terminal resize) → invoke a caller-supplied ``on_resize``
  callable so prompt-toolkit redraws against the new dimensions.

* SIGTSTP (Ctrl-Z) → gated by ``is_turn_in_flight``:
    - mid-turn: drop the signal (suspending mid-stream leaves stdout in
      an undefined state).
    - idle: delegate to the default disposition so the shell's standard
      Ctrl-Z UX still works.

Both signals are Unix-only; Windows lacks ``signal.SIGWINCH`` and
``signal.SIGTSTP`` entirely, so automated pty coverage is Unix-only.

The tests below are designed to NEVER actually suspend the pytest
process: the SIGTSTP gate exposes branch counters that tests observe
instead of firing real SIGTSTP through the default disposition (which
would deadlock the runner).
"""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from opensquilla.cli.repl.signal_handlers import install_chat_signal_handlers

# --------------------------------------------------------------------------- #
# Surface contract                                                            #
# --------------------------------------------------------------------------- #


def test_install_returns_uninstall_callable() -> None:
    """``install_chat_signal_handlers`` MUST return a callable.

    The chat REPL wraps the install with try/finally; the contract is
    that the returned value is callable with zero arguments so a stale
    handler does not pollute subsequent runs.
    """
    loop = asyncio.new_event_loop()
    try:
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: False,
        )
        assert callable(uninstall)
        uninstall()
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# SIGWINCH (terminal resize) — Unix-only                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not hasattr(signal, "SIGWINCH"),
    reason="SIGWINCH only exists on Unix; Windows uses a different resize API.",
)
@pytest.mark.asyncio
async def test_sigwinch_invokes_on_resize() -> None:
    """Delivering SIGWINCH MUST invoke the registered ``on_resize`` callable.

    Drives the install function with a running asyncio loop, raises a
    real SIGWINCH at the process, then yields to the loop so the
    signal-handler slot has a chance to fire. Asserts the callable's
    side-effect (counter increment) was observed.
    """
    loop = asyncio.get_running_loop()
    resize_count: list[int] = [0]

    def _on_resize() -> None:
        resize_count[0] += 1

    uninstall = install_chat_signal_handlers(
        loop=loop,
        on_resize=_on_resize,
        is_turn_in_flight=lambda: False,
    )
    try:
        os.kill(os.getpid(), signal.SIGWINCH)  # type: ignore[attr-defined]
        # Give the loop's signal handler slot a chance to run. A few
        # zero-sleeps are enough — asyncio dispatches signal handlers on
        # the next loop tick after delivery.
        for _ in range(5):
            await asyncio.sleep(0)
            if resize_count[0] >= 1:
                break
        assert resize_count[0] >= 1, "on_resize was not invoked after SIGWINCH"
    finally:
        uninstall()


# --------------------------------------------------------------------------- #
# SIGTSTP (Ctrl-Z) — Unix-only                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not hasattr(signal, "SIGTSTP"),
    reason="SIGTSTP only exists on Unix; Windows has no Ctrl-Z primitive.",
)
def test_sigtstp_blocked_during_turn() -> None:
    """When ``is_turn_in_flight`` returns True, SIGTSTP MUST be dropped.

    Verified by calling the installed gate directly and asserting the
    block counter incremented. Firing a real SIGTSTP would either be
    swallowed by the gate (good) or suspend the pytest runner (bad if
    the gate misfired into the default branch). Direct invocation
    sidesteps both risks and pins the gating logic deterministically.
    """
    loop = asyncio.new_event_loop()
    try:
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: True,
        )
        try:
            gate = uninstall._sigtstp_gate  # type: ignore[attr-defined]
            assert gate is not None, "SIGTSTP gate should be installed on Unix"
            # Directly invoke the gate as if SIGTSTP had been delivered.
            gate(signal.SIGTSTP, None)  # type: ignore[attr-defined]
            assert gate.tstp_block_count == 1
            assert gate.tstp_default_count == 0
        finally:
            uninstall()
    finally:
        loop.close()


@pytest.mark.skipif(
    not hasattr(signal, "SIGTSTP"),
    reason="SIGTSTP only exists on Unix; Windows has no Ctrl-Z primitive.",
)
def test_sigtstp_default_when_idle() -> None:
    """When ``is_turn_in_flight`` returns False, the gate MUST take the default path.

    The gate normally re-raises SIGTSTP with ``signal.SIG_DFL`` to
    actually suspend the process; doing that under pytest would
    deadlock the runner. The gate exposes a ``_reraise_on_idle`` knob
    we flip OFF for the test so we can assert only that the default
    branch was entered (counter increment) without the re-raise.
    """
    loop = asyncio.new_event_loop()
    try:
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: False,
        )
        try:
            gate = uninstall._sigtstp_gate  # type: ignore[attr-defined]
            assert gate is not None
            gate._reraise_on_idle = False  # safety: do not suspend pytest
            gate(signal.SIGTSTP, None)  # type: ignore[attr-defined]
            assert gate.tstp_default_count == 1
            assert gate.tstp_block_count == 0
        finally:
            uninstall()
    finally:
        loop.close()


@pytest.mark.skipif(
    not hasattr(signal, "SIGTSTP"),
    reason="SIGTSTP only exists on Unix; Windows has no Ctrl-Z primitive.",
)
def test_sigtstp_gate_switches_between_block_and_default() -> None:
    """The gate's branch is decided per delivery, not at install time.

    Pins the requirement that the gate consults
    ``is_turn_in_flight`` on every call, so a turn that finishes mid-
    REPL transitions Ctrl-Z back to "suspend the process" without
    needing a reinstall.
    """
    loop = asyncio.new_event_loop()
    try:
        flag = {"in_flight": True}
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: flag["in_flight"],
        )
        try:
            gate = uninstall._sigtstp_gate  # type: ignore[attr-defined]
            assert gate is not None
            gate._reraise_on_idle = False
            # First call: in-flight → blocked.
            gate(signal.SIGTSTP, None)  # type: ignore[attr-defined]
            # Second call: idle → default branch.
            flag["in_flight"] = False
            gate(signal.SIGTSTP, None)  # type: ignore[attr-defined]
            assert gate.tstp_block_count == 1
            assert gate.tstp_default_count == 1
        finally:
            uninstall()
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# Uninstall restoration                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not hasattr(signal, "SIGTSTP"),
    reason="SIGTSTP only exists on Unix.",
)
def test_uninstall_restores_previous_sigtstp_handler() -> None:
    """After uninstall, ``signal.getsignal(SIGTSTP)`` MUST equal the prior value.

    Pins the cleanup contract: subsequent test / REPL runs see the
    same SIGTSTP disposition they did before the chat loop ran.
    """
    sig_tstp = signal.SIGTSTP  # type: ignore[attr-defined]
    sentinel_handler = signal.getsignal(sig_tstp)

    loop = asyncio.new_event_loop()
    try:
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: False,
        )
        # During install, the gate should be the active handler.
        assert signal.getsignal(sig_tstp) is not sentinel_handler
        uninstall()
        # After uninstall, the previous handler is restored.
        assert signal.getsignal(sig_tstp) == sentinel_handler
    finally:
        loop.close()


@pytest.mark.skipif(
    not hasattr(signal, "SIGWINCH"),
    reason="SIGWINCH only exists on Unix.",
)
@pytest.mark.asyncio
async def test_uninstall_removes_sigwinch_loop_handler() -> None:
    """After uninstall, delivering SIGWINCH MUST NOT invoke ``on_resize``.

    This is the loop-side equivalent of the SIGTSTP restoration test:
    the SIGWINCH signal handler is registered via
    ``loop.add_signal_handler`` rather than ``signal.signal``, so the
    cleanup happens through ``loop.remove_signal_handler``.
    """
    loop = asyncio.get_running_loop()
    resize_count: list[int] = [0]

    def _on_resize() -> None:
        resize_count[0] += 1

    uninstall = install_chat_signal_handlers(
        loop=loop,
        on_resize=_on_resize,
        is_turn_in_flight=lambda: False,
    )
    # Confirm the install is wired before uninstall, so the comparison
    # below is meaningful.
    os.kill(os.getpid(), signal.SIGWINCH)  # type: ignore[attr-defined]
    for _ in range(5):
        await asyncio.sleep(0)
        if resize_count[0] >= 1:
            break
    assert resize_count[0] >= 1

    uninstall()
    # After uninstall, a fresh SIGWINCH must NOT bump the counter.
    baseline = resize_count[0]
    os.kill(os.getpid(), signal.SIGWINCH)  # type: ignore[attr-defined]
    for _ in range(5):
        await asyncio.sleep(0)
    assert resize_count[0] == baseline


# --------------------------------------------------------------------------- #
# Windows-style guard                                                         #
# --------------------------------------------------------------------------- #


def test_install_is_robust_when_loop_lacks_signal_support() -> None:
    """A loop that does not support ``add_signal_handler`` MUST NOT crash.

    Simulates the Windows case (where ``add_signal_handler`` raises
    ``NotImplementedError``). The install function must catch and treat
    SIGWINCH registration as a no-op. SIGTSTP install on Windows is
    skipped by ``hasattr`` so this test only exercises SIGWINCH
    robustness on the Unix loop with a faked ``add_signal_handler``.
    """

    class _FakeLoop:
        def add_signal_handler(self, *_args: object, **_kwargs: object) -> None:
            raise NotImplementedError("simulated Windows loop")

        def remove_signal_handler(self, *_args: object, **_kwargs: object) -> bool:
            return False

    uninstall = install_chat_signal_handlers(
        loop=_FakeLoop(),  # type: ignore[arg-type]
        on_resize=lambda: None,
        is_turn_in_flight=lambda: False,
    )
    # Must not raise and must remain callable.
    assert callable(uninstall)
    uninstall()


@pytest.mark.skipif(
    hasattr(signal, "SIGWINCH"),
    reason="Windows-only assertion: this branch is for environments without SIGWINCH.",
)
def test_install_is_noop_on_windows() -> None:
    """When the platform lacks SIGWINCH / SIGTSTP, install MUST be a soft no-op.

    Skipped on Unix (where the signals exist); only runs on Windows
    test environments to confirm the install / uninstall pair stays
    silent.
    """
    loop = asyncio.new_event_loop()
    try:
        uninstall = install_chat_signal_handlers(
            loop=loop,
            on_resize=lambda: None,
            is_turn_in_flight=lambda: False,
        )
        assert callable(uninstall)
        uninstall()
    finally:
        loop.close()
