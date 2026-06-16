"""Windows Firewall rule planning for windows_default managed networking."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from opensquilla.sandbox.backend.windows_default_network import (
    blocked_loopback_tcp_remote_ports,
)
from opensquilla.sandbox.types import SandboxBackendError

LOOPBACK_REMOTE_ADDRESSES = "127.0.0.0/8,::/127"
NON_LOOPBACK_REMOTE_ADDRESSES = (
    "0.0.0.0-126.255.255.255,"
    "128.0.0.0-255.255.255.255,"
    "::,::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"
)


@dataclass(frozen=True)
class FirewallRuleSpec:
    name: str
    display_name: str
    protocol: str
    local_user_sid: str
    remote_addresses: str
    remote_ports: tuple[str, ...] = ()


def firewall_rule_specs(
    *,
    offline_sid: str,
    allowed_proxy_ports: tuple[int, ...],
    allow_local_binding: bool,
) -> tuple[FirewallRuleSpec, ...]:
    specs = [
        FirewallRuleSpec(
            name="opensquilla_sandbox_offline_block_non_loopback",
            display_name="OpenSquilla Sandbox Offline - Block Non-Loopback Outbound",
            protocol="Any",
            local_user_sid=offline_sid,
            remote_addresses=NON_LOOPBACK_REMOTE_ADDRESSES,
        )
    ]
    specs.append(
        FirewallRuleSpec(
            name="opensquilla_sandbox_offline_block_dns_tcp",
            display_name="OpenSquilla Sandbox Offline - Block DNS TCP",
            protocol="TCP",
            local_user_sid=offline_sid,
            remote_addresses=NON_LOOPBACK_REMOTE_ADDRESSES,
            remote_ports=("53", "853"),
        )
    )
    specs.append(
        FirewallRuleSpec(
            name="opensquilla_sandbox_offline_block_dns_udp",
            display_name="OpenSquilla Sandbox Offline - Block DNS UDP",
            protocol="UDP",
            local_user_sid=offline_sid,
            remote_addresses=NON_LOOPBACK_REMOTE_ADDRESSES,
            remote_ports=("53", "853"),
        )
    )
    if allow_local_binding:
        return tuple(specs)
    specs.append(
        FirewallRuleSpec(
            name="opensquilla_sandbox_offline_block_loopback_udp",
            display_name="OpenSquilla Sandbox Offline - Block Loopback UDP",
            protocol="UDP",
            local_user_sid=offline_sid,
            remote_addresses=LOOPBACK_REMOTE_ADDRESSES,
        )
    )
    specs.append(
        FirewallRuleSpec(
            name="opensquilla_sandbox_offline_block_loopback_tcp_except_proxy",
            display_name="OpenSquilla Sandbox Offline - Block Loopback TCP Except Proxy",
            protocol="TCP",
            local_user_sid=offline_sid,
            remote_addresses=LOOPBACK_REMOTE_ADDRESSES,
            remote_ports=blocked_loopback_tcp_remote_ports(allowed_proxy_ports),
        )
    )
    return tuple(specs)


def powershell_firewall_commands(specs: tuple[FirewallRuleSpec, ...]) -> tuple[str, ...]:
    commands: list[str] = []
    for spec in specs:
        port_clause = _powershell_firewall_port_clause(spec)
        remote_addresses = _powershell_array_literal(spec.remote_addresses.split(","))
        local_user = _local_user_authorized_list(spec.local_user_sid)
        commands.append(
            f"if (Get-NetFirewallRule -Name '{spec.name}' -ErrorAction SilentlyContinue) "
            f"{{ Remove-NetFirewallRule -Name '{spec.name}' }}; "
            f"New-NetFirewallRule -Name '{spec.name}' -DisplayName '{spec.display_name}' "
            "-Direction Outbound -Action Block -Enabled True "
            f"-Profile Any -Protocol {spec.protocol} -RemoteAddress {remote_addresses} "
            f"{port_clause} -LocalUser '{local_user}'"
        )
    return tuple(commands)


def _powershell_firewall_port_clause(spec: FirewallRuleSpec) -> str:
    remote_ports = (
        _powershell_array_literal(list(spec.remote_ports))
        if spec.remote_ports
        else _powershell_single_quote("Any")
    )
    return f"-RemotePort {remote_ports}"


def _powershell_array_literal(values: list[str]) -> str:
    return ",".join(_powershell_single_quote(value.strip()) for value in values if value.strip())


def _powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _local_user_authorized_list(sid: str) -> str:
    return f"O:LSD:(A;;CC;;;{sid})"


def install_firewall_rules(specs: tuple[FirewallRuleSpec, ...]) -> None:
    for command in powershell_firewall_commands(specs):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise SandboxBackendError(f"firewall_rule_install_failed: {detail}")


__all__ = [
    "LOOPBACK_REMOTE_ADDRESSES",
    "NON_LOOPBACK_REMOTE_ADDRESSES",
    "FirewallRuleSpec",
    "firewall_rule_specs",
    "install_firewall_rules",
    "powershell_firewall_commands",
]
