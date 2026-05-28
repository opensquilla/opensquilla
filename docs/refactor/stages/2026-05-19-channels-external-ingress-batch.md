# Channels External Ingress Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or the recorded external-agent fallback when splitting lanes. This G003 stage is a coarse channels/external-ingress refactor and must preserve main parity for adapter config, webhook/websocket ingress, dispatch, reply, and channel RPC surfaces.

**Goal:** Finish the channels/external-ingress component boundary by moving adapter assembly and webhook route collection out of `ChannelManager` while preserving all channel public behavior.

**Architecture:** Keep existing dispatch/reply/message-IO gateway boundaries from prior stages. Add a channels-owned runtime assembly boundary for adapter construction metadata and external webhook route discovery, then have `ChannelManager` delegate to it. This keeps adapter/config/plugin decisions inside `opensquilla.channels` and leaves Gateway wiring as orchestration only.

**Tech Stack:** Python 3.12+, Starlette routes, pytest, ruff, mypy, git worktrees, Superpowers, Serena.

---

## Stage

- Name: channels-external-ingress-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-channels-external-ingress-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex leader, with same-thread subagent fallback attempted and local implementation after 429.
- Ultragoal story: `G003-channels-external-ingress-batch`

## Goal

Refactor channel adapter config and external ingress routing as one coherent behavior-compatible batch:

- isolate adapter construction, enabled/unknown filtering, agent/type metadata, and debounce metadata from `ChannelManager`;
- isolate webhook route collection and transport-name filtering from `ChannelManager`;
- keep existing Gateway dispatch/reply/runtime boundaries and channel RPC payloads unchanged;
- preserve observable channel behavior against existing channel, gateway, CLI, and onboarding tests.

## Current-state audit

- Current HEAD at child start: `703e1ef` (`Close the extension-services stage with cleanup evidence`).
- Worktree status: clean at child worktree creation and after `scripts/refactor_preflight.sh --expect-branch codex/refactor-channels-external-ingress-batch --allow-dirty`.
- AGENTS.md files in scope: root `AGENTS.md` only for touched files.
- Files inspected:
  - `docs/refactor/stages/2026-05-19-global-component-plugin-decoupling-audit.md`
  - `docs/refactor/stages/2026-05-19-channel-runtime-dispatch-boundary-batch.md`
  - `docs/refactor/stages/2026-05-19-channels-delivery-boundary.md`
  - `docs/refactor/stages/2026-05-19-gateway-channel-manager-wiring-boundary.md`
  - `src/opensquilla/channels/manager.py`
  - `src/opensquilla/channels/registry.py`
  - `src/opensquilla/channels/entries.py`
  - `src/opensquilla/channels/transports.py`
  - `src/opensquilla/channels/ingress.py`
  - `src/opensquilla/gateway/channel_ingress.py`
  - `src/opensquilla/gateway/channel_manager_wiring.py`
  - `tests/test_channels/test_channel_manager_ingress.py`
  - `tests/test_channels/test_channel_gateway_boundary.py`
  - `tests/test_gateway/test_channel_manager_wiring_boundary.py`
- Symbols inspected with Serena:
  - `ChannelManager.from_config`
  - `ChannelManager.collect_webhook_routes`
  - `ChannelManager._run_one_dispatch_cycle`
  - `GatewayChannelIngress`
  - `build_gateway_channel_manager_wiring`
  - `build_managed_channel`
  - `ConfiguredChannelEntry`
- Existing boundary pattern this stage follows:
  - Prior channel runtime stages created focused gateway/channel modules and retained compatibility aliases where needed.
  - `ChannelManager` already consumes `ChannelIngressPort` rather than importing gateway dispatch directly; this stage applies the same boundary style to adapter assembly and webhook route collection.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: current Superpowers skills were read before starting G003 planning.
- `superpowers:using-git-worktrees`:
  - Evidence: detected integration as a linked worktree, removed the old G002 active worktree, then created `../opensquilla-refactor-active` on branch `codex/refactor-channels-external-ingress-batch` from integration HEAD `703e1ef`.
- `superpowers:writing-plans`:
  - Evidence: this stage document defines the boundary decision, owned files, RED/GREEN tests, verification gate, merge, cleanup, and checkpoint requirements before code changes.
- `superpowers:test-driven-development`:
  - Evidence: RED command will be `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py -q` before creating `opensquilla.channels.runtime_assembly`.
- `superpowers:verification-before-completion`:
  - Evidence: this stage cannot be checkpointed until focused tests, full child `scripts/refactor_gate.sh`, integration merge, integration gate, cleanup, and Ultragoal checkpoint evidence exist.
- Parallelism decision:
  - `superpowers:subagent-driven-development` used: attempted via same-thread read-only planning probes for adapter/config and transport/ingress/dispatch lanes.
  - `spawn_agent` probe: two `explore` agents were spawned for independent lane mapping; both failed with `429 Too Many Requests`, so no worker edits were accepted.
  - External worker fallback: not used for implementation because the selected remaining batch is a single shared-file boundary centered on `ChannelManager`; splitting would create more conflict than throughput. If later RED tests expose independent adapter-module defects, use `scripts/refactor_external_agent.sh` before adding serial sub-slices.
- Serena evidence:
  - Serena project for the integration worktree was activated.
  - Serena project memories read: multi-branch parallelism preference, Serena usage preference, and per-substage Superpowers evidence requirements.
  - Serena symbol lookups informed the decision to keep dispatch/reply boundaries stable and focus this batch on `ChannelManager.from_config` plus `collect_webhook_routes`.

## Boundary decision

- Module batch: channels external ingress runtime assembly.
- Responsibilities moving out:
  - Building managed channel adapters from config entries.
  - Disabled-entry skipping and unknown-type handling.
  - Agent-id and channel-type metadata collection.
  - Debounce metadata assignment on adapters.
  - Webhook route discovery and transport-name filtering for adapters.
- Responsibilities staying in place:
  - `ChannelManager` lifecycle, dispatch retry, health, start/stop/restart, in-flight cancellation, session-key construction, and delivery target resolution.
  - Gateway channel manager boot/wiring in `gateway/channel_manager_wiring.py`.
  - Gateway dispatch, message IO, reply, streaming, inflight, and artifact modules already split by prior stages.
  - Adapter modules and registry plugin discovery behavior.
- New module/file responsibility:
  - `src/opensquilla/channels/runtime_assembly.py` owns `ChannelRuntimeAssembly`, `build_channel_runtime_assembly(...)`, and `collect_channel_webhook_routes(...)`.
- Public behavior that must not change:
  - Channel adapter config fields and validation.
  - Disabled entries are skipped; unknown channel types warn and skip.
  - Adapter `debounce_window_s` remains attached from entry config.
  - Webhook routes are collected only for webhook transports exposing `create_webhook_route()`.
  - Websocket/non-webhook channels do not contribute Starlette webhook routes.
  - Channel RPC status/logout/restart payloads, CLI channel output, onboarding channel specs, dispatch/reply behavior, attachment metadata, dedupe, and session-key contracts.
- Files explicitly out of scope:
  - Provider/router internals.
  - Web UI redesign/static view changes.
  - Individual adapter protocol rewrites.
  - Gateway dispatch/reply/message-IO internals unless a focused RED test proves a regression.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.channels.runtime_assembly'` before implementation.
- Behavior compatibility coverage:
  - New boundary tests plus existing channel manager ingress/lifecycle/gateway boundary, gateway channel manager wiring, channel RPC, onboarding specs, CLI channels, and channel test suites.
- Module-batch implementation:
  - Add channels runtime assembly module.
  - Delegate `ChannelManager.from_config` and `ChannelManager.collect_webhook_routes` to the new module.
  - Keep public `ChannelManager` method names and return behavior unchanged.
- Focused green command:
  - `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py tests/test_channels/test_channel_manager_ingress.py tests/test_channels/test_channel_manager_lifecycle.py tests/test_channels/test_channel_gateway_boundary.py tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_rpc_channels.py tests/test_cli/test_channels_cmd.py tests/test_onboarding/test_channel_specs.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/channels/runtime_assembly.py src/opensquilla/channels/manager.py tests/test_channels/test_channel_runtime_assembly_boundary.py`

## Files

- Create:
  - `src/opensquilla/channels/runtime_assembly.py`
  - `tests/test_channels/test_channel_runtime_assembly_boundary.py`
- Modify:
  - `src/opensquilla/channels/manager.py`
- Test:
  - Existing focused suites listed above.
- Documentation:
  - `docs/refactor/stages/2026-05-19-channels-external-ingress-batch.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-channels-external-ingress-batch --allow-dirty`.
- [x] Write the failing boundary tests.
- [x] Run the focused RED command and confirm expected failure.
- [x] Implement `channels.runtime_assembly` and delegate from `ChannelManager`.
- [x] Run the focused GREEN command and touched-file ruff.
- [x] Run `scripts/refactor_gate.sh` in the child worktree.
- [x] Commit with the required Co-authored-by trailer.
- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify cleanup.
- [ ] Checkpoint Ultragoal G003 with a fresh active `get_goal` JSON; do not call `update_goal`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `scripts/refactor_gate.sh` from `codex/refactor-architecture` after merge and after evidence cleanup.

## Rollback

- Revert the integration merge commit if channel adapter creation, webhook route collection, channel startup, dispatch/reply behavior, RPC payloads, CLI output, or onboarding channel specs regress.
- Keep the child branch for diagnosis until a replacement batch is ready.

## Completion record

- Child commit: `df82ba3` (`Separate channel ingress assembly from lifecycle management`).
- Integration merge: `f61d8d0` (`Merge channels external ingress boundary batch`).
- Verification evidence:
  - RED: `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py -q` failed before implementation with `ModuleNotFoundError: No module named 'opensquilla.channels.runtime_assembly'`.
  - GREEN boundary: `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py -q` -> `4 passed in 0.28s`.
  - Focused compatibility: `uv run --extra dev pytest tests/test_channels/test_channel_runtime_assembly_boundary.py tests/test_channels/test_channel_manager_ingress.py tests/test_channels/test_channel_manager_lifecycle.py tests/test_channels/test_channel_gateway_boundary.py tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_rpc_channels.py tests/test_cli/test_channels_cmd.py tests/test_onboarding/test_channel_specs.py -q` -> `85 passed in 1.21s`.
  - Touched-file lint: `uv run --extra dev ruff check src/opensquilla/channels/runtime_assembly.py src/opensquilla/channels/manager.py tests/test_channels/test_channel_runtime_assembly_boundary.py` -> `All checks passed!`.
  - Child gate: `scripts/refactor_gate.sh` -> ruff pass, mypy pass on 580 source files, whitespace pass, pytest `2831 passed, 8 skipped`, gateway smoke start/status/stop/status pass, `Refactor gate complete.`
  - Integration gate first run after merge exposed release hygiene failure: `tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths` failed on a tracked absolute local path in this stage doc.
  - Hygiene fix check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` -> `1 passed in 0.36s`.
  - Integration gate after hygiene fix: `scripts/refactor_gate.sh` -> ruff pass, mypy pass on 580 source files, whitespace pass, pytest `2833 passed, 6 skipped`, gateway smoke start/status/stop/status pass, `Refactor gate complete.`
  - Cleanup: `git worktree remove ../opensquilla-refactor-active`; `git worktree prune`; `git worktree list` no longer lists `../opensquilla-refactor-active`.
- Residual risk: no known G003 blocker after child gate, integration merge, integration gate, and active child worktree cleanup. Ultragoal checkpoint remains leader-owned follow-up step.
- Next recommended slice: G004 provider and router integration batch.
