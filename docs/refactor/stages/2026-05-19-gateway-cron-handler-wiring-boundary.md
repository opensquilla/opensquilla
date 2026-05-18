# Gateway Cron Handler Wiring Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: gateway-cron-handler-wiring-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-cron-handler-wiring-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Worker branch: `codex/refactor-gateway-cron-handler-worker`
- Worker worktree: `../opensquilla-refactor-agent-cron-handler`
- Owner: main Codex thread coordinates architecture, prompts, review, merge,
  verification, records, and cleanup; one external Codex worker may implement
  because same-thread `spawn_agent` remains unavailable.

## Goal

Move gateway cron handler registration wiring out of `gateway/boot.py` into a
focused Gateway cron handler wiring boundary while preserving scheduler handler
registration, cron delivery chain dependencies, system-event session fanout,
workspace resolution, memory Dream handler construction, Dream auto-schedule
registration, channel delivery through the lazy channel-manager reference, and
gateway smoke behavior.

This is a single-worker implementation stage. The target logic still converges
inside `start_gateway_server`; parallel implementation workers would edit the
same boot function and create avoidable conflicts. The parallelism decision was
still made explicitly under `superpowers:dispatching-parallel-agents`.

## Current-state audit

- Current HEAD: `7ec9fc9` (`Record gateway channel manager cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-gateway-channel-manager-wiring-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`
  - `src/opensquilla/scheduler/handlers.py`
  - `src/opensquilla/scheduler/dream_handler.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_cron_result_delivery_boundary.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
  - `tests/test_scheduler/test_dream_handler.py`
- Symbols or command surfaces inspected:
  - `start_gateway_server`
  - `_register_dream_crons`
  - `_configured_agent_ids`
  - `deliver_session_event`
  - `build_cron_delivery_chain`
  - `make_agent_run_handler`
  - `make_system_event_handler`
  - `make_memory_dream_handler`
  - `build_dream_factory`
  - `resolve_agent_workspace_dir`
- Tests inspected:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_cron_result_delivery_boundary.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
  - `tests/test_scheduler/test_dream_handler.py`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `src/opensquilla/gateway/channel_manager_wiring.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current conversation already read and followed the skill before
    continuing this resumed refactor line.
  - Worker evidence: external worker re-read the requested Superpowers skills
    before writing boundary tests or production code.
- `superpowers:using-git-worktrees`:
  - Evidence: inspected integration state and created isolated active child
    worktree `../opensquilla-refactor-active` on
    `codex/refactor-gateway-cron-handler-wiring-boundary`.
- `superpowers:writing-plans`:
  - Evidence: wrote this stage record before production edits.
- `superpowers:test-driven-development`:
  - Evidence: this stage requires RED boundary tests before adding
    `gateway/cron_handler_wiring.py` or changing `boot.py`.
  - Worker RED:
    `uv run --extra dev pytest tests/test_gateway/test_cron_handler_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_dream_boot_does_not_register_when_auto_schedule_is_off tests/test_gateway/test_cron_result_delivery_boundary.py -q`
    failed with 10 new boundary-test failures and 6 existing focused tests
    passing. Expected failures included missing
    `src/opensquilla/gateway/cron_handler_wiring.py`, missing
    `register_gateway_cron_handlers` delegation from `start_gateway_server`,
    direct boot imports/calls for cron handler factories, and
    `ModuleNotFoundError` for the new boundary.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    records, and cleanup evidence are required before claiming this stage
    complete.
  - Worker GREEN:
    `uv run --extra dev pytest tests/test_gateway/test_cron_handler_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_dream_boot_does_not_register_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_disabled tests/test_gateway/test_cron_result_delivery_boundary.py tests/test_scheduler/test_dream_handler.py -q`
    passed with 22 tests.
  - Worker touched-file checks:
    `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/cron_handler_wiring.py tests/test_gateway/test_cron_handler_wiring_boundary.py`
    passed; `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
    passed with no issues in 92 source files; `git diff --check` passed.
    A broader touched-test ruff check including
    `tests/test_gateway/test_cron_result_delivery_boundary.py` also passed.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes for the decision.
    Implementation is intentionally single-worker because all production paths
    edit `start_gateway_server` in `boot.py`.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
- External worker fallback: use `scripts/refactor_external_agent.sh` with slot
  `cron-handler`. Do not fall back to unrecorded serial work unless the
  external worker route is blocked.
  - Worker evidence: this substage ran in external-worker fallback because
    same-thread `spawn_agent` failed with `agent thread limit reached`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway cron handler boot registration boundary.
- Responsibilities moving out:
  - Constructing the cron delivery chain.
  - Building the `agent_run`, `system_event`, and `memory_dream` handlers.
  - Registering scheduler handlers and logging `gateway.cron_handler_registered`.
  - Building the system-event session emitter with websocket registry delivery.
  - Resolving cron agent workspaces from agent config.
  - Calling the Dream cron registrar with configured agent ids.
- Responsibilities staying in place:
  - Dream cron registration helper `_register_dream_crons` may remain in
    `boot.py` unless moving it is necessary and covered by tests.
  - Config loading, service build, runtime wiring, channel manager wiring, app
    construction, uvicorn lifecycle, and router preload scheduling stay in
    `start_gateway_server`.
- New module/file responsibility:
  - `src/opensquilla/gateway/cron_handler_wiring.py` owns scheduler handler
    registration wiring for gateway boot.
  - A function such as `register_gateway_cron_handlers(...)` accepts explicit
    dependencies and returns after registering handlers and Dream schedules.
- Public behavior that must not change:
  - No-op when `svc.cron_scheduler is None`.
  - Handler keys remain `agent_run`, `system_event`, and `memory_dream`.
  - Log events remain `gateway.cron_handler_registered` with the same
    `handler_key` values.
  - Delivery chain still receives the lazy channel-manager reference,
    subscription manager, and session manager.
  - System-event fanout still uses `deliver_session_event` and `get_registry`.
  - Workspace resolution still uses `resolve_agent_workspace_dir` and
    `config.workspace_strict`.
  - Dream handler still uses `build_dream_factory` and skips when
    `config.memory.dream.enabled` is false.
  - Dream auto-schedule registration still uses `_register_dream_crons` and
    `_configured_agent_ids(config)`.
  - Gateway smoke behavior remains unchanged.
- Files explicitly out of scope:
  - Scheduler handler internals.
  - Cron delivery chain internals.
  - Dream handler internals.
  - Channel manager wiring internals.
  - Web UI/static files.
  - Migrations and dependency lock files.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_cron_handler_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_dream_boot_does_not_register_when_auto_schedule_is_off tests/test_gateway/test_cron_result_delivery_boundary.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/cron_handler_wiring.py` does not exist, or AST
    boundary tests show `start_gateway_server` still directly imports/calls
    `make_agent_run_handler`, `make_system_event_handler`,
    `make_memory_dream_handler`, `build_dream_factory`, or
    `build_cron_delivery_chain`.
- Behavior compatibility coverage:
  - New boundary tests verify module exports, no-op without cron scheduler,
    handler registration keys/log events, dependency flow to handler factories,
    system-event emitter wiring, workspace resolver behavior, and Dream cron
    registrar invocation.
  - Existing Dream boot tests verify fail-closed auto-schedule behavior.
  - Existing cron delivery tests verify downstream delivery chain behavior.
- Module-batch implementation:
  - Create `gateway/cron_handler_wiring.py`.
  - Replace the relevant `start_gateway_server` inline cron registration block
    with a short delegator call.
  - Preserve helper names and dependency references where later boot blocks
    depend on them.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_cron_handler_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_dream_boot_does_not_register_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_disabled tests/test_gateway/test_cron_result_delivery_boundary.py tests/test_scheduler/test_dream_handler.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/cron_handler_wiring.py tests/test_gateway/test_cron_handler_wiring_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/cron_handler_wiring.py`
  - `tests/test_gateway/test_cron_handler_wiring_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
  - `tests/test_gateway/test_cron_result_delivery_boundary.py`
- Test:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_cron_result_delivery_boundary.py`
  - `tests/test_scheduler/test_dream_handler.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
  - Result: preflight passed on active child worktree at `7ec9fc9`, with this
    plan file present as an intentional dirty change.
- [x] Commit this stage plan on the active child branch.
  - Commit: `6d8e413` (`Plan gateway cron handler wiring boundary`).
- [x] Create external worker worktree from the active child branch.
  - Worker worktree: `../opensquilla-refactor-agent-cron-handler`.
  - Worker branch: `codex/refactor-gateway-cron-handler-worker`.
- [x] Worker writes failing boundary tests and records RED output.
- [x] Worker implements `gateway/cron_handler_wiring.py` and replaces the
      inline boot cron registration block with a short delegator call.
- [x] Main thread reviews diff for behavior compatibility and boundary scope.
  - Worker commit: `f1cfb49` (`Refactor gateway cron handler wiring boundary`).
  - Active child merge commit: `6c5bfe0` (`Merge gateway cron handler worker`).
- [x] Run focused green command and touched-file checks.
  - Focused GREEN: `22 passed in 3.01s`.
  - Touched-file `ruff check`: passed.
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`:
    success, no issues in 92 source files; existing pyproject unused-section
    notes only.
  - `git diff --check`: passed.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - Result: ruff passed; mypy no issues in 549 source files; whitespace passed;
    pytest `2654 passed, 8 skipped, 2 warnings in 54.37s`; gateway smoke
    start/status/stop/status passed.
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active` and
      `../opensquilla-refactor-agent-cron-handler`, run `git worktree prune`,
      and verify no extra refactor worktree directories remain beyond
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

- Revert the integration merge commit if cron handler registration, Dream
  scheduling, delivery fanout, or gateway smoke behavior regresses.
- Keep the child branch and worker branch for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Worker commit: `f1cfb49` (`Refactor gateway cron handler wiring boundary`).
- Active child support commits:
  - `6c5bfe0` (`Merge gateway cron handler worker`).
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
  - RED command failed as expected with 10 new boundary-test failures and 6
    existing focused tests passing before production changes.
  - GREEN focused command passed with 22 tests after moving cron handler wiring.
  - Touched checks passed: ruff for `boot.py`,
    `cron_handler_wiring.py`, and the new boundary test; mypy for
    `src/opensquilla/gateway`; `git diff --check`.
  - Main-thread focused GREEN:
    `uv run --extra dev pytest tests/test_gateway/test_cron_handler_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_dream_boot_does_not_register_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_auto_schedule_is_off tests/test_gateway/test_router_boot.py::test_dream_boot_pauses_existing_jobs_when_disabled tests/test_gateway/test_cron_result_delivery_boundary.py tests/test_scheduler/test_dream_handler.py -q`
    -> 22 passed in 3.01s.
  - Main-thread touched-file checks: ruff passed; gateway mypy no issues in 92
    source files; `git diff --check` passed.
  - Active child `scripts/refactor_gate.sh`: ruff passed; mypy no issues in
    549 source files; whitespace passed; pytest `2654 passed, 8 skipped, 2
    warnings`; gateway smoke passed.
- Cleanup evidence:
- Residual risk: low before integration merge; the stage moves cron handler
  boot wiring behind a gateway boundary while preserving handler keys, delivery
  chain dependencies, session event delivery, workspace resolution, Dream cron
  registration, focused tests, and the full child gate.
- Next recommended slice: gateway app/server-handle construction wiring is the
  next visible boot boundary, but it still touches `start_gateway_server`; keep
  it single-worker unless a scout finds a disjoint module-only slice.
