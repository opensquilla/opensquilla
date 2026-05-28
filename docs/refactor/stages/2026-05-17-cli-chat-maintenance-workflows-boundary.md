# CLI Chat Maintenance Workflows Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the gateway chat `/clear`, `/reset`, and `/compact` session maintenance slash-command workflows out of `chat_cmd.py` while preserving interactive CLI behavior.

**Architecture:** Keep `chat_cmd.py` as the slash command dispatcher. Add a focused `chat_session_maintenance_workflows.py` module that owns maintenance RPC calls, state reset semantics, and user-facing maintenance output. Keep read-only list/model commands in `chat_slash_workflows.py` and lifecycle create/resume/delete commands in `chat_session_workflows.py`. Add a root `AGENTS.md` project instruction file so future agents automatically pick up the refactor workflow.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, OpenSquilla gateway client protocol, `ChatSessionState`.

---

## Stage

- Name: cli-chat-maintenance-workflows-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-maintenance-workflows-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-maintenance-workflows-boundary`
- Owner: Codex main thread. Parallel explorer dispatch was attempted for maintenance slash behavior and module-shape scouting, but both spawns failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per `docs/refactor/overall-plan.md`.

## Goal

Move gateway chat session maintenance slash workflows behind a dedicated CLI workflow boundary without changing public command behavior, and add root project-level agent instructions for the formal refactor flow.

## Current-state audit

- Current HEAD: `9e48169`.
- Worktree status: clean before stage-plan generation; this stage plan and the red boundary test are dirty before implementation.
- AGENTS.md files in scope before user-requested root creation: only `src/opensquilla/identity/templates/bootstrap/AGENTS.md`, not under this stage's target files.
- Root AGENTS decision: user observed the project root has no `AGENTS.md`; this stage creates a root `AGENTS.md` with public-safe project instructions for future agents. This does not explain the parallel spawn failures, whose observed error was `agent thread limit reached`.
- Ignore decision: `.gitignore` ignored `AGENTS.md` while only unignoring `src/opensquilla/identity/templates/bootstrap/AGENTS.md`; this stage explicitly unignores `/AGENTS.md` so the project-level instruction file can be tracked.
- Branch scope: user confirmed the refactor is happening on the non-main integration branch, so the `.gitignore` change is isolated to the refactor branch until the whole refactor line is intentionally merged or proposed upstream.
- Files inspected:
  - `AGENTS.md` absence at repository root
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-session-workflows-boundary.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_session_workflows.py`
  - `src/opensquilla/cli/chat_slash_workflows.py`
  - `src/opensquilla/cli/repl/session_state.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_handle_gateway_slash_command`
  - `/clear`
  - `/reset`
  - `/compact`
  - `_GatewayClientLike.reset_session`
  - `_GatewayClientLike.compact_session`
  - `ChatSessionState`
- Tests inspected:
  - `test_gateway_slash_clear_resets_session_state`
  - `test_gateway_slash_compact_calls_session_rpc`
  - `test_chat_stateful_session_slashes_use_workflow_boundary`
  - `_FakeGatewayClient.reset_session`
  - `_FakeGatewayClient.compact_session`
- Existing boundary pattern this stage follows:
  - `chat_session_workflows.py` for stateful session lifecycle slash workflows.
  - `chat_slash_workflows.py` for read-only slash workflows.
  - `chat_transcript_exports.py` for chat transcript command extraction.
  - AST boundary tests in `tests/test_cli/test_chat_cmd.py`.

## Boundary decision

- Responsibilities moving out:
  - `/clear` and `/reset` maintenance RPC call via `client.reset_session(state.session_key)`.
  - Clearing transcript and usage after reset.
  - Printing `cleared <session_key>` with the existing `ACCENT` color.
  - `/compact` maintenance RPC call via `client.compact_session(state.session_key)`.
  - Printing existing compacted/skipped status text based on `payload.get("compacted")` and `summary_len`.
- Responsibilities staying in place:
  - Slash command dispatch ordering in `_handle_gateway_slash_command`.
  - `/help`, `/status`, `/session`, `/cost`, `/usage`, `/model`, `/tool-compress`, `/save`, `/image`, `/path`, `/file`, `/permissions`, `/forget`, and `/approvals`.
  - Lifecycle workflows already in `chat_session_workflows.py`.
  - Read-only workflows already in `chat_slash_workflows.py`.
  - `_GatewayClientLike` broad protocol shape in `chat_cmd.py` for now.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_session_maintenance_workflows.py` owns session maintenance workflows for interactive gateway chat.
- Public behavior that must not change:
  - `/clear` and `/reset` both call `reset_session` with the current `state.session_key`.
  - `/clear` and `/reset` clear `state.transcript` and reset `state.usage`.
  - `/clear` and `/reset` print `cleared <session_key>` with the existing `ACCENT` formatting.
  - `/compact` calls `compact_session` with the current `state.session_key`.
  - If compact payload has `compacted`, output remains `compacted summary <summary_len> chars`.
  - If compact payload is not compacted, output remains `compact skipped context already within budget`.
- Files explicitly out of scope:
  - Gateway RPC implementation.
  - Durable `opensquilla sessions ...` command workflows.
  - Standalone chat reset/compact flows.
  - Session persistence internals.
  - Other slash commands besides `/clear`, `/reset`, and `/compact`.

## Agent instruction decision

- File to create:
  - `AGENTS.md`
  - `.gitignore`
- Filename:
  - Use the standard all-caps plural filename `AGENTS.md`, not `Agent.md`.
- Responsibilities:
  - Define repository-wide guidance for future agents.
  - Point agents to current-state inspection, isolated worktrees, stage plans, Superpowers checkpoints, TDD, full gates, multi-agent ownership, and the required co-author trailer.
- Public safety:
  - Do not include local absolute user paths or private host details.
  - Keep instructions general enough for project use while preserving the active refactor discipline.
  - Preserve the template AGENTS unignore and add a root-only unignore rather than broadly tracking every nested `AGENTS.md`.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_session_maintenance_slashes_use_workflow_boundary -q`
- Expected red failure:
  - `chat_session_maintenance_workflows.py` does not exist, and `_handle_gateway_slash_command` still calls `reset_session` and `compact_session` inline.
- Minimal implementation:
  - Create `chat_session_maintenance_workflows.py` with `handle_clear_session_command` and `handle_compact_session_command`.
  - Import those functions in `chat_cmd.py`.
  - Replace inline `/clear`/`/reset` and `/compact` bodies with calls to the new workflow functions.
  - Update tests to import and monkeypatch workflow console/output boundary where needed.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_session_maintenance_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_clear_resets_session_state tests/test_cli/test_chat_cmd.py::test_gateway_slash_compact_calls_session_rpc -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_session_maintenance_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `AGENTS.md`
  - `src/opensquilla/cli/chat_session_maintenance_workflows.py`
- Modify:
  - `.gitignore`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `docs/refactor/stages/2026-05-17-cli-chat-maintenance-workflows-boundary.md`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `AGENTS.md`
  - `docs/refactor/stages/2026-05-17-cli-chat-maintenance-workflows-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-maintenance-workflows-boundary`.
- [x] Write `test_chat_session_maintenance_slashes_use_workflow_boundary`.
- [x] Run the focused test and confirm it fails because the workflow module does not exist and dispatcher still owns maintenance gateway calls.
- [x] Create root `AGENTS.md` with project-level agent/refactor instructions.
- [x] Update `.gitignore` to track the root `/AGENTS.md` while keeping other local agent instructions ignored.
- [x] Implement `chat_session_maintenance_workflows.py`.
- [x] Update `chat_cmd.py` to delegate `/clear`, `/reset`, and `/compact`.
- [x] Update existing tests to patch the new workflow console/output boundary where needed.
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

- Child commit: `22681a4` (`codex/refactor-cli-chat-maintenance-workflows-boundary`)
- Integration merge: `805b987` (`codex/refactor-architecture`)
- Verification evidence:
  - Child preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-maintenance-workflows-boundary` passed.
  - Red check: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_session_maintenance_slashes_use_workflow_boundary -q` failed before implementation because `chat_session_maintenance_workflows.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_session_maintenance_slashes_use_workflow_boundary tests/test_cli/test_chat_cmd.py::test_gateway_slash_clear_resets_session_state tests/test_cli/test_chat_cmd.py::test_gateway_slash_compact_calls_session_rpc -q` passed with 3 tests.
  - Touched checks: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_session_maintenance_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed with 143 tests.
  - Root AGENTS tracking check: `git check-ignore -v AGENTS.md || true && git ls-files --others --exclude-standard AGENTS.md` showed `.gitignore:29:!/AGENTS.md` and `AGENTS.md` as trackable.
  - Child gate: `scripts/refactor_gate.sh` completed ruff, mypy, diff check, full pytest (`2307 passed, 8 skipped`), and gateway smoke successfully.
  - Integration preflight after merge: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` showed `./AGENTS.md` and `./src/opensquilla/identity/templates/bootstrap/AGENTS.md` in AGENTS scope.
  - Integration gate: `scripts/refactor_gate.sh` on merge commit `805b987` completed ruff, mypy, diff check, full pytest (`2309 passed, 6 skipped`), and gateway smoke successfully.
- Residual risk: Low. The slice moves only interactive chat maintenance slash workflows and preserves reset/compact RPC calls, state reset behavior, and output text. Root `AGENTS.md` is intentionally public-safe and tracked by a root-only `.gitignore` unignore.
- Next recommended slice: Move `/model`, `/cost`, and `/usage` slash commands behind focused chat model/usage workflow boundaries after this slice is merged and re-gated on integration.
