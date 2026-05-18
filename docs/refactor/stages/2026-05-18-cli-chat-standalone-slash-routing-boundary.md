# CLI Chat Standalone Slash Routing Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat slash-command matching out of `chat_cmd.py` while preserving the current standalone command surface and unknown-command behavior.

**Architecture:** Add `opensquilla.cli.chat_standalone_slash_routes` as a thin route table and matcher for standalone chat commands. Keep `_standalone_repl` responsible for invoking existing workflow handlers, but make it consume route names and route parts from the new boundary instead of directly owning slash token matching.

**Tech Stack:** Python, Typer/Rich CLI, standalone chat REPL, pytest AST boundary tests, ruff, mypy.

---

## Stage

- Name: cli-chat-standalone-slash-routing-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-slash-routing-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-slash-routing-boundary`
- Owner: Codex main thread. A read-only explorer agent was dispatched for adjacent standalone `/file` reconnaissance; main-thread audit determined standalone `/file` is not currently a supported command and is therefore out of scope for this behavior-compatible slice.

## Goal

Extract standalone slash route matching into a dedicated boundary without changing command semantics, exact/prefix token behavior, workflow handler calls, or the fact that unsupported standalone commands such as `/file` remain unknown.

## Current-State Audit

- Current HEAD: `b57afa8`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_gateway_slash_routes.py`
  - `src/opensquilla/cli/chat_gateway_utility_route_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected with Serena:
  - `chat_cmd._standalone_repl`
  - `chat_cmd._slash_parts`
  - `chat_gateway_slash_routes.match_gateway_slash_route`
  - standalone slash commands: `/help`, `/new`, `/status`, `/session`, `/models`, `/model`, `/cost`, `/tool-compress`, `/clear`, `/reset`, `/compact`, `/save`, `/image`, `/path`
- Tests inspected:
  - `test_standalone_repl_uses_exact_slash_tokens`
  - existing standalone workflow boundary AST tests for model/cost, status/models, new, clear, compact, image, and path
  - gateway slash route and utility executor boundary tests for local pattern matching
- Existing boundary pattern this stage follows:
  - Gateway slash route matching is isolated in `chat_gateway_slash_routes.py`.
  - Standalone workflow behavior is already split into focused `chat_standalone_*_workflows.py` modules.
  - AST tests protect dispatcher boundaries by asserting `chat_cmd.py` calls boundaries rather than owning implementation details.

## Boundary Decision

- Responsibilities moving out:
  - Standalone slash route table.
  - Exact versus prefix slash token matching.
  - Route-name and parts construction for `_standalone_repl`.
- Responsibilities staying in place:
  - `_standalone_repl` loop, prompt handling, exit handling, service setup, and workflow invocation.
  - Existing standalone workflow handlers and their behavior.
  - Plain user message streaming.
  - Unknown command rendering.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_slash_routes.py` owns standalone slash route declarations and matching.
- Public behavior that must not change:
  - `/newer` remains an unknown slash command and does not invoke `/new`.
  - `/models` is exact-only and `/models extra` remains unknown.
  - `/file ...` remains unsupported in standalone mode and prints unknown command.
  - Existing supported commands continue to call their current workflow handlers with the same route parts.
- Files explicitly out of scope:
  - Gateway slash routing.
  - Standalone workflow behavior implementations.
  - Adding standalone `/file` support.
  - Attachment parsing helpers and provider/gateway/session internals.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_standalone_slash_routes_preserve_current_command_surface tests/test_cli/test_chat_cmd.py::test_chat_standalone_slash_matching_uses_route_boundary -q`
- Expected red failure:
  - `opensquilla.cli.chat_standalone_slash_routes` does not exist, and `_standalone_repl` still calls `_slash_parts` directly for standalone command matching.
- Minimal implementation:
  - Create `chat_standalone_slash_routes.py` with route dataclasses, route table, route-name set, prefix matcher, and `match_standalone_slash_route`.
  - Import `match_standalone_slash_route` in `chat_cmd.py`.
  - Replace direct standalone slash matching in `_standalone_repl` with route-match dispatch while keeping existing handler calls and command behavior.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_standalone_slash_routes_preserve_current_command_surface tests/test_cli/test_chat_cmd.py::test_chat_standalone_slash_matching_uses_route_boundary tests/test_cli/test_chat_cmd.py::test_standalone_repl_uses_exact_slash_tokens -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_slash_routes.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_standalone_slash_routes.py`
  - `docs/refactor/stages/2026-05-18-cli-chat-standalone-slash-routing-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-cli-chat-standalone-slash-routing-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-standalone-slash-routing-boundary`.
- [x] Write failing standalone slash-route boundary tests.
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

- Revert the integration merge commit if standalone slash command behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `e6505dc`.
- Integration merge: `844f355`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-standalone-slash-routing-boundary` passed on branch `codex/refactor-cli-chat-standalone-slash-routing-boundary` at `b57afa8`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_standalone_slash_routes_preserve_current_command_surface tests/test_cli/test_chat_cmd.py::test_chat_standalone_slash_matching_uses_route_boundary -q` failed as expected because `chat_standalone_slash_routes.py` did not exist and `_standalone_repl` still owned standalone slash matching.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_standalone_slash_routes_preserve_current_command_surface tests/test_cli/test_chat_cmd.py::test_chat_standalone_slash_matching_uses_route_boundary tests/test_cli/test_chat_cmd.py::test_standalone_repl_uses_exact_slash_tokens -q` passed, `3 passed in 0.69s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_slash_routes.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py -q` passed, `137 passed in 1.06s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 487 source files; whitespace passed; pytest passed with `2400 passed, 8 skipped, 2 warnings in 56.54s`; gateway smoke start/status/stop passed on `127.0.0.1:55565`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `b57afa8`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-slash-routing-boundary` produced merge commit `844f355`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 487 source files; whitespace passed; pytest passed with `2402 passed, 6 skipped, 2 warnings in 31.34s`; gateway smoke start/status/stop passed on `127.0.0.1:56119`.
- Residual risk:
  - Low. The slice moves route matching only; workflow behavior and unsupported standalone `/file` handling remain unchanged.
- Next recommended slice:
  - After this lands, extract standalone utility route execution for `/tool-compress` and `/save` into a focused executor boundary, or continue with a non-CLI architecture boundary if higher leverage.
