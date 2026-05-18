# Channel Runtime Dispatch Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split channel runtime dispatch responsibilities into explicit, behavior-compatible Gateway boundaries while preserving inbound dispatch, streaming replies, terminal error replies, attachment ingestion, in-flight caps, dedupe behavior, and channel reply text.

**Architecture:** Keep `opensquilla.gateway.channel_dispatch` as the receive-dispatch-respond orchestrator, but move coherent helper families into focused Gateway modules. External worker branches own disjoint module/test families, and the main thread integrates them into one coarse channel runtime boundary batch.

**Tech Stack:** Python, asyncio channel dispatch, Gateway runtime helpers, channel manager ingress ports, pytest AST/behavior tests, ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: channel-runtime-dispatch-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-channel-runtime-dispatch-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, stage record, worker prompts, review, merge, gates, and cleanup. Same-thread `spawn_agent` was rechecked and returned `agent thread limit reached`, so this stage uses `scripts/refactor_external_agent.sh` with fixed sibling worker worktrees.

## Goal

Refactor the largest remaining channel dispatch runtime boundary in one cohesive batch:

- isolate per-channel in-flight queue/cap semantics from the dispatcher;
- isolate terminal error payload/reply construction and outgoing reply sanitization;
- isolate runtime stream relay policy from turn orchestration;
- isolate channel attachment/transcript message IO from dispatch control flow;
- preserve all public and user-visible channel behavior.

This stage intentionally groups related helper families rather than creating several tiny helper-only slices.

## Current-State Audit

- Current HEAD: `df7b899`.
- Worktree status: clean before creating this stage plan.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-channel-artifact-delivery-boundary.md`
  - `docs/refactor/stages/2026-05-18-channel-rpc-payload-facade.md`
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `src/opensquilla/gateway/channel_ingress.py`
  - `src/opensquilla/channels/manager.py`
  - `src/opensquilla/channels/ingress.py`
  - `tests/test_gateway/test_channel_concurrent_dispatch.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_channel_dispatch_ghost_turn.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
- Symbols or command surfaces inspected:
  - `run_channel_dispatch`
  - `_dispatch_combined_message_after_debounce`
  - `_ChannelInFlightSet`
  - `_compute_channel_cap`
  - `_terminal_payload_from_exception`
  - `_terminal_payload_from_error_event`
  - `_terminal_reply_suffix`
  - `_sanitize_outgoing_message`
  - `_DirectiveTagStreamSanitizer`
  - `_RuntimeChannelStreamRelay`
  - `_materialize_channel_attachments`
  - `_ingest_channel_message_attachments`
  - `_append_channel_user_message`
  - `_latest_assistant_text_after`
  - `_build_runtime_reply_message`
  - `_deliver_runtime_channel_reply`
- Tests inspected:
  - in-flight cap and queue tests in `tests/test_gateway/test_channel_concurrent_dispatch.py`
  - runtime stream relay and attachment tests in `tests/test_gateway/test_channel_dispatch_realtime.py`
  - ghost-turn persistence tests in `tests/test_gateway/test_channel_dispatch_ghost_turn.py`
  - manager ingress boundary tests in `tests/test_channels/test_channel_manager_ingress.py`
- Existing boundary pattern this stage follows:
  - `gateway/channel_artifacts.py` owns artifact rendering/delivery helpers while `channel_dispatch.py` imports compatibility aliases.
  - `gateway/channel_rpc_payloads.py` owns Gateway channel RPC wire adaptation while Channels owns channel status semantics.
  - Existing tests may keep compatibility imports from `gateway.channel_dispatch` during the move, but new boundary tests must assert the new owning modules.

## Boundary Decision

- Module batch:
  - `gateway/channel_inflight.py`
  - `gateway/channel_replies.py`
  - `gateway/channel_streaming.py`
  - `gateway/channel_message_io.py`
- Responsibilities moving out:
  - Per-channel in-flight task tracking, cap formula, and cancellation semantics.
  - Terminal error payload conversion and terminal reply suffix building for channel replies.
  - Inline directive tag stripping for outgoing messages and streamed chunks.
  - Runtime stream relay lifecycle and stream chunk sanitation.
  - Channel attachment materialization, attachment ingestion, user-message persistence, transcript watermarking, and latest assistant text lookup.
- Responsibilities staying in place:
  - `run_channel_dispatch` orchestration and debounce flow.
  - Slash command/new command routing and command registry invocation.
  - Delivery target resolution and route-envelope construction.
  - Batch/stream turn path selection.
  - Runtime reply delivery orchestration until worker integration proves a narrower move is safe.
- New module/file responsibility:
  - `src/opensquilla/gateway/channel_inflight.py`: channel in-flight tracker and cap computation.
  - `src/opensquilla/gateway/channel_replies.py`: terminal payload helpers, terminal reply suffix, outgoing reply sanitation, and directive sanitizer.
  - `src/opensquilla/gateway/channel_streaming.py`: `_RuntimeChannelStreamRelay` behavior-compatible relay.
  - `src/opensquilla/gateway/channel_message_io.py`: attachment/transcript persistence helpers used by runtime dispatch.
- Public behavior that must not change:
  - Channel reply content, terminal reply payloads, and terminal suffix text.
  - Inline `[[reply_to_current]]` / `[[reply_to:...]]` directive stripping from final and streamed replies.
  - In-flight cap formula: `min(channel_inflight_cap, max(2 * max_concurrency, 1))`.
  - Queue-full behavior and metric labels.
  - In-flight task cancellation behavior during channel stop.
  - Attachment resolution, attachment ingestion payloads, persisted user message content, transcript watermarking, and latest assistant text selection.
  - Runtime stream relay start conditions, idle timeout, heartbeat handling, event handling, and final flush behavior.
  - Compatibility imports from `opensquilla.gateway.channel_dispatch` for existing tests and downstream code.
- Files explicitly out of scope:
  - Channel adapter implementations.
  - Artifact delivery internals already owned by `gateway/channel_artifacts.py`.
  - `channels.status`, `channels.logout`, and `channels.restart` RPC payload facade.
  - Web UI static assets and CLI channel commands.

## Parallel Worker Ownership

- Worker `channel-inflight` owns:
  - Create `src/opensquilla/gateway/channel_inflight.py`.
  - Create `tests/test_gateway/test_channel_inflight_boundary.py`.
  - Modify `src/opensquilla/gateway/channel_dispatch.py` only for imports/aliases and call sites for `_ChannelInFlightSet` and `_compute_channel_cap`.
  - Modify `tests/test_gateway/test_channel_concurrent_dispatch.py` only where imports should prove the new boundary while preserving compatibility coverage.
- Worker `channel-replies-streaming` owns:
  - Create `src/opensquilla/gateway/channel_replies.py`.
  - Create `src/opensquilla/gateway/channel_streaming.py`.
  - Create `tests/test_gateway/test_channel_replies_streaming_boundary.py`.
  - Modify `src/opensquilla/gateway/channel_dispatch.py` only for imports/aliases and call sites for terminal payload, sanitizer, and `_RuntimeChannelStreamRelay`.
  - Modify `tests/test_gateway/test_channel_dispatch_realtime.py` only where imports should prove the new boundary while preserving compatibility coverage.
- Worker `channel-message-io` owns:
  - Create `src/opensquilla/gateway/channel_message_io.py`.
  - Create `tests/test_gateway/test_channel_message_io_boundary.py`.
  - Modify `src/opensquilla/gateway/channel_dispatch.py` only for imports/aliases and call sites for attachment/transcript helpers.
  - Modify `tests/test_gateway/test_channel_dispatch_ghost_turn.py` and `tests/test_gateway/test_channel_dispatch_realtime.py` only for message IO import expectations.
- Main thread owns:
  - This stage document.
  - Worker prompts.
  - Merge review and conflict resolution.
  - Any final compatibility alias cleanup in `channel_dispatch.py`.
  - Focused batch verification, full child gate, integration merge/gate, stage completion record, and cleanup.

Workers are not alone in the codebase. Each worker must preserve other workers' edits during integration and must not revert unrelated changes.

## TDD Red/Green

- Failing test commands:
  - Worker inflight: `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py -q`
  - Worker replies/streaming: `uv run --extra dev pytest tests/test_gateway/test_channel_replies_streaming_boundary.py -q`
  - Worker message IO: `uv run --extra dev pytest tests/test_gateway/test_channel_message_io_boundary.py -q`
- Expected red failures:
  - New owning modules do not exist yet.
  - `channel_dispatch.py` still owns the helper families directly.
  - New architecture tests fail until helper ownership moves.
- Behavior compatibility coverage:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_concurrent_dispatch.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_channel_dispatch_realtime.py -q`
  - `uv run --extra dev pytest tests/test_gateway/test_channel_dispatch_ghost_turn.py -q`
  - `uv run --extra dev pytest tests/test_channels/test_channel_manager_ingress.py -q`
- Module-batch implementation:
  - Move helper families into the new modules with the same behavior and types.
  - Import moved helpers back into `channel_dispatch.py` under the existing private names to preserve compatibility while shrinking ownership.
  - Add boundary tests that assert new module ownership and that `channel_dispatch.py` no longer defines the moved top-level helpers/classes.
  - Keep direct behavior tests green against both new module imports and existing compatibility imports.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py tests/test_gateway/test_channel_replies_streaming_boundary.py tests/test_gateway/test_channel_message_io_boundary.py tests/test_gateway/test_channel_concurrent_dispatch.py tests/test_gateway/test_channel_dispatch_realtime.py tests/test_gateway/test_channel_dispatch_ghost_turn.py tests/test_channels/test_channel_manager_ingress.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/channel_dispatch.py src/opensquilla/gateway/channel_inflight.py src/opensquilla/gateway/channel_replies.py src/opensquilla/gateway/channel_streaming.py src/opensquilla/gateway/channel_message_io.py tests/test_gateway/test_channel_inflight_boundary.py tests/test_gateway/test_channel_replies_streaming_boundary.py tests/test_gateway/test_channel_message_io_boundary.py tests/test_gateway/test_channel_concurrent_dispatch.py tests/test_gateway/test_channel_dispatch_realtime.py tests/test_gateway/test_channel_dispatch_ghost_turn.py tests/test_channels/test_channel_manager_ingress.py`
  - `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/channel_inflight.py`
  - `src/opensquilla/gateway/channel_replies.py`
  - `src/opensquilla/gateway/channel_streaming.py`
  - `src/opensquilla/gateway/channel_message_io.py`
  - `tests/test_gateway/test_channel_inflight_boundary.py`
  - `tests/test_gateway/test_channel_replies_streaming_boundary.py`
  - `tests/test_gateway/test_channel_message_io_boundary.py`
- Modify:
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `tests/test_gateway/test_channel_concurrent_dispatch.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_channel_dispatch_ghost_turn.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
- Test:
  - `tests/test_gateway/test_channel_inflight_boundary.py`
  - `tests/test_gateway/test_channel_replies_streaming_boundary.py`
  - `tests/test_gateway/test_channel_message_io_boundary.py`
  - `tests/test_gateway/test_channel_concurrent_dispatch.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_channel_dispatch_ghost_turn.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-channel-runtime-dispatch-boundary-batch.md`

## Detailed Superpowers Implementation Plan

### Task 1: Baseline and Worker Dispatch

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration before creating this child branch.
- [x] Confirm `spawn_agent` status.
  - Observed: `spawn_agent` failed with `agent thread limit reached`.
- [x] Create fixed active worktree on `codex/refactor-channel-runtime-dispatch-boundary-batch`.
- [x] Write this stage plan before implementation.
- [ ] Commit this stage plan as the worker base.
- [ ] Launch three external workers with `scripts/refactor_external_agent.sh`, each from this child branch.

### Task 2: Worker `channel-inflight`

- [ ] Write RED tests in `tests/test_gateway/test_channel_inflight_boundary.py`.
  - Import `ChannelInFlightSet` and `compute_channel_cap` from `opensquilla.gateway.channel_inflight`.
  - Assert `opensquilla.gateway.channel_dispatch` does not define a top-level `class _ChannelInFlightSet` or `def _compute_channel_cap`.
  - Assert compatibility aliases still work from `opensquilla.gateway.channel_dispatch`.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move the in-flight tracker and cap formula into `channel_inflight.py`.
- [ ] Import them in `channel_dispatch.py` as `_ChannelInFlightSet` and `_compute_channel_cap`.
- [ ] Update `tests/test_gateway/test_channel_concurrent_dispatch.py` to import behavior tests from the new module where appropriate while preserving at least one compatibility alias assertion.
- [ ] Run the worker focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py tests/test_gateway/test_channel_concurrent_dispatch.py tests/test_channels/test_channel_manager_ingress.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 3: Worker `channel-replies-streaming`

- [ ] Write RED tests in `tests/test_gateway/test_channel_replies_streaming_boundary.py`.
  - Import terminal payload helpers and directive sanitizer from `opensquilla.gateway.channel_replies`.
  - Import `RuntimeChannelStreamRelay` from `opensquilla.gateway.channel_streaming`.
  - Assert `channel_dispatch.py` no longer defines the moved helper/class bodies after implementation.
  - Assert compatibility aliases still work from `opensquilla.gateway.channel_dispatch`.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_channel_replies_streaming_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move terminal payload helpers, terminal suffix, outgoing message sanitizer, and directive sanitizer into `channel_replies.py`.
- [ ] Move runtime stream relay into `channel_streaming.py`.
- [ ] Keep streaming imports dependency-light: `channel_streaming.py` may import `OutgoingMessage`, `TextDeltaEvent`, channel artifact helpers, `resolve_channel_stream_policy`, and `channel_replies` sanitizer helpers, but must not import `channel_dispatch.py`.
- [ ] Import moved helpers in `channel_dispatch.py` under existing private names.
- [ ] Update `tests/test_gateway/test_channel_dispatch_realtime.py` imports where appropriate.
- [ ] Run the worker focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_replies_streaming_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 4: Worker `channel-message-io`

- [ ] Write RED tests in `tests/test_gateway/test_channel_message_io_boundary.py`.
  - Import `materialize_channel_attachments`, `ingest_channel_message_attachments`, `append_channel_user_message`, `latest_assistant_text_after`, `transcript_watermark`, and `read_transcript_rows` from `opensquilla.gateway.channel_message_io`.
  - Assert `channel_dispatch.py` no longer defines the moved helper bodies after implementation.
  - Assert compatibility aliases still work from `opensquilla.gateway.channel_dispatch`.
- [ ] Run `uv run --extra dev pytest tests/test_gateway/test_channel_message_io_boundary.py -q` and confirm the expected missing-module or ownership failure.
- [ ] Move attachment/transcript helpers into `channel_message_io.py`.
- [ ] Keep this module dependency-light: it may import `AttachmentIngestResult`, `ingest_attachments`, and `media_root_from_config`, but must not import `channel_dispatch.py`.
- [ ] Import moved helpers in `channel_dispatch.py` under existing private names.
- [ ] Update ghost-turn/realtime tests to prove the new boundary while preserving behavior.
- [ ] Run the worker focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_message_io_boundary.py tests/test_gateway/test_channel_dispatch_ghost_turn.py tests/test_gateway/test_channel_dispatch_realtime.py -q`
- [ ] Run touched-file ruff and `git diff --check`.
- [ ] Commit with the required co-author trailer.

### Task 5: Main Integration Review

- [ ] Wait for all worker branches and read each last-message summary.
- [ ] Review each branch diff before merge.
- [ ] Merge worker branches into `codex/refactor-channel-runtime-dispatch-boundary-batch` one by one with `git merge --no-ff`.
- [ ] Resolve import/alias conflicts in `channel_dispatch.py` without reverting another worker's ownership.
- [ ] Run the focused batch green command.
- [ ] Run touched-file ruff, mypy, and `git diff --check`.
- [ ] Run full child `scripts/refactor_gate.sh`.
- [ ] Commit any integration conflict fix or stage-record update with the required co-author trailer.

### Task 6: Integration Branch Merge and Cleanup

- [ ] Merge child into integration with `git merge --no-ff codex/refactor-channel-runtime-dispatch-boundary-batch`.
- [ ] Run full integration `scripts/refactor_gate.sh`.
- [ ] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
- [ ] Commit the stage record update on integration with the required co-author trailer.
- [ ] Remove `../opensquilla-refactor-active` and each `../opensquilla-refactor-agent-*` worker worktree.
- [ ] Run `git worktree prune`.
- [ ] Verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if channel dispatch, streaming replies, in-flight cancellation, attachment ingestion, or terminal error reply behavior regresses.
- Keep worker branches until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Worker commits:
  - channel-inflight: `a231f96` (`Extract channel inflight boundary`)
  - channel-replies-streaming: `7464f24` (`Extract channel replies and streaming relay`)
  - channel-message-io: `f925850` (`Extract channel message IO boundary`)
- Child integration commits:
  - `c16f169` (`Merge channel inflight boundary worker`)
  - `237f2f0` (`Merge channel replies streaming worker`)
  - `e9b39af` (`Merge channel message IO worker`)
  - `6a7ef56` (`Resolve channel runtime boundary import ordering`)
- Integration merge:
  - `a75239b` (`Merge channel runtime dispatch boundary batch`)
- Verification evidence:
  - Worker `channel-inflight` RED: `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py -q` failed as expected because `opensquilla.gateway.channel_inflight` did not exist.
  - Worker `channel-replies-streaming` RED: `uv run --extra dev pytest tests/test_gateway/test_channel_replies_streaming_boundary.py -q` failed as expected because `channel_replies` / `channel_streaming` did not exist and moved definitions still lived in `channel_dispatch.py`.
  - Worker `channel-message-io` RED: `uv run --extra dev pytest tests/test_gateway/test_channel_message_io_boundary.py -q` failed as expected because `channel_message_io` did not exist and moved helper definitions still lived in `channel_dispatch.py`.
  - Worker full gates passed independently:
    - `channel-inflight`: `2493 passed, 8 skipped`; gateway smoke passed.
    - `channel-replies-streaming`: `2495 passed, 8 skipped`; gateway smoke passed.
    - `channel-message-io`: `2493 passed, 8 skipped`; gateway smoke passed.
  - Main merge focused check after conflict resolution:
    - `uv run --extra dev pytest tests/test_gateway/test_channel_inflight_boundary.py tests/test_gateway/test_channel_replies_streaming_boundary.py tests/test_gateway/test_channel_message_io_boundary.py tests/test_gateway/test_channel_concurrent_dispatch.py tests/test_gateway/test_channel_dispatch_realtime.py tests/test_gateway/test_channel_dispatch_ghost_turn.py tests/test_channels/test_channel_manager_ingress.py -q`
    - `67 passed`.
  - Main touched-file ruff: all checks passed.
  - Main mypy: success, no issues found in 521 source files.
  - Main `git diff --check`: clean.
  - Child full gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 521 source files; whitespace passed; pytest `2505 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
  - Integration full gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 521 source files; whitespace passed; pytest `2507 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status passed.
- Residual risk:
  - Low to medium. Behavior was preserved by existing runtime, realtime, artifact, ghost-turn, and in-flight tests, and compatibility aliases remain on `gateway.channel_dispatch`. The orchestrator still owns several smaller runtime helpers (`_build_reply_message`, `_status_reactor`, `_streaming_reply_kwargs`, `_text_delta_from_event`) that can move in a later cleanup after this larger boundary batch settles.
- Next recommended slice:
  - Continue with a Tools/Sandbox security boundary batch or a Web UI RPC/view-state contract batch; Channels now has a cleaner dispatch runtime boundary and should rest unless integration gate finds regressions.
