"""Native Windows sandbox support probe.

This module separates "the host is Windows" from "the Windows sandbox boundary
is actually enforceable". Process-boundary readiness and managed-network
readiness are tracked separately because local filesystem-only work can run
inside AppContainer before the network allowlist layer is ready.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

APPCONTAINER_ENFORCED_ENV = "OPENSQUILLA_WINDOWS_APPCONTAINER_ENFORCED"
RESTRICTED_TOKEN_ENFORCED_ENV = "OPENSQUILLA_WINDOWS_RESTRICTED_TOKEN_ENFORCED"
PROXY_ALLOWLIST_ENFORCED_ENV = "OPENSQUILLA_WINDOWS_PROXY_ALLOWLIST_ENFORCED"


@dataclass(frozen=True, init=False)
class WindowsSandboxSupport:
    is_windows: bool
    ctypes_available: bool
    appcontainer_enforced: bool
    restricted_token_enforced: bool
    wfp_enforced: bool
    managed_proxy_enforced: bool

    def __init__(
        self,
        *,
        is_windows: bool,
        ctypes_available: bool,
        appcontainer_enforced: bool,
        restricted_token_enforced: bool,
        wfp_enforced: bool | None = None,
        managed_proxy_enforced: bool | None = None,
        proxy_allowlist_enforced: bool | None = None,
    ) -> None:
        if wfp_enforced is None:
            wfp_enforced = bool(proxy_allowlist_enforced)
        if managed_proxy_enforced is None:
            managed_proxy_enforced = bool(proxy_allowlist_enforced)

        object.__setattr__(self, "is_windows", bool(is_windows))
        object.__setattr__(self, "ctypes_available", bool(ctypes_available))
        object.__setattr__(
            self,
            "appcontainer_enforced",
            bool(appcontainer_enforced),
        )
        object.__setattr__(
            self,
            "restricted_token_enforced",
            bool(restricted_token_enforced),
        )
        object.__setattr__(self, "wfp_enforced", bool(wfp_enforced))
        object.__setattr__(
            self,
            "managed_proxy_enforced",
            bool(managed_proxy_enforced),
        )

    @property
    def proxy_allowlist_enforced(self) -> bool:
        return self.wfp_enforced and self.managed_proxy_enforced

    @property
    def appcontainer_available(self) -> bool:
        return (
            self.is_windows
            and self.ctypes_available
            and self.appcontainer_enforced
        )

    @property
    def restricted_token_available(self) -> bool:
        return (
            self.is_windows
            and self.ctypes_available
            and self.restricted_token_enforced
            and self.proxy_allowlist_enforced
        )


def probe_windows_sandbox_support() -> WindowsSandboxSupport:
    is_windows = sys.platform.startswith("win")
    ctypes_ok = _ctypes_available()

    if not is_windows:
        return WindowsSandboxSupport(
            is_windows=False,
            ctypes_available=ctypes_ok,
            appcontainer_enforced=False,
            restricted_token_enforced=False,
            wfp_enforced=False,
            managed_proxy_enforced=False,
        )

    appcontainer_ok = _appcontainer_smoke_ok()
    restricted_token_ok = _restricted_token_smoke_ok()
    wfp_ok = _wfp_smoke_ok()
    broker_ok = _broker_smoke_ok()

    return WindowsSandboxSupport(
        is_windows=True,
        ctypes_available=ctypes_ok,
        appcontainer_enforced=appcontainer_ok,
        restricted_token_enforced=restricted_token_ok,
        wfp_enforced=wfp_ok,
        managed_proxy_enforced=broker_ok,
    )


def _ctypes_available() -> bool:
    try:
        import ctypes  # noqa: F401
    except Exception:
        return False
    return True


def _appcontainer_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_primitives import (
            appcontainer_smoke_check,
        )

        return appcontainer_smoke_check()
    except Exception:
        return False


def _restricted_token_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_primitives import (
            restricted_token_smoke_check,
        )

        return restricted_token_smoke_check()
    except Exception:
        return False


def _wfp_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_wfp import wfp_smoke_check

        return wfp_smoke_check()
    except Exception:
        return False


def _broker_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_wfp import (
            managed_network_proxy_smoke_check,
        )

        return managed_network_proxy_smoke_check()
    except Exception:
        return False


__all__ = [
    "APPCONTAINER_ENFORCED_ENV",
    "PROXY_ALLOWLIST_ENFORCED_ENV",
    "RESTRICTED_TOKEN_ENFORCED_ENV",
    "WindowsSandboxSupport",
    "probe_windows_sandbox_support",
]
