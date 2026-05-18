# Provider RPC Payload Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move provider-facing Gateway RPC payload adaptation for `providers.status` and `models.list` behind a Gateway facade while preserving public RPC payloads and provider compatibility wrappers.

**Architecture:** Add `opensquilla.gateway.provider_rpc_payloads` as the Gateway-owned adapter for provider status and model-list RPC request parsing and wire payloads. Keep `opensquilla.provider.runtime_status` and `opensquilla.provider.model_listing` focused on provider-domain reports/model rows, with thin compatibility wrappers for existing Python imports and no `provider -> gateway` import edge.

**Tech Stack:** Python, Gateway RPC dispatcher, provider status reports, provider model rows, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-rpc-payload-facade
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-rpc-payload-facade`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was rechecked after the previous cleanup and still returned `agent thread limit reached`; this stage therefore uses the documented sequential fallback with one fixed active child worktree.

## Goal

Consolidate provider status and model-list Gateway RPC wire adaptation into a Gateway-owned facade without changing RPC method names, scopes, request parameters, response keys, provider report semantics, model filtering, compatibility imports, CLI behavior, Web UI behavior, or release hygiene.

## Current-State Audit

- Current HEAD: `87db738`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-gateway-rpc-domain-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`
  - `docs/refactor/stages/2026-05-18-onboarding-domain-boundaries.md`
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/__init__.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_gateway/test_rpc_models.py`
  - `tests/test_gateway/test_rpc_domain_modules.py`
- Symbols or command surfaces inspected:
  - `providers.status`
  - `models.list`
  - `build_provider_status_report`
  - `build_provider_status_rpc_payload`
  - `list_provider_model_rows`
  - `list_provider_models_rpc_payload`
  - `ProviderStatusReport`, `ProviderStatusRow`, `ProviderModelProbe`, and `ProviderModelRow`
- Tests inspected:
  - Provider status report and Gateway delegation tests.
  - Provider model listing tests.
  - Gateway RPC model payload tests.
  - Public RPC domain registration tests.
- Existing boundary pattern this stage follows:
  - Gateway RPC modules own method registration.
  - Provider modules own provider-domain state and rows.
  - Compatibility wrappers may remain while Gateway stops depending on provider-owned RPC wire helpers.

## Boundary Decision

- Responsibilities moving out:
  - Provider status RPC request parameter validation.
  - Provider status report to wire-payload conversion.
  - Provider model list RPC request parameter validation.
  - Provider model row to wire-payload conversion.
- Responsibilities staying in place:
  - Provider active/configured/buildable status report construction.
  - Provider model row normalization and filtering.
  - Provider selector/model probing behavior.
  - Public compatibility imports for recently exposed Python helpers.
- New module/file responsibility:
  - `src/opensquilla/gateway/provider_rpc_payloads.py` owns Gateway provider/model RPC payload adaptation.
- Public behavior that must not change:
  - `providers.status` and `models.list` method names and scopes stay unchanged.
  - `providers.status` still accepts `provider` and `probeModels`.
  - `models.list` still accepts `provider` and `capabilities`.
  - Response keys, pricing shape, model probe shape, filtering, and redaction stay unchanged.
  - Provider Python compatibility wrappers keep working for external callers.
- Files explicitly out of scope:
  - Provider backend adapters.
  - Provider selector/factory behavior.
  - Model catalog fetch/pricing refresh.
  - CLI provider command text.
  - Web UI JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py -q`
- Expected red failure:
  - `opensquilla.gateway.provider_rpc_payloads` does not exist.
  - `rpc_providers.py` still imports `build_provider_status_rpc_payload` from `opensquilla.provider.runtime_status`.
  - `rpc_models.py` still imports `list_provider_models_rpc_payload` from `opensquilla.provider.model_listing`.
  - Provider modules still own private RPC request/wire helper functions.
- Minimal implementation:
  - Create `opensquilla.gateway.provider_rpc_payloads`.
  - Move RPC request parsing and wire conversion helpers into the facade.
  - Point `rpc_providers.py` and `rpc_models.py` at the facade.
  - Leave provider report/model-row builders in provider modules.
  - Leave thin provider compatibility wrappers without importing Gateway from Provider.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_rpc_domain_modules.py tests/test_gateway/test_rpc_public_surface_baseline.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/provider_rpc_payloads.py src/opensquilla/gateway/rpc_providers.py src/opensquilla/gateway/rpc_models.py src/opensquilla/provider/runtime_status.py src/opensquilla/provider/model_listing.py src/opensquilla/provider/__init__.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_gateway/test_rpc_models.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/provider_rpc_payloads.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`
- Modify:
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/__init__.py`
- Test:
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_gateway/test_rpc_models.py`
  - `tests/test_gateway/test_rpc_domain_modules.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-rpc-payload-facade`.
- [x] Write the failing Gateway provider RPC payload facade tests.
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

- Revert the integration merge commit if provider status or model-list RPC payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `2b12449 Move provider RPC payloads behind gateway facade`.
- Integration merge: `9661c35 Merge provider RPC payload facade`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-rpc-payload-facade` passed on branch `codex/refactor-provider-rpc-payload-facade` at `87db738`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py -q` failed as expected during collection with `ModuleNotFoundError: No module named 'opensquilla.gateway.provider_rpc_payloads'`.
  - First focused green: `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py -q` passed, `4 passed in 0.48s`.
  - Focused compatibility group: `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_rpc_domain_modules.py tests/test_gateway/test_rpc_public_surface_baseline.py -q` passed, `20 passed in 0.54s`.
  - Touched ruff initially found import ordering in `rpc_models.py` and `rpc_providers.py`; imports were sorted and rerun passed. `git diff --check` passed.
  - Broader provider/RPC group: `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_rpc_domain_modules.py tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_provider_factory.py tests/test_provider_model_catalog.py -q` passed, `50 passed in 5.11s`.
  - First child gate passed ruff/mypy/whitespace, then failed in `tests/test_ci/test_architecture_import_contracts.py::test_package_imports_do_not_add_new_edges` because provider compatibility wrappers introduced an unapproved `provider->gateway` import edge.
  - Import contract fix: provider compatibility wrappers now avoid importing Gateway; the Gateway facade remains the production RPC payload owner.
  - Architecture retest: `uv run --extra dev pytest tests/test_ci/test_architecture_import_contracts.py::test_package_imports_do_not_add_new_edges tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py -q` passed, `16 passed in 0.92s`.
  - Expanded focused retest: `uv run --extra dev pytest tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_rpc_domain_modules.py tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_tools_visibility.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_provider_factory.py tests/test_provider_model_catalog.py tests/test_ci/test_architecture_import_contracts.py -q` passed, `54 passed in 2.06s`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 501 source files; whitespace passed; pytest passed with `2431 passed, 8 skipped, 2 warnings in 25.29s`; gateway smoke start/status/stop passed on `127.0.0.1:64712`.
  - Child release hygiene staged retest: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.30s`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `87db738`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 501 source files; whitespace passed; pytest passed with `2433 passed, 6 skipped, 2 warnings in 26.56s`; gateway smoke start/status/stop passed on `127.0.0.1:64897`.
  - Cleanup policy: this slice used the fixed active child worktree path and removes it after the integration record commit so temporary directories do not accumulate.
- Residual risk:
  - Low. Public RPC payloads are covered by the new Gateway facade tests, existing RPC model tests, provider compatibility tests, public surface baseline, architecture import contract, and full child gate. Provider compatibility wrappers intentionally mirror the payload shape without creating a reverse Provider-to-Gateway dependency.
- Next recommended slice:
  - Continue with larger module-level boundaries using the single fixed active child worktree pattern, then merge, record, and remove the active worktree after every slice.
