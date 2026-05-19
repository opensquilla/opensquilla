# Gateway WebSocket Connection Core Stage

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: Gateway WebSocket connection core boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-websocket-connection-core`
- Child worktree: `/Users/cwan0785/opensquilla-refactor-agent-gateway`
- Owner: Codex gateway worker

## Goal

Extract the WebSocket connection-core responsibilities out of
`src/opensquilla/gateway/websocket.py` into a focused gateway helper module
without changing public WebSocket events, RPC response payloads, writer queue
behavior, or compatibility imports used by existing tests/callers.

## Current-state audit

- Current HEAD: `b7422a3`
- Worktree status before edits: clean on
  `codex/refactor-gateway-websocket-connection-core`
- AGENTS.md files in scope: `./AGENTS.md`
- Files inspected:
  - `src/opensquilla/gateway/websocket.py`
  - `src/opensquilla/gateway/config.py`
  - `tests/test_gateway/test_websocket_handshake.py`
  - `tests/test_gateway/test_ws_writer_queue.py`
  - `tests/test_gateway/test_config_ws_writer_queue.py`
  - `docs/refactor/stage-template.md`
- Symbols or command surfaces inspected:
  - `WsConnection`
  - `_OutboundFrame`
  - `_LOSSY_EVENTS`
  - `_SENTINEL_STOP`
  - `ConnectionRegistry`
  - `handle_ws_connection`
  - `scripts/refactor_preflight.sh --allow-dirty`
- Tests inspected:
  - `tests/test_gateway/test_websocket_handshake.py`
  - `tests/test_gateway/test_ws_writer_queue.py`
  - `tests/test_gateway/test_config_ws_writer_queue.py`
- Existing boundary pattern this stage follows: prior gateway boundary tests
  under `tests/test_gateway/` that protect import seams and public behavior
  while moving cohesive runtime responsibilities into focused modules.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: Read the skill instructions, confirmed the requested fixed
    worktree path with `git worktree list`, and worked only in
    `/Users/cwan0785/opensquilla-refactor-agent-gateway` on
    `codex/refactor-gateway-websocket-connection-core`.
- `superpowers:writing-plans`:
  - Evidence: Read the skill instructions and used this stage record as the
    implementation plan/checklist for the coarse module boundary.
- `superpowers:test-driven-development`:
  - Evidence: Added
    `tests/test_gateway/test_websocket_connection_core_boundary.py` before
    production edits, then ran it and observed the expected RED failure.
- `superpowers:verification-before-completion`:
  - Evidence: Fresh verification commands are recorded below before any
    completion claim.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or
    `superpowers:subagent-driven-development` used: No. This worker was
    already assigned a single owned gateway slice in a dedicated worktree.
  - `spawn_agent` probe: Not run; this worker scope was limited to
    `gateway/websocket.py`, new focused gateway websocket helper module(s),
    and focused tests.
  - If same-thread agents were unavailable, external worker fallback: Not
    needed for this single-file extraction slice.
- Historical evidence note:
  - Current evidence only; prior stage records were not used as proof.

## Boundary decision

- Module batch: Gateway WebSocket connection core.
- Responsibilities moving out:
  - `WsConnection` state and direct/queued send entry points.
  - Writer queue lifecycle and overflow/drop policy.
  - `_OutboundFrame`, `_LOSSY_EVENTS`, `_SENTINEL_STOP`, and payload-field
    extraction helper.
  - `ConnectionRegistry`.
- Responsibilities staying in place:
  - WebSocket handshake, auth negotiation, protocol negotiation, HelloOk
    construction, message loop, tick loop, feature list, subscription manager,
    and module-level registry accessor.
- New module/file responsibility:
  - `src/opensquilla/gateway/websocket_connection.py` owns per-connection
    queueing, sequencing, close behavior, and active-connection collection.
- Public behavior that must not change:
  - `connect.challenge`, HelloOk wire payload, RPC response frames, `tick`,
    writer-queue sequence minting, lossy tick drop policy, control overflow
    close behavior, and existing `opensquilla.gateway.websocket` imports for
    connection types/constants.
- Files explicitly out of scope:
  - Session manager modules.
  - Channel delivery modules.
  - Provider runtime modules.
  - Tools/MCP modules.
  - Web UI static JS/CSS.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_websocket_connection_core_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.gateway.websocket_connection'`
- Behavior compatibility coverage:
  - Existing focused gateway tests cover handshake disconnect handling,
    writer queue sequencing/drop/overflow/teardown, and config env overrides.
  - New boundary test covers helper-module import boundary plus
    `websocket.py` compatibility re-exports.
- Module-batch implementation:
  - Created `src/opensquilla/gateway/websocket_connection.py`.
  - Thinned `src/opensquilla/gateway/websocket.py` by importing and
    re-exporting the connection-core types/constants.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_websocket_connection_core_boundary.py tests/test_gateway/test_websocket_handshake.py tests/test_gateway/test_ws_writer_queue.py tests/test_gateway/test_config_ws_writer_queue.py -q`
  - First result after extraction: `36 passed in 3.02s`
  - Final touched-test result after import cleanup: `36 passed in 2.97s`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/websocket.py src/opensquilla/gateway/websocket_connection.py tests/test_gateway/test_websocket_connection_core_boundary.py tests/test_gateway/test_websocket_handshake.py tests/test_gateway/test_ws_writer_queue.py tests/test_gateway/test_config_ws_writer_queue.py`
    - Result: `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/gateway/websocket.py src/opensquilla/gateway/websocket_connection.py --show-error-codes`
    - Result: `Success: no issues found in 2 source files`
  - `git diff --check`
    - Result: exit 0, no output.
  - `scripts/refactor_gate.sh`
    - Result: full ruff passed; full mypy passed for 575 source files;
      full pytest `2805 passed, 8 skipped, 2 warnings in 53.30s`;
      gateway smoke start/status/stop/status passed; `Refactor gate complete.`

## Files

- Create:
  - `src/opensquilla/gateway/websocket_connection.py`
  - `tests/test_gateway/test_websocket_connection_core_boundary.py`
- Modify:
  - `src/opensquilla/gateway/websocket.py`
- Test:
  - `tests/test_gateway/test_websocket_connection_core_boundary.py`
  - `tests/test_gateway/test_websocket_handshake.py`
  - `tests/test_gateway/test_ws_writer_queue.py`
  - `tests/test_gateway/test_config_ws_writer_queue.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-gateway-websocket-connection-core.md`

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

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src/opensquilla/gateway/websocket.py src/opensquilla/gateway/websocket_connection.py tests/test_gateway/test_websocket_connection_core_boundary.py tests/test_gateway/test_websocket_handshake.py tests/test_gateway/test_ws_writer_queue.py tests/test_gateway/test_config_ws_writer_queue.py`
- `uv run --extra dev mypy src/opensquilla/gateway/websocket.py src/opensquilla/gateway/websocket_connection.py --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest tests/test_gateway/test_websocket_connection_core_boundary.py tests/test_gateway/test_websocket_handshake.py tests/test_gateway/test_ws_writer_queue.py tests/test_gateway/test_config_ws_writer_queue.py -q`
- `scripts/refactor_gate.sh`

## Integration gate

- Not run in this child worker. User explicitly requested not to merge to
  integration.

## Rollback

- Revert the child commit if the extraction regresses gateway WebSocket
  behavior. The extraction is intentionally limited to `gateway.websocket` and
  `gateway.websocket_connection` so rollback should not affect session,
  provider, channel, tool/MCP, or web UI static modules.

## Completion record

- Child commit: Recorded in the worker final response. The commit cannot
  embed its own final hash without changing that hash.
- Integration merge: Not performed by request.
- Verification evidence:
  - RED boundary test:
    `uv run --extra dev pytest tests/test_gateway/test_websocket_connection_core_boundary.py -q`
    failed with `ModuleNotFoundError: No module named 'opensquilla.gateway.websocket_connection'`.
  - Focused tests:
    `uv run --extra dev pytest tests/test_gateway/test_websocket_connection_core_boundary.py tests/test_gateway/test_websocket_handshake.py tests/test_gateway/test_ws_writer_queue.py tests/test_gateway/test_config_ws_writer_queue.py -q`
    passed with `36 passed in 2.97s`.
  - Touched-file ruff passed.
  - Touched-file mypy passed for 2 source files.
  - `git diff --check` passed.
  - `scripts/refactor_gate.sh` passed with full ruff, full mypy, full pytest
    `2805 passed, 8 skipped`, and gateway smoke.
- Residual risk:
  - This is a behavior-compatible extraction, so the main risk is import
    compatibility for private symbols. The new boundary test covers the private
    symbols already imported by focused writer queue tests from
    `opensquilla.gateway.websocket`.
  - Integration merge/gate intentionally not performed in this worker per user
    instruction.
- Next recommended slice: Keep gateway handler concerns separate from
  connection-core mechanics; future slices can consider handshake/message-loop
  helpers only with explicit public wire compatibility coverage.
