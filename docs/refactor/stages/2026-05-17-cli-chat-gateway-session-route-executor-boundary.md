# CLI Chat Gateway Session Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway session route execution for `/new`, `/sessions`, `/resume`, and `/delete` out of `chat_cmd.py` while preserving existing session behavior and route matching.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the pure matcher and keep `_handle_gateway_slash_command` as the top-level dispatcher. Add `chat_gateway_session_route_workflows.py` as a route-family executor that delegates to the existing session workflow modules, matching the exact route executor pattern introduced in the previous slice.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, gateway session workflow modules.

---

## Stage

- Name: cli-chat-gateway-session-route-executor-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-session-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-session-route-executor-boundary`
- Owner: Codex main thread. `spawn_agent` availability was checked and failed with `collab spawn failed: agent thread limit reached`; existing shutdown agents could not be reclaimed, so this slice continues sequentially with the fallback recorded per root `AGENTS.md`.

## Goal

Extract gateway session route execution into a focused boundary without changing `/new`, `/sessions`, `/resume`, `/delete`, route matching, RPC calls, state mutation, output text, or presenter behavior.

## Current-state audit

- Current HEAD: `0f68905`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_exact_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_sessions_workflows.py`
  - `src/opensquilla/cli/chat_session_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_gateway_exact_route_command`
  - `handle_new_session_command`
  - `handle_gateway_sessions_command`
  - `handle_resume_session_command`
  - `handle_delete_session_command`
  - gateway session routes: `/new`, `/sessions`, `/resume`, `/delete`
- Tests inspected:
  - `test_gateway_slash_new_passes_title_as_display_name`
  - `test_gateway_slash_sessions_uses_presenter_boundary`
  - `test_gateway_slash_delete_resolves_and_reports_errors`
  - `test_gateway_slash_unknown_prefix_is_not_handled`
  - `test_chat_stateful_session_slashes_use_workflow_boundary`
  - `test_gateway_slash_routes_preserve_order_and_matching_contract`
  - `test_gateway_slash_dispatch_uses_route_boundary`
- Existing boundary pattern this stage follows:
  - `chat_gateway_exact_route_workflows.py` groups a small route family behind one executor.
  - Existing workflow modules retain the concrete behavior.
  - `chat_cmd.py` delegates route-family execution before handling route families that still need local dependency wiring.

## Boundary decision

- Responsibilities moving out:
  - Mapping session route names `new`, `sessions`, `resume`, and `delete` to existing workflow handlers.
  - Grouping session lifecycle/listing route execution in one executor boundary.
- Responsibilities staying in place:
  - Slash route matching and ordering in `chat_gateway_slash_routes.py`.
  - Exact no-argument route execution in `chat_gateway_exact_route_workflows.py`.
  - Model, tool compression, transcript export, media/path/file, permissions, forget, and approvals wiring in `_handle_gateway_slash_command`.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_session_route_workflows.py` owns `GATEWAY_SESSION_ROUTE_NAMES`, `GatewaySessionRouteClient`, and `handle_gateway_session_route_command`.
- Public behavior that must not change:
  - `/new [title]` creates a session with the current model and title as display name, then resets local state.
  - `/sessions [limit]` lists sessions through the presenter boundary and preserves usage validation.
  - `/resume <id>` resolves the target and updates local state/model exactly as before.
  - `/delete <id>` resolves, deletes, and renders errors/success exactly as before.
  - Unknown prefixes such as `/newer` remain unhandled.
- Files explicitly out of scope:
  - Changing route matching or ordering.
  - Changing session workflow behavior or presenter formatting.
  - Moving model/media/permissions/forget/approvals route families.
  - Standalone chat behavior, gateway RPC payloads, Web UI, and provider/session internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_session_routes_use_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_session_route_workflows.py` does not exist and `_handle_gateway_slash_command` still directly calls session route handlers.
- Minimal implementation:
  - Create `chat_gateway_session_route_workflows.py` with `handle_gateway_session_route_command`.
  - Import that executor in `chat_cmd.py`.
  - Replace direct `/new`, `/sessions`, `/resume`, and `/delete` route branches with one executor call.
  - Update boundary tests so chat imports the route-family executor and the executor imports the underlying workflow handlers.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_session_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_session_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_new_passes_title_as_display_name tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_delete_resolves_and_reports_errors tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_session_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_session_route_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-session-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-session-route-executor-boundary.md`

## Steps

- [x] Confirm `spawn_agent` availability and record fallback.
- [x] Inspect current integration git state, AGENTS.md, and recent refactor records.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-session-route-executor-boundary`.
- [x] Write the failing session route executor boundary test.
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

- Child commit: `c3b309c` (`Move gateway chat session routes behind executor boundary`)
- Integration merge: `6476a83` (`Merge CLI chat gateway session route executor boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-session-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-session-route-executor-boundary` at `0f68905`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_session_routes_use_executor_boundary -q` failed as expected because `chat_gateway_session_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_session_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_session_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_new_passes_title_as_display_name tests/test_cli/test_chat_cmd.py::test_gateway_slash_sessions_uses_presenter_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_delete_resolves_and_reports_errors tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `6 passed in 0.49s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_session_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `220 passed in 2.39s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 475 source files; whitespace passed; pytest passed with `2384 passed, 8 skipped, 2 warnings in 52.40s`; gateway smoke start/status/stop passed on `127.0.0.1:64737`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `0f68905`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-session-route-executor-boundary` produced merge commit `6476a83`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 475 source files; whitespace passed; pytest passed with `2386 passed, 6 skipped, 2 warnings in 26.44s`; gateway smoke start/status/stop passed on `127.0.0.1:64882`.
- Residual risk:
  - Low. This slice only moves session route-family dispatch into a thin executor; existing session workflow modules still own behavior, and route matching remains unchanged.
- Next recommended slice:
  - Continue reducing `_handle_gateway_slash_command` by extracting model route execution (`/models`, `/model`) into a small executor boundary, or move the remaining side-effect-light routes (`/tool-compress`, `/save`) next.
