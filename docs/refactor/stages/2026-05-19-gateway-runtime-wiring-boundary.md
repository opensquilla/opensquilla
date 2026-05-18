# Gateway Runtime Wiring Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: gateway-runtime-wiring-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-runtime-wiring-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Worker branch: `codex/refactor-gateway-runtime-wiring-worker`
- Worker worktree: `../opensquilla-refactor-agent-gateway-runtime`
- Owner: main Codex thread coordinates and reviews; one external Codex worker
  may implement because same-thread `spawn_agent` is still at its thread limit.

## Goal

Move Gateway runtime startup wiring for heartbeat, background completion, and
`TaskRuntime` construction out of `gateway/boot.py` into a focused Gateway
runtime wiring boundary while preserving public boot behavior, channel delivery,
cron delivery, session locks, runtime event emission, diagnostics wiring, and
gateway smoke behavior.

This is intentionally a single-worker stage: the target logic converges inside
`start_gateway_server` and editing `boot.py` from multiple branches would create
avoidable conflicts.

## Current-state audit

- Current HEAD: `ff66d87` (`Record session runtime facade cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-session-runtime-facade-boundary-batch.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/background_completion.py`
  - `src/opensquilla/gateway/event_bridge.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_task_runtime_streaming_boundary.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
- Symbols or command surfaces inspected:
  - `start_gateway_server`
  - `build_services`
  - `build_turn_runner_from_services`
  - `TaskRuntime`
  - `BackgroundCompletionManager`
  - `HeartbeatService`
  - `HeartbeatLoop`
  - `HeartbeatConfigWatcher`
  - `EventBridge`
  - `create_gateway_app`
- Tests inspected:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_task_runtime_streaming_boundary.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/gateway/provider_bootstrap.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`
  - `src/opensquilla/memory/gateway_runtime.py`

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read current skill instructions; created isolated active child
    worktree `../opensquilla-refactor-active` on
    `codex/refactor-gateway-runtime-wiring-boundary`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions; wrote this stage record before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: read current skill instructions; this stage requires RED boundary
    tests before adding `gateway/runtime_wiring.py` or changing `boot.py`.
- `superpowers:verification-before-completion`:
  - Evidence: must read/use current skill before claiming this stage complete;
    focused tests, touched-file checks, child `scripts/refactor_gate.sh`,
    integration `scripts/refactor_gate.sh`, merge records, and cleanup evidence
    are required.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes for the decision. The
    stage was assessed for parallelism and intentionally kept single-worker
    because all implementation paths edit `start_gateway_server` in `boot.py`.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slot `gateway-runtime` if implementation is delegated. Do not fall back to
    unrecorded serial work unless the external worker route is blocked.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway runtime startup wiring boundary.
- Responsibilities moving out:
  - Heartbeat service/loop/watcher construction and startup.
  - Runtime event bridge construction.
  - Background completion manager construction and registration.
  - `TaskRuntime` construction, lock-provider handoff to `TurnRunner`, session
    manager runtime attachment, and tool-service runtime registration.
  - Subagent completion listener closure that bridges task runtime completion to
    announcement delivery.
- Responsibilities staying in place:
  - Gateway config loading, auth token generation, file logging, PID lock, and
    `build_services` invocation.
  - `build_turn_runner_from_services` creation.
  - Cron handler registration and channel manager creation until a later stage.
  - ASGI app construction and uvicorn server lifecycle.
  - Public compatibility helpers in `boot.py`.
- New module/file responsibility:
  - `src/opensquilla/gateway/runtime_wiring.py` owns Gateway runtime wiring for
    heartbeat, background completion, and `TaskRuntime` startup.
  - A small return object such as `GatewayRuntimeWiring` exposes
    `heartbeat_service`, `heartbeat_loop`, `heartbeat_watcher`,
    `task_runtime`, `runtime_event_bridge`, and
    `background_completion_manager` back to `boot.py`.
- Public behavior that must not change:
  - `start_gateway_server(..., run=False)` behavior and returned
    `GatewayServer` state.
  - Gateway app state fields and readiness timing.
  - Shared diagnostics state between app and turn runner.
  - Task runtime session-lock sharing with `TurnRunner`.
  - Session manager cascade-cancel attachment.
  - Background subagent completion announcements.
  - Heartbeat start order and override loading.
  - Cron delivery and channel delivery behavior.
  - Gateway smoke start/status/stop behavior.
- Files explicitly out of scope:
  - Provider runtime modules.
  - Memory runtime modules.
  - Scheduler handler internals.
  - Channel transport/dispatch modules.
  - Web UI/static files.
  - Migrations and dependency lock files.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_runtime_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_task_runtime_streaming_boundary.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/runtime_wiring.py` does not exist, or AST boundary
    tests show `start_gateway_server` still directly imports/constructs
    `TaskRuntime`, `BackgroundCompletionManager`, `HeartbeatService`,
    `HeartbeatLoop`, `HeartbeatConfigWatcher`, or `EventBridge`.
- Behavior compatibility coverage:
  - Existing `start_gateway_server(..., run=False)` tests still verify shared
    diagnostics state and router preload ordering.
  - Existing task runtime streaming tests still verify boot compatibility
    aliases and runtime stream emission behavior.
  - Focused new tests verify runtime wiring module ownership and behavior
    wiring with test doubles where practical.
- Module-batch implementation:
  - Create `gateway/runtime_wiring.py`.
  - Replace the relevant `start_gateway_server` inline block with a short
    delegator call and assignments from the returned wiring object.
  - Preserve existing parameter names and object references so later cron,
    channel, and app construction blocks behave the same.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_runtime_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_task_runtime_streaming_boundary.py tests/test_gateway/test_background_completion.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_no_split_brain_lock.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/runtime_wiring.py tests/test_gateway/test_runtime_wiring_boundary.py tests/test_gateway/test_router_boot.py`
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `tests/test_gateway/test_runtime_wiring_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_task_runtime_streaming_boundary.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_task_runtime_execution_boundary.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
  - Result: preflight passed on active child worktree at `ff66d87`.
- [x] Commit this stage plan on the active child branch.
  - Commit: `20f0c41` (`Plan gateway runtime wiring boundary`).
- [x] Create external worker worktree from the active child branch if
      implementation is delegated.
  - Worker worktree: `../opensquilla-refactor-agent-gateway-runtime`.
- [x] Worker or main thread writes failing boundary tests and records RED output.
  - RED command:
    `uv run --extra dev pytest tests/test_gateway/test_runtime_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_task_runtime_streaming_boundary.py -q`
  - Expected failures observed: `runtime_wiring.py` missing, boot missing
    `build_gateway_runtime_wiring` delegation, and import of
    `opensquilla.gateway.runtime_wiring` failed.
- [x] Implement `gateway/runtime_wiring.py` and replace inline boot wiring with
      a short delegator.
- [x] Review diff and verify no public behavior changed.
  - Worker commit: `153d710` (`refactor: extract gateway runtime wiring`).
  - Main-thread hygiene fix commit: `972f278` (`Fix session runtime stage path
    hygiene`).
  - Worker merge commit: `3bcbcdd` (`Merge gateway runtime wiring worker`).
  - Main-thread cleanup commit: `0e6495f` (`Polish gateway runtime wiring
    boundary`).
- [x] Run focused green command and touched-file checks.
  - Focused GREEN: `28 passed in 4.65s`.
  - Touched-file `ruff check`: passed.
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`:
    no issues in 90 source files; existing pyproject unused-section notes only.
  - `git diff --check`: passed.
  - Public-release hygiene retest for the prior stage path fix:
    `1 passed in 0.42s`.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - Result: ruff passed; mypy no issues in 547 source files; whitespace passed;
    pytest `2638 passed, 8 skipped, 2 warnings in 52.06s`; gateway smoke
    start/status/stop/status passed.
- [ ] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove active and worker worktrees, run `git worktree prune`, and verify
      no extra refactor worktree directories remain beyond
      `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if gateway boot or runtime task handling
  regresses.
- Keep the child branch and worker branch for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Worker commit: `153d710` (`refactor: extract gateway runtime wiring`).
- Active child support commits:
  - `972f278` (`Fix session runtime stage path hygiene`)
  - `3bcbcdd` (`Merge gateway runtime wiring worker`)
  - `0e6495f` (`Polish gateway runtime wiring boundary`)
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Worker RED/GREEN evidence recorded above.
- Worker focused GREEN: `28 passed in 0.85s`.
- Worker touched-file checks passed.
- Worker full gate reached full pytest and failed only on pre-existing public
  release hygiene in the prior stage record.
- Main-thread public-release hygiene retest after path cleanup: `1 passed in
  0.42s`.
- Main-thread focused GREEN: `28 passed in 4.65s`.
- Main-thread touched-file checks: ruff passed; mypy no issues in 90 gateway
  source files; `git diff --check` passed.
- Active child `scripts/refactor_gate.sh`: ruff passed; mypy no issues in 547
  source files; whitespace passed; pytest `2638 passed, 8 skipped, 2
  warnings`; gateway smoke passed.
- Cleanup evidence:
- Residual risk: low; the stage moves runtime wiring behind a Gateway boundary
  while preserving boot behavior through focused start-gateway tests and the
  full refactor gate.
- Next recommended slice: channel manager boot/wiring extraction is a natural
  follow-up, but it also converges on `start_gateway_server`; keep it
  single-worker unless a scout finds a disjoint file-only subdomain.
