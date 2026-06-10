"""Elevated Windows sandbox broker.

The broker is a small, user-approved Windows process. It owns administrator-only
operations such as AppContainer loopback exemptions and firewall/WFP policy
updates, while normal tool execution still happens inside the sandbox.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

CommandRunner = Callable[[Sequence[str]], object]


def _default_powershell_path() -> Path:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _default_checknetisolation_path() -> Path:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return Path(system_root) / "System32" / "CheckNetIsolation.exe"


def _default_command_runner(argv: Sequence[str]) -> None:
    result = subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"command failed with exit code {result.returncode}")


def _is_running_as_admin() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _ps_create_rule_script() -> str:
    return r"""
$ErrorActionPreference = 'Stop'
$remoteAddress = $args[6]
$params = @{
  Name = $args[0]
  DisplayName = $args[1]
  Direction = 'Outbound'
  Enabled = 'True'
  Action = $args[2]
  Profile = 'Any'
  Package = $args[3]
  Protocol = $args[4]
}
if ($remoteAddress) {
  $params.RemoteAddress = $remoteAddress -split ','
}
if ($args[5]) {
  $params.RemotePort = [int]$args[5]
}
New-NetFirewallRule @params | Out-Null
""".strip()


def _ps_remove_rule_script() -> str:
    return r"""
$ErrorActionPreference = 'Stop'
Remove-NetFirewallRule -Name $args[0] -ErrorAction SilentlyContinue
""".strip()


@dataclass(frozen=True)
class FirewallRule:
    name: str
    display_name: str
    action: str
    package_sid: str
    protocol: str
    remote_port: int | None = None
    remote_address: str | None = None


@dataclass
class WindowsFirewallPolicyManager:
    command_runner: CommandRunner = _default_command_runner
    powershell_path: Path = field(default_factory=_default_powershell_path)
    checknetisolation_path: Path = field(default_factory=_default_checknetisolation_path)
    is_admin: Callable[[], bool] = _is_running_as_admin

    def health_check(self) -> None:
        if not self.is_admin():
            raise PermissionError("Windows sandbox broker requires administrator privileges")
        if not self.powershell_path.exists() and self.powershell_path.is_absolute():
            raise FileNotFoundError(f"PowerShell not found: {self.powershell_path}")
        if (
            not self.checknetisolation_path.exists()
            and self.checknetisolation_path.is_absolute()
        ):
            raise FileNotFoundError(f"CheckNetIsolation not found: {self.checknetisolation_path}")

    def install_policy(self, request: InstallPolicyRequest) -> tuple[str, ...]:
        self.health_check()
        self._ensure_loopback_exemption(request.appcontainer_sid)
        installed: list[str] = []
        try:
            for rule in _firewall_rules_for_request(request):
                self._create_firewall_rule(rule)
                installed.append(rule.name)
        except Exception:
            for rule_name in reversed(installed):
                self._remove_firewall_rule(rule_name)
            raise
        return tuple(installed)

    def remove_policy(self, rule_names: Sequence[str]) -> int:
        removed = 0
        for rule_name in reversed(tuple(rule_names)):
            self._remove_firewall_rule(str(rule_name))
            removed += 1
        return removed

    def _ensure_loopback_exemption(self, appcontainer_sid: str) -> None:
        self.command_runner(
            [
                str(self.checknetisolation_path),
                "LoopbackExempt",
                "-a",
                f"-p={appcontainer_sid}",
            ]
        )

    def _create_firewall_rule(self, rule: FirewallRule) -> None:
        self.command_runner(
            [
                str(self.powershell_path),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _ps_create_rule_script(),
                rule.name,
                rule.display_name,
                rule.action,
                rule.package_sid,
                rule.protocol,
                str(rule.remote_port or ""),
                rule.remote_address or "",
            ]
        )

    def _remove_firewall_rule(self, rule_name: str) -> None:
        self.command_runner(
            [
                str(self.powershell_path),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _ps_remove_rule_script(),
                rule_name,
            ]
        )


def _firewall_rules_for_request(request: InstallPolicyRequest) -> tuple[FirewallRule, ...]:
    run_id = _sanitize_rule_token(request.run_id)
    sid = request.appcontainer_sid
    display_prefix = f"OpenSquilla sandbox {request.run_id}"
    proxy_address = request.proxy_host
    proxy_port = request.proxy_port
    if proxy_address != "127.0.0.1":
        raise ValueError("Windows broker-only egress currently requires 127.0.0.1 proxy")
    return (
        FirewallRule(
            name=f"OpenSquilla-{run_id}-allow-proxy-ipv4",
            display_name=f"{display_prefix} allow proxy IPv4",
            action="Allow",
            package_sid=sid,
            protocol="TCP",
            remote_address="127.0.0.1",
            remote_port=proxy_port,
        ),
        FirewallRule(
            name=f"OpenSquilla-{run_id}-block-ipv4",
            display_name=f"{display_prefix} block IPv4",
            action="Block",
            package_sid=sid,
            protocol="Any",
            remote_address="0.0.0.0-127.0.0.0,127.0.0.2-255.255.255.255",
        ),
        FirewallRule(
            name=f"OpenSquilla-{run_id}-allow-proxy-ipv6",
            display_name=f"{display_prefix} allow proxy IPv6",
            action="Allow",
            package_sid=sid,
            protocol="TCP",
            remote_address="::1",
            remote_port=proxy_port,
        ),
        FirewallRule(
            name=f"OpenSquilla-{run_id}-block-ipv6",
            display_name=f"{display_prefix} block IPv6",
            action="Block",
            package_sid=sid,
            protocol="Any",
            remote_address="::/0",
        ),
    )


def _sanitize_rule_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]


@dataclass
class WindowsSandboxBroker:
    policy_manager: WindowsFirewallPolicyManager = field(
        default_factory=WindowsFirewallPolicyManager
    )
    policies: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def handle(self, payload: dict[str, object]) -> dict[str, object]:
        op = str(payload.get("op") or "")
        if op == "health":
            self.policy_manager.health_check()
            return {"status": "ok", "admin": True}
        if op == "install_policy":
            request = InstallPolicyRequest(
                run_id=str(payload.get("run_id") or ""),
                appcontainer_sid=str(payload.get("appcontainer_sid") or ""),
                proxy_host=str(payload.get("proxy_host") or ""),
                proxy_port=int(payload.get("proxy_port") or 0),
                ttl_seconds=int(payload.get("ttl_seconds") or 0),
            )
            rule_ids = self.policy_manager.install_policy(request)
            self.policies[request.run_id] = rule_ids
            return {"status": "ok", "filter_ids": list(rule_ids)}
        if op == "remove_policy":
            run_id = str(payload.get("run_id") or "").strip()
            rule_ids = self.policies.pop(run_id, ())
            removed = self.policy_manager.remove_policy(rule_ids)
            return {"status": "ok", "removed": removed}
        if op == "shutdown":
            return {"status": "ok", "shutdown": True}
        raise ValueError(f"unknown operation: {op}")


def run_named_pipe_server(*, pipe_name: str, authkey: bytes) -> None:
    from multiprocessing.connection import Listener

    broker = WindowsSandboxBroker()
    listener = Listener(pipe_name, family="AF_PIPE", authkey=authkey)
    try:
        while True:
            conn = listener.accept()
            try:
                payload = conn.recv()
                if not isinstance(payload, dict):
                    raise ValueError("request payload must be an object")
                response = broker.handle(payload)
                conn.send(response)
                if response.get("shutdown") is True:
                    return
            except Exception as exc:
                conn.send({"status": "error", "message": str(exc)})
            finally:
                conn.close()
    finally:
        listener.close()


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenSquilla Windows sandbox broker")
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--authkey", required=True)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    run_named_pipe_server(pipe_name=args.pipe, authkey=bytes.fromhex(args.authkey))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FirewallRule",
    "WindowsFirewallPolicyManager",
    "WindowsSandboxBroker",
    "run_named_pipe_server",
]
