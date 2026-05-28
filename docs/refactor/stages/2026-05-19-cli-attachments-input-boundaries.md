# CLI Attachments Input Boundaries

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for executable behavior and
> `superpowers:verification-before-completion` before claiming completion.
> This stage must record concrete Superpowers evidence for every worker slice.

## Stage

- Name: cli-attachments-input-boundaries
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-cli-attachments-input-boundaries`
- Child worktree: `../opensquilla-refactor-active`
- Worker branches:
  - `codex/refactor-cli-attachment-files-worker`
  - `codex/refactor-cli-attachment-paths-worker`
- Worker worktrees:
  - `../opensquilla-refactor-agent-cli-attachment-files`
  - `../opensquilla-refactor-agent-cli-attachment-paths`
- Owner: main Codex thread coordinates architecture, worker prompts, review,
  facade integration, verification, records, and cleanup. Same-thread
  `spawn_agent` was rechecked and remains unavailable, so this stage uses the
  fixed external worker pool.

## Goal

Continue Phase 1 CLI boundary thinning by turning
`src/opensquilla/cli/attachments.py` into a compatibility facade over two
focused input-helper modules while preserving every `/file`, `/image`, and
`/path` behavior used by chat and one-shot agent commands.

## Current-state audit

- Current HEAD before child creation: `2b56be2` (`Record agent CLI runtime
  output integration cleanup`).
- Worktree status: clean before creating this stage.
- Preflight:
  - `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
  - Result: branch `codex/refactor-architecture`, head `2b56be2`, clean status,
    required Superpowers checkpoints listed, preflight complete.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (out of scope).
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/cli/attachments.py`
  - `src/opensquilla/cli/chat_input_builders.py`
  - `tests/test_cli/test_chat_file_command.py`
  - `tests/test_cli/test_chat_path_command.py`
  - `tests/test_cli/test_chat_input_builders_boundary.py`
- Symbols inspected:
  - File/input helpers: `attachment_size_limit_for_mime`, `mime_for_path`,
    `_ensure_existing_file`, `_inline_attachment`, `_check_size_policy`,
    `build_file_attachment`, `build_file_attachment_async`,
    `file_prompt_and_attachments`, `async_file_prompt_and_attachments`,
    `attachments_from_paths`, `image_prompt_from_command`,
    `image_prompt_and_attachments`.
  - Path helpers: `parse_path_command`, `path_strategy_hint`,
    `path_prompt_and_attachments`, and the `PATH_*` extension constants.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: re-read this turn before starting this new substage.
- `superpowers:using-git-worktrees`:
  - Evidence: integration state was inspected, preflight passed, and a reusable
    child worktree was created at `../opensquilla-refactor-active`.
- `superpowers:writing-plans`:
  - Evidence: this stage record is written before any production code changes.
- `superpowers:test-driven-development`:
  - Evidence: both workers must add RED boundary tests before their new modules;
    the main thread then adds a RED facade ownership test before editing
    `attachments.py`.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: file attachment helpers and path prompt helpers are independent
    domains. Workers create disjoint new modules and tests; main thread alone
    owns the shared `attachments.py` facade edit after both workers merge.
- `superpowers:verification-before-completion`:
  - Evidence: focused file/path/chat-input tests, touched-file ruff/mypy,
    child `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`,
    merge hashes, and cleanup evidence are required before claiming completion.

## Boundary decision

- `src/opensquilla/cli/attachment_files.py` owns:
  - CLI file/image MIME allow-lists and size constants.
  - Sync/async file attachment construction.
  - `/file` and `/image` prompt/attachment helpers.
  - `attachments_from_paths` used by `agent_cmd.py`.
- `src/opensquilla/cli/attachment_paths.py` owns:
  - `/path` command parsing.
  - Local-path strategy hints.
  - No-upload local path prompt construction.
- `src/opensquilla/cli/attachments.py` stays as a compatibility facade:
  - Re-export moved helpers/constants for existing imports.
  - Keep no helper bodies after the main-thread facade edit.
- `src/opensquilla/cli/chat_input_builders.py` remains the chat compatibility
  wrapper layer and should continue delegating through `attachments.py`.

## Parallel worker ownership

- Worker `cli-attachment-files` owns:
  - Create `src/opensquilla/cli/attachment_files.py`.
  - Create `tests/test_cli/test_attachment_files_boundary.py`.
  - May read but must not edit `src/opensquilla/cli/attachments.py`.
  - May run existing file/image focused tests for compatibility.
- Worker `cli-attachment-paths` owns:
  - Create `src/opensquilla/cli/attachment_paths.py`.
  - Create `tests/test_cli/test_attachment_paths_boundary.py`.
  - May read but must not edit `src/opensquilla/cli/attachments.py`.
  - May run existing path focused tests for compatibility.
- Main thread owns:
  - `src/opensquilla/cli/attachments.py`.
  - `tests/test_cli/test_attachments_facade_boundary.py`.
  - Worker review, merges, focused batch verification, full gates, integration
    merge, completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other
workers' changes and must not revert unrelated edits.

## TDD red/green

- File worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.attachment_files` does not exist.
- File worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_input_builders_boundary.py::test_image_prompt_builder_preserves_payload_and_status_output tests/test_cli/test_chat_input_builders_boundary.py::test_async_file_prompt_builder_preserves_upload_behavior -q`
- Path worker RED:
  - `uv run --extra dev pytest tests/test_cli/test_attachment_paths_boundary.py -q`
  - Expected: collection/import failure because
    `opensquilla.cli.attachment_paths` does not exist.
- Path worker GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_attachment_paths_boundary.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py::test_path_prompt_builder_preserves_no_upload_contract -q`
- Main-thread facade RED:
  - `uv run --extra dev pytest tests/test_cli/test_attachments_facade_boundary.py -q`
  - Expected: failure showing `attachments.py` still owns moved helper bodies
    instead of importing compatibility aliases from the new modules.
- Main-thread facade GREEN:
  - `uv run --extra dev pytest tests/test_cli/test_attachments_facade_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py -q`
- Touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/cli/attachments.py src/opensquilla/cli/attachment_files.py src/opensquilla/cli/attachment_paths.py tests/test_cli/test_attachment_files_boundary.py tests/test_cli/test_attachment_paths_boundary.py tests/test_cli/test_attachments_facade_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/cli/attachments.py src/opensquilla/cli/attachment_files.py src/opensquilla/cli/attachment_paths.py --show-error-codes`
  - `git diff --check`
- File worker evidence:
  - RED command:
    `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py -q`
  - RED result: expected collection failure,
    `ImportError: cannot import name 'attachment_files' from 'opensquilla.cli'`;
    `1 error in 0.06s`.
  - GREEN command:
    `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_input_builders_boundary.py::test_image_prompt_builder_preserves_payload_and_status_output tests/test_cli/test_chat_input_builders_boundary.py::test_async_file_prompt_builder_preserves_upload_behavior -q`
  - GREEN result: `18 passed in 3.53s`.
  - Worker ruff: `All checks passed!`.
  - Worker diff checks: clean.
  - Worker full `scripts/refactor_gate.sh`: `2724 passed, 8 skipped, 2
    warnings`; gateway smoke passed.
- Path worker evidence:
  - RED command:
    `uv run --extra dev pytest tests/test_cli/test_attachment_paths_boundary.py -q`
  - RED result: expected collection failure,
    `ImportError: cannot import name 'attachment_paths' from 'opensquilla.cli'`.
  - GREEN command:
    `uv run --extra dev pytest tests/test_cli/test_attachment_paths_boundary.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py::test_path_prompt_builder_preserves_no_upload_contract -q`
  - GREEN result: `50 passed in 3.08s`.
  - Worker ruff: `All checks passed!`.
  - Worker diff check: clean.
  - Worker full `scripts/refactor_gate.sh`: `2743 passed, 8 skipped, 2
    warnings`; gateway smoke passed.
- Main facade evidence:
  - RED command:
    `uv run --extra dev pytest tests/test_cli/test_attachments_facade_boundary.py -q`
  - RED result: `2 failed` because `attachments.py` imported no symbols from
    `opensquilla.cli.attachment_files` or `opensquilla.cli.attachment_paths`.
  - GREEN command:
    `uv run --extra dev pytest tests/test_cli/test_attachments_facade_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py -q`
  - GREEN result: `63 passed in 0.73s`.
  - Combined focused command:
    `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py tests/test_cli/test_attachment_paths_boundary.py tests/test_cli/test_attachments_facade_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py -q`
  - Combined focused result: `96 passed in 0.76s`.
  - Touched-file ruff: `All checks passed!`.
  - Touched-file mypy: `Success: no issues found in 3 source files`.
  - Whitespace check: `git diff --check` -> clean.
- Child full `scripts/refactor_gate.sh`:
  - ruff: `All checks passed!`.
  - mypy: `Success: no issues found in 568 source files`.
  - whitespace: clean.
  - pytest: `2752 passed, 8 skipped, 2 warnings in 55.27s`.
  - gateway smoke: start/status/stop/status passed on `127.0.0.1:55396`.
  - Result: `Refactor gate complete`.

## Files

- Create:
  - `src/opensquilla/cli/attachment_files.py`
  - `src/opensquilla/cli/attachment_paths.py`
  - `tests/test_cli/test_attachment_files_boundary.py`
  - `tests/test_cli/test_attachment_paths_boundary.py`
  - `tests/test_cli/test_attachments_facade_boundary.py`
- Modify:
  - `src/opensquilla/cli/attachments.py`
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`.
- [x] Confirm `spawn_agent` status.
- [x] Create fixed active worktree on `codex/refactor-cli-attachments-input-boundaries`.
- [x] Write this stage plan before production edits.
- [x] Commit this stage plan as the worker base.
- [x] Launch two external workers with `scripts/refactor_external_agent.sh`.
- [x] File worker writes RED boundary tests and records RED output.
- [x] Path worker writes RED boundary tests and records RED output.
- [x] File worker implements boundary and records GREEN/check evidence.
- [x] Path worker implements boundary and records GREEN/check evidence.
- [x] Main thread reviews both diffs for behavior compatibility and ownership.
- [x] Merge both worker branches into the active child.
- [x] Main thread writes and verifies facade RED/GREEN.
- [x] Run focused green command and touched-file checks.
- [x] Run `scripts/refactor_gate.sh` in the active child worktree.
- [x] Commit child verification/stage record update.
- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove temporary child/worker worktrees; run `git worktree prune`; verify
      no extra refactor worktree directories remain beyond integration.

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

- Revert the integration merge commit if `/file`, `/image`, `/path`, chat input
  builders, or `opensquilla agent --file` behavior regresses.
- Keep child and worker branches for diagnosis until a replacement slice is
  ready.

## Completion record

- File worker commit: `1ac1e3e` (`Refactor CLI file attachment helpers`).
- Path worker commit: `1069fb1` (`Refactor CLI path attachment helpers`).
- Active child worker merges:
  - `8579ebb` (`Merge CLI file attachment helpers worker`).
  - `d964a23` (`Merge CLI path attachment helpers worker`).
- Main facade commit: `3595bdc` (`Refactor CLI attachments facade`).
- Child verification commit: `c5edd4c` (`Record CLI attachments input child
  verification`).
- Integration merge: `84a9584f2db8481d0ab3d510b77f1266edd28ed1` (`Merge CLI
  attachments input boundaries`).
- Integration record: this cleanup record update after the integration gate and
  worktree cleanup.
- Verification evidence:
  - Combined focused command: `uv run --extra dev pytest tests/test_cli/test_attachment_files_boundary.py tests/test_cli/test_attachment_paths_boundary.py tests/test_cli/test_attachments_facade_boundary.py tests/test_cli/test_chat_file_command.py tests/test_cli/test_chat_path_command.py tests/test_cli/test_chat_input_builders_boundary.py tests/test_cli/test_agent_cmd.py tests/test_agent_cmd_no_key.py -q`
    -> `96 passed in 0.76s`.
  - Touched-file ruff: `All checks passed!`.
  - Touched-file mypy: `Success: no issues found in 3 source files`.
  - Child full `scripts/refactor_gate.sh`: ruff passed; mypy passed with no
    issues in 568 source files; whitespace clean; pytest `2752 passed, 8
    skipped, 2 warnings in 55.27s`; gateway smoke start/status/stop/status
    passed.
  - Integration full `scripts/refactor_gate.sh`: ruff passed; mypy passed with
    no issues in 568 source files; whitespace clean; pytest `2754 passed, 6
    skipped, 2 warnings in 28.20s`; gateway smoke start/status/stop/status
    passed on `127.0.0.1:55815`; result `Refactor gate complete`.
- Cleanup evidence:
  - `git worktree remove ../opensquilla-refactor-active`
  - `git worktree remove ../opensquilla-refactor-agent-cli-attachment-files`
  - `git worktree remove ../opensquilla-refactor-agent-cli-attachment-paths`
  - Deleted merged branches:
    `codex/refactor-cli-attachments-input-boundaries`,
    `codex/refactor-cli-attachment-files-worker`, and
    `codex/refactor-cli-attachment-paths-worker`.
  - `git worktree prune` completed; `git worktree list --porcelain` shows no
    `opensquilla-refactor-*` worktrees beyond
    `../opensquilla-refactor-integration`.
- Residual risk: low; this is a compatibility-facade split for CLI attachment
  input helpers. Boundary tests cover file/image/path behavior and the legacy
  `opensquilla.cli.attachments` import surface, while chat builder and
  `agent_cmd` focused tests cover the main callers.
- Next recommended slice: continue CLI boundary thinning with a coarse
  command-input or command-runtime batch, but prefer the next module-level
  slice only after rechecking current integration state and active incomplete
  stage records so the refactor line does not accumulate stale partial stages.
