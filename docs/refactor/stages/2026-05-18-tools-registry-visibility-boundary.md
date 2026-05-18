# Tools Registry Visibility Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tool profile, runtime context, and visibility policy out of `tools/registry.py` while preserving public tool names, profile filtering, owner-only behavior, subagent/cron restrictions, and RPC payload compatibility.

**Architecture:** Add `opensquilla.tools.visibility` as the policy boundary for `ToolProfile`, profile filtering, context construction, and registered-tool visibility checks. Keep `ToolRegistry` focused on registration, schema export, and list/effective payload entrypoints, with existing imports from `opensquilla.tools.registry` preserved by re-exporting the visibility symbols.

**Tech Stack:** Python, ToolRegistry, ToolContext, ToolSurfaceCapabilities, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: tools-registry-visibility-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-registry-visibility-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` remains blocked by the current thread's stale runtime agent limit, so this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate tool visibility/profile/context policy from the registry implementation without changing public tool definitions, RPC catalog/effective responses, channel profile filtering, owner-only filtering, subagent/cron default denylists, or runtime capability-gated tool visibility.

## Current-State Audit

- Current HEAD: `593eb6a`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-rpc-payload-boundary.md`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/policy.py`
  - `src/opensquilla/tools/types.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `tools/registry.py` and `tools/dispatch.py`.
  - `ToolProfile`
  - `filter_by_profile`
  - `resolve_profile`
  - `ToolRegistry._iter_visible_tools`
  - `ToolRegistry._is_visible`
  - `ToolRegistry._context_for_profile`
  - `ToolRegistry._effective_context`
  - `tools_catalog_payload`
  - `tools_effective_payload`
- Tests inspected:
  - Tool registry visibility and profile tests.
  - Gateway tools RPC visibility tests.
  - Public tool surface tests.
  - Dispatch policy denial tests.
- Existing boundary pattern this stage follows:
  - `tools/rpc_payload.py` already owns RPC request/payload policy while `tools/registry.py` keeps compatibility wrappers.
  - Gateway/RPC and Provider refactor slices use AST boundary tests to verify ownership without changing public behavior.

## Boundary Decision

- Responsibilities moving out:
  - `ToolProfile` and channel default allowlist.
  - Profile filtering and profile resolution.
  - Interaction mode parsing.
  - Default/profile/effective runtime `ToolContext` construction.
  - Registered-tool visibility filtering and stable sorting.
- Responsibilities staying in place:
  - Tool registration, lookup, unregister, and all-tools access.
  - Tool schema construction and list/effective response formatting.
  - Compatibility imports from `opensquilla.tools.registry` for `ToolProfile`, `filter_by_profile`, and `resolve_profile`.
  - RPC payload compatibility wrappers already delegated to `tools.rpc_payload`.
- New module/file responsibility:
  - `src/opensquilla/tools/visibility.py` owns tool profile/context/visibility policy.
- Public behavior that must not change:
  - Default owner tool schema contents and stable sorting.
  - Channel default profile allowlist, including `publish_artifact`.
  - Owner-only tools remain hidden from non-owners even when listed in allowed tools.
  - Hidden tools require surfacing and still respect strict `allowed_tools`.
  - Subagent and cron runtime contexts keep their existing deny/allow lists.
  - `opensquilla.tools.registry` public imports keep working.
- Files explicitly out of scope:
  - Tool execution dispatch and result envelopes.
  - Shell, filesystem, web, patch, and MCP builtin tool behavior.
  - Gateway RPC method registration.
  - Public tool names or schemas.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.tools.visibility'`.
  - `tools/registry.py` still owns `ToolProfile`, profile filtering, and context/visibility helpers.
- Minimal implementation:
  - Create `opensquilla.tools.visibility`.
  - Move profile/context/visibility helpers from `tools/registry.py` into the new module.
  - Import/re-export the public compatibility symbols from `tools/registry.py`.
  - Update `ToolRegistry` private helper methods to delegate to `tools.visibility`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_rpc_tools_visibility.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/visibility.py src/opensquilla/tools/registry.py tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_rpc_tools_visibility.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/tools/visibility.py`
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `docs/refactor/stages/2026-05-18-tools-registry-visibility-boundary.md`
- Modify:
  - `src/opensquilla/tools/registry.py`
- Test:
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
  - `tests/test_public_tool_surface.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-tools-registry-visibility-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-registry-visibility-boundary`.
- [x] Write the failing tools registry visibility boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible visibility boundary move.
- [x] Run the focused test and touched-file checks.
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

- Revert the integration merge commit if tool visibility, public tool surface, subagent/cron restrictions, or gateway tool RPC payload behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py -q` failed as expected during collection with `ModuleNotFoundError: No module named 'opensquilla.tools.visibility'`.
- Focused green: `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_rpc_tools_visibility.py -q` passed with `28 passed in 1.28s`.
- Expanded tools/public regression: `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_public_tool_surface.py tests/test_tools/test_tool_services_boundary.py tests/test_tools/test_dispatch_envelope.py tests/test_tools/test_tool_failure_envelope.py -q` passed with `48 passed in 0.84s`.
- Broader tools/engine group: `uv run --extra dev pytest tests/test_tools tests/test_gateway/test_rpc_tools_visibility.py tests/test_public_tool_surface.py tests/test_engine/test_tool_activity_heartbeat.py tests/test_engine/test_tool_concurrency.py tests/test_engine/test_tool_result_json_guard.py tests/test_engine/test_tool_result_persistence.py -q` passed with `179 passed in 2.89s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/tools/visibility.py src/opensquilla/tools/registry.py tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_rpc_tools_visibility.py` passed.
- Whitespace: `git diff --check` passed.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 507 source files; whitespace passed; pytest passed with `2447 passed, 8 skipped, 2 warnings in 45.72s`; gateway smoke start/status/stop passed on port `52425`.
- Residual risk:
- Next recommended slice:
