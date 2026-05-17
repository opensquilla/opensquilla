# CLI Chat Session Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the gateway chat `/new`, `/resume`, and `/delete` session lifecycle slash-command workflows out of `chat_cmd.py` while preserving interactive CLI behavior.

**Architecture:** Keep `chat_cmd.py` as the slash command dispatcher. Add a focused `chat_session_workflows.py` module that owns stateful session lifecycle parsing, gateway calls, state reset semantics, and user-facing status/error messages for the three session lifecycle commands. Keep read-only `/sessions` and `/models` in `chat_slash_workflows.py`.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, OpenSquilla gateway client protocol, `ChatSessionState`.

---

## Stage

- Name: cli-chat-session-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-session-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-session-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for session slash behavior and CLI workflow patterns, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per `docs/refactor/overall-plan.md`.

## Goal

Move stateful gateway chat session lifecycle slash command workflows behind a dedicated CLI workflow boundary without changing public command behavior.

## Current-state audit

- Current HEAD: `828060e`.
- Worktree status: clean before stage-plan generation; only this stage plan is dirty after `scripts/refactor_stage_init.sh`.
- AGENTS.md files in scope: only `src/opensquilla/identity/templates/bootstrap/AGENTS.md`, not under this stage's target files.
- Files inspected:
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_slash_workflows.py`
  - `src/opensquilla/cli/sessions_workflows.py`
  - `src/opensquilla/cli/repl/session_state.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `_slash_parts`
  - `/new`
  - `/resume`
  - `/delete`
  - `_GatewayClientLike.create_session`
  - `_GatewayClientLike.resolve_session`
  - `_GatewayClientLike.delete_sessions`
  - `ChatSessionState`
- Tests inspected:
  - `test_gateway_slash_new_passes_title_as_display_name`
  - `test_gateway_slash_delete_resolves_and_reports_errors`
  - `test_gateway_slash_unknown_prefix_is_not_handled`
  - `test_chat_slash_readonly_lists_use_workflow_boundary`
  - existing gateway chat create/resume tests around `_FakeGatewayClient`
- Existing boundary pattern this stage follows:
  - `chat_slash_workflows.py` for read-only chat slash workflows.
  - `chat_transcript_exports.py` for chat transcript command extraction.
  - `*_workflows.py` modules in `src/opensquilla/cli`.
  - AST boundary tests in `tests/test_cli/test_chat_cmd.py`.

## Boundary decision

- Responsibilities moving out:
  - `/new [title]` title parsing, `client.create_session(model=state.model, display_name=title)`, updating `state.session_key`, clearing transcript/usage, and printing the started-session message.
  - `/resume <id>` usage validation, target parsing, `client.resolve_session`, updating `state.session_key`, preserving/updating `state.model`, clearing transcript/usage, and printing the resumed-session message.
  - `/delete <id>` usage validation, target parsing, `client.resolve_session`, `client.delete_sessions`, and success/error/no-delete output.
- Responsibilities staying in place:
  - Slash command dispatch ordering in `_handle_gateway_slash_command`.
  - Stateless/status commands such as `/help`, `/status`, `/session`.
  - Other stateful workflows not in this slice: `/clear`, `/compact`, `/tool-compress`, `/model`, `/save`, `/image`, `/path`, `/file`, `/permissions`, `/forget`, `/approvals`.
  - `_GatewayClientLike` broad protocol shape in `chat_cmd.py` for now.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_session_workflows.py` owns stateful interactive gateway chat session lifecycle workflows.
- Public behavior that must not change:
  - `/new` without a title creates a session with `display_name=None`.
  - `/new Research Notes` passes `display_name="Research Notes"`, updates `state.session_key`, clears transcript and usage, and prints `Started new session (Research Notes): <key>`.
  - `/resume` with no id prints `[red]Usage: /resume <id>[/red]` and does not call the gateway.
  - `/resume abc` resolves `abc`, sets `state.session_key` from `session_key` or `key` fallback to target, updates `state.model` only when the payload has a model, clears transcript and usage, and prints `Resumed session: <key>`.
  - `/delete` with no id prints `[red]Usage: /delete <id>[/red]` and does not call the gateway.
  - `/delete abc` resolves `abc`, deletes the resolved `session_key` or `key` fallback to target, prints an error panel when errors exist, prints `Deleted session: <key>` when deleted, and prints a no-delete error panel when neither deleted nor errors exist.
- Files explicitly out of scope:
  - Gateway RPC implementation.
  - Durable `opensquilla sessions ...` command workflows.
  - Session persistence internals.
  - Web UI.
  - Other slash commands besides `/new`, `/resume`, and `/delete`.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_stateful_session_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_session_workflows.py` does not exist, and `chat_cmd.py` still calls `create_session`, `resolve_session`, and `delete_sessions` inline inside `_handle_gateway_slash_command`.
- Minimal implementation:
  - Create `chat_session_workflows.py` with `handle_new_session_command`, `handle_resume_session_command`, and `handle_delete_session_command`.
  - Import those functions in `chat_cmd.py`.
  - Replace inline `/new`, `/resume`, and `/delete` bodies with calls to the new workflow functions.
  - Update tests to import and monkeypatch workflow console/output boundaries where needed.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_stateful_session_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_new_passes_title_as_display_name tests/test_cli/test_chat_cmd.py::test_gateway_slash_delete_resolves_and_reports_errors -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_session_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `src/opensquilla/cli/chat_session_workflows.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-session-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-session-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-session-workflows-boundary`.
- [x] Write `test_chat_stateful_session_slashes_use_workflow_boundary`.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns gateway calls.
- [x] Implement `chat_session_workflows.py`.
- [x] Update `chat_cmd.py` to delegate `/new`, `/resume`, and `/delete`.
- [x] Update existing tests to patch the new workflow console/output boundary where needed.
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

- Child commit:
- Integration merge:
- Verification evidence:
  - Child preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-session-workflows-boundary` passed.
  - Red check: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_stateful_session_slashes_use_workflow_boundary -q` failed before implementation because `chat_session_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_stateful_session_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_new_passes_title_as_display_name tests/test_cli/test_chat_cmd.py::test_gateway_slash_delete_resolves_and_reports_errors tests/test_cli/test_chat_cmd.py::test_gateway_path_command_remote_rejects_before_send -q` passed with 4 tests.
  - Touched checks: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_session_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed with 142 tests.
  - Child gate: `scripts/refactor_gate.sh` completed ruff, mypy, diff check, full pytest (`2306 passed, 8 skipped`), and gateway smoke successfully.
- Residual risk: Low. The slice moves only stateful interactive chat session lifecycle slash workflows and keeps command parsing, output strings, gateway calls, and state reset behavior compatible.
- Next recommended slice: Move `/clear` and `/compact` session maintenance slash commands behind a dedicated workflow boundary after this slice is merged and re-gated on integration.
