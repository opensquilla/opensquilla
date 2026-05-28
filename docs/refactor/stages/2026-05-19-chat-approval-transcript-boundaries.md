# Chat Approval Transcript Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: chat-approval-transcript-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-chat-approval-transcript-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-chat-approval-prompts-worker`
  - `codex/refactor-chat-standalone-transcript-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-chat-approval`
  - `../opensquilla-refactor-agent-chat-transcript`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  facade integration, verification, merge records, and cleanup.

## Goal

Continue Phase 1 CLI chat boundary thinning by turning approval prompt handling
and standalone transcript rewrite guards into focused modules while preserving
gateway approval behavior, standalone reset/compact safety, compatibility
imports from `opensquilla.cli.chat_cmd`, and existing slash command behavior.

## Current-state audit

- Current HEAD before child creation: `c5776f3` (`Record agent CLI command
  runtime integration cleanup`).
- Worktree status: clean before creating this stage.
- Preflight:
  - Integration: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Child: `scripts/refactor_preflight.sh --allow-dirty`
  - Result: branch/head/status verified, required Superpowers checkpoints
    listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
  - Prior chat stage records under `docs/refactor/stages/`.
- Symbols or command surfaces inspected:
  - `_maybe_handle_approval`
  - `_handle_elevated_command`
  - `_local_approval_resolver`
  - `_stream_response_gateway`
  - `_stream_response_turnrunner`
  - `_read_standalone_transcript`
  - `_flush_before_standalone_rewrite`
  - `_standalone_repl`
- Existing boundary pattern this stage follows:
  - Chat gateway workflow modules such as
    `chat_gateway_permissions_workflows.py`.
  - Chat standalone workflow modules such as
    `chat_standalone_session_workflows.py`.
  - Compatibility facade wrappers in `chat_cmd.py` with boundary tests.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: read current skill instructions this turn and used them to select
    per-substage skills instead of relying on a previous high-level plan.
- `superpowers:using-git-worktrees`:
  - Evidence: inspected integration git state, verified no active refactor
    child worktree existed, then created `../opensquilla-refactor-active` on
    `codex/refactor-chat-approval-transcript-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions and wrote this stage record
    before production edits or worker dispatch.
- `superpowers:test-driven-development`:
  - Evidence: worker prompts require RED boundary tests before creating new
    modules, and the main thread will add a RED facade ownership test before
    editing shared `chat_cmd.py`.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: approval prompt handling and standalone transcript rewrite guards
    are independent domains. Workers create disjoint modules and tests; the
    main thread alone edits shared `chat_cmd.py` after both workers merge.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread `spawn_agent` was probed and returned
    `SPAWN_AGENT_AVAILABLE`; this stage uses fresh workers with explicit
    branch/worktree ownership.
- `superpowers:verification-before-completion`:
  - Evidence: focused worker tests, facade tests, touched-file ruff/mypy,
    child `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`,
    merge hashes, and cleanup evidence are required before claiming completion.
- Parallelism decision:
  - Same-thread `spawn_agent` probe: available.
  - External worker fallback: not needed at stage start; if same-thread workers
    fail or become unavailable, use `scripts/refactor_external_agent.sh`.
- Historical evidence note:
  - Do not claim a prior stage used a Superpowers checkpoint unless the stage
    record or current command log contains evidence. Record gaps explicitly.

## Boundary Decision

- Module batch:
  - Approval worker: gateway/turnrunner approval prompt presentation,
    decision mapping, and local approval queue resolver.
  - Transcript worker: standalone durable transcript inspection and safe flush
    guard before reset/compact/clear rewrites.
  - Main thread: `chat_cmd.py` compatibility facade and call-site wiring.
- Responsibilities moving out:
  - `src/opensquilla/cli/chat_approval_prompts.py` owns parsing approval
    envelopes, rendering blocked/required/pending approval panels, mapping
    user decisions to resolver calls, bypass mode updates, and local approval
    resolver construction.
  - `src/opensquilla/cli/chat_standalone_transcript_rewrite.py` owns durable
    transcript reads and flush-before-rewrite fail-closed behavior.
- Responsibilities staying in place:
  - `chat_cmd.py` keeps the Typer command surface, gateway/standalone REPL
    coordination, slash dispatch, and compatibility re-exports/wrappers.
  - Existing gateway permission command workflows stay in
    `chat_gateway_permissions_workflows.py`.
  - Existing standalone session command workflows stay in
    `chat_standalone_session_workflows.py`.
- Public behavior that must not change:
  - Approval result envelopes for `blocked`, `approval_required`, and
    `approval_pending`.
  - Approval decision aliases: once, always, bypass, deny, plus legacy yes/no.
  - Bypass decision updates `elevated_state["mode"]` when provided.
  - Live display stop/start around prompt rendering.
  - Standalone reset/compact/clear refuses unsafe rewrites when durable
    transcript inspection fails, when flush service is missing, or when flush
    execution returns/raises an error.
  - Flush execution arguments: `agent_id="main"`, `timeout=30.0`,
    `message_window=0`, `segment_mode="auto"`.
  - Existing imports and tests that access helpers from `chat_cmd.py`.
- Files explicitly out of scope:
  - Provider, gateway daemon, engine runtime, artifact, file attachment, and
    web UI internals.
  - Gateway slash route modules except existing call-site compatibility.

## TDD Red/Green

- Approval worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_approval_prompts_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.chat_approval_prompts` does not exist.
  - Observed by worker: expected collection/import failure:
    `ImportError: cannot import name 'chat_approval_prompts' from 'opensquilla.cli'`.
- Approval worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_approval_prompts_boundary.py tests/test_cli/test_chat_cmd_approval.py -q`
  - Observed by worker: `16 passed`.
  - Main-thread verification after worker completion: `16 passed`.
  - Worker checks: ruff passed, mypy passed, `git diff --check` passed.
  - Worker commit: `adcdaa9` (`Extract chat approval prompt boundary`).
- Transcript worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_standalone_transcript_rewrite_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.chat_standalone_transcript_rewrite` does not exist.
  - Observed by worker: expected collection/import failure:
    `ImportError: cannot import name 'chat_standalone_transcript_rewrite' from 'opensquilla.cli'`.
- Transcript worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_standalone_transcript_rewrite_boundary.py tests/test_cli/test_chat_cmd.py::test_standalone_reset_refuses_non_empty_transcript_without_flush_service tests/test_cli/test_chat_cmd.py::test_standalone_compact_refuses_non_empty_transcript_without_flush_service tests/test_cli/test_chat_cmd.py::test_standalone_compact_flushes_before_compacting tests/test_cli/test_chat_cmd.py::test_standalone_compact_aborts_when_flush_fails -q`
  - Observed by worker: `16 passed`.
  - Main-thread verification after worker completion: `16 passed`.
  - Worker checks: ruff passed, mypy passed, `git diff --check` passed.
  - Worker commit: `a3e1102` (`Extract standalone transcript rewrite guard`).
- Main-thread facade RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd_facade_boundary.py -q`
  - Expected: failure showing `chat_cmd.py` still owns moved helper bodies
    instead of importing/delegating to the new modules.
  - Observed: `2 failed`, showing `chat_cmd._maybe_handle_approval` and
    `chat_cmd._read_standalone_transcript` were still local functions rather
    than the new boundary helpers.
- Main-thread facade GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_approval_prompts_boundary.py tests/test_cli/test_chat_standalone_transcript_rewrite_boundary.py tests/test_cli/test_chat_cmd_facade_boundary.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_chat_cmd.py -q`
  - Observed focused subset before full chat tests: `34 passed`.
  - Observed broader focused command: `169 passed`.
  - Main-thread facade commit: `d347e53` (`Refactor chat command facade
    boundaries`).
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_approval_prompts.py src/opensquilla/cli/chat_standalone_transcript_rewrite.py tests/test_cli/test_chat_approval_prompts_boundary.py tests/test_cli/test_chat_standalone_transcript_rewrite_boundary.py tests/test_cli/test_chat_cmd_facade_boundary.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_chat_cmd.py`
    - Observed: `All checks passed!`.
  - `uv run --extra dev mypy src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_approval_prompts.py src/opensquilla/cli/chat_standalone_transcript_rewrite.py --show-error-codes`
    - Observed: `Success: no issues found in 3 source files`.
  - `git diff --check`
    - Observed: clean.

## Files

- Create:
  - `src/opensquilla/cli/chat_approval_prompts.py`
  - `src/opensquilla/cli/chat_standalone_transcript_rewrite.py`
  - `tests/test_cli/test_chat_approval_prompts_boundary.py`
  - `tests/test_cli/test_chat_standalone_transcript_rewrite_boundary.py`
  - `tests/test_cli/test_chat_cmd_facade_boundary.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Test:
  - Approval and standalone focused tests listed above.
- Documentation:
  - This stage record.

## Steps

- [x] Run integration preflight.
- [x] Confirm active goal is restored and active.
- [x] Confirm project memory contains multi-branch parallelism and
      Superpowers-per-substage requirements.
- [x] Confirm `spawn_agent` is available.
- [x] Create fixed active worktree on
      `codex/refactor-chat-approval-transcript-boundaries`.
- [x] Run child preflight.
- [x] Write this stage plan before production edits.
- [x] Commit this stage plan as the worker base.
  - Commit: `4cf579a` (`Plan chat approval transcript boundaries`).
- [x] Dispatch two same-thread workers with explicit worktree/branch ownership.
  - Approval worker: `Lagrange`.
  - Transcript worker: `Sagan`.
- [x] Approval worker writes RED boundary tests and records RED output.
  - RED: expected collection/import failure because
    `opensquilla.cli.chat_approval_prompts` did not exist.
- [x] Transcript worker writes RED boundary tests and records RED output.
  - RED: expected collection/import failure because
    `opensquilla.cli.chat_standalone_transcript_rewrite` did not exist.
- [x] Approval worker implements boundary and records GREEN/check evidence.
  - Commit: `adcdaa9` (`Extract chat approval prompt boundary`).
- [x] Transcript worker implements boundary and records GREEN/check evidence.
  - Commit: `a3e1102` (`Extract standalone transcript rewrite guard`).
- [x] Merge approval worker branch into child with `git merge --no-ff`.
  - Merge: `1192278` (`Merge chat approval prompts worker`).
- [x] Merge transcript worker branch into child with `git merge --no-ff`.
  - Merge: `fa77b3f` (`Merge chat standalone transcript worker`).
- [x] Main thread writes RED facade boundary test.
  - RED: `2 failed`, showing `chat_cmd.py` still owned moved helpers.
- [x] Main thread delegates `chat_cmd.py` wrappers/call sites to new modules.
  - Commit: `d347e53` (`Refactor chat command facade boundaries`).
- [x] Run focused tests and touched-file checks.
  - Focused tests: `169 passed`.
  - Ruff: all checks passed.
  - Mypy: no issues in 3 source files.
  - `git diff --check`: clean.
- [x] Run child `scripts/refactor_gate.sh`.
  - Ruff: all checks passed.
  - Mypy: success on 572 source files.
  - Whitespace: clean.
  - Pytest: `2790 passed, 8 skipped, 2 warnings`.
  - Gateway smoke: passed on `127.0.0.1:57955`.
- [x] Commit child verification record.
  - Commit: `382b357` (`Record chat approval transcript child
    verification`).
- [x] Merge child into integration with `git merge --no-ff`.
  - Merge: `e1a5a56` (`Merge chat approval transcript boundaries`).
- [x] Run integration `scripts/refactor_gate.sh`.
  - Ruff: all checks passed.
  - Mypy: success on 572 source files.
  - Whitespace: clean.
  - Pytest: `2792 passed, 6 skipped, 2 warnings`.
  - Gateway smoke: passed on `127.0.0.1:58086`.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove temporary worker worktrees, remove `../opensquilla-refactor-active`,
      run `git worktree prune`, and verify no extra refactor worktree
      directories remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- Gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- Gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Approval worker commit:
  - `adcdaa9` (`Extract chat approval prompt boundary`).
- Transcript worker commit:
  - `a3e1102` (`Extract standalone transcript rewrite guard`).
- Active child worker merges:
  - `1192278` (`Merge chat approval prompts worker`).
  - `fa77b3f` (`Merge chat standalone transcript worker`).
- Main facade commit:
  - `d347e53` (`Refactor chat command facade boundaries`).
- Child verification commit:
  - `382b357` (`Record chat approval transcript child verification`).
- Integration merge:
  - `e1a5a56095b8c978ed11c7f74f240d610c0a642d` (`Merge chat approval
    transcript boundaries`).
- Integration record:
  - This record update after the integration gate and worktree cleanup.
- Verification evidence:
  - Approval worker RED: missing `opensquilla.cli.chat_approval_prompts`
    module.
  - Approval worker GREEN: `16 passed`; ruff, mypy, and `git diff --check`
    passed.
  - Transcript worker RED: missing
    `opensquilla.cli.chat_standalone_transcript_rewrite` module.
  - Transcript worker GREEN: `16 passed`; ruff, mypy, and `git diff --check`
    passed.
  - Main facade RED: `2 failed`; `chat_cmd.py` still owned approval and
    transcript helpers instead of delegating to the new modules.
  - Main facade GREEN focused subset: `34 passed`.
  - Broader focused command: `169 passed`.
  - Touched-file ruff: all checks passed.
  - Touched-file mypy: success, no issues in 3 source files.
  - `git diff --check`: passed.
  - Child full `scripts/refactor_gate.sh`: ruff passed; mypy success on 572
    source files; whitespace clean; pytest `2790 passed, 8 skipped, 2
    warnings`; gateway smoke passed on `127.0.0.1:57955`.
  - Integration full `scripts/refactor_gate.sh`: ruff passed; mypy success on
    572 source files; whitespace clean; pytest `2792 passed, 6 skipped, 2
    warnings`; gateway smoke passed on `127.0.0.1:58086`.
- Cleanup evidence:
  - Removed `../opensquilla-refactor-active`.
  - Removed `../opensquilla-refactor-agent-chat-approval`.
  - Removed `../opensquilla-refactor-agent-chat-transcript`.
  - Deleted merged branches:
    `codex/refactor-chat-approval-transcript-boundaries`,
    `codex/refactor-chat-approval-prompts-worker`, and
    `codex/refactor-chat-standalone-transcript-worker`.
  - Ran `git worktree prune`.
  - `git worktree list --porcelain` shows no `opensquilla-refactor-*`
    worktrees beyond `../opensquilla-refactor-integration`.
- Residual risk:
  - Low for this slice; approval prompt handling and standalone transcript
    rewrite guards are covered by dedicated boundary tests, compatibility
    facade tests, focused chat tests, and the full integration gate.
- Next recommended slice:
  - Continue CLI boundary thinning by extracting another cohesive `chat_cmd.py`
    route/runtime boundary, or switch to a Gateway/Session batch if CLI chat
    has reached a practical pause point after integration review.
