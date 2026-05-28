# Session Management Domain Services Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move reusable session management service behavior and session runtime accessors from Gateway-owned helper modules into explicit `opensquilla.session` boundary modules while preserving all Gateway RPC method names, payload keys, and compatibility imports.

**Architecture:** Add `opensquilla.session.management_service` for create/patch session behavior, session-key creation, agent registry lookups, and per-turn model normalization. Add `opensquilla.session.services` for manager storage/epoch/lock accessors currently shared by Gateway read/list/send/lifecycle surfaces. Keep `opensquilla.gateway.session_management_service` and `opensquilla.gateway.session_services` as compatibility re-export facades, while Gateway RPC modules import from the new session boundary.

**Tech Stack:** Python, Gateway RPC context/error types, Session manager/storage, AgentRegistry, session RPC payload builders, pytest AST architecture tests, focused Gateway session behavior tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: session-management-domain-services-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-session-management-batch`
- Child worktree: `../opensquilla-refactor-agent-session-management`
- Owner: External Codex worker for session-management batch. Main integration thread owns merge into `codex/refactor-architecture`.

## Goal

Separate reusable session-management services from Gateway helper modules without changing public RPC registration, payload schemas, session key namespace behavior, registry failure semantics, read/list/send/lifecycle behavior, terminal semantics, or compatibility import paths.

## Current-state audit

- Current HEAD: `3d9837d`.
- Worktree status: clean before writing this stage plan; dirty only with this child slice after implementation.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-session-management-boundary.md`
  - `docs/refactor/stages/2026-05-18-gateway-session-management-service-boundary.md`
  - `docs/refactor/stages/2026-05-18-gateway-session-read-query-boundary.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/session_management_service.py`
  - `src/opensquilla/gateway/session_services.py`
  - `src/opensquilla/session/__init__.py`
  - `src/opensquilla/session/keys.py`
  - `src/opensquilla/session/rpc_payload.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `tests/test_gateway/test_rpc_session_services.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Symbols or command surfaces inspected:
  - `sessions.create`
  - `sessions.patch`
  - `sessions.send`
  - `require_session_key`
  - `model_value`
  - `agent_registry_model`
  - `agent_registry_has`
  - `session_turn_model`
  - `create_session_key`
  - `get_session_storage`
  - `get_session_epoch`
  - `set_session_epoch`
  - `get_session_lock`
- Tests inspected:
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_session_services.py`
  - `tests/test_gateway/test_rpc_session_send_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch`
  - `tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing`
- Existing boundary pattern this stage follows:
  - Gateway RPC registration facades delegate to focused modules.
  - Existing `opensquilla.session.rpc_payload` owns session-facing wire payload helpers used by Gateway.
  - Compatibility import facades are kept when public import paths move.

## Boundary decision

- Module batch:
  - `opensquilla.session.management_service`
  - `opensquilla.session.services`
  - Gateway compatibility facades for the two prior helper modules.
- Responsibilities moving out:
  - Session create/patch execution.
  - Session key generation for create flows.
  - Registry-backed agent existence checks and model lookup failure handling.
  - Create/send model normalization through `session_turn_model`.
  - Manager storage/epoch/lock accessors used by read/list/send/lifecycle/registry helpers.
- Responsibilities staying in place:
  - RPC method registration and scope declarations stay in `rpc_sessions.py`.
  - Gateway RPC adapters keep handler names and delegate to boundary services.
  - Gateway-specific routing, attachment ingestion, task runtime enqueueing, lifecycle, read/query, and event behavior remain in their existing Gateway modules.
  - RPC payload constructors stay in `opensquilla.session.rpc_payload`.
- New module/file responsibility:
  - `src/opensquilla/session/management_service.py` owns create/patch/key/registry/model session service behavior.
  - `src/opensquilla/session/services.py` owns public/fallback accessors for session storage, epoch cache, and per-session runtime locks.
  - `src/opensquilla/gateway/session_management_service.py` and `src/opensquilla/gateway/session_services.py` keep backward-compatible re-exports only.
- Public behavior that must not change:
  - `sessions.create`, `sessions.patch`, `sessions.send`, `sessions.list`, read/query, lifecycle, and stream methods keep names, scopes, response keys, and error codes.
  - CLI/webchat/default session key namespaces remain unchanged.
  - Explicit create model overrides still beat registry defaults.
  - Registry listing/model lookup failures still fail open and log warnings.
  - Send-time model selection still prefers the session model over the agent registry model.
  - Existing imports from `opensquilla.gateway.session_management_service` and `opensquilla.gateway.session_services` keep working.
- Files explicitly out of scope:
  - Provider/catalog modules and tests except existing session RPC compatibility tests.
  - Web UI JavaScript/CSS.
  - Session storage schema and manager behavior.
  - Turn runner scheduling/cancellation internals.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q`
- Expected red failure:
  - `src/opensquilla/session/management_service.py` does not exist.
  - `src/opensquilla/session/services.py` does not exist.
  - Gateway modules still import session management/accessor helpers from `opensquilla.gateway.*`.
- Behavior compatibility coverage:
  - Existing Gateway create/patch/send tests keep payload, registry, model, and persistence behavior covered.
  - Existing service accessor tests keep public-surface/fallback behavior covered.
  - New AST boundary test verifies the implementation lives in `opensquilla.session` and Gateway helper modules remain compatibility facades.
- Module-batch implementation:
  - Move service implementations into `opensquilla.session.management_service`.
  - Move accessor implementations into `opensquilla.session.services`.
  - Replace old Gateway helper modules with re-export facades.
  - Update Gateway imports and architecture tests to point at the new session boundary.
- Focused green command:
  - `uv run --extra dev pytest tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/session/management_service.py src/opensquilla/session/services.py src/opensquilla/gateway/session_management_service.py src/opensquilla/gateway/session_services.py src/opensquilla/gateway/rpc_session_management.py src/opensquilla/gateway/rpc_session_send.py src/opensquilla/gateway/rpc_session_read_queries.py src/opensquilla/gateway/rpc_session_lifecycle.py src/opensquilla/gateway/rpc_session_events.py src/opensquilla/gateway/boot.py src/opensquilla/gateway/rpc/registry.py tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/session/management_service.py`
  - `src/opensquilla/session/services.py`
  - `tests/test_session/test_session_management_domain_services_boundary.py`
- Modify:
  - `src/opensquilla/gateway/session_management_service.py`
  - `src/opensquilla/gateway/session_services.py`
  - `src/opensquilla/gateway/rpc_session_management.py`
  - `src/opensquilla/gateway/rpc_session_send.py`
  - `src/opensquilla/gateway/rpc_session_read_queries.py`
  - `src/opensquilla/gateway/rpc_session_lifecycle.py`
  - `src/opensquilla/gateway/rpc_session_events.py`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/rpc/registry.py`
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_session_services.py`
  - `tests/test_gateway/test_rpc_session_send_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Test:
  - `tests/test_session/test_session_management_domain_services_boundary.py`
  - `tests/test_gateway/test_session_management_service_boundary.py`
  - `tests/test_gateway/test_rpc_session_management_boundary.py`
  - `tests/test_gateway/test_rpc_session_services.py`
  - `tests/test_gateway/test_rpc_session_send_boundary.py`
  - `tests/test_gateway/test_rpc_sessions.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-session-management-domain-services-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-session-management-batch`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if the slice regresses Gateway session RPC behavior or compatibility imports.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child implementation commit: `5b4043c`.
- Child head: `ebea51e`.
- Integration merge: `443abcbce14e3a0f9156d1ba0d2ec95786aa2f71`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-session-management-batch` passed on branch `codex/refactor-session-management-batch` at `3d9837d`.
  - Red: `uv run --extra dev pytest tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q` failed as expected with `4 failed, 26 passed in 4.39s`; failures showed missing `opensquilla.session.management_service`, missing `opensquilla.session.services`, and Gateway helper modules still owning implementations.
  - Focused green: `uv run --extra dev pytest tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py::TestSessionsCreate tests/test_gateway/test_rpc_sessions.py::TestSessionsPatch tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_uses_agent_registry_model_when_session_model_missing -q` passed with `30 passed in 0.74s`.
  - Broader Gateway/session group: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_session/test_session_management_domain_services_boundary.py -q` passed with `98 passed in 1.23s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/session/management_service.py src/opensquilla/session/services.py src/opensquilla/gateway/session_management_service.py src/opensquilla/gateway/session_services.py src/opensquilla/gateway/rpc_session_management.py src/opensquilla/gateway/rpc_session_send.py src/opensquilla/gateway/rpc_session_read_queries.py src/opensquilla/gateway/rpc_session_lifecycle.py src/opensquilla/gateway/rpc_session_events.py src/opensquilla/gateway/boot.py src/opensquilla/gateway/rpc/registry.py tests/test_session/test_session_management_domain_services_boundary.py tests/test_gateway/test_session_management_service_boundary.py tests/test_gateway/test_rpc_session_management_boundary.py tests/test_gateway/test_rpc_session_services.py tests/test_gateway/test_rpc_session_send_boundary.py tests/test_gateway/test_rpc_sessions.py` passed after import-order fixes.
  - Whitespace: `git diff --check` passed.
  - Architecture correction: first full `scripts/refactor_gate.sh` run failed at `tests/test_ci/test_architecture_import_contracts.py::test_package_imports_do_not_add_new_edges` because `opensquilla.session.management_service` statically imported `opensquilla.gateway.rpc`, producing `session->gateway`; the service now uses structural typing and lazy exception lookup to avoid that package edge.
  - Full child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 514 source files; whitespace passed; pytest passed with `2466 passed, 8 skipped, 2 warnings in 29.44s`; gateway smoke start/status/stop passed on port `58144`.
  - Integration merge gate: `scripts/refactor_gate.sh` passed after merge `443abcb`; ruff passed; mypy passed with no issues in 514 source files; whitespace passed; pytest passed with `2471 passed, 6 skipped, 2 warnings in 25.98s`; gateway smoke start/status/stop/status passed on `127.0.0.1:58521`.
  - Cleanup: current worktree inventory contains no active/provider/session refactor worker worktrees beyond the integration worktree; `git diff --check HEAD^ HEAD` passed for the latest integration record.
- Residual risk:
  - Low to medium. The public RPC behavior remains covered and compatibility import facades preserve old Gateway paths, but `opensquilla.session.management_service` still performs lazy lookup of Gateway RPC exception classes at raise sites to avoid a static package edge.
- Next recommended slice:
  - Continue with a session lifecycle/read-key normalization batch: consolidate duplicated `require_session_key` helpers in read/lifecycle/session-management modules behind a session-owned parameter normalization boundary while preserving existing error messages and canonicalization behavior.
