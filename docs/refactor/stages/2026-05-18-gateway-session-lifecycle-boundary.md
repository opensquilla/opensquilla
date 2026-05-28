# Gateway Session Lifecycle Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway session lifecycle RPC behavior out of the monolithic sessions RPC module while preserving every public session method name, scope, payload, and reset/flush safety guarantee.

**Architecture:** Add `gateway/rpc_session_lifecycle.py` as the owner for session lifecycle mutations: `sessions.abort`, `sessions.reset`, `sessions.delete`, `sessions.contextCompact`, and `sessions.compact`. Keep `gateway/rpc_sessions.py` as the registration facade that delegates to the lifecycle boundary. Existing send input, turn runtime, events, compaction inputs, and session service boundaries remain in place.

**Tech Stack:** Python, Gateway RPC dispatcher, Session manager/storage, task runtime, memory flush receipts, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-lifecycle-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-lifecycle-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-lifecycle-boundary`
- Owner: Codex main thread. A read-only lifecycle probe was attempted, but live `spawn_agent` still returned `agent thread limit reached`; this stage proceeds sequentially with the fallback recorded here.

## Goal

Extract the related session lifecycle mutation family from `rpc_sessions.py` into a focused Gateway boundary without changing public RPC behavior.

## Current-State Audit

- Current HEAD: `34e4334` (`Record gateway provider runtime boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/rpc_session_send_inputs.py`
  - `src/opensquilla/gateway/rpc_session_turn_runtime.py`
  - `src/opensquilla/gateway/session_services.py`
  - `src/opensquilla/gateway/task_runtime.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_force_reset_drain.py`
  - `tests/test_gateway/test_rpc_session_events.py`
  - `tests/test_gateway/test_rpc_session_services.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `rpc_sessions.py`, `rpc_session_events.py`, `rpc_session_send_inputs.py`, `rpc_session_turn_runtime.py`, `session_services.py`, and `task_runtime.py`.
  - Existing lifecycle RPC methods: `sessions.abort`, `sessions.reset`, `sessions.delete`, `sessions.contextCompact`, `sessions.compact`.
  - Existing reset safety helper: `_drain_task_runtime_for_reset`.
- Tests inspected:
  - Gateway session lifecycle behavior tests in `tests/test_gateway/test_rpc_sessions.py`.
  - Reset drain regression tests in `tests/test_gateway/test_force_reset_drain.py`.
  - Session service/event boundary tests.
- Existing boundary pattern this stage follows:
  - `rpc_session_events.py` already owns event buffering/emission.
  - `rpc_session_send_inputs.py` already owns send input/attachment normalization.
  - `rpc_session_turn_runtime.py` already owns task runtime enqueue behavior.
  - `session_services.py` already owns SessionManager public/private compatibility helpers.

## Boundary Decision

- Responsibilities moving out:
  - Abort task/runtime cancellation behavior.
  - Reset task drain, flush, force permission, epoch rotation, and reset response behavior.
  - Delete single/bulk session behavior.
  - Context compaction behavior.
  - Transcript compact/flush behavior.
- Responsibilities staying in place:
  - `sessions.send`, `sessions.create`, `sessions.list`, `sessions.patch`, subscription, preview, and resolve handlers stay in `rpc_sessions.py`.
  - Event emission helpers stay in `rpc_session_events.py`.
  - Send input/attachment helpers stay in `rpc_session_send_inputs.py`.
  - Turn runtime enqueue stays in `rpc_session_turn_runtime.py`.
  - Public response payload builders stay in `session.rpc_payload`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_lifecycle.py` owns lifecycle mutation implementations and reset drain logic.
  - `rpc_sessions.py` keeps RPC method registration wrappers and delegates to the lifecycle boundary.
- Public behavior that must not change:
  - RPC method names and scopes remain `sessions.abort`, `sessions.reset`, `sessions.delete`, `sessions.contextCompact`, and `sessions.compact`.
  - Public payloads stay delegated to `session.rpc_payload`.
  - Reset still drains task runtime before any state-clearing branch.
  - Flush-service unavailable paths remain fail-closed unless `force=true` with admin scope.
  - Existing `rpc_sessions._drain_task_runtime_for_reset` patch surface remains available for compatibility with current reset-drain tests.
- Files explicitly out of scope:
  - Session storage/manager internals.
  - Task runtime scheduling internals.
  - Send/create/list/patch/subscription/preview/resolve handlers.
  - Web UI sessions JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py::TestSessionsAbort tests/test_gateway/test_rpc_sessions.py::TestSessionsReset tests/test_gateway/test_rpc_sessions.py::TestSessionsDelete tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact -q`
- Expected red failure:
  - `src/opensquilla/gateway/rpc_session_lifecycle.py` does not exist.
  - `rpc_sessions.py` still owns lifecycle implementation and payload imports directly.
- Minimal implementation:
  - Create `rpc_session_lifecycle.py`.
  - Move lifecycle implementations and reset drain logic into it.
  - Keep compatibility wrappers and RPC method registration in `rpc_sessions.py`.
  - Update architecture tests to point to the new lifecycle boundary while preserving behavior tests.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py::TestSessionsAbort tests/test_gateway/test_rpc_sessions.py::TestSessionsReset tests/test_gateway/test_rpc_sessions.py::TestSessionsDelete tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_lifecycle.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-lifecycle-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_force_reset_drain.py`
- Test:
  - `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
  - `tests/test_gateway/test_force_reset_drain.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-lifecycle-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-lifecycle-boundary`.
- [x] Write the failing Gateway session lifecycle boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible lifecycle extraction.
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

- Revert the integration merge commit if session lifecycle RPC behavior, reset drain/flush safety, or response payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `73456d9`
- Integration merge: `c27228c`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-lifecycle-boundary` passed on branch `codex/refactor-gateway-session-lifecycle-boundary` at `34e4334`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py::TestSessionsAbort tests/test_gateway/test_rpc_sessions.py::TestSessionsReset tests/test_gateway/test_rpc_sessions.py::TestSessionsDelete tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact -q` failed as expected with 2 boundary failures because `rpc_session_lifecycle.py` did not exist and `rpc_sessions.py` did not delegate to it.
  - Minimal green: the same focused RED command passed, `25 passed in 0.56s`.
  - Broader sessions lifecycle group: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_services.py -q` passed, `95 passed in 1.04s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_lifecycle.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py` passed.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 491 source files; whitespace passed; pytest passed with `2413 passed, 8 skipped, 2 warnings in 53.99s`; gateway smoke start/status/stop passed on `127.0.0.1:51531`.
  - Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `34e4334`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-lifecycle-boundary` produced merge commit `c27228c`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 491 source files; whitespace passed; pytest passed with `2415 passed, 6 skipped, 2 warnings in 34.75s`; gateway smoke start/status/stop passed on `127.0.0.1:51718`.
- Residual risk:
  - Low to medium. The slice moves a large lifecycle handler family but preserves RPC registration wrappers, current response payload builders, reset-drain patch compatibility, and full behavior coverage for the touched session lifecycle tests.
- Next recommended slice:
  - Continue with a larger Gateway sessions read/query boundary for list/preview/resolve/subscriptions, or move to Provider factory/config facade cleanup.
