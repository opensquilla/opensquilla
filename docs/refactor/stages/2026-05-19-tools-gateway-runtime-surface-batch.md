# Tools Gateway Runtime Surface Batch

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: tools-gateway-runtime-surface-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-gateway-runtime-surface-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread with same-thread worker agents when available.
  `spawn_agent` healthcheck returned `spawn_agent available; branch=codex/refactor-architecture; status=clean`.

## Goal

Consolidate runtime tool-surface and gateway `ToolContext` assembly without
changing public RPC payloads, route-envelope semantics, tool visibility, or
owner/elevated behavior. Keep `session` and neutral `runtime` packages free of
new `tools`/`gateway` cycles.

## Current-state audit

- Current HEAD: `d368d82`.
- Worktree status: integration clean before child creation; child branch clean
  at baseline.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (not in touched
    scope)
- Files inspected:
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/policy_runtime.py`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/rpc_tools.py`
  - `src/opensquilla/gateway/channel_commands.py`
- Tests inspected:
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `tests/test_tools/test_builtin_loader.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
  - `tests/test_ci/test_architecture_import_contracts.py`
  - `tests/test_session/test_session_engine_boundary.py`
- Existing boundary pattern this stage follows:
  - Keep behavior-specific route construction in gateway routing.
  - Keep tool visibility and payload shape inside `opensquilla.tools`.
  - Keep runtime-capability denylists in `tools.policy_runtime`.
  - Preserve compatibility facades in `tools.registry` and `tools.visibility`.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; created fixed child worktree
    `../opensquilla-refactor-active` with branch
    `codex/refactor-tools-gateway-runtime-surface-batch`; reran
    `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-gateway-runtime-surface-batch`
    from the child worktree.
- `superpowers:writing-plans`:
  - Evidence: read the skill before implementation; this stage plan records
    the batch boundary, worker ownership, RED/GREEN commands, full gates,
    merge, and cleanup steps.
- `superpowers:test-driven-development`:
  - Evidence: workers must write RED contract tests for their owned boundary
    before implementation and record expected failure output.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused tests,
    touched-file checks, full child `scripts/refactor_gate.sh`, integration
    `scripts/refactor_gate.sh`, and cleanup audit are recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes; three read-only
    explorers audited tools surface, gateway context assembly, and architecture
    guard candidates.
  - `superpowers:subagent-driven-development` used: yes for independent Worker
    A and Worker B implementation scopes.
  - `spawn_agent` probe during closeout: first review agent spawned
    successfully; a second immediate spawn hit `agent thread limit reached`.
    After closing completed agents, the second review agent spawned and
    completed. Same-thread agents are usable but capacity-bound.
  - External worker fallback: not needed for this batch because the capacity
    limit cleared after completed agents were closed.
- Historical evidence note:
  - This record does not infer Superpowers usage for prior stages. Prior stage
    evidence must come from each stage record or current command log.

## Boundary decision

- Module batch:
  - Tools-only surface request/payload boundary.
  - Gateway-owned runtime `ToolContext` assembly helper.
- Responsibilities moving out:
  - Duplicate catalog/effective runtime capability plumbing from
    `tools.rpc_payload`.
  - Duplicate visible tool row construction from `tools.registry`.
  - Duplicate gateway workspace/strictness plus route-envelope-to-context
    assembly from `rpc_session_send`, `channel_dispatch`, and `boot`.
- Responsibilities staying in place:
  - `tools.policy_runtime` keeps only runtime-capability denylist resolution.
  - `gateway.routing.tool_context_from_envelope` remains the semantic core for
    route envelope to `ToolContext` mapping.
  - `gateway.rpc_tools` and `gateway.channel_commands` stay out of the first
    edit because they pass RPC catalog context rather than building runtime
    turn `ToolContext`.
  - `session` and neutral `runtime` packages remain out of scope.
- New module/file responsibility:
  - `src/opensquilla/tools/surface.py`: tools-only request/context/payload row
    helpers used by registry and RPC payload builders.
  - `src/opensquilla/gateway/routing.py`: gateway helper for route envelope
    plus gateway config to runtime `ToolContext`, preserving owner/workspace
    semantics.
- Public behavior that must not change:
  - `tools.catalog` keeps `source` and `enabled` fields.
  - `tools.effective` does not gain catalog-only fields.
  - Runtime params take precedence over profile-only listing behavior.
  - Cron effective contexts force `is_owner=False`.
  - Channel admin sender ownership and unlisted sender restrictions stay the
    same.
  - `principal_is_owner`, `tool_source_kind`, cron tool policy, subagent depth,
    workspace directory, and non-bool `workspace_strict -> bool(workspace_dir)`
    fallback stay compatible.
- Files explicitly out of scope:
  - `src/opensquilla/gateway/rpc_tools.py`
  - `src/opensquilla/gateway/channel_commands.py`
  - `src/opensquilla/tools/execution_surface.py`
  - `src/opensquilla/session/**`
  - `src/opensquilla/runtime/**`

## Worker ownership

### Worker A: Tools Surface Boundary

- Owns:
  - `src/opensquilla/tools/surface.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/registry.py`
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
- Must not edit:
  - `src/opensquilla/gateway/**`
  - `src/opensquilla/session/**`
  - `src/opensquilla/runtime/**`
- RED tests:
  - New tools surface module exists and owns `ToolSurfaceRequest`.
  - Catalog/effective use the same resolved runtime context while preserving
    distinct row shapes.
  - Runtime params override `profile`; profile-only path remains compatible.
  - Public compatibility imports from `tools.registry` remain valid.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_policy_runtime_boundary.py tests/test_gateway/test_rpc_tools_visibility.py -q`

### Worker B: Gateway Runtime Context Assembly

- Owns:
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `src/opensquilla/gateway/boot.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_router_boot.py`
  - relevant narrow checks in `tests/test_gateway/test_rpc_sessions.py`
- Must not edit:
  - `src/opensquilla/tools/**`
  - `src/opensquilla/session/**`
  - `src/opensquilla/runtime/**`
- RED tests:
  - New gateway helper exists and builds equivalent `ToolContext` fields for
    web/CLI/channel/cron/subagent route envelopes.
  - Helper preserves explicit owner, channel admin/non-admin, task id assignment
    after task-runtime dispatch, workspace directory, and workspace strictness
    fallback.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_gateway/test_routing_interaction_mode.py tests/test_gateway/test_channel_dispatch_realtime.py::test_channel_admin_sender_gets_owner_tool_context_for_agent_turn tests/test_gateway/test_channel_dispatch_realtime.py::test_unlisted_channel_sender_keeps_restricted_tool_context_for_agent_turn tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_sessions_send_uses_agent_registry_model_when_session_has_no_model tests/test_gateway/test_router_boot.py::test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model tests/test_gateway/test_router_boot.py::test_task_runtime_turn_applies_cron_job_tool_policy tests/test_gateway/test_rpc_tools_visibility.py -q`

## TDD red/green

- Baseline focused command:
  - `uv run --extra dev pytest -q tests/test_ci/test_architecture_import_contracts.py tests/test_session/test_session_engine_boundary.py tests/test_tools/test_builtin_loader.py tests/test_gateway/test_router_boot.py`
  - Result before implementation: `28 passed`.
- Failing test commands:
  - Worker A RED: tools boundary tests failed before `opensquilla.tools.surface`
    owned `ToolSurfaceRequest` and shared row/context helpers.
  - Worker B RED: gateway routing tests failed before
    `tool_context_from_route_envelope` existed.
- Expected red failures:
  - Missing `opensquilla.tools.surface` and `ToolSurfaceRequest`.
  - Missing gateway helper for config-backed route turn `ToolContext`
    assembly.
- Behavior compatibility coverage:
  - Tools catalog/effective payload shape, profile/runtime precedence,
    runtime capability denylists, route-envelope caller kind/interaction mode,
    channel admin ownership, RPC sessions send, and task runtime boot.
- Combined focused GREEN:
  - `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_policy_runtime_boundary.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_gateway/test_channel_dispatch_realtime.py::test_channel_admin_sender_gets_owner_tool_context_for_agent_turn tests/test_gateway/test_channel_dispatch_realtime.py::test_unlisted_channel_sender_keeps_restricted_tool_context_for_agent_turn tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_sessions_send_uses_agent_registry_model_when_session_has_no_model tests/test_gateway/test_router_boot.py::test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model tests/test_gateway/test_router_boot.py::test_task_runtime_turn_applies_cron_job_tool_policy tests/test_ci/test_architecture_import_contracts.py tests/test_session/test_session_engine_boundary.py tests/test_tools/test_builtin_loader.py -q`
  - First closeout run found the RPC sessions node id had drifted; reran with
    the current node id:
    `uv run --extra dev pytest tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_policy_runtime_boundary.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_routing_interaction_mode.py tests/test_gateway/test_channel_dispatch_realtime.py::test_channel_admin_sender_gets_owner_tool_context_for_agent_turn tests/test_gateway/test_channel_dispatch_realtime.py::test_unlisted_channel_sender_keeps_restricted_tool_context_for_agent_turn tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing tests/test_gateway/test_router_boot.py::test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model tests/test_gateway/test_router_boot.py::test_task_runtime_turn_applies_cron_job_tool_policy tests/test_ci/test_architecture_import_contracts.py tests/test_session/test_session_engine_boundary.py tests/test_tools/test_builtin_loader.py -q`
  - Result: `40 passed in 2.64s`.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/surface.py src/opensquilla/tools/visibility.py src/opensquilla/tools/rpc_payload.py src/opensquilla/tools/registry.py src/opensquilla/gateway/routing.py src/opensquilla/gateway/rpc_session_send.py src/opensquilla/gateway/channel_dispatch.py src/opensquilla/gateway/boot.py tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_policy_runtime_boundary.py tests/test_gateway/test_routing_interaction_mode.py tests/test_gateway/test_channel_dispatch_realtime.py tests/test_gateway/test_router_boot.py tests/test_gateway/test_rpc_sessions.py`
    - Result: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/tools/surface.py src/opensquilla/tools/visibility.py src/opensquilla/tools/rpc_payload.py src/opensquilla/tools/registry.py src/opensquilla/gateway/routing.py src/opensquilla/gateway/rpc_session_send.py src/opensquilla/gateway/channel_dispatch.py src/opensquilla/gateway/boot.py --show-error-codes`
    - Result: `Success: no issues found in 8 source files`.
  - `git diff --check`
    - Result: clean.

## Files

- Create:
  - `src/opensquilla/tools/surface.py`
- Modify:
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/rpc_payload.py`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_router_boot.py`
  - targeted `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty` in integration.
- [x] Create fixed child worktree `../opensquilla-refactor-active`.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-gateway-runtime-surface-batch`.
- [x] Run baseline focused command and record result.
- [x] Dispatch Worker A/B with explicit ownership and TDD RED/GREEN.
- [x] Review each worker diff for public API compatibility and import cycles.
- [x] Run the combined focused GREEN command.
- [x] Run touched-file Ruff, mypy, and `git diff --check`.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
  - Result: `All checks passed!`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - Result: `Success: no issues found in 530 source files`.
- `git diff --check`
  - Result: clean.
- `uv run --extra dev pytest`
  - Result: `2550 passed, 8 skipped, 2 warnings in 28.87s`.
- gateway smoke through `scripts/refactor_gate.sh`
  - Result: gateway smoke started on `127.0.0.1:62661`, reported running,
    stopped cleanly, and then reported `not_started`.
  - Final result: `Refactor gate complete.`

## Integration gate

- `uv run --extra dev ruff check src tests`
  - Result: `All checks passed!`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - Result: `Success: no issues found in 530 source files`.
- `git diff --check HEAD^ HEAD`
  - Result: clean through `scripts/refactor_gate.sh` whitespace step.
- `uv run --extra dev pytest`
  - Result: `2552 passed, 6 skipped, 2 warnings in 28.17s`.
- gateway smoke through `scripts/refactor_gate.sh`
  - Result: gateway smoke started on `127.0.0.1:62812`, reported running,
    stopped cleanly, and then reported `not_started`.
  - Final result: `Refactor gate complete.`

## Rollback

- Revert the integration merge commit if the slice regresses tool visibility,
  catalog/effective payload shape, channel admin ownership, RPC session send,
  task-runtime boot, cron policy, or subagent route behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `638830eca5c94edf97b13dc23675bcadebd0eb69`
- Integration merge: `d0b79582038f3c139cdaadf7232cc86b807439f9`
- Verification evidence:
  - Child focused closeout: `40 passed in 2.64s`.
  - Child touched-file Ruff: all checks passed.
  - Child touched-file mypy: no issues in 8 source files.
  - Child `git diff --check`: clean.
  - Child `scripts/refactor_gate.sh`: ruff passed; mypy passed over 530
    source files; pytest `2550 passed, 8 skipped, 2 warnings`; gateway smoke
    passed.
  - Integration `scripts/refactor_gate.sh`: ruff passed; mypy passed over 530
    source files; pytest `2552 passed, 6 skipped, 2 warnings`; gateway smoke
    passed.
  - Cleanup: `git worktree remove ../opensquilla-refactor-active`
    and `git worktree prune` completed; `git worktree list` no longer shows
    `../opensquilla-refactor-active`.
- Residual risk:
  - Same-thread `spawn_agent` remains capacity-bound; close completed agents
    before spawning more, and use `scripts/refactor_external_agent.sh` fixed
    worker worktrees if capacity cannot be released.
- Next recommended slice:
  - Start the next coarse module-family boundary from the clean integration
    branch, reusing `../opensquilla-refactor-active` only after the previous
    worktree has been removed and pruned.
