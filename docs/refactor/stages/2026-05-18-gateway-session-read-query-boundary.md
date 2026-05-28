# Gateway Session Read Query Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway session read/query RPC behavior out of the monolithic sessions RPC module while preserving every public session read method name, scope, payload, replay behavior, and subscription side effect.

**Architecture:** Add `gateway/rpc_session_read_queries.py` as the owner for session read/query behavior: `sessions.list`, `sessions.preview`, `sessions.resolve`, `sessions.subscribe`, `sessions.unsubscribe`, `sessions.messages.subscribe`, and `sessions.messages.unsubscribe`. Keep `gateway/rpc_sessions.py` as the RPC registration facade that delegates to the new read/query boundary. Existing event, lifecycle, send input, turn runtime, compaction, and session service boundaries remain in place.

**Tech Stack:** Python, Gateway RPC dispatcher, Session manager/storage, session streams, WebSocket registry, subscription manager, task runtime/storage state, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-read-query-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-read-query-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-read-query-boundary`
- Owner: Codex main thread. Parallel read-only explorer agents dispatched for symbols, tests, and stage-doc pattern; main thread owns edits, integration, and gate.

## Goal

Extract the related session read/query family from `rpc_sessions.py` into a focused Gateway boundary without changing public RPC behavior.

## Current-State Audit

- Current HEAD: `0579ed0` (`Record gateway session lifecycle boundary merge`).
- Worktree status: resumed from an existing child worktree with draft read/query boundary files; current git state was treated as authoritative and preserved.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-session-lifecycle-boundary.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `initial_instructions`, project activation, onboarding, and `get_symbols_overview` for `rpc_sessions.py`, `rpc_session_events.py`, and `rpc_session_lifecycle.py`.
  - Existing read/query RPC methods: `sessions.list`, `sessions.preview`, `sessions.resolve`, `sessions.subscribe`, `sessions.unsubscribe`, `sessions.messages.subscribe`, `sessions.messages.unsubscribe`.
  - Existing helper surfaces: `_list_task_rows`, `_list_task_rows_by_session`, `_resolve_session_node`, `_optional_stream_seq`, `_require_key`.
- Tests inspected:
  - Gateway session list, subscription, messages subscription, preview, and resolve behavior tests in `tests/test_gateway/test_rpc_sessions.py`.
  - Public RPC method/scope baseline in `tests/test_gateway/test_rpc_public_surface_baseline.py`.
- Existing boundary pattern this stage follows:
  - `rpc_session_events.py` owns event buffering/emission.
  - `rpc_session_lifecycle.py` owns lifecycle mutation implementations.
  - `rpc_session_send_inputs.py` owns send input/attachment normalization.
  - `rpc_session_turn_runtime.py` owns task runtime enqueue behavior.

## Boundary Decision

- Responsibilities moving out:
  - Session list query and task-state row aggregation.
  - Session preview query and transcript row payload preparation.
  - Session resolve query, including exact id/title/prefix matching and ambiguity handling.
  - Session subscription and unsubscription side effects.
  - Message subscription and unsubscription, stream replay, replay gap metadata, WebSocket replay delivery, and task state response enrichment.
- Responsibilities staying in place:
  - RPC method registration remains in `rpc_sessions.py`.
  - Session create/send/patch handlers remain in `rpc_sessions.py`.
  - Session abort/reset/delete/compact lifecycle handlers stay delegated to `rpc_session_lifecycle.py`.
  - Event stream buffer primitives stay in `rpc_session_events.py`.
  - Public response payload builders stay in `session.rpc_payload`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_read_queries.py` owns read/query implementations and their private helpers.
  - `rpc_sessions.py` keeps compatibility wrapper functions and delegates to the read/query boundary.
- Public behavior that must not change:
  - RPC method names and scopes remain unchanged.
  - Public payload field names and response builders remain unchanged.
  - Session stream replay and WebSocket replay side effects remain unchanged.
  - Persisted task-state fallback and storage batch behavior remain unchanged.
  - Error messages for missing/non-string `params.key`, not-found sessions, and ambiguous prefixes remain unchanged.
- Files explicitly out of scope:
  - Session storage/manager internals.
  - Task runtime scheduling internals.
  - Session send/create/patch/lifecycle behavior.
  - Web UI sessions JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsList tests/test_gateway/test_rpc_sessions.py::TestSessionsSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsPreview tests/test_gateway/test_rpc_sessions.py::TestSessionsResolve -q`
- Expected red failure:
  - `src/opensquilla/gateway/rpc_session_read_queries.py` does not exist.
  - `rpc_sessions.py` still owns read/query implementations and payload imports directly.
- Minimal implementation:
  - Create `rpc_session_read_queries.py`.
  - Move read/query implementations and their helpers into it.
  - Keep compatibility wrappers and RPC method registration in `rpc_sessions.py`.
  - Update architecture assertions in `tests/test_gateway/test_rpc_sessions.py` to inspect the new read/query boundary while preserving behavior tests.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsList tests/test_gateway/test_rpc_sessions.py::TestSessionsSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsPreview tests/test_gateway/test_rpc_sessions.py::TestSessionsResolve -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_read_queries.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-read-query-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-read-query-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-read-query-boundary`.
- [x] Write the failing Gateway session read/query boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible read/query extraction.
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

- Revert the integration merge commit if session read/query RPC behavior, subscription side effects, stream replay, task-state payloads, or response payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `c694ce0`
- Integration merge: `307372e`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-read-query-boundary` passed on branch `codex/refactor-gateway-session-read-query-boundary` at `0579ed0`.
  - Resume red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsList tests/test_gateway/test_rpc_sessions.py::TestSessionsSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsMessagesSubscribe tests/test_gateway/test_rpc_sessions.py::TestSessionsPreview tests/test_gateway/test_rpc_sessions.py::TestSessionsResolve -q` failed as expected with `18 failed, 8 passed`; failures showed `rpc_sessions.py` did not yet delegate and half-moved imports caused runtime errors such as `name 'time' is not defined`.
  - Focused green: the same focused RED command passed, `26 passed in 0.56s`.
  - Broader sessions read/query group: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_read_queries_boundary.py -q` passed, `87 passed in 1.12s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_read_queries.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_sessions.py` passed.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 492 source files; whitespace passed; pytest passed with `2415 passed, 8 skipped, 2 warnings in 43.04s`; gateway smoke start/status/stop passed on `127.0.0.1:53784`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-read-query-boundary` produced merge commit `307372e`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 492 source files; whitespace passed; pytest passed with `2417 passed, 6 skipped, 2 warnings in 29.95s`; gateway smoke start/status/stop passed on `127.0.0.1:54272`.
- Residual risk:
  - Low. The slice moves read/query and subscription implementation behind wrapper registrations while preserving public method names, scopes, payload builders, replay behavior, and existing behavior tests.
- Next recommended slice:
  - Continue shrinking `rpc_sessions.py` by extracting the remaining create/send/patch registration-adjacent behavior, or move to the next Provider factory/config facade cleanup if session RPC boundaries are enough for this pass.
