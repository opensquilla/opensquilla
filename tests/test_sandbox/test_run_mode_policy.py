from __future__ import annotations

from types import SimpleNamespace

from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.run_mode_policy import (
    allowed_run_modes_for_principal,
    coerce_run_mode_for_principal,
    default_run_mode_for_principal,
    hello_auth_payload,
    principal_payload,
    run_mode_allowed_for_principal,
    run_mode_policy_payload,
)


def _principal(is_owner: bool, authenticated: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        role="operator",
        scopes=frozenset({"operator.read", "operator.write"}),
        is_owner=is_owner,
        authenticated=authenticated,
    )


def test_owner_can_use_full_host_access_by_default() -> None:
    principal = _principal(is_owner=True)

    assert allowed_run_modes_for_principal(principal) == (
        RunMode.STANDARD,
        RunMode.TRUSTED,
        RunMode.FULL,
    )
    assert default_run_mode_for_principal(principal) == RunMode.FULL
    assert run_mode_allowed_for_principal(RunMode.STANDARD, principal) is True
    assert run_mode_allowed_for_principal(RunMode.TRUSTED, principal) is True
    assert run_mode_allowed_for_principal(RunMode.FULL, principal) is True
    assert run_mode_policy_payload(principal) == {
        "allowedRunModes": ["standard", "trusted", "full"],
        "defaultRunMode": "full",
        "fullHostAccessDisabledReason": None,
    }


def test_authenticated_non_owner_cannot_use_full_host_access() -> None:
    principal = _principal(is_owner=False)

    assert allowed_run_modes_for_principal(principal) == (RunMode.STANDARD, RunMode.TRUSTED)
    assert default_run_mode_for_principal(principal) == RunMode.TRUSTED
    assert run_mode_allowed_for_principal(RunMode.STANDARD, principal) is True
    assert run_mode_allowed_for_principal(RunMode.TRUSTED, principal) is True
    assert run_mode_allowed_for_principal(RunMode.FULL, principal) is False
    assert coerce_run_mode_for_principal(RunMode.FULL, principal) == RunMode.TRUSTED
    assert run_mode_policy_payload(principal) == {
        "allowedRunModes": ["standard", "trusted"],
        "defaultRunMode": "trusted",
        "fullHostAccessDisabledReason": "owner_required",
    }


def test_unauthenticated_non_owner_uses_trusted_sandbox_policy() -> None:
    principal = _principal(is_owner=False, authenticated=False)

    assert allowed_run_modes_for_principal(principal) == (RunMode.STANDARD, RunMode.TRUSTED)
    assert default_run_mode_for_principal(principal) == RunMode.TRUSTED
    assert run_mode_allowed_for_principal(None, principal) is True
    assert coerce_run_mode_for_principal("full", principal) == RunMode.TRUSTED
    assert coerce_run_mode_for_principal("standard", principal) == RunMode.STANDARD
    assert coerce_run_mode_for_principal(None, principal) == RunMode.TRUSTED
    assert principal_payload(principal) == {
        "role": "operator",
        "scopes": ["operator.read", "operator.write"],
        "isOwner": False,
        "authenticated": False,
    }
    assert hello_auth_payload(principal) == {
        "principal": {
            "role": "operator",
            "scopes": ["operator.read", "operator.write"],
            "isOwner": False,
            "authenticated": False,
        },
        "runModePolicy": {
            "allowedRunModes": ["standard", "trusted"],
            "defaultRunMode": "trusted",
            "fullHostAccessDisabledReason": "owner_required",
        },
    }


def test_truthy_non_boolean_owner_flag_does_not_grant_owner_policy() -> None:
    principal = _principal(is_owner=False)
    principal.is_owner = "false"

    assert allowed_run_modes_for_principal(principal) == (RunMode.STANDARD, RunMode.TRUSTED)
    assert default_run_mode_for_principal(principal) == RunMode.TRUSTED
    assert run_mode_allowed_for_principal(RunMode.FULL, principal) is False
    assert coerce_run_mode_for_principal(RunMode.FULL, principal) == RunMode.TRUSTED
    assert run_mode_policy_payload(principal) == {
        "allowedRunModes": ["standard", "trusted"],
        "defaultRunMode": "trusted",
        "fullHostAccessDisabledReason": "owner_required",
    }


def test_invalid_run_mode_is_not_allowed_and_coerces_to_principal_default() -> None:
    owner = _principal(is_owner=True)
    non_owner = _principal(is_owner=False)

    assert run_mode_allowed_for_principal("nonsense", owner) is False
    assert coerce_run_mode_for_principal("nonsense", owner) == RunMode.FULL
    assert run_mode_allowed_for_principal("nonsense", non_owner) is False
    assert coerce_run_mode_for_principal("nonsense", non_owner) == RunMode.TRUSTED
