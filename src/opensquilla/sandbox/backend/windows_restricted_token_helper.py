"""Fail-closed Windows restricted-token helper.

The adapter invokes this module in a separate interpreter. The helper owns the
Windows-only boundary: restricted token creation, job-object lifetime, and child
process creation. Until filesystem and network restrictions are robust enough
to enforce the full sandbox policy, the helper validates input and exits
non-zero instead of launching the requested command.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UNENFORCEABLE = "windows_restricted_token helper cannot enforce policy on this host"


@dataclass(frozen=True)
class _HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    timeout: float


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not sys.platform.startswith("win"):
            raise SystemExit("windows_restricted_token helper only runs on native Windows")
        payload = _parse_payload(args)
        _validate_policy_is_enforceable(payload.policy)
        _run_restricted(payload)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(1) from None
        raise


def _parse_payload(args: Sequence[str]) -> _HelperPayload:
    if len(args) != 1:
        raise SystemExit("windows_restricted_token helper expects one JSON payload argument")
    try:
        raw = json.loads(args[0])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid windows_restricted_token payload JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("invalid windows_restricted_token payload: expected object")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise SystemExit("invalid windows_restricted_token payload: argv must be a string list")

    cwd_raw = raw.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        raise SystemExit("invalid windows_restricted_token payload: cwd is required")
    cwd = Path(cwd_raw)
    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"invalid windows_restricted_token cwd: {cwd}")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in env_raw.items()
    ):
        raise SystemExit("invalid windows_restricted_token payload: env must be string map")

    policy = raw.get("policy")
    if not isinstance(policy, dict):
        raise SystemExit("invalid windows_restricted_token payload: policy is required")

    timeout = raw.get("timeout")
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SystemExit("invalid windows_restricted_token payload: timeout must be positive")

    return _HelperPayload(
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env_raw),
        policy=policy,
        timeout=float(timeout),
    )


def _validate_policy_is_enforceable(policy: dict[str, Any]) -> None:
    network = policy.get("network")
    if network not in {"none", "host", "proxy_allowlist"}:
        raise SystemExit(
            f"windows_restricted_token helper received unknown network mode: {network!r}"
        )

    # Restricted tokens alone are not a complete sandbox. Until this helper can
    # pair the process boundary with deny-by-default filesystem ACLs and a real
    # network restriction/allowlist story, every policy remains unenforceable.
    raise SystemExit(_UNENFORCEABLE)


def _run_restricted(payload: _HelperPayload) -> None:
    """Structured skeleton for the future Win32 process boundary."""
    handles = _create_restricted_token_and_job()
    _create_process_with_restricted_token(payload, handles)


@dataclass(frozen=True)
class _Win32BoundaryHandles:
    token: int
    job: int


def _create_restricted_token_and_job() -> _Win32BoundaryHandles:
    """Create a restricted primary token and kill-on-close job object.

    This is deliberately not called while policy enforcement is incomplete.
    It documents the concrete Win32 APIs and constants the final helper will
    use without risking an unsandboxed child process.
    """
    if not sys.platform.startswith("win"):
        raise SystemExit("windows_restricted_token helper only runs on native Windows")

    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    create_restricted_token_disable_max_privilege = 0x1
    job_object_limit_kill_on_job_close = 0x00002000
    job_object_extended_limit_information = 9

    current_process = kernel32.GetCurrentProcess()
    source_token = wintypes.HANDLE()
    token_duplicate = 0x0002
    token_assign_primary = 0x0001
    token_query = 0x0008
    token_adjust_default = 0x0080
    token_adjust_sessionid = 0x0100
    desired_access = (
        token_duplicate
        | token_assign_primary
        | token_query
        | token_adjust_default
        | token_adjust_sessionid
    )

    if not advapi32.OpenProcessToken(current_process, desired_access, ctypes.byref(source_token)):
        raise ctypes.WinError(ctypes.get_last_error())

    restricted_token = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(
        source_token,
        create_restricted_token_disable_max_privilege,
        0,
        None,
        0,
        None,
        0,
        None,
        ctypes.byref(restricted_token),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())

    class JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JobObjectBasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    limit_info = JobObjectExtendedLimitInformation()
    limit_info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    if not kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(limit_info),
        ctypes.sizeof(limit_info),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    return _Win32BoundaryHandles(token=int(restricted_token.value), job=int(job))


def _create_process_with_restricted_token(
    payload: _HelperPayload,
    handles: _Win32BoundaryHandles,
) -> None:
    """Future CreateProcessAsUserW boundary; currently fail closed."""
    _ = (payload, handles, os.environ)
    raise SystemExit(_UNENFORCEABLE)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main"]
