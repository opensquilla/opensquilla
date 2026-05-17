# CLI Chat Gateway Forget Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/forget` workflow out of `chat_cmd.py` while preserving full and targeted approval-cache clearing behavior.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Add a gateway forget workflow module that owns `/forget` command parsing and success rendering. Keep `_forget_server_approvals` in `chat_cmd.py` for this slice because gateway `/permissions` and the standalone compatibility wrapper still share that cache-clearing bridge.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway approval RPC client.

---

## Stage

- Name: cli-chat-gateway-forget-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-forget-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-forget-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was verified with a probe in this turn. A read-only gateway `/forget` probe was dispatched, but did not return within the working timeout before implementation; the main thread continued sequentially and recorded the fallback.

## Goal

Move gateway `/forget` behind a dedicated workflow boundary without changing successful all-cache clearing text, targeted clearing text, failure no-success behavior, exact `/forget` prefix matching, or the server-side approval-cache clearing bridge.

## Current-state audit

- Current HEAD: `cae920d`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-permissions-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/gateway_client.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_forget_server_approvals`
  - `_handle_forget_command`
  - `GatewayClient.forget_approvals`
  - gateway `/permissions` workflow boundary pattern
- Tests inspected:
  - `test_gateway_permissions_workflow_delegates_and_syncs_chat_state`
  - `test_permissions_workflow_on_sets_mode_and_revokes_cache`
  - `test_permissions_workflow_off_resets_gateway_queue_and_revokes_cache`
  - `test_gateway_permissions_command_updates_chat_state`
  - `test_chat_gateway_permissions_slash_uses_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps gateway slash dispatch order and exact command matching.
  - Behavior-specific gateway slash command bodies move to dedicated `chat_gateway_*_workflows.py` modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.

## Boundary decision

- Responsibilities moving out:
  - Parsing `/forget` versus `/forget <target>`.
  - Invoking the injected approval-cache clearing bridge.
  - Rendering successful all-cache clearing text.
  - Rendering successful targeted clearing text.
  - Suppressing success text when clearing fails.
- Responsibilities staying in place:
  - Gateway slash dispatch ordering and exact `/forget` prefix matching.
  - `_forget_server_approvals`, including gateway RPC fallback error messaging and standalone local-cache clearing behavior.
  - `_handle_forget_command` compatibility wrapper for existing direct callers.
  - `/approvals` diagnostics/reset workflow.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_forget_workflows.py` owns gateway `/forget` command interpretation and success rendering.
- Public behavior that must not change:
  - `/forget` clears all cached approvals and prints `All cached approvals cleared.` followed by the future destructive operations note.
  - `/forget <target>` clears the target and prints `Cached approval for <target> cleared (if one existed).`
  - Failed server clearing prints only the bridge's failure guidance and no success text.
  - `/forgetful` and other non-exact prefixes remain unknown.
  - Gateway mode keeps clearing server-side approvals through `exec.approval.forget`.
- Files explicitly out of scope:
  - `/approvals` diagnostics/reset behavior.
  - Gateway approval RPC server implementation.
  - Gateway permissions/elevated workflow behavior.
  - Intent-cache implementation details.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_forget_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_forget_workflows.py` does not exist and `_handle_gateway_slash_command` still calls `_handle_forget_command` directly.
- Minimal implementation:
  - Create `chat_gateway_forget_workflows.py` with `handle_gateway_forget_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/forget` inline branch with the handler call.
  - Keep `_handle_forget_command` as a compatibility wrapper delegating to the workflow.
  - Add focused workflow coverage for all-cache success, targeted success, failure suppression, dispatcher delegation, and unknown prefix preservation.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_forget_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_clears_all_and_prints_success tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_clears_target_and_prints_success tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_suppresses_success_when_clear_fails tests/test_cli/test_chat_cmd.py::test_gateway_forget_command_uses_forget_helper tests/test_cli/test_chat_cmd.py::test_gateway_forget_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_forget_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_forget_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-forget-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-forget-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-forget-workflow-boundary`.
- [x] Write `test_chat_gateway_forget_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for all-cache success, target success, failure suppression, dispatcher delegation, and unknown prefix behavior.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_forget_command`.
- [x] Update `chat_cmd.py` gateway dispatch and compatibility wrapper to delegate `/forget`.
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

- Child commit: `79f7c0b`
- Integration merge: `ee44e30`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-forget-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-forget-workflow-boundary` at `cae920d`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_forget_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_forget_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_forget_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_clears_all_and_prints_success tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_clears_target_and_prints_success tests/test_cli/test_chat_cmd.py::test_gateway_forget_workflow_suppresses_success_when_clear_fails tests/test_cli/test_chat_cmd.py::test_gateway_forget_command_uses_forget_helper tests/test_cli/test_chat_cmd.py::test_gateway_forget_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q` passed: 7 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_forget_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q` passed: 200 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2362 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `cae920d`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-forget-workflow-boundary` produced merge commit `ee44e30`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2364 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts gateway `/forget` command parsing and success rendering; server-side approval cache clearing, RPC behavior, and `/approvals` diagnostics remain in place.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting gateway `/approvals` diagnostics/reset handling into a focused workflow boundary, preserving local and gateway mode approval snapshot/reset text.
