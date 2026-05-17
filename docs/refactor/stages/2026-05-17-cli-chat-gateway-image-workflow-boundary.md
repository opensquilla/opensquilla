# CLI Chat Gateway Image Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/image` workflow out of `chat_cmd.py` while preserving image attachment prompt behavior, elevated-state forwarding, transcript writes, usage accumulation, and standalone `/image` behavior.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the slash dispatcher. Add a gateway image workflow module that owns `/image` usage validation, prompt/attachment conversion, gateway stream invocation, transcript append, and usage accumulation. Keep the shared image prompt helper and standalone TurnRunner image streaming path in `chat_cmd.py` for compatibility and to avoid mixing gateway and standalone transport concerns in this slice.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, gateway stream wrapper, CLI image attachment helpers.

---

## Stage

- Name: cli-chat-gateway-image-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-image-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-image-workflow-boundary`
- Owner: Codex main thread. A read-only explorer was dispatched for gateway `/image` behavior and boundary shape, but returned only AGENTS scope information and no actionable code review; the main thread completed current-code audit, implementation, and full gate verification, recording the fallback per root `AGENTS.md`.

## Goal

Move gateway `/image` behind a dedicated workflow boundary without changing gateway image prompt/attachment behavior, elevated-state forwarding, transcript writes, usage accumulation, or standalone `/image`.

## Current-state audit

- Current HEAD: `9b350c7`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/attachments.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_image_prompt_and_attachments`
  - `_stream_response_gateway`
  - `ChatSessionState.transcript`
  - `ChatSessionState.usage`
  - gateway `/image`
  - standalone `/image`
- Tests inspected:
  - `test_chat_stateful_session_slashes_use_workflow_boundary`
  - `test_chat_session_maintenance_slashes_use_workflow_boundary`
  - `test_chat_model_usage_slashes_use_workflow_boundary`
  - `test_chat_standalone_image_slash_uses_workflow_boundary`
  - gateway slash behavior tests around `_handle_gateway_slash_command`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order.
  - Behavior-specific gateway slash command bodies move to dedicated workflow modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.
- Subagent evidence:
  - Read-only explorer `/root/gateway_image_slice_explorer` was dispatched with no write ownership.
  - The explorer returned only AGENTS scope information, so implementation proceeded from direct current-code audit.

## Boundary decision

- Responsibilities moving out:
  - Gateway `/image` usage validation.
  - Calling image prompt/attachment conversion and rendering conversion errors.
  - Calling the injected gateway stream function with prompt, elevated state, and attachments.
  - Appending user/assistant transcript entries and accumulating usage.
- Responsibilities staying in place:
  - `_handle_gateway_slash_command` slash command dispatch ordering.
  - `_image_prompt_and_attachments` compatibility helper and its "Sending image" status text.
  - `_stream_response_gateway` streaming implementation.
  - Standalone `/image` workflow and TurnRunner image streaming path.
  - Gateway `/path` and `/file`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_image_workflows.py` owns gateway image slash workflow orchestration.
- Public behavior that must not change:
  - `/image <path> [prompt]` builds the same prompt and attachment payloads.
  - Missing path prints `Usage: /image <path> [prompt]`.
  - Invalid image prompt/attachment conversion renders the same error panel text.
  - Gateway stream receives the same `client`, `session_key`, prompt, elevated state, and attachments.
  - Transcript and usage are updated from the gateway stream result.
- Files explicitly out of scope:
  - Standalone `/image`.
  - `_image_prompt_and_attachments` implementation.
  - `_stream_response_gateway` streaming internals.
  - Gateway `/path` and `/file`.
  - Provider, gateway server, and session runtime internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_image_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_image_workflows.py` does not exist and `_handle_gateway_slash_command` still owns gateway `/image` implementation details.
- Minimal implementation:
  - Create `chat_gateway_image_workflows.py` with `handle_gateway_image_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/image` inline block with the handler call.
  - Add focused direct workflow coverage for successful gateway image streaming, missing usage, and prompt conversion errors.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_image_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_renders_prompt_errors -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_image_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_image_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-image-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-image-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-image-workflow-boundary`.
- [x] Write `test_chat_gateway_image_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for success, missing usage, and prompt conversion errors.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_image_command`.
- [x] Update `chat_cmd.py` gateway dispatch to delegate `/image`.
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
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-image-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-image-workflow-boundary` at `9b350c7`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_image_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_image_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_image_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_renders_prompt_errors -q` passed: 4 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_image_workflows.py tests/test_cli/test_chat_cmd.py` passed after `ruff check --fix` sorted the import block.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_cli_product_completeness.py -q` passed: 183 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2338 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts gateway `/image` orchestration; standalone `/image`, gateway `/path`, gateway `/file`, and image attachment construction remain in place.
- Next recommended slice:
  - Continue reducing `_handle_gateway_slash_command` by extracting gateway `/path` or `/file` into focused workflow boundaries.
