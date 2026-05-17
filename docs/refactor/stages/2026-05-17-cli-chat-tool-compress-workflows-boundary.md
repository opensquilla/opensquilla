# CLI Chat Tool Compression Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the gateway and standalone chat `/tool-compress` slash-command workflow out of `chat_cmd.py` while preserving interactive CLI behavior.

**Architecture:** Keep `chat_cmd.py` as the slash command dispatcher for both gateway and standalone chat loops. Add a focused `chat_tool_compression_workflows.py` module that owns `/tool-compress` parsing, alias normalization, config reads/writes, and output formatting. Keep unrelated chat session, model, usage, save, image, permissions, forget, and approval workflows in their current modules.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, OpenSquilla gateway client config RPC, local config objects, interactive chat slash dispatcher.

---

## Stage

- Name: cli-chat-tool-compress-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-tool-compress-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-tool-compress-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for current `/tool-compress` behavior and workflow module shape, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move chat `/tool-compress` config workflow behind a dedicated CLI workflow boundary without changing gateway or standalone behavior.

## Current-state audit

- Current HEAD: `bb705ed`.
- Worktree status: clean before child worktree creation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-model-usage-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_model_usage_workflows.py`
  - `src/opensquilla/cli/chat_session_maintenance_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - standalone `/tool-compress` dispatch in `run_chat_standalone` at `src/opensquilla/cli/chat_cmd.py:590`
  - gateway `/tool-compress` dispatch in `_handle_gateway_slash_command` at `src/opensquilla/cli/chat_cmd.py:854`
  - `_handle_tool_compress_command` at `src/opensquilla/cli/chat_cmd.py:950`
  - `_FakeGatewayClient.get_config`
  - `_FakeGatewayClient.patch_config_safe`
- Tests inspected:
  - `test_gateway_slash_tool_compress_toggles_config`
  - `test_gateway_slash_tool_compress_can_switch_to_summarize`
  - `test_gateway_slash_tool_compress_status_reads_config`
  - `test_standalone_tool_compress_toggles_config`
  - existing AST boundary tests for session, maintenance, and model/usage workflow modules
- Existing boundary pattern this stage follows:
  - `chat_session_maintenance_workflows.py` owns reset/compact gateway RPCs.
  - `chat_model_usage_workflows.py` owns model and usage gateway RPCs.
  - `tests/test_cli/test_chat_cmd.py` uses AST boundary tests to ensure dispatcher files do not retain moved workflow responsibilities.

## Boundary decision

- Responsibilities moving out:
  - `/tool-compress` argument parsing and validation.
  - Alias normalization: `on -> truncate`, `trim -> truncate`, `summary -> summarize`.
  - Config path constants for `agent_token_saving.tool_result_compression_*`.
  - Gateway config status reads through `get_config`.
  - Gateway config writes through `patch_config_safe`.
  - Standalone config object reads/writes.
  - Output formatting for usage, unavailable config, and resolved mode/model status.
- Responsibilities staying in place:
  - Gateway slash command dispatch ordering.
  - Standalone slash command dispatch ordering.
  - `_GatewayClientLike` broad protocol in `chat_cmd.py` for now.
  - Other chat slash workflows already extracted or explicitly out of scope.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_tool_compression_workflows.py` owns tool compression workflows for interactive chat.
- Public behavior that must not change:
  - `/tool-compress` with no argument behaves like `/tool-compress status`.
  - Supported modes are `off`, `truncate`, `summarize`, and `status`.
  - Aliases remain supported: `on`, `trim`, and `summary`.
  - Invalid extra args or mode print `[red]Usage: /tool-compress [off|truncate|summarize|status][/red]`.
  - Gateway `status` reads mode, enabled, and summary model config paths without patching.
  - Gateway mode changes patch `agent_token_saving.tool_result_compression_mode` and `agent_token_saving.tool_result_compression_enabled`.
  - Gateway `summarize` also reads `agent_token_saving.tool_result_compression_summary_model` for output.
  - Standalone mode changes mutate the nested `agent_token_saving` config object in place.
  - Missing standalone `agent_token_saving` prints `[yellow]Tool result compression config is unavailable.[/yellow]`.
  - Final status output remains `[cyan]tool result compression:[/cyan] <MODE>` with ` [dim]model=<model>[/dim]` only for summarize with a model.
- Files explicitly out of scope:
  - Gateway RPC config implementation.
  - Agent token saving runtime behavior.
  - Non-chat `config` CLI workflows.
  - Standalone `/model` and `/cost` extraction.
  - Tool result compression engine behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_tool_compress_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_tool_compression_workflows.py` does not exist, `chat_cmd.py` still imports no tool-compression workflow, and `_handle_tool_compress_command` plus tool-compression config path strings still live in `chat_cmd.py`.
- Minimal implementation:
  - Create `chat_tool_compression_workflows.py` with `handle_tool_compress_command`.
  - Move the existing `_handle_tool_compress_command` body into the new module with behavior unchanged.
  - Import `handle_tool_compress_command` in `chat_cmd.py`.
  - Update standalone and gateway `/tool-compress` dispatch to call `handle_tool_compress_command`.
  - Update standalone focused tests to import and patch the new workflow module directly where needed.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_tool_compress_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_can_switch_to_summarize tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_status_reads_config tests/test_cli/test_chat_cmd.py::test_standalone_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_tool_compress_workflow_emits_status_and_usage_messages -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_tool_compression_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_tool_compression_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-tool-compress-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-tool-compress-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-tool-compress-workflows-boundary`.
- [x] Write `test_chat_tool_compress_slashes_use_workflow_boundary`.
- [x] Add focused workflow output coverage for usage and status messages.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns tool-compression config details.
- [x] Implement `chat_tool_compression_workflows.py`.
- [x] Update `chat_cmd.py` standalone and gateway dispatch to delegate `/tool-compress`.
- [x] Update tests to target the new workflow module where direct helper access is needed.
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
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-tool-compress-workflows-boundary` passed on branch `codex/refactor-cli-chat-tool-compress-workflows-boundary` at `bb705ed`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_tool_compress_slashes_use_workflow_boundary -q` failed as expected because `chat_tool_compression_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_tool_compress_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_can_switch_to_summarize tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_status_reads_config tests/test_cli/test_chat_cmd.py::test_standalone_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_tool_compress_workflow_emits_status_and_usage_messages -q` passed: 6 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_tool_compression_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 148 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2312 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
- Low. The slice moves the existing `/tool-compress` logic without changing config paths, aliases, mutation payloads, or resolved mode/model output. It intentionally does not fix the existing Rich markup behavior that hides the bracketed mode list in plain captured output.
- Next recommended slice:
- Continue reducing `chat_cmd.py` by extracting the standalone `/model` and `/cost` slash workflows, or move the gateway `/save` transcript export dispatch into a smaller workflow boundary if prioritizing gateway-only surfaces.
