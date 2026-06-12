# Windows Process Runtime Codex Legacy Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Windows foreground shell execution use a Codex-like legacy restricted-token backend that runs common `exec_command` commands reliably without host fallback.

**Architecture:** Keep the second-layer sandbox operation runtime intact and focus this plan on the Windows process backend. The shell tool will build a direct PowerShell `SandboxRequest`; `WindowsDefaultBackend` will prepare payload roots and stdin; `windows_default_runner` will refresh ACLs, create a better restricted token, wire stdio, launch the process, and return `SandboxResult`.

**Tech Stack:** Python 3.11+, `pytest`, Windows Win32 APIs through `ctypes`, existing OpenSquilla sandbox policy/types, existing `windows_default` backend modules.

---

## File Structure

Modify these existing files:

- `src/opensquilla/tools/builtin/shell.py`
  - Switch Windows foreground shell argv from Python shell host to direct PowerShell.
  - Keep old Python shell host code only as an unused compatibility path during this plan.
- `src/opensquilla/sandbox/backend/windows_default.py`
  - Add `stdinBase64` payload support.
  - Add process runtime RX roots to ACL planning.
  - Keep filesystem worker behavior unchanged.
- `src/opensquilla/sandbox/backend/windows_default_runner.py`
  - Parse `stdinBase64`.
  - Use improved token flags.
  - Set token default DACL.
  - Re-enable `SeChangeNotifyPrivilege`.
  - Pipe stdin to child process.
- `src/opensquilla/sandbox/backend/windows_default_roots.py`
  - Add Windows process runtime root helpers.

Create these test files or extend existing ones:

- `tests/test_sandbox/test_windows_shell_process_runtime.py`
  - Extend with direct PowerShell argv assertions.
- `tests/test_sandbox/test_windows_default_backend.py`
  - Extend with stdin payload and process RX root tests.
- `tests/test_sandbox/test_windows_default_runner.py`
  - Extend with stdin parsing, token flag, default DACL, privilege, and stdin pipe tests.
- `tests/test_sandbox/test_windows_default_process_smoke.py`
  - Add opt-in native smoke tests gated by `OPENSQUILLA_RUN_WINDOWS_SANDBOX_SMOKE=1`.

Do not modify:

- Linux `bubblewrap` behavior.
- macOS `seatbelt` behavior.
- `NoopBackend` host behavior.
- Elevated command-runner or WFP behavior.
- Background process session semantics.

---

### Task 1: Direct PowerShell argv for Windows foreground shell

**Files:**
- Modify: `src/opensquilla/tools/builtin/shell.py`
- Test: `tests/test_sandbox/test_windows_shell_process_runtime.py`

- [ ] **Step 1: Write the failing test**

Append this test to `tests/test_sandbox/test_windows_shell_process_runtime.py`:

```python
def test_windows_exec_command_uses_direct_powershell_argv(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()

    monkeypatch.setattr(
        shell,
        "_trusted_windows_powershell_path",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    argv = shell._sandbox_shell_backend_argv("Write-Output ok", runtime, cwd=tmp_path)

    assert argv[0] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert "-NoLogo" in argv
    assert "-NoProfile" in argv
    assert "-NonInteractive" in argv
    assert "-ExecutionPolicy" in argv
    assert "Bypass" in argv
    assert "-Command" in argv
    assert "Write-Output ok" in argv
    assert "-c" not in argv[:3]
    assert "python" not in argv[0].lower()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_shell_process_runtime.py::test_windows_exec_command_uses_direct_powershell_argv -q
```

Expected: FAIL because `_sandbox_shell_backend_argv` still returns `sys.executable, "-c", _WINDOWS_SANDBOX_SHELL_HOST_CODE, ...`.

- [ ] **Step 3: Implement direct PowerShell argv**

In `src/opensquilla/tools/builtin/shell.py`, add this helper near `_trusted_windows_powershell_path`:

```python
def _windows_direct_powershell_argv(command: str) -> tuple[str, ...]:
    return (
        _trusted_windows_powershell_path(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    )
```

Then replace the Windows branch of `_sandbox_shell_backend_argv` with:

```python
    if backend_name.startswith("windows_"):
        return _windows_direct_powershell_argv(
            _windows_powershell_compat_command(command)
        )
```

Leave `_WINDOWS_SANDBOX_SHELL_HOST_CODE` in the file for this task. It will no longer be used by the default Windows foreground shell path.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_shell_process_runtime.py::test_windows_exec_command_uses_direct_powershell_argv -q
```

Expected: PASS.

- [ ] **Step 5: Run the existing shell process runtime tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_shell_process_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/opensquilla/tools/builtin/shell.py tests/test_sandbox/test_windows_shell_process_runtime.py
git commit -m "Use direct PowerShell argv for Windows sandbox exec"
```

---

### Task 2: Add stdin payload support to the Windows backend

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_default.py`
- Modify: `src/opensquilla/sandbox/backend/windows_default_runner.py`
- Test: `tests/test_sandbox/test_windows_default_backend.py`
- Test: `tests/test_sandbox/test_windows_default_runner.py`

- [ ] **Step 1: Write backend payload test**

Append this test to `tests/test_sandbox/test_windows_default_backend.py`:

```python
def test_payload_encodes_stdin_as_base64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    request = _request(tmp_path)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        stdin=b"hello from stdin\r\n",
        env=request.env,
        run_mode=request.run_mode,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    assert payload["stdinBase64"] == "aGVsbG8gZnJvbSBzdGRpbg0K"
```

- [ ] **Step 2: Write runner parse test**

Append this test to `tests/test_sandbox/test_windows_default_runner.py`:

```python
def test_parse_payload_decodes_stdin_base64(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import _parse_payload

    payload = {
        "backend": "windows_default",
        "argv": ["cmd", "/c", "more"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {"network": "none", "mounts": [], "windowsAclPlan": {"autoGrants": [], "capabilitySids": []}},
        "runMode": "trusted",
        "timeout": 5,
        "stdinBase64": "YWJjMTIz",
    }

    parsed = _parse_payload([json.dumps(payload)])

    assert parsed.stdin == b"abc123"
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_backend.py::test_payload_encodes_stdin_as_base64 tests/test_sandbox/test_windows_default_runner.py::test_parse_payload_decodes_stdin_base64 -q
```

Expected: FAIL because the payload has no `stdinBase64` key and `HelperPayload` has no `stdin` field.

- [ ] **Step 4: Implement payload encoding**

In `src/opensquilla/sandbox/backend/windows_default.py`, add the import:

```python
import base64
```

Then update `_payload_for_request` so the returned dict includes `stdinBase64`:

```python
    stdin_b64 = (
        base64.b64encode(request.stdin).decode("ascii")
        if request.stdin is not None
        else None
    )
    return {
        "backend": "windows_default",
        "argv": list(request.argv),
        "cwd": str(request.cwd),
        "env": env,
        "policy": policy,
        "runMode": request.run_mode,
        "timeout": request.policy.limits.wall_timeout_s,
        "stdinBase64": stdin_b64,
    }
```

- [ ] **Step 5: Implement payload decoding**

In `src/opensquilla/sandbox/backend/windows_default_runner.py`, add the import:

```python
import base64
```

Add `stdin` to `HelperPayload`:

```python
@dataclass(frozen=True)
class HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    run_mode: str
    timeout: float
    stdin: bytes | None = None
```

In `_parse_payload`, decode `stdinBase64` before returning:

```python
    stdin_raw = raw.get("stdinBase64")
    if stdin_raw is None:
        stdin = None
    elif isinstance(stdin_raw, str):
        try:
            stdin = base64.b64decode(stdin_raw.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise SystemExit("invalid windows_default payload: stdinBase64 is invalid") from exc
    else:
        raise SystemExit("invalid windows_default payload: stdinBase64 must be a string or null")
```

Then pass `stdin=stdin` into `HelperPayload(...)`.

- [ ] **Step 6: Run tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_backend.py::test_payload_encodes_stdin_as_base64 tests/test_sandbox/test_windows_default_runner.py::test_parse_payload_decodes_stdin_base64 -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/opensquilla/sandbox/backend/windows_default.py src/opensquilla/sandbox/backend/windows_default_runner.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py
git commit -m "Pass stdin through Windows sandbox payload"
```

---

### Task 3: Add process runtime RX root planning

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_default_roots.py`
- Modify: `src/opensquilla/sandbox/backend/windows_default.py`
- Test: `tests/test_sandbox/test_windows_default_backend.py`

- [ ] **Step 1: Write root helper tests**

Append this test to `tests/test_sandbox/test_windows_default_backend.py`:

```python
def test_payload_grants_platform_and_executable_roots_rx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.backend import windows_default_roots as roots

    windows_root = tmp_path / "Windows"
    system32 = windows_root / "System32"
    powershell_root = system32 / "WindowsPowerShell" / "v1.0"
    program_files = tmp_path / "Program Files"
    program_files_x86 = tmp_path / "Program Files (x86)"
    program_data = tmp_path / "ProgramData"
    for path in (powershell_root, program_files, program_files_x86, program_data):
        path.mkdir(parents=True)
    powershell = powershell_root / "powershell.exe"
    powershell.write_text("", encoding="utf-8")

    request = _request(tmp_path)
    request = SandboxRequest(
        argv=(str(powershell), "-NoLogo", "-Command", "Write-Output ok"),
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={"SystemRoot": str(windows_root), "ProgramData": str(program_data)},
        run_mode=request.run_mode,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(
        roots,
        "_program_files_roots_from_env",
        lambda env: (program_files, program_files_x86),
    )

    payload = mod._payload_for_request(request)

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert grants[str(system32)] == "RX"
    assert grants[str(powershell_root)] == "RX"
    assert grants[str(program_files)] == "RX"
    assert grants[str(program_files_x86)] == "RX"
    assert grants[str(program_data)] == "RX"
    assert grants[str(tmp_path)] == "RWX"
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_backend.py::test_payload_grants_platform_and_executable_roots_rx -q
```

Expected: FAIL because platform default roots are not yet added.

- [ ] **Step 3: Implement root helpers**

In `src/opensquilla/sandbox/backend/windows_default_roots.py`, add:

```python
from collections.abc import Mapping, Sequence
```

Then add these functions near `runtime_rx_roots`:

```python
def windows_system_root(env: Mapping[str, str] | None = None) -> Path:
    source = env or {}
    raw = source.get("SystemRoot") or source.get("SYSTEMROOT") or "C:\\Windows"
    return Path(raw)


def windows_program_data_root(env: Mapping[str, str] | None = None) -> Path:
    source = env or {}
    return Path(source.get("ProgramData") or "C:\\ProgramData")


def _program_files_roots_from_env(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    source = env or {}
    roots = [
        Path(source.get("ProgramFiles") or "C:\\Program Files"),
        Path(source.get("ProgramFiles(x86)") or "C:\\Program Files (x86)"),
    ]
    return tuple(dict.fromkeys(root for root in roots if str(root)))


def windows_platform_rx_roots(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    system_root = windows_system_root(env)
    roots = [
        system_root,
        system_root / "System32",
        windows_program_data_root(env),
        *_program_files_roots_from_env(env),
    ]
    return tuple(dict.fromkeys(root for root in roots if str(root)))


def process_executable_rx_roots(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    if not argv:
        return ()
    executable = Path(argv[0])
    roots: list[Path] = []
    if executable.is_absolute():
        roots.append(executable.parent)
        roots.append(executable.parent.parent)
    roots.extend(windows_platform_rx_roots(env))
    return tuple(dict.fromkeys(root for root in roots if str(root)))
```

Add the new public names to `__all__`.

- [ ] **Step 4: Wire process roots into ACL planning**

In `src/opensquilla/sandbox/backend/windows_default.py`, import the helper:

```python
    process_executable_rx_roots,
```

In `_acl_plan_payload`, extend `required` after `runtime_rx_roots(_python_executable())`:

```python
        *(
            AclGrant(root, AclAccess.RX, AclGrantKind.REQUIRED)
            for root in process_executable_rx_roots(request.argv, request.env)
            if root.exists()
        ),
```

Keep the `root.exists()` guard so tests can inject only roots they create and production avoids trying to grant missing optional roots.

- [ ] **Step 5: Run the root test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_backend.py::test_payload_grants_platform_and_executable_roots_rx -q
```

Expected: PASS.

- [ ] **Step 6: Run backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_backend.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/opensquilla/sandbox/backend/windows_default.py src/opensquilla/sandbox/backend/windows_default_roots.py tests/test_sandbox/test_windows_default_backend.py
git commit -m "Plan Windows process runtime RX roots"
```

---

### Task 4: Add Codex-like restricted-token flags and token default DACL

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_default_runner.py`
- Test: `tests/test_sandbox/test_windows_default_runner.py`

- [ ] **Step 1: Write token flag and hook tests**

Append these tests to `tests/test_sandbox/test_windows_default_runner.py`:

```python
def test_restricted_token_flags_match_codex_legacy() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    assert mod.RESTRICTED_TOKEN_FLAGS == (
        mod.DISABLE_MAX_PRIVILEGE | mod.LUA_TOKEN | mod.WRITE_RESTRICTED
    )


def test_token_post_create_hooks_are_called(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []

    monkeypatch.setattr(
        mod,
        "_set_token_default_dacl",
        lambda token, sids: calls.append(("default_dacl", token, tuple(sids))),
    )
    monkeypatch.setattr(
        mod,
        "_enable_token_privilege",
        lambda token, name: calls.append(("privilege", token, name)),
    )

    mod._finalize_restricted_token(
        token=123,
        dacl_sids=("logon", "everyone", "cap-a"),
    )

    assert calls == [
        ("default_dacl", 123, ("logon", "everyone", "cap-a")),
        ("privilege", 123, "SeChangeNotifyPrivilege"),
    ]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_runner.py::test_restricted_token_flags_match_codex_legacy tests/test_sandbox/test_windows_default_runner.py::test_token_post_create_hooks_are_called -q
```

Expected: FAIL because constants and `_finalize_restricted_token` do not exist.

- [ ] **Step 3: Add constants and finalize hook**

In `src/opensquilla/sandbox/backend/windows_default_runner.py`, add module-level constants near the imports:

```python
DISABLE_MAX_PRIVILEGE = 0x01
LUA_TOKEN = 0x04
WRITE_RESTRICTED = 0x08
RESTRICTED_TOKEN_FLAGS = DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED
GENERIC_ALL = 0x10000000
```

Add these functions above `_run_restricted_process_native_impl`:

```python
def _finalize_restricted_token(token: int, dacl_sids: Sequence[object]) -> None:
    _set_token_default_dacl(token, dacl_sids)
    _enable_token_privilege(token, "SeChangeNotifyPrivilege")


def _set_token_default_dacl(token: int, dacl_sids: Sequence[object]) -> None:
    if not dacl_sids:
        return
    _set_token_default_dacl_native(token, dacl_sids)


def _enable_token_privilege(token: int, name: str) -> None:
    _enable_token_privilege_native(token, name)
```

Add native stubs that raise clear errors on non-Windows hosts:

```python
def _set_token_default_dacl_native(token: int, dacl_sids: Sequence[object]) -> None:
    if not sys.platform.startswith("win"):
        raise OSError("SetTokenInformation(TokenDefaultDacl) requires Windows")
    # Native implementation is added in the next step of this task.


def _enable_token_privilege_native(token: int, name: str) -> None:
    if not sys.platform.startswith("win"):
        raise OSError(f"AdjustTokenPrivileges({name}) requires Windows")
    # Native implementation is added in the next step of this task.
```

- [ ] **Step 4: Replace stub bodies with native implementations**

Replace `_set_token_default_dacl_native` with:

```python
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
                f"SetTokenInformation(TokenDefaultDacl) failed: {ctypes.FormatError(error_code)}",
            )
    finally:
        if new_dacl:
            kernel32.LocalFree(new_dacl)
```

Replace `_enable_token_privilege_native` with:

```python
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
        raise OSError(error_code, f"LookupPrivilegeValueW({name}) failed: {ctypes.FormatError(error_code)}")
    privileges = TOKEN_PRIVILEGES()
    privileges.PrivilegeCount = 1
    privileges.Privileges[0].Luid = luid
    privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    if not advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None):
        error_code = ctypes.get_last_error()
        raise OSError(error_code, f"AdjustTokenPrivileges({name}) failed: {ctypes.FormatError(error_code)}")
```

- [ ] **Step 5: Wire constants and finalize hook into token creation**

Inside `_run_restricted_process_native_impl`, remove the local `DISABLE_MAX_PRIVILEGE = 0x01` constant. Change `CreateRestrictedToken(..., DISABLE_MAX_PRIVILEGE, ...)` to:

```python
            RESTRICTED_TOKEN_FLAGS,
```

After successful `CreateRestrictedToken`, add:

```python
        dacl_sids = []
        if logon_sid:
            dacl_sids.append(logon_sid)
        dacl_sids.extend(restricting_sids)
        _finalize_restricted_token(restricted_token, dacl_sids)
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_runner.py::test_restricted_token_flags_match_codex_legacy tests/test_sandbox/test_windows_default_runner.py::test_token_post_create_hooks_are_called -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/opensquilla/sandbox/backend/windows_default_runner.py tests/test_sandbox/test_windows_default_runner.py
git commit -m "Align Windows restricted token flags with Codex legacy"
```

---

### Task 5: Wire stdin to the child process

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_default_runner.py`
- Test: `tests/test_sandbox/test_windows_default_runner.py`

- [ ] **Step 1: Write stdin pipe unit test**

Append this test to `tests/test_sandbox/test_windows_default_runner.py`:

```python
def test_child_stdin_writer_writes_payload_and_closes(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []

    class FakeKernel32:
        def WriteFile(self, handle, data, size, written_ptr, overlapped):
            calls.append(("write", handle, bytes(data[:size])))
            written_ptr._obj.value = size
            return 1

        def CloseHandle(self, handle):
            calls.append(("close", handle))
            return 1

    mod._write_child_stdin(FakeKernel32(), 42, b"abc")

    assert calls == [("write", 42, b"abc"), ("close", 42)]
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_runner.py::test_child_stdin_writer_writes_payload_and_closes -q
```

Expected: FAIL because `_write_child_stdin` does not exist.

- [ ] **Step 3: Implement stdin writer helper**

In `src/opensquilla/sandbox/backend/windows_default_runner.py`, add this helper above `_run_restricted_process_native_impl`:

```python
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
```

- [ ] **Step 4: Create stdin pipe in native launcher**

Inside `_run_restricted_process_native_impl`, add `stdin_read = HANDLE()` and `stdin_write = HANDLE()` near the stdout/stderr handles.

Before creating stdout and stderr pipes, create the stdin pipe:

```python
        if not kernel32.CreatePipe(
            ctypes.byref(stdin_read),
            ctypes.byref(stdin_write),
            ctypes.byref(sa),
            0,
        ):
            raise win_error("CreatePipe(stdin)")
        kernel32.SetHandleInformation(stdin_write, HANDLE_FLAG_INHERIT, 0)
```

Change:

```python
        startup.hStdInput = 0
```

to:

```python
        startup.hStdInput = stdin_read
```

After process creation succeeds, close `stdin_read` in the parent and write stdin:

```python
        close(stdin_read)
        stdin_read = HANDLE()
        _write_child_stdin(kernel32, stdin_write, payload.stdin)
        stdin_write = HANDLE()
```

In the `finally` cleanup block, include both stdin handles:

```python
        close(stdin_read)
        close(stdin_write)
```

- [ ] **Step 5: Run stdin writer test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_runner.py::test_child_stdin_writer_writes_payload_and_closes -q
```

Expected: PASS.

- [ ] **Step 6: Run runner tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_runner.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/opensquilla/sandbox/backend/windows_default_runner.py tests/test_sandbox/test_windows_default_runner.py
git commit -m "Wire stdin into Windows sandboxed processes"
```

---

### Task 6: Add opt-in native Windows process smoke tests

**Files:**
- Create: `tests/test_sandbox/test_windows_default_process_smoke.py`

- [ ] **Step 1: Create the smoke test file**

Create `tests/test_sandbox/test_windows_default_process_smoke.py` with:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "win32"
    or os.environ.get("OPENSQUILLA_RUN_WINDOWS_SANDBOX_SMOKE") != "1",
    reason="Windows sandbox native smoke tests require explicit opt-in",
)


def _policy() -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=10),
        env_allowlist=(
            "PATH",
            "SystemRoot",
            "WINDIR",
            "ComSpec",
            "TEMP",
            "TMP",
            "ProgramData",
            "ProgramFiles",
            "ProgramFiles(x86)",
        ),
        require_approval=False,
    )


def _request(tmp_path: Path, argv: tuple[str, ...], stdin: bytes | None = None) -> SandboxRequest:
    return SandboxRequest(
        argv=argv,
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(),
        stdin=stdin,
        env=dict(os.environ),
        run_mode=RunMode.TRUSTED.value,
    )


@pytest.mark.asyncio
async def test_windows_default_runs_powershell_write_output(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = await WindowsDefaultBackend().run(
        _request(
            tmp_path,
            (
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Write-Output ok",
            ),
        )
    )

    assert result.returncode == 0
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_windows_default_runs_cmd_echo(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    cmd = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    result = await WindowsDefaultBackend().run(
        _request(tmp_path, (str(cmd), "/c", "echo ok"))
    )

    assert result.returncode == 0
    assert "ok" in result.stdout.lower()


@pytest.mark.asyncio
async def test_windows_default_passes_stdin(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = await WindowsDefaultBackend().run(
        _request(
            tmp_path,
            (
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$input | ForEach-Object { Write-Output $_ }",
            ),
            stdin=b"stdin-ok\r\n",
        )
    )

    assert result.returncode == 0
    assert "stdin-ok" in result.stdout
```

- [ ] **Step 2: Run smoke tests without opt-in**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_process_smoke.py -q
```

Expected: all tests SKIPPED unless `OPENSQUILLA_RUN_WINDOWS_SANDBOX_SMOKE=1` is set.

- [ ] **Step 3: Run smoke tests with opt-in on Windows**

Run:

```powershell
$env:OPENSQUILLA_RUN_WINDOWS_SANDBOX_SMOKE="1"; .\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_default_process_smoke.py -q
```

Expected on a configured Windows sandbox host: PASS. If setup is not complete, FAIL with a clear `windows_default backend unavailable` or Win32 API error.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_sandbox/test_windows_default_process_smoke.py
git commit -m "Add Windows sandbox process smoke tests"
```

---

### Task 7: Run integration regression tests and fix direct fallout

**Files:**
- Modify only files touched by Tasks 1-6 if failures are caused by this plan.

- [ ] **Step 1: Run focused sandbox tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_shell_process_runtime.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py tests/test_sandbox/test_operation_runtime.py -q
```

Expected: PASS.

- [ ] **Step 2: Run shell execution regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_trusted_sandbox_execution.py tests/test_sandbox/test_shell_code_network_hints.py tests/test_tools/test_shell_process_isolation.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```powershell
.\.venv\Scripts\ruff.exe check src/opensquilla/tools/builtin/shell.py src/opensquilla/sandbox/backend/windows_default.py src/opensquilla/sandbox/backend/windows_default_runner.py src/opensquilla/sandbox/backend/windows_default_roots.py tests/test_sandbox/test_windows_shell_process_runtime.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py tests/test_sandbox/test_windows_default_process_smoke.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Commit regression fixes**

If files changed during this task, commit only those files:

```powershell
git add src/opensquilla/tools/builtin/shell.py src/opensquilla/sandbox/backend/windows_default.py src/opensquilla/sandbox/backend/windows_default_runner.py src/opensquilla/sandbox/backend/windows_default_roots.py tests/test_sandbox/test_windows_shell_process_runtime.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py tests/test_sandbox/test_windows_default_process_smoke.py
git commit -m "Stabilize Windows process runtime regressions"
```

If no files changed, do not create an empty commit.

---

### Task 8: Manual OpenSquilla smoke checklist

**Files:**
- Modify: `d:\lrk\opensquilla-smoke-test.md`

- [ ] **Step 1: Append the smoke checklist**

Append this section to `d:\lrk\opensquilla-smoke-test.md`:

```markdown
## Windows Process Runtime Legacy Parity Smoke

Run these in Trusted-Sandbox and Standard-Sandbox after starting OpenSquilla:

1. `Write-Output ok`
   - Expected: exit code 0 and output contains `ok`.
2. `cmd /c echo ok`
   - Expected: exit code 0 and output contains `ok`.
3. `where powershell`
   - Expected: normal command output or normal command-not-found behavior, not `Access is denied`.
4. Create a file under `C:\Users\92862\.opensquilla\workspace`.
   - Expected: succeeds.
5. Try to write under `D:\opensquilla\.venv\Scripts`.
   - Expected: denied by Windows ACL or backend policy.
6. Try to write under `C:\ProgramData` without approval.
   - Expected: denied.
7. Run a command that reads from stdin.
   - Expected: stdin text reaches the child process.
```

- [ ] **Step 2: Do not commit the external smoke file**

`d:\lrk\opensquilla-smoke-test.md` is outside the repository workspace. Leave it uncommitted.

---

## Self-Review Notes

Spec coverage:

- Direct PowerShell launch is covered by Task 1.
- Stdin payload and runner consumption are covered by Tasks 2 and 5.
- Runtime RX roots and workspace write roots are covered by Task 3.
- Codex-like token flags, default DACL, and `SeChangeNotifyPrivilege` are covered by Task 4.
- Foreground process smoke coverage is covered by Task 6.
- Regression coverage for old shell path logic is preserved in Task 7.
- Background process, elevated runner, ConPTY, WFP, and sandbox users are intentionally outside this implementation plan.

Verification commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_windows_shell_process_runtime.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py tests/test_sandbox/test_operation_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox/test_trusted_sandbox_execution.py tests/test_sandbox/test_shell_code_network_hints.py tests/test_tools/test_shell_process_isolation.py -q
.\.venv\Scripts\ruff.exe check src/opensquilla/tools/builtin/shell.py src/opensquilla/sandbox/backend/windows_default.py src/opensquilla/sandbox/backend/windows_default_runner.py src/opensquilla/sandbox/backend/windows_default_roots.py tests/test_sandbox/test_windows_shell_process_runtime.py tests/test_sandbox/test_windows_default_backend.py tests/test_sandbox/test_windows_default_runner.py tests/test_sandbox/test_windows_default_process_smoke.py
```
