# Channels Delivery Boundary Stage

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: channels-delivery-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-channels-delivery-boundary`
- Child worktree: `/Users/cwan0785/opensquilla-refactor-agent-channels`
- Owner: Codex worker for Channels delivery/manager boundary only.

## Goal

Extract outbound delivery target resolution from `ChannelManager` into a
Channels-owned helper module while preserving existing public manager behavior,
channel replies/events, and public RPC payload compatibility.

## Current-state audit

- Current HEAD: `b7422a3`.
- Worktree status: clean before this stage file and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is out of
    scope for touched files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-channel-runtime-dispatch-boundary-batch.md`
  - `src/opensquilla/channels/manager.py`
  - `src/opensquilla/channels/ingress.py`
  - `src/opensquilla/channels/entries.py`
  - `src/opensquilla/channels/stream_policy.py`
  - `src/opensquilla/channels/types.py`
  - `src/opensquilla/channels/rpc_payload.py`
  - `src/opensquilla/channels/status_report.py`
  - `src/opensquilla/gateway/rpc_channels.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
  - `tests/test_channels/test_channel_manager_lifecycle.py`
  - `tests/test_channels/test_channel_gateway_boundary.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_channels.py`
- Symbols or command surfaces inspected:
  - `ChannelManager.resolve_delivery_target`
  - `ChannelManager._build_delivery_resolution`
  - `DeliveryTargetResolution`
  - `channel_status_rpc_payload`
  - `channel_logout_rpc_payload`
  - `channel_restart_rpc_payload`
- Tests inspected:
  - `tests/test_channels/test_channel_manager_ingress.py`
  - `tests/test_channels/test_channel_manager_lifecycle.py`
  - `tests/test_channels/test_channel_gateway_boundary.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_channels.py`
- Existing boundary pattern this stage follows:
  - Channel status semantics live in `opensquilla.channels.status_report` while
    Gateway facades preserve RPC wire payloads.
  - `ChannelManager` should remain the public lifecycle facade but delegate
    cohesive domain policy to smaller Channels-owned modules.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: Existing isolated worktree verified at
    `/Users/cwan0785/opensquilla-refactor-agent-channels` on branch
    `codex/refactor-channels-delivery-boundary`; no new worktree created.
- `superpowers:writing-plans`:
  - Evidence: This stage file was created from `docs/refactor/stage-template.md`
    before production edits.
- `superpowers:test-driven-development`:
  - Evidence: RED tests are added in
    `tests/test_channels/test_channel_delivery_boundary.py` before creating
    `src/opensquilla/channels/delivery.py`; RED command failed with
    `ModuleNotFoundError: No module named 'opensquilla.channels.delivery'`.
- `superpowers:verification-before-completion`:
  - Evidence: Fresh focused tests passed with `13 passed`; touched-file ruff
    passed; mypy passed over 575 source files; `git diff --check` passed;
    `scripts/refactor_gate.sh` completed with `2807 passed, 8 skipped, 2
    warnings` and final line `Refactor gate complete.`
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or
    `superpowers:subagent-driven-development` used: not used for this worker
    slice; user assigned this fixed worker/worktree and file ownership.
  - `spawn_agent` probe: not run; this work is a single scoped Channels slice.
  - If same-thread agents were unavailable, external worker fallback: not
    needed.
- Historical evidence note:
  - Prior stage records are treated as context only; current git state and
    current command output are authoritative.

## Boundary decision

- Module batch:
  - Channels delivery target resolution.
- Responsibilities moving out:
  - Target/account/thread validation for outbound channel delivery.
  - Construction of `DeliveryTargetResolution` objects from manager channel
    catalogs.
- Responsibilities staying in place:
  - Channel lifecycle, dispatch task lifecycle, in-flight shutdown, health, and
    session key building remain in `ChannelManager`.
  - Public method `ChannelManager.resolve_delivery_target(...)` remains
    available for scheduler and runtime callers.
- New module/file responsibility:
  - `src/opensquilla/channels/delivery.py` owns delivery target resolution policy
    and returns existing `DeliveryTargetResolution` values.
- Public behavior that must not change:
  - Channel reply/event behavior.
  - `ChannelManager.resolve_delivery_target(...)` return values and reason
    strings: `unsupported_target`, `unsupported_account`, `ambiguous_account`,
    and `unsupported_thread`.
  - Threaded delivery remains Slack-only.
  - Channel RPC status/logout/restart payloads.
- Files explicitly out of scope:
  - Session persistence.
  - Provider modules.
  - Tools/MCP modules.
  - Gateway websocket core.
  - Web UI static assets.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_channels/test_channel_delivery_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.channels.delivery'`.
- Behavior compatibility coverage:
  - Direct helper coverage for entry-name, type-name, account, ambiguity, and
    thread validation.
  - Manager delegation coverage preserving public `resolve_delivery_target`.
  - RPC payload focused coverage for channel status/logout/restart.
- Module-batch implementation:
  - Add `opensquilla.channels.delivery`.
  - Replace manager's private delivery-resolution builder with a delegation to
    the new helper.
- Focused green command:
  - `uv run --extra dev pytest tests/test_channels/test_channel_delivery_boundary.py tests/test_channels/test_channel_manager_ingress.py tests/test_channels/test_channel_manager_lifecycle.py tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_gateway/test_rpc_channels.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/channels/manager.py src/opensquilla/channels/delivery.py tests/test_channels/test_channel_delivery_boundary.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/channels/delivery.py`
  - `tests/test_channels/test_channel_delivery_boundary.py`
- Modify:
  - `src/opensquilla/channels/manager.py`
- Test:
  - `tests/test_channels/test_channel_delivery_boundary.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
  - `tests/test_channels/test_channel_manager_lifecycle.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_channels.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-channels-delivery-boundary.md`

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
- [x] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- Not run by this worker. User explicitly requested no integration merge.

## Rollback

- Revert the child commit if this slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: this worker commit; see final response or `git log -1`.
- Integration merge: intentionally not performed by this worker.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty` completed on
    branch `codex/refactor-channels-delivery-boundary` at HEAD `b7422a3`.
  - RED: `uv run --extra dev pytest tests/test_channels/test_channel_delivery_boundary.py -q`
    failed during collection with `ModuleNotFoundError: No module named
    'opensquilla.channels.delivery'`.
  - Focused GREEN:
    `uv run --extra dev pytest tests/test_channels/test_channel_delivery_boundary.py tests/test_channels/test_channel_manager_ingress.py tests/test_channels/test_channel_manager_lifecycle.py tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_gateway/test_rpc_channels.py -q`
    passed with `13 passed`.
  - Touched-file ruff:
    `uv run --extra dev ruff check src/opensquilla/channels/manager.py src/opensquilla/channels/delivery.py tests/test_channels/test_channel_delivery_boundary.py`
    passed with `All checks passed!`.
  - Mypy: `uv run --extra dev mypy src/opensquilla --show-error-codes` passed
    with `Success: no issues found in 575 source files`.
  - Whitespace: `git diff --check` passed.
  - Full gate: `scripts/refactor_gate.sh` passed ruff, mypy, whitespace,
    pytest `2807 passed, 8 skipped, 2 warnings`, gateway smoke start/status/
    stop/status, and final line `Refactor gate complete.`
- Residual risk: Behavior is preserved by direct helper tests, manager
  delegation coverage, focused channel manager/RPC compatibility tests, and the
  full gate. Integration merge/gate and cleanup are intentionally not performed
  in this worker per user instruction.
- Next recommended slice: integrate this child branch into
  `codex/refactor-architecture` from the integration worktree, then run the
  integration gate there.
