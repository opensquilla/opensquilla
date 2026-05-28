# Gateway Session Management Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway session create/patch management behavior out of the monolithic sessions RPC module while preserving public RPC method names, scopes, payloads, agent validation, model defaults, and patch persistence semantics.

**Architecture:** Add `gateway/rpc_session_management.py` as the owner for session management behavior: `sessions.create`, `sessions.patch`, session-key creation, registry-backed agent validation/model defaults, and session turn model selection. Keep `gateway/rpc_sessions.py` as the RPC registration facade plus send/turn runtime owner. Existing read/query, lifecycle, send input, turn runtime, compaction, and event boundaries remain in place.

**Tech Stack:** Python, Gateway RPC dispatcher/context, AgentRegistry, Session manager/storage, session RPC payload builders, pytest behavior and AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-management-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-management-boundary`
- Child worktree: `../opensquilla-refactor-gateway-session-management-boundary`
- Owner: Codex main thread. Parallel read-only explorer probes were dispatched for symbols and tests; main thread owns edits, integration, and gates.

## Goal

Extract the related session management family from `rpc_sessions.py` into a focused Gateway boundary without changing public RPC behavior.

## Current-State Audit

- Current HEAD: `8458933` (`Record gateway session read query boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_session_read_queries_boundary.py`
  - `tests/test_gateway/test_rpc_session_lifecycle_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `initial_instructions`, integration project activation, child project onboarding, and `get_symbols_overview` for `rpc_sessions.py`.
  - Existing management RPC methods: `sessions.create`, `sessions.patch`.
  - Existing helper surfaces: `_model_value`, `_agent_registry_model`, `_agent_registry_has`, `_session_turn_model`, `_create_session_key`, `_require_key`.
- Tests inspected:
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py::test_rpc_method_surface_and_scopes_are_stable`
- Existing boundary pattern this stage follows:
  - `rpc_session_read_queries.py` owns read/query implementation while `rpc_sessions.py` registers wrappers.
  - `rpc_session_lifecycle.py` owns lifecycle mutation implementation while `rpc_sessions.py` registers wrappers.
  - `rpc_session_send_inputs.py` and `rpc_session_turn_runtime.py` split send input and turn runtime concerns.

## Boundary Decision

- Responsibilities moving out:
  - Session create behavior, including default params, session-key namespace generation, registry-backed agent validation, model defaults, explicit model override, no-manager stub responses, message seeding, and `agent.not_found` payload details.
  - Session patch behavior, including field mapping, update fallback/upsert behavior, not-found errors, and patch response payload.
  - Shared model-selection helpers used by create and send.
- Responsibilities staying in place:
  - RPC method registration remains in `rpc_sessions.py`.
  - `sessions.send` turn execution remains in `rpc_sessions.py` and existing send/turn runtime boundaries.
  - Read/query handlers stay delegated to `rpc_session_read_queries.py`.
  - Lifecycle handlers stay delegated to `rpc_session_lifecycle.py`.
  - Event stream helpers stay in `rpc_session_events.py`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_management.py` owns create/patch management implementations and their private helpers.
  - `rpc_sessions.py` keeps compatibility wrapper functions and delegates to the management boundary.
- Public behavior that must not change:
  - RPC method names and scopes remain `sessions.create`/`operator.write` and `sessions.patch`/`operator.admin`.
  - Public payload field names, `sessionId`, `seededMessage`, `agent.not_found` details, and patch `updated` semantics remain unchanged.
  - CLI/webchat session-key namespace behavior remains unchanged.
  - Registry lookup failures remain fail-open for legacy compatibility.
  - `sessions.send` model selection behavior remains unchanged.
- Files explicitly out of scope:
  - Turn runtime scheduling/execution.
  - Attachment ingestion and send input normalization.
  - Read/query and lifecycle behavior.
  - Session storage/manager internals.
  - Web UI sessions JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_public_surface_baseline.py::test_rpc_method_surface_and_scopes_are_stable -q`
- Expected red failure:
  - `src/opensquilla/gateway/rpc_session_management.py` does not exist.
  - `rpc_sessions.py` still owns create/patch implementations and imports their payload builders directly.
- Minimal implementation:
  - Create `rpc_session_management.py`.
  - Move create/patch implementations and their helper functions into it.
  - Keep compatibility wrappers and RPC method registration in `rpc_sessions.py`.
  - Update architecture assertions in `tests/test_gateway/test_rpc_sessions.py` to inspect the new management boundary while preserving behavior tests.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_public_surface_baseline.py::test_rpc_method_surface_and_scopes_are_stable -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_management.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-management-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-management-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-management-boundary`.
- [x] Write the failing Gateway session management boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible management extraction.
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

- Revert the integration merge commit if session create/patch behavior, agent validation, model defaults, patch persistence, or response payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `0f7bd6d`
- Integration merge: `b00ef7e`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-session-management-boundary` passed on branch `codex/refactor-gateway-session-management-boundary` at `8458933`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_public_surface_baseline.py::test_rpc_method_surface_and_scopes_are_stable -q` failed as expected with 2 boundary failures because `rpc_session_management.py` did not exist and `rpc_sessions.py` did not delegate to it; the existing behavior and public surface group still passed, `2 failed, 17 passed in 4.25s`.
  - Focused green: the same focused RED command passed, `19 passed in 0.58s`.
  - Broader sessions management group: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_public_surface_baseline.py -q` passed, `98 passed in 1.30s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_management.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py` passed.
  - Release hygiene spot check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.36s`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 493 source files; whitespace passed; pytest passed with `2417 passed, 8 skipped, 2 warnings in 49.72s`; gateway smoke start/status/stop passed on `127.0.0.1:56141`.
  - Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `8458933`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-session-management-boundary` produced merge commit `b00ef7e`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 493 source files; whitespace passed; pytest passed with `2419 passed, 6 skipped, 2 warnings in 29.27s`; gateway smoke start/status/stop passed on `127.0.0.1:56351`.
- Residual risk:
  - Low to medium. The slice moves create/patch and registry/model helper behavior behind a focused boundary while preserving wrapper registration, public payload builders, session-key namespace behavior, patch persistence fallback, and send model selection via a compatibility wrapper.
- Next recommended slice:
  - Continue shrinking `rpc_sessions.py` with a larger `gateway-session-send-runtime-boundary` pass that folds the remaining send orchestration facade into existing send input/turn runtime boundaries, or switch to the Provider factory/config facade lane.
