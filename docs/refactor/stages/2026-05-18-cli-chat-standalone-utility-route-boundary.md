# CLI Chat Standalone Utility Route Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat utility route execution for `/tool-compress` and `/save` out of `chat_cmd.py` while preserving tool-compression config behavior and in-memory transcript export.

**Architecture:** Keep `chat_standalone_slash_routes.py` as the standalone slash matcher and `_standalone_repl` as the top-level loop. Add `chat_standalone_utility_route_workflows.py` as a thin executor mapping route names to existing utility workflow helpers, mirroring the gateway utility route executor shape without changing behavior.

**Tech Stack:** Python, Typer/Rich CLI, standalone chat REPL, transcript export helper, tool-compression workflow helper, pytest AST boundary tests, ruff, mypy.

---

## Stage

- Name: cli-chat-standalone-utility-route-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-utility-route-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-utility-route-boundary`
- Owner: Codex main thread. A read-only explorer agent was dispatched to inspect this route family; the main thread owns implementation, verification, merge, and conflict resolution.

## Goal

Extract standalone `/tool-compress` and `/save` route-name execution into a focused utility route boundary without changing slash matching, output text, config mutation paths, transcript export behavior, or unsupported-command handling.

## Current-State Audit

- Current HEAD: `1ba7d48`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_slash_routes.py`
  - `src/opensquilla/cli/chat_gateway_utility_route_workflows.py`
  - `src/opensquilla/cli/chat_tool_compression_workflows.py`
  - `src/opensquilla/cli/chat_transcript_exports.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected with Serena:
  - `chat_cmd._standalone_repl`
  - standalone route names `tool_compress` and `save`
  - `handle_tool_compress_command`
  - `save_transcript_command`
- Tests inspected:
  - `test_standalone_slash_routes_preserve_current_command_surface`
  - `test_standalone_tool_compress_toggles_config`
  - `test_tool_compress_workflow_emits_status_and_usage_messages`
  - `test_standalone_save_transcript_writes_memory_transcript`
  - `test_gateway_utility_routes_use_executor_boundary`
  - `test_gateway_utility_route_executor_delegates_known_routes`
- Existing boundary pattern this stage follows:
  - Gateway utility route execution already lives in `chat_gateway_utility_route_workflows.py`.
  - Standalone slash matching already lives in `chat_standalone_slash_routes.py`.
  - Concrete `/tool-compress` behavior already lives in `chat_tool_compression_workflows.py`.
  - Concrete transcript export behavior already lives in `chat_transcript_exports.py`.

## Boundary Decision

- Responsibilities moving out:
  - Mapping standalone `tool_compress` route names to `handle_tool_compress_command(..., config=svc.config)`.
  - Mapping standalone `save` route names to `save_transcript_command(command, state)`.
  - Returning `False` for utility executor route names it does not own.
- Responsibilities staying in place:
  - `_standalone_repl` prompt loop, route matching, service setup, and non-utility route execution.
  - Tool compression workflow implementation.
  - Transcript export implementation.
  - Plain user message streaming and unknown-command rendering.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_utility_route_workflows.py` owns standalone utility route execution for `tool_compress` and `save`.
- Public behavior that must not change:
  - `/tool-compress` continues to mutate/read standalone config through the existing workflow helper.
  - `/save [path]` continues to export the in-memory standalone transcript.
  - Slash route matching still comes from `chat_standalone_slash_routes.py`.
  - Unsupported standalone routes remain unknown.
- Files explicitly out of scope:
  - Gateway utility route execution.
  - Tool-compression workflow internals.
  - Transcript export internals.
  - Standalone session/image/path workflow handlers.
  - Provider, gateway, session, tools, and Web UI internals.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_save_transcript_uses_export_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_route_executor_delegates_known_routes -q`
- Expected red failure:
  - `chat_standalone_utility_route_workflows.py` does not exist and `_standalone_repl` still imports/calls utility helper functions directly.
- Minimal implementation:
  - Create `chat_standalone_utility_route_workflows.py` with `STANDALONE_UTILITY_ROUTE_NAMES` and `handle_standalone_utility_route_command`.
  - Move only route-name execution into the new module; keep concrete helpers unchanged.
  - Update `_standalone_repl` to call the utility route executor after model/cost and before session/image/path handlers.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_save_transcript_uses_export_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_standalone_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_standalone_save_transcript_writes_memory_transcript -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_utility_route_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_utility_route_workflows.py`
  - `docs/refactor/stages/2026-05-18-cli-chat-standalone-utility-route-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-cli-chat-standalone-utility-route-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-utility-route-boundary`.
- [x] Write failing standalone utility route executor boundary tests.
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

## Child Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if standalone `/tool-compress` or `/save` behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `e43b52d`.
- Integration merge: `6e2d7ee`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-standalone-utility-route-boundary` passed on branch `codex/refactor-cli-chat-standalone-utility-route-boundary` at `1ba7d48`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_save_transcript_uses_export_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_route_executor_delegates_known_routes -q` failed as expected because `chat_standalone_utility_route_workflows.py` did not exist and `_standalone_repl` still owned direct utility route execution.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_save_transcript_uses_export_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_routes_use_executor_boundary tests/test_cli/test_chat_cmd.py::test_standalone_utility_route_executor_delegates_known_routes tests/test_cli/test_chat_cmd.py::test_standalone_tool_compress_toggles_config tests/test_cli/test_chat_cmd.py::test_standalone_save_transcript_writes_memory_transcript -q` passed, `5 passed in 0.54s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_utility_route_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py -q` passed, `139 passed in 1.17s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 488 source files; whitespace passed; pytest passed with `2402 passed, 8 skipped, 2 warnings in 27.67s`; gateway smoke start/status/stop passed on `127.0.0.1:57316`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `6e2d7ee`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-utility-route-boundary` produced merge commit `6e2d7ee`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 488 source files; whitespace passed; pytest passed with `2404 passed, 6 skipped, 2 warnings in 27.38s`; gateway smoke start/status/stop passed on `127.0.0.1:57891`.
- Residual risk:
  - Low. This slice only moves standalone utility route-name execution into a thin executor; existing tool-compression and transcript-export helpers still own behavior.
- Next recommended slice:
  - Continue reducing `_standalone_repl` by extracting remaining non-stateful display/help route execution or pivot to the next non-CLI architecture boundary with higher impact.
