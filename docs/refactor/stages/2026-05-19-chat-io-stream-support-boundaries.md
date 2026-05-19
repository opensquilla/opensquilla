# Chat IO And Stream Support Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: chat-io-stream-support-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-chat-io-stream-support-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-chat-stream-support-worker`
  - `codex/refactor-chat-input-builders-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-chat-stream-support`
  - `../opensquilla-refactor-agent-chat-input-builders`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  merge conflict resolution, verification, records, and cleanup. Same-thread
  `spawn_agent` was rechecked and remains unavailable, so this stage uses the
  fixed external worker pool.

## Goal

Continue Phase 1 CLI boundary thinning by shrinking the largest remaining CLI
command file, `src/opensquilla/cli/chat_cmd.py`, through two independent support
boundary moves:

- Move CLI stream timeout/error wrapping helpers out of `chat_cmd.py` into a
  focused stream support module while preserving heartbeat wrapping, idle
  timeout behavior, timeout terminal reply text, standalone stream behavior, and
  artifact collection.
- Move chat image/path/file prompt builder compatibility wrappers and local
  gateway detection out of `chat_cmd.py` into a focused input builder module
  while preserving `/image`, `/path`, `/file`, upload behavior, local-gateway
  checks, base64 status text, and legacy private imports used by existing tests.

## Current-state audit

- Current HEAD: `f324758` (`Record gateway run chat stream cleanup`).
- Worktree status: clean before creating this stage plan.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `f324758`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope for
    this stage; no files under that subtree are touched).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/chat_cmd.py`
  - `src/opensquilla/cli/attachments.py`
  - `src/opensquilla/cli/chat_gateway_file_workflows.py`
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `src/opensquilla/cli/chat_gateway_image_workflows.py`
  - `src/opensquilla/cli/chat_stream_presenters.py`
  - `tests/test_cli/test_chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py`
  - `tests/test_cli/test_chat_path_command.py`
  - `tests/test_cli/test_chat_stream_boundary.py`
- Symbols or command surfaces inspected:
  - `_turn_stream_error_message`
  - `_timeout_exception_message`
  - `_optional_positive_config_float`
  - `_wrap_cli_turn_stream`
  - `_image_prompt_from_command`
  - `_image_prompt_and_attachments`
  - `_gateway_client_is_local`
  - `_parse_path_command`
  - `_path_strategy_hint`
  - `_path_prompt_and_attachments`
  - `_file_prompt_and_attachments`
  - `_async_file_prompt_and_attachments`
  - `_stream_response_turnrunner`
  - `_handle_image_command_turnrunner`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/cli/chat_stream_presenters.py`
  - `src/opensquilla/cli/chat_gateway_file_workflows.py`
  - `src/opensquilla/cli/chat_gateway_path_workflows.py`
  - `src/opensquilla/cli/chat_gateway_image_workflows.py`
  - `src/opensquilla/cli/attachments.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: the main thread re-read the Superpowers entrypoint before
    selecting this resumed stage.
- `superpowers:using-git-worktrees`:
  - Evidence: integration git status/log/worktree state were inspected; fixed
    child worktree `../opensquilla-refactor-active` was created on
    `codex/refactor-chat-io-stream-support-boundaries`.
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
  - `superpowers:dispatching-parallel-agents` used: yes. Stream support and
    input builder wrappers are independent chat support domains with disjoint
    new modules and focused tests.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slots `chat-stream-support` and `chat-input-builders`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Chat CLI stream support boundary.
  - Chat CLI input builder boundary.
- Responsibilities moving out:
  - CLI stream timeout/error conversion and heartbeat wrapper configuration.
  - Image/path/file prompt-builder wrappers and local gateway detection.
- Responsibilities staying in place:
  - Typer `chat` command declaration and REPL orchestration.
  - Gateway and standalone slash route dispatch.
  - Approval, forget/elevated commands, transcript rendering, and stream
    artifact/status presentation already owned by other modules.
- New module/file responsibility:
  - `src/opensquilla/cli/chat_stream_support.py`: timeout/error terminal reply
    conversion, positive config float resolution, and CLI turn stream wrapping.
  - `src/opensquilla/cli/chat_input_builders.py`: image/path/file prompt
    builder wrappers and local gateway detection.
- Public behavior that must not change:
  - Heartbeat wrapper phase/message and idle timeout defaults.
  - Timeout terminal reply text for stream timeout events and exceptions.
  - Standalone stream artifact collection and returned `TurnResult` fields.
  - `/image`, `/path`, and `/file` prompt/attachment payloads.
  - Base64 image status output.
  - Local gateway detection semantics and remote-gateway path error behavior.
  - Legacy private imports from `opensquilla.cli.chat_cmd` used by tests and
    downstream code.
- Files explicitly out of scope:
  - `src/opensquilla/cli/attachments.py`
  - Gateway/standalone slash route modules other than imports needed for moved
    helper use.
  - Gateway client internals, session runtime internals, Web UI assets, release
    docs, and dependency locks.

## Parallel worker ownership

- Worker `chat-stream-support` owns:
  - Modify only stream-support helper imports/aliases and call sites in
    `src/opensquilla/cli/chat_cmd.py`.
  - Create `src/opensquilla/cli/chat_stream_support.py`.
  - Create/modify `tests/test_cli/test_chat_stream_support_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_chat_cmd.py` only if
    needed for behavior preservation.
  - Update only chat-stream-support evidence sections in this stage record.
- Worker `chat-input-builders` owns:
  - Modify only input-builder helper imports/aliases and call sites in
    `src/opensquilla/cli/chat_cmd.py`.
  - Create `src/opensquilla/cli/chat_input_builders.py`.
  - Create/modify `tests/test_cli/test_chat_input_builders_boundary.py`.
  - May add focused assertions to `tests/test_cli/test_chat_file_command.py`,
    `tests/test_cli/test_chat_path_command.py`, or `tests/test_cli/test_chat_cmd.py`
    only if needed for behavior preservation.
  - Update only chat-input-builders evidence sections in this stage record.
- Main thread owns:
  - Stage plan and worker prompts.
  - Worker review, child merges, focused batch verification, full gates,
    integration merge, completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers'
changes and must not revert unrelated edits.

## TDD red/green

- Failing test commands:
  - Chat-stream-support worker:
    `uv run --extra dev pytest tests/test_cli/test_chat_stream_support_boundary.py tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_uses_heartbeat_wrapper tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts -q`
  - Chat-input-builders worker:
    `uv run --extra dev pytest tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py -q`
- Expected red failures:
  - New boundary modules do not exist yet.
  - `chat_cmd.py` still owns the helper bodies directly.
- Behavior compatibility coverage:
  - Existing stream wrapper/artifact tests listed above.
  - Existing file/path command tests listed above.
  - Existing gateway image/path/file route tests in `tests/test_cli/test_chat_cmd.py`.
- Module-batch implementation:
  - Keep compatibility aliases in `chat_cmd.py` for existing private imports.
  - Move helper bodies into the new modules without changing return shapes,
    printed text, or exceptions.
  - Add boundary tests that assert the new modules own the helpers and
    `chat_cmd.py` no longer defines the moved helper function bodies.
- Focused green command after both workers are merged:
  - `uv run --extra dev pytest tests/test_cli/test_chat_stream_support_boundary.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_uses_heartbeat_wrapper tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts tests/test_cli/test_chat_cmd.py::test_gateway_image_route_executor_delegates_known_route tests/test_cli/test_chat_cmd.py::test_gateway_io_route_executor_delegates_known_routes -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_stream_support.py src/opensquilla/cli/chat_input_builders.py tests/test_cli/test_chat_stream_support_boundary.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_cmd.py`
  - `uv run --extra dev mypy src/opensquilla/cli --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/cli/chat_stream_support.py`
  - `src/opensquilla/cli/chat_input_builders.py`
  - `tests/test_cli/test_chat_stream_support_boundary.py`
  - `tests/test_cli/test_chat_input_builders_boundary.py`
- Modify:
  - `src/opensquilla/cli/chat_cmd.py`
  - `tests/test_cli/test_chat_file_command.py` only if needed.
  - `tests/test_cli/test_chat_path_command.py` only if needed.
  - `tests/test_cli/test_chat_cmd.py` only if needed.
- Documentation:
  - This stage record.

## Chat-stream-support worker evidence

- Worker branch: `codex/refactor-chat-stream-support-worker`.
- Worker worktree: `../opensquilla-refactor-agent-chat-stream-support`.
- Worker HEAD before edits: `e04a349` (`Plan chat IO and stream support boundaries`).
- RED command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_stream_support_boundary.py tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_uses_heartbeat_wrapper tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts -q`
  - Result: `9 failed, 2 passed`; expected failures reported
    `chat stream support helpers were not extracted` and missing
    `src/opensquilla/cli/chat_stream_support.py`.
- GREEN command:
  - `uv run --extra dev pytest tests/test_cli/test_chat_stream_support_boundary.py tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_uses_heartbeat_wrapper tests/test_cli/test_chat_cmd.py::test_standalone_turnrunner_stream_collects_artifacts -q`
  - Result: `11 passed in 0.70s`.
- Touched-file ruff:
  - `uv run --extra dev ruff check src/opensquilla/cli/chat_cmd.py src/opensquilla/cli/chat_stream_support.py tests/test_cli/test_chat_stream_support_boundary.py`
  - Result: `All checks passed!`.
- Whitespace:
  - `git diff --check`
  - Result: passed.
- Full worker gate:
  - `scripts/refactor_gate.sh`
  - Result: ruff passed; mypy passed with no issues in 563 source files;
    pytest `2704 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop
    completed; `Refactor gate complete.`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status.
- [x] Create fixed active worktree on `codex/refactor-chat-io-stream-support-boundaries`.
- [x] Write this stage plan before production edits.
- [ ] Commit this stage plan as the worker base.
- [ ] Launch two external workers with `scripts/refactor_external_agent.sh`.
- [ ] Chat-stream-support worker writes RED boundary tests and records RED output.
- [ ] Chat-input-builders worker writes RED boundary tests and records RED output.
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
      `../opensquilla-refactor-agent-chat-stream-support`, and
      `../opensquilla-refactor-agent-chat-input-builders`; run
      `git worktree prune`; verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if chat stream timeout/error text,
  heartbeat wrapping, artifact collection, image/path/file prompt construction,
  local gateway detection, upload behavior, or compatibility imports regress.
- Keep child and worker branches for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Chat-stream-support worker commit:
- Chat-input-builders worker commit:
- Active child worker merges:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
- Cleanup evidence:
- Residual risk:
- Next recommended slice:
