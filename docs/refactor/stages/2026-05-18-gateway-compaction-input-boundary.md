# Gateway Compaction Input Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move gateway compaction provider/model/context-window input normalization into a focused gateway boundary without changing session or WebChat compaction behavior.

**Architecture:** Add `opensquilla.gateway.rpc_compaction_inputs` as the shared helper boundary for gateway RPC compaction inputs. Keep `rpc_sessions.py` and `rpc_chat.py` as RPC handler owners; they call the new helper for context-window coercion, effective model selection, provider resolution, and `CompactionConfig` construction.

**Tech Stack:** Python, Starlette gateway RPC, session compaction, context-overflow auto summarize, pytest, ruff, mypy.

---

## Stage

- Name: gateway-compaction-input-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-compaction-input-boundary`
- Child worktree: `../opensquilla-refactor-gateway-compaction-input-boundary`
- Owner: Codex main thread. Parallel read-only scouts are running for broader Provider, Session/Runtime, and Tools/Web UI/Channels candidates; this slice is intentionally small and non-overlapping.

## Goal

Extract duplicated gateway compaction input/provider normalization from `rpc_sessions.py` and `rpc_chat.py` into a dedicated boundary while preserving `sessions.contextCompact`, `sessions.compact`, and WebChat AUTO_SUMMARIZE behavior.

## Current-state audit

- Current HEAD: `06c7ccb`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-sessions-send-input-boundary.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_chat.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_context_overflow.py`
- Symbols or command surfaces inspected:
  - `rpc_sessions._context_window_tokens`
  - `rpc_sessions._effective_compaction_model`
  - `rpc_sessions._resolve_compaction_provider`
  - `rpc_sessions._handle_sessions_context_compact`
  - `rpc_sessions._handle_sessions_compact`
  - `rpc_chat._effective_compaction_model`
  - `rpc_chat._resolve_compaction_provider`
  - `rpc_chat._build_context_overflow_compaction_config`
  - `sessions.contextCompact`
  - `sessions.compact`
  - WebChat context-overflow AUTO_SUMMARIZE path
- Tests inspected:
  - `TestSessionsCompact.test_gateway_compact_delegates_payload_to_session_boundary`
  - `TestSessionsContextCompact.test_context_compact_passes_provider_config_without_flush_receipt`
  - `TestSessionsContextCompact.test_context_compact_uses_model_override_on_clone_only`
  - `TestSessionsContextCompact.test_gateway_context_compact_delegates_payload_to_session_boundary`
  - `test_rpc_chat_auto_summarize_builds_provider_compaction_config`
- Existing boundary pattern this stage follows:
  - `rpc_session_send_inputs.py` owns gateway/session send input normalization and leaves RPC handlers as orchestrators.
  - `session.rpc_payload` owns response shape construction while gateway handlers delegate payload details.

## Boundary decision

- Responsibilities moving out:
  - Coercing `contextWindowTokens` / `context_window_tokens` into a positive integer with config fallback.
  - Selecting the effective compaction model from `session.model_override` or `session.model`.
  - Cloning the provider selector before applying model overrides.
  - Resolving compaction providers defensively.
  - Building gateway compaction configs from the resolved provider, effective model, and gateway config.
- Responsibilities staying in place:
  - `sessions.contextCompact` lock, storage, session existence, `compact_with_result` fallback, and response construction.
  - `sessions.compact` transcript flush/truncate behavior.
  - WebChat context-overflow policy enforcement and refusal/turn routing.
  - Existing CLI standalone compaction provider resolution.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_compaction_inputs.py` owns `context_window_tokens`, `effective_compaction_model`, `resolve_compaction_provider`, and `build_gateway_compaction_config`.
- Public behavior that must not change:
  - Accepted context-window aliases and validation messages.
  - Session model override precedence.
  - Provider selector clone-only model override behavior.
  - OpenRouter compaction config fields.
  - `sessions.compact` flush receipts and permission errors.
  - WebChat AUTO_SUMMARIZE compaction config passed into `apply_context_overflow_policy`.
- Files explicitly out of scope:
  - `src/opensquilla/session/compaction.py` core summarization logic.
  - `src/opensquilla/cli/chat_cmd.py` standalone compact provider resolution.
  - Reset, abort, queue, terminal, and subscription behavior in `rpc_sessions.py`.
  - Browser/static Web UI changes.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_gateway_context_compact_delegates_inputs_to_gateway_boundary tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_delegates_compaction_inputs_to_gateway_boundary -q`
- Expected red failure:
  - `rpc_compaction_inputs.py` does not exist, and `rpc_sessions.py` / `rpc_chat.py` still define provider/model compaction helpers inline.
- Minimal implementation:
  - Create `opensquilla.gateway.rpc_compaction_inputs`.
  - Move helper bodies for context-window coercion, effective model selection, provider resolution, and compaction config construction into the new module.
  - Import `build_gateway_compaction_config`, `context_window_tokens`, `effective_compaction_model`, and `resolve_compaction_provider` in `rpc_sessions.py`.
  - Import `build_gateway_compaction_config` in `rpc_chat.py`.
  - Keep private compatibility wrappers in `rpc_sessions.py` for `_context_window_tokens`, `_effective_compaction_model`, and `_resolve_compaction_provider`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_gateway_context_compact_delegates_inputs_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_context_compact_passes_provider_config_without_flush_receipt tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_context_compact_uses_model_override_on_clone_only tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_delegates_compaction_inputs_to_gateway_boundary tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_builds_provider_compaction_config -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_chat.py src/opensquilla/gateway/rpc_compaction_inputs.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_context_overflow.py`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact tests/test_gateway/test_context_overflow.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_compaction_inputs.py`
  - `docs/refactor/stages/2026-05-18-gateway-compaction-input-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_chat.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_context_overflow.py`
- Test:
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_context_overflow.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-compaction-input-boundary.md`

## Steps

- [x] Inspect current integration state, AGENTS.md, and compaction helper surfaces.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-compaction-input-boundary`.
- [x] Write failing gateway compaction input boundary tests.
- [x] Run focused tests and confirm expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

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

- Child commit: `c3f177e` (`Move gateway compaction inputs behind boundary`)
- Integration merge: `c717354` (`Merge branch 'codex/refactor-gateway-compaction-input-boundary' into codex/refactor-architecture`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-compaction-input-boundary` passed on branch `codex/refactor-gateway-compaction-input-boundary` at `06c7ccb`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_gateway_context_compact_delegates_inputs_to_gateway_boundary tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_delegates_compaction_inputs_to_gateway_boundary -q` failed as expected because `rpc_compaction_inputs.py` did not exist; `2 failed in 4.70s`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_gateway_context_compact_delegates_inputs_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_context_compact_passes_provider_config_without_flush_receipt tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact::test_context_compact_uses_model_override_on_clone_only tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_delegates_compaction_inputs_to_gateway_boundary tests/test_gateway/test_context_overflow.py::test_rpc_chat_auto_summarize_builds_provider_compaction_config -q` passed; `5 passed in 0.59s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_chat.py src/opensquilla/gateway/rpc_compaction_inputs.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_context_overflow.py` passed.
  - Mypy fix check: `uv run --extra dev mypy src/opensquilla --show-error-codes` passed after narrowing the provider resolver return type; `Success: no issues found in 482 source files`.
  - Touched tests after mypy fix: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsContextCompact tests/test_gateway/test_context_overflow.py -q` passed; `20 passed in 0.71s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 482 source files; whitespace passed; pytest passed with `2392 passed, 8 skipped, 2 warnings in 61.97s`; gateway smoke start/status/stop passed on `127.0.0.1:55284`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-compaction-input-boundary` produced merge commit `c717354` on top of `d229056`, preserving the concurrently merged `rpc_session_turn_runtime.py` boundary.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 483 source files; whitespace passed; pytest passed with `2395 passed, 6 skipped, 2 warnings in 30.25s`; gateway smoke start/status/stop passed on `127.0.0.1:55688`.
- Residual risk:
  - Low. The new boundary centralizes duplicated provider/model/config construction while keeping `rpc_sessions.py` compatibility wrappers for private helper names and preserving existing behavioral tests for session context compaction and WebChat AUTO_SUMMARIZE.
- Next recommended slice:
  - Continue Phase 3 with a session/runtime service boundary after the read-only scouts return; likely candidates are reset drain/epoch emission or session event terminal emission, both of which need focused concurrency tests before implementation.
