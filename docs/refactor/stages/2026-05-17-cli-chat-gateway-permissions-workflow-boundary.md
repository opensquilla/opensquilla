# CLI Chat Gateway Permissions Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/permissions` and `/elevated` workflow handling out of `chat_cmd.py` while preserving permission-mode state changes, approval-cache revocation, queue reset behavior, status output, and exact-prefix slash matching.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the slash dispatcher. Add a gateway permissions workflow module that owns slash workflow orchestration, chat-state synchronization, and the permissions-mode interpreter. Keep `_forget_server_approvals` in `chat_cmd.py` for compatibility with `/forget` and inject it into the new workflow so cache-clearing behavior remains centralized.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, gateway approval RPC helper, approval queue/intent-cache helpers.

---

## Stage

- Name: cli-chat-gateway-permissions-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-permissions-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-permissions-workflow-boundary`
- Owner: Codex main thread. A read-only probe agent `/root/gateway_permissions_boundary_probe` was dispatched to inspect current `/permissions` and `/elevated` behavior, but returned only AGENTS scope acknowledgement and no actionable code/test analysis; the main thread proceeds from direct current-code audit and records the fallback per root `AGENTS.md`.

## Goal

Move gateway `/permissions` and `/elevated` behind a dedicated workflow boundary without changing mode values, approval cache revocation, queue mode reset behavior, status/usage text, or exact-prefix slash command matching.

## Current-state audit

- Current HEAD: `5fa1454`.
- Worktree status: clean before stage-plan creation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-file-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_handle_elevated_command`
  - `_forget_server_approvals`
  - `_slash_parts_any`
  - `ChatSessionState.elevated`
  - gateway `/permissions`
  - gateway `/elevated`
- Tests inspected:
  - `test_gateway_elevated_unknown_prefix_is_not_handled`
  - existing gateway workflow boundary tests for `/image`, `/path`, and `/file`
  - approval prompt tests in `tests/test_cli/test_chat_cmd_approval.py`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch ordering.
  - Behavior-specific gateway slash command bodies move to dedicated `chat_gateway_*_workflows.py` modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.

## Boundary decision

- Responsibilities moving out:
  - Gateway `/permissions` and `/elevated` slash workflow orchestration.
  - Synchronizing `ChatSessionState.elevated` from the mutable elevated mode state.
  - Interpreting `status`, `off`, `on`, `bypass`, and `full`.
  - Rendering unknown mode usage text.
  - Calling injected approval-cache revocation on mode changes.
  - Resetting gateway approval queue mode to `prompt` when permissions are turned off.
- Responsibilities staying in place:
  - `_handle_gateway_slash_command` slash command dispatch ordering.
  - `_forget_server_approvals` helper, because `/forget` still uses it.
  - `/forget` and `/approvals` workflows.
  - Gateway message streaming and attachment workflows.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_permissions_workflows.py` owns gateway permissions slash orchestration and permission-mode command interpretation.
- Public behavior that must not change:
  - `/permissions` and `/permissions status` print the current mode without mutating or clearing approvals.
  - Unknown modes print `Unknown permissions mode:` and `Usage: /permissions on | off | bypass | full | status`.
  - `/permissions on`, `/permissions bypass`, and `/permissions full` update elevated mode and clear cached approvals.
  - `/permissions off` sets mode to sandboxed, clears cached approvals, and resets gateway queue mode to `prompt`.
  - `/elevated` remains an alias with the same exact-prefix matching behavior.
  - `/elevatedx` remains unhandled.
- Files explicitly out of scope:
  - `/forget` and `/approvals` implementation.
  - `_forget_server_approvals` server/local clearing implementation.
  - Approval prompt rendering in `_maybe_handle_approval`.
  - Gateway server approval RPC handlers.
  - Standalone chat behavior outside the shared permissions interpreter compatibility wrapper.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_permissions_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_permissions_workflows.py` does not exist and `_handle_gateway_slash_command` still calls `_handle_elevated_command` and owns `state.elevated` synchronization.
- Minimal implementation:
  - Create `chat_gateway_permissions_workflows.py` with `handle_gateway_permissions_command` and `handle_permissions_command`.
  - Import the gateway workflow in `chat_cmd.py`.
  - Replace the gateway `/permissions`/`/elevated` inline block with the workflow call.
  - Keep `_handle_elevated_command` as a compatibility wrapper that delegates to the new shared interpreter.
  - Add focused direct workflow coverage for status, unknown modes, mode changes, off queue reset, state synchronization, and exact-prefix behavior.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_permissions_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_permissions_workflow_delegates_and_syncs_chat_state tests/test_cli/test_chat_cmd.py::test_permissions_workflow_status_prints_current_without_revoking tests/test_cli/test_chat_cmd.py::test_permissions_workflow_unknown_mode_prints_usage_without_mutating tests/test_cli/test_chat_cmd.py::test_permissions_workflow_on_sets_mode_and_revokes_cache tests/test_cli/test_chat_cmd.py::test_permissions_workflow_off_resets_gateway_queue_and_revokes_cache tests/test_cli/test_chat_cmd.py::test_gateway_permissions_command_updates_chat_state tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_permissions_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_permissions_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-permissions-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-permissions-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-permissions-workflow-boundary`.
- [x] Write `test_chat_gateway_permissions_slash_uses_workflow_boundary`.
- [x] Add focused permissions workflow behavior coverage.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_permissions_command` and `handle_permissions_command`.
- [x] Update `chat_cmd.py` gateway dispatch and compatibility wrapper.
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

- Child commit: `52ef086`
- Integration merge: `b1e6ed6`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-permissions-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-permissions-workflow-boundary` at `5fa1454`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_permissions_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_permissions_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_permissions_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_permissions_workflow_delegates_and_syncs_chat_state tests/test_cli/test_chat_cmd.py::test_permissions_workflow_status_prints_current_without_revoking tests/test_cli/test_chat_cmd.py::test_permissions_workflow_unknown_mode_prints_usage_without_mutating tests/test_cli/test_chat_cmd.py::test_permissions_workflow_on_sets_mode_and_revokes_cache tests/test_cli/test_chat_cmd.py::test_permissions_workflow_off_resets_gateway_queue_and_revokes_cache tests/test_cli/test_chat_cmd.py::test_gateway_permissions_command_updates_chat_state tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q` passed: 8 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_permissions_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q` passed: 194 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2356 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `5fa1454`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-permissions-workflow-boundary` produced merge commit `b1e6ed6`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2358 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice moves permissions-mode interpretation into a workflow module while keeping `_forget_server_approvals` in place for `/forget` and preserving the compatibility wrapper.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting gateway `/forget` handling into a focused workflow boundary, preserving targeted and full approval-cache clearing behavior.
