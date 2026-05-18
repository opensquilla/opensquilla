# Gateway App Server Wiring Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: gateway-app-server-wiring-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-app-server-wiring-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Worker branch: `codex/refactor-gateway-app-server-worker`
- Worker worktree: `../opensquilla-refactor-agent-app-server`
- Owner: main Codex thread coordinates architecture, prompts, review, merge,
  verification, records, and cleanup; one external Codex worker may implement
  because same-thread `spawn_agent` remains unavailable.

## Goal

Move Gateway ASGI app construction, `GatewayServer` handle attachment, and
uvicorn server startup wiring out of `gateway/boot.py` into a focused Gateway
app/server wiring boundary while preserving app state, gateway readiness timing,
managed server start behavior, public-bind warning logs, background server task
creation, channel startup ordering, router preload scheduling, and gateway
smoke behavior.

This is a single-worker implementation stage. The target logic still converges
inside `start_gateway_server`; parallel implementation workers would edit the
same boot function and create avoidable conflicts.

## Current-state audit

- Current HEAD: `47ed701` (`Record gateway cron handler cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-gateway-cron-handler-wiring-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/app.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_readiness.py`
- Symbols or command surfaces inspected:
  - `start_gateway_server`
  - `create_gateway_app`
  - `GatewayServer`
  - `uvicorn.Config`
  - `uvicorn.Server`
  - `create_background_task`
  - `is_public_bind`
  - `preload_squilla_router_runtime`
- Tests inspected:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_readiness.py`
  - gateway smoke through `scripts/refactor_gate.sh`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `src/opensquilla/gateway/channel_manager_wiring.py`
  - `src/opensquilla/gateway/cron_handler_wiring.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current conversation already read and followed the skill before
    continuing this resumed refactor line.
- `superpowers:using-git-worktrees`:
  - Evidence: inspected integration state and created isolated active child
    worktree `../opensquilla-refactor-active` on
    `codex/refactor-gateway-app-server-wiring-boundary`.
- `superpowers:writing-plans`:
  - Evidence: wrote this stage record before production edits.
- `superpowers:test-driven-development`:
  - Evidence: worker wrote `tests/test_gateway/test_app_server_wiring_boundary.py`
    before production edits and observed the required RED failures.
- `superpowers:verification-before-completion`:
  - Evidence: worker ran focused GREEN tests and touched-file checks after
    implementation; child `scripts/refactor_gate.sh`, integration
    `scripts/refactor_gate.sh`, merge records, and cleanup evidence remain
    required before claiming the overall stage complete.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes for the decision.
    Implementation is intentionally single-worker because all production paths
    edit `start_gateway_server` in `boot.py`.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slot `app-server`. Do not fall back to unrecorded serial work unless the
    external worker route is blocked.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway ASGI app/server boot wiring boundary.
- Responsibilities moving out:
  - Calling `create_gateway_app` with the boot dependencies.
  - Setting `app.state.gateway_ready = False` before channel startup.
  - Creating `GatewayServer(app=app, config=config)`.
  - Attaching `_channel_manager`, `_services`, and
    `_background_completion_manager` to the handle.
  - When `run=True`, creating `uvicorn.Config`, `uvicorn.Server`, scheduling
    `server.serve()` with `create_background_task`, attaching `_server` and
    `_task`, preserving public-bind warning behavior, and logging
    `gateway.started`.
- Responsibilities staying in place:
  - Config loading, service build, runtime wiring, cron handler registration,
    channel manager wiring, channel startup, router preload scheduling,
    readiness flip to `True`, and return of `GatewayServer`.
- New module/file responsibility:
  - `src/opensquilla/gateway/app_server_wiring.py` owns app creation and
    managed uvicorn server startup wiring for gateway boot.
  - A function such as `build_gateway_app_server(...)` returns a
    `GatewayServer` whose `app.state.gateway_ready` is already `False`.
- Public behavior that must not change:
  - `start_gateway_server(..., run=False)` returns a `GatewayServer` with app
    state populated exactly as before.
  - `start_gateway_server(..., run=True)` schedules `server.serve()` before
    channel startup and router preload.
  - Public-bind warning event and message remain unchanged.
  - `gateway.started` log event remains unchanged.
  - Channel startup still happens after app/server wiring.
  - Router preload still schedules after channel startup.
  - `app.state.gateway_ready` flips to `True` only after channel startup and
    optional router preload scheduling.
  - Gateway smoke start/status/stop/status behavior remains unchanged.
- Files explicitly out of scope:
  - `gateway/app.py` route construction internals.
  - Channel manager wiring internals.
  - Cron handler wiring internals.
  - Runtime wiring internals.
  - Web UI/static files.
  - Migrations and dependency lock files.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_app_server_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_readiness.py -q`
- RED output:
  - Exit code: 1
  - Summary: `3 failed, 3 passed in 2.98s`
  - Failures:
    - `AssertionError: assert 'build_gateway_app_server' in {...}` in
      `test_boot_delegates_app_server_wiring_to_gateway_boundary`
    - `ModuleNotFoundError: No module named 'opensquilla.gateway.app_server_wiring'`
      in both app-server wiring behavior tests.
- Expected red failure:
  - `src/opensquilla/gateway/app_server_wiring.py` does not exist, or AST
    boundary tests show `start_gateway_server` still directly calls
    `create_gateway_app`, `GatewayServer`, `uvicorn.Config`, `uvicorn.Server`,
    or `create_background_task(server.serve())`.
- Behavior compatibility coverage:
  - New boundary tests verify module exports, dependency flow into
    `create_gateway_app`, server handle attachments, readiness false before
    return to boot, run=False no-op server startup, run=True uvicorn/task
    attachment, and public bind warning/start logs.
  - Existing router boot test verifies channel startup still precedes router
    preload scheduling.
  - Existing readiness tests verify `gateway_ready` behavior.
- Module-batch implementation:
  - Create `gateway/app_server_wiring.py`.
  - Replace app/server setup in `start_gateway_server` with a short delegator
    call returning `server_handle`.
  - Keep the final channel startup, router preload scheduling, readiness true
    flip, and return in `boot.py`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_app_server_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_readiness.py -q`
- GREEN output:
  - Exit code: 0
  - Summary: `7 passed in 0.51s`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/app_server_wiring.py tests/test_gateway/test_app_server_wiring_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
  - `git diff --check`
- Touched-file check output:
  - Ruff exit code: 0; `All checks passed!`
  - Mypy exit code: 0; `Success: no issues found in 93 source files`
  - `git diff --check` exit code: 0; no output.
- Full child gate command:
  - `scripts/refactor_gate.sh`
- Full child gate output:
  - Exit code: 0
  - Ruff: `All checks passed!`
  - Mypy: `Success: no issues found in 550 source files`
  - Pytest: `2657 passed, 8 skipped, 2 warnings in 54.23s`
  - Gateway smoke: start/status/stop/status all returned `{"ok": true, ...}`.
  - Final line: `Refactor gate complete.`

## Files

- Create:
  - `src/opensquilla/gateway/app_server_wiring.py`
  - `tests/test_gateway/test_app_server_wiring_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_readiness.py`
- Documentation:
  - This stage record.

## Steps

- [ ] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [ ] Commit this stage plan on the active child branch.
- [ ] Create external worker worktree from the active child branch.
- [x] Worker writes failing boundary tests and records RED output.
- [x] Worker implements `gateway/app_server_wiring.py` and replaces the inline
      app/server wiring block with a short delegator call.
- [x] Main thread reviews diff for behavior compatibility and boundary scope.
  - Result: reviewed worker diff after `9ed9de8`; changed files were limited to
    this stage record, `gateway/boot.py`, new `gateway/app_server_wiring.py`,
    and new `test_app_server_wiring_boundary.py`.
  - Boundary check: app/server creation and managed uvicorn startup moved to
    `build_gateway_app_server`; `boot.py` still owns channel startup, router
    preload scheduling, final readiness flip, and return of `GatewayServer`.
- [x] Run focused green command and touched-file checks.
  - Main-thread focused GREEN after merging worker branch:
    `uv run --extra dev pytest tests/test_gateway/test_app_server_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_readiness.py -q`
    passed with `7 passed in 4.22s`.
  - Main-thread touched-file checks:
    `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/app_server_wiring.py tests/test_gateway/test_app_server_wiring_boundary.py`
    passed; `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
    passed with no issues in 93 source files; `git diff --check` passed.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - Main-thread child gate after worker merge passed:
    `2657 passed, 8 skipped, 2 warnings in 58.14s`; gateway smoke
    start/status/stop/status returned `{"ok": true, ...}` and final line was
    `Refactor gate complete.`
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active` and
      `../opensquilla-refactor-agent-app-server`, run `git worktree prune`,
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

- Revert the integration merge commit if app construction, readiness, managed
  uvicorn startup, public-bind warnings, channel startup ordering, router
  preload ordering, or gateway smoke behavior regresses.
- Keep the child branch and worker branch for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Worker commit: this worker implementation commit; hash reported in worker
  final response: `9ed9de8cd3e92c52547e9e305c74670067b07386`.
- Active child support commits:
  - Stage plan: `eb84b77`
  - Worker merge: `257262c`
- Child verification commit: pending this record update.
- Integration merge:
- Integration record:
- Verification evidence: worker RED/GREEN/touched-file checks and full child
  gate recorded above; main-thread focused GREEN, touched-file checks, diff
  review, and full child gate recorded above after merging worker branch.
- Cleanup evidence: pending main-thread merge and worktree cleanup.
- Residual risk: low; boot still owns channel startup, router preload
  scheduling, and the final readiness flip after delegating app/server wiring.
- Next recommended slice:
