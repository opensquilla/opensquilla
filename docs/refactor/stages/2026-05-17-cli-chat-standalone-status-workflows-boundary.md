# CLI Chat Standalone Status Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/status`, `/session`, and `/models` display workflows out of `chat_cmd.py` while preserving standalone REPL behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the standalone slash dispatcher and turn runner coordinator. Add a focused `chat_standalone_status_workflows.py` module that owns standalone status/session rendering and the standalone `/models` gateway-required notice. Gateway status, sessions, and model catalog behavior remain in existing gateway workflow paths.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, Rich console output.

---

## Stage

- Name: cli-chat-standalone-status-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-status-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-status-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for standalone status behavior and boundary shape, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move standalone chat status/model-catalog notices behind a dedicated CLI workflow boundary without changing standalone user-facing behavior.

## Current-state audit

- Current HEAD: `705e24d`.
- Worktree status: clean before stage-plan generation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-model-cost-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_model_cost_workflows.py`
  - `src/opensquilla/cli/chat_tool_compression_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - standalone `/status`
  - standalone `/session`
  - standalone `/models`
  - `ChatSessionState`
- Tests inspected:
  - `test_standalone_model_command_updates_next_turn_model`
  - `test_standalone_model_cost_workflow_updates_state_and_emits_usage`
  - `test_chat_standalone_model_cost_slashes_use_workflow_boundary`
  - existing gateway and shared workflow boundary tests
- Existing boundary pattern this stage follows:
  - `chat_standalone_model_cost_workflows.py` owns standalone model/cost display/update behavior.
  - `chat_tool_compression_workflows.py` owns shared standalone/gateway tool-compression behavior.
  - `tests/test_cli/test_chat_cmd.py` has AST boundary tests for extracted workflow modules.

## Boundary decision

- Responsibilities moving out:
  - Standalone `/status` and `/session` output formatting.
  - Standalone `/models` gateway-required notice.
- Responsibilities staying in place:
  - Standalone slash command dispatch ordering in `_standalone_repl`.
  - Gateway `/status`, `/session`, `/sessions`, and `/models` behavior.
  - Standalone `/new`, `/model`, `/cost`, `/tool-compress`, `/clear`, `/compact`, `/save`, `/image`, `/path`, and unknown-command handling.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_status_workflows.py` owns standalone status/session and model catalog notice display.
- Public behavior that must not change:
  - `/status` and `/session` print:
    - `[{ACCENT}]session[/] [dim]{state.session_key}[/dim]`
    - `[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]`
  - `/models` in standalone mode prints `[yellow]/models requires gateway mode.[/yellow]`.
  - Exact slash token behavior remains in `_standalone_repl`: `/models-extra` is not treated as `/models`.
- Files explicitly out of scope:
  - Gateway status/session/model catalog commands.
  - Standalone `/new`, `/model`, `/cost`, `/tool-compress`, `/clear`, `/compact`, `/save`, `/image`, and `/path`.
  - Help table rendering and unknown-command handling.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_status_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_status_workflows.py` does not exist, `chat_cmd.py` imports no standalone status workflow functions, and `_standalone_repl` still contains the `/models requires gateway mode` literal.
- Minimal implementation:
  - Create `chat_standalone_status_workflows.py` with `handle_standalone_status_command` and `handle_standalone_models_command`.
  - Import both functions in `chat_cmd.py`.
  - Replace standalone `/status` and `/session` inline output with `handle_standalone_status_command(state)`.
  - Replace standalone `/models` inline output with `handle_standalone_models_command()`.
  - Add focused behavior coverage for both outputs.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_status_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_status_workflow_emits_session_model_and_models_notice tests/test_cli/test_chat_cmd.py::test_standalone_status_commands_emit_without_turnrunner_calls -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_status_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_status_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-status-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-status-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-status-workflows-boundary`.
- [x] Write `test_chat_standalone_status_slashes_use_workflow_boundary`.
- [x] Add focused workflow behavior coverage for standalone status and models notice.
- [x] Add standalone REPL coverage proving status/models commands do not run TurnRunner.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns standalone status details.
- [x] Implement `chat_standalone_status_workflows.py`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/status`, `/session`, and `/models`.
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

- Child commit: `019e8b5`
- Integration merge: `ef7ad8b`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-status-workflows-boundary` passed on branch `codex/refactor-cli-chat-standalone-status-workflows-boundary` at `705e24d`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_status_slashes_use_workflow_boundary -q` failed as expected because `chat_standalone_status_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_status_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_status_workflow_emits_session_model_and_models_notice tests/test_cli/test_chat_cmd.py::test_standalone_status_commands_emit_without_turnrunner_calls -q` passed: 3 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_status_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 154 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2318 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `705e24d`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-status-workflows-boundary` produced merge commit `ef7ad8b`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2320 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only moves standalone display formatting and keeps slash dispatch ordering in `_standalone_repl`.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/new` session creation display, or move gateway `/save` transcript dispatch into a focused boundary if prioritizing gateway-only flow.
