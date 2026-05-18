# Channel Artifact Delivery Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move channel artifact fallback rendering, marker cleanup, artifact event normalization, and adapter file delivery out of the large Gateway channel dispatcher while preserving every channel reply shape.

**Architecture:** Add `opensquilla.gateway.channel_artifacts` as the focused artifact-delivery boundary used by both batch channel turns and runtime streaming replies. Keep `gateway/channel_dispatch.py` as the dispatcher/runtime orchestrator and import the artifact boundary helpers instead of owning their implementations.

**Tech Stack:** Python, Gateway channel dispatch, ArtifactStore, channel adapter `send_file`, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: channel-artifact-delivery-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-channel-artifact-delivery-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was rechecked and still returned `agent thread limit reached`; closing the stale shutdown child records also failed because their runtime thread ids were no longer present. This stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Extract channel artifact delivery/rendering concerns from `gateway/channel_dispatch.py` into a dedicated Gateway module without changing direct channel reply content, file-upload delivery, artifact fallback lines, streamed artifact behavior, transcript artifact dedupe, event bridge artifact payloads, or release hygiene.

## Current-State Audit

- Current HEAD: `d9ceac3`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-channel-rpc-payload-facade.md`
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_channel_concurrent_dispatch.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `gateway/channel_dispatch.py`.
  - `_RuntimeChannelStreamRelay`
  - `_artifact_event_payload`
  - `_artifact_delivery_key`
  - `_dedupe_artifacts_for_channel_delivery`
  - `_channel_safe_artifact_url`
  - `_artifact_fallback_lines`
  - `_strip_artifact_markers_from_channel_text`
  - `_strip_delivered_artifact_image_references`
  - `_deliver_artifacts_as_channel_files`
  - `_split_assistant_artifact_content`
- Tests inspected:
  - Batch channel artifact fallback and adapter upload tests.
  - Runtime stream relay artifact fallback/upload/dedupe tests.
  - Runtime reply artifact delivery tests.
  - Channel concurrency dispatch tests.
- Existing boundary pattern this stage follows:
  - Gateway facade modules own cross-cutting RPC/delivery adaptation while the original orchestrator imports them.
  - Architecture tests assert ownership by checking module imports and top-level functions.

## Boundary Decision

- Responsibilities moving out:
  - Artifact event normalization from engine/runtime events.
  - Artifact delivery key/dedupe logic.
  - Channel-safe fallback URL and fallback line rendering.
  - Artifact marker and delivered image reference cleanup.
  - Artifact store media-root resolution for channel file delivery.
  - Adapter `send_file` capability check and file upload delivery.
  - Assistant JSON artifact-content splitting.
- Responsibilities staying in `gateway/channel_dispatch.py`:
  - Receive-dispatch-respond loop.
  - Runtime stream relay orchestration.
  - Turn runner batch/streaming path selection.
  - Message building, route resolution, mention gating, attachment ingestion, and transcript lookup.
- New module/file responsibility:
  - `src/opensquilla/gateway/channel_artifacts.py` owns channel artifact rendering and delivery helpers.
- Public behavior that must not change:
  - Artifact fallback text remains `Generated file: <name> -> available in WebUI` unless a channel-safe absolute URL exists.
  - Channel-delivered file artifacts are not also represented by fallback text.
  - Markdown image references for delivered artifacts are stripped from channel text.
  - Adapter `send_file` receives the original artifact filename where available.
  - Event bridge artifact payloads still omit leaked `sessionKey` query parameters.
  - Runtime stream relay does not redeliver transcript artifacts.
- Files explicitly out of scope:
  - Channel adapter implementations.
  - ArtifactStore internals.
  - Attachment ingestion and transcript persistence.
  - Web UI artifact download views.
  - CLI behavior.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_artifact_delivery_boundary.py -q`
- Expected red failure:
  - `opensquilla.gateway.channel_artifacts` does not exist.
  - `gateway/channel_dispatch.py` still owns top-level artifact delivery helpers.
- Minimal implementation:
  - Create `opensquilla.gateway.channel_artifacts`.
  - Move artifact constants and helpers from `channel_dispatch.py` into the new module with public internal names.
  - Import those helpers into `channel_dispatch.py` using the existing private helper names as aliases.
  - Update channel artifact tests to import direct helper coverage from `channel_artifacts`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_artifact_delivery_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/channel_artifacts.py src/opensquilla/gateway/channel_dispatch.py tests/test_gateway/test_channel_artifact_delivery_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/channel_artifacts.py`
  - `tests/test_gateway/test_channel_artifact_delivery_boundary.py`
  - `docs/refactor/stages/2026-05-18-channel-artifact-delivery-boundary.md`
- Modify:
  - `src/opensquilla/gateway/channel_dispatch.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
- Test:
  - `tests/test_gateway/test_channel_artifact_delivery_boundary.py`
  - `tests/test_gateway/test_channel_dispatch_realtime.py`
  - `tests/test_gateway/test_channel_concurrent_dispatch.py`
  - `tests/test_channels/test_feishu_send_file.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-channel-artifact-delivery-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-channel-artifact-delivery-boundary`.
- [x] Write the failing channel artifact delivery boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible artifact boundary move.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.

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

- Revert the integration merge commit if channel artifact fallback, upload, or stream relay behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
- Child RED:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_artifact_delivery_boundary.py -q`
  - Expected failure observed before production wiring: `ModuleNotFoundError: No module named 'opensquilla.gateway.channel_artifacts'`.
- Child focused GREEN:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_artifact_delivery_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py -q`
  - `33 passed in 0.83s`.
- Child expanded focused checks:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_artifact_delivery_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py tests/test_gateway/test_channel_concurrent_dispatch.py tests/test_channels/test_feishu_send_file.py -q`
  - `55 passed in 0.95s`.
  - `uv run --extra dev ruff check src/opensquilla/gateway/channel_artifacts.py src/opensquilla/gateway/channel_dispatch.py tests/test_gateway/test_channel_artifact_delivery_boundary.py tests/test_gateway/test_channel_dispatch_realtime.py`
  - `All checks passed!`.
  - `git diff --check`
  - Passed with no output.
  - `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q`
  - `1 passed in 0.37s`.
- Child full gate:
  - `scripts/refactor_gate.sh`
  - `ruff`: all checks passed.
  - `mypy`: success, no issues found in 504 source files.
  - `pytest`: `2439 passed, 8 skipped, 2 warnings in 48.69s`.
  - Gateway smoke: start/status/stop/status passed on port `50044`.
- Directory cleanup:
  - Keep only the fixed active child worktree during implementation.
  - Merge this child back to `codex/refactor-architecture`, record evidence, then remove `../opensquilla-refactor-active` and prune git worktree metadata.
- Residual risk:
- Next recommended slice:
  - Use a larger module-level session management slice rather than another tiny helper extraction: move cohesive session create/update/registry-model helpers out of `gateway/rpc_sessions.py` behind an existing or new session-management boundary, with compatibility tests around `sessions.create`, `sessions.patch`, agent registry defaults, and model selection.
