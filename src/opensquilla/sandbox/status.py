"""Shared sandbox posture status payloads."""

from __future__ import annotations

from typing import Any

from opensquilla.sandbox.run_mode import config_run_mode, display_name, execution_target


def posture(config: Any) -> str:
    return config_run_mode(config).value


def status_payload(config: Any, *, restart_required: bool = False) -> dict[str, Any]:
    run_mode = config_run_mode(config)
    return {
        "run_mode": run_mode.value,
        "run_mode_label": display_name(run_mode),
        "execution_target": execution_target(run_mode),
        "posture": run_mode.value,
        "sandbox": {
            "sandbox": bool(config.sandbox.sandbox),
            "security_grading": bool(config.sandbox.security_grading),
        },
        "permissions": {
            "default_mode": str(config.permissions.default_mode),
        },
        "restart_required": restart_required,
    }
