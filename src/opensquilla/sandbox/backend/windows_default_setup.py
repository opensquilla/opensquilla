"""Setup state for the Windows default sandbox."""

from __future__ import annotations

import json
import os
import secrets
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.sandbox.backend.windows_default_network import WindowsNetworkSetup

SETUP_VERSION = 1
OFFLINE_USERNAME = "OpenSquillaSandbox"
SETUP_HELPER_REPORT = "setup_helper_report.json"


@dataclass(frozen=True)
class WindowsDefaultSetupMarker:
    setup_version: int
    network: WindowsNetworkSetup | None = None

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {"setupVersion": self.setup_version}
        if self.network is not None:
            payload["network"] = self.network.to_json()
        return payload


def default_setup_marker_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / ".opensquilla" / "sandbox" / "setup_marker.json"


def write_setup_marker(
    path: Path,
    *,
    setup_version: int = SETUP_VERSION,
    network: WindowsNetworkSetup | None = None,
) -> None:
    marker = WindowsDefaultSetupMarker(setup_version=setup_version, network=network)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(marker.to_json(), sort_keys=True),
        encoding="utf-8",
    )


def read_setup_marker(path: Path) -> WindowsDefaultSetupMarker | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("setupVersion")
    if not isinstance(version, int):
        return None
    network = _network_setup_from_json(raw.get("network"))
    return WindowsDefaultSetupMarker(setup_version=version, network=network)


def _network_setup_from_json(raw: object) -> WindowsNetworkSetup | None:
    if not isinstance(raw, dict):
        return None
    sid = raw.get("offlineUserSid")
    ports = raw.get("allowedProxyPorts")
    allow_local_binding = raw.get("allowLocalBinding")
    firewall_version = raw.get("firewallRuleVersion")
    wfp_version = raw.get("wfpRuleVersion")
    network_version = raw.get("networkSetupVersion", 1)
    offline_username = raw.get("offlineUsername")
    protected_password = raw.get("protectedPassword")
    if not isinstance(sid, str) or not sid:
        return None
    if not isinstance(ports, list) or not all(isinstance(port, int) for port in ports):
        return None
    if not isinstance(allow_local_binding, bool):
        return None
    if not isinstance(firewall_version, int) or not isinstance(wfp_version, int):
        return None
    if not isinstance(network_version, int):
        return None
    return WindowsNetworkSetup(
        offline_user_sid=sid,
        allowed_proxy_ports=tuple(sorted(set(ports))),
        allow_local_binding=allow_local_binding,
        firewall_rule_version=firewall_version,
        wfp_rule_version=wfp_version,
        offline_username=offline_username if isinstance(offline_username, str) else None,
        protected_password=protected_password if isinstance(protected_password, str) else None,
        network_setup_version=network_version,
    )


def setup_marker_is_current(path: Path) -> bool:
    marker = read_setup_marker(path)
    return marker is not None and marker.setup_version == SETUP_VERSION


def setup_marker_proxy_allowlist_ready(path: Path, *, ports: tuple[int, ...]) -> bool:
    marker = read_setup_marker(path)
    if marker is None or marker.setup_version != SETUP_VERSION:
        return False
    if marker.network is None:
        return False
    return marker.network.is_current_for_ports(ports)


def setup_payload(path: Path) -> dict[str, Any]:
    return {
        "setupVersion": SETUP_VERSION,
        "markerPath": str(path),
        "sandboxStateRoot": str(path.parent),
        "sandboxSecretsRoot": str(path.parent.parent / "sandbox-secrets"),
        "sandboxBinRoot": str(path.parent.parent / "sandbox-bin"),
    }


def setup_helper_report_path(marker_path: Path) -> Path:
    return marker_path.parent / SETUP_HELPER_REPORT


def write_setup_helper_report(
    marker_path: Path,
    *,
    state: str,
    detail: str | None = None,
) -> None:
    report: dict[str, object] = {"state": state}
    if detail:
        report["detail"] = detail
    path = setup_helper_report_path(marker_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")


def read_setup_helper_report(marker_path: Path) -> dict[str, str] | None:
    try:
        raw = json.loads(setup_helper_report_path(marker_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    state = raw.get("state")
    if not isinstance(state, str) or not state:
        return None
    detail = raw.get("detail")
    report = {"state": state}
    if isinstance(detail, str) and detail:
        report["detail"] = detail
    return report


def establish_windows_network_setup(path: Path) -> WindowsNetworkSetup:
    from opensquilla.sandbox.backend.windows_default_firewall import (
        firewall_rule_specs,
        install_firewall_rules,
    )
    from opensquilla.sandbox.backend.windows_default_network import (
        FIREWALL_RULE_VERSION,
        WFP_RULE_VERSION,
    )
    from opensquilla.sandbox.backend.windows_default_wfp import install_wfp_filters_for_user

    identity = ensure_offline_sandbox_user(path.parent)
    allowed_ports = (48123,)
    rules = firewall_rule_specs(
        offline_sid=identity["sid"],
        allowed_proxy_ports=allowed_ports,
        allow_local_binding=False,
    )
    install_firewall_rules(rules)
    install_wfp_filters_for_user(identity["sid"], allowed_proxy_ports=allowed_ports)
    return WindowsNetworkSetup(
        offline_user_sid=identity["sid"],
        allowed_proxy_ports=allowed_ports,
        allow_local_binding=False,
        firewall_rule_version=FIREWALL_RULE_VERSION,
        wfp_rule_version=WFP_RULE_VERSION,
        offline_username=identity["username"],
        protected_password=identity["protectedPassword"],
    )


def run_elevated_setup_helper(path: Path) -> None:
    try:
        setup_helper_report_path(path).unlink()
    except FileNotFoundError:
        pass
    payload = _encode_setup_helper_payload(path)
    parameters = subprocess.list2cmdline(
        [
            "-m",
            "opensquilla.sandbox.backend.windows_default_setup",
            "--elevated-helper",
            payload,
        ]
    )
    exit_code = _shell_execute_runas_and_wait(
        executable=sys.executable,
        parameters=parameters,
        directory=str(_setup_helper_import_root()),
    )
    if exit_code != 0:
        detail = _setup_helper_report_detail(path)
        message = f"windows_setup_helper_failed: exit={exit_code}"
        if detail:
            message = f"{message}: {detail}"
        raise OSError(message)


def elevated_setup_helper_main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "--elevated-helper":
        print("windows_default_setup helper expects --elevated-helper payload", file=sys.stderr)
        return 2
    try:
        payload = _decode_setup_helper_payload(args[1])
        marker_path = Path(payload["markerPath"])
    except Exception as exc:
        print(f"windows_default_setup helper failed: {exc}", file=sys.stderr)
        return 2
    write_setup_helper_report(marker_path, state="running")
    try:
        network = establish_windows_network_setup(marker_path)
        write_setup_marker(marker_path, network=network)
        write_setup_helper_report(marker_path, state="ready", detail="setup_complete")
        return 0
    except Exception as exc:
        write_setup_helper_report(marker_path, state="failed", detail=str(exc))
        print(f"windows_default_setup helper failed: {exc}", file=sys.stderr)
        return 1


def _setup_helper_report_detail(marker_path: Path) -> str | None:
    report = read_setup_helper_report(marker_path)
    if report is None:
        return None
    return report.get("detail") or report.get("state")


def _setup_helper_import_root() -> Path:
    path = Path(__file__).resolve()
    package_root = path.parents[2]
    import_root = package_root.parent
    if (import_root / "opensquilla").exists():
        return import_root
    return Path.cwd()


def _encode_setup_helper_payload(path: Path) -> str:
    import base64

    raw = json.dumps({"markerPath": str(path)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_setup_helper_payload(value: str) -> dict[str, str]:
    import base64

    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OSError("windows_setup_helper_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise OSError("windows_setup_helper_payload_invalid")
    marker_path = payload.get("markerPath")
    if not isinstance(marker_path, str) or not marker_path:
        raise OSError("windows_setup_helper_payload_invalid")
    return {"markerPath": marker_path}


def _shell_execute_runas_and_wait(
    *,
    executable: str,
    parameters: str,
    directory: str,
) -> int:
    if not sys.platform.startswith("win"):
        raise OSError("windows_setup_helper_requires_windows")
    if not executable:
        raise OSError("windows_setup_helper_missing_python")

    import ctypes
    from ctypes import wintypes

    see_mask_nocloseprocess = 0x00000040
    sw_hide = 0
    infinite = 0xFFFFFFFF
    wait_failed = 0xFFFFFFFF
    error_cancelled = 1223

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = see_mask_nocloseprocess
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.lpDirectory = directory
    info.nShow = sw_hide

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == error_cancelled:
            raise OSError("windows_setup_helper_cancelled")
        raise OSError(code, f"windows_setup_helper_launch_failed: {ctypes.FormatError(code)}")
    try:
        wait_result = kernel32.WaitForSingleObject(info.hProcess, infinite)
        if wait_result == wait_failed:
            code = ctypes.get_last_error()
            raise OSError(code, f"windows_setup_helper_wait_failed: {ctypes.FormatError(code)}")
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            code = ctypes.get_last_error()
            raise OSError(code, f"windows_setup_helper_exit_failed: {ctypes.FormatError(code)}")
        return int(exit_code.value)
    finally:
        if info.hProcess:
            kernel32.CloseHandle(info.hProcess)


def ensure_offline_sandbox_user(state_root: Path) -> dict[str, str]:
    from opensquilla.sandbox.backend.windows_default_identity import protect_password

    state_root.mkdir(parents=True, exist_ok=True)
    password = _generate_offline_user_password()
    username = OFFLINE_USERNAME
    if len(username) > 20:
        raise OSError("offline_user_name_too_long")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"$name = '{username}'; "
        "$plain = $env:OPENSQUILLA_SANDBOX_PASSWORD; "
        "$password = ConvertTo-SecureString $plain -AsPlainText -Force; "
        "$user = Get-LocalUser -Name $name -ErrorAction SilentlyContinue; "
        "if ($null -eq $user) { "
        "New-LocalUser -Name $name -Password $password "
        "-Description 'OpenSquilla offline sandbox network identity' | Out-Null "
        "} else { Set-LocalUser -Name $name -Password $password }; "
        "$user = Get-LocalUser -Name $name; "
        "$user.SID.Value"
    )
    env = {**os.environ, "OPENSQUILLA_SANDBOX_PASSWORD": password}
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise OSError(detail or "offline_user_missing")
    sid = completed.stdout.strip().splitlines()[-1].strip()
    if not sid:
        raise OSError("offline_user_missing")
    return {
        "sid": sid,
        "username": OFFLINE_USERNAME,
        "protectedPassword": protect_password(password),
    }


def _generate_offline_user_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    prefix = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*()-_=+"),
    ]
    rest = [secrets.choice(alphabet) for _ in range(36)]
    return "".join(prefix + rest)


__all__ = [
    "SETUP_VERSION",
    "OFFLINE_USERNAME",
    "SETUP_HELPER_REPORT",
    "WindowsDefaultSetupMarker",
    "default_setup_marker_path",
    "ensure_offline_sandbox_user",
    "elevated_setup_helper_main",
    "establish_windows_network_setup",
    "read_setup_marker",
    "read_setup_helper_report",
    "run_elevated_setup_helper",
    "setup_marker_is_current",
    "setup_marker_proxy_allowlist_ready",
    "setup_payload",
    "setup_helper_report_path",
    "write_setup_helper_report",
    "write_setup_marker",
]


if __name__ == "__main__":
    raise SystemExit(elevated_setup_helper_main())
