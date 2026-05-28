# CLI Chat Standalone Clear Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/clear` and `/reset` session-reset workflow out of `chat_cmd.py` while preserving standalone REPL behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the slash dispatcher and turn runner coordinator. Extend `chat_standalone_session_workflows.py` so it owns standalone session lifecycle commands, now including `/clear` and `/reset` reset behavior. The shared `_flush_before_standalone_rewrite` safety hook remains in `chat_cmd.py` for this slice because `/compact` still shares it.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, Rich console output.

---

## Stage

- Name: cli-chat-standalone-clear-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-clear-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-clear-workflow-boundary`
- Owner: Codex main thread. A read-only explorer dispatch was attempted for standalone `/clear` behavior and boundary shape, but spawning failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move standalone `/clear` and `/reset` behavior behind the standalone session workflow boundary without changing flush safety, truncate behavior, local state reset, or display output.

## Current-state audit

- Current HEAD: `e09c3ab`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
  - `src/opensquilla/cli/repl/session_state.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - `_flush_before_standalone_rewrite`
  - standalone `/clear`
  - standalone `/reset`
  - `ChatSessionState`
  - `_FakeSessionManager`
  - `_FakeServices`
- Tests inspected:
  - `test_standalone_reset_refuses_non_empty_transcript_without_flush_service`
  - `test_standalone_compact_refuses_non_empty_transcript_without_flush_service`
  - `test_chat_standalone_new_slash_uses_workflow_boundary`
  - `test_standalone_new_workflow_creates_session_state_and_tool_context`
- Existing boundary pattern this stage follows:
  - `chat_standalone_session_workflows.py` already owns standalone `/new`.
  - `chat_standalone_status_workflows.py` and `chat_standalone_model_cost_workflows.py` demonstrate focused standalone workflow modules.
  - `tests/test_cli/test_chat_cmd.py` has AST boundary tests proving extracted standalone workflow modules own command details.

## Boundary decision

- Responsibilities moving out:
  - Calling the durable-transcript safety hook before reset.
  - Truncating the standalone durable session transcript.
  - Clearing local `state.transcript`.
  - Resetting local `state.usage`.
  - Rendering `[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]`.
- Responsibilities staying in place:
  - `_standalone_repl` slash command dispatch ordering.
  - `_flush_before_standalone_rewrite` implementation, shared with `/compact`.
  - Standalone `/compact`, `/save`, `/image`, `/path`, and unknown-command handling.
  - Gateway `/clear`, `/reset`, and `/compact` behavior.
- Existing module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_session_workflows.py` owns standalone session lifecycle slash workflows.
- Public behavior that must not change:
  - `/clear` and `/reset` are equivalent in standalone mode.
  - If the durable transcript cannot be flushed safely, no truncate/local reset happens and the existing warning from `_flush_before_standalone_rewrite` is preserved.
  - If safe, `session_manager.truncate(state.session_key, max_messages=0)` is called.
  - Local transcript and aggregate usage are reset only after safety succeeds.
  - The success output remains `cleared <session_key>` with existing `ACCENT` formatting.
- Files explicitly out of scope:
  - Standalone `/compact` implementation.
  - `_flush_before_standalone_rewrite` internals.
  - Gateway session maintenance workflows.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_clear_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_session_workflows.py` does not define/import `handle_standalone_clear_command`, and `_standalone_repl` still contains standalone clear/reset implementation details.
- Minimal implementation:
  - Add `handle_standalone_clear_command` to `chat_standalone_session_workflows.py`.
  - Import the handler in `chat_cmd.py`.
  - Replace the standalone `/clear` and `/reset` inline block with the handler call.
  - Add focused behavior coverage proving truncate, local transcript reset, usage reset, output, and safety-abort behavior.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_clear_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_clear_workflow_truncates_and_resets_state tests/test_cli/test_chat_cmd.py::test_standalone_clear_workflow_aborts_when_flush_guard_fails tests/test_cli/test_chat_cmd.py::test_standalone_reset_refuses_non_empty_transcript_without_flush_service -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-clear-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-clear-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-clear-workflow-boundary`.
- [x] Write `test_chat_standalone_clear_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for standalone clear success and safety abort.
- [x] Run the focused boundary test and confirm it fails because the workflow handler does not exist and dispatcher still owns standalone clear details.
- [x] Implement `handle_standalone_clear_command`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/clear` and `/reset`.
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

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `fb26484`
- Integration merge: `f7a90ec`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-clear-workflow-boundary` passed on branch `codex/refactor-cli-chat-standalone-clear-workflow-boundary` at `e09c3ab`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_clear_slash_uses_workflow_boundary -q` failed as expected because `handle_standalone_clear_command` was not imported/defined.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_new_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_chat_standalone_clear_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_clear_workflow_truncates_and_resets_state tests/test_cli/test_chat_cmd.py::test_standalone_clear_workflow_aborts_when_flush_guard_fails tests/test_cli/test_chat_cmd.py::test_standalone_reset_refuses_non_empty_transcript_without_flush_service -q` passed: 5 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 160 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2324 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Stage close: `scripts/refactor_stage_close.sh` passed on child commit `fb26484`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `e09c3ab`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-clear-workflow-boundary` produced merge commit `f7a90ec`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2326 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only moves standalone clear/reset reset mechanics and keeps the shared flush-safety helper and dispatch ordering unchanged.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/compact` into the same standalone session workflow boundary.
