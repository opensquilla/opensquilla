"""Shared sandbox posture status payloads."""

from __future__ import annotations

from typing import Any


def posture(config: Any) -> str:
    sandbox_enabled = bool(config.sandbox.sandbox)
    grading_enabled = bool(config.sandbox.security_grading)
    default_mode = str(config.permissions.default_mode)
    if sandbox_enabled and grading_enabled and default_mode == "off":
        return "on"
    if not sandbox_enabled and not grading_enabled and default_mode in {"bypass", "full"}:
        return default_mode
    return "custom"


def status_payload(config: Any, *, restart_required: bool = False) -> dict[str, Any]:
    return {
        "posture": posture(config),
        "sandbox": {
            "sandbox": bool(config.sandbox.sandbox),
            "security_grading": bool(config.sandbox.security_grading),
        },
        "permissions": {
            "default_mode": str(config.permissions.default_mode),
        },
        "restart_required": restart_required,
    }
