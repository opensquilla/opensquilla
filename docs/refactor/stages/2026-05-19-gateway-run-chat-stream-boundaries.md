# Gateway Run And Chat Stream Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: gateway-run-chat-stream-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-run-chat-stream-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-gateway-run-boundary-worker`
  - `codex/refactor-chat-stream-boundary-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-gateway-run`
  - `../opensquilla-refactor-agent-chat-stream`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  merge conflict resolution, verification, records, and cleanup. Same-thread
  `spawn_agent` was rechecked and remains unavailable, so this stage uses the
  fixed external worker pool.

## Goal

Continue Phase 1 CLI boundary thinning with two independent command/runtime
surfaces:

- Move `opensquilla gateway run` startup banner, public-bind warnings, config
  assembly, subscription manager creation, and ASGI server run loop out of
  `src/opensquilla/cli/gateway_cmd.py` into focused gateway run workflow and
  presenter modules while preserving command flags, startup guidance text,
  wildcard-bind warnings, keyboard interrupt behavior, and server construction.
- Move chat streaming artifact/status presentation helpers out of
  `src/opensquilla/cli/chat_cmd.py` into a focused stream presenter module while
  preserving gateway and standalone stream behavior, artifact payload
  sanitization, task-group status text, renderer fallback behavior, cancellation
  behavior, and returned `TurnResult` fields.

## Current-state audit

- Current HEAD: `e953bfb` (`Record CLI main memory reset cleanup`).
- Worktree status: clean before creating this stage plan.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `e953bfb`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope for
    this stage; no files under that subtree are touched).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/gateway_cmd.py`
  - `src/opensquilla/cli/gateway_lifecycle_workflows.py`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/chat_presenters.py`
  - `tests/test_cli/test_gateway_cmd.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Symbols or command surfaces inspected:
  - `gateway_startup_guidance`
  - `run_gateway`
  - `_render_gateway_task_group_status`
  - `_artifact_event_payload`
  - `_artifact_status_line`
  - `_stream_response_gateway`
  - `_stream_response_turnrunner`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/cli/gateway_lifecycle_workflows.py`
  - `src/opensquilla/cli/gateway_lifecycle_presenters.py`
  - `src/opensquilla/cli/chat_gateway_*_workflows.py`
  - `src/opensquilla/cli/chat_presenters.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: the main thread re-read the Superpowers entrypoint before
    selecting this resumed stage.
- `superpowers:using-git-worktrees`:
  - Evidence: integration git status/log/worktree list were inspected; fixed
    child worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-gateway-run-chat-stream-boundaries`.
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
  - `superpowers:dispatching-parallel-agents` used: yes. Gateway run and chat
    streaming presentation are independent CLI domains with disjoint files.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slots `gateway-run` and `chat-stream`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway run workflow/presenter boundary.
  - Chat stream artifact/status presenter boundary.
- Responsibilities moving out:
  - Gateway run host/config assembly, startup banner rendering, wildcard bind
    warnings, subscription manager creation, ASGI server run loop, and keyboard
    interrupt rendering.
  - Chat stream task-group status rendering, artifact payload normalization,
    artifact status-line formatting, and renderer-vs-console artifact fallback.
- Responsibilities staying in place:
  - Typer command declarations and options.
  - Managed gateway lifecycle `start/status/stop/restart` commands and existing
    lifecycle workflow/presenter modules.
  - Chat REPL routing, slash command dispatch, message send loops, cancellation,
    approval handling, and `TurnResult` construction.
- New module/file responsibility:
  - `src/opensquilla/cli/gateway_run_workflows.py`: gateway run config/server
    workflow and keyboard interrupt wrapper.
  - `src/opensquilla/cli/gateway_run_presenters.py`: startup guidance, banner,
    public bind warnings, and stopped message.
  - `src/opensquilla/cli/chat_stream_presenters.py`: artifact payload/status
    helpers and task-group status rendering.
- Public behavior that must not change:
  - `gateway run` command flags: `--port/-p`, `--bind/-b`, `--listen`, and
    `--debug`.
  - Gateway listen precedence: `--listen` > explicit `--bind` >
    `OPENSQUILLA_LISTEN` > `OPENSQUILLA_GATEWAY_HOST` > `127.0.0.1`.
  - Gateway startup guidance text, wildcard warning text, auth warning text,
    bypass/elevated warning text, and stopped text.
  - Gateway server construction uses `GatewayConfig.load`, `SubscriptionManager`,
    and `start_gateway_server(..., run=True)`.
  - Chat streaming artifact payloads must strip session query parameters from
    download URLs and not leak `session_key`/`sessionKey` in returned artifacts.
  - Chat task-group status text must not pollute renderer buffers.
  - Gateway stream cancellation must still abort the gateway session.
- Files explicitly out of scope:
  - `src/opensquilla/cli/gateway_lifecycle.py`
  - `src/opensquilla/cli/gateway_lifecycle_workflows.py`
  - `src/opensquilla/cli/gateway_lifecycle_presenters.py`
  - Chat slash-route workflow modules other than imports needed for stream
    presenter use.
  - Gateway server internals, session runtime internals, Web UI assets, release
    docs, and dependency locks.

## Parallel worker ownership

- Worker `gateway-run` owns:
  - Modify only `src/opensquilla/cli/gateway_cmd.py`.
  - Create `src/opensquilla/cli/gateway_run_workflows.py`.
  - Create `src/opensquilla/cli/gateway_run_presenters.py`.
  - Create/modify `tests/test_cli/test_gateway_run_cli_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_gateway_cmd.py` only if
    needed for behavior preservation.
  - Update only gateway-run evidence sections in this stage record.
- Worker `chat-stream` owns:
  - Modify only the stream helper region in `src/opensquilla/cli/chat_cmd.py`:
    `_render_gateway_task_group_status`, `_artifact_event_payload`,
    `_artifact_status_line`, and the artifact/status call sites inside
    `_stream_response_gateway` and `_stream_response_turnrunner`.
  - Create `src/opensquilla/cli/chat_stream_presenters.py`.
  - Create/modify `tests/test_cli/test_chat_stream_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_chat_cmd.py` only if
    needed for behavior preservation.
  - Update only chat-stream evidence sections in this stage record.
- Main thread owns:
  - Stage plan and worker prompts.
  - Worker review, child merges, focused batch verification, full gates,
    integration merge, completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers'
changes and must not revert unrelated edits.

## TDD red/green

- Failing test commands:
  - Gateway-run worker:
    `uv run --extra dev pytest tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_gateway_cmd.py::test_gateway_startup_guidance_shows_operator_next_steps tests/test_cli/test_gateway_cmd.py::test_gateway_start_with_wildcard_listen_keeps_bind_and_reports_probe_host -q`
  - Chat-stream worker:
    `uv run --extra dev pytest tests/test_cli/test_chat_stream_boundary.py tests/test_cli/test_chat_cmd.py::test_gateway_stream_renders_task_group_status_without_buffer_pollution tests/test_cli/test_chat_cmd.py::test_gateway_stream_collects_artifact_events tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts -q`
- Expected red failures:
  - New boundary modules do not exist yet.
  - `gateway_cmd.run_gateway` still owns config/server workflow and console
    rendering directly.
  - `chat_cmd.py` still owns stream artifact/status formatting directly.
- Behavior compatibility coverage:
  - Existing gateway command lifecycle tests listed above.
  - Existing gateway/standalone stream artifact/status tests listed above.
- Module-batch implementation:
  - Keep Typer command declarations in command modules.
  - Delegate gateway run workflow to a workflow module and render text through a
    presenter module.
  - Delegate chat stream artifact/status helpers to a presenter module while
    preserving compatibility wrappers if current tests or imports need them.
- Focused green command after both workers are merged:
  - `uv run --extra dev pytest tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_chat_stream_boundary.py tests/test_cli/test_gateway_cmd.py::test_gateway_startup_guidance_shows_operator_next_steps tests/test_cli/test_gateway_cmd.py::test_gateway_start_with_wildcard_listen_keeps_bind_and_reports_probe_host tests/test_cli/test_chat_cmd.py::test_gateway_stream_renders_task_group_status_without_buffer_pollution tests/test_cli/test_chat_cmd.py::test_gateway_stream_collects_artifact_events tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_run_workflows.py src/opensquilla/cli/gateway_run_presenters.py src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_stream_presenters.py tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_chat_stream_boundary.py tests/test_cli/test_gateway_cmd.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/cli/gateway_run_workflows.py`
  - `src/opensquilla/cli/gateway_run_presenters.py`
  - `src/opensquilla/cli/chat_stream_presenters.py`
  - `tests/test_cli/test_gateway_run_cli_boundary.py`
  - `tests/test_cli/test_chat_stream_boundary.py`
- Modify:
  - `src/opensquilla/cli/gateway_cmd.py`
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_gateway_cmd.py` only if needed.
  - `tests/test_cli/test_chat_cmd.py` only if needed.
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status.
- [x] Create fixed active worktree on `codex/refactor-gateway-run-chat-stream-boundaries`.
- [x] Write this stage plan before production edits.
- [ ] Commit this stage plan as the worker base.
- [ ] Launch two external workers with `scripts/refactor_external_agent.sh`.
- [ ] Gateway-run worker writes RED boundary tests and records RED output.
- [ ] Chat-stream worker writes RED boundary tests and records RED output.
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
      `../opensquilla-refactor-agent-gateway-run`, and
      `../opensquilla-refactor-agent-chat-stream`; run `git worktree prune`;
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

- Revert the integration merge commit if gateway run text, gateway listen
  precedence, gateway server startup, chat artifact payload sanitization,
  task-group status rendering, stream cancellation, or returned artifacts
  regress.
- Keep child and worker branches for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Gateway-run evidence

- Superpowers used: `superpowers:using-superpowers`, `superpowers:using-git-worktrees`,
  `superpowers:writing-plans`, `superpowers:test-driven-development`, and
  `superpowers:verification-before-completion`.
- RED command:
  `uv run --extra dev pytest tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_gateway_cmd.py::test_gateway_startup_guidance_shows_operator_next_steps tests/test_cli/test_gateway_cmd.py::test_gateway_start_with_wildcard_listen_keeps_bind_and_reports_probe_host -q`
  - Expected failures: new workflow/presenter modules missing and `run_gateway`
    still owning banner/config/server logic.
- GREEN command:
  `uv run --extra dev pytest tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_gateway_cmd.py::test_gateway_startup_guidance_shows_operator_next_steps tests/test_cli/test_gateway_cmd.py::test_gateway_start_with_wildcard_listen_keeps_bind_and_reports_probe_host -q`
  - Result: `9 passed in 0.66s`
- Touched checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/gateway_cmd.py src/opensquilla/cli/gateway_run_workflows.py src/opensquilla/cli/gateway_run_presenters.py tests/test_cli/test_gateway_run_cli_boundary.py tests/test_cli/test_gateway_cmd.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`
- Full gate:
  - `scripts/refactor_gate.sh`
  - Result: passed; `ruff`, `mypy`, `whitespace`, `pytest`, and gateway smoke all completed successfully.

## Completion record

- Gateway-run worker commit:
- Chat-stream worker commit:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Cleanup evidence:
- Residual risk:
- Next recommended slice:
