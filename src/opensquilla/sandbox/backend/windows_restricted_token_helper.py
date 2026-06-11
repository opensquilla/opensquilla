"""Windows restricted-token helper.

The adapter invokes this module in a separate interpreter. The helper owns the
Windows-only process boundary: filesystem ACL grants, restricted token
creation, kill-on-close job lifetime, child process creation, and output
capture.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        raise SystemExit(_run_restricted(payload))
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
    if network == "proxy_allowlist":
        raise SystemExit(
            "windows_restricted_token helper cannot enforce proxy_allowlist "
            "without a Windows network boundary"
        )


def _run_restricted(payload: _HelperPayload) -> int:
    restricting_sid = _session_restricting_sid()
    _grant_policy_paths(payload, restricting_sid)
    return _run_restricted_process(payload, restricting_sid)


def _session_restricting_sid() -> str:
    # Well-known "RESTRICTED" SID. Python Phase 1 uses icacls for ACL grants,
    # which cannot grant ACEs to arbitrary, unmapped random SIDs.
    return "S-1-5-12"


def _rights_for_mode(mode: str) -> str:
    if mode == "rw":
        return "M"
    if mode == "ro":
        return "RX"
    raise SystemExit(f"invalid windows_restricted_token policy: unknown mount mode {mode!r}")


def _grant_policy_paths(payload: _HelperPayload, sid: str) -> None:
    mounts = payload.policy.get("mounts")
    if not isinstance(mounts, list):
        raise SystemExit("invalid windows_restricted_token policy: mounts must be a list")
    for mount in mounts:
        if not isinstance(mount, dict):
            raise SystemExit("invalid windows_restricted_token policy: mount must be an object")
        host = mount.get("host")
        mode = mount.get("mode")
        required = bool(mount.get("required", True))
        if not isinstance(host, str) or not isinstance(mode, str):
            raise SystemExit("invalid windows_restricted_token policy: invalid mount shape")
        path = Path(host)
        if not path.exists():
            if required:
                raise SystemExit(f"required windows_restricted_token mount does not exist: {path}")
            continue
        rights = _rights_for_mode(mode)
        grant = f"*{sid}:(OI)(CI){rights}" if path.is_dir() else f"*{sid}:{rights}"
        argv = ["icacls", str(path), "/grant", grant, "/C"]
        if path.is_dir():
            argv.append("/T")
        completed = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(
                "windows_restricted_token ACL grant failed for "
                f"{path}: {completed.stderr.strip()}"
            )


def _run_restricted_process(payload: _HelperPayload, restricting_sid: str) -> int:
    if not sys.platform.startswith("win"):
        raise SystemExit("windows_restricted_token helper only runs on native Windows")
    try:
        return _run_restricted_process_native(payload, restricting_sid)
    except OSError as exc:
        raise SystemExit(f"windows_restricted_token process launch failed: {exc}") from exc


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


def _run_restricted_process_native(payload: _HelperPayload, restricting_sid: str) -> int:
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

    def win_error(label: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{label} failed: {ctypes.FormatError(code)}")

    def close(handle: int) -> None:
        if handle:
            kernel32.CloseHandle(handle)

    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [LPVOID]
    local_free.restype = LPVOID

    source_token = HANDLE()
    restricted_token = HANDLE()
    sid_restrict = LPVOID()
    sid_everyone = LPVOID()
    stdout_read = HANDLE()
    stdout_write = HANDLE()
    stderr_read = HANDLE()
    stderr_write = HANDLE()
    job = HANDLE()
    process_info = PROCESS_INFORMATION()
    reader_threads: list[threading.Thread] = []
    outputs: dict[str, bytes] = {"stdout": b"", "stderr": b""}

    TOKEN_ASSIGN_PRIMARY = 0x0001
    TOKEN_DUPLICATE = 0x0002
    TOKEN_QUERY = 0x0008
    TOKEN_ADJUST_DEFAULT = 0x0080
    TOKEN_ADJUST_SESSIONID = 0x0100
    DISABLE_MAX_PRIVILEGE = 0x01
    LUA_TOKEN = 0x04
    WRITE_RESTRICTED = 0x08
    STARTF_USESTDHANDLES = 0x00000100
    CREATE_SUSPENDED = 0x00000004
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000
    HANDLE_FLAG_INHERIT = 0x00000001
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF

    try:
        desired_access = (
            TOKEN_ASSIGN_PRIMARY
            | TOKEN_DUPLICATE
            | TOKEN_QUERY
            | TOKEN_ADJUST_DEFAULT
            | TOKEN_ADJUST_SESSIONID
        )
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            desired_access,
            ctypes.byref(source_token),
        ):
            raise win_error("OpenProcessToken")

        if not advapi32.ConvertStringSidToSidW(restricting_sid, ctypes.byref(sid_restrict)):
            raise win_error("ConvertStringSidToSidW(restricting)")
        if not advapi32.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(sid_everyone)):
            raise win_error("ConvertStringSidToSidW(everyone)")

        restricting_entries = (SID_AND_ATTRIBUTES * 2)()
        restricting_entries[0].Sid = sid_restrict
        restricting_entries[0].Attributes = 0
        restricting_entries[1].Sid = sid_everyone
        restricting_entries[1].Attributes = 0

        if not advapi32.CreateRestrictedToken(
            source_token,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
            0,
            None,
            0,
            None,
            2,
            restricting_entries,
            ctypes.byref(restricted_token),
        ):
            raise win_error("CreateRestrictedToken")

        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = None
        sa.bInheritHandle = True
        if not kernel32.CreatePipe(ctypes.byref(stdout_read), ctypes.byref(stdout_write), ctypes.byref(sa), 0):
            raise win_error("CreatePipe(stdout)")
        if not kernel32.CreatePipe(ctypes.byref(stderr_read), ctypes.byref(stderr_write), ctypes.byref(sa), 0):
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
        startup.dwFlags = STARTF_USESTDHANDLES
        startup.hStdInput = 0
        startup.hStdOutput = stdout_write
        startup.hStdError = stderr_write

        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(payload.argv))
        env_block = ctypes.create_unicode_buffer(_environment_block(payload.env))
        creation_flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
        created = advapi32.CreateProcessAsUserW(
            restricted_token,
            None,
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
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(payload.argv))
            created = advapi32.CreateProcessWithTokenW(
                restricted_token,
                0,
                None,
                command_line,
                creation_flags,
                env_block,
                str(payload.cwd),
                ctypes.byref(startup),
                ctypes.byref(process_info),
            )
        if not created:
            raise win_error("CreateProcessAsUserW/CreateProcessWithTokenW")

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
        close(stdout_write)
        close(stderr_write)
        close(stdout_read)
        close(stderr_read)
        close(process_info.hThread)
        close(process_info.hProcess)
        close(job)
        close(restricted_token)
        close(source_token)
        if sid_restrict:
            local_free(sid_restrict)
        if sid_everyone:
            local_free(sid_everyone)


def restricted_token_smoke_check() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        payload = _HelperPayload(
            argv=("cmd", "/c", "exit", "0"),
            cwd=Path.cwd(),
            env={"PATH": os.environ.get("PATH", "")},
            policy={
                "network": "none",
                "mounts": [
                    {
                        "host": str(Path.cwd()),
                        "sandbox": str(Path.cwd()),
                        "mode": "ro",
                        "required": True,
                    }
                ],
            },
            timeout=5.0,
        )
        return _run_restricted(payload) == 0
    except BaseException:
        return False


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main", "restricted_token_smoke_check"]
