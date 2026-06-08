from __future__ import annotations


def test_windows_support_probe_is_false_off_windows(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_APPCONTAINER_ENFORCED", "1")
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_RESTRICTED_TOKEN_ENFORCED", "1")
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_PROXY_ALLOWLIST_ENFORCED", "1")

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is False
    assert support.appcontainer_available is False
    assert support.restricted_token_available is False


def test_windows_support_probe_ignores_old_env_flags_when_smoke_checks_fail(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_restricted_token_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_broker_smoke_ok", lambda: False)
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_APPCONTAINER_ENFORCED", "1")
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_RESTRICTED_TOKEN_ENFORCED", "1")
    monkeypatch.setenv("OPENSQUILLA_WINDOWS_PROXY_ALLOWLIST_ENFORCED", "1")

    support = mod.probe_windows_sandbox_support()

    assert support.appcontainer_enforced is False
    assert support.restricted_token_enforced is False
    assert support.proxy_allowlist_enforced is False
    assert support.appcontainer_available is False
    assert support.restricted_token_available is False


def test_windows_support_probe_uses_real_checks_not_env_flags(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_broker_smoke_ok", lambda: True)
    monkeypatch.delenv("OPENSQUILLA_WINDOWS_APPCONTAINER_ENFORCED", raising=False)
    monkeypatch.delenv("OPENSQUILLA_WINDOWS_PROXY_ALLOWLIST_ENFORCED", raising=False)

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is True
    assert support.ctypes_available is True
    assert support.appcontainer_enforced is True
    assert support.wfp_enforced is True
    assert support.managed_proxy_enforced is True
    assert support.proxy_allowlist_enforced is True
    assert support.appcontainer_available is True


def test_windows_support_probe_accepts_restricted_token_with_real_checks(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_restricted_token_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_broker_smoke_ok", lambda: True)

    support = mod.probe_windows_sandbox_support()

    assert support.appcontainer_available is False
    assert support.restricted_token_enforced is True
    assert support.wfp_enforced is True
    assert support.managed_proxy_enforced is True
    assert support.proxy_allowlist_enforced is True
    assert support.restricted_token_available is True


def test_windows_support_probe_ignores_runtime_proxy_context(monkeypatch):
    from opensquilla.sandbox import integration
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_restricted_token_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: True)
    token = integration._MANAGED_NETWORK_PROXY_URL.set("http://127.0.0.1:18080")
    try:
        support = mod.probe_windows_sandbox_support()
    finally:
        integration._MANAGED_NETWORK_PROXY_URL.reset(token)

    assert support.proxy_allowlist_enforced is False
    assert support.appcontainer_available is True


def test_windows_support_probe_distinguishes_missing_wfp(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: False)
    monkeypatch.setattr(mod, "_broker_smoke_ok", lambda: True)

    support = mod.probe_windows_sandbox_support()

    assert support.appcontainer_enforced is True
    assert support.wfp_enforced is False
    assert support.managed_proxy_enforced is True
    assert support.proxy_allowlist_enforced is False
    assert support.appcontainer_available is True


def test_windows_support_probe_distinguishes_missing_managed_proxy(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_appcontainer_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_wfp_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_broker_smoke_ok", lambda: False)

    support = mod.probe_windows_sandbox_support()

    assert support.appcontainer_enforced is True
    assert support.wfp_enforced is True
    assert support.managed_proxy_enforced is False
    assert support.proxy_allowlist_enforced is False
    assert support.appcontainer_available is True


def test_windows_smoke_checks_default_to_conservative_false(monkeypatch):
    import sys

    from opensquilla.sandbox.backend import windows_primitives, windows_wfp

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        windows_primitives,
        "_get_win32_api",
        lambda: (_ for _ in ()).throw(RuntimeError("win32 unavailable")),
    )

    assert windows_primitives.appcontainer_smoke_check() is False
    assert windows_primitives.restricted_token_smoke_check() is False
    assert windows_wfp.managed_network_proxy_smoke_check() is False
    assert windows_wfp.wfp_smoke_check() is False
