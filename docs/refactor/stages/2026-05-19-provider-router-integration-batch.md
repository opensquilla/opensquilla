# Provider Router Integration Batch Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: use `superpowers:writing-plans` before implementation. Use `superpowers:test-driven-development` for code or executable behavior and `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: provider-router-integration-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-router-integration-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread; native explore workers failed with 429, so local Serena/shell execution owns the shared GatewayConfig/provider seam.

## Goal

Move provider-router tier profile policy out of `gateway.config` into a provider-owned boundary while preserving all public GatewayConfig defaults, router profile validation, direct-provider profile migration, OpenRouter pricing/catalog model IDs, and squilla_router runtime behavior.

## Current-state audit

- Current HEAD: `0984087`.
- Worktree status: clean before creating this stage doc and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-provider-status-catalog-batch.md`
  - `docs/refactor/stages/2026-05-19-provider-runtime-model-contract-batch.md`
  - `src/opensquilla/gateway/config.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/provider/model_catalog.py`
  - `src/opensquilla/provider/registry.py`
  - `src/opensquilla/squilla_router/controller.py`
  - `tests/test_model_router_defaults.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_router_boot.py`
- Symbols or command surfaces inspected:
  - Serena overviews for `gateway.provider_runtime_assembly`, `provider.model_catalog`, `provider.factory`, and `squilla_router.controller`.
  - `ROUTER_TIER_PROFILE_IDS`, `_default_tiers`, `_router_tier_profile_defaults`, `SquillaRouterConfig`, and GatewayConfig router profile validators.
  - `openrouter_pricing_model_ids` and provider-owned OpenRouter catalog/pricing refresh.
- Tests inspected:
  - `tests/test_model_router_defaults.py`
  - `tests/test_model_router_behavior.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_router_boot.py`
- Existing boundary pattern this stage follows:
  - Provider modules own provider-domain catalog/status/model policy.
  - Gateway modules own Pydantic settings, wire payloads, and startup call sites.
  - Compatibility wrappers remain in `gateway.config` where tests or public imports already reach private helper names.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified worktree list; created fixed child worktree `../opensquilla-refactor-active` on branch `codex/refactor-provider-router-integration-batch`; ran `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-router-integration-batch --allow-dirty`.
- `superpowers:writing-plans`:
  - Evidence: read the skill; wrote this stage plan before production edits and before adding the provider-owned router profile module.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; first executable contract imports the not-yet-existing `opensquilla.provider.router_profiles` module and asserts GatewayConfig compatibility wrappers delegate to it.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; this stage will not be marked complete until focused tests, touched-file checks, child `scripts/refactor_gate.sh`, integration merge gate, cleanup, and ultragoal checkpoint evidence are recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` and `superpowers:subagent-driven-development` were read.
  - `spawn_agent` probe: two read-only explore agents were attempted for provider/router mapping and both failed with 429 Too Many Requests.
  - External worker fallback: not used for implementation because this batch targets one shared `gateway.config` provider policy seam; parallel workers would conflict in the same file.
- Historical evidence note:
  - Prior provider catalog/status stages already moved OpenRouter catalog refresh, pricing refresh, runtime status, and model listing. This stage intentionally avoids repeating those helpers and instead extracts router tier profile policy.

## Boundary decision

- Module batch: provider-router integration tier profile policy.
- Responsibilities moving out:
  - Router tier profile IDs, default tier dictionaries, profile-specific tier model/provider policy, and tier override merging move from `gateway.config` to `provider.router_profiles`.
- Responsibilities staying in place:
  - `GatewayConfig`, `SquillaRouterConfig`, env binding, Pydantic validators, public/private compatibility helper names in `gateway.config`, and direct-provider defaulting logic stay Gateway-owned.
  - OpenRouter catalog/pricing refresh remains provider-owned in `provider.model_catalog` with Gateway supplying runtime config.
  - `squilla_router` runtime scoring/controller behavior remains unchanged.
- New module/file responsibility:
  - `opensquilla.provider.router_profiles` owns provider-router profile policy and exposes immutable profile IDs plus factory functions returning fresh mutable tier dictionaries.
- Public behavior that must not change:
  - Default OpenRouter tiers and direct-provider tier defaults.
  - Validation errors for unknown or provider-mismatched profiles.
  - Legacy direct-provider OpenRouter default migration.
  - OpenRouter pricing model ID collection from router tiers.
  - CLI/RPC/WebSocket/provider request behavior.
- Files explicitly out of scope:
  - Binary router model artifacts.
  - Provider adapter request payload internals.
  - CLI text, Web UI assets, channel ingress, session/runtime backplanes.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.provider.router_profiles'` before production implementation.
- Behavior compatibility coverage:
  - New provider router profile tests assert provider-owned defaults are fresh-copy, match Gateway compatibility wrappers, include the public profile ID set, and feed OpenRouter pricing model ID collection.
  - Existing `test_model_router_defaults.py` covers GatewayConfig default/migration/validation behavior.
  - Existing `test_provider_model_catalog.py` covers pricing model ID behavior and OpenRouter refresh.
- Module-batch implementation:
  - Add `provider.router_profiles`.
  - Replace GatewayConfig inline policy with imports/wrappers from provider boundary.
  - Preserve `_default_tiers`, `ROUTER_TIER_PROFILE_IDS`, `_merge_tier_dicts`, and `_router_tier_profile_defaults` as compatibility names in `gateway.config`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_router_boot.py tests/test_model_router_behavior.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/router_profiles.py src/opensquilla/gateway/config.py tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py`
  - `uv run --extra dev mypy src/opensquilla/provider/router_profiles.py src/opensquilla/gateway/config.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/provider/router_profiles.py`
  - `tests/test_provider_router_profiles.py`
- Modify:
  - `src/opensquilla/gateway/config.py`
  - `docs/refactor/stages/2026-05-19-provider-router-integration-batch.md`
- Test:
  - `tests/test_provider_router_profiles.py`
  - `tests/test_model_router_defaults.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_model_router_behavior.py`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-router-integration-batch --allow-dirty`.
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

- Revert the integration merge commit if the slice regresses router profile defaults, direct-provider migration, OpenRouter pricing models, or provider startup behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `8de6884cc5b324617fb8877b150d12216715b5ca`.
- Integration merge: `1e4e5b42f3d43e6f1253cf84905e420da8b46449`.
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-router-integration-batch --allow-dirty` passed on child branch at `0984087`.
  - RED: `uv run --extra dev pytest tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py -q` failed during collection with `ModuleNotFoundError: No module named 'opensquilla.provider.router_profiles'`.
  - First focused GREEN: the same command passed with `40 passed in 0.77s` after adding `provider.router_profiles` and GatewayConfig wrappers.
  - Focused provider/router compatibility: `uv run --extra dev pytest tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_router_boot.py tests/test_model_router_behavior.py -q` passed with `82 passed, 2 skipped in 2.17s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/provider/router_profiles.py src/opensquilla/gateway/config.py tests/test_provider_router_profiles.py tests/test_model_router_defaults.py tests/test_provider_model_catalog.py` passed.
  - Touched mypy: `uv run --extra dev mypy src/opensquilla/provider/router_profiles.py src/opensquilla/gateway/config.py --show-error-codes` passed with no issues in 2 source files.
  - Whitespace: `git diff --check` passed.
  - Child full gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 581 source files; whitespace passed; pytest passed with `2834 passed, 8 skipped, 2 warnings in 34.64s`; gateway smoke start/status/stop/status passed on loopback port `64693`.
  - Integration merge: `git merge --no-ff codex/refactor-provider-router-integration-batch` produced merge `1e4e5b42f3d43e6f1253cf84905e420da8b46449`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 581 source files; whitespace passed; pytest passed with `2836 passed, 6 skipped, 2 warnings in 29.31s`; gateway smoke start/status/stop/status passed on loopback port `64810`.
  - Release hygiene for final evidence doc: `uv run --extra dev pytest tests/test_public_release_hygiene.py -q` passed with `9 passed in 0.50s`; `git diff --check` passed.
  - Cleanup: `git worktree remove ../opensquilla-refactor-active && git worktree prune` succeeded; worktree inventory has no `../opensquilla-refactor-active` entry.
- Residual risk:
  - Low. Router tier profile data moved without changing GatewayConfig compatibility helper names or existing squilla_router/provider behavior; full gate and focused router/provider tests passed.
- Next recommended slice:
  - G005 contracts adoption/backplane batch: use the same coarse-stage workflow to adopt shared contract/backplane boundaries without changing RPC/CLI/WebSocket behavior.
