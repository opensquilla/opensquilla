# Session Lifecycle Memory Preservation Boundary

## Stage

- Name: session-lifecycle-memory-preservation-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-session-lifecycle-memory-preservation-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: main Codex thread

## Goal

Move the remaining reset/compact memory-preservation orchestration out of
Gateway lifecycle handlers and into the session domain. This is a coarse
follow-up to the lifecycle flush boundary: Gateway keeps RPC context,
task-runtime drain, locking, epoch emission, mutations, and response assembly;
session code owns transcript inspection, missing-flush policy, agent-id
normalization, flush-service execution, and lifecycle flush failure outcomes.

## Current-State Audit

- Current HEAD before edits: `4e308a9`
- Worktree status before implementation:
  `?? docs/refactor/stages/2026-05-19-session-lifecycle-memory-preservation-boundary.md`
- Preflight:
  `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-session-lifecycle-memory-preservation-boundary`
  passed on branch `codex/refactor-session-lifecycle-memory-preservation-boundary`.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is
    outside this slice's files.
- Agent parallelism:
  - Same-thread provider explorer was attempted and created, but same-thread
    spawning hit `agent thread limit reached` for the second explorer.
  - External worker launched with
    `scripts/refactor_external_agent.sh --slot memory-compaction --branch codex/refactor-agent-memory-compaction --prompt /tmp/opensquilla-memory-compaction-explorer.md`.
  - External worker was read-only, recommended this slice, and its worktree and
    branch were removed before implementation.
- Serena use:
  - Activated `../opensquilla-refactor-active`.
  - Onboarding failed because Serena's memory maintenance template was missing
    in the local install.
  - Wrote project memories for Serena usage and coarse refactor cadence.
  - Used symbol overview and targeted pattern search on
    `src/opensquilla/session/lifecycle_flush.py` and
    `src/opensquilla/gateway/rpc_session_lifecycle.py`.
- Files inspected:
  `AGENTS.md`, `docs/refactor/overall-plan.md`, recent stage docs,
  `src/opensquilla/gateway/rpc_session_lifecycle.py`,
  `src/opensquilla/session/lifecycle_flush.py`,
  `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`,
  `tests/test_gateway/test_rpc_sessions.py`,
  `tests/test_session/test_session_lifecycle_flush.py`.
- Existing boundary pattern this stage follows:
  the session package owns lifecycle decisions and Gateway adapts session-domain
  results to RPC errors/responses.

## Boundary Decision

- Module batch: session lifecycle memory preservation for reset/compact.
- Responsibilities moving out:
  transcript loading, no-flush policy dispatch, agent-id normalization,
  flush-service execution, and session-domain lifecycle memory result
  materialization.
- Responsibilities staying in Gateway:
  RPC params/context access, task runtime drain, session storage lookup where
  required, lock boundaries, apply/truncate mutations, epoch emission,
  `RpcHandlerError` adaptation, and public response assembly.
- New module/file responsibility:
  `src/opensquilla/session/lifecycle_memory.py` owns the memory preservation
  orchestration for lifecycle actions.
- Public behavior that must not change:
  `sessions.reset`, `sessions.compact`, and `sessions.contextCompact` method
  names, payload keys, error codes/messages/details, flush receipt wire shape,
  task-runtime drain ordering, and session lock behavior.
- Files explicitly out of scope:
  `src/opensquilla/memory/session_flush.py`, context compaction model/provider
  config selection, provider/runtime orchestration, CLI, Web UI.

## TDD Red/Green

- Failing test command:
  `uv run --extra dev pytest tests/test_session/test_session_lifecycle_memory.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py -q`
- Expected red failure:
  `ModuleNotFoundError: No module named 'opensquilla.session.lifecycle_memory'`.
- Behavior compatibility coverage:
  missing flush service keeps existing failure code/details; available flush
  service keeps the exact execute arguments; Gateway lifecycle handlers no
  longer import direct flush orchestration helpers.
- Module-batch implementation:
  add `preserve_lifecycle_memory` and `LifecycleMemoryPreservation`, then update
  reset/compact handlers to call that session-domain boundary.
- Focused green command:
  `uv run --extra dev pytest tests/test_session/test_session_lifecycle_memory.py tests/test_session/test_session_lifecycle_flush.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_force_reset_drain.py tests/test_gateway/test_rpc_sessions.py::TestSessionsReset tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact tests/test_memory_flush.py -q`
- Focused green result:
  `41 passed`.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/session/lifecycle_memory.py src/opensquilla/session/lifecycle_flush.py src/opensquilla/gateway/rpc_session_lifecycle.py tests/test_session/test_session_lifecycle_memory.py tests/test_session/test_session_lifecycle_flush.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `uv run --extra dev mypy src/opensquilla/session/lifecycle_memory.py src/opensquilla/session/lifecycle_flush.py src/opensquilla/gateway/rpc_session_lifecycle.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/session/lifecycle_memory.py`
  - `tests/test_session/test_session_lifecycle_memory.py`
- Modify:
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-session-lifecycle-memory-preservation-boundary.md`

## Superpowers Detailed Implementation Plan

> REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan
> task-by-task. This stage used `superpowers:using-git-worktrees`,
> `superpowers:writing-plans`, `superpowers:test-driven-development`, and
> `superpowers:verification-before-completion`.

**Goal:** Create a session-domain memory-preservation boundary for
reset/compact lifecycle actions while preserving every public RPC payload and
flush receipt shape.

**Architecture:** Add `opensquilla.session.lifecycle_memory` as the orchestration
layer above `lifecycle_flush`. Gateway passes session manager, optional flush
service, key, session object, force flag, and principal scopes into the session
boundary. The session boundary returns a small result object with
`previous_session_id`, optional `receipt`, and optional session-domain failure;
Gateway remains responsible for converting failures into `RpcHandlerError` and
for applying reset/truncate mutations.

**Tech Stack:** Python dataclasses, async pytest, AST boundary tests, existing
RPC/session lifecycle tests, `ruff`, `mypy`, and `scripts/refactor_gate.sh`.

### Task 1: Lock Gateway Boundary Ownership With RED Tests

**Files:**
- Modify: `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
- Modify: `tests/test_gateway/test_rpc_sessions.py`
- Create: `tests/test_session/test_session_lifecycle_memory.py`

- [x] **Step 1: Write the failing Gateway boundary assertions**

```python
assert ("opensquilla.session.lifecycle_memory", "preserve_lifecycle_memory") in (
    lifecycle_imports
)
assert {
    ("opensquilla.session.keys", "normalize_agent_id"),
    ("opensquilla.session.lifecycle_flush", "execute_lifecycle_flush"),
    ("opensquilla.session.lifecycle_flush", "unavailable_flush_failure_for_transcript"),
}.isdisjoint(lifecycle_imports)
```

- [x] **Step 2: Write the failing session-domain contract tests**

```python
result = await preserve_lifecycle_memory(
    "reset",
    _TranscriptSessionManager([object(), object()]),
    None,
    "agent:main:webchat:abc123",
    SimpleNamespace(session_id="abc123", agent_id="agent-1"),
    force=False,
    principal_scopes={"operator.write"},
)
assert result.failure.code == "flush_unavailable"
assert result.failure.details["message_count"] == 2
```

```python
flush_service.execute.assert_awaited_once_with(
    transcript,
    "agent:main:webchat:abc123",
    agent_id="agent-custom",
    timeout=30.0,
    message_window=0,
    segment_mode="auto",
)
```

- [x] **Step 3: Run RED**

Run:

```bash
uv run --extra dev pytest \
  tests/test_session/test_session_lifecycle_memory.py \
  tests/test_gateway/test_rpc_session_lifecycle_boundary.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'opensquilla.session.lifecycle_memory'
```

### Task 2: Add Session-Domain Memory Preservation Orchestration

**Files:**
- Create: `src/opensquilla/session/lifecycle_memory.py`
- Reuse: `src/opensquilla/session/lifecycle_flush.py`

- [x] **Step 1: Add the result type**

```python
@dataclass(frozen=True)
class LifecycleMemoryPreservation:
    previous_session_id: str | None
    receipt: Any | None
    failure: SessionLifecycleFlushFailure | None = None
```

- [x] **Step 2: Add `preserve_lifecycle_memory`**

```python
async def preserve_lifecycle_memory(
    action: LifecycleFlushAction,
    session_manager: Any,
    flush_service: Any | None,
    key: str,
    session: Any | None,
    *,
    force: bool,
    principal_scopes: Container[str],
) -> LifecycleMemoryPreservation:
    previous_session_id = getattr(session, "session_id", None) if session else None
    transcript = await session_manager.get_transcript(key)
    if flush_service is None:
        return LifecycleMemoryPreservation(
            previous_session_id=previous_session_id,
            receipt=None,
            failure=unavailable_flush_failure_for_transcript(...),
        )
    agent_id = normalize_agent_id(getattr(session, "agent_id", None) or "main")
    flush_attempt = await execute_lifecycle_flush(...)
    return LifecycleMemoryPreservation(
        previous_session_id=previous_session_id,
        receipt=flush_attempt.receipt,
        failure=flush_attempt.failure,
    )
```

- [x] **Step 3: Keep package import contracts clean**

Production `session` code must not import `opensquilla.memory.session_flush`.
Receipt wire-shape compatibility remains covered in tests, where importing
`FlushReceipt` is allowed.

### Task 3: Thin Gateway Reset/Compact Lifecycle Handlers

**Files:**
- Modify: `src/opensquilla/gateway/rpc_session_lifecycle.py`

- [x] **Step 1: Replace direct lifecycle flush orchestration imports**

```python
from opensquilla.session.lifecycle_memory import preserve_lifecycle_memory
```

Remove direct Gateway imports of:

```python
normalize_agent_id
execute_lifecycle_flush
unavailable_flush_failure_for_transcript
```

- [x] **Step 2: Convert reset no-flush branch**

```python
preservation = await preserve_lifecycle_memory(
    "reset",
    ctx.session_manager,
    ctx.flush_service,
    key,
    session,
    force=force,
    principal_scopes=ctx.principal.scopes,
)
if preservation.failure is not None:
    _raise_lifecycle_flush_failure(preservation.failure)
```

- [x] **Step 3: Convert reset flush-service branch**

Use the same `preserve_lifecycle_memory(...)` call inside the session lock, then
pass `preservation.receipt` to `session_reset_response`.

- [x] **Step 4: Convert compact branches**

For missing flush service, allow `session` to be `None` as before so compact can
still operate without requiring storage. For available flush service, continue
requiring storage and an existing session before preserving lifecycle memory.

### Task 4: Focused Verification And Stage Record

**Files:**
- Modify: `docs/refactor/stages/2026-05-19-session-lifecycle-memory-preservation-boundary.md`

- [x] **Step 1: Run focused GREEN**

Run:

```bash
uv run --extra dev pytest \
  tests/test_session/test_session_lifecycle_memory.py \
  tests/test_session/test_session_lifecycle_flush.py \
  tests/test_gateway/test_rpc_session_lifecycle_boundary.py \
  tests/test_gateway/test_force_reset_drain.py \
  tests/test_gateway/test_rpc_sessions.py::TestSessionsReset \
  tests/test_gateway/test_rpc_sessions.py::TestSessionsCompact \
  tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact \
  tests/test_memory_flush.py -q
```

Expected:

```text
41 passed
```

- [x] **Step 2: Run touched-file checks**

```bash
uv run --extra dev ruff check \
  src/opensquilla/session/lifecycle_memory.py \
  src/opensquilla/session/lifecycle_flush.py \
  src/opensquilla/gateway/rpc_session_lifecycle.py \
  tests/test_session/test_session_lifecycle_memory.py \
  tests/test_session/test_session_lifecycle_flush.py \
  tests/test_gateway/test_rpc_session_lifecycle_boundary.py \
  tests/test_gateway/test_rpc_sessions.py

uv run --extra dev mypy \
  src/opensquilla/session/lifecycle_memory.py \
  src/opensquilla/session/lifecycle_flush.py \
  src/opensquilla/gateway/rpc_session_lifecycle.py --show-error-codes

git diff --check
```

Expected: ruff passes, mypy reports no issues in 3 source files, and
`git diff --check` has no output.

### Task 5: Full Gate, Merge, And Cleanup

**Files:**
- Modify only stage record after verification and merge evidence exists.

- [x] **Step 1: Run child full gate**

```bash
scripts/refactor_gate.sh
```

Result: ruff passed, mypy passed with no issues in 517 source files,
whitespace passed, pytest reported `2488 passed, 8 skipped`, gateway
start/status/stop/status smoke passed, and the script reported
`Refactor gate complete.`

- [ ] **Step 2: Commit child slice**

```bash
git add \
  src/opensquilla/session/lifecycle_memory.py \
  src/opensquilla/gateway/rpc_session_lifecycle.py \
  tests/test_session/test_session_lifecycle_memory.py \
  tests/test_gateway/test_rpc_session_lifecycle_boundary.py \
  tests/test_gateway/test_rpc_sessions.py \
  docs/refactor/stages/2026-05-19-session-lifecycle-memory-preservation-boundary.md
git commit -m "Extract session lifecycle memory preservation boundary" \
  -m "Move reset/compact transcript inspection and lifecycle flush orchestration into the session domain while preserving RPC behavior." \
  -m "Co-authored-by: Codex <noreply@openai.com>"
```

- [x] **Step 3: Merge and run integration gate**

```bash
git -C ../opensquilla-refactor-integration merge --no-ff \
  codex/refactor-session-lifecycle-memory-preservation-boundary \
  -m "Merge session lifecycle memory preservation boundary" \
  -m "Co-authored-by: Codex <noreply@openai.com>"
git -C ../opensquilla-refactor-integration scripts/refactor_gate.sh
```

- [x] **Step 4: Record evidence and cleanup worktree**

```bash
git -C ../opensquilla-refactor-integration worktree remove ../opensquilla-refactor-active
git -C ../opensquilla-refactor-integration worktree prune
git -C ../opensquilla-refactor-integration worktree list
```

Expected: no `opensquilla-refactor-active` or external refactor worker worktrees
remain beyond `../opensquilla-refactor-integration`.

### Plan Self-Review

- Spec coverage: covers current-state inspection, Serena usage, same-thread
  agent probing, external worker fallback, TDD RED/GREEN, stage record, full
  child/integration gates, merge, and cleanup.
- Placeholder scan: no `TBD`, `TODO`, or "implement later" placeholders remain
  in this plan.
- Type consistency: `preserve_lifecycle_memory` returns
  `LifecycleMemoryPreservation`; Gateway only consumes `previous_session_id`,
  `receipt`, and `failure`.

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

## Child Gate

- Full child gate: `scripts/refactor_gate.sh` passed.
- Child pytest summary: `2488 passed, 8 skipped`.
- Gateway smoke: start/status/stop/status completed and reported
  `Refactor gate complete.`

## Integration Gate

- Full integration gate: `scripts/refactor_gate.sh` passed.
- Integration pytest summary: `2490 passed, 6 skipped`.
- Gateway smoke: start/status/stop/status completed and reported
  `Refactor gate complete.`

## Rollback

- Revert the integration merge commit if the slice regresses reset/compact
  memory preservation behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `a39a268`
- Integration merge: `251b7f4`
- Stage record commit: `f36ac80`
- Cleanup: removed `../opensquilla-refactor-active`, ran `git worktree prune`,
  and verified no extra `opensquilla-refactor-*` worktrees remain beyond
  `../opensquilla-refactor-integration`.
- Verification evidence:
  - RED: `ModuleNotFoundError` for `opensquilla.session.lifecycle_memory`
  - Focused GREEN: `41 passed`
  - Touched ruff: passed
  - Touched mypy: passed
  - `git diff --check`: passed
  - Full child `scripts/refactor_gate.sh`: passed
  - Full integration `scripts/refactor_gate.sh`: passed
- Residual risk:
  low; reset/compact lifecycle memory preservation behavior is covered by
  session-domain unit tests, Gateway AST boundary tests, existing reset/compact
  behavior tests, memory flush tests, and full child/integration gates.
- Next recommended slice:
  provider-facing onboarding/status UI batch or a broader channel dispatch
  routing boundary, depending on current integration state after this gate.
