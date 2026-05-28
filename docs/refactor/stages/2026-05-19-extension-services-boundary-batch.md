# Extension Services Boundary Batch

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended for independent lanes) or `superpowers:executing-plans` to implement this plan task-by-task. This stage uses batch-level TDD and keeps one coherent extension-services verification pass.

**Goal:** Move skills/plugins, memory, search, and scheduler boot/runtime wiring behind a cohesive extension-services boundary while preserving RPC, CLI, tool, scheduler, memory, and static UI public behavior.

**Architecture:** Gateway boot should compose extension services through one boundary module rather than owning four separate runtime/bootstrap chunks inline. Domain-specific RPC payload/runtime modules stay in their current packages; the new boundary is an integration seam that returns a typed runtime container consumed by `ServiceContainer`.

**Tech Stack:** Python 3.12+, pytest, Typer/Gateway RPC, git worktrees, Superpowers, Serena.

---

## Stage

- Name: `extension-services-boundary-batch`
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-extension-services-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: main Codex leader
- Ultragoal story: `G002-extension-services-boundary-batch`

## Current-state audit

- Current HEAD: `8fb11e8` (`Define coarse refactor audit runway`).
- Worktree status: clean at child worktree creation.
- AGENTS.md files in scope: `AGENTS.md`, `docs/AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`.
- Files inspected:
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/rpc_skills.py`
  - `src/opensquilla/gateway/rpc_memory.py`
  - `src/opensquilla/gateway/rpc_search.py`
  - `src/opensquilla/gateway/rpc_cron.py`
  - `src/opensquilla/skills/runtime_facade.py`
  - `src/opensquilla/memory/source_rpc.py`
  - `src/opensquilla/search/rpc_payload.py`
  - `src/opensquilla/scheduler/rpc_payload.py`
- Tests inspected:
  - `tests/test_skills_runtime_boundary.py`
  - `tests/test_skills_rpc_payload.py`
  - `tests/test_memory_source_rpc.py`
  - `tests/test_search/test_search_runtime_boundary.py`
  - `tests/test_search/test_search_execution.py`
  - `tests/test_scheduler/test_cron_rpc_payload.py`
  - `tests/test_scheduler/test_scheduler_engine_boundary.py`
  - `tests/test_gateway/test_rpc_domain_modules.py`
  - `tests/test_gateway/test_rpc_product_cli_gaps.py`
- Existing boundary pattern this stage follows: domain `rpc_payload.py` and `runtime.py` modules own payload/runtime semantics, while Gateway boot should only compose service containers.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: created fixed child worktree `../opensquilla-refactor-active` on `codex/refactor-extension-services-boundary-batch`; child preflight passed.
- `superpowers:writing-plans`:
  - Evidence: this stage document defines owned files, forbidden files, RED/GREEN commands, parity strategy, worker split, gate, merge, and cleanup.
- `superpowers:test-driven-development`:
  - Evidence: RED test will be added before production changes: `tests/test_extension_services/test_gateway_runtime.py` asserts the extension-services boundary exists and Gateway boot delegates to it.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: G001 used read-only parallel audit lanes. For this implementation pass, same-thread agents timed out during G001, so the initial implementation stays leader-owned in the active child worktree. If additional independent fixes are found after RED/GREEN, use `scripts/refactor_external_agent.sh` before shrinking further.
- `superpowers:verification-before-completion`:
  - Evidence: this stage will not be checkpointed until focused extension-service tests, full child `scripts/refactor_gate.sh`, integration merge, integration gate, and Ultragoal checkpoint evidence exist.

## Serena evidence

- Serena was activated for the active child worktree.
- Symbol/pattern inspection identified `gateway.boot.build_services` as the current inline owner of memory runtime, skill loader/tool registration, scheduler startup, and search runtime sync.
- Existing domain payload/runtimes already own most RPC semantics; the missing seam is boot/runtime composition.

## Boundary decision

- Module batch: extension services gateway runtime composition.
- Responsibilities moving out:
  - Memory gateway runtime initialization and returned manager/store/retriever/watch/capture fields.
  - Skill loader creation and skill tool registration.
  - Cron scheduler store construction/start and tool-service exposure.
  - Search runtime sync from gateway config.
- Responsibilities staying in place:
  - Public RPC method names/scopes and wire keys.
  - Existing domain payload helpers for skills, memory, search, and scheduler.
  - `ServiceContainer` field names and `build_turn_runner_from_services` inputs.
  - MCP, provider, channels, session lifecycle, and Web UI behavior.
- New module/file responsibility:
  - Create `src/opensquilla/extension_services/gateway_runtime.py` with `ExtensionServicesRuntime` and `build_extension_services_runtime(...)`.
  - Add `src/opensquilla/extension_services/__init__.py` as a narrow public package entrypoint.
- Public behavior that must not change:
  - `skills.*`, `memory.*`, `search.*`, `tools.search_provider`, and `cron.*` RPC surfaces.
  - CLI skills/memory/search/cron calls and output.
  - Memory TurnRunner refresh callback behavior via `_turn_runner_ref`.
  - Scheduler DB location/environment overrides and `configure_tool_services(scheduler=...)` side effect.
  - Search Brave > DuckDuckGo bootstrap policy and diagnostics/proxy/fallback behavior.
- Files explicitly out of scope:
  - Provider/router internals.
  - Channels/external ingress internals.
  - Web UI redesign or unrelated static helpers.
  - Tool policy/security execution behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_extension_services/test_gateway_runtime.py -q`
- Expected red failure:
  - New test fails because `opensquilla.extension_services.gateway_runtime` does not exist and `gateway.boot` still owns inline extension-service imports.
- Behavior compatibility coverage:
  - New boundary tests plus existing skills/memory/search/scheduler RPC and runtime tests.
- Module-batch implementation:
  - Add extension-service runtime container, move boot wiring chunks from `gateway.boot.build_services`, and keep `ServiceContainer` values identical.
- Focused green command:
  - `uv run --extra dev pytest tests/test_extension_services/test_gateway_runtime.py tests/test_skills_runtime_boundary.py tests/test_skills_rpc_payload.py tests/test_memory_source_rpc.py tests/test_memory_gateway_runtime.py tests/test_search tests/test_scheduler tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_domain_modules.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/extension_services src/opensquilla/gateway/boot.py tests/test_extension_services/test_gateway_runtime.py`

## Files

- Create:
  - `src/opensquilla/extension_services/__init__.py`
  - `src/opensquilla/extension_services/gateway_runtime.py`
  - `tests/test_extension_services/test_gateway_runtime.py`
- Modify:
  - `src/opensquilla/gateway/boot.py`
- Test:
  - Existing focused extension service suites listed above.
- Documentation:
  - `docs/refactor/stages/2026-05-19-extension-services-boundary-batch.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty` in the child worktree.
- [x] Write the failing boundary test.
- [x] Run the focused test and confirm expected RED failure.
- [x] Implement `extension_services.gateway_runtime` and delegate from `gateway.boot`.
- [x] Run the focused GREEN command and touched-file ruff.
- [x] Run `scripts/refactor_gate.sh` in the child worktree.
- [x] Commit with the required Co-authored-by trailer.
- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify cleanup.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `scripts/refactor_gate.sh` from `codex/refactor-architecture` after merge.

## Rollback

- Revert the integration merge commit if the extension-service boundary regresses Gateway boot, RPC payloads, CLI outputs, scheduler startup, or search runtime policy.
- Keep child branch for diagnosis until a replacement batch is ready.

## Completion record

- Child commit: `fb27727` (`Isolate extension-service boot wiring for coarse refactor progress`).
- Integration merge: `2e3ddf4` (`Merge extension services boundary batch`).
- Evidence commit: `4339152` (`Record extension-services integration gate evidence`).
- Verification evidence:
  - RED: `uv run --extra dev pytest tests/test_extension_services/test_gateway_runtime.py -q` failed before implementation with missing `opensquilla.extension_services` and missing Gateway delegation.
  - GREEN: `uv run --extra dev pytest tests/test_extension_services/test_gateway_runtime.py -q` -> `3 passed in 2.47s`; after team review gap closure, extension-services boundary/fail-open tests -> `4 passed in 0.34s`.
  - Focused compatibility: `uv run --extra dev pytest tests/test_extension_services/test_gateway_runtime.py tests/test_skills_runtime_boundary.py tests/test_skills_rpc_payload.py tests/test_memory_source_rpc.py tests/test_memory_gateway_runtime.py tests/test_search tests/test_scheduler tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_domain_modules.py -q` -> `82 passed in 0.83s`.
  - Expanded contract fallout check after full-gate fixes: architecture imports, router boot memory boundary, public release hygiene, and extension-service suites -> `88 passed in 2.88s`.
  - Touched-file lint: `uv run --extra dev ruff check src/opensquilla/extension_services src/opensquilla/gateway/boot.py tests/test_extension_services/test_gateway_runtime.py tests/test_skills_runtime_boundary.py tests/test_search/test_search_runtime_boundary.py tests/test_gateway/test_router_boot.py tests/test_ci/test_architecture_import_contracts.py` -> `All checks passed!`.
  - Team review: `omx team 2:executor ...` -> 3 tasks completed, 0 failed; worker-1 independently ran focused checks (`107 passed`) and child `scripts/refactor_gate.sh` (`2827 passed, 8 skipped`) and found no blocking compatibility issue. The one noted gap (skills/scheduler/search fail-open not individually failure-injected) was closed with `test_build_extension_services_runtime_keeps_fail_open_boundaries_independent`.
  - Child gate: `scripts/refactor_gate.sh` -> ruff pass, mypy pass on 579 source files, whitespace pass, pytest `2827 passed, 8 skipped`, gateway smoke start/status/stop/status pass, `Refactor gate complete.`
  - Integration gate after merge `2e3ddf4`: `scripts/refactor_gate.sh` -> ruff pass, mypy pass on 579 source files, whitespace pass, pytest `2829 passed, 6 skipped`, gateway smoke start/status/stop/status pass, `Refactor gate complete.`
  - Cleanup: `git worktree remove ../opensquilla-refactor-active`; `git worktree prune`; `git worktree list` no longer lists `../opensquilla-refactor-active`.
  - Post-cleanup integration gate: `scripts/refactor_gate.sh` -> ruff pass, mypy pass on 579 source files, whitespace pass, pytest `2829 passed, 6 skipped`, gateway smoke start/status/stop/status pass, `Refactor gate complete.`
- Residual risk: no known G002 blocker after child gate, team review, merge, integration gate, and active child worktree cleanup. Ultragoal checkpoint remains leader-owned follow-up step.
- Next recommended slice: G003 channels and external ingress batch.
