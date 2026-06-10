from __future__ import annotations

import asyncio
import ctypes
import ntpath
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from subprocess import list2cmdline

from opensquilla.sandbox.types import SandboxBackendError

_PROFILE_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PROFILE_PREFIX = "opensquilla-sandbox-"
_PROFILE_MAX_LENGTH = 64
_HRESULT_ALREADY_EXISTS = 0x800700B7
_ERROR_BROKEN_PIPE = 109
_ERROR_INSUFFICIENT_BUFFER = 122
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x00000102
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_SUSPENDED = 0x00000004
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_STILL_ACTIVE = 259
_TIMEOUT_RETURN_CODE = 124
_ERROR_SUCCESS = 0
_SE_WINDOW_OBJECT = 7
_DACL_SECURITY_INFORMATION = 0x00000004
_SET_ACCESS = 2
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_TOKEN_QUERY = 0x0008
_TOKEN_ADJUST_DEFAULT = 0x0080
_TOKEN_USER_CLASS = 1
_TOKEN_DEFAULT_DACL_CLASS = 6
_READ_CONTROL = 0x00020000
_GENERIC_ALL = 0x10000000
_WINSTA_ENUMDESKTOPS = 0x0001
_WINSTA_READATTRIBUTES = 0x0002
_WINSTA_ACCESSGLOBALATOMS = 0x0020
_WINSTA_ENUMERATE = 0x0100
_DESKTOP_READOBJECTS = 0x0001
_DESKTOP_CREATEWINDOW = 0x0002
_DESKTOP_CREATEMENU = 0x0004
_DESKTOP_ENUMERATE = 0x0040
_DESKTOP_WRITEOBJECTS = 0x0080
_SANDBOXED_POWERSHELL_WINDOW_STATION_ACCESS = (
    _READ_CONTROL
    | _WINSTA_ENUMDESKTOPS
    | _WINSTA_READATTRIBUTES
    | _WINSTA_ACCESSGLOBALATOMS
    | _WINSTA_ENUMERATE
)
_SANDBOXED_POWERSHELL_DESKTOP_ACCESS = (
    _READ_CONTROL
    | _DESKTOP_READOBJECTS
    | _DESKTOP_CREATEWINDOW
    | _DESKTOP_CREATEMENU
    | _DESKTOP_ENUMERATE
    | _DESKTOP_WRITEOBJECTS
)


@dataclass(frozen=True)
class AppContainerLaunchResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class AppContainerIdentity:
    profile_name: str
    appcontainer_sid: str


class _Win32Error(SandboxBackendError):
    def __init__(self, function: str, code: int) -> None:
        self.function = function
        self.code = code & 0xFFFFFFFF
        super().__init__(f"{function} failed with error code 0x{self.code:08X}")


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    )


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = (
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", wintypes.LPVOID),
    )


class _ProcessInformation(ctypes.Structure):
    _fields_ = (
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    )


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    )


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = (
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", wintypes.LPVOID),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    )


class _TokenDefaultDacl(ctypes.Structure):
    _fields_ = (("DefaultDacl", wintypes.LPVOID),)


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (
        ("Sid", wintypes.LPVOID),
        ("Attributes", wintypes.DWORD),
    )


class _TokenUser(ctypes.Structure):
    _fields_ = (("User", _SidAndAttributes),)


class _TrusteeW(ctypes.Structure):
    _fields_ = (
        ("pMultipleTrustee", wintypes.LPVOID),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", wintypes.LPWSTR),
    )


class _ExplicitAccessW(ctypes.Structure):
    _fields_ = (
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TrusteeW),
    )


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    )


class _IoCounters(ctypes.Structure):
    _fields_ = (
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    )


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


@dataclass(frozen=True)
class _AppContainerSid:
    pointer: wintypes.LPVOID
    sid_string: str


@dataclass(frozen=True)
class _ProcThreadAttributeList:
    buffer: ctypes.Array[ctypes.c_char]
    handle_array: ctypes.Array[wintypes.HANDLE]


def appcontainer_profile_name(session_id: str) -> str:
    safe = _PROFILE_SAFE_RE.sub("-", session_id.lower()).strip("-")
    if not safe:
        safe = "default"
    return f"{_PROFILE_PREFIX}{safe}"[:_PROFILE_MAX_LENGTH].rstrip("-")


def prepare_appcontainer_identity(session_id: str) -> AppContainerIdentity:
    profile_name = appcontainer_profile_name(session_id)
    appcontainer_sid = ensure_appcontainer_profile(profile_name)
    return AppContainerIdentity(
        profile_name=profile_name,
        appcontainer_sid=appcontainer_sid,
    )


def ensure_appcontainer_profile(profile_name: str) -> str:
    if not isinstance(profile_name, str) or not profile_name:
        raise SandboxBackendError("AppContainer profile name must be non-empty")
    if not sys.platform.startswith("win"):
        raise SandboxBackendError("AppContainer profile creation requires native Windows")
    api = _get_win32_api()
    try:
        sid_pointer = api.create_appcontainer_profile(profile_name)
    except _Win32Error as exc:
        if exc.code != _HRESULT_ALREADY_EXISTS:
            raise
        sid_pointer = api.derive_appcontainer_sid(profile_name)
    return api.sid_to_string_and_free(sid_pointer)


async def launch_appcontainer_process(
    *,
    profile_name: str,
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> AppContainerLaunchResult:
    _validate_appcontainer_launch_request(
        profile_name=profile_name,
        argv=argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
    if not sys.platform.startswith("win"):
        raise SandboxBackendError("AppContainer launch requires native Windows")
    return await _launch_appcontainer_process_native(
        profile_name=profile_name,
        argv=argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )


def _validate_appcontainer_launch_request(
    *,
    profile_name: str,
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> None:
    if not isinstance(profile_name, str) or not profile_name:
        raise SandboxBackendError("AppContainer launch requires a profile name")
    if "\0" in profile_name:
        raise SandboxBackendError("AppContainer launch profile name must not contain NUL")
    if not isinstance(argv, Sequence) or isinstance(argv, str) or not argv:
        raise SandboxBackendError("AppContainer launch argv must be a non-empty sequence")
    if not all(isinstance(item, str) and item for item in argv):
        raise SandboxBackendError("AppContainer launch argv must contain non-empty strings")
    if any("\0" in item for item in argv):
        raise SandboxBackendError("AppContainer launch argv must not contain NUL")
    if not isinstance(cwd, Path):
        raise SandboxBackendError("AppContainer launch cwd must be a Path")
    if not cwd.exists() or not cwd.is_dir():
        raise SandboxBackendError(f"AppContainer launch cwd must exist: {cwd}")
    if not isinstance(env, Mapping):
        raise SandboxBackendError("AppContainer launch env must be a string mapping")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise SandboxBackendError("AppContainer launch env must be a string mapping")
    if any(not key for key in env):
        raise SandboxBackendError("AppContainer launch env keys must not be empty")
    if any("\0" in key or "=" in key or "\0" in value for key, value in env.items()):
        raise SandboxBackendError(
            "AppContainer launch env keys must not contain NUL or '=' and values "
            "must not contain NUL"
        )
    folded_keys = [key.casefold() for key in env]
    if len(folded_keys) != len(set(folded_keys)):
        raise SandboxBackendError(
            "AppContainer launch env keys must be unique under Windows "
            "case-insensitive comparison"
        )
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SandboxBackendError("AppContainer launch timeout must be positive")


async def _launch_appcontainer_process_native(
    *,
    profile_name: str,
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> AppContainerLaunchResult:
    return await asyncio.to_thread(
        _launch_appcontainer_process_native_sync,
        profile_name=profile_name,
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env),
        timeout=timeout,
    )


def _launch_appcontainer_process_native_sync(
    *,
    profile_name: str,
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> AppContainerLaunchResult:
    api = _get_win32_api()
    sid = _acquire_appcontainer_sid(api, profile_name)
    attribute_list = None
    process_info = _ProcessInformation()
    stdout_read = stdout_write = stderr_read = stderr_write = None
    stdin_read = stdin_write = None
    job_handle = None
    try:
        stdout_read, stdout_write = api.create_pipe(inherit_write=True)
        stderr_read, stderr_write = api.create_pipe(inherit_write=True)
        stdin_read, stdin_write = api.create_pipe(inherit_read=True)
        api.grant_current_window_station_and_desktop(sid.sid_string)
        security_capabilities = _SecurityCapabilities(
            AppContainerSid=sid.pointer,
            Capabilities=None,
            CapabilityCount=0,
            Reserved=0,
        )
        inherited_handles = (stdin_read, stdout_write, stderr_write)
        attribute_list = api.create_appcontainer_attribute_list(
            security_capabilities,
            inherited_handles,
        )
        startup_info = _STARTUPINFOEXW()
        startup_info.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        startup_info.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup_info.StartupInfo.hStdInput = stdin_read
        startup_info.StartupInfo.hStdOutput = stdout_write
        startup_info.StartupInfo.hStdError = stderr_write
        raw_attribute_list = getattr(attribute_list, "buffer", attribute_list)
        startup_info.lpAttributeList = ctypes.cast(raw_attribute_list, wintypes.LPVOID)

        command_line = ctypes.create_unicode_buffer(_windows_command_line(argv))
        environment_block = ctypes.create_unicode_buffer(_windows_environment_block(env))
        creation_flags = (
            _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_UNICODE_ENVIRONMENT
            | _CREATE_SUSPENDED
        )
        job_handle = api.create_kill_on_close_job()
        api.create_process(
            command_line=command_line,
            cwd=str(cwd),
            environment_block=environment_block,
            creation_flags=creation_flags,
            startup_info=startup_info,
            process_info=process_info,
        )
        try:
            api.assign_process_to_job(job_handle, process_info.hProcess)
            api.grant_process_token_default_dacl(process_info.hProcess, sid.sid_string)
            api.resume_thread(process_info.hThread)
        except Exception:
            if process_info.hProcess:
                api.terminate_process(process_info.hProcess, _TIMEOUT_RETURN_CODE)
            raise

        api.close_handle(stdin_read)
        stdin_read = None
        api.close_handle(stdin_write)
        stdin_write = None
        api.close_handle(stdout_write)
        stdout_write = None
        api.close_handle(stderr_write)
        stderr_write = None

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        stdout_reader = threading.Thread(
            target=_read_pipe_into,
            args=(api, stdout_read, stdout_chunks),
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=_read_pipe_into,
            args=(api, stderr_read, stderr_chunks),
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()

        wait_result = api.wait_for_single_object(process_info.hProcess, timeout)
        timed_out = wait_result == _WAIT_TIMEOUT
        if timed_out:
            api.terminate_job(job_handle, _TIMEOUT_RETURN_CODE)
            api.wait_for_single_object(process_info.hProcess, None)
            returncode = _TIMEOUT_RETURN_CODE
        elif wait_result == _WAIT_OBJECT_0:
            returncode = api.get_exit_code_process(process_info.hProcess)
            if returncode == _STILL_ACTIVE:
                returncode = -1
        else:
            raise _Win32Error("WaitForSingleObject", wait_result)

        if not timed_out:
            api.terminate_job(job_handle, returncode)
        api.close_handle(job_handle)
        job_handle = None

        stdout_reader.join()
        stderr_reader.join()
        return AppContainerLaunchResult(
            returncode=returncode,
            stdout=b"".join(stdout_chunks),
            stderr=b"".join(stderr_chunks),
        )
    finally:
        if process_info.hThread:
            api.close_handle(process_info.hThread)
        if process_info.hProcess:
            api.close_handle(process_info.hProcess)
        if job_handle:
            api.close_handle(job_handle)
        for handle in (
            stdin_read,
            stdin_write,
            stdout_read,
            stdout_write,
            stderr_read,
            stderr_write,
        ):
            if handle:
                api.close_handle(handle)
        if attribute_list is not None:
            api.delete_proc_thread_attribute_list(attribute_list)
        api.free_sid(sid.pointer)


def _acquire_appcontainer_sid(api: _Win32Api, profile_name: str) -> _AppContainerSid:
    try:
        sid_pointer = api.create_appcontainer_profile(profile_name)
    except _Win32Error as exc:
        if exc.code != _HRESULT_ALREADY_EXISTS:
            raise
        sid_pointer = api.derive_appcontainer_sid(profile_name)
    try:
        sid_string = api.sid_to_string(sid_pointer)
    except Exception:
        api.free_sid(sid_pointer)
        raise
    return _AppContainerSid(pointer=sid_pointer, sid_string=sid_string)


def _windows_command_line(argv: Sequence[str]) -> str:
    return list2cmdline(list(argv))


def _windows_environment_block(env: Mapping[str, str]) -> str:
    entries = [
        f"{key}={value}"
        for key, value in sorted(env.items(), key=lambda item: item[0].casefold())
    ]
    return "\0".join(entries) + "\0\0"


def _read_pipe_into(api: _Win32Api, handle: wintypes.HANDLE, chunks: list[bytes]) -> None:
    while True:
        chunk = api.read_file(handle)
        if not chunk:
            return
        chunks.append(chunk)


class _Win32Api:
    def __init__(self) -> None:
        if not sys.platform.startswith("win"):
            raise SandboxBackendError("Win32 AppContainer APIs require native Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_prototypes()

    def _configure_prototypes(self) -> None:
        self.userenv.CreateAppContainerProfile.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
        )
        self.userenv.CreateAppContainerProfile.restype = ctypes.c_long
        self.userenv.DeriveAppContainerSidFromAppContainerName.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.LPVOID),
        )
        self.userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
        self.advapi32.ConvertSidToStringSidW.argtypes = (
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPWSTR),
        )
        self.advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self.advapi32.FreeSid.argtypes = (wintypes.LPVOID,)
        self.advapi32.FreeSid.restype = wintypes.LPVOID
        self.advapi32.ConvertStringSidToSidW.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.LPVOID),
        )
        self.advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
        self.advapi32.GetSecurityInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.LPVOID),
        )
        self.advapi32.GetSecurityInfo.restype = wintypes.DWORD
        self.advapi32.SetEntriesInAclW.argtypes = (
            wintypes.ULONG,
            ctypes.POINTER(_ExplicitAccessW),
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPVOID),
        )
        self.advapi32.SetEntriesInAclW.restype = wintypes.DWORD
        self.advapi32.SetSecurityInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
        )
        self.advapi32.SetSecurityInfo.restype = wintypes.DWORD
        self.advapi32.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        self.advapi32.OpenProcessToken.restype = wintypes.BOOL
        self.advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.advapi32.GetTokenInformation.restype = wintypes.BOOL
        self.advapi32.SetTokenInformation.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self.advapi32.SetTokenInformation.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
        self.kernel32.LocalFree.restype = wintypes.HLOCAL
        self.kernel32.GetCurrentThreadId.argtypes = ()
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.kernel32.InitializeProcThreadAttributeList.argtypes = (
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        )
        self.kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        self.kernel32.UpdateProcThreadAttribute.argtypes = (
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            wintypes.LPVOID,
        )
        self.kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        self.kernel32.DeleteProcThreadAttributeList.argtypes = (wintypes.LPVOID,)
        self.kernel32.DeleteProcThreadAttributeList.restype = None
        self.kernel32.CreateProcessW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOEXW),
            ctypes.POINTER(_ProcessInformation),
        )
        self.kernel32.CreateProcessW.restype = wintypes.BOOL
        self.kernel32.CreatePipe.argtypes = (
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(_SecurityAttributes),
            wintypes.DWORD,
        )
        self.kernel32.CreatePipe.restype = wintypes.BOOL
        self.kernel32.SetHandleInformation.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self.kernel32.SetHandleInformation.restype = wintypes.BOOL
        self.kernel32.ReadFile.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        self.kernel32.ReadFile.restype = wintypes.BOOL
        self.kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel32.TerminateProcess.restype = wintypes.BOOL
        self.kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        self.kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self.kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
        )
        self.kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel32.TerminateJobObject.restype = wintypes.BOOL
        self.kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
        self.kernel32.ResumeThread.restype = wintypes.DWORD
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.user32.GetProcessWindowStation.argtypes = ()
        self.user32.GetProcessWindowStation.restype = wintypes.HANDLE
        self.user32.GetThreadDesktop.argtypes = (wintypes.DWORD,)
        self.user32.GetThreadDesktop.restype = wintypes.HANDLE

    def create_appcontainer_profile(self, profile_name: str) -> wintypes.LPVOID:
        sid = wintypes.LPVOID()
        hr = self.userenv.CreateAppContainerProfile(
            profile_name,
            profile_name,
            "OpenSquilla sandbox AppContainer",
            None,
            0,
            ctypes.byref(sid),
        )
        _raise_for_hresult("CreateAppContainerProfile", hr)
        return sid

    def derive_appcontainer_sid(self, profile_name: str) -> wintypes.LPVOID:
        sid = wintypes.LPVOID()
        hr = self.userenv.DeriveAppContainerSidFromAppContainerName(
            profile_name,
            ctypes.byref(sid),
        )
        _raise_for_hresult("DeriveAppContainerSidFromAppContainerName", hr)
        return sid

    def sid_to_string_and_free(self, sid: wintypes.LPVOID) -> str:
        try:
            return self.sid_to_string(sid)
        finally:
            self.free_sid(sid)

    def sid_to_string(self, sid: wintypes.LPVOID) -> str:
        sid_string = wintypes.LPWSTR()
        if not self.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise _last_error("ConvertSidToStringSidW")
        try:
            return sid_string.value
        finally:
            if sid_string:
                self.kernel32.LocalFree(sid_string)

    def free_sid(self, sid: wintypes.LPVOID) -> None:
        if sid:
            self.advapi32.FreeSid(sid)

    def grant_current_window_station_and_desktop(self, appcontainer_sid: str) -> None:
        window_station = self.user32.GetProcessWindowStation()
        if not window_station:
            raise _last_error("GetProcessWindowStation")
        desktop = self.user32.GetThreadDesktop(self.kernel32.GetCurrentThreadId())
        if not desktop:
            raise _last_error("GetThreadDesktop")
        self._grant_window_object_access(
            window_station,
            appcontainer_sid,
            _SANDBOXED_POWERSHELL_WINDOW_STATION_ACCESS,
        )
        self._grant_window_object_access(
            desktop,
            appcontainer_sid,
            _SANDBOXED_POWERSHELL_DESKTOP_ACCESS,
        )

    def _grant_window_object_access(
        self,
        handle: wintypes.HANDLE,
        appcontainer_sid: str,
        access_mask: int,
    ) -> None:
        sid = wintypes.LPVOID()
        security_descriptor = wintypes.LPVOID()
        old_dacl = wintypes.LPVOID()
        new_dacl = wintypes.LPVOID()
        if not self.advapi32.ConvertStringSidToSidW(appcontainer_sid, ctypes.byref(sid)):
            raise _last_error("ConvertStringSidToSidW")
        try:
            err = self.advapi32.GetSecurityInfo(
                handle,
                _SE_WINDOW_OBJECT,
                _DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(old_dacl),
                None,
                ctypes.byref(security_descriptor),
            )
            if err != _ERROR_SUCCESS:
                raise _Win32Error("GetSecurityInfo", err)
            entry = _ExplicitAccessW()
            entry.grfAccessPermissions = access_mask
            entry.grfAccessMode = _SET_ACCESS
            entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
            entry.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
            entry.Trustee.ptstrName = ctypes.cast(sid, wintypes.LPWSTR)
            err = self.advapi32.SetEntriesInAclW(
                1,
                ctypes.byref(entry),
                old_dacl,
                ctypes.byref(new_dacl),
            )
            if err != _ERROR_SUCCESS:
                raise _Win32Error("SetEntriesInAclW", err)
            err = self.advapi32.SetSecurityInfo(
                handle,
                _SE_WINDOW_OBJECT,
                _DACL_SECURITY_INFORMATION,
                None,
                None,
                new_dacl,
                None,
            )
            if err != _ERROR_SUCCESS:
                raise _Win32Error("SetSecurityInfo", err)
        finally:
            if new_dacl:
                self.kernel32.LocalFree(new_dacl)
            if security_descriptor:
                self.kernel32.LocalFree(security_descriptor)
            if sid:
                self.kernel32.LocalFree(sid)

    def grant_process_token_default_dacl(
        self,
        process: wintypes.HANDLE,
        appcontainer_sid: str,
    ) -> None:
        token = wintypes.HANDLE()
        sid = wintypes.LPVOID()
        new_dacl = wintypes.LPVOID()
        if not self.advapi32.OpenProcessToken(
            process,
            _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT,
            ctypes.byref(token),
        ):
            raise _last_error("OpenProcessToken")
        try:
            old_dacl, token_default_dacl_buffer = self._token_default_dacl(token)
            user_sid, token_user_buffer = self._token_user_sid(token)
            if not self.advapi32.ConvertStringSidToSidW(appcontainer_sid, ctypes.byref(sid)):
                raise _last_error("ConvertStringSidToSidW")

            entries = (_ExplicitAccessW * 2)()
            for entry, trustee_sid in zip(entries, (sid, user_sid), strict=True):
                entry.grfAccessPermissions = _GENERIC_ALL
                entry.grfAccessMode = _SET_ACCESS
                entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
                entry.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
                entry.Trustee.ptstrName = ctypes.cast(trustee_sid, wintypes.LPWSTR)
            err = self.advapi32.SetEntriesInAclW(
                len(entries),
                entries,
                old_dacl,
                ctypes.byref(new_dacl),
            )
            if err != _ERROR_SUCCESS:
                raise _Win32Error("SetEntriesInAclW", err)

            token_dacl = _TokenDefaultDacl(new_dacl)
            if not self.advapi32.SetTokenInformation(
                token,
                _TOKEN_DEFAULT_DACL_CLASS,
                ctypes.byref(token_dacl),
                ctypes.sizeof(token_dacl),
            ):
                raise _last_error("SetTokenInformation")
            _ = token_default_dacl_buffer
            _ = token_user_buffer
        finally:
            if new_dacl:
                self.kernel32.LocalFree(new_dacl)
            if sid:
                self.kernel32.LocalFree(sid)
            if token:
                self.close_handle(token)

    def _token_default_dacl(
        self,
        token: wintypes.HANDLE,
    ) -> tuple[wintypes.LPVOID, ctypes.Array[ctypes.c_char]]:
        size = wintypes.DWORD(0)
        if self.advapi32.GetTokenInformation(
            token,
            _TOKEN_DEFAULT_DACL_CLASS,
            None,
            0,
            ctypes.byref(size),
        ):
            raise _Win32Error("GetTokenInformation", 0)
        error = ctypes.get_last_error()
        if error != _ERROR_INSUFFICIENT_BUFFER:
            raise _Win32Error("GetTokenInformation", error)
        buffer = ctypes.create_string_buffer(size.value)
        if not self.advapi32.GetTokenInformation(
            token,
            _TOKEN_DEFAULT_DACL_CLASS,
            buffer,
            size,
            ctypes.byref(size),
        ):
            raise _last_error("GetTokenInformation")
        return (
            ctypes.cast(buffer, ctypes.POINTER(_TokenDefaultDacl)).contents.DefaultDacl,
            buffer,
        )

    def _token_user_sid(
        self,
        token: wintypes.HANDLE,
    ) -> tuple[wintypes.LPVOID, ctypes.Array[ctypes.c_char]]:
        size = wintypes.DWORD(0)
        if self.advapi32.GetTokenInformation(
            token,
            _TOKEN_USER_CLASS,
            None,
            0,
            ctypes.byref(size),
        ):
            raise _Win32Error("GetTokenInformation", 0)
        error = ctypes.get_last_error()
        if error != _ERROR_INSUFFICIENT_BUFFER:
            raise _Win32Error("GetTokenInformation", error)
        buffer = ctypes.create_string_buffer(size.value)
        if not self.advapi32.GetTokenInformation(
            token,
            _TOKEN_USER_CLASS,
            buffer,
            size,
            ctypes.byref(size),
        ):
            raise _last_error("GetTokenInformation")
        return (
            ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents.User.Sid,
            buffer,
        )

    def create_appcontainer_attribute_list(
        self,
        security_capabilities: _SecurityCapabilities,
        inherited_handles: tuple[wintypes.HANDLE, ...],
    ) -> _ProcThreadAttributeList:
        size = ctypes.c_size_t(0)
        attribute_count = 2
        if self.kernel32.InitializeProcThreadAttributeList(
            None,
            attribute_count,
            0,
            ctypes.byref(size),
        ):
            raise _Win32Error("InitializeProcThreadAttributeList", 0)
        error = ctypes.get_last_error()
        if error != _ERROR_INSUFFICIENT_BUFFER:
            raise _Win32Error("InitializeProcThreadAttributeList", error)
        attribute_list = ctypes.create_string_buffer(size.value)
        if not self.kernel32.InitializeProcThreadAttributeList(
            attribute_list,
            attribute_count,
            0,
            ctypes.byref(size),
        ):
            raise _last_error("InitializeProcThreadAttributeList")
        handle_array = (wintypes.HANDLE * len(inherited_handles))(*inherited_handles)
        if not self.kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(security_capabilities),
            ctypes.sizeof(security_capabilities),
            None,
            None,
        ):
            self.delete_proc_thread_attribute_list(attribute_list)
            raise _last_error("UpdateProcThreadAttribute")
        if not self.kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.byref(handle_array),
            ctypes.sizeof(handle_array),
            None,
            None,
        ):
            self.delete_proc_thread_attribute_list(attribute_list)
            raise _last_error("UpdateProcThreadAttribute")
        return _ProcThreadAttributeList(buffer=attribute_list, handle_array=handle_array)

    def delete_proc_thread_attribute_list(
        self,
        attribute_list: _ProcThreadAttributeList | ctypes.Array[ctypes.c_char],
    ) -> None:
        raw_attribute_list = getattr(attribute_list, "buffer", attribute_list)
        self.kernel32.DeleteProcThreadAttributeList(raw_attribute_list)

    def create_pipe(
        self,
        *,
        inherit_read: bool = False,
        inherit_write: bool = False,
    ) -> tuple[wintypes.HANDLE, wintypes.HANDLE]:
        security_attributes = _SecurityAttributes(
            nLength=ctypes.sizeof(_SecurityAttributes),
            lpSecurityDescriptor=None,
            bInheritHandle=True,
        )
        read_handle = wintypes.HANDLE()
        write_handle = wintypes.HANDLE()
        if not self.kernel32.CreatePipe(
            ctypes.byref(read_handle),
            ctypes.byref(write_handle),
            ctypes.byref(security_attributes),
            0,
        ):
            raise _last_error("CreatePipe")
        try:
            if not inherit_read:
                self._clear_inherit(read_handle)
            if not inherit_write:
                self._clear_inherit(write_handle)
        except Exception:
            self.close_handle(read_handle)
            self.close_handle(write_handle)
            raise
        return read_handle, write_handle

    def _clear_inherit(self, handle: wintypes.HANDLE) -> None:
        if not self.kernel32.SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, 0):
            raise _last_error("SetHandleInformation")

    def create_process(
        self,
        *,
        command_line: ctypes.Array[ctypes.c_wchar],
        cwd: str,
        environment_block: ctypes.Array[ctypes.c_wchar],
        creation_flags: int,
        startup_info: _STARTUPINFOEXW,
        process_info: _ProcessInformation,
    ) -> None:
        if not self.kernel32.CreateProcessW(
            None,
            command_line,
            None,
            None,
            True,
            creation_flags,
            environment_block,
            cwd,
            ctypes.byref(startup_info),
            ctypes.byref(process_info),
        ):
            raise _last_error("CreateProcessW")

    def create_kill_on_close_job(self) -> wintypes.HANDLE:
        job = self.kernel32.CreateJobObjectW(None, None)
        if not job:
            raise _last_error("CreateJobObjectW")
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.kernel32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise _last_error("SetInformationJobObject")
        except Exception:
            self.close_handle(job)
            raise
        return job

    def assign_process_to_job(
        self,
        job: wintypes.HANDLE,
        process: wintypes.HANDLE,
    ) -> None:
        if not self.kernel32.AssignProcessToJobObject(job, process):
            raise _last_error("AssignProcessToJobObject")

    def terminate_job(self, job: wintypes.HANDLE, returncode: int) -> None:
        if not self.kernel32.TerminateJobObject(job, returncode):
            raise _last_error("TerminateJobObject")

    def resume_thread(self, thread: wintypes.HANDLE) -> None:
        result = self.kernel32.ResumeThread(thread)
        if result == 0xFFFFFFFF:
            raise _last_error("ResumeThread")

    def read_file(self, handle: wintypes.HANDLE) -> bytes:
        buffer = ctypes.create_string_buffer(65536)
        bytes_read = wintypes.DWORD(0)
        if not self.kernel32.ReadFile(
            handle,
            buffer,
            len(buffer),
            ctypes.byref(bytes_read),
            None,
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_BROKEN_PIPE:
                return b""
            raise _Win32Error("ReadFile", error)
        if bytes_read.value == 0:
            return b""
        return buffer.raw[: bytes_read.value]

    def wait_for_single_object(
        self,
        handle: wintypes.HANDLE,
        timeout: float | None,
    ) -> int:
        milliseconds = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        return int(self.kernel32.WaitForSingleObject(handle, milliseconds))

    def terminate_process(self, handle: wintypes.HANDLE, returncode: int) -> None:
        if not self.kernel32.TerminateProcess(handle, returncode):
            raise _last_error("TerminateProcess")

    def get_exit_code_process(self, handle: wintypes.HANDLE) -> int:
        exit_code = wintypes.DWORD(0)
        if not self.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise _last_error("GetExitCodeProcess")
        return int(exit_code.value)

    def close_handle(self, handle: wintypes.HANDLE) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)


def _get_win32_api() -> _Win32Api:
    return _Win32Api()


def _raise_for_hresult(function: str, hr: int) -> None:
    code = int(hr) & 0xFFFFFFFF
    if code >= 0x80000000:
        raise _Win32Error(function, code)


def _last_error(function: str) -> _Win32Error:
    return _Win32Error(function, ctypes.get_last_error())


def appcontainer_smoke_check() -> bool:
    """Return whether native AppContainer setup has passed a real smoke check.

    The check proves the process boundary can be created on this host by
    launching a tiny command inside an AppContainer profile. Network readiness
    is checked separately by ``windows_wfp`` and is enforced only for networked
    policies.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        profile_name = appcontainer_profile_name("smoke")
        appcontainer_sid = ensure_appcontainer_profile(profile_name)
        with tempfile.TemporaryDirectory(prefix="opensquilla-appcontainer-smoke-") as raw:
            cwd = Path(raw)
            _grant_smoke_cwd(cwd, appcontainer_sid)
            cmd = _trusted_cmd_path()
            powershell = _trusted_powershell_path()
            result = _launch_appcontainer_process_native_sync(
                profile_name=profile_name,
                argv=(
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "Write-Output ok",
                ),
                cwd=cwd,
                env=_smoke_env(cmd),
                timeout=5.0,
            )
        return result.returncode == 0 and result.stdout.strip().lower() == b"ok"
    except Exception:
        return False


def _grant_smoke_cwd(cwd: Path, appcontainer_sid: str) -> None:
    from opensquilla.sandbox.backend.windows_acl import build_icacls_grant_argv

    argv = build_icacls_grant_argv(cwd, appcontainer_sid, mode="rw")
    completed = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise SandboxBackendError("AppContainer smoke ACL grant failed")


def _trusted_cmd_path() -> str:
    comspec = os.environ.get("COMSPEC", "")
    if _is_absolute_cmd_exe(comspec):
        return comspec
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    if system_root and "\x00" not in system_root and ntpath.isabs(system_root):
        return ntpath.join(system_root, "System32", "cmd.exe")
    return r"C:\Windows\System32\cmd.exe"


def _is_absolute_cmd_exe(path: str) -> bool:
    return "\x00" not in path and ntpath.isabs(path) and ntpath.basename(path).lower() == "cmd.exe"


def _trusted_powershell_path() -> str:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    if system_root and "\x00" not in system_root and ntpath.isabs(system_root):
        return ntpath.join(
            system_root,
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
    return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _smoke_env(cmd: str) -> dict[str, str]:
    env = _casefolded_env(
        os.environ,
        (
            "COMSPEC",
            "PATH",
            "SystemRoot",
            "SYSTEMROOT",
            "WINDIR",
            "USERPROFILE",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMW6432",
            "PSModulePath",
        ),
    )
    env["COMSPEC"] = cmd
    if "SystemRoot" not in env and "SYSTEMROOT" not in env:
        env["SystemRoot"] = r"C:\Windows"
    if "WINDIR" not in env:
        env["WINDIR"] = env.get("SystemRoot") or env.get("SYSTEMROOT", r"C:\Windows")
    return env


def _casefolded_env(source: Mapping[str, str], keys: Sequence[str]) -> dict[str, str]:
    wanted = {key.casefold() for key in keys}
    env: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in source.items():
        folded = key.casefold()
        if folded in wanted and folded not in seen and isinstance(value, str):
            env[key] = value
            seen.add(folded)
    return env


def restricted_token_smoke_check() -> bool:
    """Return whether native restricted-token setup passed a real smoke check.

    Task 1 only wires the typed readiness probe. Later Windows restricted-token
    setup tasks will replace this conservative placeholder with native API
    checks that prove the process boundary can actually be enforced.
    """
    return False


__all__ = [
    "AppContainerIdentity",
    "AppContainerLaunchResult",
    "appcontainer_profile_name",
    "appcontainer_smoke_check",
    "ensure_appcontainer_profile",
    "launch_appcontainer_process",
    "prepare_appcontainer_identity",
    "restricted_token_smoke_check",
]
