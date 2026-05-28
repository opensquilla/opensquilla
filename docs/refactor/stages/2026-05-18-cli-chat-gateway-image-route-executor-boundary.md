# CLI Chat Gateway Image Route Executor Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway `/image` route-name execution out of `chat_cmd.py` while preserving the existing gateway image attachment workflow.

**Architecture:** Keep `chat_gateway_slash_routes.py` as the matcher and `_handle_gateway_slash_command` as the top-level dispatcher. Add a thin `chat_gateway_image_route_workflows.py` executor that maps the `image` route name to the existing `chat_gateway_image_workflows.handle_gateway_image_command` behavior workflow. Continue injecting local prompt-building and stream dependencies from `chat_cmd.py` so user-facing behavior does not change.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, gateway slash routes, gateway image attachments, TurnResult usage accounting.

---

## Stage

- Name: cli-chat-gateway-image-route-executor-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-image-route-executor-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-image-route-executor-boundary`
- Owner: Codex main thread. `spawn_agent` availability was checked and succeeded for a read-only probe, but the probe timed out without a result and was closed; this slice continues sequentially with current repository evidence.

## Goal

Extract gateway `/image` route-name execution into a focused executor without changing image prompt parsing, attachment construction, gateway streaming, transcript updates, usage accounting, usage/error text, or route matching.

## Current-state audit

- Current HEAD: `6e729bd`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_slash_routes.py`
  - `src/opensquilla/cli/chat_gateway_image_workflows.py`
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `src/opensquilla/cli/chat_gateway_file_workflows.py`
  - `src/opensquilla/cli/chat_gateway_model_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_session_route_workflows.py`
  - `src/opensquilla/cli/chat_gateway_utility_route_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `match_gateway_slash_route`
  - `handle_gateway_image_command`
  - `_stream_response_gateway`
  - `_image_prompt_and_attachments`
  - gateway `/image` route matching.
- Tests inspected:
  - `test_gateway_image_workflow_streams_with_attachments_and_updates_state`
  - `test_gateway_image_workflow_prints_usage_without_path`
  - `test_gateway_image_workflow_renders_prompt_errors`
  - `test_chat_gateway_image_slash_uses_workflow_boundary`
  - `test_gateway_slash_routes_preserve_order_and_matching_contract`
  - `test_gateway_model_routes_use_executor_boundary`
  - `test_gateway_utility_routes_use_executor_boundary`
- Existing boundary pattern this stage follows:
  - `chat_gateway_model_route_workflows.py`, `chat_gateway_session_route_workflows.py`, and `chat_gateway_utility_route_workflows.py` group route-name execution behind focused executors.
  - Existing behavior workflow modules continue to own command behavior.
  - `_handle_gateway_slash_command` delegates route-family execution before handling remaining local dependency-heavy route families.

## Boundary decision

- Responsibilities moving out:
  - Mapping the gateway `image` route name to the existing image workflow call.
  - Keeping the route-name branch out of `_handle_gateway_slash_command`.
- Responsibilities staying in place:
  - Slash route matching and ordering in `chat_gateway_slash_routes.py`.
  - Prompt parsing, attachment construction, usage text, error rendering, streaming, transcript, and usage updates in `chat_gateway_image_workflows.py`.
  - Supplying `_stream_response_gateway`, `_image_prompt_and_attachments`, `client`, and `elevated_state` from `chat_cmd.py`.
  - `/path` and `/file` route-family execution remains in `chat_cmd.py` for later slices.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_image_route_workflows.py` owns `GATEWAY_IMAGE_ROUTE_NAMES` and `handle_gateway_image_route_command`.
- Public behavior that must not change:
  - `/image <path> [prompt]` continues to stream with image attachments through the gateway.
  - `/image` without a path continues to print `Usage: /image <path> [prompt]`.
  - prompt-building errors still render through `error_panel`.
  - transcript and usage accounting remain unchanged.
  - Route order and prefix matching remain unchanged.
- Files explicitly out of scope:
  - Changing image attachment parsing or MIME behavior.
  - Changing gateway streaming semantics.
  - Changing `/path`, `/file`, permissions, forget, or approvals dispatch.
  - Changing standalone `/image`.
  - Changing route matching or ordering.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_image_route_uses_executor_boundary -q`
- Expected red failure:
  - `chat_gateway_image_route_workflows.py` does not exist and `_handle_gateway_slash_command` still imports/calls `handle_gateway_image_command` directly.
- Minimal implementation:
  - Create `chat_gateway_image_route_workflows.py` with `handle_gateway_image_route_command`.
  - Import that executor in `chat_cmd.py`.
  - Replace the direct `if route_name == "image"` branch with one executor call.
  - Update boundary tests so `chat_cmd.py` imports the executor and the executor imports the existing image workflow.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_image_route_uses_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_image_route_executor_delegates_known_route tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_image_route_workflows.py src/opensquilla/cli/chat_gateway_image_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_image_route_workflows.py`
  - `docs/refactor/stages/2026-05-18-cli-chat-gateway-image-route-executor-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-cli-chat-gateway-image-route-executor-boundary.md`

## Steps

- [x] Confirm `spawn_agent` availability and record probe timeout fallback.
- [x] Inspect current integration git state, AGENTS.md, route matcher, image workflow, and existing executor patterns.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-image-route-executor-boundary`.
- [x] Write the failing image route executor boundary test.
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

- Child commit: `adcdd3d` (`Move gateway chat image route behind executor boundary`)
- Integration merge: `91bbc24` (`Merge CLI chat gateway image route executor boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-image-route-executor-boundary` passed on branch `codex/refactor-cli-chat-gateway-image-route-executor-boundary` at `6e729bd`.
  - Spawn probe: `spawn_agent` succeeded for `/root/gateway_image_route_probe`, but the read-only probe did not return within two wait windows and was closed; main thread continued from current source evidence.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_image_route_uses_executor_boundary -q` failed as expected because `chat_gateway_image_route_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_image_route_uses_executor_boundary tests/test_cli/test_chat_cmd.py::test_gateway_image_route_executor_delegates_known_route tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_streams_with_attachments_and_updates_state tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_prints_usage_without_path tests/test_cli/test_chat_cmd.py::test_gateway_image_workflow_renders_prompt_errors tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled -q` passed, `6 passed in 0.50s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_image_route_workflows.py src/opensquilla/cli/chat_gateway_image_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `225 passed in 2.44s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 478 source files; whitespace passed; pytest passed with `2389 passed, 8 skipped, 2 warnings in 50.50s`; gateway smoke start/status/stop passed on `127.0.0.1:51802`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `6e729bd`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-image-route-executor-boundary` produced merge commit `91bbc24`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 478 source files; whitespace passed; pytest passed with `2391 passed, 6 skipped, 2 warnings in 33.33s`; gateway smoke start/status/stop passed on `127.0.0.1:49231`.
- Residual risk:
  - Low. This slice only moves `/image` route-name dispatch into a thin executor; the existing image workflow still owns prompt parsing, attachment construction, streaming, transcript updates, usage accounting, and usage/error text.
- Next recommended slice:
  - Continue route executor extraction for `/path`, because the existing gateway path workflow already owns local/remote checks and prompt attachment behavior while `_handle_gateway_slash_command` still owns the direct route-name branch.
