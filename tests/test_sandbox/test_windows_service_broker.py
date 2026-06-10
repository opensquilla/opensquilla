from __future__ import annotations

from pathlib import Path

import pytest


def _request():
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    return InstallPolicyRequest(
        run_id="run-1",
        appcontainer_sid="S-1-15-2-123",
        proxy_host="127.0.0.1",
        proxy_port=48123,
        ttl_seconds=60,
    )


def test_firewall_policy_manager_installs_loopback_and_firewall_rules() -> None:
    from opensquilla.sandbox.windows_service_broker import WindowsFirewallPolicyManager

    commands: list[tuple[str, ...]] = []
    manager = WindowsFirewallPolicyManager(
        command_runner=lambda argv: commands.append(tuple(argv)),
        powershell_path=Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
        checknetisolation_path=Path(r"C:\Windows\System32\CheckNetIsolation.exe"),
        is_admin=lambda: True,
    )

    rule_ids = manager.install_policy(_request())

    assert any(command[0].endswith("CheckNetIsolation.exe") for command in commands)
    assert any("-p=S-1-15-2-123" in command for command in commands for command in command)
    firewall_commands = [command for command in commands if command[0].endswith("powershell.exe")]
    assert len(firewall_commands) == 2
    assert rule_ids == (
        "OpenSquilla-run-1-allow-proxy-ipv4",
        "OpenSquilla-run-1-block-ipv4",
    )
    joined = "\n".join(" ".join(command) for command in firewall_commands)
    assert "New-NetFirewallRule" in joined
    assert "Package" in joined
    assert "S-1-15-2-123" in joined
    assert "127.0.0.1" in joined
    assert "48123" in joined
    assert "::1" not in joined
    assert "::/0" not in joined


def test_firewall_policy_manager_embeds_rule_values_without_command_args() -> None:
    from opensquilla.sandbox.windows_service_broker import WindowsFirewallPolicyManager

    commands: list[tuple[str, ...]] = []
    manager = WindowsFirewallPolicyManager(
        command_runner=lambda argv: commands.append(tuple(argv)),
        powershell_path=Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
        checknetisolation_path=Path(r"C:\Windows\System32\CheckNetIsolation.exe"),
        is_admin=lambda: True,
    )

    manager.install_policy(_request())

    firewall_commands = [command for command in commands if command[0].endswith("powershell.exe")]
    assert firewall_commands
    for command in firewall_commands:
        command_index = command.index("-Command")
        script = command[command_index + 1]
        assert len(command) == command_index + 2
        assert "$args" not in script
        assert "$params = @{\n  Name =" in script
        assert '@{"' not in script
        assert "Action = 'Allow'" in script or "Action = 'Block'" in script


def test_firewall_policy_manager_rolls_back_rules_after_failure() -> None:
    from opensquilla.sandbox.windows_service_broker import WindowsFirewallPolicyManager

    commands: list[tuple[str, ...]] = []

    def command_runner(argv):
        commands.append(tuple(argv))
        if any("block-ipv4" in part for part in argv):
            raise RuntimeError("firewall failed")

    manager = WindowsFirewallPolicyManager(
        command_runner=command_runner,
        powershell_path=Path("powershell.exe"),
        checknetisolation_path=Path("CheckNetIsolation.exe"),
        is_admin=lambda: True,
    )

    with pytest.raises(RuntimeError, match="firewall failed"):
        manager.install_policy(_request())

    joined = "\n".join(" ".join(command) for command in commands)
    assert "Remove-NetFirewallRule" in joined
    assert "allow-proxy-ipv4" in joined


def test_broker_rejects_policy_install_when_not_elevated() -> None:
    from opensquilla.sandbox.windows_service_broker import WindowsFirewallPolicyManager

    manager = WindowsFirewallPolicyManager(
        command_runner=lambda argv: None,
        powershell_path=Path("powershell.exe"),
        checknetisolation_path=Path("CheckNetIsolation.exe"),
        is_admin=lambda: False,
    )

    with pytest.raises(PermissionError, match="administrator"):
        manager.install_policy(_request())
