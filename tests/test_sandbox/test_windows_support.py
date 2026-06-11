from __future__ import annotations


def test_windows_support_probe_reports_restricted_token_unavailable_off_windows(
    monkeypatch,
) -> None:
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is False
    assert support.restricted_token_available is False
    assert support.proxy_allowlist_enforced is False


def test_windows_support_probe_accepts_restricted_token_with_real_checks(
    monkeypatch,
) -> None:
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_restricted_token_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_proxy_allowlist_smoke_ok", lambda: False)

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is True
    assert support.ctypes_available is True
    assert support.restricted_token_enforced is True
    assert support.restricted_token_available is True
    assert support.proxy_allowlist_enforced is False
