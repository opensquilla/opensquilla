# CLI Chat Gateway Status Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway chat `/status` and `/session` rendering out of `chat_cmd.py` while preserving session/model/permissions text.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Add a focused gateway status workflow module that owns rendering the current gateway chat session summary. Standalone `/status` remains in the existing standalone status workflow because it has a different output surface.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`.

---

## Stage

- Name: cli-chat-gateway-status-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-status-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-status-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only `/status` probe, but the current agent thread limit was reached; the fallback is recorded here per root `AGENTS.md`.

## Goal

Move gateway `/status` and `/session` rendering behind a dedicated workflow boundary without changing session key, model default, permissions default, or exact command matching.

## Current-state audit

- Current HEAD: `496c324`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-approvals-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_status_workflows.py`
  - `src/opensquilla/cli/chat_gateway_approvals_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `ChatSessionState`
  - `handle_standalone_status_command`
  - gateway `/status`
  - gateway `/session`
- Tests inspected:
  - `test_standalone_status_workflow_emits_session_model_and_models_notice`
  - `test_chat_standalone_status_slashes_use_workflow_boundary`
  - `test_chat_gateway_approvals_slash_uses_workflow_boundary`
  - gateway slash dispatcher tests near `test_gateway_slash_sessions_uses_presenter_boundary`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order and exact command matching.
  - Behavior-specific gateway slash command bodies move to dedicated `chat_gateway_*_workflows.py` modules.
  - Boundary tests assert `_handle_gateway_slash_command` delegates rather than owning workflow literals.

## Boundary decision

- Responsibilities moving out:
  - Rendering the gateway chat status/session summary.
  - Applying `default` when `state.model` is unset.
  - Applying `normal` when `state.elevated` is unset.
- Responsibilities staying in place:
  - Gateway slash dispatch ordering and exact `{"/status", "/session"}` matching.
  - Gateway REPL state/model synchronization after handled commands.
  - Standalone `/status` and `/session`.
  - `/sessions` list command.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_status_workflows.py` owns gateway status/session rendering.
- Public behavior that must not change:
  - `/status` and `/session` both render the same three-line summary.
  - Output labels remain `session`, `model`, and `permissions`.
  - Empty model displays `default`.
  - Empty elevated mode displays `normal`.
  - `/statusx` and other non-exact prefixes remain unknown.
- Files explicitly out of scope:
  - Standalone status/model catalog notice.
  - Gateway `/sessions`, `/resume`, and `/delete`.
  - Gateway lifecycle `opensquilla gateway status`.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_status_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_status_workflows.py` does not exist and `_handle_gateway_slash_command` still owns the status rendering literals.
- Minimal implementation:
  - Create `chat_gateway_status_workflows.py` with `handle_gateway_status_command`.
  - Import the handler in `chat_cmd.py`.
  - Replace the gateway `/status`/`/session` inline rendering block with the handler call.
  - Add focused workflow coverage for explicit model/permissions, default model/permissions, dispatcher delegation for `/session`, and unknown prefix preservation.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_status_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_status_workflow_renders_session_model_and_permissions tests/test_cli/test_chat_cmd.py::test_gateway_status_workflow_uses_defaults tests/test_cli/test_chat_cmd.py::test_gateway_session_command_uses_status_workflow tests/test_cli/test_chat_cmd.py::test_gateway_status_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_status_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_status_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-status-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-status-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-status-workflow-boundary`.
- [x] Write `test_chat_gateway_status_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for explicit status, default status, dispatcher delegation, and unknown prefix behavior.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `handle_gateway_status_command`.
- [x] Update `chat_cmd.py` gateway dispatch to delegate `/status` and `/session`.
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
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-status-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-status-workflow-boundary` at `496c324`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_status_slash_uses_workflow_boundary -q` failed as expected because `chat_gateway_status_workflows.py` did not exist.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_status_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_status_workflow_renders_session_model_and_permissions tests/test_cli/test_chat_cmd.py::test_gateway_status_workflow_uses_defaults tests/test_cli/test_chat_cmd.py::test_gateway_session_command_uses_status_workflow tests/test_cli/test_chat_cmd.py::test_gateway_status_unknown_prefix_is_not_handled -q` passed: 5 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_status_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 210 passed.
  - Child gate: `scripts/refactor_gate.sh` passed: ruff, mypy, whitespace, pytest 2374 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only extracts pure gateway status rendering; gateway session listing and lifecycle commands remain untouched.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting gateway `/cost` and `/usage` handling into focused workflow boundaries, preserving local usage rendering and gateway usage RPC behavior.
