# CLI Chat Standalone Path Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/path` workflow out of `chat_cmd.py` while preserving local-path prompt behavior and transcript/usage updates.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the slash dispatcher and TurnRunner coordinator. Add a standalone path workflow module that owns `/path` usage validation, path prompt conversion, no-attachment guard, TurnRunner call, transcript append, and usage accumulation. Gateway `/path` remains in `chat_cmd.py` for this slice because it has a distinct local-gateway safety check and RPC send path.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, TurnRunner stream wrapper, CLI path attachment helpers.

---

## Stage

- Name: cli-chat-standalone-path-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-path-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-path-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was verified with a probe. Read-only spec/code-quality reviewers were dispatched for this slice, but did not return within the working timeout; the main thread completed review and full gate verification, recording the fallback per root `AGENTS.md`.

## Goal

Move standalone `/path` behind a dedicated workflow boundary without changing prompt text, no-upload/no-attachment semantics, transcript writes, usage accumulation, or TurnRunner invocation shape.

## Current-state Audit

- Current HEAD: `fb4388e`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/attachments.py`
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_path_command.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_path_prompt_and_attachments`
  - `path_prompt_and_attachments`
  - `_stream_response_turnrunner`
  - standalone `/path`
  - gateway `/path`
- Tests inspected:
  - `test_standalone_path_command_runs_as_plain_message`
  - `test_gateway_path_command_sends_prompt_without_attachments_or_upload`
  - `test_gateway_path_command_remote_rejects_before_send`
  - `test_path_command_parses_quoted_path_with_prompt`
  - `test_path_command_default_prompt_mentions_no_upload`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order.
  - Standalone behavior-specific slash command bodies move to dedicated `chat_standalone_*_workflows.py` modules.
  - Boundary tests assert `_standalone_repl` delegates rather than owning workflow literals and helper calls.
- Subagent evidence:
  - Probe agent completed successfully, confirming `spawn_agent` availability.
  - Read-only spec and code-quality reviewers were dispatched, but timed out before returning actionable results. The agents were not given write ownership.

## Boundary Decision

- Responsibilities moving out:
  - Standalone `/path` usage validation.
  - Calling path prompt conversion and rendering parsing errors.
  - Enforcing that standalone `/path` does not create attachments.
  - Calling the injected TurnRunner stream function with the generated prompt.
  - Appending user/assistant transcript entries and accumulating usage.
- Responsibilities staying in place:
  - `_standalone_repl` slash command dispatch ordering.
  - Plain user message handling.
  - Gateway `/path` remote/local safety and RPC send behavior.
  - `/image`, `/file`, `/save`, and unknown command handling.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_path_workflows.py` owns standalone local path analysis slash workflow.
- Public behavior that must not change:
  - `/path <path> [prompt]` sends a plain prompt to TurnRunner and does not pass attachments.
  - Missing path prints `Usage: /path <path> [prompt]`.
  - Invalid path prompt conversion renders the same error panel text.
  - Any unexpected non-empty attachments from the path helper are rejected with `/path must not create attachments.`
  - Transcript and usage are updated from the TurnRunner result.
- Files explicitly out of scope:
  - Gateway `/path`.
  - `_path_prompt_and_attachments` implementation.
  - `/image` and `/file` workflows.
  - Provider, gateway, and session runtime internals.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_path_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_path_workflows.py` does not exist and `_standalone_repl` still owns standalone `/path` implementation details.
- Minimal implementation:
  - Create `chat_standalone_path_workflows.py` with `handle_standalone_path_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the standalone `/path` inline block with the handler call.
  - Add focused direct workflow coverage for successful prompt streaming, missing usage, and non-empty attachment guard.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_path_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_streams_prompt_without_attachments tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_rejects_unexpected_attachments tests/test_cli/test_chat_cmd.py::test_standalone_path_command_runs_as_plain_message -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_path_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_path_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-path-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_path_command.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-path-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-path-workflow-boundary`.
- [x] Write `test_chat_standalone_path_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for success, missing usage, and unexpected attachments.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_standalone_path_command`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/path`.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

## Child Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `08b4242`
- Integration merge: `4743024`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-path-workflow-boundary` passed on branch `codex/refactor-cli-chat-standalone-path-workflow-boundary` at `fb4388e`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_path_slash_uses_workflow_boundary -q` failed as expected because `chat_standalone_path_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_path_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_streams_prompt_without_attachments tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_standalone_path_workflow_rejects_unexpected_attachments tests/test_cli/test_chat_cmd.py::test_standalone_path_command_runs_as_plain_message -q` passed: 5 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_path_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_cli_product_completeness.py -q` passed: 190 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2331 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `fb4388e`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-path-workflow-boundary` produced merge commit `4743024`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2333 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts standalone `/path` workflow handling; gateway `/path` and the shared path prompt helper remain in place.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/image` or `/file` handling behind a focused workflow boundary, keeping gateway upload/path behavior separate.
