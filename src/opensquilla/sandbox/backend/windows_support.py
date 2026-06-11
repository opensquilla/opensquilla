"""Native Windows sandbox support probe."""

from __future__ import annotations

import sys
from dataclasses import dataclass

RESTRICTED_TOKEN_ENFORCED_ENV = "OPENSQUILLA_WINDOWS_RESTRICTED_TOKEN_ENFORCED"
PROXY_ALLOWLIST_ENFORCED_ENV = "OPENSQUILLA_WINDOWS_PROXY_ALLOWLIST_ENFORCED"


@dataclass(frozen=True)
class WindowsSandboxSupport:
    is_windows: bool
    ctypes_available: bool
    restricted_token_enforced: bool
    proxy_allowlist_enforced: bool = False

    @property
    def restricted_token_available(self) -> bool:
        return (
            self.is_windows
            and self.ctypes_available
            and self.restricted_token_enforced
        )


def probe_windows_sandbox_support() -> WindowsSandboxSupport:
    is_windows = sys.platform.startswith("win")
    ctypes_ok = _ctypes_available()

    if not is_windows:
        return WindowsSandboxSupport(
            is_windows=False,
            ctypes_available=ctypes_ok,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        )

    return WindowsSandboxSupport(
        is_windows=True,
        ctypes_available=ctypes_ok,
        restricted_token_enforced=_restricted_token_smoke_ok(),
        proxy_allowlist_enforced=_proxy_allowlist_smoke_ok(),
    )


def _ctypes_available() -> bool:
    try:
        import ctypes  # noqa: F401
    except Exception:
        return False
    return True


def _restricted_token_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_restricted_token_helper import (
            restricted_token_smoke_check,
        )

        return restricted_token_smoke_check()
    except Exception:
        return False


def _proxy_allowlist_smoke_ok() -> bool:
    return False


__all__ = [
    "PROXY_ALLOWLIST_ENFORCED_ENV",
    "RESTRICTED_TOKEN_ENFORCED_ENV",
    "WindowsSandboxSupport",
    "probe_windows_sandbox_support",
]
