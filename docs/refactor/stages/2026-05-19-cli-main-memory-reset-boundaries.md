# CLI Main Memory And Reset Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: cli-main-memory-reset-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-main-memory-reset-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-cli-memory-boundary-worker`
  - `codex/refactor-cli-reset-boundary-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-cli-memory`
  - `../opensquilla-refactor-agent-cli-reset`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  merge conflict resolution, verification, records, and cleanup. Same-thread
  `spawn_agent` was rechecked and remains unavailable, so this stage uses the
  fixed external worker pool.

## Goal

Thin the remaining `src/opensquilla/cli/main.py` command bodies that still mix
Typer declarations with gateway RPC, rendering, and reset workflow behavior:

- Move `memory status/list/search/show` RPC construction and output rendering
  into focused memory workflow/presenter modules while preserving command names,
  flags, RPC method names, payload keys, JSON output, table titles/columns, and
  truncated-content text.
- Move top-level `reset` gateway client workflow and terminal output formatting
  into focused reset workflow/presenter modules while preserving command name,
  flags, gateway URL normalization, exit codes, error text, receipt text, and
  flushed-path output.

`memory dream` and `memory flush-session` stay in place; they are local workflow
commands with different service dependencies and are not part of this batch.

## Current-state audit

- Current HEAD: `bc74c76` (`Record CLI lifecycle cron cleanup`).
- Worktree status: clean before creating this stage plan.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `bc74c76`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/main.py`
  - `src/opensquilla/cli/output.py`
  - existing `*_workflows.py` and `*_presenters.py` CLI patterns
  - `tests/test_cli/test_cli_product_completeness.py`
- Symbols or command surfaces inspected:
  - `memory_status_cmd`
  - `memory_list_cmd`
  - `memory_search_cmd`
  - `memory_show_cmd`
  - `memory_dream_cmd`
  - `reset_cmd`
- Tests inspected:
  - `test_memory_status_json_reuses_doctor_rpc`
  - `test_memory_list_json_uses_gateway_rpc`
  - `test_memory_search_and_show_use_gateway_rpcs`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/cli/cron_workflows.py`
  - `src/opensquilla/cli/cron_presenters.py`
  - `src/opensquilla/cli/diagnostics_workflows.py`
  - `src/opensquilla/cli/diagnostics_presenters.py`
  - `src/opensquilla/cli/sessions_workflows.py`
  - `src/opensquilla/cli/sessions_presenters.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: the main thread re-read the Superpowers entrypoint before
    selecting this resumed stage.
- `superpowers:using-git-worktrees`:
  - Evidence: integration git status/log/worktree list were inspected; fixed
    child worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-cli-main-memory-reset-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: this stage record was written before production edits and before
    launching workers.
- `superpowers:test-driven-development`:
  - Evidence: both workers must add RED boundary tests and record the expected
    failure before moving production logic.
  - Memory worker evidence: read `superpowers:test-driven-development`, added
    `tests/test_cli/test_memory_cli_boundary.py` before production edits, then
    ran the required focused command. RED failed with 3 boundary-test failures
    because `src/opensquilla/cli/memory_workflows.py` and
    `src/opensquilla/cli/memory_presenters.py` did not exist and `main.py` did
    not import the memory workflow functions; the 3 existing memory
    compatibility tests passed.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    hashes, and cleanup evidence are required before claiming this stage
    complete.
  - Memory worker evidence: read `superpowers:verification-before-completion`;
    after extracting memory RPC workflows and presenters, reran the same
    focused command and got 6 passed.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes. Memory and reset
    command bodies are independent command domains with separate new modules and
    separate tests. They both touch `main.py`, so ownership is split by exact
    command regions and the main thread will resolve any import-order conflict.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slots `cli-memory` and `cli-reset`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - CLI memory gateway RPC workflow/presenter boundary.
  - CLI reset workflow/presenter boundary.
- Responsibilities moving out:
  - Memory RPC parameter construction and `run_gateway_sync` calls.
  - Memory JSON/table/content/truncated output rendering.
  - Reset gateway client connection, URL normalization, and RPC call.
  - Reset success/error receipt rendering and exit-code handling.
- Responsibilities staying in place:
  - Typer app/sub-app registration.
  - `memory_app` object and Typer command declarations.
  - `memory_dream_cmd`, `_build_cli_dream`, and `memory_flush_session_cmd`.
  - Gateway/chat/agent command registration and existing sub-app imports.
- New module/file responsibility:
  - `src/opensquilla/cli/memory_workflows.py`: memory RPC workflow functions for
    `status`, `list`, `search`, and `show`.
  - `src/opensquilla/cli/memory_presenters.py`: memory JSON/table/content
    presenters.
  - `src/opensquilla/cli/reset_workflows.py`: reset session client workflow and
    CLI entrypoint helper.
  - `src/opensquilla/cli/reset_presenters.py`: reset success/error terminal
    output and `typer.Exit` handling.
- Public behavior that must not change:
  - Command names and flags: `memory status/list/search/show`, top-level
    `reset`, `--agent`, `--json`, `--limit/-n`, `--from-line`, `--lines`,
    `--key`, `--gateway`, and `OPENSQUILLA_GATEWAY_URL`.
  - RPC methods and payload keys: `doctor.memory.status`, `memory.list`,
    `memory.search`, `memory.show`, `agentId`, `query`, `limit`, `path`,
    `fromLine`, and `lines`.
  - JSON output must remain stdout-only via the shared CLI JSON contract.
  - Memory table titles/columns and `... truncated` text must be preserved.
  - Reset success text, error text, exit code `1` for gateway reset RPC failure,
    receipt mode text, duration formatting, and flushed path lines must be
    preserved.
- Files explicitly out of scope:
  - `src/opensquilla/cli/memory_flush_cmd.py`
  - Memory gateway RPC implementations.
  - Session lifecycle/flush service implementations.
  - `src/opensquilla/cli/gateway_client.py`
  - `src/opensquilla/cli/chat_cmd.py`
  - Web UI assets, dependency locks, release docs.

## Parallel worker ownership

- Worker `cli-memory` owns:
  - Modify only the memory RPC command region in `src/opensquilla/cli/main.py`:
    `memory_status_cmd`, `memory_list_cmd`, `memory_search_cmd`, and
    `memory_show_cmd`.
  - Create `src/opensquilla/cli/memory_workflows.py`.
  - Create `src/opensquilla/cli/memory_presenters.py`.
  - Create/modify `tests/test_cli/test_memory_cli_boundary.py`.
  - May add focused memory assertions to `tests/test_cli/test_cli_product_completeness.py`
    only if needed.
  - Update only memory evidence sections in this stage record.
- Worker `cli-reset` owns:
  - Modify only the top-level `reset_cmd` region in `src/opensquilla/cli/main.py`.
  - Create `src/opensquilla/cli/reset_workflows.py`.
  - Create `src/opensquilla/cli/reset_presenters.py`.
  - Create/modify `tests/test_cli/test_reset_cli_boundary.py`.
  - Update only reset evidence sections in this stage record.
- Main thread owns:
  - Stage plan and worker prompts.
  - Any import-order conflict in `src/opensquilla/cli/main.py`.
  - Worker review, child merges, focused batch verification, full gates,
    integration merge, completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers'
changes and must not revert unrelated edits.

## TDD red/green

- Failing test commands:
  - Memory worker:
    `uv run --extra dev pytest tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_cli_product_completeness.py::test_memory_status_json_reuses_doctor_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_list_json_uses_gateway_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_search_and_show_use_gateway_rpcs -q`
    - RED result from `codex/refactor-cli-memory-boundary-worker`: exit 1,
      3 failed and 3 passed. Failures were
      `test_memory_commands_delegate_to_workflow_boundary`,
      `test_memory_workflow_owns_rpc_methods_and_payload_keys`, and
      `test_memory_presenter_owns_json_table_and_truncated_rendering`.
  - Reset worker:
    `uv run --extra dev pytest tests/test_cli/test_reset_cli_boundary.py -q`
- Expected red failures:
  - New boundary modules do not exist yet.
  - `main.py` still imports/calls gateway RPC/client/rendering details inside
    the command bodies.
- Behavior compatibility coverage:
  - Existing memory product completeness tests listed above.
  - New reset tests must cover success modes and RPC failure output.
- Module-batch implementation:
  - Keep Typer command declarations in `main.py`.
  - Delegate command bodies to workflow functions.
  - Keep JSON/table/error rendering in presenters.
  - Preserve exact user-facing text and exit codes.
- Focused green command after both workers are merged:
  - `uv run --extra dev pytest tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_reset_cli_boundary.py tests/test_cli/test_cli_product_completeness.py::test_memory_status_json_reuses_doctor_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_list_json_uses_gateway_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_search_and_show_use_gateway_rpcs -q`
  - Memory worker GREEN result before reset-worker merge:
    `uv run --extra dev pytest tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_cli_product_completeness.py::test_memory_status_json_reuses_doctor_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_list_json_uses_gateway_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_search_and_show_use_gateway_rpcs -q`
    exited 0 with 6 passed.
  - Memory worker reran the same focused command after ruff's import-order fix:
    exit 0, 6 passed.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/main.py src/opensquilla/cli/memory_workflows.py src/opensquilla/cli/memory_presenters.py src/opensquilla/cli/reset_workflows.py src/opensquilla/cli/reset_presenters.py tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_reset_cli_boundary.py tests/test_cli/test_cli_product_completeness.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`
  - Memory worker touched-file checks:
    - `uv run --extra dev ruff check src/opensquilla/cli/main.py src/opensquilla/cli/memory_workflows.py src/opensquilla/cli/memory_presenters.py tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_cli_product_completeness.py`
      exited 0, all checks passed.
    - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
      exited 0, no issues found in 124 source files.
    - `git diff --check` exited 0.
  - Memory worker full gate:
    - `scripts/refactor_gate.sh` exited 1 after ruff, mypy, and whitespace
      passed and pytest reported 2673 passed, 8 skipped, 1 failed.
    - The failing test was
      `tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths`
      for a pre-existing local path in
      `docs/refactor/stages/2026-05-19-cli-lifecycle-cron-boundaries.md`.
      `git show HEAD:docs/refactor/stages/2026-05-19-cli-lifecycle-cron-boundaries.md`
      confirms the same local-home path lines already exist at HEAD, and that
      file is outside the memory worker ownership boundary.
    - The hygiene failure was fixed in active child commit `0272bef` before
      the worker branches were merged for child verification.

### Reset worker evidence

- Superpowers:
  - `superpowers:using-superpowers` read before implementation.
  - `superpowers:test-driven-development` read before writing reset boundary
    tests.
  - `superpowers:verification-before-completion` read before running checks.
- Current-state audit:
  - Branch: `codex/refactor-cli-reset-boundary-worker`.
  - Recent HEAD before reset edits: `30a7804` (`Plan CLI main memory reset boundaries`).
  - In-scope `AGENTS.md`: root `AGENTS.md`.
  - Reset command inspected in `src/opensquilla/cli/main.py`.
  - Existing presenter/workflow patterns inspected:
    `cron_workflows.py`, `cron_presenters.py`, `diagnostics_workflows.py`,
    and `diagnostics_presenters.py`.
- RED:
  - Command:
    `uv run --extra dev pytest tests/test_cli/test_reset_cli_boundary.py -q`
  - Result: expected failure, `8 failed`.
  - Failure reason: missing `opensquilla.cli.reset_workflows` and
    `opensquilla.cli.reset_presenters`; `reset_cmd` still owned inline
    gateway workflow/rendering before extraction.
- GREEN:
  - Command:
    `uv run --extra dev pytest tests/test_cli/test_reset_cli_boundary.py -q`
  - Result: `8 passed in 0.64s`.
- Reset boundary implementation:
  - Created `src/opensquilla/cli/reset_workflows.py` for `asyncio.run`,
    `GatewayClient`, `GatewayRPCError`, `normalize_gateway_url`, connect/reset/
    close, success handoff, and RPC failure handoff.
  - Created `src/opensquilla/cli/reset_presenters.py` for exact success/error
    terminal text and `typer.Exit(1)`.
  - Updated only the top-level `reset_cmd` region in `src/opensquilla/cli/main.py`
    to delegate to `reset_session_for_cli(key, gateway_url=gateway_url)`.
- Touched checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/main.py src/opensquilla/cli/reset_workflows.py src/opensquilla/cli/reset_presenters.py tests/test_cli/test_reset_cli_boundary.py`
    result: passed.
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
    result: passed, no issues found in 124 source files.
  - `git diff --check` result: passed.
- Full gate:
  - Pre-gate hygiene fix: cherry-picked active child commit `0272bef` to remove
    a tracked local home path from the prior CLI lifecycle cron stage record.
  - Command: `scripts/refactor_gate.sh`
  - Result after hygiene fix: passed.
  - Gate evidence: ruff passed, mypy passed (`557 source files`), whitespace
    passed, pytest `2679 passed, 8 skipped`, gateway smoke passed, refactor gate
    complete.

## Files

- Create:
  - `src/opensquilla/cli/memory_workflows.py`
  - `src/opensquilla/cli/memory_presenters.py`
  - `src/opensquilla/cli/reset_workflows.py`
  - `src/opensquilla/cli/reset_presenters.py`
  - `tests/test_cli/test_memory_cli_boundary.py`
  - `tests/test_cli/test_reset_cli_boundary.py`
- Modify:
  - `src/opensquilla/cli/main.py`
  - `tests/test_cli/test_cli_product_completeness.py` only if needed.
- Test:
  - `tests/test_cli/test_memory_cli_boundary.py`
  - `tests/test_cli/test_reset_cli_boundary.py`
  - selected existing memory product completeness tests.
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status.
- [x] Create fixed active worktree on `codex/refactor-cli-main-memory-reset-boundaries`.
- [x] Write this stage plan before production edits.
- [x] Commit this stage plan as the worker base.
- [x] Launch two external workers with `scripts/refactor_external_agent.sh`.
- [x] Memory worker writes RED boundary tests and records RED output.
- [x] Reset worker writes RED boundary tests and records RED output.
- [x] Workers implement their disjoint boundaries and record GREEN/check/gate evidence.
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
      `../opensquilla-refactor-agent-cli-memory`, and
      `../opensquilla-refactor-agent-cli-reset`; run `git worktree prune`; verify
      no extra refactor worktree directories remain beyond
      `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

### Child verification evidence

- Worker review:
  - Memory worker commit `2eb0f98` reviewed for ownership, behavior
    compatibility, and exactly one required co-author trailer.
  - Reset worker commit `26f168d` reviewed for ownership, behavior
    compatibility, and exactly one required co-author trailer.
- Active child merge commits:
  - `88c7cee` merged `codex/refactor-cli-memory-boundary-worker`.
  - `06e44ae` merged `codex/refactor-cli-reset-boundary-worker`.
- Conflict scan:
  - `rg -n "<<<<<<<|>>>>>>>|=======" src/opensquilla/cli docs/refactor/stages/2026-05-19-cli-main-memory-reset-boundaries.md`
    returned no matches.
- Focused post-merge command:
  - `uv run --extra dev pytest tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_reset_cli_boundary.py tests/test_cli/test_cli_product_completeness.py::test_memory_status_json_reuses_doctor_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_list_json_uses_gateway_rpc tests/test_cli/test_cli_product_completeness.py::test_memory_search_and_show_use_gateway_rpcs -q`
  - Result: `14 passed`.
- Touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/main.py src/opensquilla/cli/memory_workflows.py src/opensquilla/cli/memory_presenters.py src/opensquilla/cli/reset_workflows.py src/opensquilla/cli/reset_presenters.py tests/test_cli/test_memory_cli_boundary.py tests/test_cli/test_reset_cli_boundary.py tests/test_cli/test_cli_product_completeness.py`
    result: passed.
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
    result: passed, no issues found in `126 source files`.
  - `git diff --check` result: passed.
- Full active child gate:
  - Command: `scripts/refactor_gate.sh`
  - Result: passed.
  - Gate evidence: ruff passed, mypy passed (`559 source files`), whitespace
    passed, pytest `2682 passed, 8 skipped`, gateway smoke passed, refactor gate
    complete.

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

### Integration verification evidence

- Integration merge:
  - `91a955e` merged `codex/refactor-cli-main-memory-reset-boundaries` into
    `codex/refactor-architecture`.
- Merge checks:
  - `git diff --check HEAD^ HEAD` result: passed.
  - `rg -n "/Users/<user>" docs/refactor/stages/2026-05-19-cli-main-memory-reset-boundaries.md docs/refactor/stages/2026-05-19-cli-lifecycle-cron-boundaries.md`
    returned no matches.
  - Anchored conflict marker scan
    `git grep -n "^<<<<<<<\\|^=======\\|^>>>>>>>" -- src/opensquilla/cli docs/refactor/stages/2026-05-19-cli-main-memory-reset-boundaries.md docs/refactor/stages/2026-05-19-cli-lifecycle-cron-boundaries.md`
    returned no matches.
- Full integration gate:
  - Command: `scripts/refactor_gate.sh`
  - Result: passed.
  - Gate evidence: ruff passed, mypy passed (`559 source files`), whitespace
    passed, pytest `2684 passed, 6 skipped`, gateway smoke passed, refactor gate
    complete.

## Rollback

- Revert the integration merge commit if memory CLI commands or reset command
  names, flags, RPC payloads, JSON output, terminal text, exit codes, or gateway
  smoke behavior regress.
- Keep child and worker branches for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Memory worker commit:
- `2eb0f98` (`Refactor memory CLI RPC boundary`)
- Reset worker commit:
- `26f168d` (`Refactor reset CLI boundary`)
- Active child support commits:
- `0272bef` (`Fix CLI lifecycle cron cleanup path record`)
- `88c7cee` (`Merge CLI memory boundary worker`)
- `06e44ae` (`Merge CLI reset boundary worker`)
- Child verification commit:
- `6c7b587` (`Record CLI main memory reset child verification`)
- Integration merge:
- `91a955e` (`Merge CLI main memory reset boundaries`)
- Integration record:
- `d0e5cc1` (`Record CLI main memory reset integration verification`)
- Verification evidence:
- Active child focused command: `14 passed`.
- Active child full `scripts/refactor_gate.sh`: `2682 passed, 8 skipped`,
  gateway smoke passed.
- Integration full `scripts/refactor_gate.sh`: `2684 passed, 6 skipped`,
  gateway smoke passed.
- Cleanup evidence:
- Removed `../opensquilla-refactor-active`.
- Removed `../opensquilla-refactor-agent-cli-memory`.
- Removed `../opensquilla-refactor-agent-cli-reset`.
- Ran `git worktree prune`.
- `find <workspace-parent> -maxdepth 1 -type d -name 'opensquilla-refactor-*'`
  returned only `../opensquilla-refactor-integration`.
- Final integration status was clean on `codex/refactor-architecture`.
- Residual risk:
- Low. CLI memory gateway RPC commands and top-level reset now delegate to
  workflow/presenter modules while preserving command names, flags, RPC payload
  keys, exact output text, and reset failure exit code.
- Next recommended slice:
- Continue CLI command thinning with the next independent command domain that
  still mixes Typer declarations with gateway/client/rendering behavior.
