# Provider Selector Materialization Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move provider selector materialization from gateway runtime sync into the provider layer while preserving gateway sync and boot compatibility.

**Architecture:** Add `opensquilla.provider.selector_materialization` as the provider-owned boundary that converts effective runtime configs into `ProviderConfig` and `ModelSelector`. Keep `opensquilla.gateway.provider_runtime_sync` as the gateway RPC-facing synchronization boundary and compatibility facade, delegating selector materialization to provider-owned code.

**Tech Stack:** Python, ProviderConfig, SelectorConfig, ModelSelector, LlmRuntimeConfig, gateway runtime sync/assembly, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-selector-materialization-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-selector-materialization-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was re-verified for this stage and still fails with `collab spawn failed: agent thread limit reached`, so this stage uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate provider selector materialization from gateway sync code without changing provider selector config fields, normalized base-url overrides, provider routing preservation, RPC config sync behavior, provider runtime assembly, or gateway smoke behavior.

## Current-State Audit

- Current HEAD: `b5d2bf0`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-config-boundary.md`
  - `src/opensquilla/provider/selector.py`
  - `src/opensquilla/provider/runtime_config.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_provider_factory.py`
- Symbols or command surfaces inspected:
  - `ProviderConfig`
  - `SelectorConfig`
  - `ModelSelector`
  - `LlmRuntimeConfig`
  - `provider_config_from_runtime`
  - `build_provider_selector_from_runtime`
  - `sync_provider_selector`
  - `build_provider_runtime_services`
- Tests inspected:
  - Provider runtime sync boundary tests.
  - Provider runtime assembly boundary tests.
  - Gateway boot provider env tests.
  - Provider factory tests.
- Existing boundary pattern this stage follows:
  - `provider.runtime_config` owns provider runtime credential/routing resolution.
  - `gateway.provider_runtime_sync` owns RPC-facing runtime synchronization.
  - `gateway.provider_runtime_assembly` owns boot composition and catalog/image sync.

## Boundary Decision

- Durable refactor cadence:
  - Update `AGENTS.md`, `docs/refactor/overall-plan.md`, and
    `docs/refactor/stage-template.md` so future stages default to larger
    module-family batches and the fixed sibling active worktree path, without
    embedding local user home paths in public files.
- Responsibilities moving out:
  - Converting `LlmRuntimeConfig`-like objects into `ProviderConfig`.
  - Creating `ModelSelector`/`SelectorConfig` from runtime provider config.
- Responsibilities staying in place:
  - Runtime secret inheritance/clearing in gateway RPC config sync.
  - Calling `resolve_llm_runtime_config` and `selector.sync_primary` from gateway sync.
  - Image-generation runtime sync from gateway config.
  - Gateway compatibility exports for existing imports of `provider_config_from_runtime` and `build_provider_selector_from_runtime`.
- New module/file responsibility:
  - `src/opensquilla/provider/selector_materialization.py` owns provider selector materialization from runtime config.
- Public behavior that must not change:
  - `from opensquilla.gateway.provider_runtime_sync import build_provider_selector_from_runtime` keeps working.
  - `build_provider_selector_from_runtime(runtime, base_url=...)` preserves provider, model, api_key, normalized base_url, proxy, and provider_routing.
  - `sync_provider_selector` still resolves effective runtime env/config and calls `selector.sync_primary`.
  - `build_provider_runtime_services` still creates a selector when a runtime API key exists.
- Files explicitly out of scope:
  - Provider adapter construction/factory internals.
  - Runtime credential/env resolution already moved to `provider.runtime_config`.
  - Provider status/model-listing payloads.
  - Web UI provider views.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.provider.selector_materialization'`.
  - `gateway/provider_runtime_sync.py` still owns top-level selector materialization helpers.
- Minimal implementation:
  - Create `opensquilla.provider.selector_materialization`.
  - Move `provider_config_from_runtime` and `build_provider_selector_from_runtime` there.
  - Update `gateway.provider_runtime_sync` to import and re-export those helpers.
  - Update `gateway.provider_runtime_assembly` to import the helper from the provider boundary.
  - Update boundary tests to assert gateway sync no longer imports selector primitives directly.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_router_boot.py tests/test_provider_factory.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/selector_materialization.py src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/provider_runtime_assembly.py tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/provider src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/provider_runtime_assembly.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/provider/selector_materialization.py`
  - `tests/test_provider_selector_materialization_boundary.py`
  - `docs/refactor/stages/2026-05-18-provider-selector-materialization-boundary.md`
- Modify:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
- Test:
  - `tests/test_provider_selector_materialization_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_provider_factory.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-provider-selector-materialization-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-selector-materialization-boundary`.
- [x] Write the failing provider selector materialization boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the behavior-compatible provider selector materialization boundary.
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

- Red: `uv run --extra dev pytest tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py -q` failed as expected with `ModuleNotFoundError: No module named 'opensquilla.provider.selector_materialization'`.
- Focused green: `uv run --extra dev pytest tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_router_boot.py tests/test_provider_factory.py -q` passed with `42 passed in 0.60s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/provider/selector_materialization.py src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/provider_runtime_assembly.py tests/test_provider_selector_materialization_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py` passed.
- Touched mypy: `uv run --extra dev mypy src/opensquilla/provider src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/provider_runtime_assembly.py --show-error-codes` passed with no issues in 26 source files.
- Whitespace: `git diff --check` passed.
- Release/refactor hygiene spot check after durable cadence docs changed: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths tests/test_scripts/test_refactor_hooks.py::test_refactor_control_assets_do_not_embed_local_user_paths -q` passed with `2 passed in 0.32s`.
- First child gate found the durable cadence docs had embedded local user home paths; `AGENTS.md`, `docs/refactor/overall-plan.md`, and `docs/refactor/stage-template.md` were corrected to use sibling paths.
- Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 512 source files; whitespace passed; pytest passed with `2462 passed, 8 skipped, 2 warnings in 25.13s`; gateway smoke start/status/stop/status passed on `127.0.0.1:56093`.

## Integration Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if selector config fields, selector sync, provider runtime assembly, runtime env behavior, or gateway smoke behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
- Residual risk:
- Next recommended slice:
