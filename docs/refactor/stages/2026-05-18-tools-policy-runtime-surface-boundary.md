# Tools Policy Runtime Surface Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tool runtime capability detection and runtime-denylist resolution out of `tools/policy.py` while preserving public tool policy imports and runtime visibility behavior.

**Architecture:** Add `opensquilla.tools.policy_runtime` as the runtime-surface boundary for `ToolSurfaceCapabilities`, runtime dependency detection, and capability-based denylist resolution. Keep `opensquilla.tools.policy` as the public policy facade that applies declarative policy and re-exports runtime-surface symbols for compatibility.

**Tech Stack:** Python, ToolContext, ToolSurfaceCapabilities, ToolRegistry visibility, tool RPC payload runtime capabilities, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: tools-policy-runtime-surface-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-policy-runtime-surface-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` remains blocked in this live thread by stale runtime agent-limit state, so this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate runtime capability detection and runtime denylist resolution from declarative policy application without changing public imports, tool catalog/effective payloads, owner/channel visibility, subagent/cron unattended restrictions, image-generation runtime visibility, or gateway smoke behavior.

## Current-State Audit

- Current HEAD: `f5a4084`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-policy-config-boundary.md`
  - `src/opensquilla/tools/policy.py`
  - `src/opensquilla/tools/policy_config.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/registry.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Symbols or command surfaces inspected:
  - `ToolSurfaceCapabilities`
  - `tool_surface_capabilities_from_runtime`
  - `resolve_runtime_tool_surface`
  - `detect_runtime_tool_surface_capabilities`
  - `_IMAGE_GENERATION_TOOL_NAMES`
  - `_SESSION_READ_TOOL_NAMES`
  - `_SESSION_RUNTIME_TOOL_NAMES`
  - `_CHANNEL_RUNTIME_TOOL_NAMES`
  - `_ADMIN_RUNTIME_TOOL_NAMES`
  - `_GATEWAY_RUNTIME_TOOL_NAMES`
  - `_SCHEDULER_RUNTIME_TOOL_NAMES`
- Tests inspected:
  - Registry visibility/tool surface tests.
  - Gateway routing interaction-mode tests.
  - Provider image-generation runtime boundary tests.
  - Public tool surface tests.
- Existing boundary pattern this stage follows:
  - `tools/policy_config.py` now owns declarative policy config/selector math while `tools/policy.py` preserves compatibility exports.
  - `tools/visibility.py` owns registry visibility/profile context behavior.

## Boundary Decision

- Responsibilities moving out:
  - `ToolSurfaceCapabilities` dataclass.
  - Runtime dependency/image-generation capability detection.
  - Runtime capability denylist constants.
  - `tool_surface_capabilities_from_runtime`.
  - `resolve_runtime_tool_surface`.
  - `detect_runtime_tool_surface_capabilities`.
- Responsibilities staying in place:
  - Public policy application entrypoints:
    - `apply_tool_policy`
    - `apply_tool_policy_layer`
    - `apply_tool_policy_from_config`
  - Compatibility imports from `opensquilla.tools.policy` for runtime-surface symbols.
  - Declarative policy config/selector parsing remains in `tools/policy_config.py`.
- New module/file responsibility:
  - `src/opensquilla/tools/policy_runtime.py` owns runtime tool-surface capability detection and resolution.
- Public behavior that must not change:
  - `from opensquilla.tools.policy import ToolSurfaceCapabilities` keeps working.
  - Runtime unavailable dependencies still deny session, task-runtime, scheduler, gateway, channel, admin, and image tools exactly as before.
  - Tool RPC payloads still derive runtime capabilities from injected runtime dependencies.
  - Image-generation visibility still follows image-generation runtime availability.
  - Full public tool surface remains unchanged.
- Files explicitly out of scope:
  - Declarative config profiles/selectors already extracted to `tools/policy_config.py`.
  - Tool execution dispatch and builtin tool implementations.
  - Gateway RPC method registration.
  - Sandbox backend behavior.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.tools.policy_runtime'`.
  - `tools/policy.py` still owns `ToolSurfaceCapabilities`, runtime capability detection, and runtime denylist resolution.
- Minimal implementation:
  - Create `opensquilla.tools.policy_runtime`.
  - Move runtime-surface dataclass, runtime denylist constants, runtime capability detection, and runtime resolution helpers into it.
  - Update internal `tools.visibility`, `tools.rpc_payload`, and `tools.registry` imports to use `tools.policy_runtime`.
  - Keep compatibility assignments in `tools.policy`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_provider_image_generation_runtime_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/policy.py src/opensquilla/tools/policy_runtime.py src/opensquilla/tools/visibility.py src/opensquilla/tools/rpc_payload.py src/opensquilla/tools/registry.py tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_provider_image_generation_runtime_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/tools/policy_runtime.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `docs/refactor/stages/2026-05-18-tools-policy-runtime-surface-boundary.md`
- Modify:
  - `src/opensquilla/tools/policy.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/registry.py`
- Test:
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_tools/test_policy_agents.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
  - `tests/test_public_tool_surface.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-tools-policy-runtime-surface-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-policy-runtime-surface-boundary`.
- [x] Write the failing tools policy runtime surface boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible runtime-surface boundary move.
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

- Revert the integration merge commit if runtime capability denylists, tool RPC visibility, image-generation tool availability, subagent/cron restrictions, or gateway smoke behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py -q` failed as expected during collection with `ModuleNotFoundError: No module named 'opensquilla.tools.policy_runtime'`.
- Focused green: `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_provider_image_generation_runtime_boundary.py -q` passed with `29 passed in 0.56s`.
- Broader tools/runtime group: `uv run --extra dev pytest tests/test_tools tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_public_tool_surface.py tests/test_provider_image_generation_runtime_boundary.py tests/test_engine/test_tool_activity_heartbeat.py tests/test_engine/test_tool_concurrency.py tests/test_engine/test_tool_result_json_guard.py tests/test_engine/test_tool_result_persistence.py tests/test_scheduler/test_cron_rpc_payload.py -q` passed with `197 passed in 3.11s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/tools/policy.py src/opensquilla/tools/policy_runtime.py src/opensquilla/tools/visibility.py src/opensquilla/tools/rpc_payload.py src/opensquilla/tools/registry.py tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_provider_image_generation_runtime_boundary.py` passed.
- Touched mypy: `uv run --extra dev mypy src/opensquilla/tools --show-error-codes` passed with no issues in 33 source files.
- Architecture import contract spot check: `uv run --extra dev pytest tests/test_ci/test_architecture_import_contracts.py::test_package_imports_do_not_add_new_edges tests/test_tools/test_policy_runtime_boundary.py tests/test_provider_image_generation_runtime_boundary.py::test_gateway_reads_image_generation_capability_from_runtime_boundary -q` passed with `6 passed in 0.91s`.
- Whitespace: `git diff --check` passed.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 509 source files; whitespace passed; pytest passed with `2454 passed, 8 skipped, 2 warnings in 46.19s`; gateway smoke start/status/stop passed on port `53619`.
- Residual risk:
- Next recommended slice:
