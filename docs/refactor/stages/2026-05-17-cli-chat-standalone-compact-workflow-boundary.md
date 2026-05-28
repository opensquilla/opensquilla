# CLI Chat Standalone Compact Workflow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move standalone chat `/compact` workflow out of `chat_cmd.py` while preserving standalone REPL behavior.

**Architecture:** Keep `_standalone_repl` in `chat_cmd.py` as the slash dispatcher and TurnRunner coordinator. Extend `chat_standalone_session_workflows.py` so it owns standalone session lifecycle commands: `/new`, `/clear`/`/reset`, and now `/compact`. Provider resolution and durable transcript flush safety remain injected from `chat_cmd.py` in this slice to avoid coupling this workflow module directly to gateway runtime internals.

**Tech Stack:** Python, Typer/Rich CLI, pytest, ruff, mypy, `ChatSessionState`, compaction helpers, Rich console output.

---

## Stage

- Name: cli-chat-standalone-compact-workflow-boundary
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-chat-standalone-compact-workflow-boundary`
- Child worktree: `../opensquilla-refactor-cli-chat-standalone-compact-workflow-boundary`
- Owner: Codex main thread. A read-only explorer dispatch was attempted for standalone `/compact` behavior and boundary shape, but spawning failed with `agent thread limit reached`; this stage proceeds sequentially and records the fallback per root `AGENTS.md`.

## Goal

Move standalone `/compact` behind the standalone session workflow boundary without changing flush safety, context-window selection, provider compaction config, compact-manager compatibility, or display output.

## Current-state audit

- Current HEAD: `c0c0c53`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
  - `src/opensquilla/session/compaction.py`
  - `tests/test_cli/test_chat_cmd.py`
- Symbols or command surfaces inspected:
  - `_standalone_repl`
  - `_flush_before_standalone_rewrite`
  - `_resolve_compaction_provider`
  - standalone `/compact`
  - `build_compaction_config_from_provider`
  - `call_compact_with_optional_config`
  - `_FakeSessionManager`
  - `_LegacyCompactSessionManager`
- Tests inspected:
  - `test_standalone_slash_compact_passes_provider_config`
  - `test_standalone_compact_refuses_non_empty_transcript_without_flush_service`
  - `test_standalone_compact_flushes_before_compacting`
  - `test_standalone_compact_aborts_when_flush_fails`
  - `test_standalone_slash_compact_keeps_legacy_compact_manager_compatible`
  - `test_chat_standalone_clear_slash_uses_workflow_boundary`
- Existing boundary pattern this stage follows:
  - `chat_standalone_session_workflows.py` owns standalone `/new` and `/clear`/`/reset`.
  - Existing compact tests already cover provider config, flush safety, error abort, and legacy compact manager compatibility.

## Boundary decision

- Responsibilities moving out:
  - Calling the durable-transcript safety hook before compaction.
  - Computing context window from `svc.config.context_budget_tokens` with `100_000` fallback.
  - Building `CompactionConfig` from the resolved provider, model override, and `svc.config.compaction`.
  - Calling `call_compact_with_optional_config`.
  - Rendering `compacted summary <N> chars`, `compact skipped context already within budget`, or no-session-manager warning.
- Responsibilities staying in place:
  - `_standalone_repl` slash command dispatch ordering.
  - `_flush_before_standalone_rewrite` implementation.
  - `_resolve_compaction_provider` implementation.
  - Standalone `/save`, `/image`, `/path`, and unknown-command handling.
  - Gateway `/compact` behavior.
- Existing module/file responsibility:
  - `src/opensquilla/cli/chat_standalone_session_workflows.py` owns standalone session lifecycle slash workflows.
- Public behavior that must not change:
  - `/compact` flushes a non-empty durable transcript before compacting.
  - If flush safety fails, compact is skipped and transcript remains.
  - Provider config uses the active local model override and `svc.config.compaction`.
  - Legacy compact managers without a config parameter remain compatible.
  - Success and skip output text remains unchanged.
- Files explicitly out of scope:
  - Gateway `/compact`.
  - `_flush_before_standalone_rewrite` internals.
  - `_resolve_compaction_provider` internals.
  - Provider selector refactors.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_compact_slash_uses_workflow_boundary -q`
- Expected red failure:
  - `chat_standalone_session_workflows.py` does not define/import `handle_standalone_compact_command`, and `_standalone_repl` still contains standalone compact implementation details.
- Minimal implementation:
  - Add `handle_standalone_compact_command` to `chat_standalone_session_workflows.py`.
  - Import the handler in `chat_cmd.py`.
  - Replace the standalone `/compact` inline block with the handler call.
  - Add focused direct workflow behavior coverage for summary output and no-session-manager warning.
- Focused green command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_compact_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_compact_workflow_compacts_with_provider_config tests/test_cli/test_chat_cmd.py::test_standalone_compact_workflow_warns_without_session_manager tests/test_cli/test_chat_cmd.py::test_standalone_slash_compact_passes_provider_config tests/test_cli/test_chat_cmd.py::test_standalone_compact_refuses_non_empty_transcript_without_flush_service tests/test_cli/test_chat_cmd.py::test_standalone_compact_flushes_before_compacting tests/test_cli/test_chat_cmd.py::test_standalone_compact_aborts_when_flush_fails tests/test_cli/test_chat_cmd.py::test_standalone_slash_compact_keeps_legacy_compact_manager_compatible -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q`

## Files

- Create:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-compact-workflow-boundary.md`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_standalone_session_workflows.py`
  - `tests/test_cli/test_chat_cmd.py`
- Test:
  - `tests/test_cli/test_chat_cmd.py`
- Documentation:
  - `docs/refactor/stages/2026-05-17-cli-chat-standalone-compact-workflow-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-compact-workflow-boundary`.
- [x] Write `test_chat_standalone_compact_slash_uses_workflow_boundary`.
- [x] Add focused workflow behavior coverage for compact success and no-session-manager warning.
- [x] Run the focused boundary test and confirm it fails because the workflow handler does not exist and dispatcher still owns standalone compact details.
- [x] Implement `handle_standalone_compact_command`.
- [x] Update `chat_cmd.py` standalone dispatch to delegate `/compact`.
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

- Child commit: `1356d5a`
- Integration merge: `d619561`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-cli-chat-standalone-compact-workflow-boundary` passed on branch `codex/refactor-cli-chat-standalone-compact-workflow-boundary` at `c0c0c53`.
  - Red: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_compact_slash_uses_workflow_boundary -q` failed as expected because `handle_standalone_compact_command` was not imported/defined.
  - Green: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py::test_chat_standalone_compact_slash_uses_workflow_boundary tests/test_cli/test_chat_cmd.py::test_standalone_compact_workflow_compacts_with_provider_config tests/test_cli/test_chat_cmd.py::test_standalone_compact_workflow_warns_without_session_manager tests/test_cli/test_chat_cmd.py::test_standalone_slash_compact_passes_provider_config tests/test_cli/test_chat_cmd.py::test_standalone_compact_refuses_non_empty_transcript_without_flush_service tests/test_cli/test_chat_cmd.py::test_standalone_compact_flushes_before_compacting tests/test_cli/test_chat_cmd.py::test_standalone_compact_aborts_when_flush_fails tests/test_cli/test_chat_cmd.py::test_standalone_slash_compact_keeps_legacy_compact_manager_compatible -q` passed: 8 passed.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_standalone_session_workflows.py tests/test_cli/test_chat_cmd.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_cli/test_chat_cmd.py tests/test_cli/test_cli_product_completeness.py -q` passed: 163 passed.
  - Child gate: `scripts/refactor_gate.sh` passed after implementation and before child commit: ruff, mypy, whitespace, pytest 2327 passed / 8 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
  - Child close: `scripts/refactor_stage_close.sh` passed at child commit `1356d5a`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed at `c0c0c53`.
  - Integration merge: `git merge --no-ff codex/refactor-cli-chat-standalone-compact-workflow-boundary` created merge commit `d619561`.
  - Integration gate: `scripts/refactor_gate.sh` passed after merge: ruff, mypy, whitespace, pytest 2329 passed / 6 skipped / 2 warnings, gateway smoke start/status/stop/status ok.
- Residual risk:
  - Low. The slice only moves standalone compact mechanics and keeps provider resolution and flush safety injected from `chat_cmd.py`.
- Next recommended slice:
  - Continue reducing `chat_cmd.py` by extracting standalone `/image` or `/path` workflows, or pivot to gateway transcript save dispatch.
