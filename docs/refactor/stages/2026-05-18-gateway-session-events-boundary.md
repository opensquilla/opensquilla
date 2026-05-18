# Gateway Session Events Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move session message event buffering, stream cursor normalization, epoch injection, and WebSocket fanout out of `gateway/rpc_sessions.py` while preserving `sessions.messages.subscribe`, reset epoch, and replay behavior.

**Architecture:** Add a focused `opensquilla.gateway.rpc_session_events` boundary that owns session event payload enrichment and subscriber delivery. Keep `rpc_sessions.py` as the RPC method owner with compatibility wrappers for existing `_emit_to_subscribers` imports used by tests and older call sites.

**Tech Stack:** Python, Starlette gateway RPC, in-memory session stream registry, pytest, ruff, mypy.

---

## Stage

- Name: gateway-session-events-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-events-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-events-boundary`
- Owner: Codex main thread; read-only scout agents are auditing other possible future slices and must not edit this worktree.

## Goal

Extract non-handler event delivery helpers from `rpc_sessions.py` into a dedicated gateway boundary without changing WebSocket event names, replay cursor semantics, epoch injection, subscription selection, or public RPC response payloads.

## Current-state audit

- Current HEAD: `06c7ccb`.
- Worktree status: clean before adding this stage plan and RED tests.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/session_services.py`
  - `src/opensquilla/gateway/session_streams.py`
  - `tests/test_gateway/test_session_streams.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_session/test_epoch_migration.py`
  - `tests/test_session/test_epoch_production_path.py`
- Symbols or command surfaces inspected:
  - `_optional_stream_seq`
  - `_buffer_session_event`
  - `_emit_to_subscribers`
  - `_increment_and_emit_epoch`
  - `_handle_sessions_messages_subscribe`
  - `SessionStreamRegistry.record`
  - `messages_subscribe_response`
- Tests inspected:
  - `TestSessionsMessagesSubscribe.test_messages_subscribe_replays_buffered_events_after_cursor`
  - `TestSessionsMessagesSubscribe.test_messages_subscribe_reports_persisted_task_state_and_replay_gap`
  - `test_epoch_in_event_payload`
  - `test_emit_no_db_query_per_event`
  - `test_session_stream_registry_records_monotonic_stream_seq`
- Existing boundary pattern this stage follows:
  - `gateway/session_services.py` owns public access to manager/runtime state and private fallback compatibility.
  - `gateway/rpc_session_send_inputs.py` owns recently extracted send-input normalization while `rpc_sessions.py` keeps handler orchestration and compatibility names.
  - `session/rpc_payload.py` owns response payload construction.

## Boundary decision

- Responsibilities moving out:
  - Stream cursor normalization for `sessions.messages.subscribe`.
  - Session event buffering through `SessionStreamRegistry`.
  - Epoch cache lookup, DB warm-up, and epoch payload injection for session events.
  - WebSocket subscriber fanout for message and session subscribers.
  - Reset epoch increment plus best-effort `session.epoch_changed` emit.
- Responsibilities staying in place:
  - RPC method registration and validation.
  - Session lifecycle/reset/compact/send orchestration.
  - Agent task listing and replay response construction.
  - Existing `_emit_to_subscribers` and `_increment_and_emit_epoch` compatibility names in `rpc_sessions.py`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_events.py` owns `optional_stream_seq`, `buffer_session_event`, `emit_to_session_subscribers`, and `increment_and_emit_epoch`.
- Public behavior that must not change:
  - `session.event.*`, `sessions.changed`, and `session.epoch_changed` event names.
  - `stream_seq` and `session_key` enrichment only for `session.event.*` replay-buffered events.
  - Epoch injection on `session.event.*` and `sessions.changed` payloads.
  - `sessions.messages.subscribe` replay aliases `since_stream_seq` and `sinceStreamSeq`.
  - Existing imports of `opensquilla.gateway.rpc_sessions._emit_to_subscribers`.
- Files explicitly out of scope:
  - Task runtime queue/cancellation semantics.
  - Session stream registry storage implementation.
  - Web UI JavaScript behavior.
  - Provider/model routing and tools/channels slices.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_events.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.gateway.rpc_session_events'`.
- Minimal implementation:
  - Create `opensquilla.gateway.rpc_session_events`.
  - Move helper bodies from `rpc_sessions.py` into the new module.
  - Make `rpc_sessions.py` import the boundary helpers and keep thin compatibility wrappers.
  - Update `sessions.messages.subscribe` to call `optional_stream_seq`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_session_streams.py tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_session/test_epoch_migration.py::test_epoch_in_event_payload tests/test_session/test_epoch_production_path.py::test_emit_no_db_query_per_event -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_events.py tests/test_gateway/test_rpc_session_events.py`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_session_streams.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `tests/test_gateway/test_rpc_session_events.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-events-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_rpc_session_events.py`
  - `tests/test_gateway/test_session_streams.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_session/test_epoch_migration.py`
  - `tests/test_session/test_epoch_production_path.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-events-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-session-events-boundary`.
- [x] Write the failing event-boundary test.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run the focused test and touched-file checks.
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

- Revert the integration merge commit if the slice regresses event delivery or reset epoch behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `38f4db1` (`Move session events behind gateway boundary`)
- Integration merge: `d1bc3ec` (`Merge gateway session events boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-session-events-boundary` passed on branch `codex/refactor-gateway-session-events-boundary` at `06c7ccb`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_events.py -q` failed as expected with `ModuleNotFoundError: No module named 'opensquilla.gateway.rpc_session_events'`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_session_streams.py tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_session/test_epoch_migration.py::test_epoch_in_event_payload tests/test_session/test_epoch_production_path.py::test_emit_no_db_query_per_event -q` passed, `16 passed in 0.73s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_events.py tests/test_gateway/test_rpc_session_events.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_session_streams.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py -q` passed, `99 passed in 1.48s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 482 source files; whitespace passed; pytest passed with `2393 passed, 8 skipped, 2 warnings in 29.01s`; gateway smoke start/status/stop passed on `127.0.0.1:55575`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `c4207f9`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-events-boundary` produced merge commit `d1bc3ec`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 484 source files; whitespace passed; pytest passed with `2398 passed, 6 skipped, 2 warnings in 29.42s`; gateway smoke start/status/stop passed on `127.0.0.1:56392`.
- Residual risk:
  - Low. Existing `_emit_to_subscribers` and `_increment_and_emit_epoch` compatibility wrappers remain in `rpc_sessions.py`, and existing session replay/epoch tests pass.
- Next recommended slice:
  - Continue Phase 3 with a TaskRuntime reset/abort drain boundary, or open larger independent Provider/Tools/Web UI slices in parallel from the current integration head.
