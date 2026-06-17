"""Windows default sandbox runner helper."""

# ruff: noqa: N801, N806
# mypy: disable-error-code="attr-defined,arg-type,assignment,call-overload"

from __future__ import annotations

import base64
import contextlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Any

HELPER_MODULE = "opensquilla.sandbox.backend.windows_default_runner"
DISABLE_MAX_PRIVILEGE = 0x01
LUA_TOKEN = 0x04
WRITE_RESTRICTED = 0x08
RESTRICTED_TOKEN_FLAGS = DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED
GENERIC_ALL = 0x10000000
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100
TOKEN_ADJUST_PRIVILEGES = 0x0020
STARTF_USESHOWWINDOW = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
SW_HIDE = 0
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000
OFFLINE_PAYLOAD_ENV = "OPENSQUILLA_WINDOWS_DEFAULT_PAYLOAD"
OFFLINE_PAYLOAD_FILE_ARG = "--payload-file"


def _base_restricting_sid_specs() -> tuple[tuple[str, str], ...]:
    return (("S-1-1-0", "everyone"),)


def _ordered_restricting_sids(
    *,
    capability_sids: Sequence[object],
    user_sid: object | None,
    logon_sid: object | None,
    base_sids: Sequence[object],
) -> tuple[object, ...]:
    ordered = list(capability_sids)
    if user_sid is not None:
        ordered.append(user_sid)
    if logon_sid is not None:
        ordered.append(logon_sid)
    ordered.extend(base_sids)
    return tuple(ordered)


@dataclass(frozen=True)
class HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    run_mode: str
    timeout: float
    stdin: bytes | None = None
    offline_child: bool = False


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not sys.platform.startswith("win"):
            raise SystemExit("windows_default runner only runs on native Windows")
        payload = _parse_payload(args)
        _validate_policy_is_enforceable(payload.policy)
        raise SystemExit(_run_windows_default(payload))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(1) from None
        raise


def _parse_payload(args: Sequence[str]) -> HelperPayload:
    if list(args) == ["--payload-env"]:
        env_payload = os.environ.get(OFFLINE_PAYLOAD_ENV)
        if not env_payload:
            raise SystemExit("windows_default runner payload env is missing")
        raw_payload = env_payload
    elif len(args) == 2 and args[0] == OFFLINE_PAYLOAD_FILE_ARG:
        try:
            raw_payload = Path(args[1]).read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"windows_default runner payload file is unreadable: {exc}") from exc
    elif len(args) == 1:
        raw_payload = args[0]
    else:
        raise SystemExit("windows_default runner expects one JSON payload argument")
    try:
        raw = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid windows_default payload JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("invalid windows_default payload: expected object")
    if raw.get("backend") != "windows_default":
        raise SystemExit("invalid windows_default payload: expected backend windows_default")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise SystemExit("invalid windows_default payload: argv must be a string list")

    cwd_raw = raw.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        raise SystemExit("invalid windows_default payload: cwd is required")
    cwd = Path(cwd_raw)
    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"invalid windows_default cwd: {cwd}")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()
    ):
        raise SystemExit("invalid windows_default payload: env must be string map")

    policy = raw.get("policy")
    if not isinstance(policy, dict):
        raise SystemExit("invalid windows_default payload: policy is required")

    run_mode = raw.get("runMode")
    if run_mode not in {"standard", "trusted"}:
        raise SystemExit("invalid windows_default payload: runMode must be standard or trusted")

    timeout = raw.get("timeout")
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SystemExit("invalid windows_default payload: timeout must be positive")

    stdin_raw = raw.get("stdinBase64")
    if stdin_raw is None:
        stdin = None
    elif isinstance(stdin_raw, str):
        try:
            stdin = base64.b64decode(stdin_raw.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise SystemExit(
                "invalid windows_default payload: stdinBase64 is invalid"
            ) from exc
    else:
        raise SystemExit(
            "invalid windows_default payload: stdinBase64 must be a string or null"
        )
    offline_child = raw.get("offlineChild", False)
    if not isinstance(offline_child, bool):
        raise SystemExit("invalid windows_default payload: offlineChild must be boolean")

    return HelperPayload(
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env_raw),
        policy=policy,
        run_mode=str(run_mode),
        timeout=float(timeout),
        stdin=stdin,
        offline_child=offline_child,
    )


def _validate_policy_is_enforceable(policy: dict[str, Any]) -> None:
    network = policy.get("network")
    if network not in {"none", "host", "proxy_allowlist"}:
        raise SystemExit(f"windows_default runner received unknown network mode: {network!r}")
    if network == "proxy_allowlist":
        _validate_network_proxy(policy)


def _validate_network_proxy(policy: dict[str, Any]) -> None:
    proxy = policy.get("network_proxy")
    if proxy is None:
        proxy = policy.get("networkProxy")
    if not isinstance(proxy, dict):
        raise SystemExit(
            "windows_default PROXY_ALLOWLIST requires network_proxy endpoint"
        )
    host = proxy.get("host")
    port = proxy.get("port")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "windows_default PROXY_ALLOWLIST requires a local network_proxy host"
        )
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise SystemExit(
            "windows_default PROXY_ALLOWLIST requires a valid network_proxy port"
        )
    _validate_windows_network_boundary(policy)


def _validate_windows_network_boundary(policy: dict[str, Any]) -> None:
    proxy = policy.get("network_proxy") or policy.get("networkProxy")
    boundary = policy.get("windowsNetworkBoundary")
    if not isinstance(proxy, dict):
        raise SystemExit("windows_default PROXY_ALLOWLIST requires network_proxy endpoint")
    if not isinstance(boundary, dict):
        raise SystemExit("windows_default PROXY_ALLOWLIST requires windowsNetworkBoundary")
    ports = boundary.get("allowedProxyPorts")
    sid = boundary.get("offlineUserSid")
    allow_local_binding = boundary.get("allowLocalBinding")
    if not isinstance(sid, str) or not sid:
        raise SystemExit("windows_default windowsNetworkBoundary requires offlineUserSid")
    if not isinstance(ports, list) or not all(isinstance(port, int) for port in ports):
        raise SystemExit("windows_default windowsNetworkBoundary requires allowedProxyPorts")
    if not isinstance(allow_local_binding, bool):
        raise SystemExit("windows_default windowsNetworkBoundary requires allowLocalBinding")
    if proxy.get("port") not in ports:
        raise SystemExit(
            "windows_default network_proxy port is not allowed by windowsNetworkBoundary"
        )


def _run_windows_default(payload: HelperPayload) -> int:
    acl_plan = _windows_acl_plan(payload.policy)
    capability_sids = _capability_sids(acl_plan)
    if _should_reexec_as_offline_identity(payload):
        _apply_acl_refresh(acl_plan)
        return _run_payload_as_offline_identity(payload)
    if not payload.offline_child:
        _apply_acl_refresh(acl_plan)
    return _run_restricted_process_native(payload, capability_sids)


def _windows_acl_plan(policy: dict[str, Any]) -> dict[str, Any]:
    plan = policy.get("windowsAclPlan")
    if not isinstance(plan, dict):
        raise SystemExit("invalid windows_default policy: windowsAclPlan is required")
    auto_grants = plan.get("autoGrants")
    if not isinstance(auto_grants, list):
        raise SystemExit("invalid windows_default policy: autoGrants must be a list")
    capability_sids = plan.get("capabilitySids")
    if not isinstance(capability_sids, list) or not all(
        isinstance(sid, str) for sid in capability_sids
    ):
        raise SystemExit("invalid windows_default policy: capabilitySids must be a string list")
    return plan


def _capability_sids(plan: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(sid) for sid in plan["capabilitySids"])


def _apply_acl_refresh(plan: dict[str, Any]) -> None:
    for grant in plan["autoGrants"]:
        if not isinstance(grant, dict):
            raise SystemExit("invalid windows_default ACL grant: grant must be an object")
        path = grant.get("path")
        access = grant.get("access")
        sid = grant.get("capabilitySid")
        if not isinstance(path, str) or access not in {"RX", "RWX"} or not isinstance(sid, str):
            raise SystemExit("invalid windows_default ACL grant shape")
        _grant_path_to_sid(Path(path), access, sid)


def _network_boundary(policy: dict[str, Any]) -> dict[str, object] | None:
    boundary = policy.get("windowsNetworkBoundary")
    return boundary if isinstance(boundary, dict) else None


def _should_reexec_as_offline_identity(payload: HelperPayload) -> bool:
    return (
        not payload.offline_child
        and payload.policy.get("network") == "proxy_allowlist"
        and _network_boundary(payload.policy) is not None
    )


def _run_payload_as_offline_identity(payload: HelperPayload) -> int:
    boundary = _network_boundary(payload.policy)
    if boundary is None:
        raise OSError("windowsNetworkBoundary missing for offline identity launch")
    from opensquilla.sandbox.backend.windows_default_identity import (
        offline_identity_from_boundary,
        unprotect_password,
    )

    identity = offline_identity_from_boundary(boundary)
    _grant_offline_helper_runtime_access(identity.sid)
    _grant_acl_plan_to_sid(_windows_acl_plan(payload.policy), identity.sid)
    password = unprotect_password(identity.protected_password)
    return _run_payload_as_offline_identity_native(
        replace(payload, offline_child=True),
        username=identity.username,
        password=password,
    )


def _open_source_token_for_payload(payload: HelperPayload) -> int:
    if payload.offline_child:
        return _open_current_process_token()
    boundary = _network_boundary(payload.policy)
    if payload.policy.get("network") == "proxy_allowlist" and boundary is not None:
        from opensquilla.sandbox.backend.windows_default_identity import (
            logon_offline_identity,
            offline_identity_from_boundary,
        )

        return logon_offline_identity(offline_identity_from_boundary(boundary))
    return _open_current_process_token()


def _open_current_process_token() -> int:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi32.OpenProcessToken.restype = BOOL
    kernel32.GetCurrentProcess.restype = HANDLE

    desired_access = (
        TOKEN_ASSIGN_PRIMARY
        | TOKEN_DUPLICATE
        | TOKEN_QUERY
        | TOKEN_ADJUST_DEFAULT
        | TOKEN_ADJUST_SESSIONID
        | TOKEN_ADJUST_PRIVILEGES
    )
    source_token = HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        desired_access,
        ctypes.byref(source_token),
    ):
        code = ctypes.get_last_error()
        raise OSError(code, f"OpenProcessToken failed: {ctypes.FormatError(code)}")
    return int(source_token.value)


def _grant_path_to_sid(path: Path, access: str, sid: str) -> None:
    if not path.exists():
        raise SystemExit(f"windows_default ACL grant target does not exist: {path}")
    try:
        _grant_path_to_sid_native(path, access, sid)
    except OSError as exc:
        raise SystemExit(
            f"windows_default ACL grant failed for {path}: {exc}"
        ) from exc


def _grant_path_to_sid_native(path: Path, access: str, sid: str) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    DWORD = wintypes.DWORD
    LPVOID = wintypes.LPVOID

    class TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", LPVOID),
            ("MultipleTrusteeOperation", DWORD),
            ("TrusteeForm", DWORD),
            ("TrusteeType", DWORD),
            ("ptstrName", LPVOID),
        ]

    class EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", DWORD),
            ("grfAccessMode", DWORD),
            ("grfInheritance", DWORD),
            ("Trustee", TRUSTEE_W),
        ]

    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(LPVOID)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        DWORD,
        DWORD,
        ctypes.POINTER(LPVOID),
        ctypes.POINTER(LPVOID),
        ctypes.POINTER(LPVOID),
        ctypes.POINTER(LPVOID),
        ctypes.POINTER(LPVOID),
    ]
    advapi32.GetNamedSecurityInfoW.restype = DWORD
    advapi32.SetEntriesInAclW.argtypes = [
        DWORD,
        ctypes.POINTER(EXPLICIT_ACCESS_W),
        LPVOID,
        ctypes.POINTER(LPVOID),
    ]
    advapi32.SetEntriesInAclW.restype = DWORD
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        DWORD,
        DWORD,
        LPVOID,
        LPVOID,
        LPVOID,
        LPVOID,
    ]
    advapi32.SetNamedSecurityInfoW.restype = DWORD
    kernel32.LocalFree.argtypes = [LPVOID]
    kernel32.LocalFree.restype = LPVOID

    ERROR_SUCCESS = 0
    SE_FILE_OBJECT = 1
    DACL_SECURITY_INFORMATION = 0x00000004
    GRANT_ACCESS = 1
    TRUSTEE_IS_SID = 0
    TRUSTEE_IS_UNKNOWN = 0
    NO_INHERITANCE = 0
    OBJECT_INHERIT_ACE = 0x1
    CONTAINER_INHERIT_ACE = 0x2

    DELETE = 0x00010000
    FILE_DELETE_CHILD = 0x00000040
    FILE_GENERIC_READ = 0x00120089
    FILE_GENERIC_WRITE = 0x00120116
    FILE_GENERIC_EXECUTE = 0x001200A0

    def win32_error(label: str, code: int | None = None) -> OSError:
        error_code = ctypes.get_last_error() if code is None else code
        return OSError(error_code, f"{label} failed: {ctypes.FormatError(error_code)}")

    if access == "RX":
        allow_mask = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE
    elif access == "RWX":
        allow_mask = (
            FILE_GENERIC_READ
            | FILE_GENERIC_WRITE
            | FILE_GENERIC_EXECUTE
            | DELETE
            | FILE_DELETE_CHILD
        )
    else:
        raise OSError(0, f"unsupported ACL access mode: {access!r}")

    sid_ptr = LPVOID()
    security_descriptor = LPVOID()
    old_dacl = LPVOID()
    new_dacl = LPVOID()
    path_buffer = ctypes.create_unicode_buffer(str(path))
    inheritance = (
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE if path.is_dir() else NO_INHERITANCE
    )

    try:
        if not advapi32.ConvertStringSidToSidW(sid, ctypes.byref(sid_ptr)):
            raise win32_error("ConvertStringSidToSidW")
        code = advapi32.GetNamedSecurityInfoW(
            path_buffer,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        if code != ERROR_SUCCESS:
            raise win32_error("GetNamedSecurityInfoW", code)

        explicit = EXPLICIT_ACCESS_W()
        explicit.grfAccessPermissions = allow_mask
        explicit.grfAccessMode = GRANT_ACCESS
        explicit.grfInheritance = inheritance
        explicit.Trustee.pMultipleTrustee = None
        explicit.Trustee.MultipleTrusteeOperation = 0
        explicit.Trustee.TrusteeForm = TRUSTEE_IS_SID
        explicit.Trustee.TrusteeType = TRUSTEE_IS_UNKNOWN
        explicit.Trustee.ptstrName = sid_ptr

        code = advapi32.SetEntriesInAclW(
            1,
            ctypes.byref(explicit),
            old_dacl,
            ctypes.byref(new_dacl),
        )
        if code != ERROR_SUCCESS:
            raise win32_error("SetEntriesInAclW", code)
        code = advapi32.SetNamedSecurityInfoW(
            path_buffer,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            new_dacl,
            None,
        )
        if code != ERROR_SUCCESS:
            raise win32_error("SetNamedSecurityInfoW", code)
    finally:
        for pointer in (new_dacl, security_descriptor, sid_ptr):
            if pointer:
                kernel32.LocalFree(pointer)


def _environment_block(env: dict[str, str]) -> str:
    merged = dict(env)
    for key in ("SystemRoot", "WINDIR", "ComSpec"):
        value = os.environ.get(key)
        if value and key not in merged:
            merged[key] = value
    items = [
        f"{key}={value}"
        for key, value in sorted(merged.items(), key=lambda item: item[0].upper())
    ]
    return "\0".join(items) + "\0\0"


def _payload_to_json(payload: HelperPayload) -> str:
    raw: dict[str, object] = {
        "backend": "windows_default",
        "argv": list(payload.argv),
        "cwd": str(payload.cwd),
        "env": payload.env,
        "policy": payload.policy,
        "runMode": payload.run_mode,
        "timeout": payload.timeout,
        "stdinBase64": (
            base64.b64encode(payload.stdin).decode("ascii")
            if payload.stdin is not None
            else None
        ),
        "offlineChild": payload.offline_child,
    }
    return json.dumps(raw, separators=(",", ":"), sort_keys=True)


def _helper_import_root() -> Path:
    path = Path(__file__).resolve()
    package_root = path.parents[2]
    import_root = package_root.parent
    if (import_root / "opensquilla").exists():
        return import_root
    return Path.cwd()


def _helper_child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop(OFFLINE_PAYLOAD_ENV, None)
    import_root = str(_helper_import_root())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        import_root if not existing else f"{import_root}{os.pathsep}{existing}"
    )
    return env


def _offline_helper_runtime_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    executable = Path(sys.executable).resolve()
    roots.append(executable.parent)

    pyvenv_cfg = executable.parent.parent / "pyvenv.cfg"
    try:
        for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip().lower() == "home" and value.strip():
                roots.append(Path(value.strip()).resolve())
                break
    except OSError:
        pass

    base_prefix = Path(getattr(sys, "base_prefix", "") or "")
    if str(base_prefix):
        roots.append(base_prefix.resolve())
    roots.append(_helper_import_root().resolve())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=False)
        except OSError:
            resolved = root
        key = str(resolved).casefold()
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        unique.append(resolved)
    return tuple(unique)


def _write_offline_payload_file(payload: HelperPayload) -> Path:
    payload_dir = payload.cwd / ".opensquilla-cache" / "offline-helper"
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = payload_dir / f"payload-{os.getpid()}-{uuid.uuid4().hex}.json"
    payload_path.write_text(_payload_to_json(payload), encoding="utf-8")
    return payload_path


def _grant_offline_helper_runtime_access(sid: str) -> None:
    for root in _offline_helper_runtime_roots():
        _grant_path_to_sid(root, "RX", sid)


def _grant_acl_plan_to_sid(plan: dict[str, Any], sid: str) -> None:
    seen: set[tuple[str, str]] = set()
    for grant in plan["autoGrants"]:
        if not isinstance(grant, dict):
            raise SystemExit("invalid windows_default ACL grant: grant must be an object")
        path = grant.get("path")
        access = grant.get("access")
        if not isinstance(path, str) or access not in {"RX", "RWX"}:
            raise SystemExit("invalid windows_default ACL grant shape")
        key = (str(Path(path)).casefold(), access)
        if key in seen:
            continue
        seen.add(key)
        _grant_path_to_sid(Path(path), access, sid)


def _runner_error_mode_flags() -> int:
    return SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX


def _restricted_process_creation_flags() -> int:
    return CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW


def _restricted_process_application_name(argv: Sequence[str]) -> str | None:
    if not argv:
        return None
    executable = argv[0]
    if PureWindowsPath(executable).is_absolute():
        return executable
    return None


def _offline_helper_creation_flags() -> int:
    return CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW


def _restricted_process_startup_flags() -> int:
    return STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW


def _run_payload_as_offline_identity_native(
    payload: HelperPayload,
    *,
    username: str,
    password: str,
) -> int:
    if not sys.platform.startswith("win"):
        raise OSError("offline_identity_launch_requires_windows")

    import ctypes
    import msvcrt
    import threading
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LPVOID = wintypes.LPVOID
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", DWORD),
            ("lpSecurityDescriptor", LPVOID),
            ("bInheritHandle", BOOL),
        ]

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ("cb", DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", DWORD),
            ("dwY", DWORD),
            ("dwXSize", DWORD),
            ("dwYSize", DWORD),
            ("dwXCountChars", DWORD),
            ("dwYCountChars", DWORD),
            ("dwFillAttribute", DWORD),
            ("dwFlags", DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", HANDLE),
            ("hStdOutput", HANDLE),
            ("hStdError", HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", HANDLE),
            ("hThread", HANDLE),
            ("dwProcessId", DWORD),
            ("dwThreadId", DWORD),
        ]

    advapi32.CreateProcessWithLogonW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        DWORD,
        LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessWithLogonW.restype = BOOL
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        DWORD,
    ]
    kernel32.CreatePipe.restype = BOOL
    kernel32.SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
    kernel32.SetHandleInformation.restype = BOOL
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = BOOL
    kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    kernel32.WaitForSingleObject.restype = DWORD
    kernel32.TerminateProcess.argtypes = [HANDLE, DWORD]
    kernel32.TerminateProcess.restype = BOOL
    kernel32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel32.GetExitCodeProcess.restype = BOOL
    kernel32.SetErrorMode.argtypes = [DWORD]
    kernel32.SetErrorMode.restype = DWORD

    HANDLE_FLAG_INHERIT = 0x00000001
    LOGON_WITH_PROFILE = 0x00000001
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF

    def win_error(label: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{label} failed: {ctypes.FormatError(code)}")

    def close(handle: int) -> None:
        if handle:
            kernel32.CloseHandle(handle)

    stdin_read = HANDLE()
    stdin_write = HANDLE()
    stdout_read = HANDLE()
    stdout_write = HANDLE()
    stderr_read = HANDLE()
    stderr_write = HANDLE()
    process_info = PROCESS_INFORMATION()
    reader_threads: list[threading.Thread] = []
    outputs: dict[str, bytes] = {"stdout": b"", "stderr": b""}
    payload_path: Path | None = None

    try:
        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = None
        sa.bInheritHandle = True
        if not kernel32.CreatePipe(
            ctypes.byref(stdin_read),
            ctypes.byref(stdin_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stdin)")
        kernel32.SetHandleInformation(stdin_write, HANDLE_FLAG_INHERIT, 0)
        if not kernel32.CreatePipe(
            ctypes.byref(stdout_read),
            ctypes.byref(stdout_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stdout)")
        if not kernel32.CreatePipe(
            ctypes.byref(stderr_read),
            ctypes.byref(stderr_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stderr)")
        kernel32.SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0)
        kernel32.SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0)

        startup = STARTUPINFO()
        startup.cb = ctypes.sizeof(STARTUPINFO)
        startup.dwFlags = _restricted_process_startup_flags()
        startup.wShowWindow = SW_HIDE
        startup.hStdInput = stdin_read
        startup.hStdOutput = stdout_write
        startup.hStdError = stderr_write

        payload_path = _write_offline_payload_file(payload)
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline(
                [
                    sys.executable,
                    "-m",
                    HELPER_MODULE,
                    OFFLINE_PAYLOAD_FILE_ARG,
                    str(payload_path),
                ]
            )
        )
        child_env = _helper_child_env()
        env_block = ctypes.create_unicode_buffer(_environment_block(child_env))
        previous_error_mode = kernel32.SetErrorMode(_runner_error_mode_flags())
        try:
            created = advapi32.CreateProcessWithLogonW(
                username,
                ".",
                password,
                LOGON_WITH_PROFILE,
                sys.executable,
                command_line,
                _offline_helper_creation_flags(),
                env_block,
                str(_helper_import_root()),
                ctypes.byref(startup),
                ctypes.byref(process_info),
            )
        finally:
            kernel32.SetErrorMode(previous_error_mode)
        if not created:
            raise win_error("CreateProcessWithLogonW")

        close(stdin_read)
        stdin_read = HANDLE()
        close(stdin_write)
        stdin_write = HANDLE()
        close(stdout_write)
        stdout_write = HANDLE()
        close(stderr_write)
        stderr_write = HANDLE()

        def read_pipe(name: str, handle: object) -> None:
            raw_handle = getattr(handle, "value", handle)
            fd = msvcrt.open_osfhandle(int(raw_handle), os.O_RDONLY | os.O_BINARY)
            with os.fdopen(fd, "rb", closefd=True) as stream:
                outputs[name] = stream.read()

        for name, handle in (("stdout", stdout_read), ("stderr", stderr_read)):
            thread = threading.Thread(target=read_pipe, args=(name, handle), daemon=True)
            thread.start()
            reader_threads.append(thread)
        stdout_read = HANDLE()
        stderr_read = HANDLE()

        wait_ms = max(1, int(payload.timeout * 1000))
        wait_result = kernel32.WaitForSingleObject(process_info.hProcess, wait_ms)
        if wait_result == WAIT_TIMEOUT:
            kernel32.TerminateProcess(process_info.hProcess, 124)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            exit_code = 124
        elif wait_result == WAIT_FAILED:
            raise win_error("WaitForSingleObject")
        else:
            code = DWORD()
            if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(code)):
                raise win_error("GetExitCodeProcess")
            exit_code = int(code.value)

        for thread in reader_threads:
            thread.join(timeout=5)
        sys.stdout.buffer.write(outputs["stdout"])
        sys.stderr.buffer.write(outputs["stderr"])
        return exit_code
    finally:
        close(stdin_write)
        close(stdin_read)
        close(stdout_write)
        close(stderr_write)
        close(stdout_read)
        close(stderr_read)
        close(process_info.hThread)
        close(process_info.hProcess)
        if payload_path is not None:
            with contextlib.suppress(OSError):
                payload_path.unlink()


def _effective_child_env(payload: HelperPayload) -> dict[str, str]:
    env = dict(payload.env)
    if payload.policy.get("network") == "proxy_allowlist":
        proxy = payload.policy.get("network_proxy") or payload.policy.get("networkProxy")
        if isinstance(proxy, dict):
            from opensquilla.sandbox.backend.windows_default_network import network_proxy_env

            env.update(network_proxy_env(str(proxy["host"]), int(proxy["port"])))
    _inject_git_safe_directory(env, payload.cwd)
    return env


def _inject_git_safe_directory(env: dict[str, str], cwd: Path) -> None:
    root = _find_git_worktree_root_for_safe_directory(cwd)
    if root is None:
        return
    _append_git_config(env, "safe.directory", str(root).replace("\\", "/"))


def _find_git_worktree_root_for_safe_directory(start: Path) -> Path | None:
    try:
        current = start.resolve(strict=False)
    except OSError:
        current = start
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _append_git_config(env: dict[str, str], key: str, value: str) -> None:
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    env[f"GIT_CONFIG_KEY_{index}"] = key
    env[f"GIT_CONFIG_VALUE_{index}"] = value
    env["GIT_CONFIG_COUNT"] = str(index + 1)


def _run_restricted_process_native(
    payload: HelperPayload,
    capability_sids: tuple[str, ...],
) -> int:
    if not sys.platform.startswith("win"):
        raise SystemExit("windows_default runner only runs on native Windows")

    try:
        return _run_restricted_process_native_impl(payload, capability_sids)
    except OSError as exc:
        raise SystemExit(f"windows_default process launch failed: {exc}") from exc


def _finalize_restricted_token(token: int, dacl_sids: Sequence[object]) -> None:
    _set_token_default_dacl(token, dacl_sids)
    _enable_token_privilege(token, "SeChangeNotifyPrivilege")


def _set_token_default_dacl(token: int, dacl_sids: Sequence[object]) -> None:
    if not dacl_sids:
        return
    _set_token_default_dacl_native(token, dacl_sids)


def _enable_token_privilege(token: int, name: str) -> None:
    _enable_token_privilege_native(token, name)


def _set_token_default_dacl_native(token: int, dacl_sids: Sequence[object]) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    DWORD = wintypes.DWORD
    LPVOID = wintypes.LPVOID

    class TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", LPVOID),
            ("MultipleTrusteeOperation", DWORD),
            ("TrusteeForm", DWORD),
            ("TrusteeType", DWORD),
            ("ptstrName", LPVOID),
        ]

    class EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", DWORD),
            ("grfAccessMode", DWORD),
            ("grfInheritance", DWORD),
            ("Trustee", TRUSTEE_W),
        ]

    class TOKEN_DEFAULT_DACL(ctypes.Structure):
        _fields_ = [("DefaultDacl", LPVOID)]

    advapi32.SetEntriesInAclW.argtypes = [
        DWORD,
        ctypes.POINTER(EXPLICIT_ACCESS_W),
        LPVOID,
        ctypes.POINTER(LPVOID),
    ]
    advapi32.SetEntriesInAclW.restype = DWORD
    advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, DWORD, LPVOID, DWORD]
    advapi32.SetTokenInformation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [LPVOID]
    kernel32.LocalFree.restype = LPVOID

    ERROR_SUCCESS = 0
    GRANT_ACCESS = 1
    TRUSTEE_IS_SID = 0
    TRUSTEE_IS_UNKNOWN = 0
    TOKEN_DEFAULT_DACL_CLASS = 6

    entries = (EXPLICIT_ACCESS_W * len(dacl_sids))()
    for index, sid in enumerate(dacl_sids):
        entries[index].grfAccessPermissions = GENERIC_ALL
        entries[index].grfAccessMode = GRANT_ACCESS
        entries[index].grfInheritance = 0
        entries[index].Trustee.pMultipleTrustee = None
        entries[index].Trustee.MultipleTrusteeOperation = 0
        entries[index].Trustee.TrusteeForm = TRUSTEE_IS_SID
        entries[index].Trustee.TrusteeType = TRUSTEE_IS_UNKNOWN
        entries[index].Trustee.ptstrName = sid

    new_dacl = LPVOID()
    code = advapi32.SetEntriesInAclW(
        len(dacl_sids),
        entries,
        None,
        ctypes.byref(new_dacl),
    )
    if code != ERROR_SUCCESS:
        raise OSError(code, f"SetEntriesInAclW failed: {ctypes.FormatError(code)}")
    try:
        info = TOKEN_DEFAULT_DACL(new_dacl)
        if not advapi32.SetTokenInformation(
            token,
            TOKEN_DEFAULT_DACL_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error_code = ctypes.get_last_error()
            raise OSError(
                error_code,
                f"SetTokenInformation(TokenDefaultDacl) failed: "
                f"{ctypes.FormatError(error_code)}",
            )
    finally:
        if new_dacl:
            kernel32.LocalFree(new_dacl)


def _enable_token_privilege_native(token: int, name: str) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    DWORD = wintypes.DWORD
    LPVOID = wintypes.LPVOID

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", DWORD), ("HighPart", ctypes.c_long)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    SE_PRIVILEGE_ENABLED = 0x00000002

    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(LUID),
    ]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(TOKEN_PRIVILEGES),
        DWORD,
        LPVOID,
        LPVOID,
    ]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            f"LookupPrivilegeValueW({name}) failed: {ctypes.FormatError(error_code)}",
        )
    privileges = TOKEN_PRIVILEGES()
    privileges.PrivilegeCount = 1
    privileges.Privileges[0].Luid = luid
    privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    if not advapi32.AdjustTokenPrivileges(
        token,
        False,
        ctypes.byref(privileges),
        0,
        None,
        None,
    ):
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            f"AdjustTokenPrivileges({name}) failed: {ctypes.FormatError(error_code)}",
        )


def _write_child_stdin(kernel32: object, stdin_write: object, stdin: bytes | None) -> None:
    import ctypes
    from ctypes import wintypes

    try:
        if stdin:
            offset = 0
            while offset < len(stdin):
                chunk = stdin[offset:]
                written = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(chunk)
                if not kernel32.WriteFile(
                    stdin_write,
                    buffer,
                    len(chunk),
                    ctypes.byref(written),
                    None,
                ):
                    raise OSError(ctypes.get_last_error(), "WriteFile(stdin) failed")
                if written.value == 0:
                    raise OSError(0, "WriteFile(stdin) wrote zero bytes")
                offset += written.value
    finally:
        kernel32.CloseHandle(stdin_write)


def _run_restricted_process_native_impl(
    payload: HelperPayload,
    capability_sids: tuple[str, ...],
) -> int:
    import ctypes
    import msvcrt
    import threading
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LPVOID = wintypes.LPVOID
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", DWORD),
            ("lpSecurityDescriptor", LPVOID),
            ("bInheritHandle", BOOL),
        ]

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Sid", LPVOID),
            ("Attributes", DWORD),
        ]

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ("cb", DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", DWORD),
            ("dwY", DWORD),
            ("dwXSize", DWORD),
            ("dwYSize", DWORD),
            ("dwXCountChars", DWORD),
            ("dwYCountChars", DWORD),
            ("dwFillAttribute", DWORD),
            ("dwFlags", DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", HANDLE),
            ("hStdOutput", HANDLE),
            ("hStdError", HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", HANDLE),
            ("hThread", HANDLE),
            ("dwProcessId", DWORD),
            ("dwThreadId", DWORD),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", DWORD),
            ("SchedulingClass", DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    advapi32.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi32.OpenProcessToken.restype = BOOL
    advapi32.GetTokenInformation.argtypes = [HANDLE, DWORD, LPVOID, DWORD, ctypes.POINTER(DWORD)]
    advapi32.GetTokenInformation.restype = BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(LPVOID)]
    advapi32.ConvertStringSidToSidW.restype = BOOL
    advapi32.CreateRestrictedToken.argtypes = [
        HANDLE,
        DWORD,
        DWORD,
        LPVOID,
        DWORD,
        LPVOID,
        DWORD,
        ctypes.POINTER(SID_AND_ATTRIBUTES),
        ctypes.POINTER(HANDLE),
    ]
    advapi32.CreateRestrictedToken.restype = BOOL
    advapi32.CreateProcessAsUserW.argtypes = [
        HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        LPVOID,
        LPVOID,
        BOOL,
        DWORD,
        LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessAsUserW.restype = BOOL
    advapi32.CreateProcessWithTokenW.argtypes = [
        HANDLE,
        DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        DWORD,
        LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessWithTokenW.restype = BOOL

    kernel32.GetCurrentProcess.restype = HANDLE
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        DWORD,
    ]
    kernel32.CreatePipe.restype = BOOL
    kernel32.SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
    kernel32.SetHandleInformation.restype = BOOL
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = BOOL
    kernel32.CreateJobObjectW.argtypes = [LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = HANDLE
    kernel32.SetInformationJobObject.argtypes = [HANDLE, ctypes.c_int, LPVOID, DWORD]
    kernel32.SetInformationJobObject.restype = BOOL
    kernel32.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    kernel32.AssignProcessToJobObject.restype = BOOL
    kernel32.ResumeThread.argtypes = [HANDLE]
    kernel32.ResumeThread.restype = DWORD
    kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    kernel32.WaitForSingleObject.restype = DWORD
    kernel32.TerminateJobObject.argtypes = [HANDLE, DWORD]
    kernel32.TerminateJobObject.restype = BOOL
    kernel32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel32.GetExitCodeProcess.restype = BOOL
    kernel32.WriteFile.argtypes = [HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID]
    kernel32.WriteFile.restype = BOOL
    kernel32.SetErrorMode.argtypes = [DWORD]
    kernel32.SetErrorMode.restype = DWORD

    TOKEN_USER_CLASS = 1
    TOKEN_GROUPS_CLASS = 2
    SE_GROUP_LOGON_ID = 0xC0000000
    HANDLE_FLAG_INHERIT = 0x00000001
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF

    def win_error(label: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{label} failed: {ctypes.FormatError(code)}")

    def close(handle: int) -> None:
        if handle:
            kernel32.CloseHandle(handle)

    def convert_sid(value: str, label: str) -> object:
        sid = LPVOID()
        if not advapi32.ConvertStringSidToSidW(value, ctypes.byref(sid)):
            raise win_error(f"ConvertStringSidToSidW({label})")
        return sid

    def user_sid_from_token(token: int) -> tuple[object | None, object | None]:
        needed = DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None, None
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_USER_CLASS,
            buffer,
            needed,
            ctypes.byref(needed),
        ):
            return None, None
        user = SID_AND_ATTRIBUTES.from_buffer(buffer)
        return user.Sid, buffer

    def logon_sid_from_token(token: int) -> tuple[object | None, object | None]:
        needed = DWORD()
        advapi32.GetTokenInformation(token, TOKEN_GROUPS_CLASS, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None, None
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_GROUPS_CLASS,
            buffer,
            needed,
            ctypes.byref(needed),
        ):
            return None, None
        group_count = ctypes.cast(buffer, ctypes.POINTER(DWORD)).contents.value
        offset = ctypes.sizeof(DWORD)
        align = ctypes.alignment(SID_AND_ATTRIBUTES)
        offset = (offset + align - 1) & ~(align - 1)
        groups_type = SID_AND_ATTRIBUTES * group_count
        groups = groups_type.from_buffer(buffer, offset)
        for group in groups:
            if group.Attributes & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID:
                return group.Sid, buffer
        return None, buffer

    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [LPVOID]
    local_free.restype = LPVOID

    source_token = HANDLE()
    restricted_token = HANDLE()
    allocated_sids: list[object] = []
    user_sid_buffer: object | None = None
    logon_sid_buffer: object | None = None
    stdin_read = HANDLE()
    stdin_write = HANDLE()
    stdout_read = HANDLE()
    stdout_write = HANDLE()
    stderr_read = HANDLE()
    stderr_write = HANDLE()
    job = HANDLE()
    process_info = PROCESS_INFORMATION()
    reader_threads: list[threading.Thread] = []
    outputs: dict[str, bytes] = {"stdout": b"", "stderr": b""}

    try:
        source_token = HANDLE(_open_source_token_for_payload(payload))

        capability_sid_ptrs = []
        for index, capability_sid in enumerate(capability_sids):
            sid = convert_sid(capability_sid, f"capability-{index}")
            allocated_sids.append(sid)
            capability_sid_ptrs.append(sid)

        user_sid, user_sid_buffer = user_sid_from_token(source_token)
        logon_sid, logon_sid_buffer = logon_sid_from_token(source_token)
        base_sid_ptrs = []
        for sid_value, sid_label in _base_restricting_sid_specs():
            sid = convert_sid(sid_value, sid_label)
            allocated_sids.append(sid)
            base_sid_ptrs.append(sid)
        restricting_sids = _ordered_restricting_sids(
            capability_sids=tuple(capability_sid_ptrs),
            user_sid=user_sid,
            logon_sid=logon_sid,
            base_sids=tuple(base_sid_ptrs),
        )
        restricting_entries = (SID_AND_ATTRIBUTES * len(restricting_sids))()
        for index, sid in enumerate(restricting_sids):
            restricting_entries[index].Sid = sid
            restricting_entries[index].Attributes = 0

        if not advapi32.CreateRestrictedToken(
            source_token,
            RESTRICTED_TOKEN_FLAGS,
            0,
            None,
            0,
            None,
            len(restricting_sids),
            restricting_entries,
            ctypes.byref(restricted_token),
        ):
            raise win_error("CreateRestrictedToken")
        dacl_sids = []
        if logon_sid:
            dacl_sids.append(logon_sid)
        dacl_sids.extend(restricting_sids)
        _finalize_restricted_token(restricted_token, dacl_sids)

        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = None
        sa.bInheritHandle = True
        if not kernel32.CreatePipe(
            ctypes.byref(stdin_read),
            ctypes.byref(stdin_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stdin)")
        kernel32.SetHandleInformation(stdin_write, HANDLE_FLAG_INHERIT, 0)
        if not kernel32.CreatePipe(
            ctypes.byref(stdout_read),
            ctypes.byref(stdout_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stdout)")
        if not kernel32.CreatePipe(
            ctypes.byref(stderr_read),
            ctypes.byref(stderr_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stderr)")
        kernel32.SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0)
        kernel32.SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0)

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise win_error("CreateJobObjectW")
        limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limit_info),
            ctypes.sizeof(limit_info),
        ):
            raise win_error("SetInformationJobObject")

        startup = STARTUPINFO()
        startup.cb = ctypes.sizeof(STARTUPINFO)
        startup.lpDesktop = "winsta0\\default"
        startup.dwFlags = _restricted_process_startup_flags()
        startup.wShowWindow = SW_HIDE
        startup.hStdInput = stdin_read
        startup.hStdOutput = stdout_write
        startup.hStdError = stderr_write

        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(payload.argv))
        application_name = _restricted_process_application_name(payload.argv)
        env_block = ctypes.create_unicode_buffer(_environment_block(_effective_child_env(payload)))
        creation_flags = _restricted_process_creation_flags()
        previous_error_mode = kernel32.SetErrorMode(_runner_error_mode_flags())
        create_failures: list[tuple[str, int, str]] = []
        try:
            created = advapi32.CreateProcessAsUserW(
                restricted_token,
                application_name,
                command_line,
                None,
                None,
                True,
                creation_flags,
                env_block,
                str(payload.cwd),
                ctypes.byref(startup),
                ctypes.byref(process_info),
            )
            if not created:
                error_code = ctypes.get_last_error()
                create_failures.append(
                    (
                        "CreateProcessAsUserW",
                        error_code,
                        ctypes.FormatError(error_code).strip(),
                    )
                )
                command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(payload.argv))
                created = advapi32.CreateProcessWithTokenW(
                    restricted_token,
                    0,
                    application_name,
                    command_line,
                    creation_flags,
                    env_block,
                    str(payload.cwd),
                    ctypes.byref(startup),
                    ctypes.byref(process_info),
                )
                if not created:
                    error_code = ctypes.get_last_error()
                    create_failures.append(
                        (
                            "CreateProcessWithTokenW",
                            error_code,
                            ctypes.FormatError(error_code).strip(),
                        )
                    )
        finally:
            kernel32.SetErrorMode(previous_error_mode)
        if not created:
            if create_failures:
                code = create_failures[-1][1]
                details = "; ".join(
                    f"{name}={error_code} {message}"
                    for name, error_code, message in create_failures
                )
                raise OSError(
                    code,
                    f"CreateProcessAsUserW/CreateProcessWithTokenW failed: {details}",
                )
            raise win_error("CreateProcessAsUserW/CreateProcessWithTokenW")

        close(stdin_read)
        stdin_read = HANDLE()
        _write_child_stdin(kernel32, stdin_write, payload.stdin)
        stdin_write = HANDLE()
        close(stdout_write)
        stdout_write = HANDLE()
        close(stderr_write)
        stderr_write = HANDLE()

        if not kernel32.AssignProcessToJobObject(job, process_info.hProcess):
            raise win_error("AssignProcessToJobObject")
        if kernel32.ResumeThread(process_info.hThread) == WAIT_FAILED:
            raise win_error("ResumeThread")

        def read_pipe(name: str, handle: object) -> None:
            raw_handle = getattr(handle, "value", handle)
            fd = msvcrt.open_osfhandle(int(raw_handle), os.O_RDONLY | os.O_BINARY)
            with os.fdopen(fd, "rb", closefd=True) as stream:
                outputs[name] = stream.read()

        for name, handle in (("stdout", stdout_read), ("stderr", stderr_read)):
            thread = threading.Thread(target=read_pipe, args=(name, handle), daemon=True)
            thread.start()
            reader_threads.append(thread)
        stdout_read = HANDLE()
        stderr_read = HANDLE()

        wait_ms = max(1, int(payload.timeout * 1000))
        wait_result = kernel32.WaitForSingleObject(process_info.hProcess, wait_ms)
        if wait_result == WAIT_TIMEOUT:
            kernel32.TerminateJobObject(job, 124)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            exit_code = 124
        elif wait_result == WAIT_FAILED:
            raise win_error("WaitForSingleObject")
        else:
            code = DWORD()
            if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(code)):
                raise win_error("GetExitCodeProcess")
            exit_code = int(code.value)

        for thread in reader_threads:
            thread.join(timeout=5)
        sys.stdout.buffer.write(outputs["stdout"])
        sys.stderr.buffer.write(outputs["stderr"])
        return exit_code
    finally:
        close(stdin_read)
        close(stdin_write)
        close(stdout_write)
        close(stderr_write)
        close(stdout_read)
        close(stderr_read)
        close(process_info.hThread)
        close(process_info.hProcess)
        close(job)
        close(restricted_token)
        close(source_token)
        for sid in allocated_sids:
            if sid:
                local_free(sid)
        _ = user_sid_buffer
        _ = logon_sid_buffer


if __name__ == "__main__":
    main()
