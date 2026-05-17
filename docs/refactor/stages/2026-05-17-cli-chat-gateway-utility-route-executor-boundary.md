# CLI Chat Gateway Utility Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway utility route execution for `/tool-compress` and `/save` out of `chat_cmd.py` while preserving tool compression configuration and transcript export behavior.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the matcher and `_handle_gateway_slash_command` as the top-level dispatcher. Add `chat_gateway_utility_route_workflows.py` as a route-family executor that delegates to the existing tool compression workflow and gateway transcript export helper, following the exact/session/model route executor pattern.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, gateway config client, transcript export helpers.

---

## Stage

- Name: cli-chat-gateway-utility-route-executor-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-utility-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-utility-route-executor-boundary`
- Owner: Codex main thread. `spawn_agent` availability was checked and failed with `collab spawn failed: agent thread limit reached`; this slice continues sequentially with the fallback recorded per root `AGENTS.md`.

## Goal

Extract gateway utility route execution into a focused boundary without changing `/tool-compress`, `/save`, config RPC calls, transcript history export, fallback transcript behavior, output text, or route matching.

## Current-state audit

- Current HEAD: `d5b72ff`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_tool_compression_workflows.py`
  - `src/opensquilla/cli/chat_transcript_exports.py`
  - `src/opensquilla/cli/chat_gateway_exact_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_session_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_model_route_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `handle_tool_compress_command`
  - `save_gateway_transcript_command`
  - `save_transcript_command`
  - gateway utility routes: `/tool-compress`, `/save`
- Tests inspected:
  - `test_gateway_slash_tool_compress_toggles_config`
  - `test_gateway_slash_tool_compress_can_switch_to_summarize`
  - `test_gateway_slash_tool_compress_status_reads_config`
  - `test_gateway_slash_save_exports_persisted_history`
  - `test_chat_save_transcript_uses_export_boundary`
  - `test_chat_tool_compress_slashes_use_workflow_boundary`
  - `test_gateway_slash_routes_preserve_order_and_matching_contract`
  - `test_gateway_slash_dispatch_uses_route_boundary`
- Existing boundary pattern this stage follows:
  - `chat_gateway_exact_route_workflows.py`, `chat_gateway_session_route_workflows.py`, and `chat_gateway_model_route_workflows.py` group small route families behind focused executors.
  - Existing concrete workflow/helper modules continue to own behavior.
  - `_handle_gateway_slash_command` delegates route-family execution before handling route families with local media/permission wiring.

## Boundary decision

- Responsibilities moving out:
  - Mapping `tool_compress` and `save` route names to existing workflow/helper calls.
  - Grouping small gateway utility routes in one executor boundary.
- Responsibilities staying in place:
  - Slash route matching and ordering in `chat_gateway_slash_routes.py`.
  - Exact, session, and model route-family execution in their existing executors.
  - Media/path/file, permissions, forget, and approvals wiring in `_handle_gateway_slash_command`.
  - Standalone `/save` handling remains directly in standalone dispatch.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_utility_route_workflows.py` owns `GATEWAY_UTILITY_ROUTE_NAMES`, `GatewayUtilityRouteClient`, and `handle_gateway_utility_route_command`.
- Public behavior that must not change:
  - `/tool-compress` continues to read and patch gateway config through `handle_tool_compress_command`.
  - `/save [path]` continues to use persisted gateway history and falls back to local transcript when history is empty.
  - Standalone `/save` continues to use in-memory transcript export.
  - Unknown prefixes remain unhandled.
- Files explicitly out of scope:
  - Changing route matching or ordering.
  - Changing tool compression validation/config behavior.
  - Changing transcript export formatting or file target selection.
  - Moving media/path/file, permissions, forget, or approvals route families.
  - Standalone chat behavior other than keeping existing `/save` import intact.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_utility_routes_use_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_utility_route_workflows.py` does not exist and `_handle_gateway_slash_command` still directly calls utility route handlers.
- Minimal implementation:
  - Create `chat_gateway_utility_route_workflows.py` with `handle_gateway_utility_route_command`.
  - Import that executor in `chat_cmd.py`.
  - Replace direct `/tool-compress` and `/save` route branches with one executor call.
  - Update boundary tests so chat imports the route-family executor and the executor imports the underlying workflow/helper.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_utility_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_status_reads_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_save_exports_persisted_history tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_utility_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_utility_route_workflows.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-utility-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-utility-route-executor-boundary.md`

## Steps

- [x] Confirm `spawn_agent` availability and record fallback.
- [x] Inspect current integration git state, AGENTS.md, and utility workflow/helper shape.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-utility-route-executor-boundary`.
- [x] Write the failing utility route executor boundary test.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible change.
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

- Child commit: pending
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-utility-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-utility-route-executor-boundary` at `d5b72ff`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_utility_routes_use_executor_boundary -q` failed as expected because `chat_gateway_utility_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_utility_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_tool_compress_status_reads_config tests/test_cli/test_chat_cmd.py::test_gateway_slash_save_exports_persisted_history tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `6 passed in 0.62s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_utility_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `224 passed in 2.41s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 477 source files; whitespace passed; pytest passed with `2388 passed, 8 skipped, 2 warnings in 46.77s`; gateway smoke start/status/stop passed on `127.0.0.1:49814`.
- Residual risk:
  - Low. This slice only moves utility route-family dispatch into a thin executor; existing tool compression and transcript export helpers still own behavior, and standalone `/save` remains unchanged.
- Next recommended slice:
  - Continue reducing `_handle_gateway_slash_command` by extracting media/path/file route execution in small steps, likely starting with `/image` because that workflow is already isolated but still needs local dependency injection from the dispatcher.
