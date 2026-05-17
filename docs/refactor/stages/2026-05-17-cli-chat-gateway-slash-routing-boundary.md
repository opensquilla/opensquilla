# CLI Chat Gateway Slash Routing Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway slash command matching and route order into a focused routing boundary.

**Architecture:** Keep `_handle_gateway_slash_command` in `chat_cmd.py` as the gateway command executor for this slice, but remove direct prefix matching from the executor. Add `chat_gateway_slash_routes.py` as a pure route table and matcher that owns exact-vs-prefix command matching and ordering. Handler calls remain in `chat_cmd.py` so this is a small behavior-compatible step toward a declarative dispatcher.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, dataclasses, gateway slash workflows.

---

## Stage

- Name: cli-chat-gateway-slash-routing-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-gateway-slash-routing-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-gateway-slash-routing-boundary`
- Owner: Codex main thread. `spawn_agent` was attempted for a read-only gateway slash router probe, but the current agent thread limit was reached; the fallback is recorded here per root `AGENTS.md`.

## Goal

Extract gateway slash route matching and route ordering from `chat_cmd.py` without changing exact command matching, prefix matching, handler calls, or public CLI behavior.

## Current-state audit

- Current HEAD: `d8b8f41`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-help-workflow-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `_slash_parts_any`
  - gateway `/models` before `/model`
  - gateway `/permissions` and `/elevated`
  - gateway `/forget`
  - gateway unknown prefix handling
- Tests inspected:
  - `test_gateway_slash_models_does_not_hit_model_prefix`
  - `test_gateway_slash_unknown_prefix_is_not_handled`
  - `test_gateway_forget_unknown_prefix_is_not_handled`
  - `test_gateway_status_unknown_prefix_is_not_handled`
  - `test_gateway_elevated_unknown_prefix_is_not_handled`
- Existing boundary pattern this stage follows:
  - `chat_cmd.py` keeps executor responsibility while focused helper modules own separable logic.
  - New pure boundary modules get AST and behavior tests before the production import is changed.
  - Public command behavior remains covered by focused gateway slash tests.

## Boundary decision

- Responsibilities moving out:
  - Route order for gateway slash commands.
  - Exact command vs prefix-with-space matching.
  - Multiple aliases for one route, such as `/status` and `/session`, `/clear` and `/reset`, `/permissions` and `/elevated`.
  - Unknown prefix rejection for commands like `/modelsx`, `/modelx`, `/forgetful`, and `/elevatedx`.
- Responsibilities staying in place:
  - Handler invocation and dependency wiring in `_handle_gateway_slash_command`.
  - Standalone slash matching and `_slash_parts` helper for standalone mode.
  - Gateway workflow modules and user-facing text.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_gateway_slash_routes.py` owns `GATEWAY_SLASH_ROUTES`, `GatewaySlashRoute`, `GatewaySlashRouteMatch`, and `match_gateway_slash_route`.
- Public behavior that must not change:
  - The current route order is preserved exactly.
  - `/models` is matched before `/model`.
  - `/sessionsx`, `/modelsx`, `/modelx`, `/forgetful`, `/permissionsx`, `/elevatedx`, and `/newer` remain unknown.
  - Prefix commands still match the exact command itself and the command followed by a space.
  - Exact aliases still match only exact strings.
- Files explicitly out of scope:
  - Standalone slash routing.
  - Moving handler calls out of `chat_cmd.py`.
  - Changing command names, aliases, output text, or RPC payloads.
  - Web UI, gateway RPC server, or provider/session internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_slash_routes_preserve_order_and_matching_contract -q`
- Expected red failure:
  - `chat_gateway_slash_routes.py` does not exist.
- Minimal implementation:
  - Create `chat_gateway_slash_routes.py` with route dataclasses, route table, and matcher.
  - Update `_handle_gateway_slash_command` to call `match_gateway_slash_route(cmd)` once and branch on the returned route name.
  - Keep existing handler calls and command parts unchanged.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_slash_routes_preserve_order_and_matching_contract tests/test_cli/test_chat_cmd.py::test_gateway_slash_dispatch_uses_route_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_forget_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_slash_routes.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_gateway_slash_routes.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-slash-routing-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-gateway-slash-routing-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-slash-routing-boundary`.
- [x] Write `test_gateway_slash_routes_preserve_order_and_matching_contract`.
- [x] Write `test_gateway_slash_dispatch_uses_route_boundary`.
- [x] Run the focused route boundary test and confirm the expected failure.
- [x] Implement `chat_gateway_slash_routes.py`.
- [x] Update `chat_cmd.py` gateway slash dispatcher to use `match_gateway_slash_route`.
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

- Child commit: `a389c1a` (`Move gateway chat slash matching behind route boundary`)
- Integration merge: `0bf77de` (`Merge CLI chat gateway slash routing boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-cli-chat-gateway-slash-routing-boundary` passed on branch `codex/refactor-cli-chat-gateway-slash-routing-boundary` at `d8b8f41`.
  - Spawn fallback: `spawn_agent` availability check failed with `collab spawn failed: agent thread limit reached`; continued sequentially per root `AGENTS.md`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_slash_routes_preserve_order_and_matching_contract -q` failed as expected because `chat_gateway_slash_routes` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_gateway_slash_routes_preserve_order_and_matching_contract tests/test_cli/test_chat_cmd.py::test_gateway_slash_dispatch_uses_route_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_models_does_not_hit_model_prefix tests/test_cli/test_chat_cmd.py::test_gateway_slash_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_forget_unknown_prefix_is_not_handled tests/test_cli/test_chat_cmd.py::test_gateway_elevated_unknown_prefix_is_not_handled -q` passed, `6 passed in 0.50s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_gateway_slash_routes.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed, `216 passed in 2.38s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 473 source files; whitespace passed; pytest passed with `2380 passed, 8 skipped, 2 warnings in 49.26s`; gateway smoke start/status/stop passed on `127.0.0.1:62961`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `d8b8f41`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-gateway-slash-routing-boundary` produced merge commit `0bf77de`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 473 source files; whitespace passed; pytest passed with `2382 passed, 6 skipped, 2 warnings in 26.22s`; gateway smoke start/status/stop passed on `127.0.0.1:63141`.
- Residual risk: Low. The slice moves route matching and route order into a pure boundary while leaving handler invocation in `chat_cmd.py`; behavior tests cover exact aliases, prefix matching, `/models` before `/model`, and unknown-prefix rejection. No independent subagent review was possible because `spawn_agent` remained unavailable due to the current thread limit.
- Next recommended slice: Move gateway slash handler execution from the long `route_name` branch chain into a focused executor module or command table one route family at a time, starting with exact no-argument routes (`/help`, `/status`, `/clear`, `/compact`, `/cost`, `/usage`) to keep behavior risk small.
