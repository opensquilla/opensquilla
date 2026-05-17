# CLI Chat Gateway Approvals Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/approvals` diagnostics/reset workflow out of `chat_cmd.py` while preserving local and gateway approval queue/cache output behavior.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Add a gateway approvals workflow module that owns `/approvals` status/reset argument parsing, local diagnostics compatibility, gateway snapshot rendering, gateway reset behavior, and failure text. Keep `_handle_approvals_command` as a compatibility wrapper so existing direct callers keep working.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway approval RPC client.

---

## Stage

- Name: cli-chat-gateway-approvals-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-approvals-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-approvals-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only `/approvals` probe, but the current agent thread limit was reached; the fallback is recorded here per root `AGENTS.md`.

## Goal

Move gateway `/approvals` behind a dedicated workflow boundary without changing local status/reset output, gateway snapshot rendering, gateway reset RPC calls, error guidance, or exact `/approvals` prefix matching.

## Current-state audit

- Current HEAD: `f65b219`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-forget-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/gateway_client.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_handle_approvals_command`
  - `_forget_server_approvals`
  - `GatewayClient.approvals_snapshot`
  - `GatewayClient.set_approval_mode`
  - `GatewayClient.forget_approvals`
  - gateway `/forget` workflow boundary pattern
- Tests inspected:
  - `test_gateway_forget_workflow_clears_all_and_prints_success`
  - `test_gateway_forget_command_uses_forget_helper`
  - `test_chat_gateway_forget_slash_uses_workflow_boundary`
  - approval-related CLI tests found by `rg approvals`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps gateway slash dispatch order and exact command matching.
  - Behavior-specific gateway slash command bodies move to dedicated `chat_gateway_*_workflows.py` modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals and helper calls.

## Boundary decision

- Responsibilities moving out:
  - Parsing `/approvals` versus `/approvals reset`.
  - Local approval queue/cache diagnostic rendering for compatibility wrapper calls.
  - Local approval reset behavior for compatibility wrapper calls.
  - Gateway approval mode reset and cache clearing RPC sequence.
  - Gateway approval snapshot rendering.
  - Gateway reset/query failure text.
- Responsibilities staying in place:
  - Gateway slash dispatch ordering and exact `/approvals` prefix matching.
  - `_handle_approvals_command` compatibility wrapper.
  - `_forget_server_approvals`, because `/forget` and permissions mode still share it.
  - Gateway approval RPC client methods and server handlers.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_approvals_workflows.py` owns approval diagnostics/reset command interpretation and rendering.
- Public behavior that must not change:
  - `/approvals` prints `mode: <mode>`, cached intent count, and either entries or `(none)`.
  - `/approvals reset` sets gateway approval mode to `prompt`, clears server cache, and prints `Approval mode reset to prompt; server cache cleared.`
  - Local compatibility calls with `client=None` keep printing `Approval mode reset to prompt; cache cleared.` on reset.
  - Gateway query failures print `Failed to query approvals:` and `Older gateway? Restart it.`
  - Gateway reset failures print `Failed to reset approvals:` and `Restart the gateway if this is an older build.`
  - `/approvalsx` and other non-exact prefixes remain unknown.
- Files explicitly out of scope:
  - `/forget` approval-cache clearing workflow.
  - Gateway approval RPC server implementation.
  - Approval queue and intent-cache internals.
  - Web UI approvals view.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_approvals_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_approvals_workflows.py` does not exist and `_handle_gateway_slash_command` still calls `_handle_approvals_command` directly.
- Minimal implementation:
  - Create `chat_gateway_approvals_workflows.py` with `handle_gateway_approvals_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/approvals` inline branch with the handler call.
  - Keep `_handle_approvals_command` as a compatibility wrapper delegating to the workflow.
  - Extend `_FakeGatewayClient` with approval snapshot/reset/cache-clear test hooks.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_approvals_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_renders_snapshot_entries tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_reset_sets_prompt_and_clears_cache tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_query_failure_prints_restart_hint tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_reset_failure_prints_restart_hint tests/test_cli/test_chat_cmd.py::test_gateway_approvals_command_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_approvals_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_approvals_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_approvals_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-approvals-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_cmd_approval.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-approvals-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-approvals-workflow-boundary`.
- [x] Write `test_chat_gateway_approvals_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for gateway status, gateway reset, query/reset failures, dispatcher delegation, and unknown prefix behavior.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_approvals_command`.
- [x] Update `chat_cmd.py` gateway dispatch and compatibility wrapper to delegate `/approvals`.
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

- Child commit: `d6e2832`
- Integration merge: `9df7057`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-approvals-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-approvals-workflow-boundary` at `f65b219`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_approvals_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_approvals_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_approvals_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_renders_snapshot_entries tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_reset_sets_prompt_and_clears_cache tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_query_failure_prints_restart_hint tests/test_cli/test_chat_cmd.py::test_gateway_approvals_workflow_reset_failure_prints_restart_hint tests/test_cli/test_chat_cmd.py::test_gateway_approvals_command_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_approvals_unknown_prefix_is_not_handled -q` passed: 7 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_approvals_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_chat_cmd_approval.py tests/test_cli/test_cli_product_completeness.py -q` passed: 207 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2369 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `f65b219`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-approvals-workflow-boundary` produced merge commit `9df7057`.
  - Integration gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2371 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts `/approvals` diagnostics and reset rendering/RPC orchestration; `/forget`, permissions mode, and gateway approval RPC internals remain in place.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting gateway `/status`/`/session` rendering into a focused workflow boundary, preserving session/model/permissions output text.
