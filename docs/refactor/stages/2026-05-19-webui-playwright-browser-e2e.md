# Web UI Playwright Browser E2E Harness Stage

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: webui-playwright-browser-e2e
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: none; this was a focused integration cleanup for a recorded
  Web UI residual risk.
- Child worktree: none; no temporary worktree was created for this direct
  integration cleanup.
- Owner: Codex main thread, with one read-only `spawn_agent` explorer for Web UI
  E2E coverage audit.

## Goal

Close the Web UI real-browser Playwright residual risk by making the opt-in
Control UI and Chat UI browser tests install their required Chromium browser,
run locally, and be represented in the standalone Web UI browser smoke workflow.

## Current-state audit

- Current HEAD before edits: `d1613c3` (`Record tools integration gate evidence`).
- Worktree status before edits: clean integration worktree.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-webui-browser-runtime-contract.md`
  - `.github/workflows/webui-browser-smoke.yml`
  - `.github/workflows/live-release-e2e.yml`
  - `tests/functional/test_webui_browser_e2e.py`
  - `tests/functional/test_webui_browser_chat_e2e.py`
  - `tests/test_ci/test_workflows.py`
- Symbols or command surfaces inspected:
  - Functional browser harness helpers `_install_playwright`, `_node`, and
    `_npm`.
  - Web UI browser workflow opt-in environment variables and Playwright install
    command.
- Tests inspected:
  - `tests/functional/test_webui_browser_e2e.py`
  - `tests/functional/test_webui_browser_chat_e2e.py`
  - `tests/test_gateway/test_webui_browser_runtime_static.py`
  - `tests/test_gateway/test_webui_rpc_access_static.py`
  - `tests/test_gateway/test_webui_http_access_static.py`
  - `tests/test_ci/test_workflows.py`
- Existing boundary pattern this stage follows:
  - Functional E2E tests stay opt-in and provider-spend-free.
  - Static Web UI tests remain the default suite's browser-like contract.
  - Real Playwright browser tests are promoted to a runnable opt-in gate for
    full page execution.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: read current Superpowers usage guidance before debugging and
    selected the relevant debugging, TDD, parallel-agent, planning, and
    verification skills.
- `superpowers:systematic-debugging`:
  - Evidence: reproduced the exact failure before editing. Command:
    `OPENSQUILLA_WEBUI_BROWSER_E2E=1 OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run --extra dev pytest tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py -q -s`.
    Result: `2 failed`; both failures were `browserType.launch: Executable
    doesn't exist ... chromium_headless_shell-1223` and Playwright requested
    `npx playwright install`.
- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; no new worktree was created because the user
    explicitly directed work in the integration worktree and this stage was a
    focused cleanup of a recorded integration-stage residual risk.
- `superpowers:writing-plans`:
  - Evidence: read the skill and used this stage document to record scope,
    files, RED/GREEN, gates, and cleanup evidence.
- `superpowers:test-driven-development`:
  - Evidence:
    - Browser E2E RED: the opt-in Playwright tests failed before page execution
      on missing Chromium.
    - Harness helper RED: `uv run --extra dev pytest tests/functional/test_webui_browser_harness.py -q`
      failed with `ModuleNotFoundError: No module named
      '_webui_browser_playwright'`.
    - Workflow RED: `uv run --extra dev pytest tests/test_ci/test_workflows.py::test_webui_browser_workflow_is_manual_and_opt_in -q`
      failed because the standalone Web UI browser workflow did not set
      `OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E`.
- `superpowers:verification-before-completion`:
  - Evidence: completion requires the helper/control/chat browser tests,
    static Web UI suite, workflow tests, touched ruff, whitespace, full
    `scripts/refactor_gate.sh`, and final worktree cleanup audit.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used because the browser harness
    fix and read-only coverage audit were independent.
  - `spawn_agent` probe: first attempt failed with `agent thread limit reached`;
    completed stale agents were closed, then a read-only explorer was spawned
    successfully as `019e3ec8-fc0d-75e2-903b-984492cbbb83`.
  - External worker fallback: not needed after stale same-thread agents were
    closed and `spawn_agent` became available.
- Historical evidence note:
  - The prior Web UI browser runtime contract stage recorded the Playwright
    Chromium failure as residual risk. This stage closes that risk with
    executable browser evidence rather than only static Node VM coverage.

## Boundary decision

- Module batch:
  - `webui-playwright-browser-e2e`
- Responsibilities moving out:
  - Playwright npm/browser installation and command-name helpers move out of
    each individual browser E2E file into a shared functional-test helper.
- Responsibilities staying in place:
  - Server startup, health polling, page-specific assertions, and provider-free
    browser scripts stay in the existing E2E test files.
  - Browser tests remain opt-in through
    `OPENSQUILLA_WEBUI_BROWSER_E2E` and
    `OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E`.
- New module/file responsibility:
  - `tests/functional/_webui_browser_playwright.py` installs the Playwright npm
    package and then runs the local Playwright CLI to install Chromium.
  - `tests/functional/test_webui_browser_harness.py` verifies that the helper
    performs both package and browser installation.
- Public behavior that must not change:
  - Control UI route `/control/` must load in a real browser with title
    `OpenSquilla Control`, `#app`, `/control` base path, auth mode `none`, and
    no page errors.
  - Chat UI route `/control/chat` must load in a real browser with textarea,
    send button, active chat nav, gateway status `running`, auth mode `none`,
    no removed tool names, and no page errors.
- Files explicitly out of scope:
  - Visible Web UI layout, CSS, static assets, backend Gateway behavior,
    provider/session/channel/tools runtime.

## TDD red/green

- Failing test commands:
  - Browser RED:
    `OPENSQUILLA_WEBUI_BROWSER_E2E=1 OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run --extra dev pytest tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py -q -s`
  - Helper RED:
    `uv run --extra dev pytest tests/functional/test_webui_browser_harness.py -q`
  - Workflow RED:
    `uv run --extra dev pytest tests/test_ci/test_workflows.py::test_webui_browser_workflow_is_manual_and_opt_in -q`
- Expected red failure:
  - Browser RED fails because Playwright Chromium was not installed after the
    npm package install.
  - Helper RED fails because the shared helper does not exist yet.
  - Workflow RED fails because the standalone Web UI browser smoke does not run
    the chat browser E2E.
- Behavior compatibility coverage:
  - Real browser control and chat tests execute the actual Gateway app through
    Chromium.
  - Static Web UI suite keeps asset/view/runtime contract coverage in the
    default gate.
  - Workflow tests ensure both standalone and live-release browser workflows
    install Linux dependencies with `--with-deps`.
- Module-batch implementation:
  - Add shared Playwright setup helper.
  - Reuse it from both browser E2E files.
  - Add helper unit coverage.
  - Update standalone Web UI browser smoke to run both control and chat browser
    tests and install Chromium with Linux dependencies.
  - Update live-release browser install to use Linux dependencies too.
- Focused green command:
  - `OPENSQUILLA_WEBUI_BROWSER_E2E=1 OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run --extra dev pytest tests/functional/test_webui_browser_harness.py tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py tests/test_gateway/test_webui_browser_runtime_static.py tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_status_helper_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py tests/test_gateway/test_token_widget_static.py tests/test_gateway_static_skills_view.py tests/test_ci/test_workflows.py -q -s`
- Additional touched-file checks:
  - `uv run --extra dev ruff check tests/functional/_webui_browser_playwright.py tests/functional/test_webui_browser_harness.py tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py tests/test_ci/test_workflows.py`
  - `git diff --check`

## Files

- Create:
  - `tests/functional/_webui_browser_playwright.py`
  - `tests/functional/test_webui_browser_harness.py`
  - `docs/refactor/stages/2026-05-19-webui-playwright-browser-e2e.md`
- Modify:
  - `tests/functional/test_webui_browser_e2e.py`
  - `tests/functional/test_webui_browser_chat_e2e.py`
  - `tests/test_ci/test_workflows.py`
  - `.github/workflows/webui-browser-smoke.yml`
  - `.github/workflows/live-release-e2e.yml`
  - `docs/refactor/stages/2026-05-19-webui-browser-runtime-contract.md`
- Test:
  - `tests/functional/test_webui_browser_harness.py`
  - `tests/functional/test_webui_browser_e2e.py`
  - `tests/functional/test_webui_browser_chat_e2e.py`
  - Web UI static/view suite listed above.
  - `tests/test_ci/test_workflows.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping
      existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff` was not applicable
      because this direct integration cleanup did not create a child branch.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record integration hash, verification, and next slice.
- [x] Verify no temporary refactor worktree was left behind.

## Integration gate

- Focused browser and Web UI suite:
  - `OPENSQUILLA_WEBUI_BROWSER_E2E=1 OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run --extra dev pytest tests/functional/test_webui_browser_harness.py tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py tests/test_gateway/test_webui_browser_runtime_static.py tests/test_gateway/test_webui_rpc_access_static.py tests/test_gateway/test_webui_http_access_static.py tests/test_gateway/test_chat_static_assets.py tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_static_onboarding_views.py tests/test_gateway/test_agents_view_static.py tests/test_gateway/test_status_helper_static.py tests/test_gateway/test_usage_view_static.py tests/test_gateway/test_logs_view_static.py tests/test_gateway/test_cron_view_static.py tests/test_gateway/test_token_widget_static.py tests/test_gateway_static_skills_view.py tests/test_ci/test_workflows.py -q -s`
    passed, `131 passed in 5.31s`.
- Touched Ruff:
  - `uv run --extra dev ruff check tests/functional/_webui_browser_playwright.py tests/functional/test_webui_browser_harness.py tests/functional/test_webui_browser_e2e.py tests/functional/test_webui_browser_chat_e2e.py tests/test_ci/test_workflows.py`
    passed.
- Whitespace:
  - `git diff --check` passed.
- Full integration gate:
  - `scripts/refactor_gate.sh` passed; Ruff passed; mypy passed over 577
    source files; whitespace passed; pytest `2823 passed, 6 skipped, 2
    warnings in 32.07s`; gateway smoke start/status/stop/status passed on
    `127.0.0.1:52362`; final line `Refactor gate complete.`
- Cleanup:
  - `git worktree list --porcelain` showed no `opensquilla-refactor-agent-*`
    worktrees.
  - `ls -d ../opensquilla-refactor-*` showed only the integration worktree.

## Rollback

- Revert this direct integration commit if browser installation, control/chat
  browser E2E, or workflow browser-smoke behavior regresses.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Integration commit:
  - `cc665c0` (`Fix Web UI Playwright browser E2E harness`).
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty` passed on branch
    `codex/refactor-architecture` at `d1613c3`.
  - Browser RED: the two opt-in browser tests failed with missing Chromium.
  - Helper RED: helper test failed with missing helper module.
  - Workflow RED: workflow test failed with missing chat opt-in.
  - Browser GREEN: helper/control/chat browser command passed, `3 passed in
    31.39s`.
  - Full focused Web UI/CI GREEN after workflow changes: `131 passed in
    5.31s`.
  - Touched Ruff passed.
  - `git diff --check` passed.
  - Full `scripts/refactor_gate.sh` passed with `2823 passed, 6 skipped, 2
    warnings` and gateway smoke.
- Residual risk:
  - Low. Real browser coverage now exercises page load and key chat/control
    DOM/status contracts. It still does not submit a live provider chat turn,
    validate auth-token mode, uploads, artifacts, approvals, or screenshots;
    those remain broader Web UI E2E expansion opportunities rather than the
    Playwright-install regression closed by this stage.
- Next recommended slice:
  - If more Web UI E2E depth is desired, add a provider-free browser flow for
    upload/artifact or approval UI surfaces behind explicit opt-in gates.
