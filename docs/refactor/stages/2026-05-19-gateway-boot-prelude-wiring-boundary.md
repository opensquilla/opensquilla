# Gateway Boot Prelude Wiring Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: gateway-boot-prelude-wiring-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-boot-prelude-wiring-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Worker branch: `codex/refactor-gateway-boot-prelude-worker`
- Worker worktree: `../opensquilla-refactor-agent-boot-prelude`
- Owner: main Codex thread coordinates architecture, prompts, review, merge,
  verification, records, and cleanup; one external Codex worker may implement
  because same-thread `spawn_agent` remains unavailable.

## Goal

Move Gateway boot prelude setup out of `gateway/boot.py` into a focused boundary
module while preserving config loading, runtime port override, file logging,
gateway port environment export, runtime token generation, Control UI static
directory logging, skill-filter startup banner, PID lock acquisition, service
build ordering, and gateway smoke behavior.

This is a single-worker implementation stage. The target logic still converges
inside `start_gateway_server`; parallel implementation workers would edit the
same boot prelude block and create avoidable conflicts.

## Current-state audit

- Current HEAD: `57e033f` (`Record gateway app server cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-gateway-app-server-wiring-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/pidlock.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_pidfile_lock.py`
  - `tests/test_gateway/test_runtime_wiring_boundary.py`
- Symbols or command surfaces inspected:
  - `start_gateway_server`
  - `GatewayConfig.load`
  - `_setup_file_logging`
  - `emit_skill_filter_banner`
  - `_state_path`
  - `GatewayPidLock.acquire`
  - Control UI `_STATIC_DIR` and `_TEMPLATE_DIR`
- Tests inspected:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_pidfile_lock.py`
  - `tests/test_gateway/test_runtime_wiring_boundary.py`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `src/opensquilla/gateway/cron_handler_wiring.py`
  - `src/opensquilla/gateway/channel_manager_wiring.py`
  - `src/opensquilla/gateway/app_server_wiring.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current resumed work re-read the Superpowers entrypoint and
    relevant stage skills before selecting this slice.
- `superpowers:using-git-worktrees`:
  - Evidence: integration status was inspected at `57e033f`; isolated child
    worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-gateway-boot-prelude-wiring-boundary`.
- `superpowers:writing-plans`:
  - Evidence: this stage record was written before production edits.
- `superpowers:test-driven-development`:
  - Evidence: this stage requires RED boundary tests before adding
    `gateway/boot_prelude_wiring.py` or changing `boot.py`.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    records, and cleanup evidence are required before claiming this stage
    complete.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes for the decision.
    Implementation is intentionally single-worker because all production paths
    edit the same `start_gateway_server` prelude block in `boot.py`.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slot `boot-prelude`. Do not fall back to unrecorded serial work unless the
    external worker route is blocked.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway boot prelude setup boundary.
- Responsibilities moving out:
  - Loading `GatewayConfig` from `OPENSQUILLA_GATEWAY_CONFIG_PATH` when no
    explicit config is supplied.
  - Applying the runtime `port` override with `model_copy`.
  - Calling `_setup_file_logging` and logging `gateway.config_loaded`.
  - Exporting `OPENSQUILLA_GATEWAY_PORT`.
  - Generating a runtime auth token, marking `auth.token` as runtime secret,
    and logging `gateway.auth_token_generated`.
  - Resolving/logging Control UI template/static directories and disabled state.
  - Emitting the skill-filter startup banner.
  - Acquiring `GatewayPidLock` before `build_services`.
- Responsibilities staying in place:
  - Service construction, boot time recording, `gateway.starting` logging,
    diagnostics state, TurnRunner setup, runtime wiring, cron handler
    registration, channel manager wiring, app/server wiring, channel startup,
    router preload scheduling, readiness flip, and return of `GatewayServer`.
- New module/file responsibility:
  - `src/opensquilla/gateway/boot_prelude_wiring.py` owns the behavior-compatible
    prelude setup and returns both the effective `GatewayConfig` and PID lock
    object so `start_gateway_server` can keep the lock alive.
- Public behavior that must not change:
  - Explicit config objects are reused except for the documented runtime port
    override.
  - Runtime auth token generation and `mark_runtime_secret("auth.token")`
    remain unchanged.
  - `OPENSQUILLA_GATEWAY_PORT` reflects the effective config port.
  - Control UI log events and paths remain unchanged.
  - `emit_skill_filter_banner(config.skills)` remains part of boot startup.
  - PID lock is acquired before `build_services` and remains alive for the
    returned gateway server lifetime.
  - Existing router boot tests and gateway smoke behavior remain unchanged.
- Files explicitly out of scope:
  - Service construction internals.
  - Runtime wiring, cron wiring, channel wiring, and app/server wiring internals.
  - `GatewayPidLock` implementation.
  - Control UI route/static implementation.
  - Web UI assets, dependency locks, migrations, and release docs.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_boot_prelude_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_pidfile_lock.py -q`
- Actual RED output:
  - `6 failed, 3 passed in 0.58s`
  - New boundary failures:
    - `test_boot_prelude_wiring_module_exports_builder_contract`:
      `BOOT_PRELUDE.exists()` was false.
    - `test_boot_delegates_prelude_setup_to_gateway_boundary`: import for
      `opensquilla.gateway.boot_prelude_wiring.build_gateway_boot_prelude` was
      absent from `boot.py`.
    - Four behavior/delegation tests failed with
      `ModuleNotFoundError: No module named 'opensquilla.gateway.boot_prelude_wiring'`.
- Expected red failure:
  - `src/opensquilla/gateway/boot_prelude_wiring.py` does not exist, or AST
    boundary tests show `start_gateway_server` still directly performs config
    load/port override/env/auth/control-ui/banner/PID-lock setup.
- Behavior compatibility coverage:
  - New boundary tests verify module export, config loading from env path,
    explicit config reuse, port override, logging setup/config-loaded event,
    gateway port env export, runtime auth token generation/secret marking,
    Control UI enabled/disabled log events, skill banner invocation, PID lock
    acquisition before service build, and lock retention through the returned
    prelude object.
  - Existing router boot tests verify downstream diagnostics and router preload
    behavior still works after the prelude delegation.
  - Existing pidfile lock tests verify lock file placement remains unchanged.
- Module-batch implementation:
  - Create `gateway/boot_prelude_wiring.py`.
  - Replace the relevant `start_gateway_server` inline prelude block with a
    short delegator call returning the effective config and PID lock.
  - Keep service construction and all later boot wiring in `boot.py`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_boot_prelude_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_pidfile_lock.py -q`
  - Output: `9 passed in 0.51s`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/boot_prelude_wiring.py tests/test_gateway/test_boot_prelude_wiring_boundary.py`
    - Output: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
    - Output: `Success: no issues found in 94 source files`
  - `git diff --check`
    - Output: no output; exit 0.

## Files

- Create:
  - `src/opensquilla/gateway/boot_prelude_wiring.py`
  - `tests/test_gateway/test_boot_prelude_wiring_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_pidfile_lock.py`
- Documentation:
  - This stage record.

## Steps

- [ ] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [ ] Commit this stage plan on the active child branch.
- [ ] Create external worker worktree from the active child branch.
- [x] Worker writes failing boundary tests and records RED output.
- [x] Worker implements `gateway/boot_prelude_wiring.py` and replaces the
      inline prelude setup with a short delegator call.
- [x] Main thread reviews diff for behavior compatibility and boundary scope.
  - Result: reviewed worker diff after `3de6670`; changed files were limited to
    this stage record, `gateway/boot.py`, new
    `gateway/boot_prelude_wiring.py`, and new
    `test_boot_prelude_wiring_boundary.py`.
  - Boundary check: config load/port/logging/env/auth/Control UI/banner/PID
    lock setup moved to `build_gateway_boot_prelude`; `boot.py` still owns
    `build_services`, boot time, `gateway.starting`, diagnostics, TurnRunner,
    runtime/cron/channel/app-server wiring, channel startup, router preload,
    readiness, and return.
  - PID lock check: `GatewayServer` now retains `_pid_lock` so the acquired lock
    remains reachable from the returned handle.
- [x] Run focused green command and touched-file checks.
  - Main-thread focused GREEN after merging worker branch:
    `uv run --extra dev pytest tests/test_gateway/test_boot_prelude_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_pidfile_lock.py -q`
    passed with `9 passed in 3.23s`.
  - Main-thread touched-file checks:
    `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/boot_prelude_wiring.py tests/test_gateway/test_boot_prelude_wiring_boundary.py`
    passed; `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
    passed with no issues in 94 source files; `git diff --check` passed.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - Main-thread child gate after worker merge passed:
    `2663 passed, 8 skipped, 2 warnings in 54.00s`; gateway smoke
    start/status/stop/status returned `{"ok": true, ...}` and final line was
    `Refactor gate complete.`
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
  - Integration merge: `a14b463`
- [x] Run `scripts/refactor_gate.sh` in integration.
  - Integration gate passed: `2665 passed, 6 skipped, 2 warnings in 27.96s`;
    gateway smoke start/status/stop/status returned `{"ok": true, ...}` and
    final line was `Refactor gate complete.`
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active` and
      `../opensquilla-refactor-agent-boot-prelude`, run `git worktree prune`,
      and verify no extra refactor worktree directories remain beyond
      `../opensquilla-refactor-integration`.
  - Cleanup command removed both worktrees and ran `git worktree prune`.
  - Final worktree list no longer includes `opensquilla-refactor-active` or
    `opensquilla-refactor-agent-boot-prelude`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`
- Actual worker output:
  - `scripts/refactor_gate.sh`
  - Ruff: `All checks passed!`
  - Mypy: `Success: no issues found in 551 source files`
  - Whitespace: exit 0.
  - Pytest: `2663 passed, 8 skipped, 2 warnings in 52.04s`
  - Gateway smoke: start/status/stop/status all returned `{"ok": true, ...}`.
  - Final line: `Refactor gate complete.`

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if config loading, auth token generation,
  Control UI logging, PID locking, service build ordering, diagnostics setup,
  router preload ordering, or gateway smoke behavior regresses.
- Keep the child branch and worker branch for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Worker commit: `3de66703a9878010232439dcb0bfdf1f6f04f7ee`.
- Active child support commits:
  - Stage plan: `5692c8d`
  - Worker merge: `8800915`
- Child verification commit: `dabdf4b`
- Integration merge: `a14b463`
- Integration record: `503affb`
- Verification evidence:
  - RED focused command: `6 failed, 3 passed in 0.58s`.
  - GREEN focused command: `9 passed in 0.51s`.
  - Touched ruff: `All checks passed!`.
  - Touched mypy: `Success: no issues found in 94 source files`.
  - `git diff --check`: exit 0.
  - Full child gate: `Refactor gate complete.`
  - Main-thread focused GREEN after worker merge: `9 passed in 3.23s`.
  - Main-thread child gate after worker merge: `2663 passed, 8 skipped,
    2 warnings`; gateway smoke completed start/status/stop/status.
  - Integration `scripts/refactor_gate.sh`: `2665 passed, 6 skipped,
    2 warnings`; gateway smoke completed start/status/stop/status.
- Cleanup evidence: `../opensquilla-refactor-active` and
  `../opensquilla-refactor-agent-boot-prelude` removed; `git worktree prune`
  completed; final `git worktree list --porcelain` shows no temporary refactor
  worktrees beyond `../opensquilla-refactor-integration`.
- Residual risk:
  - Worktree cleanup remains for the coordinating main thread.
- Next recommended slice:
  - Continue Gateway boot decomposition only if the next batch is still
    cohesive; otherwise switch to another Phase 2/3 boundary with independent
    file ownership for better parallelism.
