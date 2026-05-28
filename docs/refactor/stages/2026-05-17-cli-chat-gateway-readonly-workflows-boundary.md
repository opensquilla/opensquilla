# CLI Chat Gateway Readonly Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split gateway chat `/sessions` and `/models` read-only list handling into focused gateway workflow modules.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway slash dispatcher. Move `/sessions` list RPC and session table emission into `chat_gateway_sessions_workflows.py`; move `/models` list RPC and model table emission into `chat_gateway_models_workflows.py`. Keep `chat_slash_workflows.py` as a compatibility facade so existing imports continue to resolve while new gateway dispatch uses focused modules.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway list RPC clients, chat presenter functions.

---

## Stage

- Name: cli-chat-gateway-readonly-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-readonly-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-readonly-workflows-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only `/models` and `/sessions` probe, but the current agent thread limit was reached; the fallback is recorded here per root `AGENTS.md`.

## Goal

Move gateway `/sessions` and `/models` read-only list workflows out of the generic `chat_slash_workflows.py` module without changing command matching, RPC calls, presenter output, usage errors, or import compatibility.

## Current-state audit

- Current HEAD: `f48870c`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-cost-usage-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_slash_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_sessions_command`
  - `handle_models_command`
  - `SessionListClient`
  - `ModelListClient`
  - gateway `/sessions`
  - gateway `/models`
- Tests inspected:
  - `test_chat_slash_readonly_lists_use_workflow_boundary`
  - `test_gateway_slash_sessions_uses_presenter_boundary`
  - `test_gateway_slash_models_does_not_hit_model_prefix`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps slash dispatch order and exact command matching.
  - Focused workflow modules own behavior-specific RPC calls and presenter delegation.
  - Boundary tests assert `_handle_gateway_slash_command` delegates and does not call gateway RPCs or presenter functions directly.

## Boundary decision

- Responsibilities moving out:
  - `/sessions` default limit parsing and `client.list_sessions(limit=...)` call.
  - `/sessions` invalid limit usage message.
  - `/sessions` table presenter delegation.
  - `/models` extra-argument usage message.
  - `/models` `client.list_models()` call.
  - `/models` table presenter delegation.
- Responsibilities staying in place:
  - Gateway slash dispatch ordering and exact prefix matching in `chat_cmd.py`.
  - Rich table rendering details in `chat_presenters.py`.
  - Backward-compatible import names in `chat_slash_workflows.py`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_sessions_workflows.py` owns gateway `/sessions` behavior.
  - `src/opensquilla/cli/chat_gateway_models_workflows.py` owns gateway `/models` behavior.
  - `src/opensquilla/cli/chat_slash_workflows.py` becomes a compatibility facade only.
- Public behavior that must not change:
  - `/sessions` defaults to limit `10`.
  - `/sessions <n>` passes that integer limit to `list_sessions`.
  - `/sessions nope` prints `[red]Usage: /sessions [limit][/red]` and does not call RPC.
  - `/models` calls `list_models` once and emits the same model table rows.
  - `/models extra` prints `[red]Usage: /models[/red]` and does not call RPC.
  - `/models` must not be handled by the `/model` branch, and `/sessionsx` or `/modelsx` remain unknown.
  - Existing imports from `opensquilla.cli.chat_slash_workflows` keep working.
- Files explicitly out of scope:
  - Session resume/delete/new workflows.
  - Model selection `/model` workflow.
  - Presenter rendering details.
  - Gateway RPC server implementation.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_readonly_lists_use_focused_workflow_boundaries -q`
- Expected red failure:
  - `chat_gateway_sessions_workflows.py` and `chat_gateway_models_workflows.py` do not exist and `chat_cmd.py` still imports handlers from `chat_slash_workflows.py`.
- Minimal implementation:
  - Create `chat_gateway_sessions_workflows.py` with `handle_gateway_sessions_command`.
  - Create `chat_gateway_models_workflows.py` with `handle_gateway_models_command`.
  - Update `chat_cmd.py` to import and call focused gateway handlers.
  - Narrow `chat_slash_workflows.py` to a compatibility facade re-exporting legacy names.
  - Update focused tests to patch the new workflow modules.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_readonly_lists_use_focused_workflow_boundaries tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_slash_workflows.py src/opensquilla/cli/chat_gateway_sessions_workflows.py src/opensquilla/cli/chat_gateway_models_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_sessions_workflows.py`
  - `src/opensquilla/cli/chat_gateway_models_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-readonly-workflows-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_slash_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-readonly-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-readonly-workflows-boundary`.
- [x] Write `test_chat_gateway_readonly_lists_use_focused_workflow_boundaries`.
- [x] Run the focused boundary test and confirm the expected failure.
- [x] Implement `chat_gateway_sessions_workflows.py`.
- [x] Implement `chat_gateway_models_workflows.py`.
- [x] Narrow `chat_slash_workflows.py` to a compatibility facade.
- [x] Update `chat_cmd.py` gateway dispatch imports and calls.
- [x] Update focused behavior tests for `/sessions` and `/models`.
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

- Child commit: `0f74606` (`Move gateway chat readonly workflows behind boundaries`)
- Integration merge: `2ddafe8` (`Merge CLI chat gateway readonly workflow boundaries`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-readonly-workflows-boundary` passed on branch `codex/refactor-cli-chat-gateway-readonly-workflows-boundary` at `f48870c`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_readonly_lists_use_focused_workflow_boundaries -q` failed as expected because `chat_gateway_sessions_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_gateway_readonly_lists_use_focused_workflow_boundaries tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `4 passed in 0.62s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_slash_workflows.py src/opensquilla/cli/chat_gateway_sessions_workflows.py src/opensquilla/cli/chat_gateway_models_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `212 passed in 2.33s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 471 source files; whitespace passed; pytest passed with `2376 passed, 8 skipped, 2 warnings in 50.99s`; gateway smoke start/status/stop passed on `127.0.0.1:61395`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `f48870c`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-readonly-workflows-boundary` produced merge commit `2ddafe8`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 471 source files; whitespace passed; pytest passed with `2378 passed, 6 skipped, 2 warnings in 26.39s`; gateway smoke start/status/stop passed on `127.0.0.1:61591`.
- Residual risk: Low. The slice only moves gateway `/sessions` and `/models` read-only list responsibilities behind focused workflow modules, while preserving the legacy `chat_slash_workflows.py` import facade and existing presenter/RPC behavior. No independent subagent review was possible because `spawn_agent` remained unavailable due to the current thread limit.
- Next recommended slice: Continue shrinking `_handle_gateway_slash_command` by extracting the gateway `/help` branch into a tiny focused workflow boundary, then reassess whether the remaining dispatcher can become a declarative routing table without changing exact command matching.
