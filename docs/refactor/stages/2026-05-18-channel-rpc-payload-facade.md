# Channel RPC Payload Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move channel management Gateway RPC payload adaptation for `channels.status`, `channels.logout`, and `channels.restart` behind a Gateway facade while preserving public RPC payloads and channel compatibility wrappers.

**Architecture:** Add `opensquilla.gateway.channel_rpc_payloads` as the Gateway-owned adapter for channel management RPC request parsing, lifecycle side effects, and wire payloads. Add `opensquilla.channels.status_report` as the channel-domain status report builder so the Channels package owns channel state semantics without importing Gateway.

**Tech Stack:** Python, Gateway RPC dispatcher, channel manager health reports, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: channel-rpc-payload-facade
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-channel-rpc-payload-facade`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was rechecked and still returned `agent thread limit reached`; this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Consolidate channel status/logout/restart Gateway RPC wire adaptation into a Gateway-owned facade while keeping Channels as the owner of channel status semantics and preserving existing Python compatibility imports.

## Current-State Audit

- Current HEAD: `6cca716`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-rpc-payload-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`
  - `src/opensquilla/gateway/rpc_channels.py`
  - `src/opensquilla/channels/rpc_payload.py`
  - `src/opensquilla/channels/__init__.py`
  - `tests/test_gateway/test_rpc_channels.py`
  - `tests/test_channels/test_channel_rpc_payload.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
- Symbols or command surfaces inspected:
  - `channels.status`
  - `channels.logout`
  - `channels.restart`
  - `channel_status_rpc_payload`
  - `channel_logout_rpc_payload`
  - `channel_restart_rpc_payload`
  - `_configured_channel_entries`, `_health_extra`, `_status_for`, and `_channel_status_row`
- Tests inspected:
  - Channel RPC status payload tests.
  - Channel RPC lifecycle payload tests.
  - Gateway RPC public surface baseline.
  - Static onboarding channel view tests.
- Existing boundary pattern this stage follows:
  - Gateway RPC modules own method registration.
  - Gateway facade modules own production RPC request/wire payload adaptation.
  - Domain packages may keep compatibility wrappers without reverse-importing Gateway.

## Boundary Decision

- Responsibilities moving out:
  - Production `channels.status` wire payload conversion.
  - Production `channels.logout` / `channels.restart` request parsing and lifecycle payload conversion.
  - Gateway RPC handler imports from `channels.rpc_payload`.
- Responsibilities staying in Channels:
  - Channel status semantics: configured entries, runtime health merge, disabled/dead/connected/stopped status selection.
  - Public compatibility wrappers exported by `opensquilla.channels.rpc_payload` and `opensquilla.channels`.
  - Channel manager and adapter behavior.
- New module/file responsibility:
  - `src/opensquilla/channels/status_report.py` owns channel-domain status reports.
  - `src/opensquilla/gateway/channel_rpc_payloads.py` owns Gateway channel RPC wire payload adaptation.
- Public behavior that must not change:
  - `channels.status`, `channels.logout`, and `channels.restart` method names and scopes stay unchanged.
  - `channels.status` response rows keep the same keys, ordering, and runtime/config merge behavior.
  - `channels.logout` accepts `name` or `channel` and returns `{"status": "disconnected", "channel": name}`.
  - `channels.restart` accepts `name` or `channel` and returns `{"status": "restarted", "channel": name}`.
  - Existing Python imports from `opensquilla.channels.rpc_payload` and `opensquilla.channels` keep working.
- Files explicitly out of scope:
  - Channel adapter implementations.
  - Channel dispatch/realtime streaming behavior.
  - Onboarding channel mutation RPCs.
  - Web UI JavaScript and CLI channel commands.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_rpc_payload_facade.py -q`
- Expected red failure:
  - `opensquilla.gateway.channel_rpc_payloads` and `opensquilla.channels.status_report` do not exist.
  - `rpc_channels.py` still imports production payload builders from `opensquilla.channels.rpc_payload`.
  - `channels.rpc_payload` still owns status merge helpers directly.
- Minimal implementation:
  - Create `opensquilla.channels.status_report`.
  - Create `opensquilla.gateway.channel_rpc_payloads`.
  - Point `gateway/rpc_channels.py` at the Gateway facade.
  - Keep compatibility wrappers in `channels.rpc_payload` without importing Gateway.
  - Update channel architecture tests for the new ownership boundary.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_channels/test_channel_rpc_payload.py tests/test_gateway/test_rpc_channels.py tests/test_gateway/test_rpc_public_surface_baseline.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/channel_rpc_payloads.py src/opensquilla/gateway/rpc_channels.py src/opensquilla/channels/status_report.py src/opensquilla/channels/rpc_payload.py src/opensquilla/channels/__init__.py tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_channels/test_channel_rpc_payload.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/channels/status_report.py`
  - `src/opensquilla/gateway/channel_rpc_payloads.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `docs/refactor/stages/2026-05-18-channel-rpc-payload-facade.md`
- Modify:
  - `src/opensquilla/gateway/rpc_channels.py`
  - `src/opensquilla/channels/rpc_payload.py`
  - `src/opensquilla/channels/__init__.py`
  - `tests/test_channels/test_channel_rpc_payload.py`
- Test:
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `tests/test_channels/test_channel_rpc_payload.py`
  - `tests/test_gateway/test_rpc_channels.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-channel-rpc-payload-facade.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-channel-rpc-payload-facade`.
- [x] Write the failing Gateway channel RPC payload facade tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible facade move.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

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

- Revert the integration merge commit if channel status or lifecycle RPC payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `4119f02 Move channel RPC payloads behind gateway facade`.
- Integration merge: `d949dc2 Merge channel RPC payload facade`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-channel-rpc-payload-facade` passed on branch `codex/refactor-channel-rpc-payload-facade` at `6cca716`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_channel_rpc_payload_facade.py -q` failed as expected during collection with `ModuleNotFoundError: No module named 'opensquilla.gateway.channel_rpc_payloads'`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_channels/test_channel_rpc_payload.py tests/test_gateway/test_rpc_channels.py tests/test_gateway/test_rpc_public_surface_baseline.py -q` passed, `10 passed in 1.06s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/channel_rpc_payloads.py src/opensquilla/gateway/rpc_channels.py src/opensquilla/channels/status_report.py src/opensquilla/channels/rpc_payload.py src/opensquilla/channels/__init__.py tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_channels/test_channel_rpc_payload.py` passed.
  - Whitespace: `git diff --check` passed.
  - Broader channel/RPC group: `uv run --extra dev pytest tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_gateway/test_rpc_channels.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_static_onboarding_views.py tests/test_channels/test_channel_rpc_payload.py tests/test_channels/test_channel_manager_lifecycle.py tests/test_channels/test_channel_manager_ingress.py tests/test_channels/test_channel_gateway_boundary.py -q` passed, `39 passed in 0.59s`.
  - Architecture contract and compatibility retest: `uv run --extra dev pytest tests/test_ci/test_architecture_import_contracts.py tests/test_gateway/test_channel_rpc_payload_facade.py tests/test_channels/test_channel_rpc_payload.py -q` passed, `12 passed in 1.82s`.
  - Release hygiene focused retest: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.37s`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 503 source files; whitespace passed; pytest passed with `2435 passed, 8 skipped, 2 warnings in 49.10s`; gateway smoke start/status/stop passed on `127.0.0.1:65392`.
  - Child release hygiene staged retest after documentation update: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.31s`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `6cca716`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 503 source files; whitespace passed; pytest passed with `2437 passed, 6 skipped, 2 warnings in 26.49s`; gateway smoke start/status/stop passed on `127.0.0.1:65527`.
  - Cleanup policy: this slice used the fixed active child worktree path and removes it after the integration record commit so temporary directories do not accumulate.
- Residual risk:
  - Low. Production RPC handlers now use the Gateway facade while existing `opensquilla.channels.rpc_payload` compatibility wrappers remain covered by channel tests. Architecture import contracts cover the absence of a new Channels-to-Gateway dependency.
- Next recommended slice:
  - Continue with a larger Gateway/Channels runtime boundary or switch to a Tools/Sandbox security boundary, keeping the fixed active child worktree and cleanup-after-merge cadence.
