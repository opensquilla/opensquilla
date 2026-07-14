# Codex-Exact Cross-Platform Filesystem Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every sandboxed OpenSquilla filesystem tool and shell command consume one Codex-aligned filesystem permission profile on Linux, macOS, and Windows, with broad reads, scoped writes, exact one-shot elevation, and resilient directory listings.

**Architecture:** The policy layer resolves Codex's logical root-read rule into a concrete platform view before execution. `SandboxOperation` carries that immutable resolved profile into a shared filesystem-worker policy builder; Bubblewrap, Seatbelt, and Windows ACL code compile the same profile instead of deriving target-specific grants. Elevation remains outside the backend and consumes exact one-shot Guardian approvals only after an out-of-root write is classified.

**Tech Stack:** Python 3.12, `pathlib`, `asyncio`, Linux `bubblewrap`, macOS Seatbelt/SBPL, native Windows restricted tokens and ACLs, `pytest`, `pytest-asyncio`, Ruff, MyPy.

---

## Sequencing and File Structure

This is one integrated plan because the three backend tasks depend on the same
resolved profile and filesystem-operation transport boundary. Execute tasks in
order. Do not start a platform backend task until Tasks 1 and 2 pass.

Create these files:

- `src/opensquilla/sandbox/platform_permissions.py`
  - Resolve Codex's logical filesystem root into POSIX `/` or the exact Windows
    system/profile/cwd projection.
- `src/opensquilla/sandbox/backend/filesystem_worker_policy.py`
  - Build a worker policy from the operation's resolved profile plus private
    helper transport mounts.
- `tests/test_sandbox/test_platform_permissions.py`
  - Cross-platform logical-root and Windows projection contract tests.
- `tests/test_sandbox/test_filesystem_worker_policy.py`
  - Operation-profile propagation and transport-grant tests.
- `tests/test_sandbox/test_filesystem_worker.py`
  - Filesystem worker result and directory-entry resilience tests.
- `tests/test_sandbox/test_filesystem_profile_integration.py`
  - Native backend smoke tests, including the Linux `/etc`, `/home`, and `/var`
    regression.

Modify these files:

- `src/opensquilla/sandbox/permissions.py`
  - Support platform-resolved paths, a default access value for unrestricted
    profiles, and helpers used by all backend compilers.
- `src/opensquilla/sandbox/policy.py`
  - Resolve Codex root semantics once while constructing `SandboxPolicy`.
- `src/opensquilla/sandbox/operation_runtime.py`
  - Carry the resolved profile on filesystem operations.
- `src/opensquilla/tools/builtin/filesystem.py`
  - Attach the active profile before delegating to a backend; retain exact
    elevation classification.
- `src/opensquilla/sandbox/backend/bubblewrap.py`
  - Remove target-derived filesystem policies and use the shared worker policy.
- `src/opensquilla/sandbox/backend/linux_permissions.py`
  - Compile root read, writable overlays, read-only carve-outs, and denies from
    the resolved profile.
- `src/opensquilla/sandbox/backend/seatbelt.py`
  - Compile full/scoped reads and writes with explicit exclusions from the
    resolved profile.
- `src/opensquilla/sandbox/backend/windows_default.py`
  - Project profile entries into required RX/RWX grants plus deny-read and
    deny-write paths.
- `src/opensquilla/sandbox/backend/windows_default_acl.py`
  - Distinguish policy grants from legacy expansion-root sensitivity checks.
- `src/opensquilla/sandbox/backend/windows_default_roots.py`
  - Reuse the shared Codex Windows root constants and profile exclusions.
- `src/opensquilla/sandbox/backend/windows_default_runner.py`
  - Validate and enforce deny-read ACL entries as well as deny-write entries.
- `src/opensquilla/sandbox/filesystem_worker.py`
  - Make `list_dir` tolerate broken, racing, and individually inaccessible
    children.
- `tests/test_sandbox/test_permission_profiles.py`
- `tests/test_sandbox/test_path_access.py`
- `tests/test_sandbox/test_linux_permissions.py`
- `tests/test_sandbox/test_linux_bwrap.py`
- `tests/test_sandbox/test_linux_helper.py`
- `tests/test_sandbox/test_seatbelt_backend.py`
- `tests/test_sandbox/test_windows_default_acl.py`
- `tests/test_sandbox/test_windows_default_backend.py`
- `tests/test_sandbox/test_windows_default_runner.py`
- `tests/test_sandbox/test_windows_native_smoke.py`
- `tests/test_tools/test_filesystem_read_workspace.py`
- `docs/tools-and-sandbox.md`
- `docs/approvals-and-permissions.md`
- `docs/configuration.md`

Do not restore a tool-local sensitive-path denylist in sandbox-on mode. Do not
add persistent grants, additive permission syntax, or child-process permission
renegotiation in this phase.

---

### Task 1: Resolve Codex Root Semantics Once Per Platform

**Files:**
- Create: `src/opensquilla/sandbox/platform_permissions.py`
- Create: `tests/test_sandbox/test_platform_permissions.py`
- Modify: `src/opensquilla/sandbox/permissions.py`
- Modify: `src/opensquilla/sandbox/policy.py`
- Modify: `src/opensquilla/sandbox/backend/windows_default_roots.py`
- Test: `tests/test_sandbox/test_permission_profiles.py`
- Test: `tests/test_sandbox/test_path_access.py`

- [ ] **Step 1: Write failing platform-resolution contract tests**

Create `tests/test_sandbox/test_platform_permissions.py` with these cases:

```python
from __future__ import annotations

from pathlib import Path, PureWindowsPath

from opensquilla.sandbox.permissions import FileSystemAccess, FileSystemPermissionProfile
from opensquilla.sandbox.platform_permissions import (
    FileSystemPlatformContext,
    FileSystemSpecialPath,
    resolve_special_path,
    resolve_temp_write_paths,
)


def test_posix_root_read_resolves_to_native_root(tmp_path: Path) -> None:
    context = FileSystemPlatformContext(
        platform="linux",
        cwd=tmp_path / "repo",
        home=tmp_path / "home",
    )

    assert resolve_special_path(FileSystemSpecialPath.ROOT, context) == (Path("/"),)


def test_windows_root_read_uses_codex_projection() -> None:
    home = PureWindowsPath(r"C:\Users\lrk")
    workspace = PureWindowsPath(r"D:\src\opensquilla")
    context = FileSystemPlatformContext(
        platform="windows",
        cwd=workspace,
        home=home,
        helper_roots=(PureWindowsPath(r"C:\Users\lrk\.opensquilla\sandbox-bin"),),
        user_profile_children=(
            home / "Desktop",
            home / "Documents",
            home / ".ssh",
            home / ".config",
        ),
    )

    roots = set(resolve_special_path(FileSystemSpecialPath.ROOT, context))

    assert PureWindowsPath(r"C:\Windows") in roots
    assert PureWindowsPath(r"C:\Program Files") in roots
    assert PureWindowsPath(r"C:\Program Files (x86)") in roots
    assert PureWindowsPath(r"C:\ProgramData") in roots
    assert home / "Desktop" in roots
    assert home / "Documents" in roots
    assert home / ".ssh" not in roots
    assert home / ".config" not in roots
    assert workspace in roots


def test_windows_workspace_profile_reads_projection_and_writes_only_workspace() -> None:
    home = PureWindowsPath(r"C:\Users\lrk")
    workspace = PureWindowsPath(r"D:\src\opensquilla")
    context = FileSystemPlatformContext(
        platform="windows",
        cwd=workspace,
        home=home,
        user_profile_children=(home / "Desktop", home / ".ssh"),
    )
    profile = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        platform_context=context,
        tmp_writable=False,
        tmpdir_env_writable=False,
    )

    assert profile.resolve(PureWindowsPath(r"C:\Windows\System32\cmd.exe")) is FileSystemAccess.READ
    assert profile.resolve(home / "Desktop" / "note.txt") is FileSystemAccess.READ
    assert profile.resolve(home / ".ssh" / "id_rsa") is FileSystemAccess.DENY
    assert not profile.is_explicitly_denied(home / ".ssh" / "id_rsa")
    assert profile.resolve(workspace / "src" / "app.py") is FileSystemAccess.WRITE


def test_explicit_deny_overrides_codex_root_read(tmp_path: Path) -> None:
    secret = tmp_path / "home" / "secret"
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path / "repo",
        denied_read_roots=(secret,),
        platform_context=FileSystemPlatformContext(
            platform="macos",
            cwd=tmp_path / "repo",
            home=tmp_path / "home",
        ),
    )

    assert profile.resolve(secret / "token") is FileSystemAccess.DENY
    assert profile.is_explicitly_denied(secret / "token")
    assert not profile.unsandboxed_execution_allowed


def test_platform_temp_roots_match_codex_special_paths() -> None:
    mac = FileSystemPlatformContext(
        platform="macos",
        cwd=Path("/repo"),
        home=Path("/Users/lrk"),
        env={"TMPDIR": "/private/var/tmp/session"},
    )
    windows = FileSystemPlatformContext(
        platform="windows",
        cwd=PureWindowsPath(r"D:\repo"),
        home=PureWindowsPath(r"C:\Users\lrk"),
        env={"TEMP": r"C:\Users\lrk\AppData\Local\Temp"},
    )

    assert resolve_temp_write_paths(mac, include_slash_tmp=True, include_tmpdir=True) == (
        Path("/tmp"),
        Path("/private/var/tmp/session"),
    )
    assert resolve_temp_write_paths(
        windows,
        include_slash_tmp=True,
        include_tmpdir=True,
    ) == (PureWindowsPath(r"C:\Users\lrk\AppData\Local\Temp"),)


def test_windows_denied_glob_uses_windows_separator_semantics() -> None:
    home = PureWindowsPath(r"C:\Users\lrk")
    profile = FileSystemPermissionProfile.workspace(
        workspace=PureWindowsPath(r"D:\repo"),
        denied_read_globs=(r"C:\Users\lrk\Desktop\*.pem",),
        platform_context=FileSystemPlatformContext(
            platform="windows",
            cwd=PureWindowsPath(r"D:\repo"),
            home=home,
            user_profile_children=(home / "Desktop",),
        ),
    )

    assert profile.resolve(home / "Desktop" / "identity.pem") is FileSystemAccess.DENY


def test_later_same_target_rule_controls_compilers_and_elevation(tmp_path: Path) -> None:
    target = tmp_path / "target"
    profile = FileSystemPermissionProfile(
        entries=(
            FileSystemPermissionEntry(target, FileSystemAccess.DENY),
            FileSystemPermissionEntry(target, FileSystemAccess.WRITE),
        )
    )

    assert profile.resolve(target / "file.txt") is FileSystemAccess.WRITE
    assert profile.effective_entries == (
        FileSystemPermissionEntry(target, FileSystemAccess.WRITE),
    )
    assert not profile.has_denied_reads
```

- [ ] **Step 2: Run the contract tests and verify the missing API failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_platform_permissions.py -q
```

Expected: collection fails because `opensquilla.sandbox.platform_permissions`
and `platform_context` do not exist.

- [ ] **Step 3: Implement the platform context and exact Windows projection**

Create `src/opensquilla/sandbox/platform_permissions.py` with this public
surface and the Codex exclusion list:

```python
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePath, PureWindowsPath
from typing import Literal

FileSystemPlatform = Literal["linux", "macos", "windows"]

WINDOWS_PROFILE_READ_EXCLUSIONS = frozenset(
    {
        ".ssh", ".tsh", ".brev", ".gnupg", ".aws", ".azure",
        ".kube", ".docker", ".config", ".npm", ".pki", ".terraform.d",
    }
)
WINDOWS_PLATFORM_READ_ROOTS = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
)


class FileSystemSpecialPath(StrEnum):
    ROOT = "root"
    SLASH_TMP = "slash_tmp"
    TMPDIR = "tmpdir"


@dataclass(frozen=True)
class FileSystemPlatformContext:
    platform: FileSystemPlatform
    cwd: PurePath
    home: PurePath
    helper_roots: tuple[PurePath, ...] = ()
    writable_roots: tuple[PurePath, ...] = ()
    user_profile_children: tuple[PurePath, ...] | None = None
    env: Mapping[str, str] = field(default_factory=dict)


def current_platform_context(
    *, cwd: Path, writable_roots: tuple[Path, ...] = (), helper_roots: tuple[Path, ...] = ()
) -> FileSystemPlatformContext:
    platform: FileSystemPlatform
    if sys.platform.startswith("win"):
        platform = "windows"
    elif sys.platform == "darwin":
        platform = "macos"
    else:
        platform = "linux"
    home = Path.home()
    children: tuple[PurePath, ...] | None = None
    if platform == "windows":
        try:
            children = tuple(home.iterdir())
        except OSError:
            children = ()
    return FileSystemPlatformContext(
        platform=platform,
        cwd=cwd,
        home=home,
        helper_roots=helper_roots,
        writable_roots=writable_roots,
        user_profile_children=children,
        env=dict(os.environ),
    )


def resolve_special_path(
    special: FileSystemSpecialPath, context: FileSystemPlatformContext
) -> tuple[PurePath, ...]:
    if special is FileSystemSpecialPath.SLASH_TMP:
        return () if context.platform == "windows" else (Path("/tmp"),)
    if special is FileSystemSpecialPath.TMPDIR:
        keys = ("TEMP", "TMP", "TMPDIR") if context.platform == "windows" else ("TMPDIR",)
        values = tuple(context.env[key] for key in keys if context.env.get(key))
        if context.platform == "windows":
            return tuple(dict.fromkeys(PureWindowsPath(value) for value in values))
        return tuple(dict.fromkeys(Path(value) for value in values if Path(value).is_absolute()))
    if special is not FileSystemSpecialPath.ROOT:
        raise ValueError(f"unsupported filesystem special path: {special}")
    if context.platform != "windows":
        return (Path("/"),)
    home = PureWindowsPath(str(context.home))
    children = context.user_profile_children or ()
    profile_roots = tuple(
        PureWindowsPath(str(child))
        for child in children
        if PureWindowsPath(str(child)).name.casefold() not in WINDOWS_PROFILE_READ_EXCLUSIONS
    )
    roots = (
        *(PureWindowsPath(root) for root in WINDOWS_PLATFORM_READ_ROOTS),
        *(PureWindowsPath(str(root)) for root in context.helper_roots),
        *profile_roots,
        PureWindowsPath(str(context.cwd)),
        *(PureWindowsPath(str(root)) for root in context.writable_roots),
    )
    return tuple(dict.fromkeys(roots))


def resolve_temp_write_paths(
    context: FileSystemPlatformContext,
    *,
    include_slash_tmp: bool,
    include_tmpdir: bool,
) -> tuple[PurePath, ...]:
    roots: tuple[PurePath, ...] = ()
    if include_slash_tmp:
        roots += resolve_special_path(FileSystemSpecialPath.SLASH_TMP, context)
    if include_tmpdir:
        roots += resolve_special_path(FileSystemSpecialPath.TMPDIR, context)
    return tuple(dict.fromkeys(roots))
```

- [ ] **Step 4: Extend the resolved profile without changing precedence**

Modify `permissions.py` so profile factories accept
`platform_context: FileSystemPlatformContext | None`, use
`resolve_special_path(ROOT, context)` for root-read entries, accept `PurePath`
in entries and resolution, and add these compiler helpers:

```python
@dataclass(frozen=True)
class FileSystemPermissionEntry:
    path: PurePath
    access: FileSystemAccess


@property
def effective_entries(self) -> tuple[FileSystemPermissionEntry, ...]:
    latest: dict[tuple[type[PurePath], str], tuple[int, FileSystemPermissionEntry]] = {}
    for index, entry in enumerate(self.entries):
        canonical = _canonical(entry.path)
        text = str(canonical)
        if isinstance(canonical, PureWindowsPath):
            text = text.casefold()
        latest[(type(canonical), text)] = (index, entry)
    return tuple(entry for _index, entry in sorted(latest.values()))


@property
def readable_roots(self) -> tuple[PurePath, ...]:
    return tuple(
        entry.path for entry in self.effective_entries
        if entry.access is FileSystemAccess.READ
    )

@property
def writable_roots(self) -> tuple[PurePath, ...]:
    return tuple(
        entry.path for entry in self.effective_entries
        if entry.access is FileSystemAccess.WRITE
    )

def read_only_subpaths(self, writable_root: PurePath) -> tuple[PurePath, ...]:
    return tuple(
        entry.path
        for entry in self.effective_entries
        if entry.access is not FileSystemAccess.WRITE
        and _is_relative_to(entry.path, writable_root)
        and entry.path != writable_root
    )

@property
def has_full_disk_read_baseline(self) -> bool:
    return any(
        entry.path == Path("/")
        and entry.access in {FileSystemAccess.READ, FileSystemAccess.WRITE}
        for entry in self.effective_entries
    )
```

Use these path helpers so native `Path` values are resolved without attempting
POSIX resolution of `PureWindowsPath` fixtures:

```python
def _canonical(path: PurePath) -> PurePath:
    if isinstance(path, Path):
        return path.expanduser().resolve(strict=False)
    return type(path)(str(path))


def _is_relative_to(candidate: PurePath, root: PurePath) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_glob(pattern: str) -> str:
    return os.path.expanduser(pattern).replace("\\", "/")
```

Use the special-root resolver in both factories. The relevant construction is:

```python
context = platform_context or current_platform_context(
    cwd=Path(workspace),
    writable_roots=tuple(Path(path) for path in declared_writable),
)
entries: list[FileSystemPermissionEntry] = []
if host_root_readonly:
    entries.extend(
        FileSystemPermissionEntry(root, FileSystemAccess.READ)
        for root in resolve_special_path(FileSystemSpecialPath.ROOT, context)
    )
declared_writable = list(
    dict.fromkeys(
        (
            *declared_writable,
            *resolve_temp_write_paths(
                context,
                include_slash_tmp=tmp_writable,
                include_tmpdir=tmpdir_env_writable,
            ),
        )
    )
)
```

Change `read_only()` to accept `host_root_readonly: bool = True` and
`platform_context: FileSystemPlatformContext | None = None`; prepend the same
resolved special-root entries before explicitly configured readable roots.
Callers that intentionally need a scoped-only profile pass
`host_root_readonly=False`.

Add `default_access: FileSystemAccess = FileSystemAccess.DENY` to the frozen
profile. `full_access()` returns an empty-entry profile with
`default_access=WRITE`; `resolve()` returns `default_access` when no entry
matches. `as_read_only()` converts a `WRITE` default to `READ`. Explicit denies
and globs keep their current precedence and continue to disable unsandboxed
elevation. Compute `has_denied_reads` and `denied_read_roots` from
`effective_entries`, so a later same-target write does not leave a shadowed deny
active in backend compilation or elevation gating. Update factory iterable annotations, `resolve()`,
`is_explicitly_denied()`, and `protected_metadata_root()` from `Path` to
`PurePath` where required; native callers continue to pass concrete `Path`
instances.

- [ ] **Step 5: Resolve the platform context in policy construction**

In `build_policy()`, compute declared writable roots first and pass one context
to `workspace()` or `read_only()`:

```python
platform_context = current_platform_context(
    cwd=workspace,
    writable_roots=tuple(
        mount.host_path for mount in mounts if mount.mode == "rw"
    ),
)
```

Remove the `sys.platform.startswith("linux")` condition around root-read and
temporary-root construction. Use the resolved platform context for both.
Linux/macOS resolve to `/`; Windows resolves to its Codex
projection. Linux and macOS resolve `/tmp`/`$TMPDIR`; Windows resolves its
`TEMP`/`TMP`/`TMPDIR` values and does not invent a POSIX `/tmp` root.

- [ ] **Step 6: Re-export shared Windows constants and run focused tests**

Replace the duplicated Windows platform-root constants in
`windows_default_roots.py` with imports from `platform_permissions.py`, then
run:

```bash
uv run pytest \
  tests/test_sandbox/test_platform_permissions.py \
  tests/test_sandbox/test_permission_profiles.py \
  tests/test_sandbox/test_path_access.py -q
```

Expected: PASS. Existing POSIX path precedence, denied-read, and elevation
classification tests must remain green.

- [ ] **Step 7: Commit the shared profile model**

```bash
git add src/opensquilla/sandbox/platform_permissions.py \
  src/opensquilla/sandbox/permissions.py \
  src/opensquilla/sandbox/policy.py \
  src/opensquilla/sandbox/backend/windows_default_roots.py \
  tests/test_sandbox/test_platform_permissions.py \
  tests/test_sandbox/test_permission_profiles.py \
  tests/test_sandbox/test_path_access.py
git commit -m "feat: resolve Codex filesystem roots per platform"
```

---

### Task 2: Carry One Profile Through Every Filesystem Operation

**Files:**
- Create: `src/opensquilla/sandbox/backend/filesystem_worker_policy.py`
- Create: `tests/test_sandbox/test_filesystem_worker_policy.py`
- Modify: `src/opensquilla/sandbox/operation_runtime.py`
- Modify: `src/opensquilla/tools/builtin/filesystem.py`
- Test: `tests/test_sandbox/test_operation_runtime.py`

- [ ] **Step 1: Write failing propagation and transport tests**

Create `tests/test_sandbox/test_filesystem_worker_policy.py`:

```python
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.filesystem_worker_policy import build_filesystem_worker_policy
from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.permissions import FileSystemPermissionProfile


def test_worker_policy_preserves_operation_profile_and_only_adds_transport(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    worker = workspace / ".opensquilla-cache" / "fs-worker"
    runtime = tmp_path / "runtime"
    workspace.mkdir(parents=True)
    worker.mkdir(parents=True)
    runtime.mkdir(parents=True)
    profile = FileSystemPermissionProfile.workspace(workspace=workspace)
    operation = SandboxOperation.filesystem(
        kind="list_dir",
        workspace=workspace,
        run_mode="standard",
        path=Path("/etc"),
        paths=(Path("/etc"),),
        file_system_profile=profile,
    )

    policy = build_filesystem_worker_policy(
        operation,
        private_rw_roots=(worker,),
        private_ro_roots=(runtime,),
        env_allowlist=("PATH", "PYTHONPATH"),
        description="test worker",
    )

    assert policy.file_system is profile
    assert {(mount.host_path, mount.mode) for mount in policy.mounts} == {
        (worker, "rw"),
        (runtime, "ro"),
    }
    assert Path("/etc") not in {mount.host_path for mount in policy.mounts}


def test_worker_policy_requires_resolved_profile(tmp_path: Path) -> None:
    operation = SandboxOperation.filesystem(
        kind="list_dir",
        workspace=tmp_path,
        run_mode="standard",
        path=tmp_path,
    )

    with pytest.raises(ValueError, match="resolved filesystem profile"):
        build_filesystem_worker_policy(
            operation,
            private_rw_roots=(tmp_path / "worker",),
            private_ro_roots=(),
            env_allowlist=("PATH",),
            description="test worker",
        )
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
uv run pytest tests/test_sandbox/test_filesystem_worker_policy.py -q
```

Expected: collection or construction fails because the builder and operation
field do not exist.

- [ ] **Step 3: Add the operation field and shared worker-policy builder**

Add this field to `SandboxOperation` and parameter to
`SandboxOperation.filesystem()`:

```python
file_system_profile: FileSystemPermissionProfile | None = field(
    default=None,
    repr=False,
    compare=False,
)
```

Pass the parameter into the constructed operation:

```python
return cls(
    domain="filesystem",
    kind=kind,
    request=request,
    workspace=workspace,
    run_mode=run_mode,
    tool_name="filesystem",
    file_system_profile=file_system_profile,
)
```

Do not serialize it into the filesystem worker's user-operation payload; the
backend consumes it before the trusted worker starts.

Create `filesystem_worker_policy.py`:

```python
from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.types import (
    MountSpec, NetworkMode, ResourceLimits, SandboxPolicy, SecurityLevel,
)


def build_filesystem_worker_policy(
    operation: SandboxOperation,
    *,
    private_rw_roots: tuple[Path, ...],
    private_ro_roots: tuple[Path, ...],
    env_allowlist: tuple[str, ...],
    description: str,
) -> SandboxPolicy:
    profile = operation.file_system_profile
    if profile is None:
        raise ValueError("filesystem operation is missing resolved filesystem profile")
    mounts = tuple(
        [
            *(MountSpec(path, path, "ro", True) for path in private_ro_roots),
            *(MountSpec(path, path, "rw", True) for path in private_rw_roots),
        ]
    )
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=mounts,
        workspace_rw=False,
        tmp_writable=True,
        limits=ResourceLimits(cpu_seconds=30, memory_mb=1024, pids=64, wall_timeout_s=30),
        env_allowlist=env_allowlist,
        require_approval=False,
        description=description,
        file_system=profile,
    )
```

- [ ] **Step 4: Attach the active profile exactly once before backend dispatch**

Import `replace` from `dataclasses` in `filesystem.py` and change
`_run_sandbox_operation_if_required()`:

```python
async def _run_sandbox_operation_if_required(
    operation: SandboxOperation,
    *,
    host_execution_active: bool = False,
) -> object | None:
    if operation.domain == "filesystem" and operation.file_system_profile is None:
        profile = active_file_system_profile(_workspace_root())
        if profile is not None:
            operation = replace(operation, file_system_profile=profile)
    return await SandboxOperationRuntime(
        get_runtime(),
        host_execution_active=full_host_access_active() or host_execution_active,
    ).run(operation)
```

This keeps Guardian's `ToolContext.sandbox_file_system_profile` override intact
because `active_file_system_profile()` remains the only lookup function.

- [ ] **Step 5: Run the operation-runtime tests**

```bash
uv run pytest \
  tests/test_sandbox/test_filesystem_worker_policy.py \
  tests/test_sandbox/test_operation_runtime.py \
  tests/test_tools/test_filesystem_read_workspace.py -q
```

Expected: PASS. No filesystem tool result payload changes yet.

- [ ] **Step 6: Commit the shared operation boundary**

```bash
git add src/opensquilla/sandbox/backend/filesystem_worker_policy.py \
  src/opensquilla/sandbox/operation_runtime.py \
  src/opensquilla/tools/builtin/filesystem.py \
  tests/test_sandbox/test_filesystem_worker_policy.py \
  tests/test_sandbox/test_operation_runtime.py \
  tests/test_tools/test_filesystem_read_workspace.py
git commit -m "refactor: carry one filesystem profile into workers"
```

---

### Task 3: Compile the Shared Profile in Bubblewrap

**Files:**
- Modify: `src/opensquilla/sandbox/backend/bubblewrap.py`
- Modify: `src/opensquilla/sandbox/backend/linux_permissions.py`
- Modify: `src/opensquilla/sandbox/backend/linux_payload.py`
- Modify: `src/opensquilla/sandbox/backend/linux_helper.py`
- Test: `tests/test_sandbox/test_linux_permissions.py`
- Test: `tests/test_sandbox/test_linux_bwrap.py`
- Test: `tests/test_sandbox/test_linux_helper.py`

- [ ] **Step 1: Add failing Linux compiler and filesystem-operation tests**

Add to `test_linux_permissions.py`:

```python
from dataclasses import replace


def test_profile_root_read_write_overlay_and_readonly_child_compile_in_order(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    profile = FileSystemPermissionProfile.workspace(workspace=workspace)
    policy = _policy(tmp_path)
    policy = replace(policy, mounts=(), file_system=profile)

    compiled = compile_linux_permissions(policy)

    assert compiled.read_all is True
    assert workspace in {root.host_path for root in compiled.write_roots}
    assert workspace / ".git" in compiled.protected_subpaths
    assert Path("/") in {root.host_path for root in compiled.read_roots}
```

Add an async test around `BubblewrapBackend.run_operation()` that captures the
helper payload and asserts its `fileSystem` contains `/` read and the workspace
write entry, while `/etc` is absent from `mounts` when `/etc` is only the
`list_dir` target:

```python
from opensquilla.sandbox.operation_runtime import SandboxOperation


@pytest.mark.asyncio
async def test_filesystem_operation_uses_attached_profile_not_target_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import bubblewrap as bubblewrap_mod

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile = FileSystemPermissionProfile.workspace(workspace=workspace)
    captured = {}

    async def capture(payload):
        captured["payload"] = payload
        return {"message": "listed", "created": False}

    monkeypatch.setattr(bubblewrap_mod, "_run_linux_helper_payload", capture)
    result = await bubblewrap_mod.BubblewrapBackend().run_operation(
        SandboxOperation.filesystem(
            kind="list_dir",
            workspace=workspace,
            run_mode="standard",
            path=Path("/etc"),
            paths=(Path("/etc"),),
            file_system_profile=profile,
        )
    )

    payload = captured["payload"]
    entries = payload.policy["fileSystem"]["entries"]
    mounts = payload.policy["mounts"]
    assert result.message == "listed"
    assert {"path": "/", "access": "read"} in entries
    assert {"path": str(workspace), "access": "write"} in entries
    assert str(Path("/etc")) not in {mount["host"] for mount in mounts}
```

- [ ] **Step 2: Run the Linux tests and verify target-derived policy failure**

```bash
uv run pytest \
  tests/test_sandbox/test_linux_permissions.py \
  tests/test_sandbox/test_linux_bwrap.py \
  tests/test_sandbox/test_linux_helper.py -q
```

Expected: the new operation test fails because
`bubblewrap._filesystem_operation_policy()` replaces the operation profile.

- [ ] **Step 3: Replace the target-derived policy with private transport grants**

In `BubblewrapBackend.run_operation()`, build the policy like this:

```python
policy = build_filesystem_worker_policy(
    operation,
    private_rw_roots=(payload_path.parent,),
    private_ro_roots=(),
    env_allowlist=("PATH", "PYTHONPATH", "HOME", "TMP", "TEMP"),
    description=f"Linux filesystem worker policy for {operation.kind}",
)
```

Delete `bubblewrap._filesystem_operation_policy()`. Do not add target mounts in
another helper. The target is operation data; only the attached profile grants
access.

- [ ] **Step 4: Compile read-only carve-outs directly from profile entries**

In `compile_linux_permissions()`, keep private mounts, then merge profile
entries. For every profile `READ` entry below a profile `WRITE` root, add the
entry to `protected_subpaths`; for every `DENY`, add it to `denied_roots`.
Deduplicate without changing declaration order:

```python
profile_write_roots = tuple(
    entry.path for entry in profile.effective_entries
    if entry.access is FileSystemAccess.WRITE
)
profile_read_only = tuple(
    entry.path
    for entry in profile.effective_entries
    if entry.access is FileSystemAccess.READ
    and any(entry.path.is_relative_to(root) and entry.path != root for root in profile_write_roots)
)
metadata_protected_subpaths = tuple(
    path
    for root in write_roots
    for base in _protected_subpath_bases(root)
    for path in _protected_subpaths_for_root(base)
)
protected_subpaths = tuple(
    dict.fromkeys((*profile_read_only, *metadata_protected_subpaths))
)
```

The existing `linux_bwrap.py` ordering remains authoritative: read-only root,
deny masks, writable binds, protected subpaths, then nested deny masks. Add an
argv assertion that `--ro-bind / /` occurs before the workspace `--bind`, and
the protected `.git` remount occurs after that bind.

- [ ] **Step 5: Verify helper serialization preserves the complete profile**

Keep `fileSystem.entries` and `deniedReadGlobs` round-tripping in
`linux_payload.py` and `linux_helper.py`. Add a payload test containing read,
write, deny, and glob rules and assert the reconstructed `SandboxPolicy` is
equal at the profile level:

```python
from dataclasses import replace

from opensquilla.sandbox.permissions import FileSystemPermissionProfile


def test_process_payload_round_trips_deny_entries_and_globs(tmp_path: Path) -> None:
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path,
        denied_read_roots=(tmp_path / "secret",),
        denied_read_globs=(str(tmp_path / "**" / "*.pem"),),
    )
    request = SandboxRequest(
        argv=("/bin/true",),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=replace(_policy(tmp_path), file_system=profile),
    )

    payload = build_process_helper_payload(request)
    restored = linux_helper._policy_from_payload(payload.policy)

    assert restored.file_system == profile
```

- [ ] **Step 6: Run Linux backend tests**

```bash
uv run pytest \
  tests/test_sandbox/test_linux_permissions.py \
  tests/test_sandbox/test_linux_bwrap.py \
  tests/test_sandbox/test_linux_payload.py \
  tests/test_sandbox/test_linux_helper.py -q
```

Expected: PASS with no target-derived mount grants.

- [ ] **Step 7: Commit the Linux compiler path**

```bash
git add src/opensquilla/sandbox/backend/bubblewrap.py \
  src/opensquilla/sandbox/backend/linux_permissions.py \
  src/opensquilla/sandbox/backend/linux_payload.py \
  src/opensquilla/sandbox/backend/linux_helper.py \
  tests/test_sandbox/test_linux_permissions.py \
  tests/test_sandbox/test_linux_bwrap.py \
  tests/test_sandbox/test_linux_payload.py \
  tests/test_sandbox/test_linux_helper.py
git commit -m "fix: compile filesystem workers from Linux session profile"
```

---

### Task 4: Compile the Shared Profile in Seatbelt

**Files:**
- Modify: `src/opensquilla/sandbox/backend/seatbelt.py`
- Test: `tests/test_sandbox/test_seatbelt_backend.py`

- [ ] **Step 1: Write failing full-read exclusion and worker parity tests**

Add tests that create a workspace profile with an explicit denied directory:

```python
from dataclasses import replace

from opensquilla.sandbox.permissions import FileSystemPermissionProfile


def test_profile_full_read_excludes_explicit_denied_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    secret = tmp_path / "secret"
    workspace.mkdir()
    secret.mkdir()
    file_system = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        denied_read_roots=(secret,),
    )
    policy = replace(_policy(workspace), file_system=file_system)

    rendered = render_seatbelt_profile(_request(policy, workspace))

    assert "(allow file-read*" in rendered
    assert f'(require-not (subpath "{secret}"))' in rendered
    assert f'(subpath "{workspace}")' in rendered
```

Extend `test_run_operation_delegates_filesystem_to_seatbelt_worker` to attach a
profile to the operation and assert `request.policy.file_system is profile` and
the target path is not a mount grant. Replace its operation construction and
add these assertions:

```python
profile = FileSystemPermissionProfile.workspace(workspace=workspace)
operation = SandboxOperation.filesystem(
    kind="write_text",
    workspace=workspace,
    run_mode="trusted",
    path=target,
    paths=(target,),
    content="hello",
    file_system_profile=profile,
)
result = await SeatbeltBackend().run_operation(operation)

request = captured["request"]
assert request.policy.file_system is profile
assert target not in {mount.host_path for mount in request.policy.mounts}
```

- [ ] **Step 2: Run Seatbelt tests and verify the exclusion is absent**

```bash
uv run pytest tests/test_sandbox/test_seatbelt_backend.py -q
```

Expected: the deny exclusion assertion fails and the worker still uses its
target-derived policy.

- [ ] **Step 3: Render reads and writes from the resolved profile**

Replace the unconditional `(allow file-read*)` and mount-only `_write_rules`
source with profile compiler helpers. The full-read case with exclusions emits:

```scheme
(allow file-read*
  (require-all
    (subpath "/")
    (require-not (subpath "/explicit/deny"))))
```

For each writable root, emit one `file-write*` rule whose `require-all`
contains the root and `require-not` clauses for every nested profile `READ` or
`DENY` entry. Preserve the existing regex protection for missing `.git`,
`.agents`, and `.codex` paths.

Use this Python structure:

```python
def _seatbelt_access_rule(
    action: str,
    root: Path,
    excluded: tuple[Path, ...],
) -> str:
    clauses = [_subpath(root), *[f"(require-not {_subpath(path)})" for path in excluded]]
    return f"(allow {action} (require-all {' '.join(clauses)}))"
```

If the resolved profile has no POSIX `/` baseline, emit one read rule per
`readable_roots` entry. Add private worker mounts to write rules separately;
they are trusted transport and are not inserted into the profile.

Stop adding ambient `_TMP_RW_PATHS` independently of the profile. Process-local
`tmp_dir` remains a private writable transport root, while `/tmp`, `$TMPDIR`,
and Windows temp roots come from the shared platform-resolved profile. This is
required so direct tools and shell commands classify the same temp path the
same way.

- [ ] **Step 4: Use the shared worker-policy builder**

In `_filesystem_operation_request()`, replace
`seatbelt._filesystem_operation_policy()` with:

```python
policy = build_filesystem_worker_policy(
    operation,
    private_rw_roots=(worker_root, payload_path.parent),
    private_ro_roots=_runtime_readonly_roots(),
    env_allowlist=(
        "PATH", "PYTHONPATH", "HOME", "TMP", "TEMP", "TMPDIR", "LANG", "LC_ALL",
    ),
    description=f"macOS filesystem worker policy for {operation.kind}",
)
```

Delete `seatbelt._filesystem_operation_policy()`. Keep target validation for
clear `FileNotFoundError`/`NotADirectoryError`; validation must not grant access.

- [ ] **Step 5: Run the complete Seatbelt suite**

```bash
uv run pytest tests/test_sandbox/test_seatbelt_backend.py -q
```

Expected: PASS on Linux unit simulation; native execution remains gated to a
macOS runner.

- [ ] **Step 6: Commit the macOS compiler path**

```bash
git add src/opensquilla/sandbox/backend/seatbelt.py \
  tests/test_sandbox/test_seatbelt_backend.py
git commit -m "fix: compile Seatbelt filesystem access from session profile"
```

---

### Task 5: Compile the Shared Profile into Windows Grants and Denies

**Files:**
- Modify: `src/opensquilla/sandbox/backend/windows_default.py`
- Modify: `src/opensquilla/sandbox/backend/windows_default_acl.py`
- Modify: `src/opensquilla/sandbox/backend/windows_default_runner.py`
- Test: `tests/test_sandbox/test_windows_default_acl.py`
- Test: `tests/test_sandbox/test_windows_default_backend.py`
- Test: `tests/test_sandbox/test_windows_default_filesystem_policy.py`
- Test: `tests/test_sandbox/test_windows_default_runner.py`

- [ ] **Step 1: Write failing Windows ACL-plan tests**

Add a backend test using real temporary paths so it runs on every CI host:

```python
from dataclasses import replace

from opensquilla.sandbox.permissions import (
    FileSystemAccess,
    FileSystemPermissionEntry,
    FileSystemPermissionProfile,
)


def test_windows_acl_plan_compiles_profile_reads_writes_and_denies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    readable = tmp_path / "readable"
    workspace = tmp_path / "workspace"
    secret = readable / "secret"
    for path in (readable, workspace, workspace / ".git", secret):
        path.mkdir(parents=True, exist_ok=True)
    profile = FileSystemPermissionProfile(
        entries=(
            FileSystemPermissionEntry(readable, FileSystemAccess.READ),
            FileSystemPermissionEntry(workspace, FileSystemAccess.WRITE),
            FileSystemPermissionEntry(workspace / ".git", FileSystemAccess.READ),
            FileSystemPermissionEntry(secret, FileSystemAccess.DENY),
        )
    )
    request = _request(tmp_path).with_policy(
        replace(_policy(), file_system=profile)
    )
    monkeypatch.setattr(mod, "capability_sids_for_command", lambda path, roots: tuple(f"S-{i}" for i, _ in enumerate(roots)))

    plan = mod._acl_plan_payload(request)
    grants = {item["path"]: item["access"] for item in plan["autoGrants"]}

    assert grants[str(readable)] == "RX"
    assert grants[str(workspace)] == "RWX"
    assert str(workspace / ".git") in plan["denyWritePaths"]
    assert str(secret) in plan["denyReadPaths"]
```

Add runner tests asserting `_windows_acl_plan()` rejects a non-string
`denyReadPaths` value and `_apply_acl_refresh()` calls `_deny_read_path_to_sid`
for each matching capability SID:

```python
from opensquilla.sandbox.backend import windows_default_runner as runner


def test_windows_acl_plan_rejects_invalid_deny_read_paths() -> None:
    with pytest.raises(SystemExit, match="denyReadPaths must be a string list"):
        runner._windows_acl_plan(
            {
                "windowsAclPlan": {
                    "autoGrants": [],
                    "capabilitySids": [],
                    "denyReadPaths": [1],
                }
            }
        )


def test_apply_acl_refresh_applies_deny_read_to_covering_sid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readable = tmp_path / "readable"
    denied = readable / "secret"
    denied.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(runner, "_grant_path_to_sid", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "_deny_read_path_to_sid",
        lambda path, sid: calls.append((path, sid)),
    )
    runner._apply_acl_refresh(
        {
            "autoGrants": [
                {
                    "path": str(readable),
                    "access": "RX",
                    "kind": "policy",
                    "capabilitySid": "S-1-test",
                }
            ],
            "capabilitySids": ["S-1-test"],
            "denyWritePaths": [],
            "denyReadPaths": [str(denied)],
        }
    )

    assert calls == [(denied, "S-1-test")]
```

- [ ] **Step 2: Run focused Windows tests and verify missing deny-read support**

```bash
uv run pytest \
  tests/test_sandbox/test_windows_default_acl.py \
  tests/test_sandbox/test_windows_default_backend.py \
  tests/test_sandbox/test_windows_default_filesystem_policy.py \
  tests/test_sandbox/test_windows_default_runner.py -q
```

Expected: new assertions fail because ACL planning still derives access from
mounts and the runner ignores `denyReadPaths`.

- [ ] **Step 3: Build ACL grants from profile entries**

In `_acl_plan_payload()`, translate existing profile paths as follows:

```python
def _profile_acl_grants(request: SandboxRequest) -> tuple[AclGrant, ...]:
    profile = request.policy.file_system
    if profile is None:
        raise SandboxBackendError("windows_default requires a resolved filesystem profile")
    grants = []
    for entry in profile.effective_entries:
        path = Path(entry.path)
        if entry.access is FileSystemAccess.DENY or not path.exists():
            continue
        access = AclAccess.RWX if entry.access is FileSystemAccess.WRITE else AclAccess.RX
        if access is AclAccess.RX and not _rx_root_needs_acl_grant(path, request.env):
            continue
        grants.append(
            AclGrant(path, access, AclGrantKind.POLICY)
        )
    return tuple(grants)
```

Platform roots already readable through the restricted token's base Windows
ACLs must continue to be skipped by `_rx_root_needs_acl_grant()`; do not try to
rewrite ACLs on `C:\Windows` or `C:\Program Files` during each command.

Private mounts from `build_filesystem_worker_policy()` remain required grants.
Profile entries become policy grants. Do not pass profile grants through
`windows_sensitive_marker`; the shared profile has already excluded or denied
paths. Keep the legacy sensitivity check only for
`OPENSQUILLA_WINDOWS_SANDBOX_EXPANSION_ROOTS`, which is outside Phase 1.

Delete the unconditional `workspace_write_roots(request.cwd)` grants from
`_acl_plan_payload()`. The cwd is writable only when the resolved profile says
so; a read-only external cwd must not become writable merely because it is the
process cwd. Filesystem-worker cache directories remain writable through their
explicit private RW mounts.

Extend `plan_acl_refresh()` without changing its default behavior:

```python
def plan_acl_refresh(
    *,
    run_mode: RunMode | str,
    required: Iterable[AclGrant],
    policy: Iterable[AclGrant],
    expansion: Iterable[AclGrant],
    sensitive_marker: Callable[[Path], str | None],
    required_policy_sensitive_marker: Callable[[Path], str | None] | None = None,
) -> AclRefreshPlan:
    mode = normalize_run_mode(run_mode)
    if mode is RunMode.FULL:
        return AclRefreshPlan(auto_grants=(), approval_required=(), denied=())

    base_marker = required_policy_sensitive_marker or sensitive_marker
    auto: list[AclGrant] = []
    ask: list[AclGrant] = []
    denied: list[AclDeniedGrant] = []
    for grant in _dedupe_grants((*required, *policy)):
        if marker := base_marker(grant.path):
            denied.append(AclDeniedGrant(grant=grant, reason=marker))
        else:
            auto.append(grant)
    for grant in _dedupe_grants(tuple(expansion)):
        if marker := sensitive_marker(grant.path):
            denied.append(AclDeniedGrant(grant=grant, reason=marker))
        elif mode is RunMode.TRUSTED:
            auto.append(grant)
        else:
            ask.append(grant)
    return AclRefreshPlan(
        auto_grants=tuple(auto),
        approval_required=tuple(ask),
        denied=tuple(denied),
    )
```

In `windows_default._acl_plan_payload()`, pass
`required_policy_sensitive_marker=lambda _path: None`. Add an ACL planner test
showing a policy grant is automatic through that override while an expansion
grant with the same sensitive marker is still denied:

```python
from opensquilla.sandbox.backend.windows_default_acl import (
    AclAccess,
    AclGrant,
    AclGrantKind,
    plan_acl_refresh,
)


def test_policy_grants_bypass_legacy_marker_but_expansions_do_not(tmp_path: Path) -> None:
    policy = AclGrant(tmp_path / "policy", AclAccess.RX, AclGrantKind.POLICY)
    expansion = AclGrant(tmp_path / "expansion", AclAccess.RWX, AclGrantKind.EXPANSION)

    plan = plan_acl_refresh(
        run_mode=RunMode.TRUSTED,
        required=(),
        policy=(policy,),
        expansion=(expansion,),
        sensitive_marker=lambda _path: "legacy_sensitive",
        required_policy_sensitive_marker=lambda _path: None,
    )

    assert plan.auto_grants == (policy,)
    assert [item.grant for item in plan.denied] == [expansion]
```

Compute `denyWritePaths` from profile `READ`/`DENY` entries nested below a
profile `WRITE` root plus existing private read-only runtime mounts. Compute
`denyReadPaths` from `profile.denied_read_roots`.

- [ ] **Step 4: Use the shared worker policy and delete the Windows narrow policy**

Replace `_filesystem_operation_policy()` in `_filesystem_operation_request()`:

```python
policy = build_filesystem_worker_policy(
    operation,
    private_rw_roots=(worker_root, payload_path.parent),
    private_ro_roots=_runtime_readonly_roots(),
    env_allowlist=(
        "PATH", "PYTHONPATH", "SystemRoot", "WINDIR", "ComSpec", "TEMP", "TMP",
        "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    ),
    description=f"Windows filesystem worker policy for {operation.kind}",
)
```

Delete `windows_default._filesystem_operation_policy()` and target-root grant
helpers that become unused. Preserve preflight existence/type validation.

- [ ] **Step 5: Validate and apply deny-read ACLs in the runner**

Extend `_windows_acl_plan()` to normalize `denyReadPaths`. Refactor the native
deny-ACE writer so read and write masks share one implementation:

```python
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_EXECUTE = 0x001200A0
GENERIC_READ = 0x80000000
FILE_MUTATION_DENY_MASK = (
    FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | FILE_DELETE_CHILD
)
FILE_WRITE_DENY_MASK = FILE_MUTATION_DENY_MASK | FILE_GENERIC_WRITE | GENERIC_WRITE
FILE_READ_DENY_MASK = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE | GENERIC_READ


def _deny_read_path_to_sid(path: Path, sid: str) -> None:
    _deny_path_to_sid(
        path,
        sid,
        mask=FILE_READ_DENY_MASK,
        label="deny-read",
    )


def _deny_write_path_to_sid(
    path: Path,
    sid: str,
    *,
    include_read_control: bool = True,
) -> None:
    _deny_path_to_sid(
        path,
        sid,
        mask=FILE_WRITE_DENY_MASK if include_read_control else FILE_MUTATION_DENY_MASK,
        label="deny-write",
    )


def _deny_path_to_sid(path: Path, sid: str, *, mask: int, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"windows_default ACL {label} target does not exist: {path}")
    try:
        _deny_path_to_sid_native(path, sid, mask=mask)
    except OSError as exc:
        raise SystemExit(f"windows_default ACL {label} failed for {path}: {exc}") from exc


def _deny_read_capability_sids_for_path(
    plan: dict[str, Any],
    deny_path: Path,
) -> tuple[str, ...]:
    matching = []
    for grant in plan.get("autoGrants", []):
        if not isinstance(grant, dict) or grant.get("access") not in {"RX", "RWX"}:
            continue
        raw_root = grant.get("path")
        sid = grant.get("capabilitySid")
        if not isinstance(raw_root, str) or not isinstance(sid, str):
            continue
        if _path_contains_casefold(
            Path(raw_root).resolve(strict=False),
            deny_path.resolve(strict=False),
        ):
            matching.append(sid)
    return tuple(dict.fromkeys(matching))
```

Rename the current `_deny_write_path_to_sid_native()` implementation to
`_deny_path_to_sid_native(path, sid, *, mask)`. Keep its existing trustee,
inheritance, DACL ordering, and cleanup logic, replacing only its hard-coded
write mask with the `mask` parameter. Keep `_deny_file_mutation_path_to_sid()`
as a call to `_deny_write_path_to_sid(..., include_read_control=False)`.

Apply grants first, deny-write entries second, and deny-read entries last.
For each deny-read path, apply the ACE to every SID returned by
`_deny_read_capability_sids_for_path()`; fail closed if an existing denied path
has no covering read grant because the plan would not enforce the requested
carve-out.
Include both deny lists in offline-identity cleanup. Missing configured deny
targets may be skipped if they raced out of existence; an ACL API failure on an
existing target must terminate the operation.

- [ ] **Step 6: Run all deterministic Windows sandbox tests**

```bash
uv run pytest tests/test_sandbox/test_windows_default_*.py -q
```

Expected: PASS on Linux with native-only tests skipped by their existing
markers.

- [ ] **Step 7: Commit the Windows compiler path**

```bash
git add src/opensquilla/sandbox/backend/windows_default.py \
  src/opensquilla/sandbox/backend/windows_default_acl.py \
  src/opensquilla/sandbox/backend/windows_default_runner.py \
  tests/test_sandbox/test_windows_default_acl.py \
  tests/test_sandbox/test_windows_default_backend.py \
  tests/test_sandbox/test_windows_default_filesystem_policy.py \
  tests/test_sandbox/test_windows_default_runner.py
git commit -m "fix: compile Windows filesystem ACLs from session profile"
```

---

### Task 6: Make Sandboxed Directory Listing Resilient Per Entry

**Files:**
- Create: `tests/test_sandbox/test_filesystem_worker.py`
- Modify: `src/opensquilla/sandbox/filesystem_worker.py`
- Modify: `tests/test_tools/test_filesystem_read_workspace.py`

- [ ] **Step 1: Write failing worker tests for dangling and unstatable entries**

Create `tests/test_sandbox/test_filesystem_worker.py`:

```python
from pathlib import Path

import pytest

from opensquilla.sandbox import filesystem_worker


def test_list_dir_keeps_siblings_when_symlink_target_is_missing(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "dangling").symlink_to(tmp_path / "missing-target")

    result = filesystem_worker._list_dir(
        {"path": str(tmp_path), "displayPath": str(tmp_path)}
    )

    assert "[file] ok.txt (5 bytes)" in result["message"]
    assert "[link] dangling (broken symlink)" in result["message"]


def test_list_dir_keeps_siblings_when_one_stat_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("secret", encoding="utf-8")
    original_stat = Path.stat

    def selective_stat(path: Path, *args: object, **kwargs: object):
        if path == blocked:
            raise PermissionError("blocked for test")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", selective_stat)

    result = filesystem_worker._list_dir({"path": str(tmp_path)})

    assert "ok.txt" in result["message"]
    assert "[file] blocked.txt (metadata unavailable)" in result["message"]


def test_list_dir_preserves_requested_directory_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_iterdir = Path.iterdir

    def selective_iterdir(path: Path):
        if path == tmp_path:
            raise PermissionError("directory denied for test")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", selective_iterdir)

    with pytest.raises(PermissionError, match="directory denied for test"):
        filesystem_worker._list_dir({"path": str(tmp_path)})
```

- [ ] **Step 2: Run the worker tests and verify the raw `stat()` failure**

```bash
uv run pytest tests/test_sandbox/test_filesystem_worker.py -q
```

Expected: at least one test fails from `entry.stat()` or reports the dangling
link as an ordinary file error.

- [ ] **Step 3: Implement per-entry non-following classification**

Replace the worker loop with this behavior:

```python
for entry in sorted(path.iterdir(), key=lambda item: item.name):
    try:
        if entry.is_symlink():
            try:
                size = entry.stat().st_size
            except OSError:
                files.append(f"[link] {entry.name} (broken symlink)")
            else:
                files.append(f"[link] {entry.name} ({size} bytes target)")
        elif entry.is_dir():
            dirs.append(f"[dir]  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                files.append(f"[file] {entry.name} (size unavailable)")
            else:
                files.append(f"[file] {entry.name} ({size} bytes)")
    except OSError:
        files.append(f"[file] {entry.name} (metadata unavailable)")
```

Opening or enumerating the requested directory must still raise its original
error. Only child metadata failures are softened.

- [ ] **Step 4: Verify host fallback and worker output agree**

Extend the existing broken-symlink tool test so the backend worker path is
covered by the new worker test and the host fallback uses the same label. Add:

```python
assert "[file] ok.txt (6 bytes)" in output
assert "[link] dangling (broken symlink)" in output
```

Then run:

```bash
uv run pytest \
  tests/test_sandbox/test_filesystem_worker.py \
  tests/test_tools/test_filesystem_read_workspace.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit directory resilience**

```bash
git add src/opensquilla/sandbox/filesystem_worker.py \
  tests/test_sandbox/test_filesystem_worker.py \
  tests/test_tools/test_filesystem_read_workspace.py
git commit -m "fix: keep directory listings after child metadata errors"
```

---

### Task 7: Prove Tool Parity, Elevation Semantics, and Native Behavior

**Files:**
- Create: `tests/test_sandbox/test_filesystem_profile_integration.py`
- Modify: `tests/test_sandbox/test_elevation.py`
- Modify: `tests/test_sandbox/test_path_access.py`
- Modify: `tests/test_sandbox/test_windows_native_smoke.py`
- Modify: `docs/tools-and-sandbox.md`
- Modify: `docs/approvals-and-permissions.md`
- Modify: `docs/configuration.md`

- [ ] **Step 1: Add an exact create/delete approval regression test**

Add to `test_elevation.py`:

```python
def test_create_and_delete_receive_distinct_one_shot_approvals(tmp_path: Path) -> None:
    queue = ApprovalQueue(db_path=str(tmp_path / "approvals.sqlite"))
    target = tmp_path / "outside" / "probe.txt"
    create = replace(
        _shell_action(f"mkdir -p {target.parent} && printf test > {target}"),
        target_paths=((str(target.parent), "write"), (str(target), "write")),
    )
    delete = replace(
        _shell_action(f"rm {target} && rmdir {target.parent}"),
        target_paths=((str(target), "write"), (str(target.parent), "write")),
    )
    try:
        create_pending = request_elevation(queue, create, session_key="session-1")
        delete_pending = request_elevation(queue, delete, session_key="session-1")

        assert create.fingerprint() != delete.fingerprint()
        assert create_pending.approval_id != delete_pending.approval_id
        assert len(queue.list_pending("exec")) == 2
    finally:
        queue.close()
```

This documents that automatic review may approve both operations but never
turns the create grant into a reusable delete grant.

- [ ] **Step 2: Add native Linux reproduction coverage**

Create `test_filesystem_profile_integration.py` with a Linux/bubblewrap marker.
The core regression is:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend
from opensquilla.sandbox.backend.seatbelt import SeatbeltBackend
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.path_validation import decide_path_access
from opensquilla.sandbox.permissions import FileSystemPermissionProfile
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.types import SandboxRequest, SecurityLevel


@pytest.mark.asyncio
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux native smoke")
@pytest.mark.parametrize("target", [Path("/etc"), Path("/home"), Path("/var"), Path.home()])
async def test_bubblewrap_filesystem_worker_reads_codex_host_view(
    target: Path,
    tmp_path: Path,
) -> None:
    backend = BubblewrapBackend()
    if not backend.available() or not target.exists():
        pytest.skip("bubblewrap or target is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile = FileSystemPermissionProfile.workspace(workspace=workspace)
    result = await backend.run_operation(
        SandboxOperation.filesystem(
            kind="list_dir",
            workspace=workspace,
            run_mode="standard",
            path=target,
            paths=(target,),
            display_path=str(target),
            file_system_profile=profile,
        )
    )

    assert isinstance(result.message, str)
    assert result.message
```

Add a second Linux case with an explicit denied root and assert the direct path
preflight is `blocked`; do not invoke the backend for a denied target:

```python
def test_explicit_denied_read_is_blocked_before_backend(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    denied = tmp_path / "secret"
    profile = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        denied_read_roots=(denied,),
    )

    decision = decide_path_access(
        denied / "token",
        workspace=workspace,
        profile=profile,
    )

    assert decision.status == "blocked"
    assert decision.reason == "denied_read"
```

- [ ] **Step 3: Add macOS and Windows native smoke cases behind platform markers**

On macOS, construct the same `list_dir` operation against `/etc` and the user
home with `SeatbeltBackend`; assert non-empty results. On Windows, extend
`test_windows_native_smoke.py` to read `%SystemRoot%`, an ordinary
`%USERPROFILE%` child, and the operation cwd through both the shell runner and
the filesystem worker. Also assert a configured deny path fails in both.

Use these explicit native tests and platform skips for macOS:

```python
@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt required")
@pytest.mark.parametrize("target", [Path("/etc"), Path.home()])
async def test_seatbelt_shell_and_worker_share_host_read_profile(
    target: Path,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(),
    )
    assert policy.file_system is not None
    backend = SeatbeltBackend()
    worker = await backend.run_operation(
        SandboxOperation.filesystem(
            kind="list_dir",
            workspace=workspace,
            run_mode="standard",
            path=target,
            paths=(target,),
            file_system_profile=policy.file_system,
        )
    )
    shell = await backend.run(
        SandboxRequest(
            argv=("/bin/ls", str(target)),
            cwd=workspace,
            action_kind="shell.exec",
            policy=policy,
            run_mode="standard",
        )
    )

    assert worker.message
    assert shell.returncode == 0
```

Use this native Windows core in `test_windows_native_smoke.py`:

```python
import os

from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.path_validation import decide_path_access
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.types import SandboxRequest, SecurityLevel


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="native Windows sandbox required",
)


@pytest.mark.asyncio
async def test_windows_shell_and_worker_share_codex_projection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(),
    )
    assert policy.file_system is not None
    backend = WindowsDefaultBackend()
    targets = (
        Path(os.environ["SystemRoot"]),
        Path(os.environ["USERPROFILE"]) / "Documents",
        workspace,
    )
    for target in targets:
        if not target.exists():
            continue
        worker = await backend.run_operation(
            SandboxOperation.filesystem(
                kind="list_dir",
                workspace=workspace,
                run_mode="standard",
                path=target,
                paths=(target,),
                file_system_profile=policy.file_system,
            )
        )
        shell = await backend.run(
            SandboxRequest(
                argv=("cmd.exe", "/d", "/c", "dir", str(target)),
                cwd=workspace,
                action_kind="shell.exec",
                policy=policy,
                run_mode="standard",
            )
        )

        assert worker.message
        assert shell.returncode == 0
```

Add the native Windows denied-read parity case:

```python
@pytest.mark.asyncio
async def test_windows_explicit_deny_blocks_direct_and_shell_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    denied = tmp_path / "denied"
    workspace.mkdir()
    denied.mkdir()
    sentinel = denied / "sentinel.txt"
    sentinel.write_text("must-not-appear", encoding="utf-8")
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(denied_read_roots=[str(denied)]),
    )
    assert policy.file_system is not None
    direct = decide_path_access(
        sentinel,
        workspace=workspace,
        profile=policy.file_system,
    )
    shell = await WindowsDefaultBackend().run(
        SandboxRequest(
            argv=("cmd.exe", "/d", "/c", "type", str(sentinel)),
            cwd=workspace,
            action_kind="shell.exec",
            policy=policy,
            run_mode="standard",
        )
    )

    assert direct.status == "blocked"
    assert shell.returncode != 0
    assert "must-not-appear" not in shell.stdout
```

- [ ] **Step 4: Run parity and elevation tests**

```bash
uv run pytest \
  tests/test_sandbox/test_elevation.py \
  tests/test_sandbox/test_path_access.py \
  tests/test_sandbox/test_filesystem_profile_integration.py -q
```

Expected on Linux: approval and path tests PASS; available bubblewrap smoke
cases PASS; macOS/Windows-native cases SKIP rather than being reported as
verified.

On a macOS runner, run:

```bash
uv run pytest tests/test_sandbox/test_filesystem_profile_integration.py \
  tests/test_sandbox/test_seatbelt_backend.py -q
```

On a native Windows runner with sandbox setup complete, run:

```powershell
uv run pytest tests/test_sandbox/test_windows_default_*.py `
  tests/test_sandbox/test_windows_native_smoke.py -q
```

Expected on the matching native platform: zero failures. Record the command,
commit, OS version, and result before marking that platform verified.

- [ ] **Step 5: Update user-facing documentation with exact platform semantics**

Document these statements verbatim in the relevant sandbox sections:

```text
With the sandbox enabled, shell commands and direct filesystem tools use the
same filesystem permission profile. Linux and macOS expose the host filesystem
read-only except for explicit denied reads and normal OS permission failures.
Windows follows Codex's restricted-account projection: Windows and Program
Files roots, ProgramData, non-sensitive direct USERPROFILE children, the
operation working directory, helper runtime roots, and declared writable roots.

Only declared writable roots are writable without review. A write outside those
roots returns elevation_required. require_escalated submits the exact action to
Guardian; an allow executes that fingerprint once. A changed command, path,
content, create, or delete is a separate approval decision.
```

Do not claim that all Windows volumes or excluded profile directories are
globally readable.

- [ ] **Step 6: Run formatting, typing, and the complete affected regression set**

```bash
uv run ruff check src/opensquilla/sandbox src/opensquilla/tools/builtin/filesystem.py tests/test_sandbox tests/test_tools/test_filesystem_read_workspace.py
uv run mypy src/opensquilla/sandbox/permissions.py \
  src/opensquilla/sandbox/platform_permissions.py \
  src/opensquilla/sandbox/operation_runtime.py \
  src/opensquilla/sandbox/backend
uv run pytest tests/test_sandbox tests/test_tools/test_filesystem_read_workspace.py -q
git diff --check
```

Expected: Ruff and MyPy exit 0; Pytest reports zero failures; native tests for
unavailable operating systems are explicitly skipped; `git diff --check`
produces no output.

- [ ] **Step 7: Commit parity coverage and documentation**

```bash
git add tests/test_sandbox/test_filesystem_profile_integration.py \
  tests/test_sandbox/test_elevation.py \
  tests/test_sandbox/test_path_access.py \
  tests/test_sandbox/test_windows_native_smoke.py \
  docs/tools-and-sandbox.md \
  docs/approvals-and-permissions.md \
  docs/configuration.md
git commit -m "test: verify Codex filesystem parity across sandbox tools"
```

---

## Completion Gate

Before declaring implementation complete, collect fresh evidence for all of
these items:

1. `list_dir` and shell read the same allowed Linux host paths.
2. Worker directory listing survives a dangling symlink and an unstatable
   child.
3. Linux mount order is root read-only, writable overlays, then protected and
   denied carve-outs.
4. Seatbelt renders full/scoped reads and writes from `policy.file_system`.
5. Windows ACL plans contain Codex projection RX grants, exact RWX roots,
   `denyWritePaths`, and `denyReadPaths`.
6. The direct tools and shell return the same category for allowed reads,
   explicit denies, workspace writes, and external writes.
7. External create and delete actions have separate fingerprints, approvals,
   and one-shot consumption.
8. Linux native evidence is recorded. macOS and Windows are described as
   unverified until their native smoke tests run on those platforms.
9. No backend contains a target-derived `_filesystem_operation_policy` grant
   path.
10. No sandbox-on direct tool applies a parallel hard-coded sensitive-path
    denylist.

Do not push the branch until the user explicitly asks for a remote update.
