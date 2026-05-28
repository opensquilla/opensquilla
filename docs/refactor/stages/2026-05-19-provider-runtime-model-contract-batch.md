# Provider Runtime Model Contract Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` for same-thread workers or `superpowers:executing-plans` if same-thread agents become unavailable. Each worker must use `superpowers:test-driven-development` and record RED/GREEN evidence. This stage must record concrete Superpowers evidence per worker slice.

**Goal:** Refactor provider runtime status, provider model listing, catalog refresh, and CLI provider/model command contracts into clearer behavior-compatible boundaries while preserving provider defaults, OpenRouter routing, pricing refresh, public RPC wire shapes, and CLI output.

**Architecture:** Use one active child integration worktree and independent worker branches for disjoint provider subdomains. Provider-domain workers own typed request/query or report boundaries; CLI workers own gateway-backed CLI workflow boundaries. The main thread owns stage planning, shared gateway payload facade review, worker merge order, full gates, integration merge, and cleanup.

**Tech Stack:** Python 3.12+, provider selector/model catalog/runtime status modules, Gateway RPC payload facade, Typer CLI workflows, pytest behavior and AST boundary tests, Ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: provider-runtime-model-contract-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-runtime-model-contract-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker dispatch, review, integration merge, full gates, stage record, and cleanup. Same-thread `spawn_agent` healthcheck succeeded with agent `019e3c3d-16db-7840-a3ec-de4fc4e95ced`.

## Goal

Refactor Provider module-family contracts as one coarse batch:

- keep provider runtime status computation provider-owned and distinguish domain reports from gateway RPC wire shape;
- keep provider model listing provider-owned and distinguish model row/query behavior from gateway RPC wire shape;
- keep OpenRouter catalog/pricing refresh and provider runtime assembly behavior stable;
- keep CLI provider/model workflows backed by small query/presenter boundaries rather than inline command logic;
- preserve public RPC method names, public wire keys, provider defaults, usage/pricing behavior, and CLI text/JSON behavior.

## Current-state audit

- Current HEAD: `a034c6f`.
- Worktree status: clean before creating this stage plan.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-sync-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-assembly-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-selector-materialization-boundary.md`
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`
  - `docs/refactor/stages/2026-05-19-webui-rpc-view-state-contract-batch.md`
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/provider/model_catalog.py`
  - `src/opensquilla/gateway/provider_rpc_payloads.py`
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/cli/providers_gateway_queries.py`
  - `src/opensquilla/cli/providers_workflows.py`
  - `src/opensquilla/cli/providers_presenters.py`
  - `src/opensquilla/cli/models_gateway_queries.py`
  - `src/opensquilla/cli/models_workflows.py`
  - `src/opensquilla/cli/models_presenters.py`
- Symbols or command surfaces inspected:
  - Serena overview for `provider.model_listing`, `provider.runtime_status`, `gateway.provider_rpc_payloads`, `gateway.rpc_providers`, `gateway.rpc_models`, `cli.providers_workflows`, and `cli.models_workflows`.
  - Provider runtime report dataclasses and model listing row normalization.
  - Gateway provider/model RPC facade functions and CLI gateway query helpers.
- Tests inspected:
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_models.py`
  - `tests/test_gateway/test_rpc_providers.py` if present during worker audit
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_cli/test_providers_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
- Existing boundary pattern this stage follows:
  - Provider-owned modules should own domain rows/reports/query behavior.
  - Gateway-owned `provider_rpc_payloads.py` should own RPC request validation and wire key conversion.
  - CLI command modules should delegate to gateway query/workflow/presenter modules.
  - Existing compatibility wrappers may remain when public imports depend on them, but new tests should lock the preferred owner.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified integration state; created fixed active child worktree at `../opensquilla-refactor-active` on branch `codex/refactor-provider-runtime-model-contract-batch`.
- `superpowers:writing-plans`:
  - Evidence: read the skill; created this stage plan before worker implementation; plan includes exact ownership, TDD commands, gates, merge review, and cleanup.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; every worker must write a failing provider/static/CLI boundary test first and record expected RED failure before implementation.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; stage cannot be claimed complete until focused worker tests, touched-file checks, child `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, and cleanup audit are recorded.
- `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development`:
  - Evidence: read the skills; same-thread `spawn_agent` healthcheck succeeded with agent `019e3c3d-16db-7840-a3ec-de4fc4e95ced`; this stage will dispatch independent worker agents with separate branches/worktrees.
- Parallelism decision:
  - Use multi-agent, multi-branch execution because provider status, model listing, catalog/assembly, and CLI workflow files are mostly disjoint.
  - Keep `src/opensquilla/gateway/provider_rpc_payloads.py` owned by the main thread unless a worker explicitly stops and requests coordination, because it bridges status and model listing outputs.
  - If same-thread spawning fails later, use `scripts/refactor_external_agent.sh` fixed worker slots before sequential fallback.
- Historical evidence note:
  - The user explicitly required every large refactor substage to use and record Superpowers. Treat missing per-worker Superpowers/TDD evidence as a stage-record gap.

## Boundary decision

- Module batch:
  - `provider-runtime-model-contract-batch`
- Responsibilities moving out or clarifying:
  - Provider runtime status query/report behavior in `provider.runtime_status`.
  - Provider model listing query/row behavior in `provider.model_listing`.
  - Catalog refresh and pricing refresh behavior around `provider.model_catalog` and `gateway.provider_runtime_assembly`.
  - CLI provider/model command workflows through gateway query and presenter boundaries.
  - Gateway RPC facade ownership for public wire keys remains in `gateway.provider_rpc_payloads`.
- Responsibilities staying in place:
  - Public RPC names: `providers.status`, `models.list`.
  - Public wire keys: `activeProvider`, `providerId`, `contextWindow`, `inputPer1k`, `outputPer1k`, `probeModels`.
  - Provider defaults, direct-provider OpenRouter routing, API-key/base-url resolution, OpenRouter pricing refresh, and CLI output text/JSON.
- New module/file responsibility:
  - Workers may add focused dataclasses or helper functions inside their owned modules if a RED test proves ownership and behavior.
  - Main thread may update `gateway.provider_rpc_payloads.py` after worker merges to consume new provider-domain helpers without creating cross-worker conflicts.
- Public behavior that must not change:
  - Provider configuration must not leak API keys in repr/stdout.
  - Unknown provider filters must still raise the existing validation errors.
  - Selector failures and unavailable selectors must keep current empty/error payload semantics.
  - CLI provider/model commands must preserve JSON and table output behavior.
- Files explicitly out of scope:
  - Web UI static assets completed in the previous batch.
  - Channel/search/skills/tool runtime surfaces.
  - Provider backend request payload internals for OpenAI/Anthropic/OpenRouter unless a focused test proves a direct dependency.
  - Binary router model artifacts under `src/opensquilla/squilla_router/models/`.

## Parallel Worker Ownership

- Worker `provider-status-domain` owns:
  - `src/opensquilla/provider/runtime_status.py`
  - `tests/test_provider_runtime_status.py`
  - Optional static assertions in `tests/test_gateway/test_provider_rpc_payload_facade.py` only if they check that gateway facade remains the wire owner.
- Worker `provider-model-listing-domain` owns:
  - `src/opensquilla/provider/model_listing.py`
  - `tests/test_provider_model_listing.py`
  - Optional static assertions in `tests/test_gateway/test_provider_rpc_payload_facade.py` only if they check that gateway facade remains the wire owner.
- Worker `provider-catalog-assembly` owns:
  - `src/opensquilla/provider/model_catalog.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `tests/test_provider_model_catalog.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_provider_image_generation_runtime_boundary.py` only if the catalog/assembly boundary requires it.
- Worker `provider-cli-workflows` owns:
  - `src/opensquilla/cli/providers_gateway_queries.py`
  - `src/opensquilla/cli/providers_workflows.py`
  - `src/opensquilla/cli/providers_presenters.py`
  - `src/opensquilla/cli/models_gateway_queries.py`
  - `src/opensquilla/cli/models_workflows.py`
  - `src/opensquilla/cli/models_presenters.py`
  - `tests/test_cli/test_providers_cmd.py`
  - `tests/test_cli/test_cli_product_completeness.py`
  - New focused CLI boundary tests under `tests/test_cli/` if needed.

Workers are not alone in the codebase. Each worker must preserve other workers' edits, avoid shared-file changes outside ownership, and not revert unrelated changes. If a worker needs `src/opensquilla/gateway/provider_rpc_payloads.py`, it must stop and report instead of editing it.

## TDD Red/Green

- Failing test commands:
  - Provider status: `uv run --extra dev pytest tests/test_provider_runtime_status.py tests/test_gateway/test_provider_rpc_payload_facade.py -q`
  - Provider model listing: `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py -q`
  - Provider catalog/assembly: `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q`
  - Provider CLI workflows: `uv run --extra dev pytest tests/test_cli/test_providers_cmd.py tests/test_cli/test_cli_product_completeness.py -q`
- Expected red failures:
  - New provider-domain query/report boundary tests fail because the helper/dataclass/delegation does not exist yet.
  - New CLI workflow tests fail because request construction or presenter ownership is still inline or unproven.
  - New catalog/assembly tests fail because catalog refresh policy or assembly delegation helper does not exist yet.
- Behavior compatibility coverage:
  - Worker suites above.
  - `tests/test_gateway/test_rpc_models.py` and provider RPC facade tests for public wire shape.
  - `tests/test_provider_model_catalog.py` and provider runtime assembly tests for OpenRouter catalog/pricing behavior.
- Module-batch implementation:
  - Move or clarify one coherent ownership boundary per worker.
  - Preserve provider defaults, public wire shape, and CLI text/JSON behavior.
  - Keep worker changes within ownership.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py tests/test_provider_runtime_config_boundary.py tests/test_provider_selector_materialization_boundary.py tests/test_provider_runtime_status.py tests/test_provider_model_catalog.py tests/test_cli/test_providers_cmd.py tests/test_cli/test_cli_product_completeness.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/model_listing.py src/opensquilla/provider/runtime_status.py src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_rpc_payloads.py src/opensquilla/gateway/rpc_providers.py src/opensquilla/gateway/rpc_models.py src/opensquilla/cli/providers_gateway_queries.py src/opensquilla/cli/providers_workflows.py src/opensquilla/cli/providers_presenters.py src/opensquilla/cli/models_gateway_queries.py src/opensquilla/cli/models_workflows.py src/opensquilla/cli/models_presenters.py tests/test_provider_runtime_status.py tests/test_provider_model_listing.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py tests/test_cli/test_providers_cmd.py tests/test_cli/test_cli_product_completeness.py`
  - `git diff --check`

## Files

- Create:
  - Optional focused provider/CLI tests if a worker needs a narrower boundary contract.
- Modify:
  - This stage file.
  - Worker-owned files listed in Parallel Worker Ownership.
  - Main-thread `src/opensquilla/gateway/provider_rpc_payloads.py` only after worker merges, if needed for facade integration.
- Test:
  - Worker tests listed in Parallel Worker Ownership.
- Documentation:
  - This stage file records Superpowers, TDD, merge, gate, and cleanup evidence.

## Detailed Superpowers Implementation Plan

### Task 1: Baseline, Evidence, and Stage Plan

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration.
- [x] Confirm `spawn_agent` status.
  - Observed: same-thread healthcheck succeeded.
- [x] Read required Superpowers skills:
  - `superpowers:using-superpowers`
  - `superpowers:using-git-worktrees`
  - `superpowers:writing-plans`
  - `superpowers:dispatching-parallel-agents`
  - `superpowers:subagent-driven-development`
  - `superpowers:test-driven-development`
  - `superpowers:verification-before-completion`
- [x] Use Serena project activation and initial instructions.
- [x] Create fixed active worktree on `codex/refactor-provider-runtime-model-contract-batch`.
- [x] Write this stage plan before implementation.
- [x] Commit this stage plan as the worker base.
  - Commit: `c45f362`.
  - Baseline focused provider suite: `129 passed in 5.20s`.

### Task 2: Worker `provider-status-domain`

- [x] Create an independent worker worktree/branch.
- [x] Write RED provider status query/report boundary tests.
- [x] Run the worker RED command and record the expected failure.
  - RED: `uv run --extra dev pytest tests/test_provider_runtime_status.py tests/test_gateway/test_provider_rpc_payload_facade.py -q`.
  - Result: expected failure, `1 failed, 10 passed`, because `ProviderStatusQuery` did not exist.
- [x] Implement one behavior-compatible provider status domain boundary move.
  - Added provider-owned `ProviderStatusQuery` and `build_provider_status_report_for_query` while preserving existing wrappers.
- [x] Run worker focused tests and touched-file checks.
  - GREEN: same pytest command, `11 passed`.
  - Ruff: `uv run --extra dev ruff check src/opensquilla/provider/runtime_status.py tests/test_provider_runtime_status.py`, `All checks passed!`.
  - `git diff --check` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `5e7d056`.

### Task 3: Worker `provider-model-listing-domain`

- [x] Create an independent worker worktree/branch.
- [x] Write RED provider model listing query/row boundary tests.
- [x] Run the worker RED command and record the expected failure.
  - RED: `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py -q`.
  - Result: expected failure, `1 failed, 11 passed`, because `ProviderModelQuery` did not exist.
- [x] Implement one behavior-compatible provider model listing boundary move.
  - Added provider-owned `ProviderModelQuery` with provider/capability matching while preserving filter kwargs and RPC compatibility wrapper behavior.
- [x] Run worker focused tests and touched-file checks.
  - GREEN: same pytest command, `12 passed in 0.45s`.
  - Ruff: `uv run --extra dev ruff check src/opensquilla/provider/model_listing.py tests/test_provider_model_listing.py`, `All checks passed!`.
  - `git diff --check` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `c206fca`.

### Task 4: Worker `provider-catalog-assembly`

- [x] Create an independent worker worktree/branch.
- [x] Write RED catalog/assembly boundary tests.
- [x] Run the worker RED command and record the expected failure.
  - RED: `uv run --extra dev pytest tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py -q`.
  - Result: expected failure, `2 failed, 12 passed`, because `openrouter_pricing_model_ids` did not exist in the provider catalog and the pricing-model policy was still owned by gateway assembly.
- [x] Implement one behavior-compatible catalog/assembly boundary move.
  - Moved OpenRouter pricing model id collection to provider-owned `model_catalog.openrouter_pricing_model_ids`; gateway runtime assembly delegates to it.
- [x] Run worker focused tests and touched-file checks.
  - GREEN: same pytest command, `14 passed`.
  - Ruff: `uv run --extra dev ruff check src/opensquilla/provider/model_catalog.py src/opensquilla/gateway/provider_runtime_assembly.py tests/test_provider_model_catalog.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_provider_image_generation_runtime_boundary.py`, `All checks passed!`.
  - `git diff --check` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `91c68ff`.

### Task 5: Worker `provider-cli-workflows`

- [x] Create an independent worker worktree/branch.
- [x] Write RED CLI provider/model workflow boundary tests.
- [x] Run the worker RED command and record the expected failure.
  - RED: `uv run --extra dev pytest tests/test_cli/test_providers_cmd.py tests/test_cli/test_cli_product_completeness.py tests/test_cli/test_provider_model_workflow_boundaries.py -q`.
  - Result: expected failure, `2 failed, 95 passed`, because `provider_status_request_params` and `model_list_request_params` did not exist.
- [x] Implement one behavior-compatible CLI workflow boundary move.
  - Added CLI gateway query request-param helpers for providers status and models list while preserving command behavior.
- [x] Run worker focused tests and touched-file checks.
  - GREEN: same pytest command, `97 passed`.
  - Ruff on touched files and new test: `All checks passed!`.
  - `git diff --check` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `48e2344`.

### Task 6: Main Integration Review

- [x] Wait for all worker branches and read summaries.
- [x] Review each branch diff before merge.
- [x] Merge worker branches into child branch one by one with `git merge --no-ff`.
  - Provider status merge: `b262c1d`.
  - Provider model listing merge: `e10437c`.
  - Provider catalog/assembly merge: `b0665d1`.
  - Provider CLI workflows merge: `c66292e`.
- [x] Integrate `gateway.provider_rpc_payloads` only if worker changes expose new provider-domain helpers that should be consumed by the facade.
  - No main-thread facade production edit was needed; existing facade continued to consume provider-domain compatibility wrappers.
- [x] Resolve conflicts without reverting another worker's ownership.
  - No merge conflicts occurred.
- [x] Run the focused batch green command.
  - Result: `134 passed in 1.73s`.
- [x] Run touched-file ruff and `git diff --check`.
  - Ruff touched files/tests: `All checks passed!`.
  - `git diff --check` passed.
- [x] Run full child `scripts/refactor_gate.sh`.
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2532 passed, 8 skipped, 2 warnings in 56.61s`; gateway smoke start/status/stop passed; refactor gate complete.
- [x] Commit stage-record update with the required co-author trailer.

### Task 7: Integration Branch Merge and Cleanup

- [x] Merge child into integration with `git merge --no-ff codex/refactor-provider-runtime-model-contract-batch`.
  - Integration merge commit: `cf69a6b`.
- [x] Run full integration `scripts/refactor_gate.sh`.
  - Result: ruff passed; mypy passed; whitespace passed; pytest `2534 passed, 6 skipped, 2 warnings in 27.04s`; gateway smoke start/status/stop passed; refactor gate complete.
- [x] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
- [x] Commit the stage record update on integration with the required co-author trailer.
- [x] Remove `../opensquilla-refactor-active`.
- [x] Remove worker worktrees created for this batch.
- [x] Run `git worktree prune`.
- [x] Verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.
  - `git worktree list` no longer lists the active child or provider worker worktrees.
  - `ls -d ../opensquilla-refactor-*` lists only `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if provider status/model listing RPC wire shape, CLI output, provider defaults, OpenRouter pricing/catalog refresh, or gateway smoke behavior regresses.
- Keep worker branches until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Worker commits:
  - `5e7d056` Refactor provider status domain query boundary.
  - `c206fca` Refactor provider model listing query boundary.
  - `91c68ff` Refactor OpenRouter pricing model policy boundary.
  - `48e2344` Refactor provider CLI gateway query params.
- Child integration commits:
  - `b262c1d` Merge provider status domain boundary batch.
  - `e10437c` Merge provider model listing domain boundary batch.
  - `b0665d1` Merge provider catalog assembly boundary batch.
  - `c66292e` Merge provider CLI workflows boundary batch.
- Integration merge:
  - `cf69a6b` Merge provider runtime model contract batch.
- Verification evidence:
  - Baseline focused provider suite: `129 passed in 5.20s`.
  - Post-worker focused provider suite: `134 passed in 1.73s`.
  - Touched-file Ruff: `All checks passed!`.
  - Child `git diff --check`: passed.
  - Child full `scripts/refactor_gate.sh`: ruff passed; mypy passed; whitespace passed; pytest `2532 passed, 8 skipped, 2 warnings in 56.61s`; gateway smoke passed.
  - Integration full `scripts/refactor_gate.sh`: ruff passed; mypy passed; whitespace passed; pytest `2534 passed, 6 skipped, 2 warnings in 27.04s`; gateway smoke passed.
  - Cleanup: temporary active and worker worktrees removed and pruned; only `../opensquilla-refactor-integration` remains among refactor worktrees.
- Residual risk:
  - Provider behavior verification is covered by unit/AST/CLI/static contract tests and gateway smoke; live provider network calls remain skipped by default.
  - Gateway provider RPC facade production code did not need a main-thread edit in this batch, so facade compatibility depends on existing wrapper coverage.
- Next recommended slice:
  - Model-router/runtime scoring or provider backend request payload boundaries, depending on whether the next priority is routing correctness or backend adapter cleanup.
