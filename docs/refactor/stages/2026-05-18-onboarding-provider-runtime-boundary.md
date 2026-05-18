# Onboarding Provider Runtime Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split provider-facing onboarding mutation RPCs out of the broad onboarding RPC module while preserving public onboarding method names, config persistence, provider selector sync, image-generation runtime sync, and Web UI behavior.

**Architecture:** Add `opensquilla.gateway.rpc_onboarding_providers` as the provider-specific onboarding RPC registration module. Keep shared onboarding helpers in `rpc_onboarding.py`; provider/image-generation mutations delegate runtime side effects through `gateway.provider_runtime_sync`.

**Tech Stack:** Python, Gateway RPC registry, GatewayConfig, onboarding mutation payloads, provider runtime sync, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: onboarding-provider-runtime-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-onboarding-provider-runtime-boundary`
- Child worktree: `../opensquilla-refactor-active-onboarding-provider-runtime`
- Owner: Codex main thread. Current agent runtime still reports stale shutdown entries / thread-limit behavior, so this slice uses the documented sequential fallback and keeps one active child worktree.

## Goal

Extract provider-specific onboarding RPC mutation handlers from `rpc_onboarding.py` into a focused provider onboarding boundary without changing public RPC method names/scopes, Web UI setup calls, runtime-only secret behavior, provider selector sync, image-generation runtime sync, persisted config redaction, or CLI behavior.

## Current-State Audit

- Current HEAD: `b8499da`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `rpc_onboarding.py` and `provider_runtime_sync.py`.
  - Serena `find_symbol` for `_provider_configure`, `_image_generation_configure`, `_sync_provider_selector`, `_sync_image_generation`, and `_apply_inplace`.
  - RPC method names `onboarding.provider.configure` and `onboarding.imageGeneration.configure`.
- Tests inspected:
  - Provider configure RPC tests in `tests/test_gateway/test_rpc_onboarding.py`.
  - Image-generation configure RPC tests in `tests/test_gateway/test_rpc_onboarding.py`.
  - Provider runtime sync boundary tests.
  - Image-generation runtime boundary tests.
- Existing boundary pattern this stage follows:
  - `rpc/__init__.py` imports sibling `rpc_*` modules to register method handlers at boot.
  - Prior RPC domain slices move domain-specific method registrations into focused modules while preserving method names/scopes.

## Boundary Decision

- Responsibilities moving out:
  - `onboarding.provider.configure` handler registration and provider mutation flow.
  - `onboarding.imageGeneration.configure` handler registration and image-generation mutation flow.
  - Provider/image-generation runtime side-effect calls for these onboarding mutations.
- Responsibilities staying in place:
  - Onboarding status/catalog/router/channel/search/memory RPC handlers stay in `rpc_onboarding.py`.
  - Shared active-config, config-path, in-place apply, persistence, and parameter requirement helpers stay in `rpc_onboarding.py`.
  - Runtime selector/materialization and image-generation sync stay in `provider_runtime_sync.py`.
  - Onboarding mutation business logic stays in `opensquilla.onboarding.mutations`.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_onboarding_providers.py` owns provider-specific onboarding mutation RPC registration.
- Public behavior that must not change:
  - RPC methods `onboarding.provider.configure` and `onboarding.imageGeneration.configure` keep the same names, scopes, payloads, redaction, persistence, and warnings.
  - Provider selector sync still uses env-resolved runtime config after provider/router changes.
  - Image-generation runtime sync still updates runtime tool availability after provider/image-generation changes.
  - Web UI setup calls and public surface baseline stay unchanged.
- Files explicitly out of scope:
  - CLI onboarding/provider workflows.
  - Web UI JavaScript.
  - Provider backend implementations.
  - Search/channel/router/memory onboarding behavior beyond existing helper imports.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_provider_boundary.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/rpc_onboarding_providers.py` does not exist.
  - `rpc_onboarding.py` still registers provider/image-generation configure methods.
  - `rpc_onboarding.py` still imports image-generation runtime directly.
- Minimal implementation:
  - Create `gateway/rpc_onboarding_providers.py`.
  - Move provider and image-generation configure handlers into the new module.
  - Import shared helpers from `rpc_onboarding.py`.
  - Delegate runtime side effects through `provider_runtime_sync.sync_provider_selector` and `provider_runtime_sync.sync_image_generation`.
  - Import the new module from `gateway/rpc/__init__.py` after `rpc_onboarding`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc/__init__.py src/opensquilla/gateway/rpc_onboarding.py src/opensquilla/gateway/rpc_onboarding_providers.py tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_onboarding.py tests/test_provider_image_generation_runtime_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_onboarding_providers.py`
  - `tests/test_gateway/test_rpc_onboarding_provider_boundary.py`
  - `docs/refactor/stages/2026-05-18-onboarding-provider-runtime-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
- Test:
  - `tests/test_gateway/test_rpc_onboarding_provider_boundary.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-onboarding-provider-runtime-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-onboarding-provider-runtime-boundary`.
- [x] Write the failing provider onboarding boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible boundary move.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

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

- Revert the integration merge commit if onboarding provider/image-generation RPC behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `c11c181` (`Extract onboarding provider RPC boundary`)
- Integration merge: `b1415e9` (`Merge onboarding provider runtime boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-onboarding-provider-runtime-boundary` passed on branch `codex/refactor-onboarding-provider-runtime-boundary` at `b8499da`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_provider_boundary.py -q` failed as expected with `2 failed` because `rpc_onboarding_providers.py` did not exist and `rpc/__init__.py` did not import it.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q` passed, `38 passed in 4.00s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc/__init__.py src/opensquilla/gateway/rpc_onboarding.py src/opensquilla/gateway/rpc_onboarding_providers.py tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_onboarding.py tests/test_provider_image_generation_runtime_boundary.py` passed.
  - Whitespace: `git diff --check` passed.
  - Broader onboarding/provider/public surface tests: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_rpc_onboarding_provider_boundary.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_static_onboarding_views.py tests/test_onboarding/test_mutations.py tests/test_onboarding/test_flow.py tests/test_provider_image_generation_runtime_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py -q` passed, `125 passed in 1.32s`.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 496 source files; whitespace passed; pytest passed with `2424 passed, 8 skipped, 2 warnings in 51.26s`; gateway smoke start/status/stop passed on `127.0.0.1:62810`.
  - Child release hygiene staged retest: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.31s`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `b8499da`.
  - Integration merge: `git merge --no-ff codex/refactor-onboarding-provider-runtime-boundary` produced merge commit `b1415e9`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 496 source files; whitespace passed; pytest passed with `2426 passed, 6 skipped, 2 warnings in 27.36s`; gateway smoke start/status/stop passed on `127.0.0.1:62972`.
- Residual risk:
  - Low. The slice moves only provider-specific onboarding RPC registrations; public method names/scopes remain covered by the public surface baseline and focused onboarding RPC tests.
- Next recommended slice:
  - Continue Gateway onboarding decomposition by moving search/channel/router onboarding domains into focused modules, or switch to Provider model status/catalog facade consolidation if the next module-level cut should stay in Provider.
