# Gateway Sessions Send Input Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `sessions.send` input normalization helpers out of `gateway/rpc_sessions.py` while preserving session send, attachment validation, upload resolution, elevated hints, and memory capture behavior.

**Architecture:** Add a focused `gateway/rpc_session_send_inputs.py` boundary for attachment helper delegation and source/memory-control normalization. Keep `rpc_sessions.py` as the RPC handler owner, with compatibility wrappers for `_validate_attachments` and `_resolve_attachments` because existing tests and upload flows import those names.

**Tech Stack:** Python, Starlette gateway RPC, pytest, ruff, mypy, attachment ingest helpers, session RPC tests.

---

## Stage

- Name: gateway-sessions-send-input-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-sessions-send-input-boundary`
- Child worktree: `../opensquilla-refactor-gateway-sessions-send-input-boundary`
- Owner: Codex main thread. Parallel explorer agents were attempted for Session/Provider/Tools-Web UI broad planning, but they exceeded wait windows and were closed; this slice proceeds from direct current-state audit.

## Goal

Extract non-handler input normalization from `rpc_sessions.py` into a dedicated boundary without changing public RPC method names, payload keys, upload/attachment semantics, elevated trust checks, memory capture controls, or existing compatibility imports.

## Current-state audit

- Current HEAD: `0a89118`.
- Worktree status: clean before stage-plan and test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `src/opensquilla/gateway/attachment_ingest.py`
  - `src/opensquilla/session/rpc_payload.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
  - `tests/test_session/test_session_rpc_payload.py`
- Symbols or command surfaces inspected:
  - `_handle_sessions_send`
  - `_trusted_elevated_hint`
  - `_normalize_memory_capture_controls`
  - `_coerce_optional_bool`
  - `_first_dict_value`
  - `_validate_attachments`
  - `_resolve_attachments`
  - `session_send_accepted_response`
  - `session_send_queue_full_details`
- Tests inspected:
  - `TestSessionsSend.test_gateway_sessions_send_delegates_response_payloads_to_session_boundary`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - upload endpoint attachment resolver tests importing `_validate_attachments` and `_resolve_attachments`.
- Existing boundary pattern this stage follows:
  - Session response payload shape lives in `opensquilla.session.rpc_payload`.
  - Gateway/session handlers import helper functions instead of owning wire-shape logic inline.
  - Compatibility wrapper names remain where tests or public-ish imports already use them.

## Boundary decision

- Responsibilities moving out:
  - Trusted elevated hint extraction from source hints.
  - Memory capture/input provenance/run-kind normalization.
  - Attachment validate/resolve wrapper behavior around `gateway.attachment_ingest`.
- Responsibilities staying in place:
  - `sessions.send` handler orchestration, locking, persistence, runtime queue handling, event emission, and response/error construction.
  - Attachment ingest call that materializes send-time transcript attachments.
  - Existing compatibility names `_validate_attachments` and `_resolve_attachments` in `rpc_sessions.py`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_session_send_inputs.py` owns `trusted_elevated_hint`, `normalize_memory_capture_controls`, `validate_session_attachments`, `resolve_session_attachments`, and small private coercion helpers.
- Public behavior that must not change:
  - Attachment allow-list, size limits, file UUID resolution, logging, and material refs.
  - Owner-only elevated hint trust behavior.
  - `noMemoryCapture`, `inputProvenance`, provenance kind, and run kind aliases.
  - `sessions.send` accepted/queue-full response payloads.
- Files explicitly out of scope:
  - Queue/runtime behavior inside `_handle_sessions_send`.
  - `sessions.reset`, `sessions.compact`, and `sessions.contextCompact`.
  - WebSocket event payload semantics.
  - Changing upload endpoint public behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_input_normalization_to_gateway_boundary tests/test_gateway/test_rpc_sessions_attachments.py::test_rpc_session_attachment_helpers_delegate_to_send_input_boundary -q`
- Expected red failure:
  - `rpc_session_send_inputs.py` does not exist and `rpc_sessions.py` still owns the normalization helpers directly.
- Minimal implementation:
  - Create `opensquilla.gateway.rpc_session_send_inputs`.
  - Move helper bodies into the new module.
  - Import and delegate from `rpc_sessions.py`, keeping `_validate_attachments` and `_resolve_attachments` compatibility wrappers.
  - Update `_handle_sessions_send` to call `trusted_elevated_hint(ctx.principal.is_owner, source_hint)` and `normalize_memory_capture_controls(params)` from the boundary.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_input_normalization_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_valid tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py::test_file_uuid_resolved_via_store_returns_material_ref tests/test_session/test_session_rpc_payload.py::test_chat_send_response_helpers_own_wire_shapes -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_send_inputs.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py`
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_session_rpc_payload.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_session_send_inputs.py`
  - `docs/refactor/stages/2026-05-18-gateway-sessions-send-input-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
- Test:
  - `tests/test_gateway/test_rpc_sessions.py`
  - `tests/test_gateway/test_rpc_sessions_attachments.py`
  - `tests/test_gateway/test_uploads_endpoint.py`
  - `tests/test_session/test_session_rpc_payload.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-sessions-send-input-boundary.md`

## Steps

- [x] Inspect current integration state, AGENTS.md, and session send/helper surfaces.
- [x] Create independent child worktree from integration HEAD.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-sessions-send-input-boundary`.
- [x] Write failing input-boundary tests.
- [x] Run focused tests and confirm expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
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

- Child commit: `e039571` (`Move session send input normalization behind gateway boundary`)
- Integration merge: `14b812f` (`Merge gateway sessions send input boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-gateway-sessions-send-input-boundary` passed on branch `codex/refactor-gateway-sessions-send-input-boundary` at `0a89118`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_input_normalization_to_gateway_boundary tests/test_gateway/test_rpc_sessions_attachments.py::test_rpc_session_attachment_helpers_delegate_to_send_input_boundary -q` failed as expected because `rpc_session_send_inputs.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_gateway_sessions_send_delegates_input_normalization_to_gateway_boundary tests/test_gateway/test_rpc_sessions.py::TestSessionsSend::test_send_valid tests/test_gateway/test_rpc_sessions_attachments.py::test_rpc_session_attachment_helpers_delegate_to_send_input_boundary tests/test_gateway/test_rpc_sessions_attachments.py::test_pdf_inline_accepted tests/test_gateway/test_uploads_endpoint.py::test_file_uuid_resolved_via_store_returns_material_ref tests/test_session/test_session_rpc_payload.py::test_chat_send_response_helpers_own_wire_shapes -q` passed, `6 passed in 0.56s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/rpc_session_send_inputs.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_sessions_attachments.py tests/test_gateway/test_uploads_endpoint.py tests/test_session/test_session_rpc_payload.py -q` passed, `156 passed in 1.71s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 481 source files; whitespace passed; pytest passed with `2390 passed, 8 skipped, 2 warnings in 61.14s`; gateway smoke start/status/stop passed on `127.0.0.1:53169`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `0a89118`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-sessions-send-input-boundary` produced merge commit `14b812f`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 481 source files; whitespace passed; pytest passed with `2392 passed, 6 skipped, 2 warnings in 50.56s`; gateway smoke start/status/stop passed on `127.0.0.1:53804`.
- Residual risk:
  - Low. Compatibility wrappers keep existing `_validate_attachments` and `_resolve_attachments` imports alive, and full child/integration gates passed.
- Next recommended slice:
  - Continue Phase 2/3 with a larger but still isolated Session/Gateway runtime/service boundary slice; parallel read-only scouts are also checking Provider/Engine and Tools/Web UI/Channels candidates from current integration state.
