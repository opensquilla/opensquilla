# Chat REPL Orchestration Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: chat-repl-orchestration-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-chat-repl-orchestration-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-chat-gateway-repl-worker`
  - `codex/refactor-chat-standalone-repl-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-chat-gateway-repl`
  - `../opensquilla-refactor-agent-chat-standalone-repl`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  facade compatibility wiring, verification, merge records, and cleanup.

## Goal

Continue Phase 1 CLI boundary thinning by moving the two largest remaining
`chat_cmd.py` REPL loops into focused orchestration modules while preserving
gateway chat behavior, standalone TurnRunner chat behavior, private
compatibility helpers from `chat_cmd.py`, and the existing test monkeypatch
surfaces.

## Current-state audit

- Current HEAD before child creation: `a851088` (`Record chat approval
  transcript integration cleanup`).
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
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - Existing `src/opensquilla/cli/chat_*.py` boundary modules.
  - `tests/test_cli/test_chat_cmd.py`
  - Prior chat stage records under `docs/refactor/stages/`.
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - `_gateway_chat`
  - `_handle_gateway_slash_command`
  - `_stream_response_gateway`
  - `_stream_response_turnrunner`
  - standalone workflow handlers
  - gateway workflow handlers
- Existing boundary pattern this stage follows:
  - Focused chat workflow modules with compatibility wrappers in `chat_cmd.py`.
  - Previous boundary tests that assert `chat_cmd.py` delegates while preserving
    legacy private helper access.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current Superpowers entrypoint was read earlier in this turn and
    used to select stage-specific skills for every refactor substage.
- `superpowers:using-git-worktrees`:
  - Evidence: integration state, recent commits, and worktree list were
    inspected; no active refactor child worktree existed; created
    `../opensquilla-refactor-active` on
    `codex/refactor-chat-repl-orchestration-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: this stage record was written before production edits and before
    launching workers.
- `superpowers:test-driven-development`:
  - Evidence: both workers must add RED boundary tests and record the expected
    failure before creating new REPL orchestration modules.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: gateway REPL orchestration and standalone REPL orchestration are
    independent domains. Workers create disjoint modules/tests; the main thread
    alone edits shared `chat_cmd.py` after both workers merge.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread `spawn_agent` probe returned
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
    record or current command log contains evidence. Missing per-substage
    Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway REPL orchestration worker.
  - Standalone REPL orchestration worker.
  - Main thread: `chat_cmd.py` compatibility facade wrappers.
- Responsibilities moving out:
  - `src/opensquilla/cli/chat_gateway_repl.py` owns connecting to the gateway,
    creating/resuming sessions, gateway chat intro rendering, prompt loop,
    slash-command dispatch integration, normal message streaming, transcript
    and usage accumulation, gateway RPC error display, and client close.
  - `src/opensquilla/cli/chat_standalone_repl.py` owns standalone service
    construction, session/tool context bootstrap, standalone chat intro loop,
    standalone slash route dispatch integration, normal TurnRunner streaming,
    transcript and usage accumulation, and service close.
- Responsibilities staying in place:
  - `chat_cmd.py` keeps Typer command options, command-mode selection,
    startup warning text before mode dispatch, and compatibility wrappers for
    `_gateway_chat` and `_standalone_repl`.
  - Existing slash route/workflow modules keep their route-specific ownership.
  - Existing stream/input/approval/transcript helper modules keep their helper
    ownership.
- Compatibility rule:
  - `chat_cmd._gateway_chat` and `chat_cmd._standalone_repl` may remain as thin
    wrappers, rather than direct aliases, so existing tests and downstream code
    that monkeypatch `chat_cmd.prompt_user`, `chat_cmd._stream_response_*`, or
    `chat_cmd._handle_gateway_slash_command` continue to work.
  - Boundary tests should assert the wrappers delegate to the new modules and
    no longer contain the full prompt loops.
- Public behavior that must not change:
  - Gateway mode creates sessions with the requested model and resumes
    explicit session IDs without creating a new session.
  - Gateway mode ignores `--model` for resumed sessions with the existing note.
  - Gateway mode closes the gateway client in a `finally` block.
  - Gateway slash commands keep their error handling and unknown-command text.
  - Standalone mode forwards timeout, workspace, workspace strictness, model,
    session key, and tool context fields.
  - Standalone slash command routing/order and all existing workflow calls
    remain unchanged.
  - EOF/Ctrl+C/quit goodbye text remains unchanged.
  - Existing `chat_cmd.py` private compatibility entry points remain callable.
- Files explicitly out of scope:
  - Existing route/workflow helper modules, unless imports are needed for new
    orchestration modules.
  - Gateway client implementation, engine runtime, session manager, provider,
    attachment helpers, and Web UI.

## TDD Red/Green

- Gateway worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.chat_gateway_repl` does not exist.
- Gateway worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_cmd.py::test_gateway_chat_forwards_model_to_create_session tests/test_cli/test_chat_cmd.py::test_gateway_chat_session_id_skips_create_session tests/test_cli/test_chat_cmd.py::test_gateway_chat_does_not_forward_workspace_fields -q`
- Standalone worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_standalone_repl_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.chat_standalone_repl` does not exist.
- Standalone worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_cmd.py::test_standalone_repl_forwards_timeout tests/test_cli/test_chat_cmd.py::test_standalone_chat_uses_workspace_in_tool_context tests/test_cli/test_chat_cmd.py::test_standalone_repl_wires_memory_services_into_turnrunner tests/test_cli/test_chat_cmd.py::test_standalone_repl_uses_exact_slash_tokens -q`
- Main-thread facade RED:
  - `uv run --extra dev pytest tests/test_cli/test_chat_repl_facade_boundary.py -q`
  - Expected: failure showing `chat_cmd.py` still owns full gateway and
    standalone REPL prompt loops instead of thin wrappers delegating to the new
    modules.
- Main-thread facade GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_repl_facade_boundary.py tests/test_cli/test_chat_cmd.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_repl.py src/opensquilla/cli/chat_standalone_repl.py tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_repl_facade_boundary.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev mypy src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_repl.py src/opensquilla/cli/chat_standalone_repl.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_repl.py`
  - `src/opensquilla/cli/chat_standalone_repl.py`
  - `tests/test_cli/test_chat_gateway_repl_boundary.py`
  - `tests/test_cli/test_chat_standalone_repl_boundary.py`
  - `tests/test_cli/test_chat_repl_facade_boundary.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py` only if compatibility injection points
    need to move to the new boundary modules.
- Documentation:
  - This stage record.

## Steps

- [x] Run integration preflight.
- [x] Confirm active goal remains active.
- [x] Confirm project memory contains multi-branch parallelism and
      Superpowers-per-substage requirements.
- [x] Confirm `spawn_agent` is available.
- [x] Create fixed active worktree on
      `codex/refactor-chat-repl-orchestration-boundaries`.
- [x] Run child preflight.
- [x] Write this stage plan before production edits.
- [x] Commit this stage plan as the worker base.
      Commit: `0ea4e16` (`Plan chat REPL orchestration boundaries`).
- [x] Dispatch two same-thread workers with explicit worktree/branch ownership.
      Workers: gateway branch
      `codex/refactor-chat-gateway-repl-worker`; standalone branch
      `codex/refactor-chat-standalone-repl-worker`.
- [x] Gateway worker writes RED boundary tests and records RED output.
      RED: `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py -q`
      failed on missing `opensquilla.cli.chat_gateway_repl`.
- [x] Standalone worker writes RED boundary tests and records RED output.
      RED: `uv run --extra dev pytest tests/test_cli/test_chat_standalone_repl_boundary.py -q`
      failed on missing `opensquilla.cli.chat_standalone_repl`.
- [x] Gateway worker implements boundary and records GREEN/check evidence.
      Commit: `4571521` (`Extract gateway chat REPL orchestration`);
      focused GREEN: `9 passed`.
- [x] Standalone worker implements boundary and records GREEN/check evidence.
      Commit: `d12acfb` (`Extract standalone chat REPL orchestration`);
      focused GREEN: `10 passed`.
- [x] Merge gateway worker branch into child with `git merge --no-ff`.
      Merge: `f3b8012` (`Merge chat gateway REPL worker`).
- [x] Merge standalone worker branch into child with `git merge --no-ff`.
      Merge: `46db55f` (`Merge chat standalone REPL worker`).
- [x] Main thread writes RED facade boundary test.
      RED: `uv run --extra dev pytest tests/test_cli/test_chat_repl_facade_boundary.py -q`
      failed with `2 failed`, proving `chat_cmd.py` still owned full
      `_gateway_chat` and `_standalone_repl` loops.
- [x] Main thread converts `chat_cmd.py` REPL bodies to compatibility wrappers.
      Commit: `fe15411` (`Refactor chat command REPL facade boundaries`).
- [x] Run focused tests and touched-file checks.
      Focused GREEN:
      `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_repl_facade_boundary.py tests/test_cli/test_chat_cmd.py -q`
      -> `153 passed`.
      Touched-file `ruff check` -> all checks passed.
      Touched-file `mypy ... --show-error-codes` -> success, no issues found.
      `git diff --check` -> clean.
- [x] Run child `scripts/refactor_gate.sh`.
      Result: ruff all checks passed; mypy success for 574 source files;
      pytest `2804 passed, 8 skipped, 2 warnings`; gateway smoke passed on
      port `59799`.
- [x] Commit child verification record.
      Commit: `b5a6b81` (`Record chat REPL child verification`).
- [x] Merge child into integration with `git merge --no-ff`.
      Merge: `fc8de7a` (`Merge chat REPL orchestration boundaries`).
- [x] Run integration `scripts/refactor_gate.sh`.
      Result: ruff all checks passed; mypy success for 574 source files;
      pytest `2806 passed, 6 skipped, 2 warnings`; gateway smoke passed on
      port `59987`.
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

- Revert the integration merge commit if gateway or standalone chat REPL
  behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Gateway worker commit:
- `4571521` (`Extract gateway chat REPL orchestration`).
- Standalone worker commit:
- `d12acfb` (`Extract standalone chat REPL orchestration`).
- Active child worker merges:
- `f3b8012` (`Merge chat gateway REPL worker`).
- `46db55f` (`Merge chat standalone REPL worker`).
- Main facade commit:
- `fe15411` (`Refactor chat command REPL facade boundaries`).
- Child verification commit:
- `b5a6b81` (`Record chat REPL child verification`).
- Integration merge:
- `fc8de7a` (`Merge chat REPL orchestration boundaries`).
- Integration record:
- Verification evidence:
- Focused tests:
  `uv run --extra dev pytest tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_repl_facade_boundary.py tests/test_cli/test_chat_cmd.py -q`
  -> `153 passed`.
- Touched-file ruff:
  `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_repl.py src/opensquilla/cli/chat_standalone_repl.py tests/test_cli/test_chat_gateway_repl_boundary.py tests/test_cli/test_chat_standalone_repl_boundary.py tests/test_cli/test_chat_repl_facade_boundary.py tests/test_cli/test_chat_cmd.py`
  -> all checks passed.
- Touched-file mypy:
  `uv run --extra dev mypy src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_repl.py src/opensquilla/cli/chat_standalone_repl.py --show-error-codes`
  -> success, no issues found.
- `git diff --check` -> clean.
- Child gate:
  `scripts/refactor_gate.sh` -> ruff all checks passed; mypy success for 574
  source files; pytest `2804 passed, 8 skipped, 2 warnings`; gateway smoke
  start/status/stop/status succeeded on port `59799`.
- Integration gate:
  `scripts/refactor_gate.sh` -> ruff all checks passed; mypy success for 574
  source files; pytest `2806 passed, 6 skipped, 2 warnings`; gateway smoke
  start/status/stop/status succeeded on port `59987`.
- Cleanup evidence:
- Removed worktrees:
  `../opensquilla-refactor-agent-chat-gateway-repl`,
  `../opensquilla-refactor-agent-chat-standalone-repl`, and
  `../opensquilla-refactor-active`.
- Deleted branches:
  `codex/refactor-chat-gateway-repl-worker`,
  `codex/refactor-chat-standalone-repl-worker`, and
  `codex/refactor-chat-repl-orchestration-boundaries`.
- Ran `git worktree prune`.
- Verified `git worktree list` contains no `opensquilla-refactor-*` worktrees
  other than `../opensquilla-refactor-integration`.
- Residual risk:
- No known behavior regressions after child and integration gates. Remaining
  risk is limited to unexercised live provider/gateway conversations, which are
  outside this offline refactor gate.
- Next recommended slice:
- Start the next coarse parallel batch from integration HEAD after cleanup:
  Session Persistence/Transcript Repository, MCP Tool Lifecycle/Registry,
  WebSocket Connection Core Boundary, and Web UI Browser Runtime Contract
  Harness. Keep Session/Channels delivery and Gateway chat RPC out of the same
  worker to avoid overlapping ownership.
