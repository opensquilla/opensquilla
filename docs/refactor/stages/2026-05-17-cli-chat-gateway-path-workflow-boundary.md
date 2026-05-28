# CLI Chat Gateway Path Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/path` workflow out of `chat_cmd.py` while preserving local-gateway safety, local-path prompt behavior, no-upload semantics, elevated-state forwarding, transcript writes, and usage accumulation.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the slash dispatcher. Add a gateway path workflow module that owns `/path` usage validation, local-gateway enforcement, path prompt conversion, gateway stream invocation, transcript append, and usage accumulation. Keep the shared path prompt helper and standalone `/path` workflow in place for compatibility and to avoid mixing gateway and standalone transport concerns in this slice.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, gateway stream wrapper, CLI path attachment helpers.

---

## Stage

- Name: cli-chat-gateway-path-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-path-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-path-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was verified with a read-only probe for this slice; the probe returned only AGENTS scope acknowledgement, so the main thread is completing current-code audit, implementation, and full gate verification.

## Goal

Move gateway `/path` behind a dedicated workflow boundary without changing local-gateway rejection behavior, prompt/no-upload behavior, elevated-state forwarding, transcript writes, usage accumulation, or standalone `/path`.

## Current-state audit

- Current HEAD: `34920f6`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-image-workflow-boundary.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-path-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_path_command.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_path_prompt_and_attachments`
  - `_gateway_client_is_local`
  - `_stream_response_gateway`
  - gateway `/path`
  - gateway `/image`
  - standalone `/path`
- Tests inspected:
  - `test_gateway_path_command_sends_prompt_without_attachments_or_upload`
  - `test_gateway_path_command_remote_rejects_before_send`
  - `test_path_command_parses_quoted_path_with_prompt`
  - `test_path_command_default_prompt_mentions_no_upload`
  - `test_chat_gateway_image_slash_uses_workflow_boundary`
  - `test_chat_standalone_path_slash_uses_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order.
  - Behavior-specific gateway slash command bodies move to dedicated workflow modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.
- Subagent evidence:
  - Probe agent `/root/spawn_probe_gateway_path` was dispatched with no write ownership and verified `spawn_agent` availability.
  - The probe returned only AGENTS scope acknowledgement, so implementation proceeds from direct current-code audit.

## Boundary decision

- Responsibilities moving out:
  - Gateway `/path` usage validation.
  - Rejecting `/path` when the gateway client is not local.
  - Calling path prompt conversion and rendering conversion errors.
  - Calling the injected gateway stream function with prompt, elevated state, and no-upload attachments.
  - Appending user/assistant transcript entries and accumulating usage.
- Responsibilities staying in place:
  - `_handle_gateway_slash_command` slash command dispatch ordering.
  - `_gateway_client_is_local` compatibility helper.
  - `_path_prompt_and_attachments` compatibility helper.
  - `_stream_response_gateway` streaming implementation.
  - Standalone `/path` workflow.
  - Gateway `/image` and `/file`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_path_workflows.py` owns gateway local path slash workflow orchestration.
- Public behavior that must not change:
  - `/path <path> [prompt]` builds the same local-path prompt and does not upload file contents.
  - Remote gateway clients are rejected before prompt conversion or streaming.
  - Missing path prints `Usage: /path <path> [prompt]`.
  - Invalid path prompt conversion renders the same error panel text.
  - Gateway stream receives the same `client`, `session_key`, prompt, elevated state, and attachments.
  - Transcript and usage are updated from the gateway stream result.
- Files explicitly out of scope:
  - Standalone `/path`.
  - `_path_prompt_and_attachments` implementation.
  - `_gateway_client_is_local` implementation.
  - `_stream_response_gateway` streaming internals.
  - Gateway `/image` and `/file`.
  - Provider, gateway server, and session runtime internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_path_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_path_workflows.py` does not exist and `_handle_gateway_slash_command` still owns gateway `/path` implementation details.
- Minimal implementation:
  - Create `chat_gateway_path_workflows.py` with `handle_gateway_path_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/path` inline block with the handler call.
  - Add focused direct workflow coverage for successful gateway path streaming, missing usage, remote rejection, and path conversion errors.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_path_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_streams_prompt_without_upload_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_remote_rejects_before_prompt tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_path_command_sends_prompt_without_attachments_or_upload tests/test_cli/test_chat_cmd.py::test_gateway_path_command_remote_rejects_before_send -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_path_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-path-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_path_command.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-path-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-path-workflow-boundary`.
- [x] Write `test_chat_gateway_path_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for success, missing usage, remote rejection, and prompt conversion errors.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_path_command`.
- [x] Update `chat_cmd.py` gateway dispatch to delegate `/path`.
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

- Child commit: `29f5fbe`
- Integration merge: `6741b1c`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-path-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-path-workflow-boundary` at `34920f6`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_path_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_path_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_path_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_streams_prompt_without_upload_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_remote_rejects_before_prompt tests/test_cli/test_chat_cmd.py::test_gateway_path_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_path_command_sends_prompt_without_attachments_or_upload tests/test_cli/test_chat_cmd.py::test_gateway_path_command_remote_rejects_before_send -q` passed: 7 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_path_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_cli_product_completeness.py -q` passed: 202 passed.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2343 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `34920f6`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-path-workflow-boundary` produced merge commit `6741b1c`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2345 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts gateway `/path` orchestration; standalone `/path`, gateway `/image`, gateway `/file`, and the shared local-path prompt helper remain in place.
- Next recommended slice:
  - Continue reducing `_handle_gateway_slash_command` by extracting gateway `/file` into a focused workflow boundary while preserving upload bridge behavior and attachment payloads.
