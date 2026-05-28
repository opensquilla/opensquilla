# CLI Chat Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the gateway chat `/sessions` and `/models` slash-command workflows out of `chat_cmd.py` while preserving CLI behavior.

**Architecture:** Keep `chat_cmd.py` as the command dispatcher. Add a focused workflow module that owns parsing, gateway calls, usage messages, and presenter invocation for the two read-only list commands. Reuse `chat_presenters.py` for Rich table rendering.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, OpenSquilla gateway client protocol.

---

## Stage

- Name: cli-chat-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-workflows-boundary`
- Owner: Codex main thread; parallel scout unavailable because the agent thread limit is still reached.

## Current-state audit

- Current HEAD: `884ecb1`.
- Worktree status: clean before stage-plan generation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: only `src/opensquilla/identity/templates/bootstrap/AGENTS.md`, not under this stage's target files.
- Files inspected:
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_presenters.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `/sessions`
  - `/models`
  - `emit_chat_sessions_table`
  - `emit_chat_models_table`
  - `_GatewayClientLike.list_sessions`
  - `_GatewayClientLike.list_models`
- Tests inspected:
  - `test_chat_slash_tables_use_presenter_boundary`
  - `test_gateway_slash_sessions_uses_presenter_boundary`
  - `test_gateway_slash_models_does_not_hit_model_prefix`
- Existing boundary pattern this stage follows:
  - `*_workflows.py` modules in `src/opensquilla/cli`
  - `chat_presenters.py` from the prior chat presenter slice
  - AST boundary tests in `tests/test_cli/test_chat_cmd.py`

## Boundary decision

- Responsibilities moving out:
  - `/sessions [limit]` argument parsing and usage message.
  - `client.list_sessions(limit=...)`.
  - Passing session rows to `emit_chat_sessions_table`.
  - `/models` usage validation.
  - `client.list_models()`.
  - Passing model rows to `emit_chat_models_table`.
- Responsibilities staying in place:
  - Slash command dispatch ordering in `_handle_gateway_slash_command`.
  - Stateful commands such as `/new`, `/resume`, `/delete`, `/clear`, `/compact`, `/model`, `/save`, `/image`.
  - `_GatewayClientLike` protocol shape for the broader chat gateway client.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_slash_workflows.py` owns read-only gateway list workflows for interactive chat slash commands.
- Public behavior that must not change:
  - `/sessions` default limit remains `10`.
  - `/sessions <bad>` prints `[red]Usage: /sessions [limit][/red]` and is treated as handled.
  - `/sessions N` calls `list_sessions(limit=N)` and renders returned `sessions`.
  - `/models extra` prints `[red]Usage: /models[/red]` and does not call `list_models`.
  - `/models` calls `list_models()` once and leaves `state.model` unchanged.
- Files explicitly out of scope:
  - Gateway RPC implementation.
  - Session persistence.
  - Web UI.
  - Other slash commands besides `/sessions` and `/models`.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_slash_readonly_lists_use_workflow_boundary -q`
- Expected red failure:
  - `chat_slash_workflows.py` does not exist and `chat_cmd.py` still imports/calls presenters directly for these workflows.
- Minimal implementation:
  - Create `chat_slash_workflows.py` with `handle_sessions_command` and `handle_models_command`.
  - Import those functions in `chat_cmd.py`.
  - Replace the inline `/sessions` and `/models` bodies with calls to the new workflow functions.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_slash_readonly_lists_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_slash_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_slash_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write `test_chat_slash_readonly_lists_use_workflow_boundary`.
- [x] Run the focused test and confirm it fails because the workflow module does not exist.
- [x] Implement `chat_slash_workflows.py`.
- [x] Update `chat_cmd.py` to delegate `/sessions` and `/models`.
- [x] Update existing tests to monkeypatch workflow dependencies at the workflow boundary.
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

- Child commit: `d46526f` (`codex/refactor-cli-chat-workflows-boundary`)
- Integration merge: `775fa15` (`codex/refactor-architecture`)
- Verification evidence:
  - Child preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-workflows-boundary` passed.
  - Red check: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_slash_readonly_lists_use_workflow_boundary -q` failed before implementation because the workflow boundary file did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_slash_readonly_lists_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix -q` passed with 3 tests.
  - Touched checks: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_slash_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed with 141 tests.
  - Child gate: `scripts/refactor_gate.sh` completed ruff, mypy, diff check, full pytest, and gateway smoke successfully.
  - Integration gate: `scripts/refactor_gate.sh` on merge commit `775fa15` completed ruff, mypy, diff check, full pytest (`2307 passed, 6 skipped`), and gateway smoke successfully.
- Residual risk: Low. The slice only moves `/sessions` and `/models` read-only workflows behind a new CLI boundary and keeps the dispatcher behavior stable.
- Next recommended slice: Move the remaining stateful session slash commands (`/new`, `/resume`, `/delete`) behind a separate session workflow boundary after this slice is merged and re-gated on integration.
