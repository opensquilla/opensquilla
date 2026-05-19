# Agent CLI Command Runtime Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: agent-cli-command-runtime-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-agent-cli-command-runtime-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-agent-run-runtime-worker`
  - `codex/refactor-agent-command-output-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-run-runtime`
  - `../opensquilla-refactor-agent-command-output`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  facade integration, verification, merge records, and cleanup.

## Goal

Continue Phase 1 CLI boundary thinning by turning
`src/opensquilla/cli/agent_cmd.py` into a command facade over two focused
agent-command modules while preserving all `opensquilla agent run` behavior:
single-shot runtime execution, session/key/workspace config, attachment ingest,
transcript/usage output, JSON/plain rendering, no-provider exit behavior, and
public compatibility imports.

## Current-state audit

- Current HEAD before child creation: `7847410` (`Record CLI attachments input
  integration cleanup`).
- Worktree status: clean before creating this stage.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `7847410`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/agent_cmd.py`
  - `src/opensquilla/cli/agent_runtime_config.py`
  - `src/opensquilla/cli/agent_outputs.py`
  - `tests/test_cli/test_agent_cmd.py`
  - `tests/test_agent_cmd_no_key.py`
  - `tests/test_cli/test_agent_runtime_config_boundary.py`
  - `tests/test_cli/test_agent_output_boundary.py`
- Symbols or command surfaces inspected:
  - `run_agent_once`
  - `run_agent_command`
  - `AgentRunResult`
  - `_public_artifacts`
  - `_usage_from_done`
  - `_to_transcript_usage`
  - `_to_benchmark_transcript`
  - `_write_json`
  - `_write_jsonl`
  - `_resolve_permissions_profile`
  - `_resolve_workspace_strict`
  - `_with_agent_workspace_config`
  - `_with_agent_model_config`
  - `_with_agent_thinking_config`
  - `_agent_model_from_config`
- Existing boundary pattern this stage follows:
  - `agent_runtime_config.py`
  - `agent_outputs.py`
  - `attachment_files.py`
  - `attachment_paths.py`
  - compatibility-facade tests in `tests/test_cli/test_agent_*_boundary.py`.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: read this turn before continuing work and used it to select
    stage-specific skills rather than relying on the top-level refactor plan.
- `superpowers:using-git-worktrees`:
  - Evidence: inspected integration state, ran preflight, verified no active
    refactor child worktree remained, then created
    `../opensquilla-refactor-active` on
    `codex/refactor-agent-cli-command-runtime-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions and wrote this stage plan before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: worker prompts require RED boundary tests before new modules, and
    the main thread will add a RED facade ownership test before editing
    `agent_cmd.py`.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: runtime execution and result rendering are independent domains.
    Workers create disjoint modules and tests; main thread alone edits the
    shared `agent_cmd.py` facade after both workers merge.
- `superpowers:subagent-driven-development`:
  - Evidence: same-thread `spawn_agent` was rechecked after closing completed
    agents and returned `SPAWN_AGENT_AVAILABLE`; this stage uses fresh workers
    with explicit branch/worktree ownership.
- `superpowers:verification-before-completion`:
  - Evidence: focused runtime/output/facade tests, touched-file ruff/mypy,
    child `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`,
    merge hashes, and cleanup evidence are required before claiming completion.
- Parallelism decision:
  - Same-thread `spawn_agent` probe: available after closing completed agents.
  - External worker fallback: not needed at stage start; if same-thread workers
    fail or become unavailable, use `scripts/refactor_external_agent.sh`.
- Historical evidence note:
  - Do not claim a prior stage used a Superpowers checkpoint unless the stage
    record or current command log contains evidence. Record gaps explicitly.

## Boundary Decision

- Module batch:
  - Agent run runtime worker: single-shot agent execution runtime.
  - Agent command output worker: command payload and output rendering.
  - Main thread: `agent_cmd.py` compatibility facade.
- Responsibilities moving out:
  - `src/opensquilla/cli/agent_run_runtime.py` owns `run_agent_once`, including
    service construction, per-agent workspace resolution, session creation,
    attachment path expansion and ingest, transcript persistence, route
    envelope/tool context construction, TurnRunner event collection,
    transcript/usage writes, and `AgentRunResult` construction.
  - `src/opensquilla/cli/agent_command_output.py` owns public-artifact
    normalization for command output, JSON payload construction, plain text
    result rendering, and no-provider exit behavior integration points.
- Responsibilities staying in place:
  - `agent_cmd.py` keeps the Typer command signature and imports/re-exports
    compatibility names from `agent_outputs.py`, `agent_runtime_config.py`, and
    the new modules.
  - `agent_runtime_config.py` stays the config-helper owner.
  - `agent_outputs.py` stays the dataclass/transcript/usage/artifact owner.
  - `attachments.py` stays the compatibility facade for file path expansion.
- Public behavior that must not change:
  - `run_agent_once` import path from `opensquilla.cli.agent_cmd`.
  - `AgentRunResult` import path from `opensquilla.cli.agent_cmd`.
  - Agent registry model default and explicit model override.
  - Per-agent workspace resolution and `workspace_strict`.
  - Memory service wiring through `extra_agent_ids`.
  - `max_iterations`, `permissions`, unattended/interactive mode, and
    no-memory-capture forwarding.
  - Inline attachments and repeated `--file` path behavior.
  - Transcript and usage JSON output files.
  - JSON output shape and artifact URL redaction.
  - Plain output text, generated-file lines, and no-provider exit code/output.
- Files explicitly out of scope:
  - Gateway runtime, engine runtime, provider, session, and artifact store
    internals.
  - `src/opensquilla/cli/main.py`, except tests may continue verifying its
    delegation to `run_agent_command`.
  - Chat command modules.

## TDD Red/Green

- Runtime worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_agent_run_runtime_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.agent_run_runtime` does not exist.
- Runtime worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_agent_run_runtime_boundary.py tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_agent_registry_model_when_model_not_explicit tests/test_cli/test_agent_cmd.py::test_run_agent_once_collects_artifact_events tests/test_cli/test_agent_cmd.py::test_run_agent_once_explicit_model_overrides_agent_registry_model tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_configured_agent_workspace_without_global_workspace tests/test_cli/test_agent_cmd.py::test_run_agent_once_wires_memory_services_into_turnrunner tests/test_cli/test_agent_cmd.py::test_run_agent_once_forwards_max_iterations tests/test_cli/test_agent_cmd.py::test_run_agent_once_defaults_to_unattended_interaction_contract tests/test_cli/test_agent_cmd.py::test_run_agent_once_passes_bypass_permissions_to_tool_context tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_permissions_environment_default tests/test_cli/test_agent_cmd.py::test_run_agent_once_rejects_invalid_permissions tests/test_cli/test_agent_cmd.py::test_run_agent_once_can_opt_into_interactive_single_shot tests/test_cli/test_agent_cmd.py::test_run_agent_once_rejects_invalid_max_iterations tests/test_cli/test_agent_cmd.py::test_run_agent_once_forwards_inline_attachments tests/test_cli/test_agent_cmd.py::test_run_agent_once_builds_multiple_file_attachments tests/test_cli/test_agent_cmd.py::test_run_agent_once_rejects_agent_file_requiring_upload_bridge tests/test_cli/test_agent_cmd.py::test_run_agent_once_rejects_large_text_file_without_staging -q`
- Output worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_agent_command_output_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.agent_command_output` does not exist.
- Output worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_agent_command_output_boundary.py tests/test_cli/test_agent_cmd.py::test_run_agent_command_json_includes_artifacts tests/test_agent_cmd_no_key.py -q`
- Main-thread facade RED:
  - `uv run --extra dev pytest tests/test_cli/test_agent_cmd_facade_boundary.py -q`
  - Expected: failure showing `agent_cmd.py` still owns moved helper bodies
    instead of importing `run_agent_once` and output helpers from the new
    modules.
- Main-thread facade GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_agent_run_runtime_boundary.py tests/test_cli/test_agent_command_output_boundary.py tests/test_cli/test_agent_cmd_facade_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py tests/test_cli/test_agent_runtime_config_boundary.py tests/test_cli/test_agent_output_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/agent_cmd.py src/opensquilla/cli/agent_run_runtime.py src/opensquilla/cli/agent_command_output.py tests/test_cli/test_agent_run_runtime_boundary.py tests/test_cli/test_agent_command_output_boundary.py tests/test_cli/test_agent_cmd_facade_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py`
  - `uv run --extra dev mypy src/opensquilla/cli/agent_cmd.py src/opensquilla/cli/agent_run_runtime.py src/opensquilla/cli/agent_command_output.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/cli/agent_run_runtime.py`
  - `src/opensquilla/cli/agent_command_output.py`
  - `tests/test_cli/test_agent_run_runtime_boundary.py`
  - `tests/test_cli/test_agent_command_output_boundary.py`
  - `tests/test_cli/test_agent_cmd_facade_boundary.py`
- Modify:
  - `src/opensquilla/cli/agent_cmd.py`
- Test:
  - `tests/test_cli/test_agent_cmd.py`
  - `tests/test_agent_cmd_no_key.py`
  - `tests/test_cli/test_agent_runtime_config_boundary.py`
  - `tests/test_cli/test_agent_output_boundary.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status after closing completed agents.
- [x] Create fixed active worktree on
      `codex/refactor-agent-cli-command-runtime-boundaries`.
- [x] Write this stage plan before production edits.
- [ ] Commit this stage plan as the worker base.
- [ ] Dispatch two same-thread workers with explicit worktree/branch ownership.
- [ ] Runtime worker writes RED boundary tests and records RED output.
- [ ] Output worker writes RED boundary tests and records RED output.
- [ ] Runtime worker implements boundary and records GREEN/check evidence.
- [ ] Output worker implements boundary and records GREEN/check evidence.
- [ ] Main thread reviews both worker diffs for behavior compatibility and ownership.
- [ ] Merge both worker branches into the active child.
- [ ] Main thread writes and verifies facade RED/GREEN.
- [ ] Run focused green command and touched-file checks.
- [ ] Run `scripts/refactor_gate.sh` in the active child worktree.
- [ ] Commit child verification/stage record update.
- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, residual risk, and next slice.
- [ ] Remove temporary child/worker worktrees; run `git worktree prune`; verify
      no extra refactor worktree directories remain beyond integration.

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

- Revert the integration merge commit if `opensquilla agent run`,
  `run_agent_once`, JSON/plain output, artifact redaction, no-provider
  handling, attachment ingest, session persistence, or transcript/usage writes
  regress.
- Keep child and worker branches for diagnosis until a replacement slice is
  ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Runtime worker commit:
- Output worker commit:
- Active child worker merges:
- Main facade commit:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Cleanup evidence:
- Residual risk:
- Next recommended slice:
