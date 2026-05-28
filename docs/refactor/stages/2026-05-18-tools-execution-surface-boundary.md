# Tools Execution Surface Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move engine-facing tool execution surface assembly into the tools layer while preserving tool definitions, dispatch denials, known-skill mismatch envelopes, runtime capability denials, and public imports.

**Architecture:** Add `opensquilla.tools.execution_surface` as the module-level boundary that combines declarative policy, runtime capability denial, profile filtering, skill-name mismatch metadata, and dispatch handler creation. Keep `opensquilla.tools.dispatch` focused on executing a single tool call against a registry, and keep `engine.runtime.TurnRunner` as a thin caller of the tools boundary.

**Tech Stack:** Python, ToolRegistry, ToolContext, AgentToolHandler, ToolDefinition, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: tools-execution-surface-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-dispatch-service-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was re-verified and still fails with `collab spawn failed: agent thread limit reached`; stale shutdown agents also cannot be closed from this live thread, so this larger slice uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate tools execution-surface assembly from `engine/runtime.py` without changing user-visible tool availability, dispatch envelopes, approval-surface handling, published artifact propagation, image-generation runtime visibility, or gateway smoke behavior.

## Current-State Audit

- Current HEAD: `40113a2`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-policy-runtime-surface-boundary.md`
  - `src/opensquilla/engine/runtime.py`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/tool_boundary.py`
  - `src/opensquilla/tools/__init__.py`
  - `src/opensquilla/tools/dispatch.py`
  - `src/opensquilla/tools/envelope.py`
  - `src/opensquilla/tools/policy.py`
  - `src/opensquilla/tools/policy_runtime.py`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/tools/services.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/builtin/loader.py`
  - `tests/test_public_tool_surface.py`
  - `tests/test_tools/test_builtin_loader.py`
  - `tests/test_tools/test_dispatch_envelope.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_tools/test_tool_services_boundary.py`
- Symbols or command surfaces inspected:
  - `TurnRunner._build_tools`
  - `TurnRunner._apply_runtime_capability_denies`
  - `build_tool_handler`
  - `ToolRegistry.to_tool_definitions`
  - `filter_by_profile`
  - `resolve_profile`
  - `apply_tool_policy_from_config`
  - `detect_runtime_tool_surface_capabilities`
  - `resolve_runtime_tool_surface`
  - `load_builtin_tools`
  - `configure_tool_services`
- Tests inspected:
  - Dispatch envelope tests.
  - Registry visibility tests.
  - Builtin loader tests.
  - Public tool surface tests.
  - Tool services boundary tests.
- Existing boundary pattern this stage follows:
  - `tools/policy_config.py` owns declarative policy parsing.
  - `tools/policy_runtime.py` owns runtime capability denials.
  - `tools/visibility.py` owns profile and registry visibility filtering.
  - `tools/dispatch.py` owns one-call dispatch and failure envelopes.

## Boundary Decision

- Responsibilities moving out of `engine/runtime.py`:
  - Applying gateway tool policy to a `ToolContext`.
  - Applying runtime capability denials before schema export and dispatch.
  - Resolving and recording the tool profile.
  - Filtering exported tool definitions by profile.
  - Discovering invocable skill names for skill/tool mismatch envelopes.
  - Creating the `AgentToolHandler` for a registry/context pair.
- Responsibilities staying in place:
  - `TurnRunner` still decides when to build tools for a turn and how to pass the resulting definitions/handler to providers.
  - `tools.dispatch` still performs per-call injection checks, policy defense-in-depth, permission-matrix checks, approval-surface checks, artifact collection, and failure envelopes.
  - `tools.builtin.loader` still owns builtin module import/registration.
  - `tools.services` still owns gateway-wired service handles.
- New module/file responsibility:
  - `src/opensquilla/tools/execution_surface.py` owns engine-facing tool execution surface assembly.
- Public behavior that must not change:
  - `from opensquilla.tools.dispatch import build_tool_handler` keeps working.
  - `TurnRunner._apply_runtime_capability_denies` remains as a compatibility shim for existing tests and callers.
  - Missing tools, denied tools, known skill names called as tools, and unsupported approval surfaces keep the same JSON envelope shapes.
  - Published artifacts still attach to `ToolResult.artifacts`.
  - Runtime-unavailable session tools remain hidden from definitions and denied at dispatch.
- Files explicitly out of scope:
  - Builtin tool implementation internals.
  - Sandbox backend policy and sensitive path scanning.
  - Gateway RPC tool catalog/effective payloads already covered by prior registry/policy slices.
  - Web UI display changes.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_tools/test_execution_surface_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.tools.execution_surface'`.
  - `engine/runtime.py` still assembles tool policy/profile/dispatch directly.
- Minimal implementation:
  - Create `opensquilla.tools.execution_surface`.
  - Move tool execution context resolution and surface assembly from `TurnRunner._build_tools` into the new module.
  - Keep `TurnRunner._build_tools` as a thin caller.
  - Keep `TurnRunner._apply_runtime_capability_denies` as a compatibility shim delegating to the new module.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_execution_surface_boundary.py tests/test_tools/test_dispatch_envelope.py tests/test_tools/test_registry_visibility.py tests/test_tools/test_policy_runtime_boundary.py tests/test_public_tool_surface.py tests/test_provider_image_generation.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/execution_surface.py src/opensquilla/engine/runtime.py tests/test_tools/test_execution_surface_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/tools src/opensquilla/engine/runtime.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/tools/execution_surface.py`
  - `tests/test_tools/test_execution_surface_boundary.py`
  - `docs/refactor/stages/2026-05-18-tools-execution-surface-boundary.md`
- Modify:
  - `src/opensquilla/engine/runtime.py`
- Test:
  - `tests/test_tools/test_execution_surface_boundary.py`
  - `tests/test_tools/test_dispatch_envelope.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `tests/test_public_tool_surface.py`
  - `tests/test_provider_image_generation.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-tools-execution-surface-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-dispatch-service-boundary`.
- [x] Write the failing tools execution surface boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the behavior-compatible execution-surface boundary.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

## Child Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if tool definitions, dispatch envelopes, runtime denials, image-generation availability, published artifacts, or gateway smoke behavior regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `bd04ad17a1d8bbaac0b56e432a17d7cdf434ffc2` (`bd04ad1`, `Extract tool execution surface boundary`).
- Integration merge: `9d976fcf80b8e604ba10da35929f89e324005ffd` (`9d976fc`, `Merge tools execution surface boundary`).
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_tools/test_execution_surface_boundary.py -q` failed during collection with `ModuleNotFoundError: No module named 'opensquilla.tools.execution_surface'`.
- Focused green: `uv run --extra dev pytest tests/test_tools/test_execution_surface_boundary.py tests/test_tools/test_dispatch_envelope.py tests/test_tools/test_registry_visibility.py tests/test_tools/test_policy_runtime_boundary.py tests/test_public_tool_surface.py tests/test_provider_image_generation.py -q` passed with `42 passed in 1.57s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/tools/execution_surface.py src/opensquilla/engine/runtime.py tests/test_tools/test_execution_surface_boundary.py` passed.
- Touched mypy: `uv run --extra dev mypy src/opensquilla/tools src/opensquilla/engine/runtime.py --show-error-codes` passed with no issues in 35 source files.
- Whitespace: `git diff --check` passed.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 510 source files; whitespace passed; pytest passed with `2457 passed, 8 skipped, 2 warnings in 63.55s`; gateway smoke start/status/stop passed on port `54427`.
- Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed at `9d976fc`.
- Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 510 source files; whitespace passed; pytest passed with `2459 passed, 6 skipped, 2 warnings in 26.43s`; gateway smoke start/status/stop passed on port `54566`.
- Directory hygiene target: remove `../opensquilla-refactor-active` after this record commit, then run `git worktree prune` and verify no extra `opensquilla-refactor-*` worktrees remain beyond integration.
- Residual risk: `build_tool_execution_surface` intentionally preserves `build_tool_handler` as the public dispatch primitive, so future slices should avoid moving per-call dispatch internals until envelope and approval tests are expanded for the new owner.
- Next recommended slice: move gateway/provider runtime composition at module scale, using the existing provider runtime assembly and sync boundary tests as the RED contract.
