# CLI Lifecycle And Cron Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: cli-lifecycle-cron-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-lifecycle-cron-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-cli-gateway-lifecycle-worker`
  - `codex/refactor-cli-cron-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-cli-gateway`
  - `../opensquilla-refactor-agent-cli-cron`
- Owner: main Codex thread coordinates architecture, prompts, review, merge,
  verification, records, and cleanup; two external Codex workers implement
  disjoint CLI subdomains because same-thread `spawn_agent` remains
  unavailable.

## Goal

Thin two independent CLI command surfaces in parallel:

- Gateway lifecycle CLI: move lifecycle manager construction/result emission out
  of `cli/gateway_cmd.py` into a focused workflow/presenter boundary while
  preserving `gateway run/start/status/stop/restart` behavior and terminal/JSON
  output.
- Cron CLI: move cron RPC workflow and table/payload presentation out of
  `cli/cron_cmd.py` into focused workflow/presenter boundaries while preserving
  command names, flags, confirmation behavior, RPC method/payload shapes,
  machine-readable JSON, and table/empty-state text.

## Current-state audit

- Current HEAD: `b3aa8f3` (`Record gateway boot prelude cleanup`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/gateway_cmd.py`
  - `src/opensquilla/cli/cron_cmd.py`
  - `tests/test_cli/test_gateway_cmd.py`
  - `src/opensquilla/cli/gateway_lifecycle.py`
  - `src/opensquilla/cli/gateway_rpc.py`
  - existing CLI workflow/presenter modules under `src/opensquilla/cli`
- Symbols or command surfaces inspected:
  - `gateway_startup_guidance`
  - `run_gateway`
  - `_resolve_lifecycle_host`
  - `_lifecycle_manager`
  - `_emit_lifecycle_result`
  - `start_gateway`, `status_gateway`, `stop_gateway`, `restart_gateway`
  - `cron_list`, `cron_status`, `cron_add`, `cron_update`, `cron_remove`,
    `cron_run`, `cron_runs`
  - `_render_jobs`, `_render_runs`, `_emit_success`
- Tests inspected:
  - `tests/test_cli/test_gateway_cmd.py`
  - Cron has no dedicated CLI test file yet; this stage must add focused Cron
    CLI boundary tests.
- Existing boundary pattern this stage follows:
  - `src/opensquilla/cli/providers_workflows.py`
  - `src/opensquilla/cli/providers_presenters.py`
  - `src/opensquilla/cli/search_workflows.py`
  - `src/opensquilla/cli/search_presenters.py`
  - `src/opensquilla/cli/sessions_workflows.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current resumed work re-read the Superpowers entrypoint and
    relevant stage skills before selecting this batch.
- `superpowers:using-git-worktrees`:
  - Evidence: integration status was inspected at `b3aa8f3`; isolated active
    child worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-cli-lifecycle-cron-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: this stage record was written before production edits.
- `superpowers:test-driven-development`:
  - Evidence: each worker must write RED boundary tests before production edits.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    records, and cleanup evidence are required before claiming this stage
    complete.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes. The two subdomains are
    independent and have disjoint write ownership.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slots `cli-gateway` and `cli-cron`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.
- Main-thread resumed Superpowers evidence:
  - Re-read `superpowers:using-superpowers`,
    `superpowers:dispatching-parallel-agents`,
    `superpowers:subagent-driven-development`,
    `superpowers:using-git-worktrees`, and
    `superpowers:test-driven-development` before reviewing worker outputs.
  - Re-ran the `spawn_agent` availability probe in this resumed turn; it still
    failed with `collab spawn failed: agent thread limit reached`, so this
    stage continued through the external worker pool.

## Boundary decision

- Module batch:
  - CLI Gateway lifecycle workflow/presenter boundary.
  - CLI Cron workflow/presenter boundary.
- Worker ownership:
  - Gateway lifecycle worker owns:
    - `src/opensquilla/cli/gateway_cmd.py`
    - new `src/opensquilla/cli/gateway_lifecycle_workflows.py` and/or
      `src/opensquilla/cli/gateway_lifecycle_presenters.py`
    - `tests/test_cli/test_gateway_cmd.py`
    - `tests/test_cli/test_gateway_lifecycle_cli_boundary.py` if needed
    - this stage record, only gateway-lifecycle evidence sections
  - Cron worker owns:
    - `src/opensquilla/cli/cron_cmd.py`
    - new `src/opensquilla/cli/cron_workflows.py`
    - new `src/opensquilla/cli/cron_presenters.py`
    - new `tests/test_cli/test_cron_cmd.py` and/or
      `tests/test_cli/test_cron_cli_boundary.py`
    - this stage record, only cron evidence sections
- Responsibilities staying in place:
  - Typer command declarations remain in `gateway_cmd.py` and `cron_cmd.py`.
  - Gateway server runtime boot, gateway lifecycle manager internals, gateway
    RPC client internals, and scheduler/gateway RPC handlers stay out of scope.
- Public behavior that must not change:
  - Gateway command names, flags, JSON payloads, text output, exit codes,
    startup guidance, public-bind warnings, and managed lifecycle behavior.
  - Cron command names, flags, confirmation prompts, JSON payloads, RPC method
    names and parameter keys, table titles/columns, and empty-state text.
- Files explicitly out of scope:
  - `src/opensquilla/cli/main.py`
  - `src/opensquilla/cli/gateway_lifecycle.py`
  - `src/opensquilla/cli/gateway_rpc.py`
  - Gateway server/runtime modules.
  - Scheduler/gateway RPC implementations.
  - Web UI assets, dependency locks, release docs.

## TDD red/green

- Gateway lifecycle worker RED command:
  - `uv run --extra dev pytest tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py -q`
- Cron worker RED command:
  - `uv run --extra dev pytest tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py -q`
- Cron worker RED output:
  - Exit code: 1
  - Result: `2 failed, 3 passed in 4.57s`
  - Expected failures:
    - `test_cron_cli_has_workflow_and_presenter_boundaries` failed because
      `src/opensquilla/cli/cron_workflows.py` did not exist.
    - `test_cron_commands_delegate_without_inline_rpc_or_rendering` failed
      because `cron_cmd.py` still called inline RPC/rendering helpers instead
      of `list_cron_jobs_for_cli`.
- Expected red failures:
  - New workflow/presenter boundary modules or delegation tests are absent.
  - Existing command behavior tests must remain green except the intentional new
    boundary assertions.
- Gateway lifecycle worker RED evidence:
  - Command:
    `uv run --extra dev pytest tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py -q`
  - Result: failed as expected with 3 boundary failures and 17 existing gateway
    tests passing.
  - Failure: `Failed: missing gateway lifecycle boundary module:
    opensquilla.cli.gateway_lifecycle_workflows`.
- Gateway lifecycle worker GREEN evidence:
  - Command:
    `uv run --extra dev pytest tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py -q`
  - Result: `20 passed in 0.76s`.
- Gateway lifecycle worker touched-file checks:
  - Command:
    `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_lifecycle_workflows.py src/opensquilla/cli/gateway_lifecycle_presenters.py tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py`
  - Result: `All checks passed!`
  - Command:
    `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - Result: `Success: no issues found in 120 source files` with existing mypy
    notes for untyped function bodies and unused pyproject sections.
  - Command: `git diff --check`
  - Result: passed with no output.
- Gateway lifecycle worker full child gate evidence:
  - Command: `scripts/refactor_gate.sh`
  - Result: passed. Gate completed ruff, mypy, whitespace, pytest, and gateway
    smoke.
  - Pytest summary: `2666 passed, 8 skipped, 2 warnings in 54.14s`.
  - Gateway smoke: start/status/stop/status JSON flow succeeded on port
    `63964`.
- Focused green command after both workers are merged:
  - `uv run --extra dev pytest tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py -q`
- Cron worker focused GREEN command:
  - `uv run --extra dev pytest tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py -q`
- Cron worker focused GREEN output:
  - Exit code: 0
  - Result: `5 passed in 0.75s`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_lifecycle_workflows.py src/opensquilla/cli/gateway_lifecycle_presenters.py src/opensquilla/cli/cron_cmd.py src/opensquilla/cli/cron_workflows.py src/opensquilla/cli/cron_presenters.py tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`
- Cron worker touched-file check output:
  - `uv run --extra dev ruff check src/opensquilla/cli/cron_cmd.py src/opensquilla/cli/cron_workflows.py src/opensquilla/cli/cron_presenters.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py`
    - Exit code: 0
    - Result: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
    - Exit code: 0
    - Result: `Success: no issues found in 120 source files`
    - Notes: mypy also reported the existing unchecked-body note for
      `src/opensquilla/cli/main.py:228` and unused `pyproject.toml` sections.
  - `git diff --check`
    - Exit code: 0
    - Result: no output.

## Cron worker gate evidence

- Full child gate command:
  - `scripts/refactor_gate.sh`
- Full child gate output:
  - Exit code: 0
  - Ruff: `All checks passed!`
  - Mypy: `Success: no issues found in 553 source files`
  - Pytest: `2668 passed, 8 skipped, 2 warnings in 54.63s`
  - Gateway smoke: start/status/stop/status completed.
  - Final line: `Refactor gate complete.`

## Main-thread review and child verification

- Gateway worker commit:
  - `27daf79` (`Refactor gateway lifecycle CLI boundary`)
  - Review: touched only the gateway lifecycle ownership set and this stage
    record; commit trailer appears exactly once.
- Cron worker commit:
  - `d848ba0` (`refactor(cli): split cron workflows and presenters`)
  - Review: touched only the cron CLI ownership set and this stage record;
    commit trailer appears exactly once.
- Worker merges into active child:
  - `fcb39f5` (`Merge gateway lifecycle CLI boundary worker`)
  - `d2ce4dc` (`Merge cron CLI boundary worker`)
- Focused merged GREEN command:
  - `uv run --extra dev pytest tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py -q`
  - Result: `25 passed in 3.67s`.
- Merged touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_lifecycle_workflows.py src/opensquilla/cli/gateway_lifecycle_presenters.py src/opensquilla/cli/cron_cmd.py src/opensquilla/cli/cron_workflows.py src/opensquilla/cli/cron_presenters.py tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py`
    - Result: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
    - Result: `Success: no issues found in 122 source files`.
  - `git diff --check`
    - Result: no output.
- Active child full gate:
  - Command: `scripts/refactor_gate.sh`
  - Result: passed.
  - Mypy: `Success: no issues found in 555 source files`.
  - Pytest: `2671 passed, 8 skipped, 2 warnings in 51.63s`.
  - Gateway smoke: start/status/stop/status JSON flow succeeded on port
    `64403`.
  - Final line: `Refactor gate complete.`

## Files

- Create:
  - `src/opensquilla/cli/gateway_lifecycle_workflows.py` or
    `src/opensquilla/cli/gateway_lifecycle_presenters.py`
  - `src/opensquilla/cli/cron_workflows.py`
  - `src/opensquilla/cli/cron_presenters.py`
  - `tests/test_cli/test_gateway_lifecycle_cli_boundary.py` if needed
  - `tests/test_cli/test_cron_cmd.py` or `tests/test_cli/test_cron_cli_boundary.py`
- Modify:
  - `src/opensquilla/cli/gateway_cmd.py`
  - `src/opensquilla/cli/cron_cmd.py`
  - `tests/test_cli/test_gateway_cmd.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Commit this stage plan on the active child branch.
- [x] Create two external worker worktrees from the active child branch.
- [x] Gateway worker writes failing boundary tests and records RED output.
- [x] Cron worker writes failing boundary tests and records RED output.
- [x] Workers implement their disjoint boundaries and record GREEN/check/gate
      evidence.
- [x] Main thread reviews both diffs for behavior compatibility and ownership.
- [x] Merge both worker branches into the active child.
- [x] Run focused green command and touched-file checks.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
- [x] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`,
      `../opensquilla-refactor-agent-cli-gateway`, and
      `../opensquilla-refactor-agent-cli-cron`; run `git worktree prune`; verify
      no extra refactor worktree directories remain beyond
      `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if CLI command names, flags, JSON output,
  terminal text, exit codes, confirmation behavior, RPC method names/payload
  keys, or gateway smoke behavior regress.
- Keep child and worker branches for diagnosis until a replacement slice is
  ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Gateway worker commit:
  - `27daf79` (`Refactor gateway lifecycle CLI boundary`)
- Cron worker commit:
  - `d848ba0` (`refactor(cli): split cron workflows and presenters`)
- Active child support commits:
  - `44a8a41` (`Plan CLI lifecycle and cron boundaries`)
  - `fcb39f5` (`Merge gateway lifecycle CLI boundary worker`)
  - `d2ce4dc` (`Merge cron CLI boundary worker`)
- Child verification commit:
  - `6e5b7f5` (`Record CLI lifecycle cron child verification`)
- Integration merge:
  - `7022051` (`Merge CLI lifecycle and cron boundaries`)
- Integration record:
  - `afcfc1a` (`Record CLI lifecycle cron integration verification`)
- Verification evidence:
  - Child focused CLI suite: `25 passed in 3.67s`.
  - Child `scripts/refactor_gate.sh`: `2671 passed, 8 skipped, 2 warnings in
    51.63s`; gateway smoke completed on port `64403`.
  - Integration `scripts/refactor_gate.sh`: `2673 passed, 6 skipped, 2
    warnings in 28.21s`; gateway smoke completed on port `64544`.
- Cleanup evidence:
  - `git worktree remove ../opensquilla-refactor-active`
  - `git worktree remove ../opensquilla-refactor-agent-cli-gateway`
  - `git worktree remove ../opensquilla-refactor-agent-cli-cron`
  - `git worktree prune`
  - `find <workspace-parent> -maxdepth 1 -type d -name 'opensquilla-refactor-*'`
    returned only the integration refactor worktree.
- Residual risk:
  - Low. Cron/gateway CLI command shells now delegate to workflow/presenter
    modules; existing command names, flags, RPC method names, payload keys,
    JSON output, table titles, empty states, lifecycle exit codes, and gateway
    smoke behavior are covered by focused and full gates.
- Next recommended slice:
  - Continue with another coarse independent CLI or gateway module family,
    using the same per-substage Superpowers evidence requirement and external
    worker fallback while `spawn_agent` is thread-limited.
