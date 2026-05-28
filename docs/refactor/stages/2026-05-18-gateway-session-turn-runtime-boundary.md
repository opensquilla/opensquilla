# Gateway Session Turn Runtime Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `sessions.send` TaskRuntime enqueue and queue-full rollback path behind a focused gateway boundary without changing public RPC behavior.

**Architecture:** Keep `rpc_sessions.py` as the `sessions.send` RPC handler, transcript persistence owner, legacy background TurnRunner path, and subscriber event owner. Add `gateway/rpc_session_turn_runtime.py` for runtime enqueue, queue-full rollback response handling, and post-accept upload eviction on the TaskRuntime path.

**Tech Stack:** Python, Starlette gateway RPC dispatcher, TaskRuntime, pytest, ruff, mypy.

---

## Stage

- Name: gateway-session-turn-runtime-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-turn-runtime-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-turn-runtime-boundary`
- Owner: Codex main thread. Read-only scout agents are running in parallel for Provider/Engine, Session/Gateway runtime, and Tools/Web UI/Channels future slices; this implementation slice is owned here to avoid shared-file edits.

## Goal

Extract the TaskRuntime-specific enqueue/rejection path from `rpc_sessions.py` while preserving session send payloads, transcript rollback semantics, upload UUID eviction timing, run kind/memory controls, and queue mode behavior.

## Current-state audit

- Current HEAD: `06c7ccb`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-sessions-send-input-boundary.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/engine/start_turn.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
- Symbols or command surfaces inspected:
  - `_handle_sessions_send`
  - `start_turn_via_runtime`
  - `TaskQueueFullError`
  - `session_send_accepted_response`
  - `session_send_queue_full_details`
  - `session_send_queue_full_dirty_details`
  - `_QueueFullRuntime`
  - `_RollbackSessionManager`
- Tests inspected:
  - `TestSessionsSend.test_gateway_sessions_send_delegates_response_payloads_to_session_boundary`
  - `TestSessionsSend.test_gateway_sessions_send_delegates_input_normalization_to_gateway_boundary`
  - `TestSessionsSend.test_send_queue_full_rolls_back_and_returns_retryable_details`
  - `TestSessionsSend.test_send_queue_full_dirty_returns_orphan_details`
  - `tests/test_gateway/test_uploads_endpoint.py::test_file_uuid_resolved_via_store_returns_material_ref`
- Existing boundary pattern this stage follows:
  - `rpc_session_send_inputs.py` owns input normalization helpers and leaves `rpc_sessions.py` as orchestration.
  - `session.rpc_payload` owns public response payload shapes.
  - RPC handlers delegate focused behaviors to small gateway/session boundary modules while compatibility tests pin public payloads.

## Boundary decision

- Responsibilities moving out:
  - TaskRuntime enqueue call for `sessions.send`.
  - `TaskQueueFullError` translation into retryable/dirty RPC errors.
  - Queue-full transcript rollback with `remove_message`.
  - Success-path upload UUID eviction for the TaskRuntime path.
- Responsibilities staying in place:
  - RPC request validation, session intent application, route envelope construction, transcript persistence, and legacy background TurnRunner execution.
  - Subscriber event emission and terminal event normalization for the legacy background path.
  - The `sessions.send` method name, accepted payload shape, queue-full error codes/details, and upload behavior.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_turn_runtime.py` owns `enqueue_session_turn_via_runtime` and its private upload eviction helper.
- Public behavior that must not change:
  - Queue full with successful rollback returns `QUEUE_FULL`, `retryable=True`, and `rollback_message_id`.
  - Queue full with failed rollback returns `QUEUE_FULL_DIRTY`, `retryable=False`, and `orphan_message_id`.
  - Runtime acceptance returns the same `{"status": "accepted", "key": ..., "task_id": ...}` payload.
  - Consumed staged upload UUIDs are evicted only after the runtime accepts a turn, never on rejection.
  - `queueMode=steer` still maps to runtime mode `interrupt`.
- Files explicitly out of scope:
  - `gateway/task_runtime.py` scheduling and fairness behavior.
  - `engine/start_turn.py` ingress observability.
  - Legacy background TurnRunner streaming internals inside `_handle_sessions_send`.
  - Channel dispatch runtime enqueue paths.
  - Web UI static queue behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_runtime_enqueue_to_gateway_boundary -q`
- Expected red failure:
  - `rpc_session_turn_runtime.py` does not exist and `rpc_sessions.py` still imports/calls `start_turn_via_runtime` and owns `TaskQueueFullError` translation inline.
- Minimal implementation:
  - Add `opensquilla.gateway.rpc_session_turn_runtime.enqueue_session_turn_via_runtime`.
  - Move the TaskRuntime enqueue, queue-full rollback/error construction, and runtime success upload eviction into the new module.
  - Update `_handle_sessions_send` to compute `runtime_mode` and call the boundary when `ctx.task_runtime` is present.
  - Update boundary tests so queue-full response payload helpers are asserted in the new module rather than inline in `rpc_sessions.py`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_runtime_enqueue_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_response_payloads_to_session_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_queue_full_rolls_back_and_returns_retryable_details tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_queue_full_dirty_returns_orphan_details tests/test_gateway/test_uploads_endpoint.py::test_file_uuid_resolved_via_store_returns_material_ref -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_turn_runtime.py tests/test_gateway/test_rpc_sessions.py`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_uploads_endpoint.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_turn_runtime.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-turn-runtime-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-turn-runtime-boundary.md`

## Steps

- [x] Inspect current integration state, AGENTS.md, and `sessions.send` runtime enqueue surface.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-session-turn-runtime-boundary`.
- [x] Write failing runtime-boundary test.
- [x] Run focused test and confirm expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

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
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `1caf88b` (`Move session runtime enqueue behind gateway boundary`)
- Integration merge: `d229056` (`Merge gateway session turn runtime boundary`)
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_runtime_enqueue_to_gateway_boundary -q` failed as expected because `rpc_session_turn_runtime.py` did not exist.
- Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_runtime_enqueue_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_response_payloads_to_session_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_queue_full_rolls_back_and_returns_retryable_details tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_queue_full_dirty_returns_orphan_details tests/test_gateway/test_uploads_endpoint.py::test_file_uuid_resolved_via_store_returns_material_ref -q` passed, `5 passed in 0.81s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_turn_runtime.py tests/test_gateway/test_rpc_sessions.py` passed.
- Touched tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_uploads_endpoint.py -q` passed, `107 passed in 1.71s`.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 482 source files; whitespace passed; pytest passed with `2391 passed, 8 skipped, 2 warnings in 62.91s`; gateway smoke start/status/stop passed on `127.0.0.1:55176`.
- Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `06c7ccb`.
- Integration merge: `git merge --no-ff codex/refactor-gateway-session-turn-runtime-boundary` produced merge commit `d229056`.
- Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 482 source files; whitespace passed; pytest passed with `2393 passed, 6 skipped, 2 warnings in 29.58s`; gateway smoke start/status/stop passed on `127.0.0.1:55497`.
- Residual risk:
  - Low. The slice preserves the existing RPC handler envelope/session/persistence flow and only moves the TaskRuntime enqueue branch plus its queue-full rollback response handling behind a focused boundary. Legacy background TurnRunner behavior is untouched.
- Next recommended slice:
  - Continue the Session/Gateway runtime lane by moving `sessions.reset` TaskRuntime settle/cancel/drain behavior (`_drain_task_runtime_for_reset`) behind a focused boundary with tests that preserve no-false-interrupted semantics and reset drain timeouts.
