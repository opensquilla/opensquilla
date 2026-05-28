# Gateway Session Send Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway `sessions.send` orchestration out of the monolithic sessions RPC module while preserving public RPC behavior, attachment persistence, task-runtime enqueue semantics, event streaming, and terminal/error payloads.

**Architecture:** Add `gateway/rpc_session_send.py` as the owner for the send turn orchestration currently embedded in `rpc_sessions.py`. Keep `rpc_sessions.py` as the RPC registration facade and compatibility host for attachment helper aliases that existing tests and upload paths import. Existing send input, turn runtime, management, read/query, lifecycle, and event boundaries remain in place.

**Tech Stack:** Python, Gateway RPC dispatcher/context, Session manager/storage, attachment ingest, route envelopes, task runtime, TurnRunner stream wrappers, session event subscribers, pytest behavior and AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-send-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-send-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-send-boundary`
- Owner: Codex main thread. Prior parallel probes were attempted; runtime left stale shutdown entries, so this slice proceeds in the main thread with the fallback recorded here.

## Goal

Extract the session send orchestration family from `rpc_sessions.py` into a focused Gateway boundary without changing public RPC behavior.

## Current-State Audit

- Current HEAD: `40df888` (`Record gateway session management boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_send_inputs.py`
  - `src/opensquilla/gateway/rpc_session_turn_runtime.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
- Symbols or command surfaces inspected:
  - Existing send RPC method: `sessions.send`.
  - Existing helper surfaces: `_handle_sessions_send`, `_resolve_attachments`, `_validate_attachments`, `_session_turn_model`, `_emit_to_subscribers`, `_optional_positive_timeout`.
- Tests inspected:
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsSend`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - Upload endpoint tests importing `rpc_sessions` attachment helpers.
- Existing boundary pattern this stage follows:
  - `rpc_session_send_inputs.py` owns attachment/input normalization helpers.
  - `rpc_session_turn_runtime.py` owns task-runtime enqueue behavior.
  - `rpc_session_management.py` owns session management helpers used by send.

## Boundary Decision

- Responsibilities moving out:
  - The full `sessions.send` handler orchestration, including key/message validation, attachment ingestion, intent application, route envelope selection, transcript append, task-runtime enqueue path, TurnRunner background path, stream idle timeout handling, event emission, terminal event normalization, and upload eviction after turn acceptance.
- Responsibilities staying in place:
  - RPC method registration remains in `rpc_sessions.py`.
  - Attachment helper aliases and constants remain in `rpc_sessions.py` for compatibility with current tests and upload helper imports.
  - Send input normalization stays in `rpc_session_send_inputs.py`.
  - Task-runtime enqueue stays in `rpc_session_turn_runtime.py`.
  - Session management helpers stay in `rpc_session_management.py`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_send.py` owns send orchestration implementation and its private timeout helper.
  - `rpc_sessions.py` delegates `sessions.send` to the send boundary.
- Public behavior that must not change:
  - RPC method name and scope remain `sessions.send`/`operator.write`.
  - Accepted response, queue-full rollback/dirty details, terminal event payloads, and stream idle timeout code/message remain unchanged.
  - Attachment validation/persistence behavior and post-accept upload eviction remain unchanged.
  - Task runtime and fallback TurnRunner paths remain unchanged.
- Files explicitly out of scope:
  - Storage/manager internals.
  - Turn runtime queue implementation.
  - Attachment validation helper behavior.
  - Read/query, lifecycle, and management handlers.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsSend tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/rpc_session_send.py` does not exist.
  - `rpc_sessions.py` still owns the `sessions.send` implementation and direct send orchestration imports.
- Minimal implementation:
  - Create `rpc_session_send.py`.
  - Move `sessions.send` orchestration into it.
  - Keep compatibility attachment helper aliases in `rpc_sessions.py`.
  - Update send architecture assertions to inspect the new send boundary while preserving behavior tests.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsSend tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_send.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `tests/test_gateway/test_rpc_session_send_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-send-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_rpc_session_send_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-send-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-send-boundary`.
- [x] Write the failing Gateway session send boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible send extraction.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

## Child Gate

- RED: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsSend tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py -q`
  - Result: expected failure, `2 failed, 57 passed in 5.62s`.
  - Cause: `rpc_session_send.py` missing and `rpc_sessions.py` still owned the send orchestration.
- Focused GREEN: same command.
  - Result: `59 passed in 1.14s`.
- Touched lint: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_send.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py`
  - Result: `All checks passed!`
- Whitespace: `git diff --check`
  - Result: passed.
- Broader gateway/session check: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_public_surface_baseline.py -q`
  - Result: `141 passed in 1.38s`.
- Full child gate: `scripts/refactor_gate.sh`
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2419 passed, 8 skipped, 2 warnings in 27.26s`; gateway smoke passed on port `58195`; `Refactor gate complete.`

## Integration Gate

- Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture`
  - Result: passed on branch `codex/refactor-architecture` at `40df888`.
- Integration merge: `git merge --no-ff codex/refactor-gateway-session-send-boundary`
  - Result: merge commit `f0542be`.
- Full integration gate: `scripts/refactor_gate.sh`
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2421 passed, 6 skipped, 2 warnings in 28.59s`; gateway smoke passed on port `58423`; `Refactor gate complete.`

## Rollback

- Revert the integration merge commit if session send behavior, attachment persistence, task enqueue, event streaming, or terminal/error payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `6a52c4e`
- Integration merge: `f0542be`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-send-boundary` passed on branch `codex/refactor-gateway-session-send-boundary` at `40df888`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsSend tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py -q` failed as expected with `2 failed, 57 passed in 5.62s` because `rpc_session_send.py` did not exist and `rpc_sessions.py` still owned send orchestration.
  - Focused green: same command passed with `59 passed in 1.06s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_send.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py` passed.
  - Whitespace: `git diff --check` passed.
  - Broader gateway/session check: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_public_surface_baseline.py -q` passed with `141 passed in 1.38s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 494 source files; whitespace passed; pytest `2419 passed, 8 skipped, 2 warnings in 27.26s`; gateway smoke start/status/stop passed on `127.0.0.1:58195`.
  - Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `40df888`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-send-boundary` produced merge commit `f0542be`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 494 source files; whitespace passed; pytest `2421 passed, 6 skipped, 2 warnings in 28.59s`; gateway smoke start/status/stop passed on `127.0.0.1:58423`.
- Residual risk:
  - This is a module-level extraction of the existing send orchestration, so behavior risk is concentrated around import-time dispatcher registration and background TurnRunner event emission. Covered by focused send tests, attachment/upload tests, broader gateway session tests, public surface baseline, and full refactor gate.
- Next recommended slice:
  - Continue with larger module-level slices instead of one helper at a time. Reuse a small number of active worktrees, then remove merged temporary worktree directories after each integration record to avoid accumulating checkout folders.
  - Next technical slice: collapse remaining compatibility-only helpers in `rpc_sessions.py` after confirming no public tests or upload/session callers import them directly, or move the remaining reset/compact lifecycle glue into a broader lifecycle facade slice.
