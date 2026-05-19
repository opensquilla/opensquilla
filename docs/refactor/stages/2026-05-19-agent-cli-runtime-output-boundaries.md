# Agent CLI Runtime And Output Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: agent-cli-runtime-output-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-agent-cli-runtime-output-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-agent-runtime-config-worker`
  - `codex/refactor-agent-output-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-agent-runtime-config`
  - `../opensquilla-refactor-agent-agent-output`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  merge conflict resolution, verification, records, and cleanup. Same-thread
  `spawn_agent` was rechecked and remains unavailable, so this stage uses the
  fixed external worker pool.

## Goal

Continue Phase 1 CLI boundary thinning by reducing
`src/opensquilla/cli/agent_cmd.py` into two focused support boundaries while
preserving the `opensquilla agent` one-shot command behavior:

- Move agent runtime configuration helpers out of `agent_cmd.py` into a focused
  runtime config module while preserving model resolution, workspace overrides,
  thinking overrides, permission profile validation, workspace strict parsing,
  environment defaults, and `ToolContext` behavior.
- Move result/public artifact/usage/transcript/no-provider output helpers out of
  `agent_cmd.py` into a focused output module while preserving JSON payloads,
  text output, generated-file lines, transcript/usage file writes, sanitized
  artifacts, and the no-provider diagnostic panel.

## Current-state audit

- Current HEAD: `bd26ed7` (`Record chat IO stream support cleanup`).
- Worktree status: clean before creating this stage plan.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `bd26ed7`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope for
    this stage; no files under that subtree are touched).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/agent_cmd.py`
  - `tests/test_cli/test_agent_cmd.py`
  - `tests/test_agent_cmd_no_key.py`
- Symbols or command surfaces inspected:
  - `AgentRunResult`
  - `run_agent_once`
  - `run_agent_command`
  - `_resolve_permissions_profile`
  - `_with_agent_workspace_config`
  - `_with_agent_thinking_config`
  - `_with_agent_model_config`
  - `_agent_model_from_config`
  - `_resolve_workspace_strict`
  - `_parse_bool`
  - `_public_artifacts`
  - `_usage_from_done`
  - `_to_benchmark_transcript`
  - `_message_event`
  - `_entry_timestamp`
  - `_to_transcript_usage`
  - `_write_jsonl`
  - `_write_json`
  - `_print_no_provider_error`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/cli/chat_input_builders.py`
  - `src/opensquilla/cli/chat_stream_support.py`
  - `src/opensquilla/cli/*_workflows.py`
  - `src/opensquilla/cli/*_presenters.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: the main thread re-read the Superpowers entrypoint in this resumed
    run before selecting module batches.
- `superpowers:using-git-worktrees`:
  - Evidence: integration git status/log/worktree state were inspected; fixed
    child worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-agent-cli-runtime-output-boundaries`.
- `superpowers:writing-plans`:
  - Evidence: this stage record was written before production edits and before
    launching workers.
- `superpowers:test-driven-development`:
  - Evidence: both workers must add RED boundary tests and record the expected
    failure before moving production logic.
- `superpowers:verification-before-completion`:
  - Evidence: focused tests, touched-file checks, child
    `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, merge
    hashes, and cleanup evidence are required before claiming this stage
    complete.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes. Runtime config helpers
    and output helpers are independent support domains with disjoint new modules
    and tests.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slots `agent-runtime-config` and `agent-output`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Agent CLI runtime config boundary.
  - Agent CLI output/export boundary.
- Responsibilities moving out:
  - Permissions profile normalization, config cloning overrides, agent model
    lookup, workspace strict parsing, and boolean parsing.
  - Agent result dataclass, public artifact sanitization, usage extraction,
    benchmark transcript conversion, file writers, and no-provider error
    presenter.
- Responsibilities staying in place:
  - Typer command declaration and option list.
  - `run_agent_once` orchestration and TurnRunner wiring.
  - `run_agent_command` top-level command shell.
- New module/file responsibility:
  - `src/opensquilla/cli/agent_runtime_config.py`: runtime config and option
    normalization helpers for agent one-shot execution.
  - `src/opensquilla/cli/agent_outputs.py`: result/output/transcript helper
    functions and no-provider presentation.
- Public behavior that must not change:
  - `run_agent_once` model/workspace/thinking/permissions behavior.
  - Default unattended interaction contract and explicit interactive opt-in.
  - CLI JSON output shape, generated file text, sanitized artifacts, transcript
    JSONL shape, usage JSON shape, and no-provider diagnostic text.
  - Legacy imports from `opensquilla.cli.agent_cmd` used by tests or downstream
    code.
- Files explicitly out of scope:
  - Engine runtime, Gateway service construction, provider selection internals,
    attachment builder internals, Web UI assets, release docs, and dependency
    locks.

## Parallel worker ownership

- Worker `agent-runtime-config` owns:
  - Modify only runtime-config helper imports/aliases and call sites in
    `src/opensquilla/cli/agent_cmd.py`.
  - Create `src/opensquilla/cli/agent_runtime_config.py`.
  - Create/modify `tests/test_cli/test_agent_runtime_config_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_agent_cmd.py` only if
    needed for behavior preservation.
  - Update only agent-runtime-config evidence sections in this stage record.
- Worker `agent-output` owns:
  - Modify only output/result helper imports/aliases and call sites in
    `src/opensquilla/cli/agent_cmd.py`.
  - Create `src/opensquilla/cli/agent_outputs.py`.
  - Create/modify `tests/test_cli/test_agent_output_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_agent_cmd.py` or
    `tests/test_agent_cmd_no_key.py` only if needed for behavior preservation.
  - Update only agent-output evidence sections in this stage record.
- Main thread owns:
  - Stage plan and worker prompts.
  - Worker review, child merges, focused batch verification, full gates,
    integration merge, completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers'
changes and must not revert unrelated edits.

## TDD red/green

- Failing test commands:
  - Agent-runtime-config worker:
    `uv run --extra dev pytest tests/test_cli/test_agent_runtime_config_boundary.py tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_agent_registry_model_when_model_not_explicit tests/test_cli/test_agent_cmd.py::test_run_agent_once_explicit_model_overrides_agent_registry_model tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_configured_agent_workspace_without_global_workspace tests/test_cli/test_agent_cmd.py::test_run_agent_once_passes_bypass_permissions_to_tool_context tests/test_cli/test_agent_cmd.py::test_run_agent_once_uses_permissions_environment_default tests/test_cli/test_agent_cmd.py::test_run_agent_once_rejects_invalid_permissions -q`
  - Agent-output worker:
    `uv run --extra dev pytest tests/test_cli/test_agent_output_boundary.py tests/test_cli/test_agent_cmd.py::test_run_agent_command_json_includes_artifacts tests/test_cli/test_agent_cmd.py::test_run_agent_once_collects_artifact_events tests/test_agent_cmd_no_key.py -q`
- Expected red failures:
  - New boundary modules do not exist yet.
  - `agent_cmd.py` still owns the helper bodies directly.
- Behavior compatibility coverage:
  - Existing model/workspace/permissions tests listed above.
  - Existing artifact JSON and no-provider tests listed above.
- Module-batch implementation:
  - Keep compatibility aliases in `agent_cmd.py` for existing private imports.
  - Move helper bodies into the new modules without changing return shapes,
    text, exceptions, file formats, or JSON payloads.
  - Add boundary tests that assert the new modules own the helpers and
    `agent_cmd.py` no longer defines the moved helper function/class bodies.
- Focused green command after both workers are merged:
  - `uv run --extra dev pytest tests/test_cli/test_agent_runtime_config_boundary.py tests/test_cli/test_agent_output_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/agent_cmd.py src/opensquilla/cli/agent_runtime_config.py src/opensquilla/cli/agent_outputs.py tests/test_cli/test_agent_runtime_config_boundary.py tests/test_cli/test_agent_output_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/cli/agent_runtime_config.py`
  - `src/opensquilla/cli/agent_outputs.py`
  - `tests/test_cli/test_agent_runtime_config_boundary.py`
  - `tests/test_cli/test_agent_output_boundary.py`
- Modify:
  - `src/opensquilla/cli/agent_cmd.py`
  - `tests/test_cli/test_agent_cmd.py` only if needed.
  - `tests/test_agent_cmd_no_key.py` only if needed.
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status.
- [x] Create fixed active worktree on `codex/refactor-agent-cli-runtime-output-boundaries`.
- [x] Write this stage plan before production edits.
- [ ] Commit this stage plan as the worker base.
- [ ] Launch two external workers with `scripts/refactor_external_agent.sh`.
- [ ] Agent-runtime-config worker writes RED boundary tests and records RED output.
- [ ] Agent-output worker writes RED boundary tests and records RED output.
- [ ] Workers implement their disjoint boundaries and record GREEN/check/gate evidence.
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
      `../opensquilla-refactor-agent-agent-runtime-config`, and
      `../opensquilla-refactor-agent-agent-output`; run `git worktree prune`;
      verify no extra refactor worktree directories remain beyond
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

- Revert the integration merge commit if agent model/workspace/permission
  behavior, JSON/text output, no-provider diagnostics, transcript/usage files,
  or artifact sanitization regress.
- Keep child and worker branches for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Agent-runtime-config worker commit:
- Agent-output worker commit:
- Active child worker merges:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Cleanup evidence:
- Residual risk:
- Next recommended slice:
