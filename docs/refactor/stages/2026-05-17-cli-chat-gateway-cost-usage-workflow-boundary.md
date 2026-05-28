# CLI Chat Gateway Cost Usage Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split gateway chat `/cost` and `/usage` handling out of the model workflow module into a focused gateway usage workflow boundary.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Keep `chat_model_usage_workflows.py` focused on gateway `/model`, and add `chat_gateway_usage_workflows.py` for `/cost` local turn usage rendering and `/usage` aggregate gateway usage RPC rendering. This is a narrower boundary split from the existing combined model/usage workflow module, preserving all CLI text and RPC behavior.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, gateway usage RPC client.

---

## Stage

- Name: cli-chat-gateway-cost-usage-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-cost-usage-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-cost-usage-workflow-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only `/cost`/`/usage` probe and later for a minimal availability probe, but the current agent thread limit was reached both times; the fallback is recorded here per root `AGENTS.md`.

## Goal

Move gateway `/cost` and `/usage` into a dedicated workflow module without changing local accumulated usage rendering, aggregate gateway usage RPC formatting, `/model` behavior, or exact command matching.

## Current-state audit

- Current HEAD: `1604ca3`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-status-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_model_usage_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_model_command`
  - `handle_cost_command`
  - `handle_usage_command`
  - `ModelUsageClient`
  - gateway `/cost`
  - gateway `/usage`
- Tests inspected:
  - `test_gateway_slash_model_updates_session_model`
  - `test_gateway_slash_cost_and_usage_emit_usage_views`
  - `test_chat_model_usage_slashes_use_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order and exact command matching.
  - Focused workflow modules own behavior-specific rendering and RPC calls.
  - Boundary tests assert `_handle_gateway_slash_command` delegates and does not call gateway RPCs or render usage directly.

## Boundary decision

- Responsibilities moving out of `chat_model_usage_workflows.py`:
  - Rendering local accumulated usage for `/cost`.
  - Calling `client.usage_status()` for `/usage`.
  - Rendering aggregate gateway usage totals.
- Responsibilities staying in `chat_model_usage_workflows.py`:
  - `/model` display and session model update RPC.
  - `patch_session` protocol dependency.
- Responsibilities staying in `chat_cmd.py`:
  - Gateway slash dispatch ordering and exact `/cost`/`/usage` matching.
  - State synchronization around other commands.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_usage_workflows.py` owns gateway `/cost` and `/usage` behavior.
- Public behavior that must not change:
  - `/cost` prints `state.usage.render()` with the same accumulated usage text.
  - `/usage` prints `aggregate usage: <tokens> tok · $<cost>` with comma-separated token count and six decimal places.
  - `/model` behavior remains unchanged.
  - `/costx` and `/usagex` remain unknown.
- Files explicitly out of scope:
  - Standalone model/cost workflow.
  - Gateway usage RPC server implementation.
  - Usage accounting internals.
  - `/model` behavior beyond narrowing its module.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_usage_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_gateway_usage_workflows.py` does not exist and `chat_cmd.py` still imports `/cost` and `/usage` handlers from `chat_model_usage_workflows.py`.
- Minimal implementation:
  - Create `chat_gateway_usage_workflows.py` with `handle_gateway_cost_command` and `handle_gateway_usage_command`.
  - Move cost/usage client protocol responsibility to the new module.
  - Keep `chat_model_usage_workflows.py` focused on `/model`.
  - Update `chat_cmd.py` imports and `/cost`/`/usage` dispatch.
  - Update focused tests to patch the new workflow module console and assert unknown prefixes remain unknown.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views tests/test_cli/test_chat_cmd.py::test_gateway_usage_unknown_prefixes_are_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_model_usage_workflows.py src/opensquilla/cli/chat_gateway_usage_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_usage_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-cost-usage-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_model_usage_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-cost-usage-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-cost-usage-workflow-boundary`.
- [x] Write `test_chat_gateway_usage_slashes_use_workflow_boundary`.
- [x] Update focused behavior coverage for `/cost`, `/usage`, `/model`, and unknown prefixes.
- [x] Run the focused gateway usage boundary test and confirm the expected failure.
- [x] Implement `chat_gateway_usage_workflows.py`.
- [x] Narrow `chat_model_usage_workflows.py` to `/model`.
- [x] Update `chat_cmd.py` gateway dispatch imports and calls.
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

- Child commit: `03f51c3` (`Move gateway chat cost usage workflow behind boundary`)
- Integration merge: `317fd5a` (`Merge CLI chat gateway cost usage workflow boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-cost-usage-workflow-boundary` passed on branch `codex/refactor-cli-chat-gateway-cost-usage-workflow-boundary` at `1604ca3`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_usage_slashes_use_workflow_boundary -q` failed as expected before implementation because `chat_gateway_usage_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_chat_model_usage_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views tests/test_cli/test_chat_cmd.py::test_gateway_usage_unknown_prefixes_are_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model -q` passed, `5 passed in 0.50s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_model_usage_workflows.py src/opensquilla/cli/chat_gateway_usage_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `212 passed in 1.64s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 469 source files; whitespace passed; pytest passed with `2376 passed, 8 skipped, 2 warnings in 51.52s`; gateway smoke start/status/stop passed on `127.0.0.1:60583`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `1604ca3`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-cost-usage-workflow-boundary` produced merge commit `317fd5a`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 469 source files; whitespace passed; pytest passed with `2378 passed, 6 skipped, 2 warnings in 26.40s`; gateway smoke start/status/stop passed on `127.0.0.1:60730`.
- Residual risk: Low. The slice only moves gateway `/cost` and `/usage` responsibilities behind a focused workflow module, with behavior and boundary tests covering exact command matching and output/RPC delegation. No independent subagent review was possible because `spawn_agent` remained unavailable due to the current thread limit.
- Next recommended slice: Continue reducing `_handle_gateway_slash_command` by splitting the generic `chat_slash_workflows.py` responsibilities for gateway `/models` and `/sessions` into focused gateway workflow modules, preserving exact prefix matching and list rendering behavior.
