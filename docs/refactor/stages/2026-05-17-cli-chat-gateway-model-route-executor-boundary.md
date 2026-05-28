# CLI Chat Gateway Model Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway model route execution for `/models` and `/model` out of `chat_cmd.py` while preserving model list, model update, and route matching behavior.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the route matcher and keep `_handle_gateway_slash_command` as the top-level dispatcher. Add `chat_gateway_model_route_workflows.py` as a route-family executor that delegates to the existing model list and model update workflow modules, following the exact-route and session-route executor pattern.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, gateway model workflow modules.

---

## Stage

- Name: cli-chat-gateway-model-route-executor-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-model-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-model-route-executor-boundary`
- Owner: Codex main thread. `spawn_agent` availability was checked and failed with `collab spawn failed: agent thread limit reached`; this slice continues sequentially with the fallback recorded per root `AGENTS.md`.

## Goal

Extract gateway model route execution into a focused boundary without changing `/models`, `/model`, model listing presenter behavior, session model patching, route matching, output text, or RPC calls.

## Current-state audit

- Current HEAD: `b266a4f`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_models_workflows.py`
  - `src/opensquilla/cli/chat_model_usage_workflows.py`
  - `src/opensquilla/cli/chat_gateway_exact_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_session_route_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_gateway_models_command`
  - `handle_model_command`
  - gateway model routes: `/models`, `/model`
- Tests inspected:
  - `test_gateway_slash_model_updates_session_model`
  - `test_gateway_slash_models_does_not_hit_model_prefix`
  - `test_chat_gateway_readonly_lists_use_focused_workflow_boundaries`
  - `test_chat_model_usage_slashes_use_workflow_boundary`
  - `test_gateway_slash_routes_preserve_order_and_matching_contract`
  - `test_gateway_slash_dispatch_uses_route_boundary`
- Existing boundary pattern this stage follows:
  - `chat_gateway_exact_route_workflows.py` and `chat_gateway_session_route_workflows.py` group small route families behind focused executors.
  - Existing concrete workflow modules continue to own behavior.
  - `_handle_gateway_slash_command` delegates route-family execution before handling route families with local media/permission wiring.

## Boundary decision

- Responsibilities moving out:
  - Mapping `models` and `model` route names to existing workflow handlers.
  - Grouping model list/update route execution in one gateway model route executor.
- Responsibilities staying in place:
  - Slash route matching and ordering in `chat_gateway_slash_routes.py`.
  - Exact and session route-family execution in their existing executors.
  - Tool compression, transcript export, media/path/file, permissions, forget, and approvals wiring in `_handle_gateway_slash_command`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_model_route_workflows.py` owns `GATEWAY_MODEL_ROUTE_NAMES`, `GatewayModelRouteClient`, and `handle_gateway_model_route_command`.
- Public behavior that must not change:
  - `/models` lists models using `emit_chat_models_table`.
  - `/models extra` preserves the current usage message.
  - `/model` prints the current/default model.
  - `/model <provider/model>` patches the current gateway session and updates local state.
  - `/models` remains matched before `/model`, and unknown prefixes like `/modelsx` remain unhandled.
- Files explicitly out of scope:
  - Changing route matching or ordering.
  - Changing model workflow behavior, presenter formatting, or RPC payloads.
  - Moving tool compression, transcript export, media/path/file, permissions, forget, or approvals route families.
  - Standalone chat behavior, Web UI, provider runtime, and gateway RPC internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_model_routes_use_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_model_route_workflows.py` does not exist and `_handle_gateway_slash_command` still directly calls model route handlers.
- Minimal implementation:
  - Create `chat_gateway_model_route_workflows.py` with `handle_gateway_model_route_command`.
  - Import that executor in `chat_cmd.py`.
  - Replace direct `/models` and `/model` route branches with one executor call.
  - Update boundary tests so chat imports the route-family executor and the executor imports the underlying workflow handlers.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_model_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_model_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_model_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_model_route_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-model-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-model-route-executor-boundary.md`

## Steps

- [x] Confirm `spawn_agent` availability and record fallback.
- [x] Inspect current integration git state, AGENTS.md, and dispatcher/model workflow shape.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-model-route-executor-boundary`.
- [x] Write the failing model route executor boundary test.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible change.
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

- Child commit: `14106ce` (`Move gateway chat model routes behind executor boundary`)
- Integration merge: `5fb34db` (`Merge CLI chat gateway model route executor boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-model-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-model-route-executor-boundary` at `b266a4f`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_model_routes_use_executor_boundary -q` failed as expected because `chat_gateway_model_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_model_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_model_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_model_updates_session_model tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `5 passed in 0.54s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_model_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `222 passed in 2.40s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 476 source files; whitespace passed; pytest passed with `2386 passed, 8 skipped, 2 warnings in 47.55s`; gateway smoke start/status/stop passed on `127.0.0.1:65398`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `b266a4f`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-model-route-executor-boundary` produced merge commit `5fb34db`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 476 source files; whitespace passed; pytest passed with `2388 passed, 6 skipped, 2 warnings in 26.34s`; gateway smoke start/status/stop passed on `127.0.0.1:49165`.
- Residual risk:
  - Low. This slice only moves model route-family dispatch into a thin executor; existing model workflow modules still own behavior, and route matching remains unchanged.
- Next recommended slice:
  - Continue reducing `_handle_gateway_slash_command` by extracting tool/transcript utility routes (`/tool-compress`, `/save`) into a focused executor boundary, before tackling media/path/file routes that need more local dependency wiring.
