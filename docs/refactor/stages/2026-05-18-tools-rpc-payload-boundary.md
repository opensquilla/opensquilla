# Tools RPC Payload Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tool RPC payload construction out of `tools/registry.py` while preserving tool visibility, owner filtering, runtime capability detection, and public tool names.

**Architecture:** Add `opensquilla.tools.rpc_payload` as the RPC payload boundary for `tools.catalog` and `tools.effective`. Keep `ToolRegistry` focused on registration, filtering, and tool schema generation. Keep compatibility wrappers in `tools.registry` for existing imports.

**Tech Stack:** Python, gateway RPC dispatcher, ToolRegistry, tool policy/capabilities, pytest, ruff, mypy.

---

## Stage

- Name: tools-rpc-payload-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-rpc-payload-boundary`
- Child worktree: `../opensquilla-refactor-tools-rpc-payload-boundary`
- Owner: Codex main thread. The child worktree was refreshed from integration head `5afdc58`; previous worker attempts left no filesystem changes.

## Goal

Extract `tools.catalog` and `tools.effective` RPC payload construction from `tools/registry.py` into `tools/rpc_payload.py` without changing tool names, owner-only visibility, caller-kind filtering, runtime capability detection, or public release/tool-surface invariants.

## Current-State Audit

- Current HEAD before this slice: `5afdc58`.
- Worktree status: clean before test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Serena project: `opensquilla-refactor-integration` was used for symbol-level inspection before editing this child worktree.
- Symbols inspected with Serena:
  - `gateway.rpc_tools._handle_tools_catalog`
  - `gateway.rpc_tools._handle_tools_effective`
  - `tools.registry.tools_catalog_payload`
  - `tools.registry.tools_effective_payload`
  - `tools.registry._tool_rpc_params`
  - `tools.registry._tool_surface_capabilities_for_runtime`
- Files inspected:
  - `src/opensquilla/gateway/rpc_tools.py`
  - `src/opensquilla/tools/registry.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
  - `tests/test_public_tool_surface.py`

## Boundary Decision

- Responsibilities moving out:
  - RPC param normalization for tool RPC methods.
  - Runtime capability resolution used by tool RPC payloads.
  - `tools.catalog` payload construction.
  - `tools.effective` payload construction.
- Responsibilities staying in `tools/registry.py`:
  - Tool registration and lookup.
  - Tool visibility/filtering internals.
  - Tool definition/schema generation.
  - Compatibility wrappers for `tools_catalog_payload` and `tools_effective_payload`.
- Responsibilities staying in `gateway/rpc_tools.py`:
  - RPC method registration, scope selection, and context extraction.
- Public behavior that must not change:
  - Tool names and removed wrapper tool exclusions.
  - Owner-only tool visibility.
  - Channel/subagent/agent caller-kind behavior.
  - Image-generation runtime capability detection.
  - Public release golden/static checks.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_delegates_payloads_to_tools_boundary tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary -q`
- Expected red failure:
  - Failed because `src/opensquilla/tools/rpc_payload.py` did not exist and `rpc_tools.py` still imported payload builders from `opensquilla.tools.registry`.
- Minimal implementation:
  - Create `opensquilla.tools.rpc_payload`.
  - Move payload builder bodies and private RPC helper logic into the new module.
  - Update `gateway/rpc_tools.py` to import from `tools.rpc_payload`.
  - Keep `tools.registry` compatibility wrappers that delegate to `tools.rpc_payload`.
  - Update architecture tests so runtime capability import ownership follows the new payload boundary.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_delegates_payloads_to_tools_boundary tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_visibility_respects_principal_ownership tests/test_tools/test_registry_visibility.py::test_tools_rpc_payloads_are_built_by_registry_boundary tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_tools.py src/opensquilla/tools/registry.py src/opensquilla/tools/rpc_payload.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_provider_image_generation_runtime_boundary.py tests/test_tools/test_registry_visibility.py`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py tests/test_tools/test_registry_visibility.py tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary tests/test_public_tool_surface.py -q`

## Files

- Create:
  - `src/opensquilla/tools/rpc_payload.py`
  - `docs/refactor/stages/2026-05-18-tools-rpc-payload-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_tools.py`
  - `src/opensquilla/tools/registry.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`

## Steps

- [x] Refresh child worktree from integration head.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-rpc-payload-boundary`.
- [x] Inspect target symbols with Serena.
- [x] Write failing tools RPC payload boundary tests.
- [x] Run focused tests and confirm expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.

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

- Revert the integration merge commit if tool visibility, tool names, or runtime capability behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: pending
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-rpc-payload-boundary` passed on branch `codex/refactor-tools-rpc-payload-boundary` at `5afdc58`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_delegates_payloads_to_tools_boundary tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary -q` failed as expected because `tools/rpc_payload.py` did not exist and `rpc_tools.py` imported payload builders from `tools.registry`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_delegates_payloads_to_tools_boundary tests/test_gateway/test_rpc_tools_visibility.py::test_tools_rpc_visibility_respects_principal_ownership tests/test_tools/test_registry_visibility.py::test_tools_rpc_payloads_are_built_by_registry_boundary tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary -q` passed after updating the architecture test owner.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_tools.py src/opensquilla/tools/registry.py src/opensquilla/tools/rpc_payload.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_provider_image_generation_runtime_boundary.py tests/test_tools/test_registry_visibility.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_tools_visibility.py tests/test_tools/test_registry_visibility.py tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary tests/test_public_tool_surface.py -q` passed, `30 passed in 0.85s`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 486 source files; whitespace passed; pytest passed with `2398 passed, 8 skipped, 2 warnings in 53.25s`; gateway smoke start/status/stop passed on `127.0.0.1:54120`.
- Residual risk:
  - Pending integration merge and integration gate.
- Next recommended slice:
  - Continue with Channels/Gateway payload boundary after this slice lands.
