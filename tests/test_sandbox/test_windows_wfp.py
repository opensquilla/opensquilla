from __future__ import annotations

import pytest


def test_wfp_policy_names_are_stable() -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    assert mod.WFP_PROVIDER_NAME == "OpenSquilla Sandbox Network Policy"
    assert mod.WFP_SUBLAYER_NAME == "OpenSquilla AppContainer Broker-Only Egress"


@pytest.mark.parametrize(
    ("provider_installed", "filters_installed", "expected"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ],
)
def test_wfp_smoke_check_requires_windows_provider_and_filters(
    monkeypatch,
    provider_installed: bool,
    filters_installed: bool,
    expected: bool,
) -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_provider_installed", lambda: provider_installed)
    monkeypatch.setattr(mod, "_required_filters_installed", lambda: filters_installed)

    assert mod.wfp_smoke_check() is expected


def test_wfp_smoke_check_is_false_off_windows_even_when_hooks_pass(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod, "_provider_installed", lambda: True)
    monkeypatch.setattr(mod, "_required_filters_installed", lambda: True)

    assert mod.wfp_smoke_check() is False


def test_install_wfp_policy_validates_sid_host_port_and_platform(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(
        mod,
        "_install_wfp_policy_native",
        lambda **kwargs: calls.append(kwargs),
    )

    mod.install_wfp_policy(
        appcontainer_sid="S-1-15-2-12345",
        broker_host="127.0.0.1",
        broker_port=18080,
    )

    assert calls == [
        {
            "appcontainer_sid": "S-1-15-2-12345",
            "broker_host": "127.0.0.1",
            "broker_port": 18080,
        }
    ]

    with pytest.raises(RuntimeError, match="requires Windows"):
        monkeypatch.setattr(mod.sys, "platform", "linux")
        mod.install_wfp_policy(
            appcontainer_sid="S-1-15-2-12345",
            broker_host="127.0.0.1",
            broker_port=18080,
        )

    monkeypatch.setattr(mod.sys, "platform", "win32")
    with pytest.raises(ValueError, match="AppContainer SID"):
        mod.install_wfp_policy(
            appcontainer_sid="S-1-5-21-12345",
            broker_host="127.0.0.1",
            broker_port=18080,
        )
    with pytest.raises(ValueError, match="broker_host"):
        mod.install_wfp_policy(
            appcontainer_sid="S-1-15-2-12345",
            broker_host="",
            broker_port=18080,
        )
    with pytest.raises(ValueError, match="broker_port"):
        mod.install_wfp_policy(
            appcontainer_sid="S-1-15-2-12345",
            broker_host="127.0.0.1",
            broker_port=0,
        )
    with pytest.raises(ValueError, match="broker_port"):
        mod.install_wfp_policy(
            appcontainer_sid="S-1-15-2-12345",
            broker_host="127.0.0.1",
            broker_port=65536,
        )


def test_uninstall_wfp_policy_validates_platform_and_delegates(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    calls: list[str] = []
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_uninstall_wfp_policy_native", lambda: calls.append("called"))

    mod.uninstall_wfp_policy()

    assert calls == ["called"]

    monkeypatch.setattr(mod.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="requires Windows"):
        mod.uninstall_wfp_policy()


def test_default_native_hooks_and_probes_fail_closed(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_wfp as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")

    assert mod._provider_installed() is False
    assert mod._required_filters_installed() is False
    assert mod.managed_network_proxy_smoke_check() is False
    assert mod.wfp_smoke_check() is False
    with pytest.raises(RuntimeError, match="native WFP policy install is not implemented"):
        mod._install_wfp_policy_native(
            appcontainer_sid="S-1-15-2-12345",
            broker_host="127.0.0.1",
            broker_port=18080,
        )
    with pytest.raises(RuntimeError, match="native WFP policy uninstall is not implemented"):
        mod._uninstall_wfp_policy_native()
