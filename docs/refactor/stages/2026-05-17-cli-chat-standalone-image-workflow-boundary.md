# CLI Chat Standalone Image Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/image` dispatch workflow out of `chat_cmd.py` while preserving image attachment streaming, transcript writes, usage accumulation, and gateway `/image` behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the slash dispatcher and TurnRunner coordinator. Add a standalone image workflow module that owns `/image` usage validation, calls the existing TurnRunner image command function through dependency injection, appends transcript entries, and accumulates usage. Leave gateway `/image` and low-level image attachment construction in `chat_cmd.py`/`attachments.py` for this slice so remote/gateway upload behavior is untouched.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, TurnRunner image wrapper, CLI image attachment helpers.

---

## Stage

- Name: cli-chat-standalone-image-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-image-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-image-workflow-boundary`
- Owner: Codex main thread. A read-only explorer was dispatched for standalone `/image` behavior and boundary shape, but did not return within the working timeout; the main thread completed current-code audit, implementation, and full gate verification, recording the fallback per root `AGENTS.md`.

## Goal

Move standalone `/image` behind a dedicated workflow boundary without changing image attachment streaming, usage text, transcript writes, TurnRunner invocation shape, or gateway `/image`.

## Current-state audit

- Current HEAD: `a38a7d4`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/attachments.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_image_prompt_from_command`
  - `_image_prompt_and_attachments`
  - `_handle_image_command_turnrunner`
  - standalone `/image`
  - gateway `/image`
- Tests inspected:
  - `test_chat_standalone_path_slash_uses_workflow_boundary`
  - `test_standalone_path_workflow_streams_prompt_without_attachments`
  - `test_standalone_path_workflow_prints_usage_without_path`
  - existing gateway `/image` branch coverage via `_handle_gateway_slash_command` patterns
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order.
  - Standalone behavior-specific slash command bodies move to dedicated `chat_standalone_*_workflows.py` modules.
  - Boundary tests assert `_standalone_repl` delegates rather than owning workflow literals and helper calls.
- Subagent evidence:
  - Read-only explorer `/root/image_slice_explorer` was dispatched with no write ownership.
  - The explorer exceeded the working timeout and was closed before returning actionable results.

## Boundary decision

- Responsibilities moving out:
  - Standalone `/image` usage validation.
  - Calling the standalone TurnRunner image command dependency.
  - Appending user/assistant transcript entries after the image command result.
  - Accumulating TurnRunner usage from the image command result.
- Responsibilities staying in place:
  - `_standalone_repl` slash command dispatch ordering.
  - The low-level `_handle_image_command_turnrunner` streaming implementation.
  - `_image_prompt_from_command` and `_image_prompt_and_attachments` compatibility helpers.
  - Gateway `/image` prompt/attachment/send behavior.
  - `/file`, `/path`, `/save`, and unknown command handling.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_image_workflows.py` owns standalone image slash workflow orchestration.
- Public behavior that must not change:
  - `/image <path> [prompt]` sends image attachments through the existing TurnRunner image command path.
  - Missing path prints `Usage: /image <path> [prompt]`.
  - Image command errors are rendered by the existing image command runner.
  - Transcript user entry uses `_image_prompt_from_command(command)`.
  - Transcript assistant entry and usage are updated from the TurnRunner result.
- Files explicitly out of scope:
  - Gateway `/image`.
  - `_image_prompt_and_attachments` implementation.
  - `_handle_image_command_turnrunner` streaming internals.
  - `/file` upload workflows.
  - Provider, gateway, and session runtime internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_image_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_image_workflows.py` does not exist and `_standalone_repl` still owns standalone `/image` implementation details.
- Minimal implementation:
  - Create `chat_standalone_image_workflows.py` with `handle_standalone_image_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the standalone `/image` inline block with the handler call.
  - Add focused direct workflow coverage for successful image command orchestration and missing usage.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_image_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_image_workflow_runs_image_command_and_updates_state tests/test_cli/test_chat_cmd.py::test_standalone_image_workflow_prints_usage_without_path -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_image_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_image_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-image-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-image-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-standalone-image-workflow-boundary`.
- [x] Write `test_chat_standalone_image_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for success and missing usage.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_standalone_image_command`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/image`.
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
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-standalone-image-workflow-boundary` passed on branch `codex/refactor-cli-chat-standalone-image-workflow-boundary` at `a38a7d4`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_image_slash_uses_workflow_boundary -q` failed as expected because `chat_standalone_image_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_image_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_image_workflow_runs_image_command_and_updates_state tests/test_cli/test_chat_cmd.py::test_standalone_image_workflow_prints_usage_without_path -q` passed: 3 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_image_workflows.py tests/test_cli/test_chat_cmd.py` passed after `ruff check --fix` sorted the import block.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q` passed: 179 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2334 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts standalone `/image` orchestration; gateway `/image` and image attachment construction remain in place.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/file` or gateway `/image`/`/file` workflow boundaries in separate slices.
