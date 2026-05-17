# CLI Chat Gateway Exact Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway exact no-argument slash route execution out of `chat_cmd.py` while preserving existing route matching and user-visible behavior.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the pure route matcher and keep `_handle_gateway_slash_command` as the gateway dispatcher. Add an exact route executor boundary for the side-effect-free/no-argument route family so the dispatcher first offers `help`, `status`, `clear`, `compact`, `cost`, and `usage` to a focused workflow module, then continues to prefix route handlers.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, gateway chat workflow modules.

---

## Stage

- Name: cli-chat-gateway-exact-route-executor-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-exact-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-exact-route-executor-boundary`
- Owner: Codex main thread. `spawn_agent` availability was checked before continuing and failed with `collab spawn failed: agent thread limit reached`; this slice continues sequentially with the fallback recorded per root `AGENTS.md`.

## Goal

Extract gateway exact/no-argument route execution into a dedicated boundary without changing command names, route matching, RPC calls, state updates, or output text.

## Current-state audit

- Current HEAD: `cca2b44`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-path-workflow-boundary.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-slash-routing-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_slash_routes.py`
  - `src/opensquilla/cli/chat_gateway_help_workflows.py`
  - `src/opensquilla/cli/chat_gateway_status_workflows.py`
  - `src/opensquilla/cli/chat_gateway_usage_workflows.py`
  - `src/opensquilla/cli/chat_session_maintenance_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `match_gateway_slash_route`
  - gateway exact routes: `/help`, `/status`, `/session`, `/clear`, `/reset`, `/compact`, `/cost`, `/usage`
  - prefix routes that stay in dispatcher: `/new`, `/sessions`, `/resume`, `/delete`, `/models`, `/model`, `/tool-compress`, `/save`, `/image`, `/path`, `/file`, `/permissions`, `/forget`, `/approvals`
- Tests inspected:
  - `test_gateway_slash_help_renders_help_table`
  - `test_gateway_slash_clear_resets_session_state`
  - `test_gateway_slash_compact_calls_session_rpc`
  - `test_gateway_slash_cost_and_usage_emit_usage_views`
  - `test_chat_gateway_help_uses_workflow_boundary`
  - `test_chat_session_maintenance_slashes_use_workflow_boundary`
  - `test_chat_gateway_usage_slashes_use_workflow_boundary`
  - `test_chat_gateway_status_slash_uses_workflow_boundary`
  - `test_gateway_slash_dispatch_uses_route_boundary`
- Existing boundary pattern this stage follows:
  - Pure route matching is already isolated in `chat_gateway_slash_routes.py`.
  - Workflow modules own individual command behavior.
  - `chat_cmd.py` keeps dispatcher and dependency wiring until a later command-table slice.

## Boundary decision

- Responsibilities moving out:
  - Dispatching exact no-argument gateway route names to their existing workflow handlers.
  - Grouping `help`, `status`, `clear`, `compact`, `cost`, and `usage` as a small executable route family.
- Responsibilities staying in place:
  - Slash route matching and route order in `chat_gateway_slash_routes.py`.
  - Prefix route execution in `_handle_gateway_slash_command`.
  - Gateway upload/path/image/elevated/approval dependency wiring.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_exact_route_workflows.py` owns `GATEWAY_EXACT_ROUTE_NAMES`, `GatewayExactRouteClient`, and `handle_gateway_exact_route_command`.
- Public behavior that must not change:
  - `/help` renders the same table.
  - `/status` and `/session` render the same state summary.
  - `/clear` and `/reset` reset session state through the same RPC and clear local transcript/usage.
  - `/compact` calls the same compact RPC and renders the same result.
  - `/cost` renders local turn usage.
  - `/usage` renders aggregate gateway usage.
  - Unknown and prefix routes continue through the existing matcher and dispatcher behavior.
- Files explicitly out of scope:
  - Changing route matching or order.
  - Moving prefix route handlers into a command table.
  - Standalone slash command routing.
  - Gateway workflow behavior, RPC payloads, output text, and Web UI.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_exact_routes_use_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_exact_route_workflows.py` does not exist and `_handle_gateway_slash_command` still directly calls exact route handlers.
- Minimal implementation:
  - Create `chat_gateway_exact_route_workflows.py` with `handle_gateway_exact_route_command`.
  - Import that executor in `chat_cmd.py`.
  - Replace direct exact route branches with one executor call before prefix route branches.
  - Update boundary tests so exact route behavior is asserted through the executor module.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_exact_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_exact_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_help_renders_help_table tests/test_cli/test_chat_cmd.py::test_gateway_slash_clear_resets_session_state tests/test_cli/test_chat_cmd.py::test_gateway_slash_compact_calls_session_rpc tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_exact_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_exact_route_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-exact-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-exact-route-executor-boundary.md`

## Steps

- [x] Confirm `spawn_agent` availability and record fallback.
- [x] Inspect current integration and standalone path child git state without restarting that completed slice.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-exact-route-executor-boundary`.
- [x] Write the failing exact route executor boundary test.
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

- Child commit: `ac9c408` (`Move gateway chat exact routes behind executor boundary`)
- Integration merge: `0bc49e1` (`Merge CLI chat gateway exact route executor boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-exact-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-exact-route-executor-boundary` at `cca2b44`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_exact_routes_use_executor_boundary -q` failed as expected because `chat_gateway_exact_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_exact_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_exact_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_help_renders_help_table tests/test_cli/test_chat_cmd.py::test_gateway_slash_clear_resets_session_state tests/test_cli/test_chat_cmd.py::test_gateway_slash_compact_calls_session_rpc tests/test_cli/test_chat_cmd.py::test_gateway_slash_cost_and_usage_emit_usage_views tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `7 passed in 0.50s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_exact_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `218 passed in 1.80s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 474 source files; whitespace passed; pytest passed with `2382 passed, 8 skipped, 2 warnings in 54.81s`; gateway smoke start/status/stop passed on `127.0.0.1:63985`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `cca2b44`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-exact-route-executor-boundary` produced merge commit `0bc49e1`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 474 source files; whitespace passed; pytest passed with `2384 passed, 6 skipped, 2 warnings in 26.12s`; gateway smoke start/status/stop passed on `127.0.0.1:64137`.
- Residual risk:
  - Low. Exact route execution now delegates through a focused executor, while route matching and prefix command wiring remain unchanged.
- Next recommended slice:
  - Continue reducing the gateway dispatcher by moving one prefix route family into a focused executor or command table, starting with session lifecycle routes (`/new`, `/sessions`, `/resume`, `/delete`) because their behavior is already behind workflow modules.
