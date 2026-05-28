# Gateway Session Facade Prune Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `rpc_sessions.py` into a pure RPC registration facade by moving private test/caller dependencies to the already extracted session boundary modules.

**Architecture:** Keep `rpc_sessions.py` responsible for registering public `sessions.*` RPC methods and delegating to focused Gateway session modules. Tests that currently import private facade aliases should import the owning boundary modules directly, so the facade no longer re-exports send-input, event, management, read-query, lifecycle, or compaction helper wrappers.

**Tech Stack:** Python, Gateway RPC dispatcher/context, Session event/read/lifecycle/management/send-input modules, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-facade-prune-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-facade-prune`
- Child worktree: `../opensquilla-refactor-active-gateway-session-facade-prune`
- Owner: Codex main thread. This slice proceeds sequentially because the live agent runtime still has stale shutdown entries; the scope is one Gateway session facade file plus tests.

## Goal

Remove compatibility-only private helper aliases from `rpc_sessions.py` after the session domain boundaries have been extracted.

## Current-State Audit

- Current HEAD: `1d9e61e` (`Record gateway session send boundary merge`).
- Worktree status: clean before writing this stage plan and RED test.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/rpc_session_send_inputs.py`
  - `src/opensquilla/session/manager.py`
  - `tests/test_gateway/test_force_reset_drain.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
  - `tests/test_session/test_epoch_migration.py`
  - `tests/test_session/test_epoch_production_path.py`
- Symbols or command surfaces inspected:
  - `rpc_sessions.py` top-level helper aliases and `sessions.*` handler registrations.
  - `rpc_session_events.emit_to_session_subscribers`.
  - `rpc_session_send_inputs.validate_session_attachments` and `resolve_session_attachments`.
  - `rpc_session_lifecycle.handle_sessions_reset`.
- Tests inspected:
  - Gateway attachment helper tests.
  - Upload endpoint attachment resolution tests.
  - Session epoch event emission tests.
  - Session management boundary tests.
- Existing boundary pattern this stage follows:
  - Session send, send-input, turn-runtime, events, lifecycle, management, and read-query modules already own behavior; `rpc_sessions.py` should no longer mirror their private helpers.

## Boundary Decision

- Responsibilities moving out:
  - Private facade constants and aliases for attachment validation.
  - Private facade wrappers for session events, read query helpers, management helpers, and compaction helpers.
  - Reset helper indirection that can use lifecycle defaults.
- Responsibilities staying in place:
  - Public RPC method registration and method/scope names.
  - Handler functions that delegate directly to their owning boundary modules.
- New module/file responsibility:
  - No new production module; the owning boundary modules already exist.
  - New architecture test locks `rpc_sessions.py` as a pure handler facade.
- Public behavior that must not change:
  - Public RPC methods, scopes, payloads, attachment validation, upload resolution, epoch event injection, reset behavior, and session send/create/list/patch/read behavior.
- Files explicitly out of scope:
  - Session storage/manager internals.
  - Gateway WebSocket transport internals.
  - Attachment ingest implementation.
  - Provider, Channels, Tools, and Web UI internals.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py::test_epoch_in_event_payload tests/test_session/test_epoch_production_path.py::test_emit_no_db_query_per_event tests/test_gateway/test_rpc_session_management_boundary.py -q`
- Expected red failure:
  - `test_rpc_sessions_facade_only_registers_session_handlers` fails because `rpc_sessions.py` still exposes private helper wrappers/constants and imports send-input/compaction helper modules directly.
- Minimal implementation:
  - Update tests to import session helper behavior from owning boundary modules.
  - Remove private helper wrappers/constants and now-unused imports from `rpc_sessions.py`.
  - Let lifecycle own reset drain/epoch helpers and pass the drain hook from the lifecycle boundary for testability.
- Focused green command:
  - Same as the RED command.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/session/manager.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py`
  - `git diff --check`

## Files

- Create:
  - `tests/test_gateway/test_rpc_session_facade_prune_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-facade-prune-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/session/manager.py`
  - `tests/test_gateway/test_force_reset_drain.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
  - `tests/test_session/test_epoch_migration.py`
  - `tests/test_session/test_epoch_production_path.py`
- Test:
  - Focused gateway/session facade and helper tests listed above.
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-facade-prune-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-facade-prune`.
- [x] Write the failing facade-prune boundary test.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the behavior-compatible facade prune.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [ ] Remove the active child worktree after the integration record is committed.

## Child Gate

- RED: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py::test_epoch_in_event_payload tests/test_session/test_epoch_production_path.py::test_emit_no_db_query_per_event tests/test_gateway/test_rpc_session_management_boundary.py -q`
  - Result: expected failure, `1 failed, 45 passed in 4.50s`.
  - Cause: `rpc_sessions.py` still exposed private helper wrappers/constants and direct helper imports.
- Focused GREEN: same command.
  - Result: `46 passed in 0.80s`.
- Reset drain regression check: `uv run --extra dev pytest tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsReset -q`
  - Result: `13 passed in 0.49s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/session/manager.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py`
  - Result: `All checks passed!`
- Whitespace: `git diff --check`
  - Result: passed.
- Broader gateway/session/epoch check: `uv run --extra dev pytest tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py -q`
  - Result: `156 passed in 1.36s`.
- Full child gate: `scripts/refactor_gate.sh`
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2420 passed, 8 skipped, 2 warnings in 26.34s`; gateway smoke passed on port `59871`; `Refactor gate complete.`

## Integration Gate

- Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture`
  - Result: passed on branch `codex/refactor-architecture` at `1d9e61e`.
- Integration merge: `git merge --no-ff codex/refactor-gateway-session-facade-prune`
  - Result: merge commit `da123c4`.
- Full integration gate: `scripts/refactor_gate.sh`
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2422 passed, 6 skipped, 2 warnings in 28.61s`; gateway smoke passed on port `60283`; `Refactor gate complete.`

## Rollback

- Revert the integration merge commit if session RPC registration, attachment validation/resolution, reset epoch emission, or session behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `f3f8a8f`
- Integration merge: `da123c4`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-facade-prune` passed on branch `codex/refactor-gateway-session-facade-prune` at `1d9e61e`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py::test_epoch_in_event_payload tests/test_session/test_epoch_production_path.py::test_emit_no_db_query_per_event tests/test_gateway/test_rpc_session_management_boundary.py -q` failed as expected with `1 failed, 45 passed in 4.50s`.
  - Focused green: same command passed with `46 passed in 0.80s`.
  - Reset drain regression check: `uv run --extra dev pytest tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsReset -q` passed with `13 passed in 0.49s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/session/manager.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py` passed.
  - Whitespace: `git diff --check` passed.
  - Broader gateway/session/epoch check: `uv run --extra dev pytest tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_facade_prune_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_session/test_epoch_migration.py tests/test_session/test_epoch_production_path.py -q` passed with `156 passed in 1.36s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 494 source files; whitespace passed; pytest `2420 passed, 8 skipped, 2 warnings in 26.34s`; gateway smoke start/status/stop passed on `127.0.0.1:59871`.
  - Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `1d9e61e`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-facade-prune` produced merge commit `da123c4`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 494 source files; whitespace passed; pytest `2422 passed, 6 skipped, 2 warnings in 28.61s`; gateway smoke start/status/stop passed on `127.0.0.1:60283`.
- Residual risk:
  - Low. The slice removes private compatibility aliases and redirects tests to owning boundary modules while preserving public RPC method registration and full integration behavior.
- Next recommended slice:
  - Continue with larger module-level slices using one active child worktree at a time. Good candidates: Provider runtime/config facade consolidation or a Web UI access module consolidation, with child worktree cleanup immediately after the integration record.
