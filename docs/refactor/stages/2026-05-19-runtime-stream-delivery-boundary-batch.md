# Runtime Stream Delivery Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for same-thread worker execution. Steps use checkbox (`- [ ]`) syntax for tracking. This stage must record concrete Superpowers evidence, not only intent.

**Goal:** Split task runtime stream emission, session event delivery/replay, and WebUI task-terminal mapping into explicit boundaries while preserving WebSocket/RPC payloads, task terminal messages, replay sequencing, and frontend migration behavior.

**Architecture:** Keep `opensquilla.gateway.boot` as service wiring and keep existing public event names compatible. Move runtime stream normalization and session delivery helpers to focused gateway modules, while the WebUI keeps consuming `task.*` terminal events until the server-side migration is complete.

**Tech Stack:** Python asyncio, Gateway WebSocket/session event delivery, task runtime streams, static chat view JavaScript, pytest, ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: runtime-stream-delivery-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-runtime-stream-delivery-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker prompts, merge review, conflict resolution, full gates, integration merge record, and cleanup.

## Goal

Refactor the next cohesive user-visible stream/terminal boundary in one behavior-compatible batch:

- move task runtime stream normalization out of `boot.py`;
- consolidate session event buffering/subscriber delivery so `EventBridge`, RPC handlers, and boot inline emitters use the same delivery path;
- keep WebUI task-terminal migration behavior explicit and tested while server payloads carry `terminal_message`;
- preserve task terminal payloads, raw error details, stream replay sequencing, epoch injection, subscriber routing, and static frontend fallback behavior.

## Current-State Audit

- Current integration HEAD before child worktree: `b838642` (`Record task runtime terminalization cleanup`).
- Worktree status before child creation: clean.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed from integration.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-task-runtime-terminalization-boundary-batch.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/event_bridge.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/session_streams.py`
  - `src/opensquilla/session/rpc_payload.py`
  - `src/opensquilla/gateway/static/js/views/chat.js`
  - `tests/test_gateway/test_task_runtime_terminal_message.py`
  - `tests/test_gateway/test_rpc_session_events.py`
  - `tests/test_gateway/test_chat_view_static.py`
  - `tests/test_session/test_session_rpc_payload.py`
- Symbols or command surfaces inspected:
  - `boot._emit_task_runtime_stream_events`
  - `boot.run_task_runtime_turn`
  - boot inline `_emit_session_event`
  - `EventBridge.emit`
  - `buffer_session_event`
  - `emit_to_session_subscribers`
  - `SessionStreamRegistry.record`
  - `normalize_terminal_event_payload`
  - chat view `_CHAT_VIEW_STATE.taskTerminalAsSessionEvent`
  - chat view `_CHAT_VIEW_STATE.taskTerminalMessage`
- Tests inspected:
  - task runtime terminal message tests
  - RPC session event delivery tests
  - chat view static migration tests
  - session RPC terminal payload normalization tests
- Existing boundary pattern this stage follows:
  - Gateway modules keep orchestration in public facades while moving focused helper families to sibling modules.
  - Existing RPC send and task runtime boundary batches preserve compatibility imports while adding ownership tests.

## Superpowers Evidence

- `superpowers:using-superpowers`:
  - Evidence: read before stage work in this session; relevant skills were re-read for this stage.
- `superpowers:using-git-worktrees`:
  - Evidence: fixed active child worktree `../opensquilla-refactor-active` created on `codex/refactor-runtime-stream-delivery-boundary-batch` after confirming the path was absent.
- `superpowers:writing-plans`:
  - Evidence: this stage plan was written before implementation worker dispatch and before production edits.
- `superpowers:test-driven-development`:
  - Evidence: each worker must add/run a boundary RED test before production changes; RED commands are listed below and completion evidence must record expected failures.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: runtime stream extraction, session delivery consolidation, and WebUI static mapping have separate file ownership and can be implemented in parallel.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread `spawn_agent` was probed successfully with read-only agent `019e3cf6-3346-7410-a539-ec55b7d92998`; use same-thread workers first for this substage.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused checks, full child `scripts/refactor_gate.sh`, integration merge gate, stage record, and cleanup evidence are fresh and recorded.
- Parallelism decision:
  - `spawn_agent` probe: successful; a read-only agent started, inspected integration status, and made no edits.
  - Same-thread worker plan: dispatch independent implementation workers with explicit ownership.
  - External worker fallback: only use `scripts/refactor_external_agent.sh` fixed worktrees if same-thread implementation workers fail or cannot return usable changes.
- Historical evidence note:
  - Do not infer success from worker summaries. Main thread must inspect diffs, run focused checks, full gates, merge records, and cleanup.

## Boundary Decision

- Module batch:
  - `src/opensquilla/gateway/task_runtime_streaming.py`
  - `src/opensquilla/gateway/session_event_delivery.py`
  - `src/opensquilla/gateway/static/js/views/chat.js`
- Responsibilities moving out:
  - Task runtime stream event normalization, `stream_event_sink` fanout, terminal error payload rewriting, and raw-error re-raise behavior.
  - Shared buffering/subscriber routing for session events used by RPC, `EventBridge`, and boot inline session emitters.
  - Static task-terminal mapping tests that keep frontend fallback behavior isolated while server payloads carry terminal messages.
- Responsibilities staying in place:
  - Gateway service construction and dependency wiring in `boot.py`.
  - Task runtime public event names and payload compatibility.
  - `SessionStreamRegistry` replay storage semantics.
  - RPC epoch lookup/cache behavior.
  - WebUI consumption of `task.failed`, `task.timeout`, `task.abandoned`, and `task.cancelled` during migration.
- New module/file responsibility:
  - `task_runtime_streaming.py`: owns `emit_task_runtime_stream_events` and stream error terminal normalization.
  - `session_event_delivery.py`: owns shared `buffer_session_event` and subscriber delivery primitives independent of `RpcContext`.
  - `chat.js`: keeps task-terminal mapping centralized in `_CHAT_VIEW_STATE` helpers without duplicating gateway error text in event handlers.
- Public behavior that must not change:
  - `boot._emit_task_runtime_stream_events` remains available as a compatibility alias or thin delegator for existing tests/imports during this stage.
  - `session.event.error` payloads keep `message`, `terminal_message`, `terminal_reason`, and raw `error_message`.
  - `stream_event_sink` receives every wrapped stream event and sink failures are swallowed/logged.
  - `session.event.*` payloads are buffered with `session_key` and monotonic `stream_seq`.
  - RPC session event delivery still injects epoch for `session.event.*` and `sessions.changed`.
  - `sessions.*` events still include session subscribers in addition to message subscribers.
  - WebUI still maps `task.cancelled` to `session.event.done` and failure-like task terminals to `session.event.error`.
- Files explicitly out of scope:
  - TaskRuntime `_execute` and `shutdown` lifecycle extraction.
  - session storage schema and migrations.
  - provider/model behavior.
  - channel dispatch runtime semantics beyond using `EventBridge.emit`.
  - changing public WebSocket event names.

## Parallel Worker Ownership

- Worker `runtime-stream` owns:
  - Create `src/opensquilla/gateway/task_runtime_streaming.py`.
  - Create `tests/test_gateway/test_task_runtime_streaming_boundary.py`.
  - Modify `src/opensquilla/gateway/boot.py` only for imports/delegation of stream emission.
  - Modify `tests/test_gateway/test_task_runtime_terminal_message.py` only for new ownership/compatibility assertions.
- Worker `session-delivery` owns:
  - Create `src/opensquilla/gateway/session_event_delivery.py`.
  - Create `tests/test_gateway/test_session_event_delivery_boundary.py`.
  - Modify `src/opensquilla/gateway/event_bridge.py`, `src/opensquilla/gateway/rpc_session_events.py`, and the boot inline `_emit_session_event` call site.
  - Modify `tests/test_gateway/test_rpc_session_events.py` only for delivery helper ownership compatibility.
- Worker `webui-terminal` owns:
  - Modify `src/opensquilla/gateway/static/js/views/chat.js`.
  - Modify `tests/test_gateway/test_chat_view_static.py`.
  - Do not edit Python gateway runtime files.
- Main thread owns:
  - This stage document.
  - Worker prompts and base commit.
  - Merge order and conflict resolution for shared `boot.py`.
  - Focused batch verification, full child gate, integration merge/gate, stage record update, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers' edits during integration and must not revert unrelated changes.

## TDD Red/Green

- Failing test commands:
  - Worker runtime-stream: `uv run --extra dev pytest tests/test_gateway/test_task_runtime_streaming_boundary.py -q`
  - Worker session-delivery: `uv run --extra dev pytest tests/test_gateway/test_session_event_delivery_boundary.py -q`
  - Worker webui-terminal: `uv run --extra dev pytest tests/test_gateway/test_chat_view_static.py -q`
- Expected red failures:
  - Runtime stream owner module/test does not exist and `boot.py` still owns `_emit_task_runtime_stream_events`.
  - Shared session delivery owner module/test does not exist and delivery logic remains duplicated.
  - Static test fails until frontend task-terminal fallback ownership is tightened without changing event names.
- Behavior compatibility coverage:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_terminal_message.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_events.py -q`
  - `uv run --extra dev pytest tests/test_session/test_session_rpc_payload.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_session_streams.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_chat_view_static.py -q`
- Module-batch implementation:
  - Move stream normalization into `task_runtime_streaming.py` and import/delegate from `boot.py`.
  - Move shared buffering/subscriber delivery into `session_event_delivery.py` and reuse it from RPC and EventBridge paths.
  - Keep chat terminal mapping centralized and static-tested without changing visible task event behavior.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_streaming_boundary.py tests/test_gateway/test_session_event_delivery_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_session_streams.py tests/test_gateway/test_chat_view_static.py tests/test_session/test_session_rpc_payload.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/task_runtime_streaming.py src/opensquilla/gateway/session_event_delivery.py src/opensquilla/gateway/event_bridge.py src/opensquilla/gateway/rpc_session_events.py tests/test_gateway/test_task_runtime_streaming_boundary.py tests/test_gateway/test_session_event_delivery_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_chat_view_static.py tests/test_session/test_session_rpc_payload.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/task_runtime_streaming.py`
  - `src/opensquilla/gateway/session_event_delivery.py`
  - `tests/test_gateway/test_task_runtime_streaming_boundary.py`
  - `tests/test_gateway/test_session_event_delivery_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/event_bridge.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/static/js/views/chat.js`
  - `tests/test_gateway/test_task_runtime_terminal_message.py`
  - `tests/test_gateway/test_rpc_session_events.py`
  - `tests/test_gateway/test_chat_view_static.py`
- Test:
  - Boundary and compatibility tests listed in TDD Red/Green.
- Documentation:
  - `docs/refactor/stages/2026-05-19-runtime-stream-delivery-boundary-batch.md`

## Detailed Superpowers Implementation Plan

### Task 1: Base Plan And Worker Dispatch

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration before creating this child branch.
- [x] Confirm `spawn_agent` status.
  - Observed: same-thread read-only probe started successfully.
- [x] Create fixed active worktree on `codex/refactor-runtime-stream-delivery-boundary-batch`.
- [x] Write this stage plan before implementation.
- [x] Commit this stage plan as the worker base.
  - Commit: `02227c0` (`Plan runtime stream delivery boundary batch`).
- [x] Launch three worker slices with explicit ownership:
  - `runtime-stream`
  - `session-delivery`
  - `webui-terminal`
  - Same-thread `runtime-stream` worker: `019e3cf9-4b55-7e52-8618-70f2359e502c`.
  - Same-thread `session-delivery` worker: `019e3cf9-4c82-76a3-b03e-8dad80e4064a`.
  - Same-thread `webui-terminal` worker hit `agent thread limit reached`, so this slice used `scripts/refactor_external_agent.sh --slot webui-terminal --branch codex/refactor-webui-terminal-boundary --base 02227c0`.

### Task 2: Worker `runtime-stream`

- [x] Write RED tests in `tests/test_gateway/test_task_runtime_streaming_boundary.py`.
  - Import `emit_task_runtime_stream_events` from `opensquilla.gateway.task_runtime_streaming`.
  - Assert `boot._emit_task_runtime_stream_events` is the imported compatibility alias or a short delegator.
  - Assert stream `ErrorEvent(code="iteration_timeout")` emits the existing terminal payload and raises raw `RuntimeError`.
  - Assert `stream_event_sink` is called and sink failures do not block event emission.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_task_runtime_streaming_boundary.py -q` and confirm the expected missing-module or ownership failure.
  - RED: `4 failed`, all from `ModuleNotFoundError: No module named 'opensquilla.gateway.task_runtime_streaming'`.
- [x] Move `_emit_task_runtime_stream_events` implementation to `task_runtime_streaming.emit_task_runtime_stream_events`.
- [x] Keep `boot._emit_task_runtime_stream_events` compatible.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_streaming_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py -q`
  - touched-file `ruff check`
  - GREEN: `9 passed in 0.55s`.
  - Ruff: `All checks passed!`.
  - `git diff --check && git diff --cached --check`: passed with no output.
- [x] Commit with the required trailer.
  - Commit: `2092b89` (`Extract task runtime stream emission`).

### Task 3: Worker `session-delivery`

- [x] Write RED tests in `tests/test_gateway/test_session_event_delivery_boundary.py`.
  - Assert new `buffer_session_event` helper records only `session.event.*` with `session_key` and `stream_seq`.
  - Assert shared delivery sends `session.event.*` to message subscribers and buffers payload.
  - Assert `sessions.changed` also reaches session subscribers and still receives epoch when called through RPC path.
  - Assert `EventBridge.emit` delegates to the shared delivery helper rather than directly calling `get_session_streams().record`.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_session_event_delivery_boundary.py -q` and confirm the expected missing-module or ownership failure.
  - RED: expected `ModuleNotFoundError: No module named 'opensquilla.gateway.session_event_delivery'`.
- [x] Move shared buffering/subscriber routing to `session_event_delivery.py`.
- [x] Update `rpc_session_events.py`, `event_bridge.py`, and boot inline session emitter to delegate to the shared helper while preserving epoch behavior.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_session_event_delivery_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_session_streams.py tests/test_session/test_session_rpc_payload.py -q`
  - touched-file `ruff check`
  - GREEN: `43 passed`.
  - Ruff: passed.
  - `git diff --check`: passed.
- [x] Commit with the required trailer.
  - Commit: `e4989e5` (`Refactor session event delivery boundary`).

### Task 4: Worker `webui-terminal`

- [x] Write or tighten RED static tests in `tests/test_gateway/test_chat_view_static.py`.
  - Assert task-terminal mapping remains centralized in `_CHAT_VIEW_STATE.taskTerminalAsSessionEvent`.
  - Assert visible terminal fallback strings are isolated in `_CHAT_VIEW_STATE.terminalMessages`/`taskTerminalMessage`, not duplicated in task event handlers.
  - Assert `payload?.terminal_message` remains preferred.
- [x] Run `uv run --extra dev pytest tests/test_gateway/test_chat_view_static.py -q` and confirm the expected failure.
  - RED: `1 failed, 44 passed`; `_CHAT_VIEW_STATE.taskTerminalAsSessionEvent` was not yet using the centralized terminal status helper.
- [x] Adjust `chat.js` only if needed to centralize mapping/fallback behavior without changing public event handling.
- [x] Run focused worker checks:
  - `uv run --extra dev pytest tests/test_gateway/test_chat_view_static.py -q`
  - touched-file `ruff check tests/test_gateway/test_chat_view_static.py`
  - GREEN: `45 passed`.
  - Ruff: `All checks passed!`.
  - `git diff --check`: passed.
  - Worker also ran `scripts/refactor_gate.sh`: `2591 passed, 8 skipped`.
- [x] Commit with the required trailer.
  - Commit: `e0d8504` (`test: tighten webui task terminal mapping`).

### Task 5: Main-Thread Integration Review

- [x] Collect worker results and inspect diffs before trusting summaries.
- [x] Merge worker changes into `../opensquilla-refactor-active`, resolving shared `boot.py` conflicts manually.
  - Same-thread worker commits landed linearly on active child.
  - External webui worker merged with `db5209c` (`Merge webui terminal boundary worker`).
- [x] Run focused green command.
  - `uv run --extra dev pytest tests/test_gateway/test_task_runtime_streaming_boundary.py tests/test_gateway/test_session_event_delivery_boundary.py tests/test_gateway/test_task_runtime_terminal_message.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_session_streams.py tests/test_gateway/test_chat_view_static.py tests/test_session/test_session_rpc_payload.py -q`
  - Result: `97 passed in 0.57s`.
- [x] Run additional touched-file checks.
  - Touched-file ruff: `All checks passed!`.
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`: `Success: no issues found in 539 source files` with existing untyped-function notes.
  - `git diff --check`: passed with no output.
- [x] Run `scripts/refactor_gate.sh` in child.
  - Result: `2599 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Commit child verification/stage record.
  - Commit: `4903a1e` (`Record runtime stream delivery child verification`).
- [x] Merge child into integration with `git merge --no-ff`.
  - Merge commit: `e693592` (`Merge runtime stream delivery boundary batch`).
- [x] Run `scripts/refactor_gate.sh` in integration.
  - Result: `2601 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- [x] Record child hash, integration merge hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.
  - Removed `../opensquilla-refactor-active`.
  - Removed external worker worktree `../opensquilla-refactor-agent-webui-terminal`.
  - Ran `git worktree prune`.
  - Verified `test ! -e ../opensquilla-refactor-active` and `test ! -e ../opensquilla-refactor-agent-webui-terminal`.
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

- Child commit: `4903a1e` (`Record runtime stream delivery child verification`)
- Worker commits:
  - `2092b89` (`Extract task runtime stream emission`)
  - `e4989e5` (`Refactor session event delivery boundary`)
  - `e0d8504` (`test: tighten webui task terminal mapping`)
  - `db5209c` (`Merge webui terminal boundary worker`)
- Integration merge: `e693592` (`Merge runtime stream delivery boundary batch`)
- Verification evidence:
  - Focused batch: `97 passed in 0.57s`.
  - Touched-file ruff: `All checks passed!`.
  - Mypy: `Success: no issues found in 539 source files` with existing notes.
  - `git diff --check`: passed with no output.
  - Child `scripts/refactor_gate.sh`: `2599 passed, 8 skipped, 2 warnings`; gateway smoke passed.
  - Integration `scripts/refactor_gate.sh`: `2601 passed, 6 skipped, 2 warnings`; gateway smoke passed.
- Cleanup evidence:
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-webui-terminal`.
  - Ran `git worktree prune`.
  - Verified both removed paths are absent and `git worktree list --porcelain` has no extra refactor worktrees beyond `../opensquilla-refactor-integration`.
- Residual risk: boot cron-result manual delivery still has a small duplicated subscriber loop; leave it for a later boot wiring/service cleanup to avoid broadening this stream boundary.
- Next recommended slice: task runtime execution/shutdown lifecycle boundary, covering `_execute`, `shutdown`, and terminal state mutation helpers after this stream/session delivery layer is separate.
