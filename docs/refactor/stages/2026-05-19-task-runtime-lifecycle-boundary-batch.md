# Task Runtime Lifecycle Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for same-thread worker execution. Steps use checkbox (`- [ ]`) syntax for tracking. This stage must record concrete Superpowers evidence, not only intent.

**Goal:** Split task execution, shutdown drain/cancel policy, and terminal state mutation from `TaskRuntime` while preserving queue behavior, terminal payloads, no-split-brain locks, fair scheduling, metrics, and shutdown order.

**Architecture:** Keep `opensquilla.gateway.task_runtime.TaskRuntime` as the public facade and compatibility surface. Move lifecycle helper families into focused gateway modules with callback-based access to runtime-owned storage/event state so public behavior and wire contracts stay unchanged.

**Tech Stack:** Python asyncio, Gateway task runtime, pytest async tests, structlog metric events, ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: task-runtime-lifecycle-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-task-runtime-lifecycle-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker prompts, branch/worktree coordination, merge review, conflict resolution, full gates, integration merge record, and cleanup.

## Goal

Refactor the remaining `TaskRuntime` lifecycle coupling in one cohesive, behavior-compatible batch:

- move `_execute` lifecycle flow into an execution boundary;
- move shutdown graceful-drain/cancel/abandon sequencing into a shutdown boundary;
- move terminal state cleanup and abandoned snapshot helpers into a terminal-state boundary;
- preserve public imports, queueing, cancellation, terminal event payloads, subagent completion notifications, no-split-brain session locks, fair scheduling, shutdown drain semantics, shutdown order, and core metric events.

## Current-State Audit

- Current integration HEAD before child worktree: `9f647c3` (`Record runtime stream delivery cleanup`).
- Worktree status before child creation: clean.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed from integration.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-runtime-stream-delivery-boundary-batch.md`
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/gateway/task_runtime_records.py`
  - `src/opensquilla/gateway/task_runtime_scheduler.py`
  - `src/opensquilla/gateway/task_runtime_terminal.py`
  - `tests/test_gateway/test_graceful_shutdown_drain.py`
  - `tests/test_gateway/test_shutdown_order.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_metrics_counters.py`
  - `tests/test_gateway/test_task_runtime_scheduler_boundary.py`
- Symbols or command surfaces inspected:
  - `TaskRuntime.shutdown`
  - `TaskRuntime._execute`
  - `TaskRuntime._mark_terminal`
  - `TaskRuntime._mark_unfinished_abandoned`
  - `TaskRuntime._mark_running`
  - `TaskRuntime._remove_pending`
  - `TaskRuntimeScheduler.remove_inactive_session`
  - `TaskRuntimeScheduler.acquire_fair_slot`
  - `build_task_terminal_payload`
  - `notify_subagent_terminal`
- Tests inspected:
  - graceful shutdown drain/fallback tests
  - shutdown order test
  - no-split-brain lock tests
  - terminal cleanup/leak tests
  - metrics counters test
  - existing task runtime records/terminal/scheduler boundary tests
- Existing boundary pattern this stage follows:
  - Recent task runtime batches kept `TaskRuntime` as facade while extracting focused sibling modules and preserving compatibility aliases/imports.
  - The previous runtime-stream batch used a plan-first worker-base commit, parallel worker ownership, focused checks, child/integration full gates, stage records, and cleanup.

## Superpowers Evidence

- `superpowers:using-superpowers`:
  - Evidence: read before stage work in this session; relevant process skills were re-read for this stage.
- `superpowers:using-git-worktrees`:
  - Evidence: fixed active child worktree `../opensquilla-refactor-active` created on `codex/refactor-task-runtime-lifecycle-boundary-batch` after confirming the path was absent.
- `superpowers:writing-plans`:
  - Evidence: this stage plan was written before implementation worker dispatch and before production edits.
- `superpowers:test-driven-development`:
  - Evidence: each worker must add/run a boundary RED test before production changes; RED commands are listed below and completion evidence must record expected failures.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: execution, shutdown, and terminal-state boundaries have distinct module/test ownership and can be implemented in parallel with main-thread conflict review for shared `task_runtime.py`.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread `spawn_agent` was probed successfully with read-only agent `019e3d06-af95-7531-b231-9c4073406932`. Implementation workers will be dispatched through `spawn_agent`.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused checks, full child `scripts/refactor_gate.sh`, integration merge gate, stage record, and cleanup evidence are fresh and recorded.
- Parallelism decision:
  - `spawn_agent` probe: successful; read-only probe started, confirmed integration branch/status/HEAD, and made no edits.
  - Same-thread implementation plan: use spawn-agent workers, but place each worker in its own branch-isolated worktree to avoid concurrent writes to shared `task_runtime.py`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` fixed worker worktrees only if same-thread worker dispatch fails or a worker cannot continue.
- Historical evidence note:
  - Do not infer success from worker summaries. Main thread must inspect diffs, run focused checks, full gates, merge records, and cleanup.

## Boundary Decision

- Module batch:
  - `src/opensquilla/gateway/task_runtime_execution.py`
  - `src/opensquilla/gateway/task_runtime_shutdown.py`
  - `src/opensquilla/gateway/task_runtime_terminal_state.py`
- Responsibilities moving out:
  - Execution flow: session lock ownership context, cancel-before-start branch, slot acquire/release around turn handler, `TaskRun` construction, and exception-to-terminal mapping.
  - Shutdown flow: active asyncio task snapshot, graceful drain, timeout fallback, cancellation wait, done result swallowing, and abandoned marking orchestration.
  - Terminal state mutation: runtime dict cleanup under `_state_lock`, terminal-emitted guard, pending/running/last-envelope cleanup, scheduler inactive-session cleanup, and unfinished-task snapshot for abandoned marking.
- Responsibilities staying in place:
  - Public `TaskRuntime` API: `enqueue`, `status`, `list`, `cancel`, `send`, `wait`, and `shutdown`.
  - Runtime-owned storage writes, event emission, terminal listener wiring, and compatibility imports.
  - `_session_locks` ownership and `_get_session_lock_for_turn`.
  - Scheduler slot accounting module and terminal payload module already extracted in previous batches.
- New module/file responsibility:
  - `task_runtime_execution.py`: owns execution coordinator helper and `TaskRun` construction without owning storage mutation or queue APIs.
  - `task_runtime_shutdown.py`: owns shutdown drain/cancel helper and delegates terminal abandon marking back through a callback.
  - `task_runtime_terminal_state.py`: owns terminal state cleanup and unfinished snapshot helpers. It must explicitly not pop `_session_locks`.
- Public behavior that must not change:
  - `opensquilla.gateway.task_runtime` public imports and `TaskRuntime` method signatures.
  - task event names and payloads: `task.running`, `task.succeeded`, `task.failed`, `task.cancelled`, `task.timeout`, `task.abandoned`.
  - terminal reply text and raw `error_class`/`error_message` persistence.
  - `turn_cancellations_total`, `in_flight_turns_total`, `queue_full_errors_total`, and `opensquilla_queue_depth` metric events.
  - no-split-brain behavior: `_session_locks` remains retained at terminal state.
  - graceful shutdown drain/fallback and gateway shutdown ordering.
  - fair scheduling and subagent reserved-slot behavior.
- Files explicitly out of scope:
  - `opensquilla.engine.runtime` lock internals.
  - boot stream/session delivery modules from the previous stage.
  - WebUI static files.
  - storage schema/migrations.
  - provider/channel/tool behavior.

## Parallel Worker Ownership

- Worker `lifecycle-execution` owns:
  - Create `src/opensquilla/gateway/task_runtime_execution.py`.
  - Create `tests/test_gateway/test_task_runtime_execution_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for `_execute` delegation and imports.
  - Modify existing execution/cancel/metrics tests only if needed for compatibility assertions.
- Worker `lifecycle-shutdown` owns:
  - Create `src/opensquilla/gateway/task_runtime_shutdown.py`.
  - Create `tests/test_gateway/test_task_runtime_shutdown_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for `shutdown` and `_mark_unfinished_abandoned` delegation/imports.
  - Modify `tests/test_gateway/test_graceful_shutdown_drain.py` and `tests/test_gateway/test_shutdown_order.py` only if imports/ownership assertions are needed.
- Worker `lifecycle-terminal-state` owns:
  - Create `src/opensquilla/gateway/task_runtime_terminal_state.py`.
  - Create `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for `_mark_terminal` state cleanup delegation and imports.
  - Modify `tests/test_gateway/test_task_runtime_terminal_cleanup.py`, `tests/test_gateway/test_no_split_brain_lock.py`, and `tests/test_gateway/test_task_runtime_scheduler_boundary.py` only if ownership assertions are needed.
- Main thread owns:
  - This stage document.
  - Worker worktree creation and prompts.
  - Merge order and conflict resolution for shared `task_runtime.py`.
  - Focused batch verification, full child gate, integration merge/gate, stage record update, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers' edits during integration and must not revert unrelated changes.

## TDD Red/Green

- Failing test commands:
  - Worker execution: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py -q`
  - Worker shutdown: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_shutdown_boundary.py -q`
  - Worker terminal-state: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_state_boundary.py -q`
- Expected red failures:
  - New owning modules do not exist yet.
  - `TaskRuntime._execute`, `TaskRuntime.shutdown`, and `_mark_terminal` still own full lifecycle bodies directly.
  - Boundary tests fail until new modules own the extracted helpers while `TaskRuntime` remains a thin facade.
- Behavior compatibility coverage:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_task_runtime_shutdown_boundary.py tests/test_gateway/test_task_runtime_terminal_state_boundary.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_task_runtime_scheduler_boundary.py -q`
- Module-batch implementation:
  - Extract callback-based helpers so `TaskRuntime` delegates lifecycle flow while retaining public API, storage/event wiring, and `_session_locks`.
  - Keep moved helpers type-light enough to avoid circular imports; use protocols/callables where useful.
  - Add AST/behavior boundary tests that prove ownership moved without weakening compatibility behavior.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_task_runtime_shutdown_boundary.py tests/test_gateway/test_task_runtime_terminal_state_boundary.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_task_runtime_scheduler_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/task_runtime.py src/opensquilla/gateway/task_runtime_execution.py src/opensquilla/gateway/task_runtime_shutdown.py src/opensquilla/gateway/task_runtime_terminal_state.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_task_runtime_shutdown_boundary.py tests/test_gateway/test_task_runtime_terminal_state_boundary.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_task_runtime_scheduler_boundary.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/task_runtime_execution.py`
  - `src/opensquilla/gateway/task_runtime_shutdown.py`
  - `src/opensquilla/gateway/task_runtime_terminal_state.py`
  - `tests/test_gateway/test_task_runtime_execution_boundary.py`
  - `tests/test_gateway/test_task_runtime_shutdown_boundary.py`
  - `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`
- Modify:
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_graceful_shutdown_drain.py`
  - `tests/test_gateway/test_shutdown_order.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_metrics_counters.py`
  - `tests/test_gateway/test_fair_queuing.py`
  - `tests/test_gateway/test_task_runtime_terminal_message.py`
  - `tests/test_gateway/test_task_runtime_scheduler_boundary.py`
- Test:
  - Boundary and compatibility tests listed in TDD Red/Green.
- Documentation:
  - `docs/refactor/stages/2026-05-19-task-runtime-lifecycle-boundary-batch.md`

## Detailed Superpowers Implementation Plan

### Task 1: Base Plan And Worker Dispatch

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration before creating this child branch.
- [x] Confirm `spawn_agent` status.
  - Observed: same-thread read-only probe started successfully.
- [x] Create fixed active worktree on `codex/refactor-task-runtime-lifecycle-boundary-batch`.
- [x] Write this stage plan before implementation.
- [x] Commit this stage plan as the worker base.
  - Commit: `2851140` (`Plan task runtime lifecycle boundary batch`).
- [x] Create branch-isolated worker worktrees from the plan base:
  - `../opensquilla-refactor-agent-lifecycle-execution`
  - `../opensquilla-refactor-agent-lifecycle-shutdown`
  - `../opensquilla-refactor-agent-lifecycle-terminal-state`
- [x] Launch three same-thread `spawn_agent` workers with explicit ownership and worktree paths.
  - `lifecycle-execution`: agent `019e3d09-342a-7c93-81f9-c7fbe671846d`.
  - `lifecycle-shutdown`: agent `019e3d09-3547-7861-baf2-f478d3dd3657`.
  - `lifecycle-terminal-state`: agent `019e3d09-362e-7e00-aa31-f2a78f196993`.

### Task 2: Worker `lifecycle-execution`

- [x] Write RED tests in `tests/test_gateway/test_task_runtime_execution_boundary.py`.
  - Assert `opensquilla.gateway.task_runtime_execution` exports an execution helper.
  - Assert `TaskRuntime._execute` is a thin delegator into the execution boundary.
  - Assert cancel-before-start still emits `CANCELLED` with `terminal_reason="cancelled_before_start"`.
  - Assert slot release still happens if the turn handler raises.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py -q` and confirm the expected missing-module or ownership failure.
  - RED: `2 failed, 2 passed`; failures were missing `opensquilla.gateway.task_runtime_execution` and `_execute` not yet delegating.
- [x] Move `_execute` flow to `task_runtime_execution.py`, using callbacks for wait/acquire/release/mark-terminal/turn-handler/metrics.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_fair_queuing.py -q`
  - touched-file `ruff check`
  - GREEN: `12 passed`.
  - Ruff: `All checks passed!`.
  - `git diff --check && git diff --cached --check`: passed with no output.
- [x] Commit with the required trailer.
  - Commit: `2cbcfdd` (`Extract task runtime execution lifecycle`).

### Task 3: Worker `lifecycle-shutdown`

- [x] Write RED tests in `tests/test_gateway/test_task_runtime_shutdown_boundary.py`.
  - Assert `opensquilla.gateway.task_runtime_shutdown` exports a shutdown helper.
  - Assert `TaskRuntime.shutdown` is a thin delegator.
  - Assert graceful drain completes without cancelling.
  - Assert graceful timeout falls back to cancellation and invokes abandoned marking once for unfinished tasks.
  - Assert `cancel=False` waits without issuing cancellation.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_shutdown_boundary.py -q` and confirm the expected missing-module or ownership failure.
  - RED: exit 2, `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_shutdown'`.
- [x] Move shutdown task snapshot/drain/cancel/abandon orchestration to `task_runtime_shutdown.py`.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_shutdown_boundary.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_shutdown_order.py -q`
  - touched-file `ruff check`
  - GREEN: `8 passed in 0.96s`.
  - Ruff: `All checks passed!`.
  - `git diff --check && git diff --cached --check`: passed.
- [x] Commit with the required trailer.
  - Commit: `97f6634` (`Extract task runtime shutdown boundary`).

### Task 4: Worker `lifecycle-terminal-state`

- [x] Write RED tests in `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`.
  - Assert `opensquilla.gateway.task_runtime_terminal_state` exports terminal cleanup helpers.
  - Assert `TaskRuntime._mark_terminal` delegates state cleanup and no longer directly mutates every tracking dict inline.
  - Assert terminal cleanup helper never references or pops `_session_locks`.
  - Assert unfinished snapshot returns non-terminal tasks for shutdown-abandon flow.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_state_boundary.py -q` and confirm the expected missing-module or ownership failure.
  - RED: `4 failed` due to missing `task_runtime_terminal_state` module and `_mark_terminal` not delegating cleanup.
- [x] Move terminal state cleanup and unfinished-task snapshot helpers to `task_runtime_terminal_state.py`.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_state_boundary.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_task_runtime_scheduler_boundary.py -q`
  - touched-file `ruff check`
  - GREEN: `14 passed in 6.68s`.
  - Ruff: `All checks passed!`.
  - `git diff --check` and `git diff --cached --check`: clean.
- [x] Commit with the required trailer.
  - Commit: `bde475d` (`Extract task runtime terminal state cleanup`).

### Task 5: Main-Thread Integration Review

- [x] Collect worker results and inspect diffs before trusting summaries.
- [x] Merge worker branches into `../opensquilla-refactor-active`, resolving shared `task_runtime.py` conflicts manually.
  - Execution worker merge: `b3a85ba` (`Merge task runtime execution lifecycle worker`).
  - Shutdown worker merge: `ee7b095` (`Merge task runtime shutdown lifecycle worker`).
  - Terminal-state worker merge: `5be97a1` (`Merge task runtime terminal state worker`).
  - Compatibility fix: `0745eef` (`Restore task runtime TaskRun compatibility alias`).
- [x] Run focused green command.
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_task_runtime_shutdown_boundary.py tests/test_gateway/test_task_runtime_terminal_state_boundary.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_task_runtime_scheduler_boundary.py -q`
  - Result: `39 passed in 7.98s` after restoring `TaskRun` compatibility alias.
- [x] Run additional touched-file checks.
  - Touched-file ruff: `All checks passed!`.
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`: `Success: no issues found in 542 source files` with existing notes.
  - `git diff --check`: passed with no output.
- [x] Run `scripts/refactor_gate.sh` in child.
  - Result: `2612 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Commit child verification/stage record.
  - Commit: `ade2713` (`Record task runtime lifecycle child verification`).
- [x] Merge child into integration with `git merge --no-ff`.
  - Merge commit: `2060d8c` (`Merge task runtime lifecycle boundary batch`).
- [x] Run `scripts/refactor_gate.sh` in integration.
  - Result: `2614 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Record child hash, integration merge hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active` and all lifecycle worker worktrees, run `git worktree prune`, and verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-lifecycle-execution`.
  - Removed `../opensquilla-refactor-agent-lifecycle-shutdown`.
  - Removed `../opensquilla-refactor-agent-lifecycle-terminal-state`.
  - Ran `git worktree prune`.
  - Verified all four removed paths are absent.
  - `git worktree list --porcelain` shows no remaining `opensquilla-refactor-*` worktrees except `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `ade2713` (`Record task runtime lifecycle child verification`)
- Worker commits:
  - `2cbcfdd` (`Extract task runtime execution lifecycle`)
  - `97f6634` (`Extract task runtime shutdown boundary`)
  - `bde475d` (`Extract task runtime terminal state cleanup`)
  - `b3a85ba` (`Merge task runtime execution lifecycle worker`)
  - `ee7b095` (`Merge task runtime shutdown lifecycle worker`)
  - `5be97a1` (`Merge task runtime terminal state worker`)
  - `0745eef` (`Restore task runtime TaskRun compatibility alias`)
- Integration merge: `2060d8c` (`Merge task runtime lifecycle boundary batch`)
- Verification evidence:
  - Focused batch: `39 passed in 7.98s`.
  - Touched-file ruff: `All checks passed!`.
  - Mypy: `Success: no issues found in 542 source files` with existing notes.
  - `git diff --check`: passed with no output.
  - Child `scripts/refactor_gate.sh`: `2612 passed, 8 skipped, 2 warnings`; gateway smoke passed.
  - Integration `scripts/refactor_gate.sh`: `2614 passed, 6 skipped, 2 warnings`; gateway smoke passed.
- Cleanup evidence:
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-lifecycle-execution`.
  - Removed `../opensquilla-refactor-agent-lifecycle-shutdown`.
  - Removed `../opensquilla-refactor-agent-lifecycle-terminal-state`.
  - Ran `git worktree prune`.
  - Verified all four removed paths are absent and `git worktree list --porcelain` has no extra refactor worktrees beyond `../opensquilla-refactor-integration`.
- Residual risk: the facade still owns `_mark_running`, `_remove_pending`, storage update/event emission in `_mark_terminal`, and queue collection; these are smaller follow-up boundaries after lifecycle extraction.
- Next recommended slice: task runtime queue/collection and running-state facade cleanup, or a broader Gateway boot cron-result delivery cleanup noted by the previous stage.
