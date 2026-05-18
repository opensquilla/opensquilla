# Web UI RPC Access Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move static Web UI view access to the WebSocket RPC client behind a dedicated access boundary while preserving existing view behavior and RPC payloads.

**Architecture:** Keep `RpcClient` as the low-level WebSocket protocol client and keep `App` as the bootstrap owner. Add a `WebUiRpc` access module loaded after `rpc.js` and before every view so views depend on a stable view-facing RPC boundary instead of reaching directly into `App.getRpc()`.

**Tech Stack:** Browser JavaScript static assets, Jinja template asset order, pytest static contract tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: webui-rpc-access-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-webui-rpc-access-boundary`
- Child worktree: `/Users/cwan0785/opensquilla-refactor-webui-rpc-access-boundary`
- Owner: Codex main thread. Agent parallelism was attempted for `webui_rpc_access_probe`, but live `spawn_agent` returned `agent thread limit reached`; this stage proceeds sequentially with the fallback recorded here.

## Goal

Create a module-level Web UI RPC access boundary that covers all static views in one slice, instead of continuing helper-sized Web UI refactors.

## Current-State Audit

- Current HEAD: `83e8c2b` (`Record standalone utility route boundary merge`).
- Worktree status: clean before writing this stage plan and RED test.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/templates/index.html`
  - `src/opensquilla/gateway/static/js/rpc.js`
  - `src/opensquilla/gateway/static/js/app.js`
  - `src/opensquilla/gateway/static/js/views/*.js`
  - `tests/test_gateway/test_chat_view_static.py`
  - `tests/test_gateway/test_static_onboarding_views.py`
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_status_helper_static.py`
- Symbols or command surfaces inspected:
  - Serena `initial_instructions` and `activate_project` succeeded for `/Users/cwan0785/opensquilla-refactor-integration`.
  - Serena `search_for_pattern` located direct `App.getRpc()` view dependencies across all static views.
  - Serena child activation for this new worktree failed with stale cached path `/Users/cwan0785/opensquilla-refactor-cli-chat-standalone-file-workflow-boundary`; shell/git checks confirm the child worktree itself exists and is clean.
- Tests inspected:
  - Existing static text-contract tests for chat, onboarding, status helpers, and public release surfaces.
- Existing boundary pattern this stage follows:
  - `rpc.js` already owns low-level protocol mechanics.
  - `app.js` already owns bootstrap and connection settings.
  - Views already keep per-view rendering logic and store the RPC client in local `_rpc` variables; this stage changes where that client is acquired, not the method payloads.

## Boundary Decision

- Responsibilities moving out:
  - Static views directly calling `App.getRpc()` to acquire the shared RPC client.
  - View-facing access to common RPC operations such as `client`, `call`, `waitForConnection`, `on`, and `policy`.
- Responsibilities staying in place:
  - `RpcClient` WebSocket protocol, reconnect, handshake, ping, event, and response behavior.
  - `App` bootstrap, route registration, connection settings, auth token access, and auto-connect behavior.
  - Per-view rendering, event subscriptions, and RPC method names/payloads.
- New module/file responsibility:
  - `src/opensquilla/gateway/static/js/rpc_access.js` exposes `window.WebUiRpc` as the view-facing RPC access boundary.
- Public behavior that must not change:
  - Asset loading still initializes the same app, views, and WebSocket connection.
  - Existing RPC method names and payload shapes are unchanged.
  - `App.getRpc()` remains available as a compatibility/bootstrap API.
  - HTTP fetch-based approval and upload code is out of this WebSocket RPC boundary and remains unchanged.
- Files explicitly out of scope:
  - Low-level `RpcClient` protocol semantics.
  - Gateway Python RPC handlers and payload factories.
  - View layout/CSS behavior.
  - CLI, Provider, Channels, Tools, and Session runtime boundaries.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_rpc_access_static.py -q`
- Expected red failure:
  - `ValueError: substring not found` for `static/js/rpc_access.js`, or `FileNotFoundError` for `src/opensquilla/gateway/static/js/rpc_access.js`.
- Minimal implementation:
  - Add `static/js/rpc_access.js` exporting `window.WebUiRpc`.
  - Load it after `rpc.js` and before views in `templates/index.html`.
  - Replace all static view `App.getRpc()` client acquisition with `WebUiRpc.client()`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py -q`
- Additional touched-file checks:
  - `uv run --extra dev pytest tests/test_gateway/test_status_helper_static.py tests/test_gateway/test_gateway_static_skills_view.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/static/js/rpc_access.js`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
  - `docs/refactor/stages/2026-05-18-webui-rpc-access-boundary.md`
- Modify:
  - `src/opensquilla/gateway/templates/index.html`
  - `src/opensquilla/gateway/static/js/views/agents.js`
  - `src/opensquilla/gateway/static/js/views/approvals.js`
  - `src/opensquilla/gateway/static/js/views/channels.js`
  - `src/opensquilla/gateway/static/js/views/chat.js`
  - `src/opensquilla/gateway/static/js/views/config.js`
  - `src/opensquilla/gateway/static/js/views/cron.js`
  - `src/opensquilla/gateway/static/js/views/logs.js`
  - `src/opensquilla/gateway/static/js/views/overview.js`
  - `src/opensquilla/gateway/static/js/views/sessions.js`
  - `src/opensquilla/gateway/static/js/views/setup.js`
  - `src/opensquilla/gateway/static/js/views/skills.js`
  - `src/opensquilla/gateway/static/js/views/usage.js`
- Test:
  - `tests/test_gateway/test_webui_rpc_access_static.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-webui-rpc-access-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-webui-rpc-access-boundary`.
- [x] Write the failing static Web UI RPC access contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible Web UI RPC access boundary.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.

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

- Revert the integration merge commit if static asset loading or Web UI RPC access regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
  - Strict preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-webui-rpc-access-boundary` reported the expected dirty-worktree error after the stage plan and RED test were written.
  - Planning preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-webui-rpc-access-boundary` passed on branch `codex/refactor-webui-rpc-access-boundary` at `83e8c2b`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_webui_rpc_access_static.py -q` failed as expected with missing `static/js/rpc_access.js` in the template and missing `src/opensquilla/gateway/static/js/rpc_access.js`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py -q` passed, `77 passed in 4.23s`.
  - Touched static tests: `uv run --extra dev pytest tests/test_gateway/test_status_helper_static.py tests/test_gateway_static_skills_view.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py -q` passed, `26 passed in 0.06s`.
  - Combined focused/touched retry after ruff fix: `uv run --extra dev pytest tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_status_helper_static.py tests/test_gateway_static_skills_view.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py -q` passed, `103 passed in 0.48s`.
  - Touched ruff: `uv run --extra dev ruff check tests/test_gateway/test_webui_rpc_access_static.py` passed after `ruff check --fix` normalized the import block.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 488 source files; whitespace passed; pytest passed with `2404 passed, 8 skipped, 2 warnings in 50.16s`; gateway smoke start/status/stop passed on `127.0.0.1:58942`.
  - Browser smoke: local gateway started on `127.0.0.1:59009`; Playwright opened `/control/chat`, page title was `OpenSquilla Control`, status rendered `Connected`, and console messages at warning level reported `Errors: 0, Warnings: 0`; gateway then stopped and status returned `not_started`.
- Residual risk:
  - Low. The slice changes the static view RPC client acquisition boundary only; method names, params, low-level `RpcClient`, `App.getRpc()` compatibility, fetch upload, and approval HTTP calls are unchanged.
- Next recommended slice:
  - Continue with a larger Web UI module boundary around direct HTTP fetch access (`approval_monitor.js`, approvals view, upload/download helpers) or a larger Gateway RPC method-family split, rather than returning to helper-sized CLI cuts.
