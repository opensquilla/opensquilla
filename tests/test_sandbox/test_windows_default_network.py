from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.windows_default_network import (
    blocked_loopback_tcp_remote_ports,
    network_proxy_env,
    proxy_ports_from_env,
)


def test_proxy_ports_from_env_collects_loopback_proxy_ports() -> None:
    env = {
        "HTTP_PROXY": "http://127.0.0.1:43128",
        "HTTPS_PROXY": "http://localhost:43128",
        "ALL_PROXY": "http://user:pass@[::1]:43129",
        "NO_PROXY": "example.com",
        "BAD_PROXY": "http://127.0.0.1:1",
    }

    assert proxy_ports_from_env(env) == (43128, 43129)


def test_proxy_ports_from_env_ignores_non_loopback_and_invalid_values() -> None:
    env = {
        "HTTP_PROXY": "http://proxy.example:8080",
        "HTTPS_PROXY": "not-a-url",
        "ALL_PROXY": "http://127.0.0.1:notaport",
    }

    assert proxy_ports_from_env(env) == ()


def test_network_proxy_env_overrides_user_proxy_settings() -> None:
    env = network_proxy_env("127.0.0.1", 48123)

    assert {
        key: env[key]
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "npm_config_https_proxy",
            "NPM_CONFIG_HTTPS_PROXY",
            "PIP_PROXY",
            "WS_PROXY",
            "WSS_PROXY",
        )
    } == {
        "HTTP_PROXY": "http://127.0.0.1:48123",
        "HTTPS_PROXY": "http://127.0.0.1:48123",
        "http_proxy": "http://127.0.0.1:48123",
        "https_proxy": "http://127.0.0.1:48123",
        "ALL_PROXY": "http://127.0.0.1:48123",
        "all_proxy": "http://127.0.0.1:48123",
        "npm_config_https_proxy": "http://127.0.0.1:48123",
        "NPM_CONFIG_HTTPS_PROXY": "http://127.0.0.1:48123",
        "PIP_PROXY": "http://127.0.0.1:48123",
        "WS_PROXY": "http://127.0.0.1:48123",
        "WSS_PROXY": "http://127.0.0.1:48123",
    }
    assert env["NO_PROXY"]
    assert env["no_proxy"] == env["NO_PROXY"]
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.sslBackend"
    assert env["GIT_CONFIG_VALUE_0"] == "openssl"
    assert env["OPENSQUILLA_SANDBOX_NETWORK"] == "proxy_allowlist"


def test_blocked_loopback_tcp_remote_ports_complements_allowed_ports() -> None:
    assert blocked_loopback_tcp_remote_ports((43128, 43130)) == (
        "1-43127",
        "43129",
        "43131-65535",
    )


def test_setup_marker_round_trips_network_state(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_network import (
        FIREWALL_RULE_VERSION,
        WFP_RULE_VERSION,
        WindowsNetworkSetup,
    )
    from opensquilla.sandbox.backend.windows_default_setup import (
        read_setup_marker,
        write_setup_marker,
    )

    marker_path = tmp_path / "setup_marker.json"
    network = WindowsNetworkSetup(
        offline_user_sid="S-1-5-21-100-200-300-400",
        allowed_proxy_ports=(43128,),
        allow_local_binding=False,
        firewall_rule_version=FIREWALL_RULE_VERSION,
        wfp_rule_version=WFP_RULE_VERSION,
    )

    write_setup_marker(marker_path, network=network)
    marker = read_setup_marker(marker_path)

    assert marker is not None
    assert marker.network == network


def test_legacy_firewall_marker_with_current_wfp_is_not_proxy_ready() -> None:
    from opensquilla.sandbox.backend.windows_default_network import (
        FIREWALL_RULE_VERSION,
        WFP_RULE_VERSION,
        WindowsNetworkSetup,
    )

    assert FIREWALL_RULE_VERSION > 1
    network = WindowsNetworkSetup(
        offline_user_sid="S-1-5-21-100-200-300-400",
        allowed_proxy_ports=(48123,),
        allow_local_binding=False,
        firewall_rule_version=1,
        wfp_rule_version=WFP_RULE_VERSION,
    )

    assert not network.is_current_for_ports((48123,))


def test_legacy_firewall_marker_with_local_binding_is_not_proxy_ready() -> None:
    from opensquilla.sandbox.backend.windows_default_network import (
        WFP_RULE_VERSION,
        WindowsNetworkSetup,
    )

    network = WindowsNetworkSetup(
        offline_user_sid="S-1-5-21-100-200-300-400",
        allowed_proxy_ports=(48123,),
        allow_local_binding=True,
        firewall_rule_version=1,
        wfp_rule_version=WFP_RULE_VERSION,
    )

    assert not network.is_current_for_ports((48123,))


def test_setup_marker_without_network_is_not_proxy_ready(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_setup import (
        setup_marker_proxy_allowlist_ready,
        write_setup_marker,
    )

    marker_path = tmp_path / "setup_marker.json"
    write_setup_marker(marker_path)

    assert setup_marker_proxy_allowlist_ready(marker_path, ports=(43128,)) is False


def test_offline_username_fits_windows_local_user_limit() -> None:
    from opensquilla.sandbox.backend.windows_default_setup import OFFLINE_USERNAME

    assert len(OFFLINE_USERNAME) <= 20


def test_establish_windows_network_setup_passes_proxy_ports_to_wfp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import (
        windows_default_firewall,
        windows_default_wfp,
    )
    from opensquilla.sandbox.backend import (
        windows_default_setup as mod,
    )

    calls: list[tuple[str, object]] = []
    identity = {
        "sid": "S-1-5-21-100-200-300-400",
        "username": "OpenSquillaSandbox",
        "protectedPassword": "protected",
    }
    monkeypatch.setattr(mod, "ensure_offline_sandbox_user", lambda path: identity)
    monkeypatch.setattr(
        windows_default_firewall,
        "firewall_rule_specs",
        lambda **kwargs: calls.append(("firewall_ports", kwargs["allowed_proxy_ports"])) or (),
    )
    monkeypatch.setattr(
        windows_default_firewall,
        "install_firewall_rules",
        lambda rules: calls.append(("firewall_install", tuple(rules))),
    )

    def fake_install_wfp_filters_for_user(sid: str, *, allowed_proxy_ports: tuple[int, ...]):
        calls.append(("wfp", (sid, allowed_proxy_ports)))

    monkeypatch.setattr(
        windows_default_wfp,
        "install_wfp_filters_for_user",
        fake_install_wfp_filters_for_user,
    )

    network = mod.establish_windows_network_setup(tmp_path / "setup_marker.json")

    assert ("firewall_ports", (48123,)) in calls
    assert ("wfp", ("S-1-5-21-100-200-300-400", (48123,))) in calls
    assert network.allowed_proxy_ports == (48123,)


def test_ensure_offline_sandbox_user_uses_configured_short_name(monkeypatch, tmp_path):
    from opensquilla.sandbox.backend import windows_default_setup as mod

    commands: list[str] = []

    class Completed:
        returncode = 0
        stdout = "S-1-5-21-100-200-300-400\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        commands.append(argv[-1])
        return Completed()

    monkeypatch.setattr(mod, "OFFLINE_USERNAME", "ShortSandboxUser")
    monkeypatch.setattr(mod, "_generate_offline_user_password", lambda: "Password123!")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        "opensquilla.sandbox.backend.windows_default_identity.protect_password",
        lambda password: f"protected:{password}",
    )

    identity = mod.ensure_offline_sandbox_user(tmp_path)

    assert identity["username"] == "ShortSandboxUser"
    assert "$name = 'ShortSandboxUser';" in commands[0]
    assert "OpenSquillaSandboxOffline" not in commands[0]


def test_run_elevated_setup_helper_launches_python_module_with_runas(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_setup as mod

    launched = {}
    marker = tmp_path / "setup_marker.json"

    monkeypatch.setattr(mod.sys, "executable", r"C:\Python312\python.exe")

    def fake_runas(*, executable, parameters, directory):
        launched["executable"] = executable
        launched["parameters"] = parameters
        launched["directory"] = directory
        return 0

    monkeypatch.setattr(mod, "_shell_execute_runas_and_wait", fake_runas)

    mod.run_elevated_setup_helper(marker)

    assert launched["executable"] == r"C:\Python312\python.exe"
    assert "-m opensquilla.sandbox.backend.windows_default_setup" in launched["parameters"]
    assert "--elevated-helper" in launched["parameters"]
    assert (Path(launched["directory"]) / "opensquilla").exists()


def test_runas_setup_helper_uses_hidden_window() -> None:
    from opensquilla.sandbox.backend import windows_default_setup as mod

    source = inspect.getsource(mod._shell_execute_runas_and_wait)

    assert "sw_hide = 0" in source
    assert "info.nShow = sw_hide" in source
    assert "sw_shownormal" not in source


def test_run_elevated_setup_helper_reports_nonzero_exit(monkeypatch, tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_setup as mod

    monkeypatch.setattr(mod, "_shell_execute_runas_and_wait", lambda **kwargs: 9)

    with pytest.raises(OSError, match="windows_setup_helper_failed: exit=9"):
        mod.run_elevated_setup_helper(tmp_path / "setup_marker.json")


def test_elevated_setup_helper_main_writes_failure_report(monkeypatch, tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_setup as mod

    marker = tmp_path / "setup_marker.json"
    payload = mod._encode_setup_helper_payload(marker)

    def fail_setup(path):
        raise OSError("Set-LocalUser access denied")

    monkeypatch.setattr(mod, "establish_windows_network_setup", fail_setup)

    code = mod.elevated_setup_helper_main(["--elevated-helper", payload])

    assert code == 1
    report = json.loads((marker.parent / "setup_helper_report.json").read_text())
    assert report["state"] == "failed"
    assert "Set-LocalUser access denied" in report["detail"]


def test_run_elevated_setup_helper_includes_failure_report_detail(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.sandbox.backend import windows_default_setup as mod

    marker = tmp_path / "setup_marker.json"
    report_path = marker.parent / "setup_helper_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def fake_runas(**kwargs):
        report_path.write_text(
            json.dumps({"state": "failed", "detail": "Set-LocalUser access denied"}),
            encoding="utf-8",
        )
        return 1

    monkeypatch.setattr(mod, "_shell_execute_runas_and_wait", fake_runas)

    with pytest.raises(OSError, match="Set-LocalUser access denied"):
        mod.run_elevated_setup_helper(marker)
