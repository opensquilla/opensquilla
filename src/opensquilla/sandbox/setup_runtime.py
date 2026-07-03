"""Runtime wrapper for automatic sandbox setup."""

from __future__ import annotations

import asyncio
from typing import Any

from opensquilla.sandbox.setup_state import (
    SandboxSetupState,
    SetupResult,
    current_sandbox_setup_status,
    ensure_sandbox_setup,
)

_LOCK = asyncio.Lock()
_SETTING_UP = False
_LAST_RESULT: SetupResult | None = None


async def current_sandbox_setup_runtime_status(config: Any) -> SetupResult:
    if _SETTING_UP:
        return SetupResult(
            state=SandboxSetupState.SETTING_UP,
            platform="auto",
            message="Sandbox setup is running.",
            requires_admin=False,
        )
    if _LAST_RESULT is not None and _LAST_RESULT.state is SandboxSetupState.FAILED:
        return _LAST_RESULT
    return await current_sandbox_setup_status(config)


async def ensure_sandbox_setup_auto(config: Any) -> SetupResult:
    global _LAST_RESULT, _SETTING_UP

    async with _LOCK:
        _SETTING_UP = True
        try:
            result = await ensure_sandbox_setup(config)
            _LAST_RESULT = result
            return result
        except Exception as exc:  # noqa: BLE001
            result = SetupResult(
                state=SandboxSetupState.FAILED,
                platform="auto",
                message="Sandbox setup failed.",
                requires_admin=False,
                detail=str(exc),
            )
            _LAST_RESULT = result
            return result
        finally:
            _SETTING_UP = False


def reset_sandbox_setup_runtime_state() -> None:
    global _LAST_RESULT, _LOCK, _SETTING_UP

    _LOCK = asyncio.Lock()
    _SETTING_UP = False
    _LAST_RESULT = None


__all__ = [
    "current_sandbox_setup_runtime_status",
    "ensure_sandbox_setup_auto",
    "reset_sandbox_setup_runtime_state",
]
