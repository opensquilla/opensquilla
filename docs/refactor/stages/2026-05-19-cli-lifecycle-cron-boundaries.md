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
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_lifecycle_workflows.py src/opensquilla/cli/gateway_lifecycle_presenters.py src/opensquilla/cli/cron_cmd.py src/opensquilla/cli/cron_workflows.py src/opensquilla/cli/cron_presenters.py tests/test_cli/test_gateway_cmd.py tests/test_cli/test_gateway_lifecycle_cli_boundary.py tests/test_cli/test_cron_cmd.py tests/test_cli/test_cron_cli_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`

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

- [ ] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [ ] Commit this stage plan on the active child branch.
- [ ] Create two external worker worktrees from the active child branch.
- [ ] Gateway worker writes failing boundary tests and records RED output.
- [ ] Cron worker writes failing boundary tests and records RED output.
- [ ] Workers implement their disjoint boundaries and record GREEN/check/gate
      evidence.
- [ ] Main thread reviews both diffs for behavior compatibility and ownership.
- [ ] Merge both worker branches into the active child.
- [ ] Run focused green command and touched-file checks.
- [ ] Run `scripts/refactor_gate.sh` in the active child worktree.
- [ ] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active`,
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
- Cron worker commit:
- Active child support commits:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Cleanup evidence:
- Residual risk:
- Next recommended slice:
