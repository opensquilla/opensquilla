# Sandbox Run Mode P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the P0 sandbox run-mode migration so `Standard-Sandbox`, `Trusted-Sandbox`, and `Full Host Access` replace the old `bypass/elevated` user semantics without regressing the existing project test suite.

**Architecture:** Centralize new run-mode vocabulary in `opensquilla.sandbox`, then adapt CLI, session context, approvals, tools, frontend, and backend selection around that boundary. `Trusted-Sandbox` must skip routine prompts while still executing in the sandbox; only `Full Host Access` and sandbox-failure `Host Once` may run on the host.

**Tech Stack:** Python 3.12, Pydantic settings, Typer CLI, Starlette gateway RPC, existing vanilla JS Web UI, pytest.

---

## Scope

This plan implements the P0 behavior from:

- `docs/superpowers/specs/2026-05-29-sandbox-run-mode-design.md`
- `docs/superpowers/specs/2026-06-01-sandbox-design-ui-refresh-comparison.md`

In scope:

- Three run modes: `Standard-Sandbox`, `Trusted-Sandbox`, `Full Host Access`.
- CLI commands: `opensquilla sandbox on|trust|full|status|reset`.
- `opensquilla sandbox bypass` removed as a supported mode and changed to a no-op failure with migration guidance.
- Session-scoped Run Context for run mode, workspace, mounts, and future domain grants.
- Existing chats keep saved Run Context; new chats initialize from global default.
- Normal approval no longer implies host execution.
- `Trusted-Sandbox` skips routine sandboxed prompts but still asks for boundary expansion and Host Once.
- Host Once appears only after sandbox-related backend failure.
- Chat composer gear shows `Run Mode`, `Squilla Router`, and `Visual effects`.
- Approvals surfaces remove `Bypass Approvals`.
- First slice of external path access and mount validation.
- Native Windows backend entry named `windows_restricted_token`, with fail-closed behavior when helper/setup is unavailable.
- Additive sandbox-focused tests are added directly under `tests/test_sandbox/` as the relevant behavior is implemented.

Out of scope for this plan:

- Full `Control -> Sandbox` page.
- Allowed Domains and package-manager domain bundles.
- Full proxy/allowlist network guard.
- Resource-limit hardening beyond what existing backends already expose.
- Worktree/session isolation.
- Broad Claude-style auto classifier.

Those are separate P1/P2 plans.

## File Structure

New files:

- `src/opensquilla/sandbox/run_mode.py`  
  Owns public run-mode vocabulary, legacy mapping, config patches, display labels, and execution/approval behavior helpers.

- `src/opensquilla/sandbox/run_context.py`  
  Owns session Run Context data, serialization into `SessionNode.origin`, default initialization, and safe update helpers.

- `src/opensquilla/sandbox/path_validation.py`  
  Owns cross-platform mount candidate normalization and block/ask/allow decisions.

- `src/opensquilla/gateway/rpc_sandbox.py`  
  Owns RPC methods for `sandbox.run_context.get` and `sandbox.run_context.set`.

- `src/opensquilla/sandbox/backend/windows_restricted_token.py`  
  Python backend adapter for native Windows restricted-token sandbox execution.

- `src/opensquilla/sandbox/backend/windows_restricted_token_helper.py`  
  Windows-only helper boundary. Uses Win32 APIs through `ctypes`; fails closed when a policy cannot be enforced.

Modified files:

- `src/opensquilla/sandbox/config.py`  
  Add `run_mode` and `windows_restricted_token` backend selection vocabulary.

- `src/opensquilla/sandbox/status.py`  
  Report run mode instead of old `posture=bypass` as the primary state.

- `src/opensquilla/sandbox/policy.py`  
  Accept per-session mounts and keep `Trusted-Sandbox` sandboxed.

- `src/opensquilla/sandbox/integration.py`  
  Resolve policy from Run Context and fail closed when saved sandbox context cannot be satisfied.

- `src/opensquilla/sandbox/backend/__init__.py`  
  Select `windows_restricted_token` on native Windows when available.

- `src/opensquilla/permissions.py`  
  Replace default elevated helper with default run-mode helper. Keep legacy elevated compatibility only for `full`.

- `src/opensquilla/gateway/config.py`  
  Keep old `permissions.default_mode` for compatibility, but add/validate sandbox run-mode config.

- `src/opensquilla/cli/sandbox_cmd.py`  
  Implement `on|trust|full|status|reset`; make `bypass` fail with migration guidance.

- `src/opensquilla/application/approval_queue.py`  
  Store session run-mode overrides instead of session elevated/bypass overrides.

- `src/opensquilla/application/approval_rpc.py`  
  Stop accepting ordinary approval as permission to switch to host execution.

- `src/opensquilla/gateway/app.py`  
  Remove `/api/elevated-mode` as the primary UI path; add `/api/run-mode` compatibility wrapper or route it to the new RPC.

- `src/opensquilla/gateway/rpc/__init__.py`  
  Register `rpc_sandbox`.

- `src/opensquilla/gateway/rpc_approvals.py`  
  Remove `elevatedMode=bypass` from ordinary approval resolution.

- `src/opensquilla/gateway/rpc_chat.py`  
  Accept `_source.runMode` instead of `_source.elevated`.

- `src/opensquilla/gateway/rpc_sessions.py`  
  Initialize and persist Run Context; place resolved run mode into route metadata.

- `src/opensquilla/gateway/routing.py`  
  Build `ToolContext.run_mode`; do not turn `Trusted-Sandbox` into `ToolContext.elevated`.

- `src/opensquilla/tools/types.py`  
  Add `run_mode`, `sandbox_mounts`, and `host_once` context fields.

- `src/opensquilla/tools/builtin/shell.py`  
  Make ordinary approval sandboxed; make `Trusted-Sandbox` skip routine approval without host execution; keep Host Once only after sandbox backend denial.

- `src/opensquilla/tools/builtin/code_exec.py`  
  Align sensitive approval and sandbox behavior with the new run-mode contract.

- `src/opensquilla/tools/builtin/filesystem.py`  
  Route external paths to Path Access Request instead of host fallback.

- `src/opensquilla/gateway/static/js/views/chat.js`  
  Replace `Execution mode`/bypass UI with `Run Mode`.

- `src/opensquilla/gateway/static/js/views/approvals.js`  
  Remove `Bypass approvals` action.

- `src/opensquilla/gateway/static/js/approval_monitor.js`  
  Remove modal `Bypass Approvals` action.

- `src/opensquilla/gateway/static/js/views/config.js`  
  Replace user-facing help text for old sandbox posture.

- `src/opensquilla/gateway/static/css/views/chat.css`  
  Rename bypass-dot styling to run-mode state styling while preserving existing layout.

Existing tests that are allowed to change because they explicitly lock the old sandbox semantics:

- `tests/test_cli/test_sandbox_cmd.py`
- `tests/test_gateway/test_chat_static_assets.py`

Do not modify unrelated tests.

Sandbox tests should be added directly under:

- `tests/test_sandbox/`

Tests introduced for a task should live with that task's commit when they are useful long-term. Do not create a separate test directory.

## Test Decision Rules

- Use `uv run pytest`, not bare `pytest`, because the project expects the repository-local environment.
- There is no required pre-development full-suite baseline gate.
- There is no required post-development full-suite baseline gate.
- The implementation owner chooses tests based on the files and behavior touched by each task.
- Full `uv run pytest tests` is optional diagnostic evidence only. If it fails in unrelated areas, record the failures and continue.
- Do not edit unrelated tests to make the suite pass.
- Add important new sandbox tests directly to `tests/test_sandbox/`.
- If a selected sandbox-relevant test fails because of this work, fix the implementation code or the explicitly migrated sandbox-semantic test.
- The final handoff must list exactly which tests were run, which passed, and any unrelated known failures that were observed.

---

### Task 0: Worktree And Test Selection Check

**Files:**
- No file changes.

- [ ] **Step 1: Verify worktree**

Run:

```bash
git status --short
```

Expected: either no output, or only user-owned changes unrelated to this implementation. If there are unrelated user changes, do not touch them.

- [ ] **Step 2: Decide the first task's tests**

Choose tests based on the next task's touched files. For Task 1, a good first command after writing the test is:

```bash
uv run pytest tests/test_sandbox/test_run_modes.py -q
```

Expected: this command initially fails before implementation and passes after Task 1 implementation.

- [ ] **Step 3: Commit**

No commit is required for Task 0. Runtime code must not change in this task.

---

### Task 1: Add Core Run Mode Vocabulary

**Files:**
- Create: `src/opensquilla/sandbox/run_mode.py`
- Modify: `src/opensquilla/sandbox/config.py`
- Modify: `src/opensquilla/sandbox/status.py`
- Modify: `src/opensquilla/permissions.py`
- Test: `tests/test_sandbox/test_run_modes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sandbox/test_run_modes.py`:

```python
from __future__ import annotations

import types

from opensquilla.sandbox.run_mode import (
    RunMode,
    approval_behavior,
    execution_target,
    legacy_state_to_run_mode,
    normalize_run_mode,
    run_mode_config_patch,
)


def test_trusted_sandbox_is_sandboxed_and_skips_only_routine_prompts() -> None:
    patch = run_mode_config_patch(RunMode.TRUSTED)

    assert patch.sandbox is True
    assert patch.security_grading is True
    assert patch.permissions_default_mode == "off"
    assert execution_target(RunMode.TRUSTED) == "sandbox"
    assert approval_behavior(RunMode.TRUSTED) == "trusted"


def test_full_host_access_is_the_only_global_host_target() -> None:
    assert execution_target(RunMode.STANDARD) == "sandbox"
    assert execution_target(RunMode.TRUSTED) == "sandbox"
    assert execution_target(RunMode.FULL) == "host"


def test_legacy_bypass_state_maps_to_trusted_without_preserving_host_bypass() -> None:
    mode = legacy_state_to_run_mode(
        sandbox_enabled=False,
        grading_enabled=False,
        permissions_default_mode="bypass",
    )

    assert mode == RunMode.TRUSTED


def test_configured_default_elevated_only_returns_full() -> None:
    from opensquilla.permissions import configured_default_elevated, configured_default_run_mode

    config = types.SimpleNamespace(
        sandbox=types.SimpleNamespace(run_mode="trusted", sandbox=True, security_grading=True),
        permissions=types.SimpleNamespace(default_mode="off"),
    )

    assert configured_default_run_mode(config) == RunMode.TRUSTED
    assert configured_default_elevated(config) is None

    config.sandbox.run_mode = "full"
    assert configured_default_run_mode(config) == RunMode.FULL
    assert configured_default_elevated(config) == "full"


def test_normalize_run_mode_accepts_user_facing_spellings() -> None:
    assert normalize_run_mode("standard-sandbox") == RunMode.STANDARD
    assert normalize_run_mode("trusted") == RunMode.TRUSTED
    assert normalize_run_mode("full-host-access") == RunMode.FULL
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_run_modes.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'opensquilla.sandbox.run_mode'`.

- [ ] **Step 3: Add run-mode core module**

Create `src/opensquilla/sandbox/run_mode.py`:

```python
"""User-facing sandbox run-mode vocabulary.

This module is the compatibility boundary between old permission posture
strings and the new product model:

* Standard-Sandbox: sandbox execution, ordinary risky actions ask.
* Trusted-Sandbox: sandbox execution, routine prompts skipped, boundaries ask.
* Full Host Access: host execution, no per-command prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class RunMode(StrEnum):
    STANDARD = "standard"
    TRUSTED = "trusted"
    FULL = "full"


ExecutionTarget = Literal["sandbox", "host"]
ApprovalBehavior = Literal["standard", "trusted", "full"]


@dataclass(frozen=True)
class RunModeConfigPatch:
    sandbox: bool
    security_grading: bool
    permissions_default_mode: Literal["off", "full"]


_ALIASES: dict[str, RunMode] = {
    "on": RunMode.STANDARD,
    "off": RunMode.STANDARD,
    "standard": RunMode.STANDARD,
    "standard-sandbox": RunMode.STANDARD,
    "standard_sandbox": RunMode.STANDARD,
    "trust": RunMode.TRUSTED,
    "trusted": RunMode.TRUSTED,
    "trusted-sandbox": RunMode.TRUSTED,
    "trusted_sandbox": RunMode.TRUSTED,
    "full": RunMode.FULL,
    "full-host-access": RunMode.FULL,
    "full_host_access": RunMode.FULL,
}


def normalize_run_mode(value: Any, *, default: RunMode = RunMode.STANDARD) -> RunMode:
    if isinstance(value, RunMode):
        return value
    raw = str(value if value is not None else default.value).strip().lower()
    if raw in _ALIASES:
        return _ALIASES[raw]
    allowed = ", ".join(sorted(_ALIASES))
    raise ValueError(f"run mode must be one of: {allowed}")


def display_name(mode: RunMode | str) -> str:
    resolved = normalize_run_mode(mode)
    return {
        RunMode.STANDARD: "Standard-Sandbox",
        RunMode.TRUSTED: "Trusted-Sandbox",
        RunMode.FULL: "Full Host Access",
    }[resolved]


def execution_target(mode: RunMode | str) -> ExecutionTarget:
    return "host" if normalize_run_mode(mode) is RunMode.FULL else "sandbox"


def approval_behavior(mode: RunMode | str) -> ApprovalBehavior:
    resolved = normalize_run_mode(mode)
    if resolved is RunMode.TRUSTED:
        return "trusted"
    if resolved is RunMode.FULL:
        return "full"
    return "standard"


def run_mode_config_patch(mode: RunMode | str) -> RunModeConfigPatch:
    resolved = normalize_run_mode(mode)
    if resolved is RunMode.FULL:
        return RunModeConfigPatch(
            sandbox=False,
            security_grading=False,
            permissions_default_mode="full",
        )
    return RunModeConfigPatch(
        sandbox=True,
        security_grading=True,
        permissions_default_mode="off",
    )


def legacy_state_to_run_mode(
    *,
    sandbox_enabled: bool,
    grading_enabled: bool,
    permissions_default_mode: Any,
) -> RunMode:
    raw = str(permissions_default_mode or "off").strip().lower()
    if raw == "full":
        return RunMode.FULL
    if raw == "bypass":
        return RunMode.TRUSTED
    if sandbox_enabled and grading_enabled:
        return RunMode.STANDARD
    if raw in {"off", "restricted", "on"}:
        return RunMode.STANDARD
    return RunMode.STANDARD


def config_run_mode(config: Any) -> RunMode:
    sandbox = getattr(config, "sandbox", None)
    explicit = getattr(sandbox, "run_mode", None)
    if explicit:
        return normalize_run_mode(explicit)
    permissions = getattr(config, "permissions", None)
    return legacy_state_to_run_mode(
        sandbox_enabled=bool(getattr(sandbox, "sandbox", False)),
        grading_enabled=bool(getattr(sandbox, "security_grading", False)),
        permissions_default_mode=getattr(permissions, "default_mode", "off"),
    )


__all__ = [
    "ApprovalBehavior",
    "ExecutionTarget",
    "RunMode",
    "RunModeConfigPatch",
    "approval_behavior",
    "config_run_mode",
    "display_name",
    "execution_target",
    "legacy_state_to_run_mode",
    "normalize_run_mode",
    "run_mode_config_patch",
]
```

- [ ] **Step 4: Add config field**

Modify `src/opensquilla/sandbox/config.py`:

```python
BackendName = Literal["auto", "bubblewrap", "seatbelt", "windows_restricted_token", "noop"]
RunModeName = Literal["standard", "trusted", "full"]
```

Add to `SandboxSettings`:

```python
    run_mode: RunModeName | None = None
```

Add `"RunModeName"` to `__all__`.

- [ ] **Step 5: Update status payload**

Modify `src/opensquilla/sandbox/status.py` so `status_payload()` includes `run_mode`, `run_mode_label`, and `execution_target`. Keep `posture` only as a legacy field:

```python
from opensquilla.sandbox.run_mode import config_run_mode, display_name, execution_target


def posture(config: Any) -> str:
    return config_run_mode(config).value


def status_payload(config: Any, *, restart_required: bool = False) -> dict[str, Any]:
    mode = config_run_mode(config)
    return {
        "run_mode": mode.value,
        "run_mode_label": display_name(mode),
        "execution_target": execution_target(mode),
        "posture": mode.value,
        "sandbox": {
            "sandbox": bool(config.sandbox.sandbox),
            "security_grading": bool(config.sandbox.security_grading),
            "run_mode": getattr(config.sandbox, "run_mode", None),
        },
        "permissions": {
            "default_mode": str(config.permissions.default_mode),
        },
        "restart_required": restart_required,
    }
```

- [ ] **Step 6: Update permission defaults helper**

Modify `src/opensquilla/permissions.py`:

```python
from opensquilla.sandbox.run_mode import RunMode, config_run_mode


def configured_default_run_mode(config: Any) -> RunMode:
    return config_run_mode(config)


def configured_default_elevated(config: Any) -> str | None:
    mode = configured_default_run_mode(config)
    return "full" if mode is RunMode.FULL else None
```

Keep `normalize_permission_mode()` for old config parsing; do not let `bypass` create host execution.

- [ ] **Step 7: Run test**

Run:

```bash
uv run pytest tests/test_sandbox/test_run_modes.py -q
```

Expected: PASS.

- [ ] **Step 8: Run focused existing tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_policy_network.py tests/test_sandbox/test_windows_auto_backend.py -q
```

Expected: PASS. If failures are due to new run-mode field serialization, fix implementation code.

- [ ] **Step 9: Commit**

Run:

```bash
git add tests/test_sandbox/test_run_modes.py src/opensquilla/sandbox/run_mode.py src/opensquilla/sandbox/config.py src/opensquilla/sandbox/status.py src/opensquilla/permissions.py
git commit -m "feat: add sandbox run mode core"
```

---

### Task 2: Migrate Sandbox CLI Commands

**Files:**
- Modify: `src/opensquilla/cli/sandbox_cmd.py`
- Modify: `tests/test_cli/test_sandbox_cmd.py`
- Test: `tests/test_sandbox/test_cli_run_modes.py`

- [ ] **Step 1: Write CLI behavior tests**

Create `tests/test_sandbox/test_cli_run_modes.py`:

```python
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.onboarding.config_store import load_config


runner = CliRunner()


def _invoke(config_path: Path, *args: str):
    return runner.invoke(app, ["sandbox", *args, "--config", str(config_path)])


def test_sandbox_trust_keeps_runtime_sandbox_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = _invoke(config_path, "trust")

    assert result.exit_code == 0, result.output
    cfg = load_config(config_path)
    assert cfg.sandbox.run_mode == "trusted"
    assert cfg.sandbox.sandbox is True
    assert cfg.sandbox.security_grading is True
    assert cfg.permissions.default_mode == "off"


def test_sandbox_bypass_fails_without_changing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    before = _invoke(config_path, "on")
    assert before.exit_code == 0, before.output

    result = _invoke(config_path, "bypass")

    assert result.exit_code != 0
    assert "removed" in result.output.lower()
    assert "sandbox trust" in result.output
    cfg = load_config(config_path)
    assert cfg.sandbox.run_mode == "standard"
    assert cfg.sandbox.sandbox is True


def test_sandbox_reset_restores_standard_sandbox(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    assert _invoke(config_path, "full").exit_code == 0

    reset = _invoke(config_path, "reset")

    assert reset.exit_code == 0, reset.output
    cfg = load_config(config_path)
    assert cfg.sandbox.run_mode == "standard"
    assert cfg.sandbox.sandbox is True
    assert cfg.permissions.default_mode == "off"


def test_sandbox_status_reports_run_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    assert _invoke(config_path, "trust").exit_code == 0

    result = runner.invoke(app, ["sandbox", "status", "--config", str(config_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_mode"] == "trusted"
    assert payload["run_mode_label"] == "Trusted-Sandbox"
    assert payload["execution_target"] == "sandbox"

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["sandbox"]["run_mode"] == "trusted"
```

- [ ] **Step 2: Run tests to verify current failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_cli_run_modes.py -q
```

Expected: FAIL because `trust` is not implemented and `bypass` still succeeds.

- [ ] **Step 3: Implement CLI run-mode writer**

In `src/opensquilla/cli/sandbox_cmd.py`:

- Replace `_apply_posture()` with `_apply_run_mode()`.
- Add `trust` command.
- Change `bypass` command into a failing migration message.
- Change `reset` to `on`.

Use this structure:

```python
from opensquilla.sandbox.run_mode import RunMode, display_name, normalize_run_mode, run_mode_config_patch


def _apply_run_mode(config: Any, mode: RunMode) -> Any:
    patch = run_mode_config_patch(mode)
    config.sandbox.run_mode = mode.value
    config.sandbox.sandbox = patch.sandbox
    config.sandbox.security_grading = patch.security_grading
    config.permissions.default_mode = patch.permissions_default_mode
    return config


def _write_run_mode(config_path: Path | None, mode: RunMode) -> None:
    target = _resolve_path(config_path)
    config = _apply_run_mode(load_config(target), mode)
    persist_config(config, path=target, restart_required=True)
    payload = _status_payload(config, restart_required=True)
    typer.echo(
        "Sandbox run mode set to "
        f"{payload['run_mode_label']}. Restart the gateway for running processes to apply it."
    )
```

`bypass` command body:

```python
@sandbox_app.command("bypass", hidden=True)
def sandbox_bypass(config_path: Path | None = typer.Option(None, "--config")) -> None:
    """Removed legacy command."""

    typer.echo(
        "`sandbox bypass` was removed because it used to disable sandboxing.\n"
        "Use `opensquilla sandbox trust` to stay sandboxed with fewer prompts,\n"
        "or `opensquilla sandbox full` for full host access.",
        err=True,
    )
    raise typer.Exit(2)
```

- [ ] **Step 4: Update existing CLI tests that lock old sandbox semantics**

Modify only `tests/test_cli/test_sandbox_cmd.py`. It is allowed because it explicitly asserts old sandbox/bypass semantics.

Replace old bypass/default tests with:

```python
def test_sandbox_status_reports_standard_run_mode_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        ["sandbox", "status", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_mode"] in {"standard", "trusted"}
    assert payload["execution_target"] == "sandbox"
    assert payload["restart_required"] is False
```

Add:

```python
def test_sandbox_trust_persists_trusted_sandbox_posture(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = _invoke(config_path, "trust")

    assert result.exit_code == 0, result.output
    cfg = load_config(config_path)
    assert cfg.sandbox.run_mode == "trusted"
    assert cfg.sandbox.sandbox is True
    assert cfg.sandbox.security_grading is True
    assert cfg.permissions.default_mode == "off"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["sandbox"]["run_mode"] == "trusted"
    assert data["sandbox"]["sandbox"] is True
    assert data["permissions"]["default_mode"] == "off"
```

Add:

```python
def test_sandbox_bypass_is_removed_and_does_not_mutate_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    assert _invoke(config_path, "on").exit_code == 0

    result = _invoke(config_path, "bypass")

    assert result.exit_code != 0
    assert "removed" in result.output.lower()
    cfg = load_config(config_path)
    assert cfg.sandbox.run_mode == "standard"
    assert cfg.sandbox.sandbox is True
    assert cfg.permissions.default_mode == "off"
```

Change reset assertion to standard sandbox:

```python
assert cfg.sandbox.run_mode == "standard"
assert cfg.sandbox.sandbox is True
assert cfg.sandbox.security_grading is True
assert cfg.permissions.default_mode == "off"
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_cli_run_modes.py tests/test_cli/test_sandbox_cmd.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_sandbox/test_cli_run_modes.py src/opensquilla/cli/sandbox_cmd.py tests/test_cli/test_sandbox_cmd.py
git commit -m "feat: migrate sandbox cli run modes"
```

---

### Task 3: Add Session Run Context Persistence And RPC

**Files:**
- Create: `src/opensquilla/sandbox/run_context.py`
- Create: `src/opensquilla/gateway/rpc_sandbox.py`
- Modify: `src/opensquilla/gateway/rpc/__init__.py`
- Modify: `src/opensquilla/gateway/rpc_sessions.py`
- Modify: `src/opensquilla/gateway/routing.py`
- Modify: `src/opensquilla/tools/types.py`
- Test: `tests/test_sandbox/test_run_context.py`

- [ ] **Step 1: Write Run Context tests**

Create `tests/test_sandbox/test_run_context.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.sandbox.run_mode import RunMode


class _SessionManager:
    def __init__(self):
        self.node = SimpleNamespace(
            session_key="agent:main:webchat:abc",
            origin=None,
        )

    async def get_session(self, session_key: str):
        return self.node if session_key == self.node.session_key else None

    async def update(self, session_key: str, **fields):
        for key, value in fields.items():
            setattr(self.node, key, value)
        return self.node


@pytest.mark.asyncio
async def test_run_context_initializes_from_global_default_and_persists_override() -> None:
    from opensquilla.sandbox.run_context import get_run_context, set_run_mode

    manager = _SessionManager()
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )

    ctx = await get_run_context(manager, manager.node.session_key, config=config, workspace="/tmp/ws")
    assert ctx.run_mode == RunMode.STANDARD
    assert ctx.source == "default"

    updated = await set_run_mode(manager, manager.node.session_key, RunMode.TRUSTED, config=config)
    assert updated.run_mode == RunMode.TRUSTED
    assert manager.node.origin["sandbox_run_context"]["run_mode"] == "trusted"


@pytest.mark.asyncio
async def test_saved_context_wins_over_later_global_default() -> None:
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {"sandbox_run_context": {"run_mode": "standard", "workspace": "/tmp/old"}}
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="full", sandbox=False, security_grading=False),
        permissions=SimpleNamespace(default_mode="full"),
    )

    ctx = await get_run_context(manager, manager.node.session_key, config=config, workspace="/tmp/new")

    assert ctx.run_mode == RunMode.STANDARD
    assert ctx.workspace == "/tmp/old"
    assert ctx.source == "saved"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_run_context.py -q
```

Expected: FAIL because `opensquilla.sandbox.run_context` does not exist.

- [ ] **Step 3: Create Run Context module**

Create `src/opensquilla/sandbox/run_context.py`:

```python
"""Session-scoped sandbox Run Context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from opensquilla.sandbox.run_mode import RunMode, config_run_mode, normalize_run_mode

RUN_CONTEXT_ORIGIN_KEY = "sandbox_run_context"


@dataclass(frozen=True)
class MountGrant:
    path: str
    access: Literal["ro", "rw"] = "ro"
    scope: Literal["chat", "workspace"] = "chat"


@dataclass(frozen=True)
class DomainGrant:
    domain: str
    scope: Literal["chat", "workspace"] = "chat"
    source: Literal["manual", "approved"] = "manual"


@dataclass(frozen=True)
class RunContext:
    run_mode: RunMode
    workspace: str | None = None
    mounts: tuple[MountGrant, ...] = field(default_factory=tuple)
    domains: tuple[DomainGrant, ...] = field(default_factory=tuple)
    source: Literal["saved", "default", "migration"] = "default"

    def to_origin_payload(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode.value,
            "workspace": self.workspace,
            "mounts": [grant.__dict__ for grant in self.mounts],
            "domains": [grant.__dict__ for grant in self.domains],
        }


def _origin_dict(node: Any) -> dict[str, Any]:
    origin = getattr(node, "origin", None)
    return dict(origin) if isinstance(origin, dict) else {}


def _context_from_payload(payload: Any, *, source: str) -> RunContext | None:
    if not isinstance(payload, dict):
        return None
    try:
        mode = normalize_run_mode(payload.get("run_mode"))
    except ValueError:
        return None
    mounts = tuple(
        MountGrant(
            path=str(item.get("path")),
            access="rw" if item.get("access") == "rw" else "ro",
            scope="workspace" if item.get("scope") == "workspace" else "chat",
        )
        for item in payload.get("mounts", [])
        if isinstance(item, dict) and item.get("path")
    )
    domains = tuple(
        DomainGrant(
            domain=str(item.get("domain")),
            scope="workspace" if item.get("scope") == "workspace" else "chat",
            source="approved" if item.get("source") == "approved" else "manual",
        )
        for item in payload.get("domains", [])
        if isinstance(item, dict) and item.get("domain")
    )
    return RunContext(
        run_mode=mode,
        workspace=str(payload["workspace"]) if payload.get("workspace") else None,
        mounts=mounts,
        domains=domains,
        source="saved" if source == "saved" else "migration",
    )


async def get_run_context(
    session_manager: Any,
    session_key: str,
    *,
    config: Any,
    workspace: str | None,
) -> RunContext:
    get_session = getattr(session_manager, "get_session", None)
    node = await get_session(session_key) if callable(get_session) else None
    if node is not None:
        origin = _origin_dict(node)
        saved = _context_from_payload(origin.get(RUN_CONTEXT_ORIGIN_KEY), source="saved")
        if saved is not None:
            return saved
    return RunContext(run_mode=config_run_mode(config), workspace=workspace, source="default")


async def persist_run_context(session_manager: Any, session_key: str, context: RunContext) -> RunContext:
    get_session = getattr(session_manager, "get_session", None)
    update = getattr(session_manager, "update", None)
    if not callable(get_session) or not callable(update):
        return context
    node = await get_session(session_key)
    if node is None:
        return context
    origin = _origin_dict(node)
    origin[RUN_CONTEXT_ORIGIN_KEY] = context.to_origin_payload()
    await update(session_key, origin=origin)
    return context


async def set_run_mode(
    session_manager: Any,
    session_key: str,
    run_mode: RunMode | str,
    *,
    config: Any,
) -> RunContext:
    current = await get_run_context(session_manager, session_key, config=config, workspace=None)
    updated = RunContext(
        run_mode=normalize_run_mode(run_mode),
        workspace=current.workspace,
        mounts=current.mounts,
        domains=current.domains,
        source="saved",
    )
    return await persist_run_context(session_manager, session_key, updated)


__all__ = [
    "DomainGrant",
    "MountGrant",
    "RUN_CONTEXT_ORIGIN_KEY",
    "RunContext",
    "get_run_context",
    "persist_run_context",
    "set_run_mode",
]
```

- [ ] **Step 4: Add ToolContext fields**

Modify `src/opensquilla/tools/types.py`:

```python
    # Sandbox Run Context. New code should use this instead of elevated.
    # Values: "standard", "trusted", "full".
    run_mode: str | None = None
    sandbox_mounts: list[dict[str, Any]] = field(default_factory=list)
    host_once: bool = False
```

Keep `elevated` for compatibility, but update its comment:

```python
    # Legacy elevated mode. Only "full" should imply host execution in new code.
```

- [ ] **Step 5: Build run mode into route metadata and ToolContext**

Modify `src/opensquilla/gateway/routing.py`:

- Add `run_mode: str | None = None` to `build_cli_route_envelope()`.
- Store `metadata["run_mode"] = run_mode` when it is one of `standard|trusted|full`.
- In `tool_context_from_envelope()`, resolve:

```python
    from opensquilla.sandbox.run_mode import RunMode, normalize_run_mode

    run_mode_value = envelope.metadata.get("run_mode")
    try:
        run_mode = normalize_run_mode(run_mode_value).value if run_mode_value else None
    except ValueError:
        run_mode = None
    elevated = envelope.metadata.get("elevated") or default_elevated
    if elevated == "full" and is_owner:
        run_mode = RunMode.FULL.value
    if elevated != "full" or not is_owner:
        elevated = None
```

Pass `run_mode=run_mode` into `ToolContext`.

- [ ] **Step 6: Add sandbox RPC module**

Create `src/opensquilla/gateway/rpc_sandbox.py`:

```python
"""Sandbox Run Context RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.sandbox.run_context import get_run_context, set_run_mode
from opensquilla.sandbox.run_mode import display_name, execution_target, normalize_run_mode

_d = get_dispatcher()


def _payload(context) -> dict[str, Any]:
    return {
        "runMode": context.run_mode.value,
        "runModeLabel": display_name(context.run_mode),
        "executionTarget": execution_target(context.run_mode),
        "workspace": context.workspace,
        "mounts": [grant.__dict__ for grant in context.mounts],
        "domains": [grant.__dict__ for grant in context.domains],
        "source": context.source,
    }


@_d.method("sandbox.run_context.get", scope="operator.read")
async def _handle_sandbox_run_context_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or not params.get("sessionKey"):
        raise ValueError("params.sessionKey is required")
    if ctx.session_manager is None:
        raise RuntimeError("session manager unavailable")
    context = await get_run_context(
        ctx.session_manager,
        str(params["sessionKey"]),
        config=ctx.config,
        workspace=None,
    )
    return _payload(context)


@_d.method("sandbox.run_context.set", scope="operator.write")
async def _handle_sandbox_run_context_set(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or not params.get("sessionKey"):
        raise ValueError("params.sessionKey is required")
    if not ctx.principal.is_owner:
        raise PermissionError("owner privileges required")
    if ctx.session_manager is None:
        raise RuntimeError("session manager unavailable")
    run_mode = normalize_run_mode(params.get("runMode"))
    context = await set_run_mode(
        ctx.session_manager,
        str(params["sessionKey"]),
        run_mode,
        config=ctx.config,
    )
    return _payload(context)
```

Modify `src/opensquilla/gateway/rpc/__init__.py`:

```python
import opensquilla.gateway.rpc_sandbox  # noqa: E402, F401
```

- [ ] **Step 7: Resolve context inside `sessions.send`**

Modify `src/opensquilla/gateway/rpc_sessions.py` near route-envelope construction:

```python
from opensquilla.sandbox.run_context import get_run_context
```

After session exists and before `tool_context_from_envelope()`:

```python
run_context = await get_run_context(
    ctx.session_manager,
    key,
    config=ctx.config,
    workspace=str(workspace_dir) if "workspace_dir" in locals() else None,
)
route_envelope.metadata["run_mode"] = run_context.run_mode.value
route_envelope.metadata["sandbox_mounts"] = [grant.__dict__ for grant in run_context.mounts]
```

If `_source.runMode` is present and owner-owned, update Run Context through `set_run_mode()` before building the route.

- [ ] **Step 8: Run tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_run_context.py -q
```

Expected: PASS.

- [ ] **Step 9: Run focused gateway tests**

Run:

```bash
uv run pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_chat_clarify_submit.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add tests/test_sandbox/test_run_context.py src/opensquilla/sandbox/run_context.py src/opensquilla/gateway/rpc_sandbox.py src/opensquilla/gateway/rpc/__init__.py src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/routing.py src/opensquilla/tools/types.py
git commit -m "feat: add sandbox session run context"
```

---

### Task 4: Fix Approval, Shell, And Host Once Semantics

**Files:**
- Modify: `src/opensquilla/application/approval_queue.py`
- Modify: `src/opensquilla/application/approval_rpc.py`
- Modify: `src/opensquilla/gateway/app.py`
- Modify: `src/opensquilla/gateway/rpc_approvals.py`
- Modify: `src/opensquilla/tools/builtin/shell.py`
- Modify: `src/opensquilla/tools/builtin/code_exec.py`
- Test: `tests/test_sandbox/test_trusted_sandbox_execution.py`

- [ ] **Step 1: Write behavior tests**

Create `tests/test_sandbox/test_trusted_sandbox_execution.py`:

```python
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_trusted_sandbox_does_not_mark_shell_host_elevated(monkeypatch) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[tuple[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "check_safe_bin", lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""))

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.WEB, session_key="s1", run_mode="trusted")
    )
    try:
        result = await shell.exec_command("echo hi")
    finally:
        current_tool_context.reset(token)

    assert "sandboxed" in result
    assert [name for name, _ in calls] == ["gate", "backend"]


@pytest.mark.asyncio
async def test_ordinary_approval_result_does_not_carry_elevated_mode(monkeypatch) -> None:
    from opensquilla.application.approval_queue import ApprovalQueue

    queue = ApprovalQueue(db_path=":memory:")
    try:
        approval_id = queue.request(namespace="exec", params={"sessionKey": "s1", "command": "rm x"})
        queue.resolve(approval_id, True)
        status = queue.status(approval_id)
        assert "elevatedMode" not in status["params"]
    finally:
        queue.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_trusted_sandbox_execution.py -q
```

Expected: FAIL because old shell approval/elevated code still treats bypass/trust as host elevation.

- [ ] **Step 3: Add run-mode storage to ApprovalQueue**

In `src/opensquilla/application/approval_queue.py`:

- Add:

```python
VALID_RUN_MODES = frozenset({"standard", "trusted", "full"})
```

- Add `self._session_run_modes: dict[str, str] = {}`.
- Add:

```python
    def set_run_mode(self, session_key: str, mode: str | None) -> None:
        key = session_key.strip()
        if not key:
            raise ValueError("session_key is required")
        if mode in (None, "", "off"):
            self._session_run_modes.pop(key, None)
            return
        if mode not in VALID_RUN_MODES:
            raise ValueError("mode must be one of: standard, trusted, full")
        self._session_run_modes[key] = mode

    def get_run_mode(self, session_key: str | None) -> str | None:
        key = (session_key or "").strip()
        if not key:
            return None
        return self._session_run_modes.get(key)
```

- Keep `set_elevated_mode()` and `get_elevated_mode()` only as legacy wrappers:

```python
    def set_elevated_mode(self, session_key: str, mode: str | None) -> None:
        if mode == "full":
            self.set_run_mode(session_key, "full")
        elif mode in ("bypass", "on"):
            self.set_run_mode(session_key, "trusted")
        else:
            self.set_run_mode(session_key, None)

    def get_elevated_mode(self, session_key: str | None) -> str | None:
        mode = self.get_run_mode(session_key)
        return "full" if mode == "full" else None
```

- Remove the `if approved and elevated_mode in VALID_ELEVATED_MODES` branch from ordinary `resolve()`. Ordinary approval must not change execution target.

- [ ] **Step 4: Stop accepting elevatedMode on ordinary approval RPC**

In `src/opensquilla/gateway/app.py`, remove:

```python
if namespace != "plugin" and body.get("elevatedMode") in ("on", "bypass", "full"):
    resolve_params["elevatedMode"] = body.get("elevatedMode")
```

In `src/opensquilla/gateway/rpc_approvals.py`, remove elevated-mode extraction and pass `elevated_mode=None` to `approval_resolve_rpc_payload()`.

In `src/opensquilla/application/approval_rpc.py`, keep the parameter for compatibility but do not persist it for ordinary approval.

- [ ] **Step 5: Replace shell elevated checks with run-mode checks**

In `src/opensquilla/tools/builtin/shell.py`:

- Rename `_elevate_current_call` to `_host_once_current_call`.
- Add:

```python
from opensquilla.sandbox.run_mode import RunMode, normalize_run_mode


def _context_run_mode() -> RunMode:
    ctx = current_tool_context.get()
    if ctx is not None and ctx.run_mode:
        return normalize_run_mode(ctx.run_mode)
    if ctx is not None and ctx.session_key:
        with contextlib.suppress(Exception):
            mode = get_approval_queue().get_run_mode(ctx.session_key)
            if mode:
                return normalize_run_mode(mode)
    if ctx is not None and ctx.elevated == "full":
        return RunMode.FULL
    return RunMode.STANDARD


def _host_execution_allowed() -> bool:
    if _host_once_current_call.get():
        _host_once_current_call.set(False)
        return True
    return _context_run_mode() is RunMode.FULL


def _trusted_sandbox_mode() -> bool:
    return _context_run_mode() is RunMode.TRUSTED
```

- Replace `elevated_bypass = _elevated_mode() in ("on", "bypass", "full")` with:

```python
host_execution = _host_execution_allowed()
```

- Sandbox branch should run when runtime sandbox is enabled and `not host_execution`.
- Host branch should log `shell_exec_full_host` only when run mode is full or Host Once.

- [ ] **Step 6: Change `_check_exec_approval()`**

Rules:

- Sensitive path block still runs unless `RunMode.FULL`.
- `Trusted-Sandbox` skips warnlist approval and returns `None`, but does not set host execution.
- `Full Host Access` skips approval and sets host execution.
- Ordinary approval returns `None`, but does not set host execution.
- Intent-cache and auto-approve skip ordinary approval only; they do not set host execution.

Key replacements:

```python
run_mode = _context_run_mode()
full_host = run_mode is RunMode.FULL
trusted_sandbox = run_mode is RunMode.TRUSTED
```

When trusted:

```python
if trusted_sandbox:
    log.info(
        "shell_approval_skipped_trusted_sandbox",
        command=_audit_command(command),
        tool=tool_name,
    )
    return None
```

When full:

```python
if full_host:
    _host_once_current_call.set(True)
    return None
```

After an ordinary approved queue entry, remove `_host_once_current_call.set(True)`.

- [ ] **Step 7: Make backend denial escalation explicitly Host Once**

In `src/opensquilla/sandbox/integration.py`, change approval params in `escalate_backend_denial()` to include:

```python
reason=f"host once requested after sandbox denied: {notes_str}"
```

and params should include `"approvalKind": "host_once"` through `ApprovalGate.gate()`. If `ApprovalGate` cannot pass that field today, add optional `extra_params` to `ApprovalGate.gate()` and thread it through.

In `shell.py`, after `escalate_backend_denial()` returns `ALLOW`, set `_host_once_current_call.set(True)` immediately before the one host rerun. Do not persist anything in the session.

- [ ] **Step 8: Align code execution**

In `src/opensquilla/tools/builtin/code_exec.py`:

- Replace `_context_elevated_mode() != "full"` sensitive checks with `ToolContext.run_mode != "full"`.
- Destructive Python approval must not imply host execution.
- Keep actual Python subprocess sandboxed when runtime sandbox is enabled and run mode is standard/trusted.

- [ ] **Step 9: Run selected tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_trusted_sandbox_execution.py tests/test_sandbox/test_escalate_backend_denial.py tests/test_gateway/test_rpc_approvals.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add tests/test_sandbox/test_trusted_sandbox_execution.py src/opensquilla/application/approval_queue.py src/opensquilla/application/approval_rpc.py src/opensquilla/gateway/app.py src/opensquilla/gateway/rpc_approvals.py src/opensquilla/tools/builtin/shell.py src/opensquilla/tools/builtin/code_exec.py src/opensquilla/sandbox/integration.py
git commit -m "feat: keep trusted sandbox approvals sandboxed"
```

---

### Task 5: Migrate Chat And Approval Frontend Surfaces

**Files:**
- Modify: `src/opensquilla/gateway/static/js/views/chat.js`
- Modify: `src/opensquilla/gateway/static/js/views/approvals.js`
- Modify: `src/opensquilla/gateway/static/js/approval_monitor.js`
- Modify: `src/opensquilla/gateway/static/js/views/config.js`
- Modify: `src/opensquilla/gateway/static/css/views/chat.css`
- Modify: `tests/test_gateway/test_chat_static_assets.py`

- [ ] **Step 1: Update old frontend static tests**

Modify only `tests/test_gateway/test_chat_static_assets.py`; this file explicitly locks old bypass UI and is allowed to change.

First add the config asset helper near the existing path constants:

```python
CONFIG_JS = Path("src/opensquilla/gateway/static/js/views/config.js")
```

and add the reader near the other `_read_*` helpers:

```python
def _read_config_js() -> str:
    return CONFIG_JS.read_text(encoding="utf-8")
```

Then replace `test_chat_permission_pill_distinguishes_global_and_session_modes()` with:

```python
def test_chat_run_mode_control_replaces_elevated_bypass_copy() -> None:
    chat_source = _read_chat_js()
    config_source = _read_config_js()

    assert '<span class="chat-toolbar-row-label">Run Mode</span>' in chat_source
    assert '<span class="chat-toolbar-row-label">Execution mode</span>' not in chat_source
    assert "sandbox.run_context.get" in chat_source
    assert "sandbox.run_context.set" in chat_source
    assert "Standard-Sandbox" in chat_source
    assert "Trusted-Sandbox" in chat_source
    assert "Full Host Access" in chat_source
    assert "opensquilla sandbox on|trust|full|reset" in config_source
    assert "This maps to /elevated bypass" not in chat_source
```

Replace `test_webui_bypass_shortcuts_do_not_enable_full_mode()` with:

```python
def test_webui_removes_bypass_approval_shortcuts() -> None:
    chat_source = _read_chat_js()
    monitor_source = _read_approval_monitor_js()
    approvals_source = _read_approvals_js()
    combined = "\n".join([chat_source, monitor_source, approvals_source])

    assert "Bypass Approvals" not in combined
    assert "Bypass approvals" not in combined
    assert "data-approval-action=\"bypass\"" not in combined
    assert "data-decision=\"bypass\"" not in combined
    assert "elevatedMode" not in monitor_source
    assert "elevatedMode" not in approvals_source
```

- [ ] **Step 2: Run static tests to verify failure**

Run:

```bash
uv run pytest tests/test_gateway/test_chat_static_assets.py::test_chat_run_mode_control_replaces_elevated_bypass_copy tests/test_gateway/test_chat_static_assets.py::test_webui_removes_bypass_approval_shortcuts -q
```

Expected: FAIL.

- [ ] **Step 3: Replace Chat gear execution row**

In `src/opensquilla/gateway/static/js/views/chat.js`:

- Replace localStorage elevated constants with session run mode state:

```javascript
  let _runMode = 'standard';
  let _runModeSource = 'default';
```

- Replace label `Execution mode` with `Run Mode`.
- Replace single bypass pill with a compact segmented control:

```html
<div class="chat-run-mode-segmented" id="chat-run-mode-group" role="group" aria-label="Run Mode">
  <button class="chat-run-mode-option" data-run-mode="standard" title="Sandboxed execution. Ordinary risky actions ask.">Standard</button>
  <button class="chat-run-mode-option" data-run-mode="trusted" title="Sandboxed execution. Routine approvals are skipped; boundary changes still ask.">Trusted</button>
  <button class="chat-run-mode-option" data-run-mode="full" title="Host execution without per-command prompts.">Full</button>
</div>
```

- Add helpers:

```javascript
  function _normalizeRunMode(mode) {
    return mode === 'trusted' || mode === 'full' || mode === 'standard' ? mode : 'standard';
  }

  async function _loadRunContext() {
    if (!_sessionKey) return;
    const payload = await _rpc.call('sandbox.run_context.get', { sessionKey: _sessionKey });
    _runMode = _normalizeRunMode(payload?.runMode);
    _runModeSource = payload?.source || 'default';
    _updateRunModeControl();
  }

  async function _setRunMode(mode, options = {}) {
    const normalized = _normalizeRunMode(mode);
    _runMode = normalized;
    _updateRunModeControl();
    if (!_sessionKey) return;
    const payload = await _rpc.call('sandbox.run_context.set', {
      sessionKey: _sessionKey,
      runMode: normalized,
    });
    _runMode = _normalizeRunMode(payload?.runMode);
    _runModeSource = payload?.source || 'saved';
    _updateRunModeControl();
    if (options.toast) UI.toast(`Run Mode: ${payload?.runModeLabel || normalized}`, normalized === 'full' ? 'warn' : 'info');
  }
```

- In send params, replace `_source.elevated` with:

```javascript
params._source = { ...(params._source || {}), runMode: _runMode };
```

- [ ] **Step 4: Remove approval bypass actions**

In `src/opensquilla/gateway/static/js/approval_monitor.js`:

- Remove the `Bypass Approvals` button.
- `approved` should be true only for `once` and `always`.
- Do not send `elevatedMode`.

In `src/opensquilla/gateway/static/js/views/approvals.js`:

- Remove the `Bypass approvals` button.
- Do not send `elevatedMode`.
- Effective execution summary should read `runMode` if available; otherwise show neutral "Run Mode is controlled by the current chat".

- [ ] **Step 5: Update config help text**

In `src/opensquilla/gateway/static/js/views/config.js`, replace help strings:

```javascript
'sandbox.sandbox':
  'Runtime sandbox switch. Prefer opensquilla sandbox on|trust|full so sandbox and permission defaults stay aligned.',
'permissions.default_mode':
  'Legacy compatibility field. New user-facing execution posture is sandbox.run_mode: standard, trusted, or full.',
```

- [ ] **Step 6: Update CSS naming without changing layout**

In `src/opensquilla/gateway/static/css/views/chat.css`:

- Keep existing dimensions.
- Rename bypass dot comments/classes to run-mode.
- Full mode may use warning color; trusted may use info/accent color.

- [ ] **Step 7: Run frontend static tests**

Run:

```bash
uv run pytest tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_webui_typography_static.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/opensquilla/gateway/static/js/views/chat.js src/opensquilla/gateway/static/js/views/approvals.js src/opensquilla/gateway/static/js/approval_monitor.js src/opensquilla/gateway/static/js/views/config.js src/opensquilla/gateway/static/css/views/chat.css tests/test_gateway/test_chat_static_assets.py
git commit -m "feat: migrate web ui to sandbox run mode"
```

---

### Task 6: Add External Path Validation And Mount Request First Slice

**Files:**
- Create: `src/opensquilla/sandbox/path_validation.py`
- Modify: `src/opensquilla/sandbox/run_context.py`
- Modify: `src/opensquilla/sandbox/policy.py`
- Modify: `src/opensquilla/sandbox/integration.py`
- Modify: `src/opensquilla/tools/builtin/filesystem.py`
- Modify: `src/opensquilla/tools/builtin/shell.py`
- Test: `tests/test_sandbox/test_path_access.py`

- [ ] **Step 1: Write path validation tests**

Create `tests/test_sandbox/test_path_access.py`:

```python
from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.path_validation import MountDecision, validate_mount_candidate


def test_normal_project_sibling_path_requests_read_only_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "other-project"
    workspace.mkdir()
    sibling.mkdir()

    decision = validate_mount_candidate(str(sibling), workspace=workspace, write=False)

    assert decision.status == "request"
    assert decision.access == "ro"
    assert decision.normalized_path == str(sibling.resolve())


def test_sensitive_ssh_path_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ssh = tmp_path / ".ssh"
    workspace.mkdir()
    ssh.mkdir()

    decision = validate_mount_candidate(str(ssh), workspace=workspace, write=False)

    assert decision.status == "blocked"
    assert "credential" in decision.reason.lower() or "sensitive" in decision.reason.lower()


def test_workspace_path_is_already_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    child = workspace / "src"
    child.mkdir(parents=True)

    decision = validate_mount_candidate(str(child), workspace=workspace, write=True)

    assert decision.status == "allowed"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_path_access.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement path validation module**

Create `src/opensquilla/sandbox/path_validation.py` with:

```python
"""Cross-platform validation for user-requested sandbox mounts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MountStatus = Literal["allowed", "request", "blocked"]
MountAccess = Literal["ro", "rw"]


_SENSITIVE_NAMES = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".config/gcloud",
    ".docker",
    "keychains",
}

_SENSITIVE_PARTS = {
    "credentials",
    "credential",
    "secret",
    "secrets",
    "token",
    "tokens",
}

_POSIX_BLOCKED_ROOTS = {
    "/",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
}


@dataclass(frozen=True)
class MountDecision:
    status: MountStatus
    normalized_path: str | None
    access: MountAccess
    reason: str


def _safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _looks_sensitive(path: Path) -> bool:
    text = path.as_posix().lower()
    if os.name != "nt":
        for root in _POSIX_BLOCKED_ROOTS:
            if text == root or text.startswith(root.rstrip("/") + "/"):
                return True
    parts = [part.lower() for part in path.parts]
    joined_suffixes = {"/".join(parts[index:]) for index in range(len(parts))}
    if any(name in joined_suffixes or name in parts for name in _SENSITIVE_NAMES):
        return True
    return any(part in _SENSITIVE_PARTS for part in parts)


def validate_mount_candidate(
    raw_path: str,
    *,
    workspace: Path,
    write: bool,
) -> MountDecision:
    if not raw_path or not str(raw_path).strip():
        return MountDecision("blocked", None, "ro", "empty path")
    candidate = _safe_resolve(Path(raw_path))
    workspace_resolved = _safe_resolve(workspace)
    access: MountAccess = "rw" if write else "ro"
    if _is_relative_to(candidate, workspace_resolved):
        return MountDecision("allowed", str(candidate), access, "path is already inside workspace")
    if _looks_sensitive(candidate):
        return MountDecision("blocked", str(candidate), "ro", "sensitive path cannot be mounted")
    if candidate.anchor and str(candidate) == candidate.anchor:
        return MountDecision("blocked", str(candidate), "ro", "filesystem root cannot be mounted")
    return MountDecision("request", str(candidate), access, "path requires a sandbox mount")


__all__ = ["MountAccess", "MountDecision", "MountStatus", "validate_mount_candidate"]
```

- [ ] **Step 4: Thread mounts into policy**

Modify `src/opensquilla/sandbox/policy.py`:

- Add optional argument to `build_policy()`:

```python
    session_mounts: tuple[MountSpec, ...] = (),
```

- In `_collect_mounts()`, append validated session mounts after workspace and before config extras. In `STRICT`, downgrade session mounts to read-only unless the operation is a clear write to that mount.

Modify `src/opensquilla/sandbox/integration.py` to read `ToolContext.sandbox_mounts` and convert them into `MountSpec` before `build_policy()`.

- [ ] **Step 5: Return Path Access Request instead of host fallback**

In `src/opensquilla/tools/builtin/filesystem.py`, when a requested absolute path is outside workspace and mounts:

- call `validate_mount_candidate()`;
- if status is `request`, return JSON:

```python
{
    "status": "path_access_required",
    "path": decision.normalized_path,
    "access": decision.access,
    "message": "This path is outside the current sandbox view. Add it as a mount to continue sandboxed.",
}
```

- if status is `blocked`, return JSON:

```python
{
    "status": "blocked",
    "reason": "sensitive_path",
    "path": decision.normalized_path,
    "message": decision.reason,
}
```

In `shell.py`, if `workdir` is outside workspace/mounts, return the same `path_access_required` envelope before attempting host execution.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_path_access.py -q
```

Expected: PASS.

- [ ] **Step 7: Run focused existing sandbox/path tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_sensitive_paths.py tests/test_tools/test_sandbox_network_hint.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add tests/test_sandbox/test_path_access.py src/opensquilla/sandbox/path_validation.py src/opensquilla/sandbox/run_context.py src/opensquilla/sandbox/policy.py src/opensquilla/sandbox/integration.py src/opensquilla/tools/builtin/filesystem.py src/opensquilla/tools/builtin/shell.py
git commit -m "feat: request sandbox mounts for external paths"
```

---

### Task 7: Add Native Windows Restricted-Token Backend

**Files:**
- Create: `src/opensquilla/sandbox/backend/windows_restricted_token.py`
- Create: `src/opensquilla/sandbox/backend/windows_restricted_token_helper.py`
- Modify: `src/opensquilla/sandbox/backend/__init__.py`
- Modify: `src/opensquilla/sandbox/config.py`
- Modify: `src/opensquilla/sandbox/integration.py`
- Modify: `tests/test_sandbox/test_windows_auto_backend.py`
- Test: `tests/test_sandbox/test_windows_restricted_token_backend.py`

- [ ] **Step 1: Write backend selection tests**

Create `tests/test_sandbox/test_windows_restricted_token_backend.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.types import SandboxBackendError


class _FakeApprovalQueue:
    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        return "approval:test"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        return False

    def resolve(self, approval_id: str, approved: bool) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_runtime():
    reset_runtime()
    yield
    reset_runtime()


def test_windows_auto_selects_restricted_token_when_available(monkeypatch, tmp_path: Path) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "win32")
    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(
        backend_mod.WindowsRestrictedTokenBackend,
        "available",
        lambda self: True,
    )

    runtime = configure_runtime(
        SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.backend.name == "windows_restricted_token"
    assert runtime.effective.sandbox_enabled is True


def test_windows_auto_fails_closed_when_restricted_token_unavailable(monkeypatch, tmp_path: Path) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "win32")
    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(
        backend_mod.WindowsRestrictedTokenBackend,
        "available",
        lambda self: False,
    )

    with pytest.raises(SandboxBackendError, match="no real sandbox backend"):
        configure_runtime(
            SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
            approval_queue=_FakeApprovalQueue(),
            workspace=tmp_path,
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_sandbox/test_windows_restricted_token_backend.py -q
```

Expected: FAIL because `WindowsRestrictedTokenBackend` does not exist and current Windows auto disables sandbox.

- [ ] **Step 3: Add backend adapter**

Create `src/opensquilla/sandbox/backend/windows_restricted_token.py`:

```python
"""Native Windows restricted-token sandbox backend."""

from __future__ import annotations

import asyncio
import json
import sys
import time

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.types import SandboxBackendError, SandboxRequest, SandboxResult


class WindowsRestrictedTokenBackend(Backend):
    name = "windows_restricted_token"

    def available(self) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            import ctypes  # noqa: F401
            return True
        except Exception:
            return False

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if not self.available():
            raise SandboxBackendError("windows_restricted_token backend is unavailable")
        payload = {
            "argv": list(request.argv),
            "cwd": str(request.cwd),
            "env": request.env,
            "policy": request.policy.summary(),
            "timeout": request.policy.limits.wall_timeout_s,
        }
        helper_argv = [
            sys.executable,
            "-m",
            "opensquilla.sandbox.backend.windows_restricted_token_helper",
            json.dumps(payload, ensure_ascii=False),
        ]
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *helper_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=max(1.0, request.policy.limits.wall_timeout_s + 2.0),
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return SandboxResult(
                returncode=124,
                stdout="",
                stderr="windows restricted-token helper timed out",
                wall_time_s=time.monotonic() - started,
                backend_used=self.name,
                policy_used=request.policy.summary(),
                timed_out=True,
            )
        return SandboxResult(
            returncode=int(proc.returncode or 0),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            wall_time_s=time.monotonic() - started,
            backend_used=self.name,
            policy_used=request.policy.summary(),
        )
```

- [ ] **Step 4: Add helper skeleton with fail-closed enforcement checks**

Create `src/opensquilla/sandbox/backend/windows_restricted_token_helper.py`.

The first implementation must:

- run only on `sys.platform.startswith("win")`;
- parse one JSON payload argument;
- reject `policy.network == "host"` unless run mode is `Full Host Access`;
- reject missing cwd;
- create process with a restricted token through `ctypes` using `CreateRestrictedToken`;
- attach a Job Object with kill-on-close;
- return non-zero with a clear error if any Win32 enforcement step fails.

Use Codex as the design reference:

- restricted token with capability/restricting SIDs;
- default DACL adjusted to the sandbox SIDs;
- Job Object lifecycle cleanup;
- setup/readiness separate from normal execution.

If the full `CreateRestrictedToken` launch is not complete in the first code pass, the helper must fail closed:

```python
raise SystemExit("windows_restricted_token helper cannot enforce policy on this host")
```

It must never fall back to unsandboxed `subprocess.run()`.

- [ ] **Step 5: Select backend on Windows**

Modify `src/opensquilla/sandbox/backend/__init__.py`:

```python
from opensquilla.sandbox.backend.windows_restricted_token import WindowsRestrictedTokenBackend
```

In `_auto_backend()`:

```python
    if sys.platform.startswith("win"):
        windows_backend = WindowsRestrictedTokenBackend()
        if windows_backend.available():
            return windows_backend
```

In `select_backend()`:

```python
    elif choice == "windows_restricted_token":
        backend = WindowsRestrictedTokenBackend()
```

Add to `__all__`.

- [ ] **Step 6: Remove Windows auto-disable compatibility**

Modify `src/opensquilla/sandbox/integration.py`:

- Delete or disable `_apply_host_compatibility()` behavior that turns Windows sandbox on into sandbox off.
- If Windows backend is unavailable, `select_backend()` must raise and gateway must fail closed for sandbox modes.

- [ ] **Step 7: Update existing Windows backend tests**

Modify `tests/test_sandbox/test_windows_auto_backend.py`:

- Replace `test_windows_auto_backend_disables_sandbox_runtime` with tests matching tests:
  - auto selects `windows_restricted_token` when available;
  - auto fails closed when unavailable.

- Keep macOS and Linux tests unchanged unless import paths require adding the new backend symbol.

- [ ] **Step 8: Run Windows backend tests**

Run:

```bash
uv run pytest tests/test_sandbox/test_windows_restricted_token_backend.py tests/test_sandbox/test_windows_auto_backend.py -q
```

Expected: PASS on non-Windows through monkeypatching. Native Windows smoke testing is manual unless a Windows runner is available.

- [ ] **Step 9: Commit**

Run:

```bash
git add tests/test_sandbox/test_windows_restricted_token_backend.py src/opensquilla/sandbox/backend/windows_restricted_token.py src/opensquilla/sandbox/backend/windows_restricted_token_helper.py src/opensquilla/sandbox/backend/__init__.py src/opensquilla/sandbox/config.py src/opensquilla/sandbox/integration.py tests/test_sandbox/test_windows_auto_backend.py
git commit -m "feat: add windows restricted-token sandbox backend"
```

---

### Task 8: Test Coverage Review

**Files:**
- Modify only if needed: `tests/test_sandbox/*.py`
- Modify only if needed: `tests/test_cli/test_sandbox_cmd.py`
- Modify only if needed: `tests/test_gateway/test_chat_static_assets.py`

- [ ] **Step 1: Review tests added during implementation**

Confirm the implementation tasks already added the important sandbox tests directly under `tests/test_sandbox/`:

- run-mode mapping and legacy `bypass` migration behavior;
- session Run Context resume/default behavior;
- Trusted-Sandbox staying sandboxed;
- Host Once only after sandbox backend failure;
- external path and sensitive mount validation;
- Windows restricted-token backend selection/fail-closed behavior.

Expected: each implemented behavior has either a new `tests/test_sandbox/` test or an intentionally migrated old semantic test.

- [ ] **Step 2: Add missing sandbox tests directly if needed**

If a requirement above lacks coverage, add the missing test directly to the closest `tests/test_sandbox/` file. Do not create `.sandbox-tmp-tests/`.

Run the tests selected for the files changed in this step. Example:

```bash
uv run pytest tests/test_sandbox/test_run_modes.py tests/test_sandbox/test_run_context.py tests/test_sandbox/test_path_access.py -q
```

Expected: selected tests pass, or implementation code is fixed until they pass.

- [ ] **Step 3: Commit coverage additions if any**

Run with exact paths that changed:

```bash
git add tests/test_sandbox/test_run_modes.py tests/test_sandbox/test_run_context.py tests/test_sandbox/test_path_access.py
git commit -m "test: cover sandbox run mode behavior"
```

If Task 8 only reviewed existing tests and changed nothing, no commit is required.

---

### Task 9: Final Verification And Cleanup

**Files:**
- No code changes unless verification finds implementation bugs.

- [ ] **Step 1: Choose and run final verification tests**

Choose tests based on the files changed in this branch. A typical final command for this migration is:

```bash
uv run pytest tests/test_sandbox tests/test_cli/test_sandbox_cmd.py tests/test_gateway/test_chat_static_assets.py tests/test_application/test_approval_rpc.py tests/test_gateway/test_rpc_approvals.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_chat_clarify_submit.py tests/test_tools/test_sandbox_network_hint.py -q
```

Expected: selected sandbox-relevant tests pass. If a selected test fails because of this branch, fix implementation code or the explicitly migrated sandbox-semantic test.

- [ ] **Step 2: Optionally record full-suite health**

Run only if useful:

```bash
timeout 300 uv run pytest tests
```

Expected: diagnostic output only. Full-suite failure in unrelated areas does not block this sandbox migration.

- [ ] **Step 3: Check old bypass strings**

Run:

```bash
rg -n "Bypass Approvals|Bypass approvals|/elevated bypass|sandbox on\\|bypass\\|full|data-decision=\"bypass\"|data-approval-action=\"bypass\"" src tests
```

Expected: no matches except historical migration error text or tests explicitly asserting that `sandbox bypass` is removed.

- [ ] **Step 4: Check host execution gates**

Run:

```bash
rg -n "elevated.*bypass|bypass.*host|_elevate_current_call|set_elevated_mode" src/opensquilla
```

Expected: no active code path where `bypass` or `trusted` implies host execution. Legacy wrappers may remain only with comments and tests proving they map to sandboxed trusted mode.

- [ ] **Step 5: Final status**

Run:

```bash
git status --short
```

Expected: no output.

If implementation fixes were made during verification, commit them:

```bash
git add <exact files>
git commit -m "fix: stabilize sandbox run mode migration"
```

---

## Self-Review

Spec coverage:

- Three user-facing run modes: Task 1, Task 2, Task 5, Task 9.
- CLI `bypass` removed: Task 2.
- Session Run Context and resume semantics: Task 3, Task 9.
- Trusted-Sandbox prompt contract: Task 4, Task 9.
- Ordinary approval does not imply host: Task 4.
- Host Once only after sandbox failure: Task 4.
- Chat gear keeps only Run Mode, Router, Visual effects: Task 5.
- Approval surfaces remove bypass shortcut: Task 5.
- External path access asks for mount first: Task 6.
- Windows restricted-token backend current scope: Task 7.
- Test selection is implementation-owner controlled rather than a fixed full-suite gate: Task 0, Task 8, Task 9.
- New important sandbox tests are added directly under `tests/test_sandbox/`: Task 1 through Task 8.

Known follow-up plans:

- P1 `Control -> Sandbox` page.
- P1 Allowed Domains and package-install domain bundles.
- P1 Doctor/Explain product surfaces.
- P2 backend resource-limit hardening.
- P2 worktree/session isolation.

No placeholders remain. The plan intentionally allows updating only tests that directly assert old sandbox/bypass semantics; unrelated tests stay fixed.
