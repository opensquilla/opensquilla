# CLI Chat Gateway Remaining Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the remaining gateway slash route-name execution branches out of `chat_cmd.py` while preserving `/path`, `/file`, permissions, forget, and approvals behavior.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the matcher and `_handle_gateway_slash_command` as the top-level dispatcher. Add `chat_gateway_io_route_workflows.py` for `/path` and `/file`, and `chat_gateway_control_route_workflows.py` for `permissions`, `forget`, and `approvals`. Existing workflow modules continue to own command behavior; the new modules only route by `route_name` and pass through dependencies.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, local path/file attachments, approval and permissions workflows.

---

## Stage

- Name: cli-chat-gateway-remaining-route-executor-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-remaining-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-remaining-route-executor-boundary`
- Owner: Codex main thread. Three read-only `spawn_agent` probes were launched for path/file, privacy/control routes, and dispatcher-wide batching; all stayed running past the wait windows and were closed, so this slice continues from main-thread audit evidence.

## Goal

Extract the remaining direct gateway slash route branches into focused executors without changing route matching, prompt/attachment behavior, upload behavior, remote path safety checks, approval-cache behavior, permissions state, transcript updates, usage accounting, or diagnostic text.

## Current-state audit

- Current HEAD: `090c15c`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `src/opensquilla/cli/chat_gateway_file_workflows.py`
  - `src/opensquilla/cli/chat_gateway_permissions_workflows.py`
  - `src/opensquilla/cli/chat_gateway_forget_workflows.py`
  - `src/opensquilla/cli/chat_gateway_approvals_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_gateway_path_command`
  - `handle_gateway_file_command`
  - `handle_gateway_permissions_command`
  - `handle_gateway_forget_command`
  - `handle_gateway_approvals_command`
  - `_stream_response_gateway`
  - `_path_prompt_and_attachments`
  - `_async_file_prompt_and_attachments`
  - `_gateway_client_is_local`
  - `_forget_server_approvals`
- Tests inspected:
  - `test_chat_gateway_path_slash_uses_workflow_boundary`
  - `test_chat_gateway_file_slash_uses_workflow_boundary`
  - `test_chat_gateway_permissions_slash_uses_workflow_boundary`
  - `test_chat_gateway_forget_slash_uses_workflow_boundary`
  - `test_chat_gateway_approvals_slash_uses_workflow_boundary`
  - existing path/file/permissions/forget/approvals behavior workflow tests.
- Existing boundary pattern this stage follows:
  - `chat_gateway_*_route_workflows.py` modules map route names to existing behavior workflows.
  - `_handle_gateway_slash_command` passes local dependencies into route executors and returns when a route family handles the command.

## Boundary decision

- Responsibilities moving out:
  - Mapping `path` and `file` route names to their behavior workflows.
  - Mapping `permissions`, `forget`, and `approvals` route names to their behavior workflows.
- Responsibilities staying in place:
  - Route matching and ordering.
  - Existing command behavior in path/file/permissions/forget/approvals workflow modules.
  - Local dependency providers in `chat_cmd.py`: stream response, attachment builders, local gateway check, remote path message, and approval cache forgetter.
  - Compatibility wrappers `_handle_approvals_command`, `_handle_forget_command`, and `_handle_elevated_command`.
- New module/file responsibility:
  - `chat_gateway_io_route_workflows.py` owns `GATEWAY_IO_ROUTE_NAMES` and `handle_gateway_io_route_command`.
  - `chat_gateway_control_route_workflows.py` owns `GATEWAY_CONTROL_ROUTE_NAMES` and `handle_gateway_control_route_command`.
- Public behavior that must not change:
  - `/path` continues to require local gateway access and use local path attachments.
  - `/file` continues to upload through the gateway client before streaming.
  - `/permissions` and `/elevated` continue to mutate elevated state and revoke cached approvals.
  - `/forget` continues to clear all or targeted cached approvals.
  - `/approvals` continues to report/reset queue/cache diagnostics.
- Files explicitly out of scope:
  - Changing attachment parsing, upload payloads, or diagnostic text.
  - Changing permissions modes or approval-cache semantics.
  - Changing route order or aliases.
  - Changing standalone chat wrappers.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_io_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_control_routes_use_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_io_route_workflows.py` and `chat_gateway_control_route_workflows.py` do not exist, and `_handle_gateway_slash_command` still directly calls the behavior workflows.
- Minimal implementation:
  - Create the two route executor modules.
  - Import both executors in `chat_cmd.py`.
  - Replace the five remaining direct route branches with two executor calls.
  - Update boundary tests and add delegation tests for known and unknown route names.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_io_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_io_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_control_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_control_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_io_route_workflows.py src/opensquilla/cli/chat_gateway_control_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_io_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_control_route_workflows.py`
  - `docs/refactor/stages/2026-05-18-cli-chat-gateway-remaining-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-cli-chat-gateway-remaining-route-executor-boundary.md`

## Steps

- [x] Inspect current integration git state, AGENTS.md, dispatcher branches, and workflow shapes.
- [x] Launch parallel read-only agents; record timeout fallback.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-remaining-route-executor-boundary`.
- [x] Write failing executor boundary tests.
- [x] Run the focused tests and confirm expected failures.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
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

- Child commit: `b5fa46e` (`Move remaining gateway chat routes behind executors`)
- Integration merge: `8372bbf` (`Merge CLI chat gateway remaining route executor boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-remaining-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-remaining-route-executor-boundary` at `090c15c`.
  - Parallel probes: `gateway_path_file_route_probe`, `gateway_privacy_routes_probe`, and `gateway_dispatcher_batch_plan_probe` were launched and then closed after exceeding wait windows without returning results.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_io_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_control_routes_use_executor_boundary -q` failed as expected because `chat_gateway_io_route_workflows.py` and `chat_gateway_control_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_io_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_io_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_control_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_control_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `5 passed in 0.73s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_io_route_workflows.py src/opensquilla/cli/chat_gateway_control_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `224 passed in 1.93s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 480 source files; whitespace passed; pytest passed with `2388 passed, 8 skipped, 2 warnings in 54.88s`; gateway smoke start/status/stop passed on `127.0.0.1:51104`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `090c15c`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-remaining-route-executor-boundary` produced merge commit `8372bbf`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 480 source files; whitespace passed; pytest passed with `2390 passed, 6 skipped, 2 warnings in 36.49s`; gateway smoke start/status/stop passed on `127.0.0.1:51761`.
- Residual risk:
  - Low. This slice moves remaining gateway slash route-name dispatch into thin executors while preserving existing path/file/control behavior workflows and compatibility wrappers.
- Next recommended slice:
  - Shift from CLI chat gateway route dispatch to a different architecture lane with parallel agents, such as session RPC payload boundaries or provider runtime boundaries, because `_handle_gateway_slash_command` now only chains route executors after route matching.
