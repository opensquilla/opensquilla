# Gateway Channel Manager Wiring Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: gateway-channel-manager-wiring-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-channel-manager-wiring-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Worker branch: `codex/refactor-gateway-channel-manager-worker`
- Worker worktree: `../opensquilla-refactor-agent-channel-manager`
- Owner: main Codex thread coordinates architecture, prompts, review, merge,
  verification, records, and cleanup; one external Codex worker may implement
  because same-thread `spawn_agent` remains unavailable.

## Goal

Move gateway channel manager construction, webhook route collection, lazy
channel-manager reference population, and channel startup result logging out of
`gateway/boot.py` into a focused Gateway channel wiring boundary while
preserving boot behavior, channel RPC context wiring, cron delivery through the
lazy reference, webhook route registration, router preload ordering, injected
channel manager behavior, and gateway smoke behavior.

This is a single-worker implementation stage. The cohesive target block
converges inside `start_gateway_server`, so parallel implementation workers
would edit the same boot function and create avoidable conflicts. The
parallelism decision was still made explicitly under
`superpowers:dispatching-parallel-agents`.

## Current-state audit

- Current HEAD at worker start: `88eaa05` (`Plan gateway channel manager wiring boundary`)
- Worktree status: clean before this plan file.
- AGENTS.md files in scope:
  - `AGENTS.md`
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-gateway-runtime-wiring-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `tests/test_gateway/test_runtime_wiring_boundary.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
- Symbols or command surfaces inspected:
  - `start_gateway_server`
  - `_make_channel_rpc_context_factory`
  - `ChannelManager.from_config`
  - `GatewayChannelIngress`
  - `collect_webhook_routes`
  - `channel_manager.start_all`
  - `preload_squilla_router_runtime`
  - `create_gateway_app`
- Tests inspected:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_runtime_wiring_boundary.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
  - `tests/test_gateway/test_shutdown_order.py`
- Existing boundary pattern this stage follows:
  - `src/opensquilla/gateway/runtime_wiring.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/gateway/cron_result_delivery.py`
  - `src/opensquilla/gateway/channel_rpc_payloads.py`

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: read current skill instructions before continuing this resumed
    refactor turn.
- `superpowers:using-git-worktrees`:
  - Evidence: read current skill instructions; inspected integration state;
    created isolated active child worktree `../opensquilla-refactor-active` on
    `codex/refactor-gateway-channel-manager-wiring-boundary`.
- `superpowers:writing-plans`:
  - Evidence: read current skill instructions; wrote this stage record before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: read current skill instructions; this stage requires RED boundary
    tests before adding `gateway/channel_manager_wiring.py` or changing
    `boot.py`.
  - Worker RED evidence: ran
    `uv run --extra dev pytest tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_shutdown_order.py -q`
    before production edits. Result: expected failure, 5 failed and 2 passed;
    failures showed `channel_manager_wiring.py` was missing and
    `boot.py` had not imported/delegated to the new boundary.
- `superpowers:verification-before-completion`:
  - Evidence: read current skill instructions; focused tests, touched-file
    checks, child `scripts/refactor_gate.sh`, integration
    `scripts/refactor_gate.sh`, merge records, and cleanup evidence are
    required before claiming this stage complete.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes for the decision.
    Implementation is intentionally single-worker because all production paths
    edit `start_gateway_server` in `boot.py`; main thread remains free to
    review, run focused checks, and merge.
  - `spawn_agent` probe: attempted and failed with
    `collab spawn failed: agent thread limit reached`.
  - External worker fallback: use `scripts/refactor_external_agent.sh` with
    slot `channel-manager`. Do not fall back to unrecorded serial work unless
    the external worker route is blocked.
  - Worker execution note: this worker ran in
    `../opensquilla-refactor-agent-channel-manager` because same-thread
    `spawn_agent` failed with `agent thread limit reached`.
- Historical evidence note:
  - Missing per-substage Superpowers evidence is a blocker.

## Boundary decision

- Module batch:
  - Gateway channel manager boot/wiring boundary.
- Responsibilities moving out:
  - Building a channel RPC context factory for channel adapters.
  - Constructing `ChannelManager` from configured channel entries.
  - Creating `GatewayChannelIngress`.
  - Collecting webhook routes.
  - Populating the lazy channel-manager holder for cron and heartbeat delivery.
  - Starting channels after app/server setup and logging per-channel success or
    failure using `start_errors`.
- Responsibilities staying in place:
  - Config loading, auth token generation, PID lock, service build, diagnostics,
    runtime wiring, cron handler registration, app construction, uvicorn server
    lifecycle, router preload scheduling, and `GatewayServer` ownership.
  - The `_make_channel_rpc_context_factory` compatibility helper may remain in
    `boot.py` unless moving it is necessary for the boundary and covered by
    tests.
- New module/file responsibility:
  - `src/opensquilla/gateway/channel_manager_wiring.py` owns channel manager
    construction and channel startup logging for gateway boot.
  - A small return object such as `GatewayChannelManagerWiring` exposes
    `channel_manager` and `webhook_routes` back to `boot.py`.
- Public behavior that must not change:
  - `start_gateway_server(..., run=False)` with no configured channels.
  - `start_gateway_server(..., channel_manager=...)` injected manager behavior.
  - Channel startup happens before Squilla router preload scheduling when
    `run=True`.
  - Webhook routes are passed to `create_gateway_app` through `extra_routes`.
  - Cron delivery and heartbeat delivery observe the constructed or injected
    channel manager through the lazy reference.
  - Channel RPC context gets the same services, `turn_runner`,
    `heartbeat_service`, diagnostics state, dispatcher, task runtime, and
    ingress behavior.
  - Per-channel start success/failure log events and failure metadata are
    preserved.
- Files explicitly out of scope:
  - Channel adapter internals under `src/opensquilla/channels`.
  - Channel RPC payload facades.
  - Cron handler internals.
  - Runtime wiring internals.
  - Web UI/static files.
  - Migrations and dependency lock files.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_shutdown_order.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/channel_manager_wiring.py` does not exist, or AST
    boundary tests show `start_gateway_server` still directly imports or calls
    `ChannelManager.from_config`, `GatewayChannelIngress`, `collect_webhook_routes`,
    or `channel_manager.start_all`.
- Behavior compatibility coverage:
  - New boundary tests verify module exports, construction side effects, lazy
    reference population for constructed and injected managers, webhook route
    propagation, and start logging behavior.
  - Existing router boot test verifies channel startup still precedes router
    preload scheduling.
  - Existing shutdown test verifies gateway shutdown still stops channels after
    task runtime drain.
- Module-batch implementation:
  - Create `gateway/channel_manager_wiring.py`.
  - Replace the relevant `start_gateway_server` inline block with delegator
    calls and assignments from returned wiring objects.
  - Preserve the injected `channel_manager` path and existing local variable
    names where later app/server wiring depends on them.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_channel_rpc_payload_facade.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/channel_manager_wiring.py tests/test_gateway/test_channel_manager_wiring_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/channel_manager_wiring.py`
  - `tests/test_gateway/test_channel_manager_wiring_boundary.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
- Test:
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_gateway/test_shutdown_order.py`
  - `tests/test_gateway/test_channel_rpc_payload_facade.py`
- Documentation:
  - This stage record.

## Steps

- [ ] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [ ] Commit this stage plan on the active child branch.
- [ ] Create external worker worktree from the active child branch.
- [x] Worker writes failing boundary tests and records RED output.
- [x] Worker implements `gateway/channel_manager_wiring.py` and replaces the
      inline boot channel manager construction/start blocks with short
      delegator calls.
- [ ] Main thread reviews diff for behavior compatibility and boundary scope.
- [ ] Run focused green command and touched-file checks.
- [ ] Run `scripts/refactor_gate.sh` in the active child worktree.
- [ ] Commit child verification/stage record update with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active` and
      `../opensquilla-refactor-agent-channel-manager`, run
      `git worktree prune`, and verify no extra refactor worktree directories
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

- Revert the integration merge commit if channel boot, webhook routes, router
  preload ordering, or channel delivery regress.
- Keep the child branch and worker branch for diagnosis until a replacement
  slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Worker commit: this commit on `codex/refactor-gateway-channel-manager-worker`
- Active child support commits:
- Child verification commit:
- Integration merge:
- Integration record:
- Verification evidence:
  - RED:
    `uv run --extra dev pytest tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_shutdown_order.py -q`
    -> expected failure, 5 failed and 2 passed.
  - GREEN:
    `uv run --extra dev pytest tests/test_gateway/test_channel_manager_wiring_boundary.py tests/test_gateway/test_router_boot.py::test_start_gateway_server_schedules_router_preload_after_channels tests/test_gateway/test_shutdown_order.py tests/test_gateway/test_channel_rpc_payload_facade.py -q`
    -> 11 passed.
  - Touched-file ruff:
    `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/channel_manager_wiring.py tests/test_gateway/test_channel_manager_wiring_boundary.py`
    -> all checks passed.
  - Gateway mypy:
    `uv run --extra dev mypy src/opensquilla/gateway --show-error-codes`
    -> success, no issues found in 91 source files.
  - Whitespace:
    `git diff --check` -> clean.
  - Full `scripts/refactor_gate.sh`: not run by this external worker; main
    thread will run or re-run the child and integration gates.
- Cleanup evidence:
- Residual risk: focused compatibility coverage passed; residual risk is
  limited to interactions only covered by the full refactor gate.
- Next recommended slice:
