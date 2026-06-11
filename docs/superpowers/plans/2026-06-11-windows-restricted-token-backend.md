# Windows Restricted-Token Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the active Windows AppContainer sandbox path and make Windows `backend=auto` run commands through a working restricted-token backend.

**Architecture:** Keep the existing Python sandbox backend interface. Windows uses `WindowsRestrictedTokenBackend`, which launches a helper Python process; the helper creates a restricted token, applies required filesystem ACL grants, starts the requested argv in a kill-on-close job object, captures output, and fails closed for unsupported network policy. Linux bubblewrap, macOS seatbelt, noop, run-mode, and shared policy behavior remain unchanged except for Windows-specific selection and diagnostics.

**Tech Stack:** Python 3.12, `ctypes` Win32 APIs, pytest, existing OpenSquilla sandbox backend abstractions.

---

## File Structure

- Modify `src/opensquilla/sandbox/config.py`
  - Remove the `windows_appcontainer` backend literal.
  - Keep `windows_restricted_token`.

- Modify `src/opensquilla/sandbox/backend/__init__.py`
  - Remove `WindowsAppContainerBackend`.
  - Make Windows auto selection use only `WindowsRestrictedTokenBackend`.
  - Keep Linux/macOS/noop paths as they are.

- Modify `src/opensquilla/sandbox/backend/windows_support.py`
  - Remove AppContainer support fields and probes.
  - Make restricted-token availability independent of AppContainer WFP/broker readiness.

- Replace or heavily trim `src/opensquilla/sandbox/backend/windows_primitives.py`
  - Remove AppContainer profile/launch primitives.
  - Keep only Windows helpers needed by restricted-token smoke checks, or move them into `windows_restricted_token_helper.py`.

- Modify `src/opensquilla/sandbox/backend/windows_restricted_token.py`
  - Keep the adapter structure.
  - Keep environment allowlist filtering, adding only required Windows process environment defaults.

- Modify `src/opensquilla/sandbox/backend/windows_restricted_token_helper.py`
  - Replace fail-closed skeleton with real restricted-token process launch.
  - Add helper-internal functions for ACL grants, token creation, job creation, process launch, pipe capture, and timeout cleanup.
  - Continue to reject unsupported policy before launch.

- Modify `src/opensquilla/sandbox/integration.py`
  - Remove AppContainer platform network boundary usage.
  - Keep managed network proxy logic for existing non-Windows backends.

- Modify `src/opensquilla/tools/builtin/shell.py`
  - Stop adding Windows Python runtime mounts for `windows_restricted_token`.
  - Launch PowerShell directly for restricted-token Windows backend instead of routing through the Python shell host.
  - Preserve existing command translation helpers where they can run before launch.

- Modify `src/opensquilla/tools/builtin/code_exec.py`
  - Remove AppContainer-specific wording from Windows sandbox guidance.

- Delete AppContainer-only production modules:
  - `src/opensquilla/sandbox/backend/windows_appcontainer.py`
  - `src/opensquilla/sandbox/backend/windows_appcontainer_helper.py`
  - `src/opensquilla/sandbox/backend/windows_acl.py`
  - `src/opensquilla/sandbox/backend/windows_network_boundary.py`
  - `src/opensquilla/sandbox/backend/windows_wfp.py`
  - `src/opensquilla/sandbox/windows_service_broker.py`
  - `src/opensquilla/sandbox/windows_service_client.py`
  - `src/opensquilla/sandbox/windows_service_ipc.py`

- Modify tests:
  - `tests/test_sandbox/test_windows_auto_backend.py`
  - `tests/test_sandbox/test_windows_restricted_token_backend.py`
  - `tests/test_sandbox/test_windows_native_smoke.py`
  - Shell/code-exec tests that mention AppContainer wording or Python runtime mounts.

- Delete AppContainer-only tests:
  - `tests/test_sandbox/test_windows_acl.py`
  - `tests/test_sandbox/test_windows_appcontainer_backend.py`
  - `tests/test_sandbox/test_windows_appcontainer_identity.py`
  - `tests/test_sandbox/test_windows_network_boundary.py`
  - `tests/test_sandbox/test_windows_service_broker.py`
  - `tests/test_sandbox/test_windows_service_client.py`
  - `tests/test_sandbox/test_windows_wfp.py`

---

### Task 1: Backend Config And Selection

**Files:**
- Modify: `src/opensquilla/sandbox/config.py`
- Modify: `src/opensquilla/sandbox/backend/__init__.py`
- Test: `tests/test_sandbox/test_windows_auto_backend.py`
- Test: `tests/test_sandbox/test_windows_restricted_token_backend.py`

- [ ] **Step 1: Update the failing Windows auto-selection test**

Replace the first Windows auto test in `tests/test_sandbox/test_windows_auto_backend.py` with:

```python
def test_windows_auto_backend_selects_restricted_token_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend import WindowsRestrictedTokenBackend

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)

    runtime = configure_runtime(
        SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.settings.sandbox is True
    assert runtime.settings.security_grading is True
    assert runtime.effective.sandbox_enabled is True
    assert runtime.effective.grading_enabled is True
    assert runtime.backend.name == "windows_restricted_token"
```

Delete the test that asserts AppContainer is selected first. Keep the test that
asserts Windows auto resolves to unavailable when restricted token is
unavailable, rewritten so it only patches `WindowsRestrictedTokenBackend`.

- [ ] **Step 2: Add explicit AppContainer rejection test**

Add this test to `tests/test_sandbox/test_windows_restricted_token_backend.py`:

```python
def test_windows_appcontainer_backend_literal_is_rejected() -> None:
    with pytest.raises(Exception, match="windows_appcontainer"):
        SandboxSettings(sandbox=True, backend="windows_appcontainer")  # type: ignore[arg-type]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_sandbox/test_windows_auto_backend.py tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: failures because `windows_appcontainer` is still a valid literal,
`WindowsAppContainerBackend` is still imported, and auto selection still prefers
AppContainer.

- [ ] **Step 4: Remove AppContainer from config**

In `src/opensquilla/sandbox/config.py`, replace the backend literal with:

```python
BackendName = Literal[
    "auto",
    "bubblewrap",
    "seatbelt",
    "noop",
    "windows_restricted_token",
]
```

- [ ] **Step 5: Remove AppContainer from backend selection**

In `src/opensquilla/sandbox/backend/__init__.py`:

Remove:

```python
from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend
```

Change the Windows branch in `_auto_backend()` to:

```python
    if sys.platform.startswith("win"):
        restricted_token = WindowsRestrictedTokenBackend()
        if restricted_token.available():
            return restricted_token
```

Remove the explicit selection branch:

```python
    elif choice == "windows_appcontainer":
        backend = WindowsAppContainerBackend()
```

Remove `WindowsAppContainerBackend` from `__all__`.

- [ ] **Step 6: Update diagnostic text**

In `_auto_backend_failure_message()`, replace the diagnostics tuple with:

```python
    diagnostics = (
        "Windows sandbox setup diagnostics: "
        f"ctypes={'ready' if support.ctypes_available else 'missing'}, "
        f"Restricted Token={'ready' if support.restricted_token_enforced else 'not ready'}, "
        f"network boundary={'ready' if support.proxy_allowlist_enforced else 'not ready'}"
    )
```

- [ ] **Step 7: Run backend selection tests**

Run:

```bash
pytest tests/test_sandbox/test_windows_auto_backend.py tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: the selection tests pass except helper/probe tests that still depend
on old support fields.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/opensquilla/sandbox/config.py src/opensquilla/sandbox/backend/__init__.py tests/test_sandbox/test_windows_auto_backend.py tests/test_sandbox/test_windows_restricted_token_backend.py
git commit -m "refactor: select restricted-token sandbox on Windows"
```

---

### Task 2: Restricted-Token Support Probe

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_support.py`
- Modify: `tests/test_sandbox/test_windows_support.py`
- Modify: `tests/test_sandbox/test_windows_restricted_token_backend.py`

- [ ] **Step 1: Rewrite support probe tests**

In `tests/test_sandbox/test_windows_support.py`, replace AppContainer-oriented
tests with:

```python
def test_windows_support_probe_reports_restricted_token_unavailable_off_windows(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is False
    assert support.restricted_token_available is False
    assert support.proxy_allowlist_enforced is False


def test_windows_support_probe_accepts_restricted_token_with_real_checks(monkeypatch):
    from opensquilla.sandbox.backend import windows_support as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(mod, "_restricted_token_smoke_ok", lambda: True)
    monkeypatch.setattr(mod, "_proxy_allowlist_smoke_ok", lambda: False)

    support = mod.probe_windows_sandbox_support()

    assert support.is_windows is True
    assert support.ctypes_available is True
    assert support.restricted_token_enforced is True
    assert support.restricted_token_available is True
    assert support.proxy_allowlist_enforced is False
```

- [ ] **Step 2: Update restricted-token availability test**

In `tests/test_sandbox/test_windows_restricted_token_backend.py`, replace
`test_windows_restricted_token_available_requires_enforced_boundary` with:

```python
def test_windows_restricted_token_available_requires_enforced_process_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_support as support_mod
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(support_mod.sys, "platform", "win32")
    monkeypatch.setattr(support_mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(support_mod, "_restricted_token_smoke_ok", lambda: False)
    assert WindowsRestrictedTokenBackend().available() is False

    monkeypatch.setattr(support_mod, "_restricted_token_smoke_ok", lambda: True)
    assert WindowsRestrictedTokenBackend().available() is True
```

- [ ] **Step 3: Run support tests to verify failure**

Run:

```bash
pytest tests/test_sandbox/test_windows_support.py tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: failures from missing `_proxy_allowlist_smoke_ok` and removed
AppContainer fields.

- [ ] **Step 4: Simplify support dataclass**

Replace the dataclass body in `src/opensquilla/sandbox/backend/windows_support.py`
with:

```python
@dataclass(frozen=True)
class WindowsSandboxSupport:
    is_windows: bool
    ctypes_available: bool
    restricted_token_enforced: bool
    proxy_allowlist_enforced: bool = False

    @property
    def restricted_token_available(self) -> bool:
        return (
            self.is_windows
            and self.ctypes_available
            and self.restricted_token_enforced
        )
```

- [ ] **Step 5: Simplify `probe_windows_sandbox_support()`**

Replace the Windows branch with:

```python
    restricted_token_ok = _restricted_token_smoke_ok()
    proxy_ok = _proxy_allowlist_smoke_ok()

    return WindowsSandboxSupport(
        is_windows=True,
        ctypes_available=ctypes_ok,
        restricted_token_enforced=restricted_token_ok,
        proxy_allowlist_enforced=proxy_ok,
    )
```

Replace the non-Windows return with:

```python
        return WindowsSandboxSupport(
            is_windows=False,
            ctypes_available=ctypes_ok,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        )
```

- [ ] **Step 6: Remove AppContainer probe functions**

Delete `_appcontainer_smoke_ok()`, `_wfp_smoke_ok()`, and `_broker_smoke_ok()`.

Add:

```python
def _proxy_allowlist_smoke_ok() -> bool:
    return False
```

Keep `_restricted_token_smoke_ok()` but make it import from the restricted-token
helper or a restricted-only primitive:

```python
def _restricted_token_smoke_ok() -> bool:
    try:
        from opensquilla.sandbox.backend.windows_restricted_token_helper import (
            restricted_token_smoke_check,
        )

        return restricted_token_smoke_check()
    except Exception:
        return False
```

- [ ] **Step 7: Update `__all__`**

Make `__all__` exactly:

```python
__all__ = [
    "PROXY_ALLOWLIST_ENFORCED_ENV",
    "RESTRICTED_TOKEN_ENFORCED_ENV",
    "WindowsSandboxSupport",
    "probe_windows_sandbox_support",
]
```

- [ ] **Step 8: Run support tests**

Run:

```bash
pytest tests/test_sandbox/test_windows_support.py tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: support and availability tests pass.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/opensquilla/sandbox/backend/windows_support.py tests/test_sandbox/test_windows_support.py tests/test_sandbox/test_windows_restricted_token_backend.py
git commit -m "refactor: simplify Windows sandbox support probe"
```

---

### Task 3: Remove AppContainer Platform Network Boundary

**Files:**
- Modify: `src/opensquilla/sandbox/integration.py`
- Test: `tests/test_sandbox/test_managed_network_backends.py`
- Test: `tests/test_sandbox/test_network_guard.py`
- Test: `tests/test_sandbox/test_windows_restricted_token_backend.py`

- [ ] **Step 1: Add regression test that restricted token does not use AppContainer boundary**

Add this test to `tests/test_sandbox/test_windows_restricted_token_backend.py`:

```python
def test_restricted_token_backend_does_not_prepare_appcontainer_boundary(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.integration import _uses_platform_network_boundary

    backend = type("Backend", (), {"name": "windows_restricted_token"})()
    runtime = type("Runtime", (), {"backend": backend})()
    request = _request(tmp_path)

    assert _uses_platform_network_boundary(request, runtime) is False
```

- [ ] **Step 2: Run the regression test**

Run:

```bash
pytest tests/test_sandbox/test_windows_restricted_token_backend.py::test_restricted_token_backend_does_not_prepare_appcontainer_boundary -q
```

Expected: pass now or fail later if stale AppContainer logic still activates.

- [ ] **Step 3: Simplify platform boundary integration**

In `src/opensquilla/sandbox/integration.py`, replace
`_run_backend_with_platform_network_boundary()` with:

```python
async def _run_backend_with_platform_network_boundary(
    request: SandboxRequest,
    runtime: SandboxRuntime,
) -> SandboxResult:
    return await runtime.backend.run(request)
```

Replace `_uses_platform_network_boundary()` with:

```python
def _uses_platform_network_boundary(
    request: SandboxRequest,
    runtime: SandboxRuntime,
) -> bool:
    _ = (request, runtime)
    return False
```

Replace `_prepare_platform_network_boundary()` with:

```python
async def _prepare_platform_network_boundary(
    request: SandboxRequest,
    runtime: SandboxRuntime,
) -> object | None:
    _ = (request, runtime)
    return None
```

Keep `_cleanup_platform_network_boundary()` as a no-op-safe cleanup helper.

- [ ] **Step 4: Remove AppContainer import path**

Delete this import from `_prepare_platform_network_boundary()`:

```python
from opensquilla.sandbox.backend.windows_network_boundary import WindowsNetworkBoundary
```

- [ ] **Step 5: Run network integration tests**

Run:

```bash
pytest tests/test_sandbox/test_managed_network_backends.py tests/test_sandbox/test_network_guard.py tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: existing non-Windows managed proxy tests pass; restricted-token
boundary regression passes.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/opensquilla/sandbox/integration.py tests/test_sandbox/test_windows_restricted_token_backend.py
git commit -m "refactor: remove AppContainer network boundary path"
```

---

### Task 4: Direct Windows Shell Launch For Restricted Token

**Files:**
- Modify: `src/opensquilla/tools/builtin/shell.py`
- Modify: `src/opensquilla/tools/builtin/code_exec.py`
- Modify: shell tests currently living in `tests/test_sandbox/test_windows_appcontainer_backend.py` before that file is deleted
- Create: `tests/test_sandbox/test_windows_restricted_token_shell.py`

- [ ] **Step 1: Move non-AppContainer shell tests to a restricted-token test file**

Create `tests/test_sandbox/test_windows_restricted_token_shell.py` with tests
covering direct PowerShell argv:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def test_windows_restricted_token_backend_uses_direct_powershell_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.tools.builtin import shell

    backend = type("Backend", (), {"name": "windows_restricted_token"})()
    runtime = type("Runtime", (), {"backend": backend})()

    argv = shell._sandbox_shell_backend_argv(
        command="echo ok",
        runtime=runtime,
    )

    assert argv[0].lower().endswith("powershell.exe")
    assert "-Command" in argv
    assert "echo ok" in argv
    assert argv[0] != sys.executable
```

If `_sandbox_shell_backend_argv()` currently has a different signature, adapt
the test to call the existing helper with its real arguments.

- [ ] **Step 2: Run the new shell test to verify failure**

Run:

```bash
pytest tests/test_sandbox/test_windows_restricted_token_shell.py -q
```

Expected: failure because the current Windows backend path still returns
`sys.executable -c _WINDOWS_SANDBOX_SHELL_HOST_CODE ...`.

- [ ] **Step 3: Add backend predicate helpers**

In `src/opensquilla/tools/builtin/shell.py`, add:

```python
def _windows_restricted_token_backend_active(runtime: object | None = None) -> bool:
    runtime = get_runtime() if runtime is None else runtime
    backend = getattr(runtime, "backend", None) if runtime is not None else None
    backend_name = str(getattr(backend, "name", "") or "")
    return backend_name == "windows_restricted_token"
```

Keep `_windows_sandbox_backend_active()` for generic Windows behavior.

- [ ] **Step 4: Stop adding Python runtime mounts for restricted token**

At the top of `_policy_with_windows_shell_runtime_mounts()`, add:

```python
    if _windows_restricted_token_backend_active(runtime):
        return policy
```

- [ ] **Step 5: Return direct PowerShell argv for restricted token**

In `_sandbox_shell_backend_argv()`, before the Python shell-host branch, add:

```python
    if _windows_restricted_token_backend_active(runtime):
        return (
            trusted_powershell_path,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        )
```

Use the existing local variable or helper that resolves the trusted PowerShell
path. Do not introduce a second path-resolution policy.

- [ ] **Step 6: Update Windows code-exec guidance wording**

In `src/opensquilla/tools/builtin/code_exec.py`, replace:

```python
"use exec_command so the Windows shell path translation, AppContainer ACL "
"grants, and managed network approvals run before the process starts."
```

with:

```python
"use exec_command so the Windows shell path translation, sandbox filesystem "
"grants, and managed network approvals run before the process starts."
```

- [ ] **Step 7: Run shell/code-exec tests**

Run:

```bash
pytest tests/test_sandbox/test_windows_restricted_token_shell.py tests/test_sandbox/test_shell_code_network_hints.py -q
```

Expected: pass after adapting tests to the actual helper signatures.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/opensquilla/tools/builtin/shell.py src/opensquilla/tools/builtin/code_exec.py tests/test_sandbox/test_windows_restricted_token_shell.py
git commit -m "refactor: launch Windows restricted-token shell directly"
```

---

### Task 5: Implement Restricted-Token Helper

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_restricted_token_helper.py`
- Modify: `src/opensquilla/sandbox/backend/windows_restricted_token.py`
- Test: `tests/test_sandbox/test_windows_restricted_token_backend.py`

- [ ] **Step 1: Add helper tests for unsupported network policy**

Add to `tests/test_sandbox/test_windows_restricted_token_backend.py`:

```python
def test_helper_rejects_proxy_allowlist_before_launch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_restricted_token_helper as helper

    def forbidden_run(payload: object) -> int:
        raise AssertionError("proxy_allowlist must fail before launch")

    policy = _policy(tmp_path).summary()
    policy["network"] = "proxy_allowlist"
    policy["network_proxy"] = {"host": "127.0.0.1", "port": 48123}

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(helper, "_run_restricted", forbidden_run)

    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": policy,
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "proxy_allowlist" in captured.err
```

- [ ] **Step 2: Add helper test that `network=none` reaches the launch path**

Add:

```python
def test_helper_network_none_reaches_restricted_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_restricted_token_helper as helper

    launched: dict[str, object] = {}

    def fake_run(payload: object) -> int:
        launched["payload"] = payload
        return 0

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(helper, "_run_restricted", fake_run)

    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    assert exc_info.value.code == 0
    assert "payload" in launched
```

- [ ] **Step 3: Run helper tests to verify failure**

Run:

```bash
pytest tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: new tests fail because helper still raises `_UNENFORCEABLE`.

- [ ] **Step 4: Change `main()` to exit with the launch return code**

In `windows_restricted_token_helper.py`, change:

```python
        _run_restricted(payload)
```

to:

```python
        raise SystemExit(_run_restricted(payload))
```

- [ ] **Step 5: Replace policy validation**

Replace `_validate_policy_is_enforceable()` with:

```python
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
```

- [ ] **Step 6: Add Windows SID generation and ACL grant helpers**

Add these imports:

```python
import subprocess
import uuid
```

Add:

```python
def _session_restricting_sid() -> str:
    raw = uuid.uuid4().int
    a = raw & 0xFFFFFFFF
    b = (raw >> 32) & 0xFFFFFFFF
    c = (raw >> 64) & 0xFFFFFFFF
    d = (raw >> 96) & 0xFFFFFFFF
    return f"S-1-5-21-{a}-{b}-{c}-{d}"


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
        argv = [
            "icacls",
            str(path),
            "/grant",
            f"*{sid}:(OI)(CI){rights}" if path.is_dir() else f"*{sid}:{rights}",
            "/C",
        ]
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
```

- [ ] **Step 7: Implement restricted process launch skeleton**

Replace `_run_restricted()` with:

```python
def _run_restricted(payload: _HelperPayload) -> int:
    sid = _session_restricting_sid()
    _grant_policy_paths(payload, sid)
    return _run_restricted_process(payload, sid)
```

Add:

```python
def _run_restricted_process(payload: _HelperPayload, restricting_sid: str) -> int:
    if not sys.platform.startswith("win"):
        raise SystemExit("windows_restricted_token helper only runs on native Windows")
    return _run_restricted_process_native(payload, restricting_sid)
```

- [ ] **Step 8: Add native process implementation**

Implement `_run_restricted_process_native()` in the same file using `ctypes`.
The implementation must:

```python
def _run_restricted_process_native(payload: _HelperPayload, restricting_sid: str) -> int:
    import ctypes
    import subprocess as _subprocess
    import threading
    from ctypes import wintypes

    # 1. Open current process token.
    # 2. Convert restricting SID and Everyone SID.
    # 3. CreateRestrictedToken with DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED.
    # 4. Create stdout/stderr pipes with inheritable write handles.
    # 5. Create kill-on-close job object.
    # 6. CreateProcessAsUserW with CREATE_SUSPENDED and STARTF_USESTDHANDLES.
    # 7. AssignProcessToJobObject, ResumeThread, and read pipes in background threads.
    # 8. Wait for timeout; terminate job and return 124 on timeout.
    # 9. Return GetExitCodeProcess result.
```

Use `subprocess.list2cmdline(payload.argv)` for the command line. Use a helper
that builds the Windows environment block:

```python
def _environment_block(env: dict[str, str]) -> str:
    merged = dict(env)
    for key in ("SystemRoot", "WINDIR", "ComSpec"):
        value = os.environ.get(key)
        if value and key not in merged:
            merged[key] = value
    items = [f"{key}={value}" for key, value in sorted(merged.items(), key=lambda item: item[0].upper())]
    return "\0".join(items) + "\0\0"
```

If `CreateProcessAsUserW` fails due to privileges, call `CreateProcessWithTokenW`
with the same command line, cwd, environment block, and startup info. If both
fail, raise `SystemExit` with the Win32 error code in the message. Never fall
back to `subprocess.run(payload.argv)`.

- [ ] **Step 9: Add smoke check**

Add:

```python
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
    except Exception:
        return False
```

- [ ] **Step 10: Run unit tests**

Run:

```bash
pytest tests/test_sandbox/test_windows_restricted_token_backend.py tests/test_sandbox/test_windows_support.py -q
```

Expected: non-native tests pass. Native behavior is covered by opt-in smoke
tests in the next task.

- [ ] **Step 11: Commit**

Run:

```bash
git add src/opensquilla/sandbox/backend/windows_restricted_token.py src/opensquilla/sandbox/backend/windows_restricted_token_helper.py tests/test_sandbox/test_windows_restricted_token_backend.py
git commit -m "feat: run Windows commands with restricted token"
```

---

### Task 6: Native Windows Smoke Tests

**Files:**
- Modify: `tests/test_sandbox/test_windows_native_smoke.py`

- [ ] **Step 1: Replace AppContainer smoke marker**

In `tests/test_sandbox/test_windows_native_smoke.py`, replace the AppContainer
readiness helper with:

```python
def _native_restricted_token_ready() -> bool:
    if not _RUN_WINDOWS_NATIVE_SMOKE:
        return False
    try:
        from opensquilla.sandbox.backend.windows_restricted_token import (
            WindowsRestrictedTokenBackend,
        )

        return WindowsRestrictedTokenBackend().available()
    except Exception:
        return False


_native_restricted_token_smoke = pytest.mark.skipif(
    not (_RUN_WINDOWS_NATIVE_SMOKE and _native_restricted_token_ready()),
    reason=(
        "native Windows restricted-token smoke requires "
        "OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE=1 and restricted-token readiness"
    ),
)
```

- [ ] **Step 2: Add simple command smoke**

Add:

```python
@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_echo(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    request = SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": os.environ.get("PATH", "")},
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode == 0
    assert "ok" in result.stdout.lower()
```

- [ ] **Step 3: Add workspace write smoke**

Add:

```python
@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_can_write_workspace(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    target = tmp_path / "created.txt"
    request = SandboxRequest(
        argv=("cmd", "/c", f"echo ok>{target}"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": os.environ.get("PATH", "")},
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8").strip().lower() == "ok"
```

- [ ] **Step 4: Add outside-write smoke**

Add:

```python
@_native_restricted_token_smoke
@pytest.mark.asyncio
async def test_native_windows_restricted_token_blocks_write_outside_workspace(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.txt"
    request = SandboxRequest(
        argv=("cmd", "/c", f"echo bad>{outside}"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": os.environ.get("PATH", "")},
    )

    result = await WindowsRestrictedTokenBackend().run(request)

    assert result.returncode != 0 or not outside.exists()
```

- [ ] **Step 5: Run native smoke opt-in**

Run:

```bash
$env:OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE='1'; pytest tests/test_sandbox/test_windows_native_smoke.py -q
```

Expected on a Windows host with support: echo and workspace write pass; outside
write is denied or the command returns non-zero.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_sandbox/test_windows_native_smoke.py
git commit -m "test: add Windows restricted-token native smoke"
```

---

### Task 7: Delete AppContainer Production And Test Files

**Files:**
- Delete AppContainer production files listed in File Structure.
- Delete AppContainer tests listed in File Structure.
- Modify references found by `rg`.

- [ ] **Step 1: Search active AppContainer references**

Run:

```bash
rg -n "AppContainer|appcontainer|windows_appcontainer" src tests
```

Expected: many references before deletion.

- [ ] **Step 2: Delete AppContainer-only files**

Run:

```bash
git rm src/opensquilla/sandbox/backend/windows_appcontainer.py
git rm src/opensquilla/sandbox/backend/windows_appcontainer_helper.py
git rm src/opensquilla/sandbox/backend/windows_acl.py
git rm src/opensquilla/sandbox/backend/windows_network_boundary.py
git rm src/opensquilla/sandbox/backend/windows_wfp.py
git rm src/opensquilla/sandbox/windows_service_broker.py
git rm src/opensquilla/sandbox/windows_service_client.py
git rm src/opensquilla/sandbox/windows_service_ipc.py
git rm tests/test_sandbox/test_windows_acl.py
git rm tests/test_sandbox/test_windows_appcontainer_backend.py
git rm tests/test_sandbox/test_windows_appcontainer_identity.py
git rm tests/test_sandbox/test_windows_network_boundary.py
git rm tests/test_sandbox/test_windows_service_broker.py
git rm tests/test_sandbox/test_windows_service_client.py
git rm tests/test_sandbox/test_windows_wfp.py
```

- [ ] **Step 3: Remove stale references**

Run:

```bash
rg -n "AppContainer|appcontainer|windows_appcontainer" src tests
```

For remaining production references, either delete them or rewrite them to
restricted-token terminology. Do not remove historical references from the
design spec or plan files.

- [ ] **Step 4: Run sandbox tests**

Run:

```bash
pytest tests/test_sandbox -q
```

Expected: no import errors for deleted AppContainer modules; platform-neutral
tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add -A src tests
git commit -m "refactor: remove Windows AppContainer sandbox path"
```

---

### Task 8: Final Verification

**Files:**
- No new files unless tests reveal needed fixes.

- [ ] **Step 1: Run targeted sandbox tests**

Run:

```bash
pytest tests/test_sandbox/test_windows_auto_backend.py tests/test_sandbox/test_windows_restricted_token_backend.py tests/test_sandbox/test_windows_support.py tests/test_sandbox/test_windows_restricted_token_shell.py -q
```

Expected: pass.

- [ ] **Step 2: Run broader sandbox suite**

Run:

```bash
pytest tests/test_sandbox -q
```

Expected: pass or only native Windows smoke tests skipped unless explicitly
enabled.

- [ ] **Step 3: Run native smoke when on Windows**

Run:

```bash
$env:OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE='1'; pytest tests/test_sandbox/test_windows_native_smoke.py -q
```

Expected: restricted-token smoke passes on a supported Windows host.

- [ ] **Step 4: Search for AppContainer production references**

Run:

```bash
rg -n "AppContainer|appcontainer|windows_appcontainer" src tests
```

Expected: no active source/test references. Design and plan docs may still
mention AppContainer as historical context.

- [ ] **Step 5: Check working tree**

Run:

```bash
git status --short
```

Expected: clean except for unrelated user changes that existed before the
implementation.

- [ ] **Step 6: Final commit if any verification fixes were needed**

If verification required fixes, commit them:

```bash
git add -A src tests
git commit -m "fix: complete Windows restricted-token sandbox migration"
```

---

## Self-Review

Spec coverage:

- AppContainer removal is covered by Tasks 1, 3, and 7.
- Working restricted-token launch is covered by Tasks 5 and 6.
- Linux/macOS/noop preservation is covered by Tasks 1 and 8.
- Network fail-closed behavior is covered by Tasks 3 and 5.
- Shell runtime Python mount timeout is covered by Task 4.
- Tests and native smoke are covered by Tasks 1, 2, 4, 5, 6, 7, and 8.

Known implementation risk:

- The helper's native process code is the riskiest step. It must never fall
  back to `subprocess.run(payload.argv)` because that would launch outside the
  restricted token.
- ACL grants using `icacls /T` are acceptable for Phase 1, but persistent
  idempotent ACL setup belongs in Phase 2.
