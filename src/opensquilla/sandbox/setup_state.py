"""Platform-neutral sandbox setup state."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SandboxSetupState(StrEnum):
    NOT_SETUP = "not_setup"
    SETTING_UP = "setting_up"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SetupResult:
    state: SandboxSetupState
    platform: str
    message: str
    requires_admin: bool = False
    detail: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": self.state.value,
            "platform": self.platform,
            "message": self.message,
            "requiresAdmin": self.requires_admin,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class WindowsSetupSupport:
    restricted_token_available: bool
    ctypes_available: bool
    restricted_token_enforced: bool
    proxy_allowlist_enforced: bool


def _platform_name(platform: str | None = None) -> str:
    value = platform or sys.platform
    if value.startswith("win"):
        return "win32"
    if value == "darwin":
        return "darwin"
    if value.startswith("linux"):
        return "linux"
    return value


def _requires_admin(platform: str) -> bool:
    _ = platform
    return False


def setup_status_payload(
    state: SandboxSetupState,
    *,
    platform: str | None = None,
    message: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    normalized_platform = _platform_name(platform)
    default_message = {
        SandboxSetupState.NOT_SETUP: "Sandbox setup has not been completed.",
        SandboxSetupState.SETTING_UP: "Sandbox setup is running.",
        SandboxSetupState.READY: "Sandbox setup is ready.",
        SandboxSetupState.FAILED: "Sandbox setup failed.",
        SandboxSetupState.UNAVAILABLE: "Sandbox setup is unavailable on this host.",
    }[state]
    return SetupResult(
        state=state,
        platform=normalized_platform,
        message=message or default_message,
        requires_admin=_requires_admin(normalized_platform),
        detail=detail,
    ).to_payload()


async def current_sandbox_setup_status(config: Any) -> SetupResult:
    platform = _platform_name()
    if platform == "win32":
        return await _windows_setup_status(config)
    return await _portable_setup_status(config, platform=platform)


async def ensure_sandbox_setup(config: Any) -> SetupResult:
    platform = _platform_name()
    if platform == "win32":
        return await _ensure_windows_setup(config)
    return await _ensure_portable_setup(config, platform=platform)


async def _windows_setup_status(config: Any) -> SetupResult:
    _ = config
    return _windows_restricted_token_setup_result()


async def _ensure_windows_setup(config: Any) -> SetupResult:
    _ = config
    return _windows_restricted_token_setup_result()


def _windows_restricted_token_setup_result() -> SetupResult:
    support = _probe_windows_sandbox_support()
    if support.restricted_token_available:
        detail = None
        if not support.proxy_allowlist_enforced:
            detail = "proxy_allowlist=not ready"
        return SetupResult(
            state=SandboxSetupState.READY,
            platform="win32",
            message="Windows restricted-token sandbox is ready.",
            requires_admin=False,
            detail=detail,
        )

    reasons: list[str] = []
    if not support.ctypes_available:
        reasons.append("ctypes=missing")
    if not support.restricted_token_enforced:
        reasons.append("restricted_token=not ready")
    if not reasons:
        reasons.append("restricted_token=not ready")
    return SetupResult(
        state=SandboxSetupState.UNAVAILABLE,
        platform="win32",
        message="Windows restricted-token sandbox is unavailable on this host.",
        requires_admin=False,
        detail=", ".join(reasons),
    )


def _probe_windows_sandbox_support() -> WindowsSetupSupport:
    from opensquilla.sandbox.backend.windows_support import (
        probe_windows_sandbox_support,
    )

    support = probe_windows_sandbox_support()
    return WindowsSetupSupport(
        restricted_token_available=support.restricted_token_available,
        ctypes_available=support.ctypes_available,
        restricted_token_enforced=support.restricted_token_enforced,
        proxy_allowlist_enforced=support.proxy_allowlist_enforced,
    )


async def _portable_setup_status(config: Any, *, platform: str) -> SetupResult:
    _ = config
    return SetupResult(
        state=SandboxSetupState.READY,
        platform=platform,
        message="Sandbox setup is ready.",
        requires_admin=False,
    )


async def _ensure_portable_setup(config: Any, *, platform: str) -> SetupResult:
    _ = config
    return SetupResult(
        state=SandboxSetupState.READY,
        platform=platform,
        message="Sandbox setup is ready.",
        requires_admin=False,
    )


__all__ = [
    "SandboxSetupState",
    "SetupResult",
    "WindowsSetupSupport",
    "current_sandbox_setup_status",
    "ensure_sandbox_setup",
    "setup_status_payload",
]
