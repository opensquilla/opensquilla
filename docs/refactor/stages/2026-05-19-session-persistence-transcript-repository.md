# Session Persistence Transcript Repository

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: Session persistence/transcript repository boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-session-persistence-transcript-repository`
- Child worktree: `../opensquilla-refactor-agent-session`
- Owner: Codex refactor worker

## Goal

Extract a behavior-compatible repository facade for session persistence and
transcript reads/writes so `SessionManager` no longer owns low-level
storage-routing decisions for this boundary.

## Current-state audit

- Current HEAD: `b7422a3`
- Worktree status: clean before edits
- AGENTS.md files in scope: `AGENTS.md`
- Files inspected:
  - `src/opensquilla/session/manager.py`
  - `src/opensquilla/session/storage.py`
  - `src/opensquilla/session/models.py`
  - `tests/test_session/test_manager.py`
  - `docs/refactor/stage-template.md`
- Symbols or command surfaces inspected:
  - `SessionManager.create`
  - `SessionManager.get_session`
  - `SessionManager.append_message`
  - `SessionManager.get_transcript`
  - `SessionManager._rotate_session_id`
  - `SessionStorage.upsert_session`
  - `SessionStorage.get_session`
  - `SessionStorage.append_transcript_entry`
  - `SessionStorage.get_transcript`
- Tests inspected:
  - `tests/test_session/test_manager.py`
  - `tests/test_session/test_epoch_production_path.py`
  - `tests/test_session/test_epoch_migration.py`
- Existing boundary pattern this stage follows:
  - Keep storage schema and persisted model shape in `SessionStorage`.
  - Add a narrow session-domain facade beside existing session service modules.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: existing child worktree verified at
    `../opensquilla-refactor-agent-session` on branch
    `codex/refactor-session-persistence-transcript-repository`.
- `superpowers:writing-plans`:
  - Evidence: this stage record documents the implementation plan before code
    edits.
- `superpowers:test-driven-development`:
  - Evidence: RED boundary tests will be written and run before implementation.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, and gate status will be
    recorded before any completion claim.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or
    `superpowers:subagent-driven-development` used: not used inside this child
    worker because the parent orchestration already assigned this bounded
    module slice.
  - `spawn_agent` probe: not run from this child worker.
  - If same-thread agents were unavailable, external worker fallback: this
    worktree is the external worker slot for the session slice.
- Historical evidence note:
  - Prior stage evidence is not claimed here; current git state and command
    outputs are authoritative.

## Boundary decision

- Module batch: session persistence and transcript repository facade.
- Responsibilities moving out:
  - Manager-level session load/save calls.
  - Manager-level transcript append/read/delete routing.
  - Manager-level compaction summary read/write routing.
- Responsibilities staying in place:
  - SQLite schema, migrations, transactions, and row serialization remain in
    `SessionStorage`.
  - Lifecycle, branching, compaction decisions, token updates, and public
    session keys remain in `SessionManager`.
- New module/file responsibility:
  - `src/opensquilla/session/repository.py` provides a session-domain facade
    over `SessionStorage` without changing storage schema.
- Public behavior that must not change:
  - Session key canonicalization, transcript ordering, epoch stale-write guard,
    token accounting, archive payload shape, and JSON dump keys.
- Files explicitly out of scope:
  - Gateway RPC/session delivery, channels, provider, tools, and web UI.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_session/test_manager.py::test_manager_routes_session_reads_and_transcript_writes_through_repository -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.session.repository'`
- Behavior compatibility coverage:
  - Manager session read returns unchanged `SessionNode`.
  - Manager append persists transcript content and token updates.
  - Manager transcript read preserves ordering and session-key lookup.
- Module-batch implementation:
  - Created `SessionPersistenceRepository` in
    `src/opensquilla/session/repository.py`.
  - Routed manager session CRUD, transcript append/read/delete, summary
    reads/writes, compaction rewrite, prune, and cap persistence calls through
    the repository facade.
- Focused green command:
  - `uv run --extra dev pytest tests/test_session/test_manager.py::test_manager_routes_session_reads_and_transcript_writes_through_repository -q`
  - Result: `1 passed in 0.31s`
- Additional touched-file checks:
  - `uv run --extra dev pytest tests/test_session/test_manager.py tests/test_session/test_epoch_production_path.py tests/test_session/test_epoch_migration.py -q`
  - Result: `49 passed in 1.90s`
  - `uv run --extra dev ruff check src/opensquilla/session/manager.py src/opensquilla/session/storage.py src/opensquilla/session/repository.py tests/test_session/test_manager.py`
  - Result: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/session/manager.py src/opensquilla/session/storage.py src/opensquilla/session/repository.py --show-error-codes`
  - Result: `Success: no issues found in 3 source files`
  - `git diff --check`
  - Result: exit 0

## Files

- Create:
  - `src/opensquilla/session/repository.py`
  - `docs/refactor/stages/2026-05-19-session-persistence-transcript-repository.md`
- Modify:
  - `src/opensquilla/session/manager.py`
- Test:
  - `tests/test_session/test_manager.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-session-persistence-transcript-repository.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping
      existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src/opensquilla/session/manager.py src/opensquilla/session/storage.py src/opensquilla/session/repository.py tests/test_session/test_manager.py`
- `uv run --extra dev mypy src/opensquilla/session/manager.py src/opensquilla/session/storage.py src/opensquilla/session/repository.py --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest tests/test_session/test_manager.py tests/test_session/test_epoch_production_path.py tests/test_session/test_epoch_migration.py`
- gateway smoke through `scripts/refactor_gate.sh`

Result: `scripts/refactor_gate.sh` passed. Full gate evidence:

- Ruff: `All checks passed!`
- Mypy: `Success: no issues found in 575 source files`
- Whitespace: `git diff --check` exit 0
- Pytest: `2805 passed, 8 skipped, 2 warnings in 65.04s`
- Gateway smoke: start/status/stop/status succeeded on `127.0.0.1:60913`

## Integration gate

- Integration merge: `f4c3450` (`Merge session persistence transcript
  repository`).
- Batch focused verification after merging Channels, Provider, Session,
  Gateway, and Web UI: focused pytest group passed with `110 passed`.
- Full integration gate after the coarse batch and stage-record path cleanup:
  `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues
  in 577 source files; whitespace passed; pytest `2822 passed, 6 skipped, 2
  warnings`; gateway smoke start/status/stop/status passed on
  `127.0.0.1:61875`; final line `Refactor gate complete.`
- Cleanup evidence: the Session worker worktree and child branch were removed,
  `git worktree prune` was run, and no `opensquilla-refactor-agent-*`
  worktrees remained after cleanup.

## Rollback

- Revert the child commit if this facade changes manager behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commits:
  - `26842c4` (`Extract session persistence repository`)
  - `28f4316` (`Record session persistence repository stage`)
- Integration merge: `f4c3450` (`Merge session persistence transcript repository`)
- Verification evidence:
  - RED boundary test failed before implementation because
    `opensquilla.session.repository` did not exist.
  - Focused manager/epoch tests passed after implementation.
  - Touched-file ruff, mypy, and diff checks passed.
  - Full `scripts/refactor_gate.sh` passed, including gateway smoke.
  - Integration coarse-batch focused tests passed with `110 passed`.
  - Full integration gate passed with ruff, mypy over 577 source files,
    whitespace, pytest `2822 passed, 6 skipped, 2 warnings`, gateway smoke on
    `127.0.0.1:61875`, and final line `Refactor gate complete.`
- Residual risk:
  - Repository facade is intentionally thin; storage transaction/schema
    ownership remains in `SessionStorage`.
- Cleanup evidence:
  - Session worker branch/worktree were removed and `git worktree prune`
    completed; only the integration refactor worktree remained for this refactor
    line.
- Next recommended slice:
  - Consider a later session slice for task-runtime repository boundaries if
    the integration owner wants the remaining ledger methods pulled out of
    `SessionStorage`.
