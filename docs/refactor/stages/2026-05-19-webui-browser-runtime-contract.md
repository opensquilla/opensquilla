# Web UI Browser Runtime Contract Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-runtime contract harness for the static Web UI core modules so future refactors can execute the RPC, HTTP, router, and app boundaries together without relying only on text-scrape checks.

**Architecture:** Keep visible Web UI behavior unchanged. Add a small browser-runtime contract module loaded with the existing core scripts and a static Node VM harness test that evaluates the browser modules in script order with browser API stubs.

**Tech Stack:** Browser JavaScript static assets, Starlette Gateway template asset order, Node VM contract harness through pytest, Ruff, full refactor gate.

---

## Stage

- Name: webui-browser-runtime-contract
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-webui-browser-runtime-contract`
- Child worktree: `../opensquilla-refactor-agent-webui`
- Owner: Codex Web UI worker. This worker is not alone in the codebase; other workers own parallel worktrees and branches.

## Goal

Create a coarse browser runtime contract harness for the Web UI core runtime modules while preserving every visible control UI workflow.

## Current-state audit

- Current HEAD: `b7422a3` (`Record chat REPL cleanup`).
- Worktree status: clean before writing this stage plan and RED test.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-webui-rpc-access-boundary.md`
  - `docs/refactor/stages/2026-05-18-webui-http-access-boundary.md`
  - `docs/refactor/stages/2026-05-19-webui-rpc-view-state-contract-batch.md`
  - `src/opensquilla/gateway/templates/index.html`
  - `src/opensquilla/gateway/static/js/app.js`
  - `src/opensquilla/gateway/static/js/rpc.js`
  - `src/opensquilla/gateway/static/js/rpc_access.js`
  - `src/opensquilla/gateway/static/js/http_access.js`
  - `src/opensquilla/gateway/static/js/router.js`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
  - `tests/test_gateway/test_webui_http_access_static.py`
- Symbols or command surfaces inspected:
  - Browser global exports for `RpcClient`, `WebUiRpc`, `WebUiHttp`, `Router`, and `App`.
  - Static asset load order in the control UI template.
  - Existing static Web UI contract tests and opt-in Playwright browser tests.
- Tests inspected:
  - `tests/test_gateway/test_webui_rpc_access_static.py`
  - `tests/test_gateway/test_webui_http_access_static.py`
  - `tests/test_gateway/test_chat_static_assets.py`
  - `tests/test_gateway/test_chat_view_static.py`
  - `tests/functional/test_webui_browser_e2e.py`
- Existing boundary pattern this stage follows:
  - `rpc.js` owns low-level WebSocket RPC mechanics.
  - `rpc_access.js` owns view-facing RPC access.
  - `http_access.js` owns browser HTTP/fetch/auth behavior.
  - `router.js` owns History API route resolution.
  - `app.js` remains the bootstrap owner and compatibility source for connection settings and auth token access.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified the current worker is already the fixed dedicated worktree `../opensquilla-refactor-agent-webui` on branch `codex/refactor-webui-browser-runtime-contract`; no new worktree was created.
- `superpowers:writing-plans`:
  - Evidence: read the skill; created this stage plan before writing implementation code, with files, RED/GREEN commands, gates, and residual-risk tracking.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; write and run a failing static/runtime contract test before adding the browser runtime module.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; completion requires focused runtime/static tests, touched-file Ruff, `git diff --check`, feasible full refactor gate, and commit hash evidence.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or `superpowers:subagent-driven-development` used: no same-thread or external worker dispatch for this slice because the owned files form one tightly coupled Web UI core runtime load-order contract.
  - `spawn_agent` probe: skipped; this worker was launched as the Web UI domain worker and the next action was local TDD on owned files.
  - If same-thread agents were unavailable, external worker fallback: not needed because no independent subdomain is being split from this worker's scope.
- Historical evidence note:
  - Prior Web UI stages recorded RPC/HTTP/static view-state coverage and explicitly left browser runtime coverage as residual risk; this stage addresses that gap.

## Boundary decision

- Module batch:
  - `webui-browser-runtime-contract`
- Responsibilities moving out:
  - Browser runtime readiness checks move out of ad hoc static assertions into a dedicated browser-facing contract module and executable harness test.
- Responsibilities staying in place:
  - `RpcClient` protocol semantics, reconnection, handshake, event dispatch, and gap/tick behavior.
  - `WebUiRpc` and `WebUiHttp` public method names and payload behavior.
  - `Router` navigation behavior.
  - `App` bootstrap, layout, navigation registration, connection settings, and auto-connect behavior.
- New module/file responsibility:
  - `src/opensquilla/gateway/static/js/browser_runtime.js` exposes `window.OpenSquillaBrowserRuntime` with runtime global discovery and readiness assertions.
  - `tests/test_gateway/test_webui_browser_runtime_static.py` evaluates the core browser scripts in Node VM order and verifies the runtime contract.
- Public behavior that must not change:
  - Control UI script order other than inserting the no-op runtime contract module after existing core access/router scripts.
  - Visible layout, copy, routes, WebSocket behavior, HTTP auth/download/upload behavior, and view rendering.
- Files explicitly out of scope:
  - Backend Gateway Python.
  - Provider/session/channel/tools runtime.
  - CSS and visible UI layout.
  - Functional Playwright test rewrites.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_browser_runtime_static.py -q`
- Expected red failure:
  - `static/js/browser_runtime.js` is not loaded in the template and the file does not exist.
- Behavior compatibility coverage:
  - Existing RPC/HTTP static tests still cover `WebUiRpc` and `WebUiHttp` public surface.
  - New Node VM harness covers the core runtime globals executing together without firing `DOMContentLoaded`.
- Module-batch implementation:
  - Add the runtime contract module and load it after `router.js` and before view/component scripts.
  - Keep the module side-effect limited to installing `window.OpenSquillaBrowserRuntime`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_webui_browser_runtime_static.py tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_webui_http_access_static.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check tests/test_gateway/test_webui_browser_runtime_static.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/static/js/browser_runtime.js`
  - `tests/test_gateway/test_webui_browser_runtime_static.py`
  - `docs/refactor/stages/2026-05-19-webui-browser-runtime-contract.md`
- Modify:
  - `src/opensquilla/gateway/templates/index.html`
- Test:
  - `tests/test_gateway/test_webui_browser_runtime_static.py`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
  - `tests/test_gateway/test_webui_http_access_static.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-webui-browser-runtime-contract.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Record child hash, verification, residual risk, and next recommended slice.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert this child commit if browser runtime static execution, control UI asset load order, RPC/HTTP access, or app bootstrap behavior regresses.
- Do not rewrite integration, main, or unrelated worktrees.

## Completion record

- Child commit:
  - `9846b294406aaa547fa3001d27c14ea365ecf349` (`9846b29`, `Add Web UI browser runtime contract`).
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty` passed on branch `codex/refactor-webui-browser-runtime-contract` at `b7422a3`.
  - RED: `uv run --extra dev pytest tests/test_gateway/test_webui_browser_runtime_static.py -q` failed as expected with `2 failed`; the template did not load `static/js/browser_runtime.js` and the Node VM harness could not read `src/opensquilla/gateway/static/js/browser_runtime.js`.
  - Minimal GREEN: the same focused RED command passed, `2 passed in 0.07s`.
  - Focused access/runtime suite: `uv run --extra dev pytest tests/test_gateway/test_webui_browser_runtime_static.py tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_webui_http_access_static.py -q` passed, `7 passed in 0.13s`.
  - Web UI static/view suite: `uv run --extra dev pytest tests/test_gateway/test_webui_browser_runtime_static.py tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_status_helper_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py tests/test_gateway/test_token_widget_static.py tests/test_gateway_static_skills_view.py -q` passed, `120 passed in 6.11s`.
  - Touched Ruff: `uv run --extra dev ruff check tests/test_gateway/test_webui_browser_runtime_static.py` passed.
  - Whitespace: `git diff --check` passed.
  - Full child gate: `scripts/refactor_gate.sh` passed; Ruff passed; mypy passed with no issues in 574 source files; whitespace passed; pytest `2806 passed, 8 skipped, 2 warnings in 58.13s`; gateway smoke start/status/stop passed on `127.0.0.1:61054`; refactor gate complete.
  - Optional functional browser attempt: `OPENSQUILLA_WEBUI_BROWSER_E2E=1 OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run --extra dev pytest tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py -q` failed before page execution because Playwright Chromium was not installed in the local cache (`npx playwright install` required).
- Residual risk:
  - Real-browser Playwright smoke did not run to completion in this environment because the Chromium binary is missing; the new Node VM harness covers browser-like execution of the core runtime modules but does not replace a visual/browser rendering pass.
  - The runtime contract intentionally adds only a no-op diagnostic global; future refactors should avoid treating it as a replacement for the existing RPC/HTTP/app modules.
- Next recommended slice:
  - Install or provision Playwright Chromium in the test environment and promote the existing opt-in Web UI browser smokes into a routinely runnable browser gate, or continue with a larger Web UI view-module runtime harness for selected views.
