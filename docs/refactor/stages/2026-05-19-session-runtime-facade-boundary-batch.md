# Session Runtime Facade Boundary Batch

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: session-runtime-facade-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-session-runtime-facade-batch`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-session-read-service-boundary`
  - `codex/refactor-task-runtime-facade-observability`
- Worker worktrees:
  - `../opensquilla-refactor-agent-session-read`
  - `../opensquilla-refactor-agent-runtime-facade`
- Owner: main Codex thread coordinates; external Codex workers implement
  isolated boundaries because same-thread `spawn_agent` is currently at its
  thread limit.

## Goal

Advance the Gateway/session runtime architecture line with two independent,
behavior-compatible subdomains:

- Move session read-query/task-row resolution out of Gateway RPC handlers into
  session-domain read services, and remove the remaining session-domain dynamic
  dependency on Gateway RPC error classes.
- Replace direct real-`TaskRuntime` private state reads in behavior tests with
  explicit read-only facade/test helpers while keeping compatibility shims.

This is intentionally a module-family batch: both workers reduce Gateway/session
coupling without touching `boot.py` or scheduler internals.

## Current-state audit

- Current HEAD: `5a674c4` (`Record runtime state cron delivery cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-runtime-state-cron-delivery-parallel-batch.md`
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/session/management_service.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/gateway/task_runtime_state.py`
  - `src/opensquilla/gateway/background_completion.py`
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_task_runtime_execution_boundary.py`
- Symbols or command surfaces inspected:
  - `list_task_rows`
  - `list_task_rows_by_session`
  - `resolve_session_node`
  - `handle_sessions_list`
  - `handle_sessions_messages_subscribe`
  - `handle_sessions_resolve`
  - `session.management_service._rpc_error_type`
  - `TaskRuntime.get_runtime_task`
  - `TaskRuntime._tasks`, `_pending_by_session`, `_running_by_session`,
    `_last_envelope_by_session`, `_runtime_state`, `_session_locks`
- Tests inspected:
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_task_runtime_execution_boundary.py`
  - `tests/test_gateway/test_task_runtime_lookup_boundary.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/session/management_service.py`
  - `src/opensquilla/session/services.py`
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/task_runtime_state.py`
  - `src/opensquilla/gateway/task_runtime_records.py`

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read current skill instructions; created isolated active child
    worktree `../opensquilla-refactor-active` on
    `codex/refactor-session-runtime-facade-batch`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions; wrote this stage record before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: read current skill instructions; worker prompts require RED tests
    and expected failure summaries before production edits.
- `superpowers:verification-before-completion`:
  - Evidence: read current skill instructions; this stage must not claim
    completion until focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    records, and cleanup evidence are recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes. This batch has two
    independent domains with disjoint file ownership.
  - `superpowers:subagent-driven-development` used: yes for worker/review
    discipline; same-thread implementers are unavailable, so external workers
    carry the implementation tasks.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: used `scripts/refactor_external_agent.sh` for
    three read-only scouts; scout worktrees were removed and pruned after
    reports were collected. Implementation will also use fixed external worker
    worktrees.
- Historical evidence note:
  - Do not claim a prior stage used a Superpowers checkpoint unless the stage
    record or current command log contains evidence. Record gaps explicitly.

## Boundary decision

- Module batch:
  - Session read-query service boundary.
  - TaskRuntime facade/test-observability boundary.
- Responsibilities moving out:
  - Session worker:
    - Task-row lookup and batching currently in
      `gateway/rpc_session_read_queries.py`.
    - Session node resolution currently in `gateway/rpc_session_read_queries.py`.
    - Gateway RPC error-class dynamic import currently in
      `session/management_service.py`.
  - Runtime worker:
    - Behavior tests that inspect real `TaskRuntime` raw private dicts.
    - Ad hoc private-state assertions that should use a read-only snapshot
      facade or test helper.
    - Background-completion fake runtime direct `_tasks` setup, except for one
      explicit compatibility fallback test.
- Responsibilities staying in place:
  - Gateway RPC handler functions stay in Gateway modules and keep public method
    names and payload keys unchanged.
  - `TaskRuntime` keeps compatibility properties for `_tasks`,
    `_pending_by_session`, `_running_by_session`, `_last_envelope_by_session`,
    `_state_lock`, and `_session_locks`.
  - `background_completion` keeps legacy `_tasks` fallback after preferring
    `get_runtime_task`.
  - Session-domain services must not statically import `opensquilla.gateway`.
- New module/file responsibility:
  - `src/opensquilla/session/read_service.py`: session/task read-query helpers
    that do not depend on Gateway RPC handler modules.
  - `src/opensquilla/session/errors.py` or equivalent: session-domain error
    data/classes that Gateway adapters can translate to `RpcHandlerError` or
    `RpcUnavailableError`.
  - `tests/test_gateway/task_runtime_test_helpers.py` or focused helpers inside
    existing tests: read-only runtime snapshot assertions without raw real
    `TaskRuntime` dict access.
- Public behavior that must not change:
  - `sessions.list`, `sessions.messages.subscribe`, `sessions.preview`, and
    `sessions.resolve` response payload shapes.
  - Task-row source preference: live `TaskRuntime.list()` first where available,
    then storage fallback.
  - Storage batch path for session task rows.
  - Ambiguous session resolution error text.
  - Session create/patch RPC error codes and details.
  - TaskRuntime terminal cleanup, cancellation, lock retention, and leak bounds.
  - Background completion parent route fallback compatibility.
- Files explicitly out of scope:
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`
  - `src/opensquilla/gateway/task_runtime_streaming.py`
  - `src/opensquilla/scheduler/**`
  - `src/opensquilla/engine/runtime.py`
  - Web UI/static files
  - Provider/tools/channel modules
  - Migrations and dependency lock files

## TDD red/green

- Session worker failing test command:
  - `uv run --extra dev pytest tests/test_session/test_session_read_service.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py -q`
- Session worker expected red failure:
  - `ModuleNotFoundError` for `opensquilla.session.read_service` or assertion
    failure showing Gateway still owns `list_task_rows`,
    `list_task_rows_by_session`, and `resolve_session_node`.
  - Boundary failure showing `session.management_service` still imports Gateway
    RPC error classes dynamically.
- Session behavior compatibility coverage:
  - `sessions.list` and `sessions.messages.subscribe` keep exact task-row
    payload behavior.
  - Session resolution keeps exact direct/ambiguous/not-found behavior.
  - Session create/patch Gateway adapters keep public RPC error behavior while
    session-domain service avoids Gateway imports.
- Runtime worker failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_facade_observability_boundary.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_background_completion.py -q`
- Runtime worker expected red failure:
  - Missing runtime snapshot facade/test helper, or AST scan failure showing
    real `TaskRuntime` behavior tests still read `_tasks`,
    `_pending_by_session`, `_running_by_session`, `_last_envelope_by_session`,
    `_runtime_state`, or `_session_locks` directly outside intentional boundary
    tests.
- Runtime behavior compatibility coverage:
  - Terminal cleanup still clears short-lived runtime state and retains session
    locks.
  - Cancel-before-start behavior remains unchanged.
  - Leak-bound test still verifies state growth with a facade/snapshot.
  - Background completion fake runtime uses `get_runtime_task` helper while one
    explicit legacy `_tasks` fallback test remains.
- Module-batch implementation:
  - Session worker and runtime worker can run in parallel with no file overlap.
  - Main thread reviews each branch, then merges into active child.
- Focused green command after worker merges:
  - `uv run --extra dev pytest tests/test_session/test_session_read_service.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_sessions.py::TestSessionsList tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_gateway/test_task_runtime_facade_observability_boundary.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_background_completion.py tests/test_gateway/test_task_runtime_lookup_boundary.py tests/test_gateway/test_no_split_brain_lock.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/session/read_service.py src/opensquilla/session/management_service.py src/opensquilla/session/errors.py src/opensquilla/gateway/rpc_session_read_queries.py src/opensquilla/gateway/rpc_session_management.py src/opensquilla/gateway/task_runtime.py src/opensquilla/gateway/background_completion.py tests/test_session/test_session_read_service.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_task_runtime_facade_observability_boundary.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_background_completion.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/session/read_service.py`
  - `src/opensquilla/session/errors.py` if needed for Gateway error decoupling
  - `tests/test_session/test_session_read_service.py`
  - `tests/test_gateway/test_task_runtime_facade_observability_boundary.py`
- Modify:
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/session/management_service.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `src/opensquilla/gateway/background_completion.py`
- Test:
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_session_services.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_task_runtime_terminal_cleanup.py`
  - `tests/test_gateway/test_task_runtime_execution_boundary.py`
  - `tests/test_gateway/test_background_completion.py`
  - `tests/test_gateway/test_task_runtime_lookup_boundary.py`
  - `tests/test_gateway/test_no_split_brain_lock.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
  - Result: preflight passed on active child worktree at `5a674c4`.
- [x] Commit this stage plan on the active child branch.
  - Commit: `f538152` (`Plan session runtime facade boundary batch`).
- [x] Create external worker worktrees from the active child branch.
  - Worker worktrees: `../opensquilla-refactor-agent-session-read`,
    `../opensquilla-refactor-agent-runtime-facade`.
- [x] Dispatch session read-query service worker.
- [x] Dispatch TaskRuntime facade/test-observability worker.
- [x] Session worker writes failing tests and records RED output.
  - RED command:
    `uv run --extra dev pytest tests/test_session/test_session_read_service.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py -q`
  - Expected failure observed: `ImportError: cannot import name 'read_service'
    from 'opensquilla.session'`.
- [x] Runtime worker writes failing tests and records RED output.
  - RED command:
    `uv run --extra dev pytest tests/test_gateway/test_task_runtime_facade_observability_boundary.py tests/test_gateway/test_task_runtime_terminal_cleanup.py tests/test_gateway/test_task_runtime_execution_boundary.py tests/test_gateway/test_background_completion.py -q`
  - Expected failures observed: `TaskRuntime.snapshot_runtime_state()` missing
    and new boundary test flagged direct private-state reads in behavior tests.
- [x] Session worker implements behavior-compatible read service and Gateway
      error adapter decoupling.
- [x] Runtime worker implements snapshot/test-helper facade and migrates direct
      private-state test reads.
- [x] Review session worker diff and verification.
  - Worker commit: `64a64fa` (`Refactor session read services`).
  - Worker focused GREEN: `22 passed in 0.64s`.
  - Worker full gate: `2633 passed, 8 skipped`; ruff, mypy, whitespace, and
    gateway smoke passed.
- [x] Review runtime worker diff and verification.
  - Worker commit: `7fe8847` (`Add TaskRuntime observability snapshot facade`).
  - Worker focused GREEN: `24 passed`; extended focused GREEN: `30 passed`.
  - Worker full gate: passed; ruff, mypy, whitespace, full pytest, and gateway
    smoke completed successfully.
- [x] Merge session worker into active child with `git merge --no-ff`.
  - Merge commit: `9fc6fe6` (`Merge session read service boundary`).
- [x] Merge runtime worker into active child with `git merge --no-ff`.
  - Merge commit: `44b4e2b` (`Merge task runtime facade observability boundary`).
- [x] Run focused green command and touched-file checks.
  - Focused merged command: `52 passed in 10.88s`.
  - Touched-file `ruff check`: passed.
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`: no issues in
    546 source files; existing notes only.
  - `git diff --check`: passed.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
  - Result: ruff passed; mypy no issues in 546 source files; whitespace passed;
    pytest `2635 passed, 8 skipped, 2 warnings in 55.60s`; gateway smoke
    start/status/stop/status passed.
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

  - Commit: `daec318` (`Record session runtime facade child verification`).
- [x] Merge child into integration with `git merge --no-ff`.
  - Merge commit: `a395dca` (`Merge session runtime facade boundary batch`).
- [x] Run `scripts/refactor_gate.sh` in integration.
  - Result: ruff passed; mypy no issues in 546 source files; whitespace passed;
    pytest `2637 passed, 6 skipped, 2 warnings in 28.76s`; gateway smoke
    start/status/stop/status passed.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active` and worker worktrees, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.
  - Removed:
    - `../opensquilla-refactor-active`
    - `../opensquilla-refactor-agent-session-read`
    - `../opensquilla-refactor-agent-runtime-facade`
  - `git worktree list --porcelain` verified no extra
    `opensquilla-refactor-*` worktrees remain beyond
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

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch and worker branches for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Session worker commit: `64a64fa` (`Refactor session read services`).
- Runtime worker commit: `7fe8847` (`Add TaskRuntime observability snapshot
  facade`).
- Child merge commits:
  - `9fc6fe6` (`Merge session read service boundary`)
  - `44b4e2b` (`Merge task runtime facade observability boundary`)
- Child verification commit: `daec318` (`Record session runtime facade child
  verification`).
- Integration merge: `a395dca` (`Merge session runtime facade boundary batch`).
- Integration record: `c63e4b4` (`Record session runtime facade integration
  verification`).
- Verification evidence:
  - Worker RED/GREEN evidence recorded above.
  - Merged focused command: `52 passed in 10.88s`.
  - Touched-file `ruff check`: passed.
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`: no issues in
    546 source files; existing notes only.
  - `git diff --check`: passed.
  - Active child `scripts/refactor_gate.sh`: ruff passed; mypy no issues in 546
    source files; whitespace passed; pytest `2635 passed, 8 skipped, 2
    warnings`; gateway smoke passed.
  - Integration `scripts/refactor_gate.sh`: ruff passed; mypy no issues in 546
    source files; whitespace passed; pytest `2637 passed, 6 skipped, 2
    warnings`; gateway smoke passed.
- Cleanup evidence:
  - Worker PIDs `63174` and `63175` were no longer present.
  - Removed active child and worker worktrees:
    `../opensquilla-refactor-active`,
    `../opensquilla-refactor-agent-session-read`, and
    `../opensquilla-refactor-agent-runtime-facade`.
  - Ran `git worktree prune`.
  - `git worktree list --porcelain` shows the refactor line only has
    `../opensquilla-refactor-integration`.
- Residual risk: no blocking risk observed; session read helpers moved to the
  session domain and runtime state test observability now uses a read-only
  snapshot facade while keeping compatibility paths.
- Next recommended slice: boot/service wiring remains viable but should be a
  single-worker or main-thread-owned stage because it converges on `boot.py`.
