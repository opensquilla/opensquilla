# Session Lifecycle Flush Boundary

## Stage

- Name: session-lifecycle-flush-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-session-lifecycle-flush-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: main Codex thread, with same-thread agent availability probed

## Goal

Move reset/compact lifecycle flush policy and execution out of the Gateway RPC
handler and into the session domain as a cohesive boundary. This stage is a
coarse module-boundary refactor, not a helper-only move: the session package
now owns unavailable-flush rejection, force/admin policy, skipped/error receipt
construction, flush service call options, exception mapping, and disk-error
wire details for lifecycle actions.

## Current-State Audit

- Current HEAD before edits: `b8fdb52`
- Worktree status before implementation: dirty only from this stage plan and
  this slice's source/test edits.
- Preflight:
  `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-session-lifecycle-flush-boundary`
  passed on branch `codex/refactor-session-lifecycle-flush-boundary` at
  `b8fdb52`.
- AGENTS.md files in scope: root `AGENTS.md`; bootstrap template AGENTS is out
  of scope for this slice.
- Serena used for code navigation:
  `get_symbols_overview` and `search_for_pattern` on
  `src/opensquilla/gateway/rpc_session_lifecycle.py`, plus targeted symbol
  reads for `handle_sessions_reset` and `handle_sessions_compact`.
- Files inspected:
  `src/opensquilla/gateway/rpc_session_lifecycle.py`,
  `src/opensquilla/session/rpc_payload.py`,
  `src/opensquilla/memory/session_flush.py`,
  `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`,
  `tests/test_gateway/test_rpc_sessions.py`,
  `tests/test_session/test_session_rpc_payload.py`.
- Existing behavior preserved:
  reset/compact `flush_unavailable`, `permission_denied`, and
  `flush_disk_error` codes, messages, details keys, receipt serialization, and
  flush service execute arguments.

## Boundary Decision

- Module batch: session lifecycle flush policy/execution.
- Responsibilities moved out of Gateway:
  unavailable flush policy, force/admin rejection, skipped/error lifecycle
  receipts, flush execution call shape, exception-to-receipt mapping, and
  lifecycle disk-error failure payloads.
- Responsibilities staying in Gateway:
  RPC context access, session lookup, locking, task drain/epoch side effects,
  converting session-domain failures to `RpcHandlerError`, and response
  assembly.
- New module/file responsibility:
  `src/opensquilla/session/lifecycle_flush.py` owns Gateway-neutral lifecycle
  flush outcomes for reset/compact.
- Public behavior that must not change:
  JSON-RPC error codes/messages/details, reset/compact response payloads,
  flush receipt wire shape, and `FlushReceipt` semantics.
- Files explicitly out of scope:
  memory flush implementation internals, provider/runtime orchestration,
  Web UI, CLI command surfaces.

## TDD Red/Green

- RED test command:
  `uv run --extra dev pytest tests/test_session/test_session_lifecycle_flush.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsReset tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact -q`
- Expected RED failure:
  `ModuleNotFoundError: No module named 'opensquilla.session.lifecycle_flush'`.
- Green focused command:
  same command passed with `25 passed`, then `27 passed` after adding
  architecture-contract and receipt wire-shape coverage.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/session/lifecycle_flush.py src/opensquilla/gateway/rpc_session_lifecycle.py tests/test_session/test_session_lifecycle_flush.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `uv run --extra dev mypy src/opensquilla/session/lifecycle_flush.py src/opensquilla/gateway/rpc_session_lifecycle.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  `src/opensquilla/session/lifecycle_flush.py`,
  `tests/test_session/test_session_lifecycle_flush.py`
- Modify:
  `src/opensquilla/gateway/rpc_session_lifecycle.py`,
  `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`,
  `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  `docs/refactor/stages/2026-05-19-session-lifecycle-flush-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping
      existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child Gate

- First full child gate exposed an architecture regression:
  `session->memory` unexpected package import edge.
- Fix: keep lifecycle skipped/error receipt wire-shape local to
  `opensquilla.session.lifecycle_flush` and lock it against
  `FlushReceipt.to_dict()` in tests, without adding a production
  `session -> memory` dependency.
- Final full child gate: `scripts/refactor_gate.sh` passed.
- Final child pytest summary: `2486 passed, 8 skipped`.
- Gateway smoke: start/status/stop completed and reported
  `Refactor gate complete.`

## Integration Gate

- Pending after merge: `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: pending
- Integration merge: pending
- Verification evidence:
  - RED: `ModuleNotFoundError` for `opensquilla.session.lifecycle_flush`
  - Focused GREEN: `27 passed`
  - Touched ruff: passed
  - Touched mypy: passed
  - `git diff --check`: passed
  - Full child `scripts/refactor_gate.sh`: passed
- Residual risk:
  integration merge and integration gate are still pending.
- Next recommended slice:
  Provider/runtime orchestration boundary or memory flush/compaction ownership,
  whichever offers the larger coherent module-level consolidation after the
  integration gate.
