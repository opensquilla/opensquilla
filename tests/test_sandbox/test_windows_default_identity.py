from __future__ import annotations

import pytest


def test_offline_identity_requires_username_and_protected_password() -> None:
    from opensquilla.sandbox.backend.windows_default_identity import (
        offline_identity_from_boundary,
    )

    with pytest.raises(ValueError, match="offlineUsername"):
        offline_identity_from_boundary({"offlineUserSid": "S-1-5-21-1"})


def test_offline_identity_parses_boundary_payload() -> None:
    from opensquilla.sandbox.backend.windows_default_identity import (
        offline_identity_from_boundary,
    )

    identity = offline_identity_from_boundary(
        {
            "offlineUserSid": "S-1-5-21-100-200-300-400",
            "offlineUsername": "OpenSquillaSandbox",
            "protectedPassword": "base64-dpapi-payload",
        }
    )

    assert identity.sid == "S-1-5-21-100-200-300-400"
    assert identity.username == "OpenSquillaSandbox"
    assert identity.protected_password == "base64-dpapi-payload"


def test_protect_and_unprotect_password_round_trip(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_identity as mod

    monkeypatch.setattr(
        mod,
        "_protect_password_native",
        lambda value: f"protected:{value}",
    )
    monkeypatch.setattr(
        mod,
        "_unprotect_password_native",
        lambda value: value.removeprefix("protected:"),
    )

    protected = mod.protect_password("secret-password")

    assert protected == "protected:secret-password"
    assert mod.unprotect_password(protected) == "secret-password"


def test_logon_offline_identity_unprotects_password_before_logon(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_identity as mod

    identity = mod.OfflineSandboxIdentity(
        sid="S-1-5-21-100-200-300-400",
        username="OpenSquillaSandbox",
        protected_password="protected",
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "_unprotect_password", lambda value: "plain-password")
    monkeypatch.setattr(
        mod,
        "_logon_user_native",
        lambda username, password: calls.append((username, password)) or 123,
    )

    assert mod.logon_offline_identity(identity) == 123
    assert calls == [("OpenSquillaSandbox", "plain-password")]
