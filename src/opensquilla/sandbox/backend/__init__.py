"""Sandbox backend implementations and selection helper.

Five concrete backends ship today:

* :class:`~opensquilla.sandbox.backend.bubblewrap.BubblewrapBackend` — the Linux
  primary path; uses the ``bwrap`` binary for namespace isolation.
* :class:`~opensquilla.sandbox.backend.seatbelt.SeatbeltBackend` — macOS
  primary path; uses ``sandbox-exec`` with a generated SBPL profile.
* :class:`~opensquilla.sandbox.backend.windows_appcontainer.WindowsAppContainerBackend` —
  native Windows primary path; delegates to an AppContainer helper and fails
  closed until policy enforcement is implemented.
* :class:`~opensquilla.sandbox.backend.windows_restricted_token.WindowsRestrictedTokenBackend` —
  legacy/degraded native Windows path; delegates to a restricted-token helper
  and fails closed when policy enforcement is unavailable.
* :class:`~opensquilla.sandbox.backend.noop.NoopBackend` — used when the sandbox
  feature switch is off; runs the command through the existing rlimit
  wrapper and emits a warning on every invocation so the bypass is visible
  in logs.

:func:`select_backend` picks one based on the settings + host capabilities.
"""

from __future__ import annotations

import logging
import sys

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend
from opensquilla.sandbox.backend.noop import NoopBackend
from opensquilla.sandbox.backend.seatbelt import SeatbeltBackend
from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend
from opensquilla.sandbox.backend.windows_restricted_token import WindowsRestrictedTokenBackend
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.types import SandboxBackendError

log = logging.getLogger(__name__)


def _auto_backend() -> Backend:
    """Pick the strongest available backend for the current host."""
    if sys.platform.startswith("linux"):
        bwrap = BubblewrapBackend()
        if bwrap.available():
            return bwrap
    if sys.platform == "darwin":
        seatbelt = SeatbeltBackend()
        if seatbelt.available():
            return seatbelt
    if sys.platform.startswith("win"):
        appcontainer = WindowsAppContainerBackend()
        if appcontainer.available():
            return appcontainer
        restricted_token = WindowsRestrictedTokenBackend()
        if restricted_token.available():
            return restricted_token
    return NoopBackend()


def select_backend(settings: SandboxSettings) -> Backend:
    """Return the backend matching ``settings.backend``.

    ``"auto"`` defers to :func:`_auto_backend`. Explicit choices are honoured
    even when the backend is unavailable — the caller will see an honest
    ``available() is False`` and can decide whether to degrade or abort.
    Selection is logged so operators can correlate runtime behaviour with
    config.
    """
    choice = settings.backend
    backend: Backend
    if not settings.sandbox:
        backend = NoopBackend()
    elif choice == "auto":
        backend = _auto_backend()
    elif choice == "bubblewrap":
        backend = BubblewrapBackend()
    elif choice == "seatbelt":
        backend = SeatbeltBackend()
    elif choice == "noop":
        backend = NoopBackend()
    elif choice == "windows_appcontainer":
        backend = WindowsAppContainerBackend()
    elif choice == "windows_restricted_token":
        backend = WindowsRestrictedTokenBackend()
    else:  # pragma: no cover — pydantic Literal constrains this upstream
        raise ValueError(f"unknown sandbox backend: {choice!r}")

    log.info(
        "sandbox.backend_selected: choice=%s resolved=%s available=%s",
        choice,
        backend.name,
        backend.available(),
    )
    if settings.sandbox and choice == "auto" and isinstance(backend, NoopBackend):
        raise SandboxBackendError(
            "sandbox=true but no real sandbox backend is available for backend=auto"
        )
    if settings.sandbox and choice != "noop" and not backend.available():
        raise SandboxBackendError(
            f"sandbox backend {backend.name!r} is unavailable while sandbox=true"
        )
    return backend


__all__ = [
    "Backend",
    "BubblewrapBackend",
    "NoopBackend",
    "SeatbeltBackend",
    "WindowsAppContainerBackend",
    "WindowsRestrictedTokenBackend",
    "select_backend",
]
