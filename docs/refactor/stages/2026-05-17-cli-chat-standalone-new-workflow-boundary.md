# CLI Chat Standalone New Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/new` session creation and display workflow out of `chat_cmd.py` while preserving standalone REPL behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the standalone slash dispatcher and turn runner coordinator. Add a focused standalone session workflow module that owns `/new` session key generation, session manager creation, tool-context rebuilding, state replacement, and the user-facing "Started new session" message. Gateway `/new` stays in the existing gateway session workflow path.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, Rich console output.

---

## Stage

- Name: cli-chat-standalone-new-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-new-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-new-workflow-boundary`
- Owner: Codex main thread. A read-only explorer dispatch was attempted for standalone `/new` behavior and boundary shape, but spawning failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move standalone chat `/new` behind a dedicated CLI workflow boundary without changing session creation, model retention, tool context, prompt state, or display output.

## Current-state audit

- Current HEAD: `57c4e82`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-status-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - standalone `/new`
  - standalone exact slash token behavior
  - `ChatSessionState`
  - `_FakeSessionManager`
  - `_FakeServices`
- Tests inspected:
  - `test_standalone_status_commands_emit_without_turnrunner_calls`
  - `test_standalone_repl_uses_exact_slash_tokens`
  - `test_gateway_slash_new_passes_title_as_display_name`
  - `test_chat_standalone_status_slashes_use_workflow_boundary`
  - `test_chat_standalone_model_cost_slashes_use_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_standalone_status_workflows.py` owns standalone status/session display.
  - `chat_standalone_model_cost_workflows.py` owns standalone model/cost display and state update.
  - `tests/test_cli/test_chat_cmd.py` has AST boundary tests proving extracted workflow modules own literals and command details.

## Boundary decision

- Responsibilities moving out:
  - Standalone `/new` session key generation.
  - `session_manager.get_or_create(..., agent_id="main")` for the new session.
  - Rebuilding standalone tool context for the new session.
  - Replacing `ChatSessionState` while retaining the current model override.
  - Rendering `[green]Started new session{label}:[/green] {session_key}`.
- Responsibilities staying in place:
  - Initial standalone session creation before the REPL loop.
  - `_standalone_repl` slash command dispatch ordering.
  - Gateway `/new` behavior through `chat_session_workflows.py`.
  - Standalone `/status`, `/session`, `/models`, `/model`, `/cost`, `/tool-compress`, `/clear`, `/compact`, `/save`, `/image`, `/path`, and unknown-command handling.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_session_workflows.py` owns standalone session lifecycle slash workflows, starting with `/new`.
- Public behavior that must not change:
  - `/new` creates a session key with prefix `agent:main:standalone:` and an 8-character UUID suffix.
  - `/new Research Notes` prints `Started new session (Research Notes):` followed by the new key.
  - `/new` without a title prints `Started new session:` followed by the new key.
  - The next user message after `/new` runs against the new session and new tool context.
  - The active model override is retained across `/new`.
  - Exact slash token behavior remains: `/newer` is not treated as `/new`.
- Files explicitly out of scope:
  - Gateway `/new`.
  - Initial standalone session creation.
  - Standalone clear/compact/save/image/path behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_new_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_session_workflows.py` does not exist, `chat_cmd.py` imports no standalone session workflow function, and `_standalone_repl` still contains the `Started new session` literal.
- Minimal implementation:
  - Create `chat_standalone_session_workflows.py` with `handle_standalone_new_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the standalone `/new` inline block with a call that returns updated `session_key`, `tool_ctx`, and `state`.
  - Add focused behavior coverage for direct workflow output and REPL handoff to the next turn.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_new_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_new_workflow_creates_session_state_and_tool_context tests/test_cli/test_chat_cmd.py::test_standalone_new_command_updates_next_turn_session -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-new-workflow-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-new-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-new-workflow-boundary`.
- [x] Write `test_chat_standalone_new_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for standalone `/new`.
- [x] Add standalone REPL coverage proving the next turn uses the new session.
- [x] Run the focused boundary test and confirm it fails because the workflow module does not exist and dispatcher still owns standalone `/new` details.
- [x] Implement `chat_standalone_session_workflows.py`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/new`.
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

- Child commit: `bbe9c93`
- Integration merge: `f7bee3f`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-new-workflow-boundary` passed on branch `codex/refactor-cli-chat-standalone-new-workflow-boundary` at `57c4e82`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_new_slash_uses_workflow_boundary -q` failed as expected because `chat_standalone_session_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_new_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_new_workflow_creates_session_state_and_tool_context tests/test_cli/test_chat_cmd.py::test_standalone_new_command_updates_next_turn_session -q` passed: 3 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 157 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2321 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Stage close: `scripts/refactor_stage_close.sh` passed on child commit `bbe9c93`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `57c4e82`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-new-workflow-boundary` produced merge commit `f7bee3f`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2323 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only moves standalone `/new` session creation and display formatting while keeping dispatch ordering in `_standalone_repl`.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone clear/compact command workflows, or move gateway `/save` transcript dispatch if prioritizing gateway-only flow.
