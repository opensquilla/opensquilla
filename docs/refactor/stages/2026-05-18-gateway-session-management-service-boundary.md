# Gateway Session Management Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway session create/patch service behavior and shared model-default helpers out of the RPC adapter layer while preserving `sessions.create`, `sessions.patch`, and `sessions.send` behavior.

**Architecture:** Add `gateway/session_management_service.py` as the owner for session key generation, registry-backed agent validation/model defaults, create/patch execution, and send-time session turn model selection. Keep `gateway/rpc_session_management.py` as the thin RPC adapter for create/patch and update `gateway/rpc_session_send.py` to depend on the service module rather than the RPC management module.

**Tech Stack:** Python, Gateway RPC context, AgentRegistry, Session manager/storage, session RPC payload builders, pytest AST architecture tests, focused RPC behavior tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-session-management-service-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-session-management-service-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was rechecked and still returned `agent thread limit reached`, so this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate Gateway session management service behavior from RPC adapter modules without changing public RPC methods, scopes, payloads, agent validation, model defaults, send-time model resolution, or patch persistence semantics.

## Current-State Audit

- Current HEAD: `3cbdf28`.
- Worktree status: clean before writing this stage plan and RED test.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-session-management-boundary.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/session_services.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_session_facade_prune_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `gateway/rpc_sessions.py`.
  - `handle_sessions_create`
  - `handle_sessions_patch`
  - `require_session_key`
  - `model_value`
  - `agent_registry_model`
  - `agent_registry_has`
  - `session_turn_model`
  - `create_session_key`
  - `handle_sessions_send`
- Tests inspected:
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch`
  - `tests/test_gateway/test_rpc_sessions.py` send model-default coverage
- Existing boundary pattern this stage follows:
  - RPC registration facades delegate to focused implementation modules.
  - Service/accessor modules own shared Gateway behavior used by more than one RPC adapter.
  - Architecture tests assert ownership through module imports and top-level function locations.

## Boundary Decision

- Responsibilities moving out:
  - Session key generation for create flows.
  - Registry-backed agent existence validation.
  - Agent/session model default helpers used by create and send.
  - Create session behavior, no-manager stub responses, optional seeded message persistence, and payload builder calls.
  - Patch field mapping, update/upsert fallback behavior, and patch payload builder calls.
- Responsibilities staying in place:
  - RPC method registration stays in `rpc_sessions.py`.
  - `rpc_session_management.py` keeps create/patch RPC handler names and delegates to the service.
  - `rpc_session_send.py` keeps send orchestration and imports only the shared service helpers it needs.
  - Existing read/query, lifecycle, send-input, turn-runtime, events, and storage accessor boundaries remain in place.
- New module/file responsibility:
  - `src/opensquilla/gateway/session_management_service.py` owns reusable session management service behavior.
- Public behavior that must not change:
  - RPC method names and scopes remain stable.
  - `sessions.create` response payloads, stub behavior, seeded-message semantics, registry validation, and explicit model override stay unchanged.
  - `sessions.patch` response payloads and persistence fallback semantics stay unchanged.
  - `sessions.send` still resolves model from session first, then agent registry.
  - Registry lookup/list failures remain fail-open for legacy compatibility.
- Files explicitly out of scope:
  - Session manager/storage internals.
  - Turn runtime scheduling and queue behavior.
  - Attachment ingestion and send input normalization.
  - Web UI sessions JavaScript.
  - CLI command behavior.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q`
- Expected red failure:
  - `src/opensquilla/gateway/session_management_service.py` does not exist.
  - `rpc_session_management.py` still owns service helper functions and payload builder imports.
  - `rpc_session_send.py` still imports shared model helpers from the RPC management module.
- Minimal implementation:
  - Create `session_management_service.py`.
  - Move create/patch implementations and shared helpers into it.
  - Rename service entrypoints to `create_session` and `patch_session`.
  - Keep `rpc_session_management.py` handler wrappers and update send imports.
  - Update existing management boundary/payload delegation tests to inspect the service boundary.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/session_management_service.py src/opensquilla/gateway/rpc_session_management.py src/opensquilla/gateway/rpc_session_send.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/session_management_service.py`
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-session-management-service-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-session-management-service-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-session-management-service-boundary`.
- [x] Write the failing session management service boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible service boundary move.
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

- Revert the integration merge commit if session create/patch payloads, send model defaults, registry validation, or patch persistence regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `66df5e94d8a5c1b418f6c4a167908ff6fe77e852`.
- Integration merge: `bad75c335c742d3d6ba037e99b45c1bd3ac1a1e4`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-session-management-service-boundary` passed on branch `codex/refactor-gateway-session-management-service-boundary` at `3cbdf28`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q` failed as expected with `2 failed, 17 passed in 2.93s`; failures showed `session_management_service.py` was missing and `rpc_session_send.py` still imported from the RPC management module.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q` passed with `21 passed in 0.50s`.
  - Broader session group: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_read_queries_boundary.py tests/test_gateway/test_rpc_session_lifecycle_boundary.py tests/test_gateway/test_rpc_session_events.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_public_surface_baseline.py -q` passed with `102 passed in 0.95s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/session_management_service.py src/opensquilla/gateway/rpc_session_management.py src/opensquilla/gateway/rpc_session_send.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_sessions.py` passed.
  - Release hygiene spot check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed with `1 passed in 0.32s`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 505 source files; whitespace passed; pytest passed with `2441 passed, 8 skipped, 2 warnings in 48.90s`; gateway smoke start/status/stop passed on port `50806`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 505 source files; whitespace passed; pytest passed with `2443 passed, 6 skipped, 2 warnings in 26.90s`; gateway smoke start/status/stop passed on port `50944`.
- Residual risk:
  - Low. This slice only moves existing create/patch/model-default behavior behind a service module and keeps RPC method registration, payload builders, registry fail-open behavior, and send model-selection tests green.
- Next recommended slice:
  - Use a larger Provider/Gateway runtime assembly slice next: consolidate provider bootstrap/runtime status/model catalog wiring so Gateway boot code delegates provider assembly through one focused provider runtime service.
