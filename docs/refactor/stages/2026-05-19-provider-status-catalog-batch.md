# Provider Status Catalog Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move remaining OpenRouter model catalog refresh orchestration into the provider catalog boundary while preserving provider status/model RPC payload compatibility and gateway startup behavior.

**Architecture:** Keep Gateway RPC routes thin and Gateway-owned wire payload adaptation in `opensquilla.gateway.provider_rpc_payloads`. Move OpenRouter catalog/pricing refresh orchestration from `opensquilla.gateway.provider_runtime_assembly` into `opensquilla.provider.model_catalog`, with Gateway passing only config-derived model IDs and the existing engine pricing callback.

**Tech Stack:** Python, Provider status reports, provider model listing rows, ModelCatalog, Gateway runtime assembly, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-status-catalog-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-status-catalog-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: External Codex worker for provider status/catalog/listing boundaries. This worker must not merge into integration.

## Goal

Further separate provider-domain status/catalog/listing materialization from Gateway route and startup code without changing public JSON/RPC payloads, provider defaults, public imports, route scopes, OpenRouter catalog refresh behavior, live pricing refresh behavior, or model/status filtering behavior.

## Current-State Audit

- Current HEAD: `3d9837d`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`
  - `docs/refactor/stages/2026-05-18-provider-selector-materialization-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-assembly-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-config-boundary.md`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/model_catalog.py`
  - `src/opensquilla/provider/__init__.py`
  - `src/opensquilla/gateway/provider_rpc_payloads.py`
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_rpc_models.py`
- Symbols or command surfaces inspected:
  - `providers.status`
  - `models.list`
  - `build_provider_status_report`
  - `build_provider_status_payload`
  - `build_provider_status_rpc_payload`
  - `list_provider_model_rows`
  - `list_provider_models_rpc_payload`
  - `ModelCatalog.fetch_openrouter`
  - `_refresh_openrouter_catalog_and_pricing`
  - `build_provider_runtime_services`
  - `refresh_live_prices`
- Tests inspected:
  - Provider status compatibility and Gateway delegation tests.
  - Provider model listing compatibility and Gateway model RPC tests.
  - Provider model catalog OpenRouter fetch tests.
  - Gateway provider runtime assembly boundary tests.
- Existing boundary pattern this stage follows:
  - Gateway RPC route modules register methods only and delegate payload construction to Gateway facades.
  - Provider modules own provider-domain reports, listing rows, selector materialization, runtime config, and model catalog data.
  - Compatibility wrappers remain where public Python imports already exist, without introducing Provider-to-Gateway imports.

## Boundary Decision

- Module batch:
  - Provider status/report materialization.
  - Provider model listing row materialization.
  - Provider model catalog refresh orchestration.
  - Gateway provider/model RPC payload facade and runtime assembly call sites.
- Responsibilities moving out:
  - OpenRouter catalog refresh timeout/error handling from Gateway runtime assembly.
  - OpenRouter live pricing refresh orchestration from Gateway runtime assembly, parameterized by a pricing callback so Provider does not import Engine.
- Responsibilities staying in place:
  - Gateway RPC request parsing and wire payload shape in `gateway.provider_rpc_payloads`.
  - Gateway route registration in `rpc_providers.py` and `rpc_models.py`.
  - GatewayConfig-specific pricing model ID extraction in `provider_runtime_assembly.py`.
  - Provider public compatibility wrappers in `runtime_status.py`, `model_listing.py`, and `provider.__init__`.
  - Model catalog data storage and `fetch_openrouter` HTTP details in `provider.model_catalog`.
- New module/file responsibility:
  - `opensquilla.provider.model_catalog.refresh_openrouter_catalog_and_pricing` owns best-effort OpenRouter catalog refresh and optional pricing callback execution.
- Public behavior that must not change:
  - `providers.status` and `models.list` JSON/RPC method names, scopes, request params, response keys, filtering, pricing shape, and model probe shape.
  - Existing imports from `opensquilla.provider` and provider submodules keep working.
  - OpenRouter catalog refresh remains best-effort and uses the same `/v1/models` endpoint behavior.
  - Live pricing refresh remains best-effort and receives the same active/router model IDs plus a base URL ending in `/v1`.
  - Gateway startup still creates selectors, model catalogs, image-generation runtime state, and provider defaults as before.
- Files explicitly out of scope:
  - Session-management modules.
  - Provider adapter implementation internals.
  - Provider selector/factory behavior beyond existing catalog refresh call sites.
  - CLI provider command text.
  - Web UI JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py -q`
- Expected red failure:
  - `ImportError` because `opensquilla.provider.model_catalog.refresh_openrouter_catalog_and_pricing` does not exist.
  - Gateway boundary assertions still find `_refresh_openrouter_catalog_and_pricing` in `provider_runtime_assembly.py` instead of provider-owned catalog refresh orchestration.
- Behavior compatibility coverage:
  - Provider catalog refresh invokes `ModelCatalog.fetch_openrouter` with existing `api_key`, `base_url`, and `proxy` arguments.
  - Pricing refresh callback receives the same model ID set and `base_url.rstrip('/') + '/v1'`.
  - Pricing refresh still runs even if catalog fetch fails, matching the previous independent best-effort blocks.
  - Gateway runtime assembly passes active model plus router tier models to the provider refresh boundary.
  - Existing provider status/model-list RPC facade and public import tests remain in the focused green group.
- Module-batch implementation:
  - Add provider-owned `refresh_openrouter_catalog_and_pricing`.
  - Replace Gateway `_refresh_openrouter_catalog_and_pricing` with a small GatewayConfig model-ID extractor plus a call to the provider function.
  - Keep Gateway route modules and provider compatibility wrappers behavior-compatible.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_gateway/test_rpc_models.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - None.
- Modify:
  - `src/opensquilla/provider/model_catalog.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
- Test:
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_gateway/test_rpc_models.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-provider-status-catalog-batch.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-status-catalog-batch`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if the slice regresses provider status, model listing, OpenRouter catalog refresh, pricing refresh, or gateway startup behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `3a67894c2c014f3fd353b26bf5b680eb7169aabc`.
- Integration merge: `49a6f0269214c34373245f31d924d36cf6e07d76`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-status-catalog-batch` passed on branch `codex/refactor-provider-status-catalog-batch` at `3d9837d`.
  - Red: `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py -q` failed during collection with `ImportError: cannot import name 'refresh_openrouter_catalog_and_pricing' from 'opensquilla.provider.model_catalog'`.
  - First focused green: `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py -q` passed with `8 passed in 2.33s`.
  - Focused compatibility group: `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_gateway/test_rpc_models.py -q` passed with `25 passed in 0.57s`.
  - First touched checks found import ordering issues in `provider_runtime_assembly.py` and `test_provider_runtime_assembly_boundary.py`, plus a mypy callback type mismatch against `refresh_live_prices`; these were corrected and retested.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py` passed.
  - Touched mypy: `uv run --extra dev mypy src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py --show-error-codes` passed with no issues in 2 source files.
  - Whitespace: `git diff --check` passed.
  - Final full child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 512 source files; whitespace passed; pytest passed with `2465 passed, 8 skipped, 2 warnings in 28.88s`; gateway smoke start/status/stop/status passed on `127.0.0.1:58098`.
  - Integration merge gate: `scripts/refactor_gate.sh` passed after merge `49a6f02`; ruff passed; mypy passed with no issues in 512 source files; whitespace passed; pytest passed with `2467 passed, 6 skipped, 2 warnings in 27.46s`; gateway smoke start/status/stop/status passed on `127.0.0.1:58424`.
  - Cleanup: current worktree inventory contains no active/provider/session refactor worker worktrees beyond the integration worktree; `git diff --check HEAD^ HEAD` passed for the latest integration record.
- Residual risk:
  - Low. The Provider catalog boundary now owns best-effort catalog/pricing refresh orchestration, but Gateway still supplies GatewayConfig-derived pricing model IDs and the existing engine pricing callback. Public provider compatibility wrappers and JSON/RPC payload facades were covered by focused tests and the full gate.
- Next recommended slice:
  - Continue with a coarser Gateway/provider cleanup batch around provider-facing onboarding specs and provider status UI/static access, preserving the existing `providers.status` and `models.list` RPC payload contracts.
