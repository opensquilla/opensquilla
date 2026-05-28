# Tools Policy Config Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tool policy config parsing, selector expansion, groups, and named profiles out of `tools/policy.py` while preserving public tool policy behavior.

**Architecture:** Add `opensquilla.tools.policy_config` as the config/selector boundary for `ToolPolicy`, selector/profile expansion, config-shaped policy parsing, sender/channel policy lookup, and policy-layer set operations. Keep `opensquilla.tools.policy` as the runtime surface that applies parsed policy to `ToolContext`, resolves runtime capabilities, and re-exports `ToolPolicy` for compatibility.

**Tech Stack:** Python, ToolPolicy, GatewayConfig-shaped tool config, ToolContext, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: tools-policy-config-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-policy-config-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` remains blocked in this live thread by stale runtime agent-limit state, so this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate declarative tool policy config/selector parsing from runtime tool-surface policy application without changing tool profiles, group selectors, sender overrides, channel policies, cron route policy narrowing, runtime capability denylists, or existing imports from `opensquilla.tools.policy`.

## Current-State Audit

- Current HEAD: `93921bb`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-registry-visibility-boundary.md`
  - `src/opensquilla/tools/policy.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/types.py`
  - `tests/test_tools/test_policy_agents.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
- Symbols or command surfaces inspected:
  - `_TOOL_GROUPS`
  - `_TOOL_PROFILES`
  - `ToolPolicy`
  - `_expand_selectors`
  - `_profile_allowlist`
  - `_policy_from_config`
  - `_sender_policy`
  - `_agent_policy_from_config`
  - `_channel_entry_policy_from_config`
  - `apply_tool_policy`
  - `apply_tool_policy_layer`
  - `apply_tool_policy_from_config`
  - `resolve_runtime_tool_surface`
- Tests inspected:
  - Tool policy agent config tests.
  - Registry visibility/tool surface tests.
  - Gateway routing interaction-mode tests.
  - Public tool surface tests.
- Existing boundary pattern this stage follows:
  - `tools/visibility.py` now owns registry visibility/profile context policy while `tools/registry.py` preserves compatibility exports.
  - `tools/rpc_payload.py` owns tool RPC payload construction while registry keeps compatibility wrappers.

## Boundary Decision

- Responsibilities moving out:
  - Tool group and named profile definitions.
  - Selector expansion for exact names, groups, wildcard, and fnmatch patterns.
  - Config-shaped `ToolPolicy` parsing.
  - Sender, agent, and channel-entry policy lookup.
  - Base/channel/sender policy layer set operations.
- Responsibilities staying in place:
  - Runtime tool capability detection and runtime dependency denylists.
  - `apply_tool_policy`, `apply_tool_policy_layer`, and `apply_tool_policy_from_config` public entrypoints.
  - `ToolSurfaceCapabilities` and runtime tool surface resolution.
  - Compatibility import `from opensquilla.tools.policy import ToolPolicy`.
- New module/file responsibility:
  - `src/opensquilla/tools/policy_config.py` owns declarative tool policy parsing and selector math.
- Public behavior that must not change:
  - `group:*`, `*`, exact, and fnmatch selectors behave the same.
  - Named profiles `full`, `minimal`, `memory_only`, `coding`, and `messaging` behave the same.
  - Agent and channel policy layering/denies keep precedence.
  - Cron route tool policy can narrow or extend only within the cron hard-deny baseline.
  - Existing imports from `opensquilla.tools.policy` keep working.
- Files explicitly out of scope:
  - Tool execution dispatch.
  - Registry visibility/profile context policy already extracted to `tools/visibility.py`.
  - Gateway RPC method registration.
  - Builtin tool implementations and sandbox backend behavior.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_tools/test_policy_config_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.tools.policy_config'`.
  - `tools/policy.py` still owns `ToolPolicy`, groups, profiles, selector expansion, and config parsing helpers.
- Minimal implementation:
  - Create `opensquilla.tools.policy_config`.
  - Move `ToolPolicy`, group/profile constants, selector expansion, config parsing, sender/agent/channel lookup, and policy-layer helpers into it.
  - Update `tools/policy.py` to import the new boundary and re-export `ToolPolicy`.
  - Preserve public runtime application behavior and existing test coverage.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_policy_config_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/policy.py src/opensquilla/tools/policy_config.py tests/test_tools/test_policy_config_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/tools/policy_config.py`
  - `tests/test_tools/test_policy_config_boundary.py`
  - `docs/refactor/stages/2026-05-18-tools-policy-config-boundary.md`
- Modify:
  - `src/opensquilla/tools/policy.py`
- Test:
  - `tests/test_tools/test_policy_config_boundary.py`
  - `tests/test_tools/test_policy_agents.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_public_tool_surface.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-tools-policy-config-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-policy-config-boundary`.
- [x] Write the failing tools policy config boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible policy config boundary move.
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

- Revert the integration merge commit if tool policy profiles, group selectors, agent/channel/sender overrides, cron route policy, or runtime capability denylists regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `e22535c2f8ca547abd3799fff9425ada4ce2da26`.
- Integration merge: `b13ce98bdf100f87ac78b3b28bfea5c9cfe4febb`.
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_tools/test_policy_config_boundary.py -q` failed as expected during collection with `ModuleNotFoundError: No module named 'opensquilla.tools.policy_config'`.
- Focused green: `uv run --extra dev pytest tests/test_tools/test_policy_config_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py -q` passed with `23 passed in 1.14s`.
- Broader tools/routing group: `uv run --extra dev pytest tests/test_tools tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_public_tool_surface.py tests/test_engine/test_tool_activity_heartbeat.py tests/test_engine/test_tool_concurrency.py tests/test_engine/test_tool_result_json_guard.py tests/test_engine/test_tool_result_persistence.py tests/test_scheduler/test_cron_rpc_payload.py -q` passed with `188 passed in 2.93s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/tools/policy.py src/opensquilla/tools/policy_config.py tests/test_tools/test_policy_config_boundary.py tests/test_tools/test_policy_agents.py tests/test_tools/test_registry_visibility.py tests/test_gateway/test_routing_interaction_mode.py` passed.
- Touched mypy: `uv run --extra dev mypy src/opensquilla/tools --show-error-codes` passed with no issues in 32 source files.
- Architecture import contract spot check: `uv run --extra dev pytest tests/test_ci/test_architecture_import_contracts.py::test_package_imports_do_not_add_new_edges tests/test_tools/test_policy_config_boundary.py tests/test_tools/test_policy_agents.py -q` passed with `8 passed in 0.94s`.
- Whitespace: `git diff --check` passed.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 508 source files; whitespace passed; pytest passed with `2450 passed, 8 skipped, 2 warnings in 47.30s`; gateway smoke start/status/stop passed on port `53094`.
- Release hygiene spot check after stage-doc update: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed with `1 passed in 0.31s`.
- Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `93921bb`.
- Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 508 source files; whitespace passed; pytest passed with `2452 passed, 6 skipped, 2 warnings in 26.51s`; gateway smoke start/status/stop passed on port `53221`.
- Residual risk:
  - Low. The slice moves declarative policy parsing and selector math without changing public policy entrypoints, runtime capability denylists, cron hard-deny behavior, or `ToolPolicy` compatibility import.
- Next recommended slice:
  - Continue Tools/Sandbox cleanup by splitting runtime capability detection/denylists out of `tools/policy.py`, or shift to a Channels message-normalization boundary if tool policy has been sufficiently thinned for this pass.
