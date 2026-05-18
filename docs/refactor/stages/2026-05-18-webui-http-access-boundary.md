# Web UI HTTP Access Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move direct Web UI HTTP `fetch` access behind a dedicated static access module while preserving approvals, session list fallback, elevated-mode sync, artifact download, and staged upload behavior.

**Architecture:** Keep `WebUiRpc` as the WebSocket RPC access boundary from the previous slice. Add `WebUiHttp` as the browser HTTP access boundary loaded before `approval_monitor.js` and every view, so component/view modules no longer own direct `fetch` or bearer-token header construction.

**Tech Stack:** Browser JavaScript static assets, Jinja template asset order, pytest static contract tests, Playwright smoke, ruff, mypy, full refactor gate.

---

## Stage

- Name: webui-http-access-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-webui-http-access-boundary`
- Child worktree: `../opensquilla-refactor-webui-http-access-boundary`
- Owner: Codex main thread. A read-only explorer agent was attempted for this Web UI HTTP slice, but live `spawn_agent` returned `agent thread limit reached`; this larger module-level stage proceeds sequentially with the fallback recorded here.

## Goal

Centralize the Web UI browser HTTP access surface in one module-level boundary instead of leaving direct `fetch` and auth-header construction distributed across views/components.

## Current-State Audit

- Current HEAD: `0f4ab87` (`Record Web UI RPC access boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/templates/index.html`
  - `src/opensquilla/gateway/static/js/rpc_access.js`
  - `src/opensquilla/gateway/static/js/approval_monitor.js`
  - `src/opensquilla/gateway/static/js/views/approvals.js`
  - `src/opensquilla/gateway/static/js/views/chat.js`
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_chat_view_static.py`
- Symbols or command surfaces inspected:
  - Serena `initial_instructions` and `activate_project` succeeded for the integration worktree.
  - Serena `search_for_pattern` located direct `fetch(` call sites in `approval_monitor.js`, `views/approvals.js`, and `views/chat.js`.
  - Serena child activation for this new worktree failed with a stale cached historical child-worktree path; shell/git checks confirm the child worktree itself exists.
- Tests inspected:
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_chat_view_static.py`
  - `tests/test_gateway/test_static_onboarding_views.py`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
- Existing boundary pattern this stage follows:
  - `static/js/rpc_access.js` owns WebSocket RPC client access for all views.
  - `static/js/app.js` remains the bootstrap owner and compatibility source for `getAuthToken`.
  - Static text-contract tests already enforce Web UI asset dependency order and high-risk browser behavior.

## Boundary Decision

- Responsibilities moving out:
  - Direct `fetch(` calls from `approval_monitor.js`, approvals view, and chat view.
  - Bearer-token Authorization header construction for artifact download and staged upload.
  - JSON POST boilerplate for approvals and elevated-mode endpoints.
- Responsibilities staying in place:
  - `App.getAuthToken()` remains the compatibility source for the current WebSocket/session token.
  - Per-view rendering, toast messages, polling/backoff, form handling, and upload/download result handling.
  - Low-level Gateway endpoint behavior and Python handlers.
- New module/file responsibility:
  - `src/opensquilla/gateway/static/js/http_access.js` exposes `window.WebUiHttp` with `request`, `getJson`, `postJsonResponse`, `postJson`, `download`, and `upload`.
- Public behavior that must not change:
  - Approval monitor polling and adaptive backoff behavior.
  - Approvals view refresh/resolve/settings interactions.
  - Chat session list fallback when `/api/sessions` is unavailable.
  - Elevated-mode 403 handling.
  - Artifact download auth/session headers.
  - Staged upload multipart body, auth header, same-origin credentials, and error handling.
- Files explicitly out of scope:
  - `RpcClient` and WebSocket protocol semantics.
  - Gateway Python HTTP/RPC handlers.
  - CSS/layout changes.
  - CLI, Provider, Channels, Tools, and Session runtime boundaries.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py::test_chat_upload_uses_app_auth_token_accessor tests/test_gateway/test_chat_view_static.py::test_chat_renders_live_and_historical_artifacts_as_header_auth_downloads -q`
- Expected red failure:
  - `static/js/http_access.js` is not loaded or present, direct `fetch(` call sites remain outside the boundary, and existing chat tests still observe direct chat-owned auth/fetch behavior.
- Minimal implementation:
  - Add `static/js/http_access.js` with a lazy `App.getAuthToken()` bridge and response helpers.
  - Load it after `rpc_access.js` and before `approval_monitor.js`.
  - Replace direct `fetch` call sites in `approval_monitor.js`, `views/approvals.js`, and `views/chat.js` with `WebUiHttp`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_webui_rpc_access_static.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/static/js/http_access.js`
  - `tests/test_gateway/test_webui_http_access_static.py`
  - `docs/refactor/stages/2026-05-18-webui-http-access-boundary.md`
- Modify:
  - `src/opensquilla/gateway/templates/index.html`
  - `src/opensquilla/gateway/static/js/approval_monitor.js`
  - `src/opensquilla/gateway/static/js/views/approvals.js`
  - `src/opensquilla/gateway/static/js/views/chat.js`
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_chat_view_static.py`
- Test:
  - `tests/test_gateway/test_webui_http_access_static.py`
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_chat_view_static.py`
  - `tests/test_gateway/test_static_onboarding_views.py`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-webui-http-access-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-webui-http-access-boundary`.
- [x] Write the failing Web UI HTTP access contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible Web UI HTTP access boundary.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

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

- Revert the integration merge commit if browser HTTP behavior, asset loading, uploads, downloads, or approvals regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `250c9a1` (`Extract Web UI HTTP access boundary`)
- Integration merge: `99493dd` (`Merge Web UI HTTP access boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-webui-http-access-boundary` passed on branch `codex/refactor-webui-http-access-boundary` at `0f4ab87`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py::test_chat_upload_uses_app_auth_token_accessor tests/test_gateway/test_chat_view_static.py::test_chat_renders_live_and_historical_artifacts_as_header_auth_downloads -q` failed as expected with missing `static/js/http_access.js`, missing boundary file, and chat still owning download/upload fetch behavior.
  - Minimal green: the same focused RED command passed, `4 passed in 0.02s`.
  - Focused Web UI static group: `uv run --extra dev pytest tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_webui_rpc_access_static.py -q` passed, `79 passed in 0.48s`.
  - Touched ruff: `uv run --extra dev ruff check tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py` passed after `ruff check --fix` normalized the new test import block.
  - Release hygiene spot check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.32s`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 488 source files; whitespace passed; pytest passed with `2406 passed, 8 skipped, 2 warnings in 55.96s`; gateway smoke start/status/stop passed on `127.0.0.1:60013`.
  - Browser smoke: local gateway started on `127.0.0.1:60071`; Playwright opened `/control/chat` and `/control/approvals`, both pages rendered with title `OpenSquilla Control`, status showed `Connected`, and console messages at warning level reported `Errors: 0, Warnings: 0`; gateway then stopped and status returned `not_started`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `0f4ab87`.
  - Integration merge: `git merge --no-ff codex/refactor-webui-http-access-boundary` produced merge commit `99493dd`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 488 source files; whitespace passed; pytest passed with `2408 passed, 6 skipped, 2 warnings in 27.35s`; gateway smoke start/status/stop passed on `127.0.0.1:60335`.
- Residual risk:
  - Low to medium. The slice centralizes HTTP access and preserves endpoint URLs, status handling, same-origin credentials, staged upload multipart bodies, and artifact session headers. The main remaining risk is browser-only behavior around the lazy `App.getAuthToken()` bridge, covered by Playwright load smoke but not by a dedicated JavaScript unit harness.
- Next recommended slice:
  - Continue with a larger Gateway RPC module-family split or Web UI view-service boundary, keeping slices at module scale and avoiding helper-sized cuts.
