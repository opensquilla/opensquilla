# CLI Chat Standalone Model Cost Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/model` and `/cost` slash-command workflows out of `chat_cmd.py` while preserving standalone REPL behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the standalone slash dispatcher and turn runner coordinator. Add a focused `chat_standalone_model_cost_workflows.py` module that owns standalone model display/update and cost rendering. Gateway model/cost behavior stays in `chat_model_usage_workflows.py`.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, standalone TurnRunner chat loop.

---

## Stage

- Name: cli-chat-standalone-model-cost-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-model-cost-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-model-cost-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for standalone model/cost behavior and boundary shape, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move standalone chat model and cost slash workflows behind a dedicated CLI workflow boundary without changing standalone user-facing behavior.

## Current-state audit

- Current HEAD: `372015d`.
- Worktree status: clean before stage-plan generation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-tool-compress-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - standalone `/model`
  - standalone `/cost`
  - `ChatSessionState`
  - `UsageSummary`
  - existing gateway `handle_model_command` / `handle_cost_command`
- Tests inspected:
  - `test_standalone_repl_forwards_timeout`
  - `test_standalone_path_command_runs_as_plain_message`
  - `test_gateway_slash_model_updates_session_model`
  - `test_gateway_slash_cost_and_usage_emit_usage_views`
  - `test_chat_model_usage_slashes_use_workflow_boundary`
  - `test_chat_tool_compress_slashes_use_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_model_usage_workflows.py` owns gateway model/cost/usage behavior.
  - `chat_tool_compression_workflows.py` owns shared standalone/gateway tool-compression behavior.
  - `tests/test_cli/test_chat_cmd.py` has AST boundary tests for extracted workflow modules.

## Boundary decision

- Responsibilities moving out:
  - Standalone `/model` with no argument display.
  - Standalone `/model <new-model>` parsing, `state.model` update, and output.
  - Standalone `/cost` usage rendering.
- Responsibilities staying in place:
  - Standalone slash command dispatch ordering in `_standalone_repl`.
  - The local `model` variable in `_standalone_repl`, because later TurnRunner calls still use it.
  - Gateway `/model`, `/cost`, and `/usage` behavior in `chat_model_usage_workflows.py`.
  - Standalone `/new`, `/status`, `/models`, `/tool-compress`, `/clear`, `/compact`, `/save`, `/image`, `/path`, and unknown-command handling.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_model_cost_workflows.py` owns standalone model/cost workflows.
- Public behavior that must not change:
  - `/model` with no argument prints `[dim]model=<state.model or default>[/dim]` and does not change local `model`.
  - `/model provider/name` sets `state.model` to `provider/name`, prints `[green]model:[/green] provider/name`, and returns the new model so `_standalone_repl` updates its local `model` variable.
  - `/model` should still use `_slash_parts`, so exact slash token behavior remains unchanged.
  - `/cost` prints `state.usage.render()`.
  - Subsequent normal messages, `/path`, `/image`, and `/compact` still receive the latest local `model` after `/model <new-model>`.
- Files explicitly out of scope:
  - Gateway model/cost/usage workflows.
  - Standalone session lifecycle, clear/reset, compact, save, image, and path extraction.
  - TurnRunner streaming behavior.
  - Provider selector and compaction provider resolution.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_model_cost_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_model_cost_workflows.py` does not exist, `chat_cmd.py` imports no standalone model/cost workflow functions, and `_standalone_repl` still directly calls `state.usage.render()` in its body.
- Minimal implementation:
  - Create `chat_standalone_model_cost_workflows.py` with `handle_standalone_model_command` and `handle_standalone_cost_command`.
  - Import both functions in `chat_cmd.py`.
  - Replace standalone `/model` inline body with `new_model = handle_standalone_model_command(parts, state)` and update local `model` only when `new_model is not None`.
  - Replace standalone `/cost` inline body with `handle_standalone_cost_command(state)`.
  - Add focused behavior tests for the new workflow module and a standalone REPL test proving `/model` changes the model sent to the next TurnRunner call.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_model_cost_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_model_cost_workflow_updates_state_and_emits_usage tests/test_cli/test_chat_cmd.py::test_standalone_model_command_updates_next_turn_model -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_model_cost_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_model_cost_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-model-cost-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-model-cost-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-model-cost-workflows-boundary`.
- [x] Write `test_chat_standalone_model_cost_slashes_use_workflow_boundary`.
- [x] Add focused workflow behavior coverage for standalone model and cost output.
- [x] Add standalone REPL coverage proving `/model <new>` affects the next TurnRunner model.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns standalone model/cost details.
- [x] Implement `chat_standalone_model_cost_workflows.py`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/model` and `/cost`.
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

- Child commit: `e1a58ce`
- Integration merge: `a6f5175`
- Verification evidence:
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `372015d`.
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-model-cost-workflows-boundary` passed on branch `codex/refactor-cli-chat-standalone-model-cost-workflows-boundary` at `372015d`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_model_cost_slashes_use_workflow_boundary -q` failed as expected because `chat_standalone_model_cost_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_model_cost_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_model_cost_workflow_updates_state_and_emits_usage tests/test_cli/test_chat_cmd.py::test_standalone_model_command_updates_next_turn_model -q` passed: 3 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_model_cost_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 151 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2315 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration gate: `scripts/refactor_gate.sh` passed after merge `a6f5175`: ruff, mypy, whitespace, pytest 2317 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice preserves standalone `/model` local model propagation by returning the new model from the workflow and updating `_standalone_repl` only when a model argument is supplied.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/status` and `/models requires gateway mode` display handling, or move gateway `/save` transcript dispatch into a focused boundary if prioritizing gateway-only flow.
