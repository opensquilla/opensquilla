from __future__ import annotations

from opensquilla.gateway.auth import Principal
from opensquilla.sandbox.run_mode_policy import hello_auth_payload


def test_owner_hello_auth_payload_allows_full_by_default() -> None:
    principal = Principal(
        role="operator",
        scopes=frozenset({"operator.read", "operator.write"}),
        is_owner=True,
        authenticated=True,
    )

    assert hello_auth_payload(principal) == {
        "principal": {
            "role": "operator",
            "scopes": ["operator.read", "operator.write"],
            "isOwner": True,
            "authenticated": True,
        },
        "runModePolicy": {
            "allowedRunModes": ["standard", "trusted", "full"],
            "defaultRunMode": "full",
            "fullHostAccessDisabledReason": None,
        },
    }


def test_unauthenticated_non_owner_hello_auth_payload_disables_full() -> None:
    principal = Principal(
        role="operator",
        scopes=frozenset({"operator.read"}),
        is_owner=False,
        authenticated=False,
    )

    assert hello_auth_payload(principal) == {
        "principal": {
            "role": "operator",
            "scopes": ["operator.read"],
            "isOwner": False,
            "authenticated": False,
        },
        "runModePolicy": {
            "allowedRunModes": ["standard", "trusted"],
            "defaultRunMode": "trusted",
            "fullHostAccessDisabledReason": "owner_required",
        },
    }
