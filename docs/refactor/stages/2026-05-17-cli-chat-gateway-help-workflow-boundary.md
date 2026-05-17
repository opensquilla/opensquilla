# CLI Chat Gateway Help Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/help` rendering behind a focused workflow boundary.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Add `chat_gateway_help_workflows.py` to own gateway `/help` table rendering through the existing `render_help_table()` and CLI console. Standalone `/help` remains unchanged and out of scope.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash dispatcher, chat REPL command registry.

---

## Stage

- Name: cli-chat-gateway-help-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-help-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-help-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only `/help` probe, but the current agent thread limit was reached; the fallback is recorded here per root `AGENTS.md`.

## Goal

Move gateway `/help` rendering out of `chat_cmd.py` into a focused workflow module without changing the help table, exact command matching, unknown command behavior, or standalone mode.

## Current-state audit

- Current HEAD: `684d28b`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-readonly-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/repl/commands.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `render_help_table`
  - `console.print`
  - gateway `/help`
- Tests inspected:
  - `TestChatCommand.test_chat_help`
  - gateway slash boundary tests around `_handle_gateway_slash_command`
  - `test_gateway_slash_unknown_prefix_is_not_handled`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps exact slash dispatch.
  - Focused workflow modules own behavior-specific rendering and presenter calls.
  - Boundary tests assert `_handle_gateway_slash_command` delegates and no longer calls rendering helpers directly.

## Boundary decision

- Responsibilities moving out:
  - Gateway `/help` rendering through `console.print(render_help_table())`.
- Responsibilities staying in place:
  - Exact `/help` command matching in `_handle_gateway_slash_command`.
  - Standalone mode `/help` rendering.
  - Help table content and command registry in `cli/repl/commands.py`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_help_workflows.py` owns gateway `/help` display behavior.
- Public behavior that must not change:
  - `/help` returns handled `True`.
  - `/help` prints the same `OpenSquilla Chat Commands` Rich table from `render_help_table()`.
  - `/helpful` and other unknown slash prefixes remain unknown.
  - Standalone `/help` behavior is unchanged.
- Files explicitly out of scope:
  - `opensquilla.cli.repl.commands` registry behavior.
  - Standalone chat command handling.
  - Unknown-command message text.
  - Gateway RPC server implementation.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_help_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_help_workflows.py` does not exist and `chat_cmd.py` still calls `render_help_table()` directly in `_handle_gateway_slash_command`.
- Minimal implementation:
  - Create `chat_gateway_help_workflows.py` with `handle_gateway_help_command`.
  - Update `chat_cmd.py` to import and call `handle_gateway_help_command` for exact `/help`.
  - Add focused behavior coverage that patches the new workflow console and verifies the help table output still appears.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_help_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_help_renders_help_table tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_help_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_help_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-help-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-help-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-help-workflow-boundary`.
- [x] Write `test_chat_gateway_help_uses_workflow_boundary`.
- [x] Add focused behavior coverage for gateway `/help`.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `chat_gateway_help_workflows.py`.
- [x] Update `chat_cmd.py` gateway `/help` dispatch.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.

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

- Child commit:
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-help-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-help-workflow-boundary` at `684d28b`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_help_uses_workflow_boundary -q` failed as expected because `chat_gateway_help_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_help_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_help_renders_help_table tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `3 passed in 0.60s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_help_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `214 passed in 2.32s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 472 source files; whitespace passed; pytest passed with `2378 passed, 8 skipped, 2 warnings in 44.58s`; gateway smoke start/status/stop passed on `127.0.0.1:62085`.
- Residual risk:
- Next recommended slice:
