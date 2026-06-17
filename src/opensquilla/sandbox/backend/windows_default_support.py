"""Readiness probe for the Windows default sandbox."""

# mypy: disable-error-code=attr-defined

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from opensquilla.sandbox.backend.windows_default_setup import (
    default_setup_marker_path,
    read_setup_marker,
    setup_marker_is_current,
    setup_marker_proxy_allowlist_ready,
)


@dataclass(frozen=True)
class WindowsDefaultSupport:
    is_windows: bool
    ctypes_available: bool
    token_api_available: bool
    acl_api_available: bool
    setup_ready: bool
    proxy_allowlist_enforced: bool = False

    @property
    def requires_admin_setup(self) -> bool:
        return self.is_windows and self.ctypes_available and not self.setup_ready

    @property
    def default_backend_available(self) -> bool:
        return (
            self.is_windows
            and self.ctypes_available
            and self.token_api_available
            and self.acl_api_available
            and self.setup_ready
        )


def probe_windows_default_support(
    *,
    home: Path | None = None,
    proxy_ports: tuple[int, ...] = (),
) -> WindowsDefaultSupport:
    is_windows = sys.platform.startswith("win")
    if not is_windows:
        return WindowsDefaultSupport(
            is_windows=False,
            ctypes_available=False,
            token_api_available=False,
            acl_api_available=False,
            setup_ready=False,
            proxy_allowlist_enforced=False,
        )

    ctypes_ready = _ctypes_available()
    token_ready = ctypes_ready and _token_api_available()
    acl_ready = ctypes_ready and _acl_api_available()
    marker_path = default_setup_marker_path(home)
    setup_ready = setup_marker_is_current(marker_path)
    if not proxy_ports:
        marker = read_setup_marker(marker_path)
        if marker is not None and marker.network is not None:
            proxy_ports = marker.network.allowed_proxy_ports
    network_ready = bool(proxy_ports) and setup_marker_proxy_allowlist_ready(
        marker_path,
        ports=tuple(sorted(set(proxy_ports))),
    )
    return WindowsDefaultSupport(
        is_windows=True,
        ctypes_available=ctypes_ready,
        token_api_available=token_ready,
        acl_api_available=acl_ready,
        setup_ready=setup_ready,
        proxy_allowlist_enforced=token_ready and acl_ready and setup_ready and network_ready,
    )


def _ctypes_available() -> bool:
    try:
        import ctypes  # noqa: F401
    except Exception:
        return False
    return True


def _token_api_available() -> bool:
    try:
        import ctypes

        ctypes.WinDLL("advapi32", use_last_error=True)
        ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return False
    return True


def _acl_api_available() -> bool:
    try:
        import ctypes

        ctypes.WinDLL("advapi32", use_last_error=True)
    except Exception:
        return False
    return True


__all__ = ["WindowsDefaultSupport", "probe_windows_default_support"]
