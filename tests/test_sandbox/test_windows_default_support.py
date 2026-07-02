from __future__ import annotations

from pathlib import Path


def test_support_probe_reports_unavailable_off_windows(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")

    support = mod.probe_windows_default_support()

    assert support.is_windows is False
    assert support.default_backend_available is False
    assert support.proxy_allowlist_enforced is False


def test_support_probe_requires_setup_marker_on_windows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_token_api_available", lambda: True)
    monkeypatch.setattr(mod, "_acl_api_available", lambda: True)
    monkeypatch.setattr(
        mod,
        "default_setup_marker_path",
        lambda home=None: tmp_path / "setup_marker.json",
    )

    support = mod.probe_windows_default_support(home=tmp_path)

    assert support.is_windows is True
    assert support.ctypes_available is True
    assert support.setup_ready is False
    assert support.default_backend_available is False
    assert support.requires_admin_setup is True


def test_support_probe_accepts_current_setup_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod
    from opensquilla.sandbox.backend.windows_default_setup import write_setup_marker

    marker = tmp_path / "setup_marker.json"
    write_setup_marker(marker, setup_version=1)

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_token_api_available", lambda: True)
    monkeypatch.setattr(mod, "_acl_api_available", lambda: True)
    monkeypatch.setattr(mod, "default_setup_marker_path", lambda home=None: marker)

    support = mod.probe_windows_default_support(home=tmp_path)

    assert support.setup_ready is True
    assert support.default_backend_available is True
    assert support.proxy_allowlist_enforced is False


def test_support_probe_requires_network_marker_for_proxy_enforcement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod
    from opensquilla.sandbox.backend.windows_default_setup import write_setup_marker

    marker = tmp_path / "setup_marker.json"
    write_setup_marker(marker)

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_token_api_available", lambda: True)
    monkeypatch.setattr(mod, "_acl_api_available", lambda: True)
    monkeypatch.setattr(mod, "default_setup_marker_path", lambda home=None: marker)

    support = mod.probe_windows_default_support(home=tmp_path, proxy_ports=(43128,))

    assert support.default_backend_available is True
    assert support.proxy_allowlist_enforced is False


def test_support_probe_accepts_current_network_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod
    from opensquilla.sandbox.backend.windows_default_network import (
        FIREWALL_RULE_VERSION,
        WFP_RULE_VERSION,
        WindowsNetworkSetup,
    )
    from opensquilla.sandbox.backend.windows_default_setup import write_setup_marker

    marker = tmp_path / "setup_marker.json"
    write_setup_marker(
        marker,
        network=WindowsNetworkSetup(
            offline_user_sid="S-1-5-21-100-200-300-400",
            allowed_proxy_ports=(43128,),
            allow_local_binding=False,
            firewall_rule_version=FIREWALL_RULE_VERSION,
            wfp_rule_version=WFP_RULE_VERSION,
        ),
    )

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_token_api_available", lambda: True)
    monkeypatch.setattr(mod, "_acl_api_available", lambda: True)
    monkeypatch.setattr(mod, "default_setup_marker_path", lambda home=None: marker)

    support = mod.probe_windows_default_support(home=tmp_path)

    assert support.proxy_allowlist_enforced is True


def test_support_probe_rejects_legacy_firewall_network_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_support as mod
    from opensquilla.sandbox.backend.windows_default_network import (
        WFP_RULE_VERSION,
        WindowsNetworkSetup,
    )
    from opensquilla.sandbox.backend.windows_default_setup import write_setup_marker

    marker = tmp_path / "setup_marker.json"
    write_setup_marker(
        marker,
        network=WindowsNetworkSetup(
            offline_user_sid="S-1-5-21-100-200-300-400",
            allowed_proxy_ports=(43128,),
            allow_local_binding=False,
            firewall_rule_version=1,
            wfp_rule_version=WFP_RULE_VERSION,
        ),
    )

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_token_api_available", lambda: True)
    monkeypatch.setattr(mod, "_acl_api_available", lambda: True)
    monkeypatch.setattr(mod, "default_setup_marker_path", lambda home=None: marker)

    support = mod.probe_windows_default_support(home=tmp_path)

    assert support.default_backend_available is True
    assert support.proxy_allowlist_enforced is False
