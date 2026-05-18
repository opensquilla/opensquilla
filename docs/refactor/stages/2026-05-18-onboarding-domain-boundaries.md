# Onboarding Domain Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the remaining router, search, channel, and memory onboarding RPC registrations out of `gateway/rpc_onboarding.py` while preserving public RPC method names, scopes, payloads, runtime sync, and Web UI behavior.

**Architecture:** Keep `rpc_onboarding.py` as the core onboarding status/catalog/shared-helper module. Add focused sibling modules for router, search, channels, and memory onboarding RPCs, imported by `gateway/rpc/__init__.py` after core onboarding so helper imports remain stable.

**Tech Stack:** Python, Gateway RPC registry, onboarding mutations/specs/redaction, search runtime sync, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: onboarding-domain-boundaries
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-onboarding-domain-boundaries`
- Child worktree: `../opensquilla-refactor-active-onboarding-domains`
- Owner: Codex main thread. Agent runtime still exposes stale shutdown entries, so this stage uses the documented sequential fallback with one active child worktree.

## Goal

Extract the remaining non-core onboarding RPC domains from `rpc_onboarding.py` without changing any public RPC method name, scope, payload shape, persisted config behavior, search runtime sync, provider selector sync from router configuration, channel restart semantics, Web UI setup calls, CLI behavior, or release hygiene.

## Current-State Audit

- Current HEAD: `c26d15b`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-onboarding-provider-runtime-boundary.md`
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
  - `src/opensquilla/gateway/rpc_onboarding_providers.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
  - `tests/test_gateway/test_static_onboarding_views.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `rpc_onboarding.py`.
  - RPC method names `onboarding.router.catalog`, `onboarding.router.configure`, `onboarding.search.configure`, `onboarding.memory_embedding.configure`, `onboarding.channel.probe`, `onboarding.channel.upsert`, `onboarding.channel.remove`, `onboarding.channel.enable`, and `onboarding.channel.disable`.
- Tests inspected:
  - Router, search, channel, and memory embedding tests in `tests/test_gateway/test_rpc_onboarding.py`.
  - Public RPC surface baseline.
  - Static Web UI setup view RPC string tests.
  - Onboarding mutation/flow tests for domain behavior.
- Existing boundary pattern this stage follows:
  - `rpc/__init__.py` imports sibling `rpc_*` modules to register method handlers at boot.
  - The provider onboarding slice already uses a focused sibling module that imports shared helpers from `rpc_onboarding.py`.

## Boundary Decision

- Responsibilities moving out:
  - Router onboarding RPC handlers.
  - Search onboarding RPC handler and search runtime sync.
  - Channel onboarding probe/upsert/remove/toggle handlers.
  - Memory embedding onboarding RPC handler.
- Responsibilities staying in place:
  - Core onboarding status/catalog handlers.
  - Shared helpers for active config lookup, config path resolution, in-place apply, persistence, parameter validation, and provider selector/image runtime compatibility wrappers.
  - Provider/image-generation onboarding handlers stay in `rpc_onboarding_providers.py`.
  - Onboarding business logic stays in `opensquilla.onboarding.mutations`, specs, and redaction modules.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_onboarding_router.py` owns router onboarding RPC registration.
  - `src/opensquilla/gateway/rpc_onboarding_search.py` owns search onboarding RPC registration and search runtime sync.
  - `src/opensquilla/gateway/rpc_onboarding_channels.py` owns channel onboarding RPC registration.
  - `src/opensquilla/gateway/rpc_onboarding_memory.py` owns memory embedding onboarding RPC registration.
- Public behavior that must not change:
  - All existing onboarding RPC method names and scopes stay registered.
  - Response payloads, redaction, warnings, restartRequired flags, and persisted config paths stay unchanged.
  - Router configure still syncs the running provider selector.
  - Search configure still syncs search runtime.
  - Channel mutations still require restart.
  - Web UI setup and CLI surfaces remain unchanged.
- Files explicitly out of scope:
  - Web UI JavaScript.
  - CLI onboarding workflows.
  - Onboarding mutation internals.
  - Provider backend implementations.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_domain_boundaries.py -q`
- Expected red failure:
  - `rpc_onboarding_router.py`, `rpc_onboarding_search.py`, `rpc_onboarding_channels.py`, and `rpc_onboarding_memory.py` do not exist.
  - `rpc_onboarding.py` still registers router/search/channel/memory methods and owns direct search runtime sync.
- Minimal implementation:
  - Create the four focused onboarding RPC modules.
  - Move handler bodies from `rpc_onboarding.py` into the owning modules.
  - Import shared helpers from `rpc_onboarding.py`.
  - Import the new modules from `gateway/rpc/__init__.py` after `rpc_onboarding_providers`.
  - Keep public method names/scopes unchanged.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_domain_boundaries.py tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_static_onboarding_views.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc/__init__.py src/opensquilla/gateway/rpc_onboarding.py src/opensquilla/gateway/rpc_onboarding_router.py src/opensquilla/gateway/rpc_onboarding_search.py src/opensquilla/gateway/rpc_onboarding_channels.py src/opensquilla/gateway/rpc_onboarding_memory.py tests/test_gateway/test_rpc_onboarding_domain_boundaries.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_onboarding_router.py`
  - `src/opensquilla/gateway/rpc_onboarding_search.py`
  - `src/opensquilla/gateway/rpc_onboarding_channels.py`
  - `src/opensquilla/gateway/rpc_onboarding_memory.py`
  - `tests/test_gateway/test_rpc_onboarding_domain_boundaries.py`
  - `docs/refactor/stages/2026-05-18-onboarding-domain-boundaries.md`
- Modify:
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
- Test:
  - `tests/test_gateway/test_rpc_onboarding_domain_boundaries.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
  - `tests/test_gateway/test_static_onboarding_views.py`
  - `tests/test_onboarding/test_mutations.py`
  - `tests/test_onboarding/test_flow.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-onboarding-domain-boundaries.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-onboarding-domain-boundaries`.
- [x] Write the failing onboarding domain boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible domain move.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

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

- Revert the integration merge commit if onboarding domain RPC behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-onboarding-domain-boundaries` passed on branch `codex/refactor-onboarding-domain-boundaries` at `c26d15b`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_domain_boundaries.py -q` failed as expected with `3 failed` because the four domain modules did not exist, `rpc/__init__.py` did not import them, and search runtime sync was still owned by `rpc_onboarding.py`.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_domain_boundaries.py tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_static_onboarding_views.py -q` passed, `54 passed in 3.71s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc/__init__.py src/opensquilla/gateway/rpc_onboarding.py src/opensquilla/gateway/rpc_onboarding_router.py src/opensquilla/gateway/rpc_onboarding_search.py src/opensquilla/gateway/rpc_onboarding_channels.py src/opensquilla/gateway/rpc_onboarding_memory.py tests/test_gateway/test_rpc_onboarding_domain_boundaries.py` passed.
  - First whitespace check caught an EOF blank line in `rpc_onboarding.py`; fixed and reran `git diff --check`, which passed.
  - Broader onboarding domain tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_rpc_onboarding_domain_boundaries.py tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_static_onboarding_views.py tests/test_onboarding/test_mutations.py tests/test_onboarding/test_flow.py tests/test_onboarding/test_router_specs.py tests/test_onboarding/test_search_specs.py tests/test_onboarding/test_channel_specs.py -q` passed, `175 passed in 1.19s`.
  - First child gate passed ruff/mypy/whitespace, then failed in `tests/test_search/test_search_runtime_boundary.py::test_gateway_configures_search_runtime_boundary` because the older architecture contract still expected `rpc_onboarding.py` to import `configure_search` directly. The test was updated so `rpc_onboarding_search.py` owns search runtime sync.
  - Search runtime boundary retest: `uv run --extra dev pytest tests/test_search/test_search_runtime_boundary.py::test_gateway_configures_search_runtime_boundary tests/test_gateway/test_rpc_onboarding_domain_boundaries.py::test_search_runtime_sync_is_owned_by_search_onboarding_boundary -q` passed, `2 passed in 0.30s`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 500 source files; whitespace passed; pytest passed with `2427 passed, 8 skipped, 2 warnings in 25.51s`; gateway smoke start/status/stop passed on `127.0.0.1:63650`.
  - Child release hygiene staged retest: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.37s`.
- Residual risk:
  - Low. This slice moves RPC registrations into sibling modules only; public method names/scopes and domain behavior remain covered by focused onboarding tests, public surface baseline, static setup view tests, and the full gate.
- Next recommended slice:
  - Continue Gateway RPC decomposition with any remaining broad files, or switch to Provider model status/catalog facade consolidation now that provider and onboarding runtime boundaries are thinner.
