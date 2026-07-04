"""Principal-aware sandbox run-mode authorization helpers."""

from __future__ import annotations

from typing import Any

from opensquilla.sandbox.run_mode import RunMode, normalize_run_mode

_OWNER_ALLOWED_RUN_MODES = (RunMode.STANDARD, RunMode.TRUSTED, RunMode.FULL)
_NON_OWNER_ALLOWED_RUN_MODES = (RunMode.STANDARD, RunMode.TRUSTED)


def principal_is_owner(principal: Any) -> bool:
    return getattr(principal, "is_owner", False) is True


def allowed_run_modes_for_principal(principal: Any) -> tuple[RunMode, ...]:
    if principal_is_owner(principal):
        return _OWNER_ALLOWED_RUN_MODES
    return _NON_OWNER_ALLOWED_RUN_MODES


def default_run_mode_for_principal(principal: Any) -> RunMode:
    if principal_is_owner(principal):
        return RunMode.FULL
    return RunMode.TRUSTED


def run_mode_allowed_for_principal(mode: Any, principal: Any) -> bool:
    try:
        normalized = normalize_run_mode(mode, default=default_run_mode_for_principal(principal))
    except ValueError:
        return False
    return normalized in allowed_run_modes_for_principal(principal)


def coerce_run_mode_for_principal(mode: Any, principal: Any) -> RunMode:
    default = default_run_mode_for_principal(principal)
    try:
        normalized = normalize_run_mode(mode, default=default)
    except ValueError:
        return default
    if normalized in allowed_run_modes_for_principal(principal):
        return normalized
    return default


def principal_payload(principal: Any) -> dict[str, Any]:
    scopes = getattr(principal, "scopes", ())
    return {
        "role": getattr(principal, "role", None),
        "scopes": sorted(str(scope) for scope in scopes),
        "isOwner": principal_is_owner(principal),
        "authenticated": bool(getattr(principal, "authenticated", False)),
    }


def run_mode_policy_payload(principal: Any) -> dict[str, Any]:
    allowed = allowed_run_modes_for_principal(principal)
    return {
        "allowedRunModes": [mode.value for mode in allowed],
        "defaultRunMode": default_run_mode_for_principal(principal).value,
        "fullHostAccessDisabledReason": None if principal_is_owner(principal) else "owner_required",
    }


def hello_auth_payload(principal: Any) -> dict[str, Any]:
    return {
        "principal": principal_payload(principal),
        "runModePolicy": run_mode_policy_payload(principal),
    }


__all__ = [
    "allowed_run_modes_for_principal",
    "coerce_run_mode_for_principal",
    "default_run_mode_for_principal",
    "hello_auth_payload",
    "principal_is_owner",
    "principal_payload",
    "run_mode_allowed_for_principal",
    "run_mode_policy_payload",
]
