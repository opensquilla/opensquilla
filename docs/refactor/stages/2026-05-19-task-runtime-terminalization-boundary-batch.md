# Task Runtime Terminalization Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for same-thread agent work or `superpowers:executing-plans` only if agent execution becomes unavailable. Steps use checkbox (`- [ ]`) syntax for tracking. This stage must record concrete Superpowers evidence, not only intent.

**Goal:** Split task runtime records, terminal event construction, and fair scheduling state into explicit Gateway boundaries while preserving task ordering, terminal payloads, shutdown behavior, and public compatibility imports.

**Architecture:** Keep `opensquilla.gateway.task_runtime.TaskRuntime` as the in-process orchestrator, but move cohesive helper families into focused modules. Same-thread `spawn_agent` is unavailable in this session, so independent implementation slices use `scripts/refactor_external_agent.sh` fixed worker worktrees and the main thread integrates the shared `task_runtime.py` imports and call sites.

**Tech Stack:** Python asyncio, Gateway task runtime, session task records, pytest async tests, ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: task-runtime-terminalization-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-task-runtime-terminalization-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker prompts, merge review, conflict resolution, full gates, integration merge record, and cleanup.

## Goal

Refactor the task runtime's largest remaining mixed responsibilities in one cohesive, behavior-compatible batch:

- move public/private task runtime DTOs and queue error contracts out of the orchestrator;
- move terminal payload/subagent completion event construction out of the orchestrator;
- move fair global/subagent slot accounting into an explicit scheduler boundary;
- preserve queueing, cancellation, terminal event payloads, terminal listener behavior, no-split-brain lock behavior, shutdown drain semantics, and compatibility imports from `opensquilla.gateway.task_runtime`.

## Current-State Audit

- Current integration HEAD before child worktree: `da37474` (`Record engine session flush compaction integration`).
- Worktree status before child creation: clean.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed from integration.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-engine-session-flush-compaction-boundary.md`
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/session/terminal_reply.py`
  - `src/opensquilla/session/rpc_payload.py`
  - `src/opensquilla/contracts/task.py`
  - `tests/test_gateway/test_task_runtime_terminal_message.py`
  - `tests/test_gateway/test_fair_queuing.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
  - `tests/test_gateway/test_graceful_shutdown_drain.py`
  - `tests/test_gateway/test_metrics_counters.py`
  - `tests/test_session/test_session_rpc_payload.py`
- Symbols or command surfaces inspected:
  - `TaskHandle`
  - `TaskRun`
  - `SubagentCompletionEvent`
  - `_RuntimeTask`
  - `TaskQueueFullError`
  - `TaskRuntime._execute`
  - `TaskRuntime._wait_for_subagent_slot`
  - `TaskRuntime._acquire_fair_slot`
  - `TaskRuntime._release_slot`
  - `TaskRuntime._mark_terminal`
  - `TaskRuntime._mark_unfinished_abandoned`
  - `TaskRuntime._notify_subagent_terminal`
  - `build_terminal_reply`
- Tests inspected:
  - terminal message/payload tests in `tests/test_gateway/test_task_runtime_terminal_message.py`
  - fair queueing and cleanup tests in `tests/test_gateway/test_fair_queuing.py`
  - no-split-brain lock tests in `tests/test_gateway/test_no_split_brain_lock.py`
  - graceful shutdown drain tests in `tests/test_gateway/test_graceful_shutdown_drain.py`
  - session RPC task-state tests in `tests/test_session/test_session_rpc_payload.py`
- Existing boundary pattern this stage follows:
  - Gateway modules keep orchestration in the original surface while moving focused helper families to sibling modules and re-exporting compatibility aliases from the old module.
  - Recent channel and memory batches used external worker worktrees when `spawn_agent` was thread-limited and recorded RED/GREEN plus full child/integration gates.

## Superpowers Evidence

- `superpowers:using-superpowers`:
  - Evidence: read before continuing the active goal in this session; current stage explicitly rechecked relevant skills.
- `superpowers:using-git-worktrees`:
  - Evidence: fixed child worktree `../opensquilla-refactor-active` created on `codex/refactor-task-runtime-terminalization-boundary-batch` after confirming the path was clear.
- `superpowers:writing-plans`:
  - Evidence: this stage plan was written before production edits and before worker dispatch.
- `superpowers:test-driven-development`:
  - Evidence: each worker must create and run a boundary RED test before production changes; RED commands are listed below and must be copied into the completion record.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: task runtime DTO, terminal, and fair-scheduling slices have independent test ownership and can be worked in separate branches; shared `task_runtime.py` conflicts are reserved for main-thread merge review.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread worker execution was probed first as required, but the probe failed with `agent thread limit reached`.
- `superpowers:executing-plans`:
  - Evidence: external Codex workers execute this written plan because same-thread subagents are unavailable.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused checks, full child `scripts/refactor_gate.sh`, integration merge gate, stage record, and cleanup evidence are fresh and recorded.
- Parallelism decision:
  - `spawn_agent` probe: failed with `agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` fixed slots:
    - `task-runtime-records`
    - `task-runtime-terminal`
    - `task-runtime-scheduler`
- Historical evidence note:
  - Do not infer success from worker summaries. Main thread must inspect diffs, run focused checks, full gates, merge records, and cleanup.

## Boundary Decision

- Module batch:
  - `src/opensquilla/gateway/task_runtime_records.py`
  - `src/opensquilla/gateway/task_runtime_terminal.py`
  - `src/opensquilla/gateway/task_runtime_scheduler.py`
- Responsibilities moving out:
  - Task runtime DTOs: `TaskHandle`, `TaskRun`, private runtime task record, stream sink type, handler/emitter/listener type aliases, and queue-full error.
  - Terminal event contracts: `SubagentCompletionEvent`, terminal event payload construction, subagent terminal listener notification helper.
  - Scheduler state: global slot accounting, subagent reserved-slot wait, per-agent round-robin bookkeeping, and slot release notifications.
- Responsibilities staying in place:
  - Public `TaskRuntime` orchestrator and method surface.
  - enqueue/status/list/cancel/send/wait/shutdown orchestration.
  - session lock acquisition/order and turn-handler invocation.
  - storage update sequencing and public event emission.
  - compatibility aliases/imports from `opensquilla.gateway.task_runtime`.
- New module/file responsibility:
  - `task_runtime_records.py`: owns task runtime dataclasses and queue error contracts without importing `task_runtime.py`.
  - `task_runtime_terminal.py`: owns subagent completion payloads and terminal listener notification without importing `task_runtime.py`.
  - `task_runtime_scheduler.py`: owns fair scheduling state transitions and slot counters without importing `task_runtime.py`.
- Public behavior that must not change:
  - `opensquilla.gateway.task_runtime` imports for `TaskRuntime`, `TaskHandle`, `TaskRun`, `SubagentCompletionEvent`, and `TaskQueueFullError`.
  - event names and payload keys for `task.running`, `task.succeeded`, `task.failed`, `task.cancelled`, `task.timeout`, and subagent completion events.
  - terminal reply text generated by `build_terminal_reply`.
  - per-session serialization and no-split-brain lock retention.
  - fair queueing, cross-agent independence, subagent reserved slots, and cleanup of agent round-robin structures.
  - graceful shutdown drain and timeout fallback.
  - core metric names and labels.
- Files explicitly out of scope:
  - `opensquilla.engine.runtime` turn execution.
  - session storage schema and migrations.
  - Web UI static files.
  - channel dispatch/background completion behavior beyond existing task runtime tests.
  - changing public RPC payload shapes.

## Parallel Worker Ownership

- Worker `task-runtime-records` owns:
  - Create `src/opensquilla/gateway/task_runtime_records.py`.
  - Create `tests/test_gateway/test_task_runtime_records_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for imports/aliases of records/types.
  - Modify `tests/test_gateway/test_metrics_counters.py` only if direct imports need to prove compatibility.
- Worker `task-runtime-terminal` owns:
  - Create `src/opensquilla/gateway/task_runtime_terminal.py`.
  - Create `tests/test_gateway/test_task_runtime_terminal_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for terminal imports/call sites.
  - Modify `tests/test_gateway/test_task_runtime_terminal_message.py` to import new ownership while preserving compatibility assertions.
- Worker `task-runtime-scheduler` owns:
  - Create `src/opensquilla/gateway/task_runtime_scheduler.py`.
  - Create `tests/test_gateway/test_task_runtime_scheduler_boundary.py`.
  - Modify `src/opensquilla/gateway/task_runtime.py` only for scheduler delegation/call sites.
  - Modify `tests/test_gateway/test_fair_queuing.py` and `tests/test_gateway/test_no_split_brain_lock.py` only where imports/ownership assertions are needed.
- Main thread owns:
  - This stage document.
  - Worker prompts and base commit.
  - Merge order and conflict resolution for shared `task_runtime.py`.
  - Focused batch verification, full child gate, integration merge/gate, stage record update, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers' edits during integration and must not revert unrelated changes.

## TDD Red/Green

- Failing test commands:
  - Worker records: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py -q`
  - Worker terminal: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_boundary.py -q`
  - Worker scheduler: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_scheduler_boundary.py -q`
- Expected red failures:
  - New owning modules do not exist yet.
  - `task_runtime.py` still owns moved definitions directly.
  - New boundary tests fail until ownership moves while compatibility aliases remain.
- Behavior compatibility coverage:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_message.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_fair_queuing.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_no_split_brain_lock.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_graceful_shutdown_drain.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_metrics_counters.py -q`
  - `uv run --extra dev pytest tests/test_session/test_session_rpc_payload.py -q`
- Module-batch implementation:
  - Move helper families into the new modules with the same behavior and types.
  - Import moved helpers back into `task_runtime.py` under the existing names to preserve compatibility.
  - Add boundary tests that assert new module ownership and that `task_runtime.py` no longer defines the moved top-level helper bodies/classes directly.
  - Keep direct behavior tests green against both new module imports and existing compatibility imports.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py tests/test_gateway/test_task_runtime_terminal_boundary.py tests/test_gateway/test_task_runtime_scheduler_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_metrics_counters.py tests/test_session/test_session_rpc_payload.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/task_runtime.py src/opensquilla/gateway/task_runtime_records.py src/opensquilla/gateway/task_runtime_terminal.py src/opensquilla/gateway/task_runtime_scheduler.py tests/test_gateway/test_task_runtime_records_boundary.py tests/test_gateway/test_task_runtime_terminal_boundary.py tests/test_gateway/test_task_runtime_scheduler_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_metrics_counters.py tests/test_session/test_session_rpc_payload.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/task_runtime_records.py`
  - `src/opensquilla/gateway/task_runtime_terminal.py`
  - `src/opensquilla/gateway/task_runtime_scheduler.py`
  - `tests/test_gateway/test_task_runtime_records_boundary.py`
  - `tests/test_gateway/test_task_runtime_terminal_boundary.py`
  - `tests/test_gateway/test_task_runtime_scheduler_boundary.py`
- Modify:
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_task_runtime_terminal_message.py`
  - `tests/test_gateway/test_fair_queuing.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
  - `tests/test_gateway/test_graceful_shutdown_drain.py`
  - `tests/test_gateway/test_metrics_counters.py`
  - `tests/test_session/test_session_rpc_payload.py`
- Test:
  - Boundary and compatibility tests listed in TDD Red/Green.
- Documentation:
  - `docs/refactor/stages/2026-05-19-task-runtime-terminalization-boundary-batch.md`

## Detailed Superpowers Implementation Plan

### Task 1: Base Plan And Worker Dispatch

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration before creating this child branch.
- [x] Confirm `spawn_agent` status.
  - Observed: failed with `agent thread limit reached`.
- [x] Create fixed active worktree on `codex/refactor-task-runtime-terminalization-boundary-batch`.
- [x] Write this stage plan before implementation.
- [x] Commit this stage plan as the worker base.
  - Commit: `6971bdd` (`Plan task runtime terminalization boundary batch`).
- [x] Launch three external workers with `scripts/refactor_external_agent.sh`, each from this child branch.
  - `task-runtime-records`: branch `codex/refactor-task-runtime-records-boundary`.
  - `task-runtime-terminal`: branch `codex/refactor-task-runtime-terminal-boundary`.
  - `task-runtime-scheduler`: branch `codex/refactor-task-runtime-scheduler-boundary`.

### Task 2: Worker `task-runtime-records`

- [ ] Write RED tests in `tests/test_gateway/test_task_runtime_records_boundary.py`.
  - Import `TaskHandle`, `TaskRun`, `RuntimeTask`, `TaskQueueFullError`, and type aliases from `opensquilla.gateway.task_runtime_records`.
  - Assert `opensquilla.gateway.task_runtime` compatibility aliases still expose `TaskHandle`, `TaskRun`, and `TaskQueueFullError`.
  - Assert `task_runtime.py` no longer defines top-level `class TaskHandle`, `class TaskRun`, `class _RuntimeTask`, or `class TaskQueueFullError` after implementation.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move the record dataclasses/type aliases/error into `task_runtime_records.py`, using public `RuntimeTask` in the new module and importing it as `_RuntimeTask` in `task_runtime.py` for compatibility with current internals.
- [ ] Preserve existing public compatibility imports from `opensquilla.gateway.task_runtime`.
- [ ] Run worker focused green:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py tests/test_gateway/test_metrics_counters.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 3: Worker `task-runtime-terminal`

- [ ] Write RED tests in `tests/test_gateway/test_task_runtime_terminal_boundary.py`.
  - Import `SubagentCompletionEvent`, `build_task_terminal_payload`, and `notify_subagent_terminal` from `opensquilla.gateway.task_runtime_terminal`.
  - Assert `task_runtime.py` no longer defines top-level `class SubagentCompletionEvent` after implementation.
  - Assert compatibility alias from `opensquilla.gateway.task_runtime.SubagentCompletionEvent` still works.
  - Assert failure payloads still add `terminal_message` and success payloads do not.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move `SubagentCompletionEvent` and terminal payload construction into `task_runtime_terminal.py`.
- [ ] Move subagent terminal listener notification into `notify_subagent_terminal(...)` without importing `task_runtime.py`.
- [ ] Keep `TaskRuntime._mark_terminal` responsible for state mutation, storage updates, event emission, and calling the new terminal helpers.
- [ ] Update `tests/test_gateway/test_task_runtime_terminal_message.py` imports to prove new ownership while preserving compatibility alias coverage.
- [ ] Run worker focused green:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_session/test_session_rpc_payload.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 4: Worker `task-runtime-scheduler`

- [ ] Write RED tests in `tests/test_gateway/test_task_runtime_scheduler_boundary.py`.
  - Import `TaskRuntimeScheduler` from `opensquilla.gateway.task_runtime_scheduler`.
  - Assert scheduler owns `wait_for_subagent_slot`, `acquire_fair_slot`, and `release_slot`.
  - Assert `task_runtime.py` no longer defines top-level method bodies for `_wait_for_subagent_slot`, `_acquire_fair_slot`, and `_release_slot` beyond thin delegation after implementation.
  - Assert no-split-brain lock behavior stays owned by `TaskRuntime`, not scheduler.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_scheduler_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move fair scheduling counters/conditions and slot accounting into `TaskRuntimeScheduler`.
- [ ] Keep storage updates, `_mark_running`, metrics emission, and per-session locks in `TaskRuntime`.
- [ ] Delegate `_wait_for_subagent_slot`, `_acquire_fair_slot`, and `_release_slot` through the scheduler with narrow callback hooks if needed.
- [ ] Update fair-queue tests only to assert scheduler ownership while preserving behavior.
- [ ] Run worker focused green:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_scheduler_boundary.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_graceful_shutdown_drain.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 5: Main Integration Review

- [x] Wait for external worker results and read each `last_message` summary.
- [x] Review every worker diff before merge.
- [x] Merge worker branches into `codex/refactor-task-runtime-terminalization-boundary-batch` one by one with `git merge --no-ff`.
  - `8669ad5` (`Merge task runtime records boundary worker`).
  - `bd472cc` (`Merge task runtime terminal boundary worker`).
  - `56fd20a` (`Merge task runtime scheduler boundary worker`).
- [x] Resolve shared `task_runtime.py` imports/delegation conflicts without reverting another worker's ownership.
  - `489faeb` (`Resolve task runtime boundary import ordering`).
- [x] Run the focused batch green command.
  - `61 passed`.
- [x] Run touched-file ruff, mypy, and `git diff --check`.
  - Targeted ruff passed.
  - Mypy passed with no issues in 537 source files.
  - `git diff --check` clean.
- [x] Run full child `scripts/refactor_gate.sh`.
  - Passed: ruff, mypy, whitespace, pytest `2588 passed, 8 skipped, 2 warnings`, gateway smoke on `127.0.0.1:52711`.
- [x] Commit any integration fix or stage-record update with the required co-author trailer.

### Task 6: Integration Branch Merge And Cleanup

- [ ] Merge child into integration with `git merge --no-ff codex/refactor-task-runtime-terminalization-boundary-batch`.
- [ ] Run full integration `scripts/refactor_gate.sh`.
- [ ] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
- [ ] Commit the stage record update on integration with the required co-author trailer.
- [ ] Remove `../opensquilla-refactor-active` and external worker worktrees:
  - `../opensquilla-refactor-agent-task-runtime-records`
  - `../opensquilla-refactor-agent-task-runtime-terminal`
  - `../opensquilla-refactor-agent-task-runtime-scheduler`
- [ ] Run `git worktree prune`.
- [ ] Verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if task ordering, terminal payloads, subagent completion notifications, fair scheduling, no-split-brain locking, or shutdown drain behavior regresses.
- Keep worker branches until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Worker commits:
  - task-runtime-records: `4ef5c2d` (`Refactor task runtime records boundary`).
  - task-runtime-terminal: `fcd836f` (`Refactor task runtime terminal boundary`).
  - task-runtime-scheduler: `6a11963` (`Refactor task runtime scheduler boundary`).
- Child integration commits:
  - `8669ad5` (`Merge task runtime records boundary worker`).
  - `bd472cc` (`Merge task runtime terminal boundary worker`).
  - `56fd20a` (`Merge task runtime scheduler boundary worker`).
  - `489faeb` (`Resolve task runtime boundary import ordering`).
- Integration merge:
- Verification evidence:
  - Worker `task-runtime-records` RED: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py -q` failed as expected with `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_records'`.
  - Worker `task-runtime-terminal` RED: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_boundary.py -q` failed as expected with `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_terminal'`.
  - Worker `task-runtime-scheduler` RED: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_scheduler_boundary.py -q` failed as expected with `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_scheduler'`.
  - Worker full gates passed independently:
    - `task-runtime-records`: `2578 passed, 8 skipped`; gateway smoke passed.
    - `task-runtime-terminal`: `2582 passed, 8 skipped`; gateway smoke passed.
    - `task-runtime-scheduler`: `2578 passed, 8 skipped`; gateway smoke passed.
  - Main focused batch after worker merge/conflict resolution:
    - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_records_boundary.py tests/test_gateway/test_task_runtime_terminal_boundary.py tests/test_gateway/test_task_runtime_scheduler_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_fair_queuing.py tests/test_gateway/test_no_split_brain_lock.py tests/test_gateway/test_graceful_shutdown_drain.py tests/test_gateway/test_metrics_counters.py tests/test_session/test_session_rpc_payload.py -q`
    - `61 passed`.
  - Main touched-file ruff: all checks passed.
  - Main mypy: success, no issues found in 537 source files.
  - Main `git diff --check`: clean.
  - Child full gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 537 source files; whitespace passed; pytest `2588 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- Cleanup evidence:
- Residual risk:
  - Low to medium. Task runtime orchestration remains in `TaskRuntime`, while records, terminal payload/subagent completion helpers, and scheduler state now have explicit owning modules. Compatibility imports remain on `opensquilla.gateway.task_runtime`, and scheduler-owned state is still exposed via compatibility properties for existing tests. Future slices should avoid removing those compatibility properties until downstream/import-surface checks are broadened.
- Next recommended slice:
  - Continue with a session/task runtime cleanup batch that can reduce remaining orchestration coupling around `TaskRuntime._execute`, `TaskRuntime.shutdown`, and runtime stream emission, or pivot to another coarse module-family slice if overall-plan priorities point elsewhere after integration gate and cleanup.
