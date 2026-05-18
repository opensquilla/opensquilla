"""Signal handlers for the concurrent chat REPL.

Two signals are handled, both Unix-only by platform contract:

* ``SIGWINCH`` (terminal resize) — invoke a caller-supplied ``on_resize``
  callable so the prompt-toolkit ``Application`` repaints against the new
  terminal dimensions. The chat REPL passes
  ``ChatApplication.application.invalidate`` here.

* ``SIGTSTP`` (Ctrl-Z) — gated through ``is_turn_in_flight``: while a turn
  task is streaming, the signal is ignored (suspending mid-stream would
  leave stdout in an undefined state); when idle the signal is delegated
  to ``signal.SIG_DFL`` so the shell's standard "Ctrl-Z = suspend" UX is
  preserved. ``Claude Code`` / ``Codex CLI`` behave identically for the
  same reason.

Both signals are platform-guarded via ``hasattr(signal, "SIG...")``;
Windows lacks both and the install function becomes a no-op there. Per
the platform contract, automated Windows pty
coverage is deferred — Windows is manual-QA only.

The install function returns an ``uninstall`` callable that restores the
previously-registered handlers so subsequent test / REPL runs are not
polluted by a leftover SIGWINCH binding on the asyncio loop or a
leftover SIGTSTP gate on the process. Callers MUST invoke the returned
uninstall (typically in a ``try/finally``).
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _SigtstpGate:
    """Stateful SIGTSTP handler that flips behavior based on REPL state.

    The handler installed on ``signal.SIGTSTP`` checks ``is_turn_in_flight``
    on each delivery. When True it returns immediately (drops the signal
    on the floor) so the process is NOT suspended mid-stream. When False
    it re-raises the signal with the default disposition by temporarily
    restoring ``signal.SIG_DFL`` and re-sending ``SIGTSTP`` to the
    process.

    Counters are exposed for test observation: tests assert the gate
    branches were exercised without having to actually suspend the test
    runner (which would deadlock pytest).
    """

    is_turn_in_flight: Callable[[], bool]
    tstp_block_count: int = 0
    tstp_default_count: int = 0
    # Set to False by tests that want to assert the default-branch was
    # entered without actually re-raising SIGTSTP (which would suspend the
    # pytest runner). Production callers leave this True.
    _reraise_on_idle: bool = field(default=True, repr=False)

    def __call__(self, signum: int, frame: Any) -> None:  # noqa: ANN401 - signal API
        if self.is_turn_in_flight():
            # Mid-turn: drop the signal so stdout is not left in an
            # undefined state. The user can still cancel via Ctrl+G.
            self.tstp_block_count += 1
            return
        # Idle: defer to the default disposition so the shell's standard
        # Ctrl-Z UX (suspend the process; ``fg`` to resume) keeps
        # working. Restoring SIG_DFL and re-raising is the standard
        # idiom for "act as if no handler was installed for this one
        # delivery".
        self.tstp_default_count += 1
        if not self._reraise_on_idle:
            return
        # Local imports / aliases keep the hot path small. We snapshot
        # the current handler so we can restore the gate after the
        # default disposition runs.
        sig_tstp = getattr(signal, "SIGTSTP", None)
        if sig_tstp is None:
            return
        try:
            previous = signal.signal(sig_tstp, signal.SIG_DFL)
        except (OSError, ValueError):
            # Reinstall on the next install_chat_signal_handlers call;
            # nothing useful we can do here.
            return
        try:
            import os  # noqa: PLC0415 - lazy stdlib import

            os.kill(os.getpid(), sig_tstp)
        finally:
            # Reinstall the gate so future deliveries are again routed
            # through this handler.
            try:
                signal.signal(sig_tstp, previous)
            except (OSError, ValueError):
                pass


def install_chat_signal_handlers(
    *,
    loop: asyncio.AbstractEventLoop,
    on_resize: Callable[[], None],
    is_turn_in_flight: Callable[[], bool],
) -> Callable[[], None]:
    """Install SIGWINCH + SIGTSTP handlers for the chat REPL.

    Parameters:
        loop: the running asyncio loop. ``SIGWINCH`` is registered via
            ``loop.add_signal_handler`` so the invalidate callback fires
            on the loop's thread (prompt-toolkit's Application is not
            thread-safe; redrawing must happen on the loop's thread).
        on_resize: callable invoked on every SIGWINCH delivery. The chat
            REPL passes ``ChatApplication.application.invalidate``.
        is_turn_in_flight: predicate consulted on every SIGTSTP delivery
            to decide whether to drop or pass through the signal.

    Returns:
        An ``uninstall`` callable that restores the previously-registered
        handlers and removes the SIGWINCH loop handler. Idempotent.

    On platforms missing either signal (notably Windows), the
    corresponding install is silently skipped and the returned
    ``uninstall`` is a partial no-op. Calling the function with both
    signals missing returns a no-op uninstall.
    """
    sigwinch_installed = False
    sigtstp_previous: Any = None
    sigtstp_installed = False
    gate: _SigtstpGate | None = None

    # ---- SIGWINCH ---------------------------------------------------- #
    if hasattr(signal, "SIGWINCH"):
        sig_winch = signal.SIGWINCH  # type: ignore[attr-defined]

        def _on_sigwinch() -> None:
            # Swallow any exception from the caller-provided callback so a
            # bad invalidate cannot kill the asyncio signal-handler slot.
            try:
                on_resize()
            except Exception:
                pass

        try:
            loop.add_signal_handler(sig_winch, _on_sigwinch)
            sigwinch_installed = True
        except (NotImplementedError, RuntimeError):
            # Some loops (e.g. on Windows ProactorEventLoop or test
            # selectors without signal support) do not support
            # add_signal_handler. Treat as a no-op rather than failing
            # the REPL launch.
            sigwinch_installed = False

    # ---- SIGTSTP ----------------------------------------------------- #
    if hasattr(signal, "SIGTSTP"):
        sig_tstp = signal.SIGTSTP  # type: ignore[attr-defined]
        gate = _SigtstpGate(is_turn_in_flight=is_turn_in_flight)
        try:
            sigtstp_previous = signal.signal(sig_tstp, gate)
            sigtstp_installed = True
        except (OSError, ValueError):
            # ``signal.signal`` can fail off the main thread; in that
            # case we leave SIGTSTP at its prior disposition.
            gate = None
            sigtstp_installed = False

    def uninstall() -> None:
        # SIGWINCH: remove the loop handler. ``remove_signal_handler``
        # silently returns False if nothing is registered, but we still
        # guard with the install flag to avoid touching the loop on
        # platforms that never registered it.
        if sigwinch_installed and hasattr(signal, "SIGWINCH"):
            sig_winch_local = signal.SIGWINCH  # type: ignore[attr-defined]
            try:
                loop.remove_signal_handler(sig_winch_local)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        # SIGTSTP: restore the previous handler.
        if sigtstp_installed and hasattr(signal, "SIGTSTP"):
            sig_tstp_local = signal.SIGTSTP  # type: ignore[attr-defined]
            try:
                signal.signal(sig_tstp_local, sigtstp_previous)
            except (OSError, ValueError):
                pass

    # Expose the gate on the uninstall callable so tests can introspect
    # branch counters without reaching into the install function's local
    # scope. Production callers never use this attribute.
    uninstall._sigtstp_gate = gate  # type: ignore[attr-defined]
    return uninstall
