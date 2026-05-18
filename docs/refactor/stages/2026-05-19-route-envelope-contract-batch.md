# Route Envelope Contract Batch

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: route-envelope-contract-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-route-envelope-contract-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread with same-thread worker agents. `spawn_agent`
  healthcheck returned `spawn_agent available.`

## Goal

Normalize the route-envelope contract across gateway, scheduler, and session
subagent domains without making scheduler or session import gateway routing.
Keep public facades and wire shapes stable while moving shared structural logic
into a neutral runtime module.

## Current-state audit

- Current HEAD: `a3a1bc4`
- Worktree status: integration clean before child worktree creation; child
  branch clean at baseline.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (not in touched
    scope)
- Files inspected:
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/scheduler/routing.py`
  - `src/opensquilla/scheduler/handlers.py`
  - `src/opensquilla/scheduler/delivery.py`
  - `src/opensquilla/session/subagent_routing.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
  - `tests/test_scheduler/test_scheduler_routing_boundary.py`
  - `tests/test_tools/test_sessions_gateway_boundary.py`
  - `tests/test_tools/test_policy_agents.py`
- Existing boundary pattern this stage follows:
  - Keep domain-owned builders in their original modules.
  - Extract shared structural helpers to a neutral non-gateway module.
  - Gateway consumes scheduler/session envelopes structurally and normalizes at
    the ingress edge.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read before child creation; created fixed child worktree
    `../opensquilla-refactor-active` with branch
    `codex/refactor-route-envelope-contract-batch`, per root `AGENTS.md`.
- `superpowers:writing-plans`:
  - Evidence: this stage plan records the neutral core boundary, worker
    ownership, RED/GREEN commands, full gate, merge, and cleanup steps before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: main-thread core setup and worker prompts require RED tests first,
    expected failure capture, then minimal implementation.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused suites,
    `scripts/refactor_gate.sh` on child, integration merge gate, and cleanup
    checks are freshly run and recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes; gateway, scheduler,
    and session read-only explorers audited independent subdomains.
  - `superpowers:subagent-driven-development` used: yes; implementation will
    dispatch independent workers after the neutral core dependency exists.
  - `spawn_agent` probe: same-thread healthcheck returned
    `spawn_agent available.` and was closed.
  - External worker fallback: not needed unless same-thread workers fail.
- Historical evidence note:
  - This record does not infer Superpowers usage for prior stages. Prior stage
    evidence must come from each stage record or current command log.

## Boundary decision

- Module batch:
  - Neutral route-envelope runtime contract under `src/opensquilla/runtime/`.
  - Gateway ingress normalization and compatibility facades.
  - Scheduler cron route facade delegation.
  - Session subagent route facade as the subagent builder source of truth.
- Responsibilities moving out:
  - Shared `ReplyTarget` value object.
  - Structural delivery field extraction.
  - Structural source-kind to `CallerKind` mapping.
  - Interaction-mode normalization.
  - Shared tool-context construction for route-envelope-like objects.
- Responsibilities staying in place:
  - `opensquilla.gateway.routing` public imports and builders.
  - `opensquilla.scheduler.routing.build_cron_route_envelope` public facade.
  - `opensquilla.session.subagent_routing.build_subagent_route_envelope` public
    session-owned builder.
  - Scheduler and session modules do not import `opensquilla.gateway.routing`.
- Public behavior that must not change:
  - Route envelope field names and values.
  - `source_kind.value` strings for web/cli/channel/cron/subagent/system.
  - Cron tool allow/deny policy and per-job `tool_policy` application.
  - Subagent `spawn_depth`, parent metadata, provenance, and unattended mode.
  - Delivery fields persisted for channel-capable reply targets.
- Files explicitly out of scope:
  - Gateway channel dispatch behavior beyond route helper calls.
  - Scheduler job persistence schema.
  - Model-router runtime scoring files from the previous batch.

## Worker ownership

### Main Thread: Neutral Core Contract

- Owns:
  - `src/opensquilla/runtime/routing.py`
  - `tests/test_runtime_routing_contract.py`
- RED tests:
  - Neutral contract can normalize source kind and interaction mode from both
    enum-like and string values.
  - Neutral contract can build delivery fields from a structural reply target.
  - Neutral contract can build cron and subagent `ToolContext` from
    route-envelope-like objects.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_runtime_routing_contract.py -q`

### Worker A: Gateway Adapter

- Owns:
  - `src/opensquilla/gateway/routing.py`
  - `tests/test_gateway/test_routing_interaction_mode.py`
- Must not edit:
  - `src/opensquilla/scheduler/routing.py`
  - `src/opensquilla/session/subagent_routing.py`
  - `src/opensquilla/gateway/task_runtime.py`
- RED tests:
  - Gateway normalizes scheduler cron envelopes into gateway `RouteEnvelope`.
  - Gateway normalizes session subagent envelopes into gateway `RouteEnvelope`.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_gateway/test_routing_interaction_mode.py tests/test_scheduler/test_scheduler_routing_boundary.py tests/test_tools/test_sessions_gateway_boundary.py tests/test_tools/test_policy_agents.py -q`

### Worker B: Scheduler Cron Facade

- Owns:
  - `src/opensquilla/scheduler/routing.py`
  - `tests/test_scheduler/test_scheduler_routing_boundary.py`
  - scheduler cron/tool-policy portions of `tests/test_tools/test_policy_agents.py`
- Must not edit:
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/session/subagent_routing.py`
  - `src/opensquilla/scheduler/handlers.py`
  - `src/opensquilla/scheduler/delivery.py`
- RED tests:
  - Scheduler may import the neutral runtime routing module but still must not
    import gateway routing.
  - Scheduler cron tool context preserves caller kind, unattended mode, cron
    hard-deny policy, source kind, channel fields, and per-job `tool_policy`.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_scheduler/test_scheduler_routing_boundary.py tests/test_tools/test_policy_agents.py tests/test_gateway/test_routing_interaction_mode.py -q`

### Worker C: Session Subagent Facade

- Owns:
  - `src/opensquilla/session/subagent_routing.py`
  - `tests/test_tools/test_sessions_gateway_boundary.py`
- Must not edit:
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/scheduler/routing.py`
  - `src/opensquilla/tools/builtin/sessions.py`
- RED tests:
  - Session subagent envelope maps through neutral/gateway tool-context
    conversion without importing gateway from session tools.
  - Session subagent route fields preserve parent session, parent task,
    `spawn_depth`, provenance, source kind, and unattended mode.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_tools/test_sessions_gateway_boundary.py tests/test_gateway/test_routing_interaction_mode.py -q`

## TDD red/green

- Baseline focused command:
  - `uv run --extra dev pytest tests/test_gateway/test_routing_interaction_mode.py tests/test_scheduler/test_scheduler_routing_boundary.py tests/test_tools/test_sessions_gateway_boundary.py tests/test_tools/test_policy_agents.py tests/test_gateway/test_router_boot.py::test_task_runtime_turn_applies_cron_job_tool_policy tests/test_gateway/test_router_boot.py::test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model -q`
  - Baseline result: `13 passed`.
- Failing test commands:
  - Main and worker RED commands listed above.
- Expected red failures:
  - Missing neutral `opensquilla.runtime.routing` helpers before core
    implementation.
  - Gateway lacks explicit structural normalization helper before Worker A.
  - Scheduler/session tests lack neutral-core coverage before Workers B/C.
- Combined focused GREEN:
  - `uv run --extra dev pytest tests/test_runtime_routing_contract.py tests/test_gateway/test_routing_interaction_mode.py tests/test_scheduler/test_scheduler_routing_boundary.py tests/test_tools/test_sessions_gateway_boundary.py tests/test_tools/test_policy_agents.py tests/test_gateway/test_router_boot.py::test_task_runtime_turn_applies_cron_job_tool_policy tests/test_gateway/test_router_boot.py::test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/runtime/routing.py src/opensquilla/gateway/routing.py src/opensquilla/scheduler/routing.py src/opensquilla/session/subagent_routing.py tests/test_runtime_routing_contract.py tests/test_gateway/test_routing_interaction_mode.py tests/test_scheduler/test_scheduler_routing_boundary.py tests/test_tools/test_sessions_gateway_boundary.py tests/test_tools/test_policy_agents.py`
  - `uv run --extra dev mypy src/opensquilla/runtime/routing.py src/opensquilla/gateway/routing.py src/opensquilla/scheduler/routing.py src/opensquilla/session/subagent_routing.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/runtime/routing.py`
  - `tests/test_runtime_routing_contract.py`
- Modify:
  - `src/opensquilla/gateway/routing.py`
  - `src/opensquilla/scheduler/routing.py`
  - `src/opensquilla/session/subagent_routing.py`
  - `tests/test_tools/test_builtin_loader.py`
  - focused tests listed above
  - `docs/refactor/stages/2026-05-19-model-router-runtime-scoring-batch.md`
    (public-file hygiene cleanup for a pre-existing absolute-path note exposed
    by this stage gate)
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty` in integration.
- [x] Create fixed child worktree `../opensquilla-refactor-active`.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-route-envelope-contract-batch`.
- [x] Run focused baseline and record `13 passed`.
- [x] Main thread writes and verifies neutral core RED/GREEN.
- [x] Dispatch Worker A/B/C with explicit ownership and TDD RED/GREEN.
- [x] Review each worker diff for ownership, public API compatibility, and
      behavior preservation.
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
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

Result before child commit:

- Focused combined route suite:
  - `20 passed` for runtime routing, gateway interaction mode, scheduler
    boundary, sessions gateway boundary, policy agents, and two router boot
    cron/model route regressions.
- Reviewer pass:
  - Gateway reviewer found no blocking issues and confirmed direct structural
    cron/subagent DTO probes through gateway normalization, delivery fields,
    and tool context.
  - Scheduler/session reviewer found one blocking import-cycle issue: making
    `runtime.routing` import `tools` caused builtin session tools to miss
    registration after importing scheduler routing. The fix keeps
    `runtime.routing` pure structural, keeps scheduler `ToolContext`
    construction in scheduler, and restores the session-owned
    `SubagentSourceKind` compatibility enum.
  - Third same-thread reviewer hit the live thread limit; external worker
    fallback was inspected but not needed after the two active reviewers plus
    main-thread gate exposed and verified the blocking issue.
- Systematic debugging evidence:
  - First child `scripts/refactor_gate.sh` failed on architecture import
    contracts, public release hygiene, and session package tool-import guard.
  - Repro confirmed that importing scheduler routing could leave
    `sessions_spawn`, `sessions_send`, `sessions_yield`, and `session_status`
    missing from the default registry.
  - Added a subprocess regression in `tests/test_tools/test_builtin_loader.py`
    proving scheduler routing import preserves those session tools.
- Focused regression after fix:
  - `30 passed` across architecture import contracts, session boundary,
    public release hygiene, builtin loader, runtime routing, gateway routing,
    scheduler routing, sessions gateway boundary, policy agents, and router
    boot checks.
- Touched-file checks:
  - Ruff passed for route files and touched focused tests.
  - Mypy passed for the four touched source files.
  - `git diff --check` passed.
- Full child `scripts/refactor_gate.sh`:
  - Ruff passed.
  - Mypy passed with no issues in 529 source files.
  - Whitespace passed.
  - Pytest passed with `2548 passed, 6 skipped, 2 warnings in 29.81s`.
  - Gateway smoke start/status/stop/status passed on `127.0.0.1:60568`.

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `50c5b77a0227` (`Refactor route envelope contract boundaries`).
- Integration merge: `8bfcdf3e4c00` (`Merge route envelope contract batch`).
- Verification evidence:
  - Child full `scripts/refactor_gate.sh`: ruff passed; mypy passed with no
    issues in 529 source files; whitespace passed; pytest `2548 passed,
    6 skipped, 2 warnings in 29.81s`; gateway smoke start/status/stop/status
    passed on `127.0.0.1:60568`.
  - Integration full `scripts/refactor_gate.sh`: ruff passed; mypy passed with
    no issues in 529 source files; whitespace passed; pytest `2548 passed,
    6 skipped, 2 warnings in 27.42s`; gateway smoke start/status/stop/status
    passed on `127.0.0.1:60702`.
  - Focused regression included the scheduler-routing import cycle guard in
    `tests/test_tools/test_builtin_loader.py`, architecture import contracts,
    session package boundary guard, public release hygiene, route contract
    tests, gateway normalization tests, scheduler boundary tests, policy-agent
    tests, sessions gateway boundary tests, and router boot cron/model route
    checks.
  - Cleanup: removed the active child worktree, ran `git worktree prune`,
    deleted the merged child branch `codex/refactor-route-envelope-contract-batch`,
    and verified the sibling `opensquilla-refactor-*` directory listing contains
    only the integration worktree.
- Residual risk:
  - Neutral `runtime.routing` is intentionally structural only. Scheduler keeps
    cron `ToolContext` construction in the scheduler layer to avoid pulling
    `tools` into the runtime package or the session package.
  - Same-thread `spawn_agent` was available for the healthcheck and two
    reviewers, then hit the thread limit on a third reviewer. External-worker
    fallback was available but not needed for additional edits after the full
    child and integration gates passed.
- Next recommended slice:
  - Continue with a coarse Tools/Gateway runtime-surface boundary batch:
    consolidate remaining route-like `ToolContext` construction paths that are
    already in packages allowed to import `tools`, while keeping `session` and
    neutral `runtime` free of `tools` imports.
