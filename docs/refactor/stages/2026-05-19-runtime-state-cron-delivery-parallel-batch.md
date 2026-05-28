# Runtime State And Cron Delivery Parallel Batch

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: runtime-state-cron-delivery-parallel-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-runtime-state-cron-delivery-batch`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-task-runtime-state-boundary`
  - `codex/refactor-gateway-cron-result-delivery-boundary`
- Worker worktrees:
  - `../opensquilla-refactor-agent-runtime-state`
  - `../opensquilla-refactor-agent-cron-delivery`
- Owner: main Codex thread coordinates; worker agents implement isolated module boundaries.

## Goal

Split two independent Gateway architecture boundaries in parallel while preserving
all public runtime, scheduler, WebSocket, and session-event behavior:

- Extract TaskRuntime in-memory queue/running indexes behind a state boundary.
- Extract Gateway cron-result delivery out of `boot.py` into a named delivery
  boundary.

This is intentionally a coarse, parallel batch rather than two serial helper
moves. The batch keeps merge and gate discipline by using worker branches,
reviewing them into the active child branch, then merging the child branch into
the integration branch.

## Current-state audit

- Current HEAD: `9962247` (`Record task runtime lifecycle cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope: root `AGENTS.md`.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-task-runtime-lifecycle-boundary-batch.md`
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/gateway/background_completion.py`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/scheduler/delivery.py`
  - `src/opensquilla/scheduler/handlers.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
- Symbols or command surfaces inspected:
  - `TaskRuntime.__init__`, `enqueue`, `cancel`, `send`, `wait`, `shutdown`,
    `_try_collect`, `_mark_running`, `_mark_terminal`, `_remove_pending`
  - `build_cron_result_payload`, `build_sessions_changed_payload`
  - `start_gateway_server` inline `_cron_ws_emitter` and `_session_forwarder`
  - `DeliveryChain`
- Tests inspected:
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
- Existing boundary pattern this stage follows:
  - `task_runtime_execution.py`
  - `task_runtime_shutdown.py`
  - `task_runtime_terminal_state.py`
  - `task_runtime_terminal.py`
  - `session_event_delivery.py`
  - `task_runtime_streaming.py`

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read current skill instructions and created isolated child
    worktree `../opensquilla-refactor-active` on
    `codex/refactor-runtime-state-cron-delivery-batch`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions and wrote this stage plan before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: read current skill instructions. Worker prompts require RED
    tests to be committed before production edits and require the expected
    failing output to be recorded in worker summaries and this stage record.
- `superpowers:verification-before-completion`:
  - Evidence: read current skill instructions. This stage must not claim
    completion until focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    records, and cleanup evidence are recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes. The two explorer
    agents confirmed runtime-state and cron-delivery file ownership can be
    split with low direct file overlap.
  - `superpowers:subagent-driven-development` used: yes. Implementation will
    be dispatched to worker agents with isolated branches and main-thread
    review before merge.
  - `spawn_agent` probe: available. Explorer agents `Kuhn` and `Mendel`
    completed read-only boundary analysis.
  - External worker fallback: not needed unless implementation workers fail or
    same-thread agents become unavailable; fallback command is
    `scripts/refactor_external_agent.sh`.
- Historical evidence note:
  - Do not claim a prior stage used a Superpowers checkpoint unless the stage
    record or current command log contains evidence. Record gaps explicitly.

## Boundary decision

- Module batch:
  - Runtime state worker: TaskRuntime queue/running-state facade cleanup.
  - Cron delivery worker: Gateway boot cron-result delivery cleanup.
- Responsibilities moving out:
  - Runtime state worker:
    - `_tasks`, `_pending_by_session`, `_running_by_session`,
      `_last_envelope_by_session`, and `_state_lock`.
    - Pending registration/depth lookup, collect-mode merge state mutation,
      runtime task lookup for wait/send/background completion, running
      transition state mutation, terminal cleanup state mutation inputs, and
      unfinished task snapshot.
  - Cron delivery worker:
    - `build_cron_result_payload`
    - `build_sessions_changed_payload`
    - cron WebSocket fanout from `start_gateway_server`
    - origin-session cron-result forwarding from `start_gateway_server`
    - gateway-owned adapter for scheduler `DeliveryChain`.
- Responsibilities staying in place:
  - `TaskRuntime` remains the public facade and keeps public API compatibility:
    `enqueue`, `status`, `list`, `cancel`, `send`, `wait`, `shutdown`.
  - `opensquilla.gateway.task_runtime` keeps compatibility imports:
    `TaskRun`, `TaskHandle`, `TaskQueueFullError`,
    `SubagentCompletionEvent`, and `_RuntimeTask`.
  - `TaskRuntime` keeps storage writes, metric names, public event emission,
    `_session_locks`, and `_get_session_lock_for_turn`.
  - Scheduler modules remain gateway-free.
  - `boot.py` remains responsible for service construction and dependency
    wiring, but not inline cron delivery helpers.
- New module/file responsibility:
  - `src/opensquilla/gateway/task_runtime_state.py`: in-memory runtime index
    ownership only; no storage, no WebSocket send, no session lock ownership.
  - `src/opensquilla/gateway/cron_result_delivery.py`: gateway cron delivery
    payloads, session event forwarding, WebSocket fanout, and
    `DeliveryChain` construction helpers.
- Public behavior that must not change:
  - Queue-full behavior and `queue_full_errors_total` metric.
  - Collect-mode merge semantics, `message_count`, and `no_memory_capture`.
  - One-shot provenance behavior in `TaskRuntime.send`.
  - Terminal cleanup memory behavior.
  - Background completion channel target capture.
  - `cron.run.start` and `cron.run.finished` fanout topics.
  - `session.event.cron_result` wire shape.
  - `sessions.changed` reason `cron_result`.
  - Public imports from `opensquilla.gateway.task_runtime` and scheduler
    `DeliveryChain` behavior.
- Files explicitly out of scope:
  - Runtime worker must not edit `src/opensquilla/gateway/boot.py` or
    `src/opensquilla/gateway/cron_result_delivery.py`.
  - Cron worker must not edit `src/opensquilla/gateway/task_runtime.py`,
    `src/opensquilla/gateway/task_runtime_*.py`, or
    `src/opensquilla/gateway/background_completion.py`.
  - Neither worker may edit `src/opensquilla/scheduler/handlers.py` unless the
    main thread approves after reviewing conflict risk.

## TDD red/green

- Runtime-state worker failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_state_boundary.py tests/test_gateway/test_task_runtime_queue_state_boundary.py tests/test_gateway/test_task_runtime_lookup_boundary.py -q`
- Runtime-state expected red failure:
  - `ModuleNotFoundError` or assertion failure proving
    `TaskRuntimeState` is missing and `TaskRuntime` still directly owns raw
    runtime indexes.
- Runtime-state behavior compatibility coverage:
  - Add boundary tests proving `TaskRuntimeState` owns runtime indexes while
    `TaskRuntime` keeps session locks and public compatibility imports.
  - Add behavior tests for collect merge, queue-full metric, one-shot
    provenance, background completion lookup, and terminal cleanup.
- Cron-delivery worker failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_cron_result_delivery_boundary.py -q`
- Cron-delivery expected red failure:
  - `ModuleNotFoundError` or assertion failure proving cron delivery helpers
    still live inline in `boot.py`.
- Cron-delivery behavior compatibility coverage:
  - Add boundary tests proving `boot.py` delegates cron delivery to the new
    module.
  - Add behavior tests for cron WebSocket fanout with error isolation,
    `session.event.cron_result`, stream recording, subscriber send, and
    `sessions.changed` reason.
- Module-batch implementation:
  - Merge runtime-state worker first if it changes `TaskRuntime` public
    behavior or touched background completion mocks.
  - Merge cron-delivery worker independently if it avoids task-runtime files.
- Focused green command after worker merges:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_state_boundary.py tests/test_gateway/test_task_runtime_queue_state_boundary.py tests/test_gateway/test_task_runtime_lookup_boundary.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_metrics_counters.py tests/test_gateway/test_background_completion.py tests/test_gateway/test_task_runtime_reserved_slots.py tests/test_gateway/test_cron_result_delivery_boundary.py tests/test_gateway/test_rpc_cron_current_session.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/task_runtime.py src/opensquilla/gateway/task_runtime_state.py src/opensquilla/gateway/background_completion.py src/opensquilla/gateway/boot.py src/opensquilla/gateway/cron_result_delivery.py tests/test_gateway/test_task_runtime_state_boundary.py tests/test_gateway/test_task_runtime_queue_state_boundary.py tests/test_gateway/test_task_runtime_lookup_boundary.py tests/test_gateway/test_cron_result_delivery_boundary.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/task_runtime_state.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`
  - `tests/test_gateway/test_task_runtime_state_boundary.py`
  - `tests/test_gateway/test_task_runtime_queue_state_boundary.py`
  - `tests/test_gateway/test_task_runtime_lookup_boundary.py`
  - `tests/test_gateway/test_cron_result_delivery_boundary.py`
- Modify:
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/gateway/background_completion.py`
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_metrics_counters.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_task_runtime_reserved_slots.py`
  - `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
  - Result: preflight passed on active child worktree at `9962247`.
- [x] Commit this stage plan on the active child branch.
  - Commit: `4c1922f` (`Plan runtime state and cron delivery parallel batch`).
- [x] Create worker worktrees from the active child branch.
  - Runtime worktree: `../opensquilla-refactor-agent-runtime-state`.
  - Cron delivery worktree: `../opensquilla-refactor-agent-cron-delivery`.
- [x] Dispatch runtime-state worker.
  - Worker: `Russell`; same-thread `spawn_agent` was available.
- [x] Dispatch cron-delivery worker.
  - Worker: `Ampere`; same-thread `spawn_agent` was available.
- [x] Runtime worker writes failing tests and records RED output.
  - Initial RED: `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_state'`.
  - Review-loop RED: `2 failed, 9 passed`; failures covered missing legacy
    `_tasks` fallback before the compatibility fix.
- [x] Cron worker writes failing tests and records RED output.
  - RED: `ModuleNotFoundError: No module named 'opensquilla.gateway.cron_result_delivery'`.
- [x] Runtime worker implements minimal compatible state boundary.
  - Commit: `bd0b75f` (`refactor: extract task runtime state boundary`).
- [x] Cron worker implements minimal compatible cron delivery boundary.
  - Commit: `e61f64d` (`refactor: extract gateway cron result delivery`).
- [x] Review runtime worker diff and verification.
  - Review found no blocking issues; required fixes for missing
    `no_memory_capture`, one-shot provenance, and legacy `_tasks` fallback
    coverage were applied before merge.
  - Runtime focused verification after review fixes: `38 passed in 7.22s`;
    ruff and `git diff --check` passed.
- [x] Review cron worker diff and verification.
  - Review found no blocking issues.
  - Cron focused verification: `22 passed in 0.47s`; reviewer also ran
    `26 passed` including session-event delivery boundary, ruff, mypy for
    touched files, and `git diff --check`.
- [x] Merge runtime worker into active child with `git merge --no-ff`.
  - Merge commit: `cb18d05` (`Merge task runtime state boundary worker`).
- [x] Merge cron worker into active child with `git merge --no-ff`.
  - Merge commit: `b4f4835` (`Merge gateway cron delivery boundary worker`).
- [x] Run focused green command and touched-file checks.
  - Focused green command: `60 passed in 9.68s`.
  - Touched-file ruff: all checks passed.
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`: success,
    no issues in 544 source files, with existing notes.
  - `git diff --check`: passed.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - First run exposed stale boundary-test expectation:
    `test_mark_terminal_delegates_state_cleanup` still expected
    `_mark_terminal` to call `cleanup_terminal_task_state` directly.
  - Root cause: the new runtime-state boundary delegates terminal cleanup via
    `TaskRuntimeState.cleanup_terminal`; the test was updated to verify this
    two-step boundary.
  - Local regression for the fix:
    `tests/test_gateway/test_task_runtime_terminal_state_boundary.py`
    plus runtime focused files: `21 passed in 6.74s`; `git diff --check`
    passed.
  - Final child gate: ruff passed; mypy success on 544 source files; pytest
    `2629 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- Commit: `1f40b42` (`Record runtime state cron delivery child verification`).
- [x] Merge child into integration with `git merge --no-ff`.
  - Merge commit: `4a1e6f7` (`Merge runtime state cron delivery parallel batch`).
- [x] Run `scripts/refactor_gate.sh` in integration.
  - Integration gate: ruff passed; mypy success on 544 source files; pytest
    `2631 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Record child hash, integration hash, verification, and next slice.
  - Integration record commit pending in this edit.
- [x] Remove `../opensquilla-refactor-active` and worker worktrees, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-runtime-state`.
  - Removed `../opensquilla-refactor-agent-cron-delivery`.
  - Ran `git worktree prune`.
  - Verified all three removed paths are absent.
  - `git worktree list --porcelain` shows no remaining `opensquilla-refactor-*`
    worktrees except `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch and worker branches for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Runtime worker commit:
  - `bd0b75f` (`refactor: extract task runtime state boundary`).
- Cron worker commit:
  - `e61f64d` (`refactor: extract gateway cron result delivery`).
- Child merge commits:
  - `cb18d05` (`Merge task runtime state boundary worker`).
  - `b4f4835` (`Merge gateway cron delivery boundary worker`).
- Child verification commit:
  - `1f40b42` (`Record runtime state cron delivery child verification`).
- Integration merge:
  - `4a1e6f7` (`Merge runtime state cron delivery parallel batch`).
- Integration record:
  - `23325e5` (`Record runtime state cron delivery integration`).
- Verification evidence:
  - Runtime worker RED: missing `opensquilla.gateway.task_runtime_state` module.
  - Runtime review-loop RED: missing legacy `_tasks` fallback.
  - Runtime worker GREEN: `38 passed in 7.22s`; ruff and `git diff --check`
    passed.
  - Cron worker RED: missing `opensquilla.gateway.cron_result_delivery` module.
  - Cron worker GREEN: `22 passed in 0.47s`; ruff and `git diff --check`
    passed.
  - Focused merged batch: `60 passed in 9.68s`.
  - Child gate: ruff passed; mypy success on 544 source files; pytest
    `2629 passed, 8 skipped, 2 warnings`; gateway smoke passed.
  - Integration gate: ruff passed; mypy success on 544 source files; pytest
    `2631 passed, 6 skipped, 2 warnings`; gateway smoke passed.
- Cleanup evidence:
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-runtime-state`.
  - Removed `../opensquilla-refactor-agent-cron-delivery`.
  - Ran `git worktree prune`.
  - Verified all three removed paths are absent and `git worktree list --porcelain`
    has no extra refactor worktrees beyond `../opensquilla-refactor-integration`.
- Residual risk:
  - `TaskRuntime` still exposes private compatibility properties (`_tasks`,
    `_pending_by_session`, `_running_by_session`, `_last_envelope_by_session`,
    `_state_lock`) that delegate to `TaskRuntimeState`; this is intentional
    compatibility for existing tests and local callers, but later stages can
    migrate direct private access to explicit facade methods.
  - `boot.py` still contains broad service wiring; cron-result delivery has
    moved out, but additional boot-boundary extractions remain possible.
- Next recommended slice:
  - Continue Gateway boot/service wiring cleanup, or migrate remaining direct
    `TaskRuntime` private compatibility access in tests/callers to explicit
    facade methods once downstream behavior is stable.
