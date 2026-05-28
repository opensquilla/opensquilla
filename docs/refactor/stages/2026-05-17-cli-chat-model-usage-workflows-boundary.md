# CLI Chat Model Usage Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the gateway chat `/model`, `/cost`, and `/usage` slash-command workflows out of `chat_cmd.py` while preserving interactive CLI behavior.

**Architecture:** Keep `chat_cmd.py` as the slash command dispatcher. Add a focused `chat_model_usage_workflows.py` module that owns model status/update and usage display workflows. Keep read-only list/model catalog commands in `chat_slash_workflows.py`, session lifecycle commands in `chat_session_workflows.py`, and maintenance commands in `chat_session_maintenance_workflows.py`.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, OpenSquilla gateway client protocol, `ChatSessionState`.

---

## Stage

- Name: cli-chat-model-usage-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-model-usage-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-model-usage-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for model/usage behavior and module-shape scouting, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move gateway chat model and usage slash workflows behind a dedicated CLI workflow boundary without changing public command behavior.

## Current-state audit

- Current HEAD: `83bda1d`.
- Worktree status: clean before stage-plan generation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-maintenance-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_session_workflows.py`
  - `src/opensquilla/cli/chat_session_maintenance_workflows.py`
  - `src/opensquilla/cli/chat_slash_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `/model`
  - `/cost`
  - `/usage`
  - `_GatewayClientLike.patch_session`
  - `_GatewayClientLike.usage_status`
  - `ChatSessionState`
- Tests inspected:
  - `test_chat_slash_readonly_lists_use_workflow_boundary`
  - `test_chat_stateful_session_slashes_use_workflow_boundary`
  - `test_chat_session_maintenance_slashes_use_workflow_boundary`
  - `_FakeGatewayClient`
- Existing boundary pattern this stage follows:
  - `chat_slash_workflows.py` for read-only list/model catalog commands.
  - `chat_session_workflows.py` for stateful session lifecycle commands.
  - `chat_session_maintenance_workflows.py` for reset/compact maintenance commands.
  - AST boundary tests in `tests/test_cli/test_chat_cmd.py`.

## Boundary decision

- Responsibilities moving out:
  - `/model` display behavior for the current session model.
  - `/model <new-model>` session patch RPC, `state.model` update, and output.
  - `/cost` current session usage rendering.
  - `/usage` aggregate gateway usage RPC and output formatting.
- Responsibilities staying in place:
  - Slash command dispatch ordering in `_handle_gateway_slash_command`.
  - Other slash command families already extracted into focused modules.
  - `_GatewayClientLike` broad protocol shape in `chat_cmd.py` for now.
  - Standalone chat `/model` and `/cost` behavior.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_model_usage_workflows.py` owns model and usage workflows for interactive gateway chat.
- Public behavior that must not change:
  - `/model` with no argument prints `[dim]model=<state.model or default>[/dim]` and does not call the gateway.
  - `/model provider/name` calls `patch_session(state.session_key, model="provider/name")`, updates `state.model`, and prints `[green]model:[/green] provider/name`.
  - `/cost` prints `state.usage.render()`.
  - `/usage` calls `client.usage_status()` and prints `aggregate usage: <totalTokens:,> tok · $<totalCostUsd:.6f>`.
- Files explicitly out of scope:
  - Gateway RPC implementation.
  - Durable model catalog CLI commands.
  - Standalone chat model/cost handling.
  - `/models` catalog listing, already in `chat_slash_workflows.py`.
  - Tool compression and other cost-saving config commands.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_model_usage_workflows.py` does not exist, and `_handle_gateway_slash_command` still calls `patch_session`, `usage_status`, and `state.usage.render()` inline.
- Minimal implementation:
  - Create `chat_model_usage_workflows.py` with `handle_model_command`, `handle_cost_command`, and `handle_usage_command`.
  - Import those functions in `chat_cmd.py`.
  - Replace inline `/model`, `/cost`, and `/usage` bodies with calls to the new workflow functions.
  - Add focused behavior checks for `/model`, `/cost`, and `/usage` through `_handle_gateway_slash_command`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_model_usage_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_model_usage_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-model-usage-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-model-usage-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-model-usage-workflows-boundary`.
- [x] Write `test_chat_model_usage_slashes_use_workflow_boundary`.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns model/usage gateway calls.
- [x] Implement `chat_model_usage_workflows.py`.
- [x] Update `chat_cmd.py` to delegate `/model`, `/cost`, and `/usage`.
- [x] Add focused behavior tests for `/model`, `/cost`, and `/usage`.
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

- Child commit: `923d246`
- Integration merge: `185f1e2`
- Verification evidence:
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `83bda1d`.
  - `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-model-usage-workflows-boundary` passed on branch `codex/refactor-cli-chat-model-usage-workflows-boundary` at `83bda1d`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary -q` failed as expected because `chat_model_usage_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views -q` passed: 3 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_model_usage_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 146 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2310 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration gate: `scripts/refactor_gate.sh` passed after merge `185f1e2`: ruff, mypy, whitespace, pytest 2312 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice preserves existing `/model`, `/cost`, and `/usage` formatting while moving ownership out of the dispatcher. The broad `_GatewayClientLike` protocol still remains in `chat_cmd.py` for future incremental narrowing.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting `/tool-compress` gateway config workflow into a focused CLI workflow boundary with AST boundary tests and behavior coverage.
