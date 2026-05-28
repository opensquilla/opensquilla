# Provider Runtime Assembly Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Provider runtime selector/catalog/pricing/image assembly out of the Gateway bootstrap facade while preserving boot behavior and compatibility imports.

**Architecture:** Add `opensquilla.gateway.provider_runtime_assembly` as the service module that owns provider selector startup, OpenRouter model catalog/pricing refresh, base URL normalization, and image-generation runtime sync. Keep `opensquilla.gateway.provider_bootstrap` as the Gateway boot compatibility facade that re-exports the service entrypoints used by `boot.build_services()`.

**Tech Stack:** Python, GatewayConfig, effective LLM runtime config, provider selector, model catalog, image-generation runtime state, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-runtime-assembly-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-runtime-assembly-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was rechecked and still returned `agent thread limit reached`; this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate Provider runtime assembly service behavior from the Gateway bootstrap compatibility facade without changing provider selector startup, model catalog refresh, pricing refresh, image-generation runtime sync, provider defaults, or gateway boot behavior.

## Current-State Audit

- Current HEAD: `cab6959`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-sync-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/provider_bootstrap.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `gateway/boot.py`, `gateway/provider_bootstrap.py`, and `gateway/provider_runtime_sync.py`.
  - `build_provider_runtime_services`
  - `ProviderRuntimeServices`
  - `normalize_provider_base_url`
  - `_refresh_openrouter_catalog_and_pricing`
  - `build_provider_selector_from_runtime`
  - `sync_image_generation`
- Tests inspected:
  - Provider bootstrap boundary tests.
  - Provider runtime sync boundary tests.
  - Provider image-generation runtime boundary tests.
  - Gateway router boot tests.
- Existing boundary pattern this stage follows:
  - `boot.py` delegates to `provider_bootstrap.py`.
  - `provider_runtime_sync.py` owns provider selector/config materialization and image runtime sync side effects.
  - Provider RPC payload adaptation already lives in a Gateway facade.

## Boundary Decision

- Responsibilities moving out:
  - `ProviderRuntimeServices` bundle definition.
  - Provider base URL normalization used by runtime assembly.
  - Provider selector startup from effective LLM runtime config.
  - Model catalog creation and best-effort OpenRouter catalog refresh.
  - Best-effort OpenRouter live pricing refresh.
  - Best-effort image-generation runtime sync.
- Responsibilities staying in place:
  - `boot.py` continues to import `build_provider_runtime_services` from `provider_bootstrap.py`.
  - `provider_bootstrap.py` remains a compatibility facade for boot and any existing imports.
  - Effective LLM runtime/env/default resolution stays in `gateway/llm_runtime.py`.
  - Provider selector config materialization and image sync primitives stay in `provider_runtime_sync.py`.
  - Provider backend implementations and model catalog internals stay in `provider/`.
- New module/file responsibility:
  - `src/opensquilla/gateway/provider_runtime_assembly.py` owns provider runtime assembly service behavior.
- Public behavior that must not change:
  - Boot creates a provider selector only when an effective API key exists.
  - Base URLs ending in `/v1` are normalized before selector/catalog startup.
  - OpenRouter catalog and live pricing refresh remain best-effort and non-fatal.
  - Image-generation runtime sync remains best-effort and non-fatal.
  - Existing `opensquilla.gateway.provider_bootstrap` imports continue to work.
- Files explicitly out of scope:
  - Provider backend implementations.
  - Provider selector/factory behavior.
  - Provider RPC payload shapes.
  - CLI provider command text.
  - Web UI JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_assembly_boundary.py -q`
- Expected red failure:
  - `src/opensquilla/gateway/provider_runtime_assembly.py` does not exist.
  - `provider_bootstrap.py` still directly imports provider runtime sync helpers and `ModelCatalog`.
- Minimal implementation:
  - Create `provider_runtime_assembly.py` by moving the current provider runtime assembly service from `provider_bootstrap.py`.
  - Keep `provider_bootstrap.py` as a thin re-exporting facade.
  - Update existing provider bootstrap boundary tests to expect `provider_bootstrap -> provider_runtime_assembly -> provider_runtime_sync`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_bootstrap.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `docs/refactor/stages/2026-05-18-provider-runtime-assembly-boundary.md`
- Modify:
  - `src/opensquilla/gateway/provider_bootstrap.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
- Test:
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-provider-runtime-assembly-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-runtime-assembly-boundary`.
- [x] Write the failing provider runtime assembly boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible provider runtime assembly move.
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

- Revert the integration merge commit if provider selector startup, model catalog refresh, pricing refresh, image-generation runtime sync, or gateway smoke behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `916e1d5db64da8f8abc71925ec9ca786662a7f55`.
- Integration merge: `07022819cf85e7d132871f8e0283b9a35ab4d6dc`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-runtime-assembly-boundary` passed on branch `codex/refactor-provider-runtime-assembly-boundary` at `cab6959`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_assembly_boundary.py -q` failed as expected with `2 failed in 0.02s` because `src/opensquilla/gateway/provider_runtime_assembly.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q` passed with `12 passed in 3.28s`.
  - Broader Provider/Gateway boot/runtime group: `uv run --extra dev pytest tests/test_gateway/test_router_boot.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py tests/test_provider_runtime_status.py tests/test_provider_model_catalog.py tests/test_provider_model_listing.py -q` passed with `53 passed in 1.28s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_bootstrap.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py` passed.
  - Release hygiene spot check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed with `1 passed in 0.36s`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 506 source files; whitespace passed; pytest passed with `2443 passed, 8 skipped, 2 warnings in 49.99s`; gateway smoke start/status/stop passed on port `51487`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 506 source files; whitespace passed; pytest passed with `2445 passed, 6 skipped, 2 warnings in 26.95s`; gateway smoke start/status/stop passed on port `51621`.
- Residual risk:
  - Low. The slice preserves the `provider_bootstrap` import facade and moves existing assembly logic without changing selector/catalog/pricing/image runtime behavior.
- Next recommended slice:
  - Continue Provider cleanup at module granularity by consolidating provider model catalog/runtime status query services, or move to Tools/Channels service-boundary consolidation if provider boot/runtime is sufficiently thin.
