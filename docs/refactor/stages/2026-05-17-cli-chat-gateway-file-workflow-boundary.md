# CLI Chat Gateway File Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/file` workflow out of `chat_cmd.py` while preserving upload bridge behavior, attachment payloads, elevated-state forwarding, transcript writes, and usage accumulation.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the slash dispatcher. Add a gateway file workflow module that owns `/file` usage validation, upload bridge construction, async file prompt/attachment conversion, gateway stream invocation, transcript append, and usage accumulation. Keep the shared file prompt helper in `chat_cmd.py` for compatibility with existing direct helper tests and avoid changing attachment semantics in this slice.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, gateway stream wrapper, CLI file attachment helpers.

---

## Stage

- Name: cli-chat-gateway-file-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-file-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-file-workflow-boundary`
- Owner: Codex main thread. A read-only probe agent `/root/gateway_file_boundary_probe` was dispatched to inspect current gateway `/file` behavior, but returned only AGENTS scope acknowledgement and no actionable code/test analysis; the main thread proceeds from direct current-code audit and records the fallback per root `AGENTS.md`.

## Goal

Move gateway `/file` behind a dedicated workflow boundary without changing upload bridge calls, inline/staged attachment payloads, elevated-state forwarding, transcript writes, usage accumulation, or direct `_file_prompt_and_attachments` helper compatibility.

## Current-state audit

- Current HEAD: `3cc8d88`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_image_workflows.py`
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `src/opensquilla/cli/attachments.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_async_file_prompt_and_attachments`
  - `_file_prompt_and_attachments`
  - `_stream_response_gateway`
  - `GatewayClient.upload_file`
  - gateway `/file`
  - gateway `/image`
  - gateway `/path`
- Tests inspected:
  - `_file_prompt_and_attachments` helper tests in `tests/test_cli/test_chat_file_command.py`
  - gateway path/image workflow boundary tests in `tests/test_cli/test_chat_cmd.py`
  - existing gateway slash handler tests around `_handle_gateway_slash_command`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order.
  - Behavior-specific gateway slash command bodies move to dedicated `chat_gateway_*_workflows.py` modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.

## Boundary decision

- Responsibilities moving out:
  - Gateway `/file` usage validation.
  - Constructing the async upload bridge to `client.upload_file`.
  - Calling async file prompt/attachment conversion and rendering conversion/upload errors.
  - Calling the injected gateway stream function with prompt, elevated state, and attachments.
  - Appending user/assistant transcript entries and accumulating usage.
- Responsibilities staying in place:
  - `_handle_gateway_slash_command` slash command dispatch ordering.
  - `_file_prompt_and_attachments` compatibility helper for direct helper tests.
  - `_async_file_prompt_and_attachments` compatibility helper.
  - `_stream_response_gateway` streaming implementation.
  - Gateway `/image` and `/path` workflows.
  - Standalone chat workflows.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_file_workflows.py` owns gateway file slash workflow orchestration and upload bridge adaptation.
- Public behavior that must not change:
  - `/file <path> [prompt]` prints `Usage: /file <path> [prompt]` when no path is supplied.
  - Upload bridge calls `client.upload_file(path, mime, name)` for staged file payloads.
  - Inline attachments, staged `file_uuid` attachments, MIME/name fields, and prompt defaults remain produced by the existing attachment helper.
  - Attachment conversion and upload failures render the same error panel text.
  - Gateway stream receives the same `client`, `session_key`, prompt, elevated state, and attachments.
  - Transcript and usage are updated from the gateway stream result.
- Files explicitly out of scope:
  - `_file_prompt_and_attachments` and `_async_file_prompt_and_attachments` helper implementations.
  - Gateway `/image` and `/path`.
  - Standalone chat workflows.
  - Gateway server upload endpoint and provider/session internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_file_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_file_workflows.py` does not exist and `_handle_gateway_slash_command` still owns gateway `/file` implementation details.
- Minimal implementation:
  - Create `chat_gateway_file_workflows.py` with `handle_gateway_file_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/file` inline block with the handler call.
  - Add focused direct workflow coverage for successful streaming with attachments, usage text, upload bridge forwarding, and prompt/upload errors.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_file_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_forwards_upload_bridge tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_file_command_uploads_and_sends_attachment -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_file_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_file_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-file-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-file-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-file-workflow-boundary`.
- [x] Write `test_chat_gateway_file_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for success, usage, upload bridge forwarding, and prompt/upload errors.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_file_command`.
- [x] Update `chat_cmd.py` gateway dispatch to delegate `/file`.
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

- Child commit: `5fae136`
- Integration merge: `199cc78`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-file-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-file-workflow-boundary` at `3cc8d88`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_file_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_file_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_file_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_forwards_upload_bridge tests/test_cli/test_chat_cmd.py::test_gateway_file_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_file_command_uploads_and_sends_attachment -q` passed: 6 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_file_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q` passed: 194 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2349 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `3cc8d88`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-file-workflow-boundary` produced merge commit `199cc78`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2351 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts gateway `/file` orchestration; upload payload construction remains in the existing attachment helper and gateway server/provider internals are untouched.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting gateway `/permissions` and `/elevated` handling into a focused workflow boundary, preserving approval-mode and intent-cache behavior.
