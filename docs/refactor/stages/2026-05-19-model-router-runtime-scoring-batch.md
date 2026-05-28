# Model Router Runtime Scoring Batch

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: model-router-runtime-scoring-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-model-router-runtime-scoring-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread with same-thread worker agents, because `spawn_agent`
  healthcheck returned `spawn_agent available.`

## Goal

Refactor the model-router/runtime scoring module family into clearer internal
boundaries while preserving all routing decisions, model/tier selection,
thinking and prompt metadata, price lookup behavior, routing history, and public
facades.

This stage intentionally batches three related but separately owned boundaries:

- Engine router turn orchestration behind `apply_squilla_router`.
- V4 Phase 3 runtime-adapter result/default normalization.
- Pricing internals behind the stable `opensquilla.engine.pricing` facade.

## Current-state audit

- Current HEAD: `d4f4941`
- Worktree status: clean before child worktree creation; child branch clean at
  baseline.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` (not in touched
    scope)
- Files inspected:
  - `src/opensquilla/engine/steps/squilla_router.py`
  - `src/opensquilla/squilla_router/v4_phase3.py`
  - `src/opensquilla/squilla_router/controller.py`
  - `src/opensquilla/engine/pricing.py`
  - `src/opensquilla/session/subagent_routing.py`
  - `tests/test_model_router_behavior.py`
  - `tests/test_model_router_defaults.py`
  - `tests/test_engine/test_pricing.py`
  - `tests/test_engine/test_savings_score.py`
  - `tests/test_engine/test_runtime_cost_source.py`
  - `tests/test_engine/test_routing_history_store.py`
- Symbols or command surfaces inspected:
  - `apply_squilla_router`, `RoutingHistoryStore`, `_compute_savings`,
    `_finalize_decision`, `_apply_controller`
  - `V4Phase3Strategy`, `_find_valid_tier`, `_map_result`,
    `_unavailable_classify`
  - `PricingCache`, `PriceEntry`, `ModelPrice`, `lookup_price`,
    `refresh_live_prices`
- Tests inspected:
  - `tests/test_model_router_behavior.py`
  - `tests/test_model_router_defaults.py`
  - `tests/test_engine/test_pricing.py`
  - `tests/test_engine/test_savings_score.py`
  - `tests/test_engine/test_runtime_cost_source.py`
  - `tests/test_engine/test_routing_history_store.py`
- Existing boundary pattern this stage follows:
  - Keep old public modules as facades while extracting implementation detail
    into narrower internal modules.
  - Preserve public imports, RPC/config payloads, provider defaults, routing
    metadata keys, and test-visible behavior.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read before child creation; created fixed child worktree
    `../opensquilla-refactor-active` with branch
    `codex/refactor-model-router-runtime-scoring-batch`, per root `AGENTS.md`.
- `superpowers:writing-plans`:
  - Evidence: this stage plan records architecture boundary, ownership, RED
    tests, focused verification, full gate, merge, and cleanup steps before
    production edits.
- `superpowers:test-driven-development`:
  - Evidence: worker prompts require new RED tests first, expected failure
    capture, then minimal extraction/refactor and focused GREEN commands.
- `superpowers:verification-before-completion`:
  - Evidence: stage cannot be claimed complete until focused suites,
    `scripts/refactor_gate.sh` on child, integration merge gate, and cleanup
    checks are freshly run and recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` used: yes; three read-only
    explorers audited independent domains.
  - `superpowers:subagent-driven-development` used: yes; implementation will
    dispatch independent workers with strict ownership and main-thread review.
  - `spawn_agent` probe: same-thread healthcheck agent returned
    `spawn_agent available.` and was closed.
  - External worker fallback: not needed for this stage unless same-thread
    workers fail during dispatch.
- Historical evidence note:
  - This record does not infer Superpowers usage for prior stages. Prior stage
    evidence must come from each stage record or current command log.

## Boundary decision

- Module batch:
  - `opensquilla.engine.steps.squilla_router` turn orchestration.
  - `opensquilla.squilla_router.v4_phase3` adapter normalization.
  - `opensquilla.engine.pricing` public facade and internals.
- Responsibilities moving out:
  - Router step pure-ish turn decision/history shaping into a private helper
    module under `src/opensquilla/engine/steps/`.
  - V4 route/tier/result fallback shaping into private helpers or value
    functions under `src/opensquilla/squilla_router/v4_phase3.py` or a sibling
    internal module.
  - Pricing cache/live/static helper implementation into narrower internal
    modules under `src/opensquilla/engine/`.
- Responsibilities staying in place:
  - `apply_squilla_router`, `preload_strategy`, `RoutingHistoryStore`, and
    `_history_store` remain import-compatible.
  - `V4Phase3Strategy.classify` public tuple shape remains unchanged.
  - `opensquilla.engine.pricing` keeps exporting `ModelPrice`, `PricingCache`,
    `PriceEntry`, `lookup_price`, `refresh_live_prices`, cache test helpers,
    and compatibility hooks used by tests.
- Public behavior that must not change:
  - Routed tier/model metadata keys.
  - Thinking mode/level/requested metadata.
  - Prompt policy and prompt injection behavior.
  - Routing history restoration, pruning, and appended final decision shape.
  - OpenRouter attribution headers and live/static price override precedence.
  - Runtime savings math and billed/estimated rollup semantics.
- Files explicitly out of scope:
  - `src/opensquilla/gateway/*` except verification.
  - `src/opensquilla/engine/runtime.py` except verification.
  - `src/opensquilla/session/subagent_routing.py`,
    `src/opensquilla/scheduler/routing.py`, and
    `src/opensquilla/gateway/routing.py`.
  - Provider catalog/runtime model listing code from the previous stage.

## Worker ownership

### Worker A: Router Turn Boundary

- Owns:
  - `src/opensquilla/engine/steps/squilla_router.py`
  - new private helper module under `src/opensquilla/engine/steps/`
  - new focused test file `tests/test_model_router_turn_boundary.py`
- Must not edit:
  - `src/opensquilla/squilla_router/v4_phase3.py`
  - `src/opensquilla/squilla_router/controller.py`
  - `src/opensquilla/engine/pricing.py`
  - `tests/test_model_router_behavior.py`
- RED test:
  - Add a focused test proving restored routing history is passed trimmed to
    the strategy and appended after finalization with `base_tier`,
    `final_tier`, and `final_route_class`.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_model_router_turn_boundary.py tests/test_model_router_behavior.py tests/test_engine/test_routing_history_store.py -q`

### Worker B: V4 Adapter Normalization

- Owns:
  - `src/opensquilla/squilla_router/v4_phase3.py`
  - optional new private helper module under `src/opensquilla/squilla_router/`
  - new focused test file `tests/test_squilla_router_v4_phase3_adapter.py`
- Must not edit:
  - `src/opensquilla/engine/steps/squilla_router.py`
  - `src/opensquilla/engine/pricing.py`
  - `tests/test_model_router_behavior.py`
  - `tests/test_model_router_defaults.py`
- RED tests:
  - Route `R0` falls forward to `t2` when valid tiers are `["t2", "t3"]`.
  - Unavailable fallback starts from `t1` and falls forward to first valid tier.
  - Runtime-config localized `P0` prompt hint is preserved in `extra`.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_squilla_router_v4_phase3_adapter.py tests/test_model_router_defaults.py tests/test_inference_postprocess_rules.py -q`

### Worker C: Pricing Facade Split

- Owns:
  - `src/opensquilla/engine/pricing.py`
  - new pricing-internal modules under `src/opensquilla/engine/`
  - new focused test file `tests/test_engine/test_pricing_boundaries.py`
  - targeted updates to `tests/test_engine/test_pricing.py` only if existing
    monkeypatch paths must move to the new internal module.
- Must not edit:
  - `src/opensquilla/engine/steps/squilla_router.py`
  - `src/opensquilla/engine/runtime.py`
  - `src/opensquilla/squilla_router/*`
- RED tests:
  - New internal pricing modules expose moved helpers while
    `opensquilla.engine.pricing` still re-exports the public facade.
  - Existing OpenRouter attribution, override precedence, and live-cache tests
    continue to pass after extraction.
- Focused GREEN:
  - `uv run --extra dev pytest tests/test_engine/test_pricing_boundaries.py tests/test_engine/test_pricing.py tests/test_engine/test_savings_score.py tests/test_engine/test_runtime_cost_source.py -q`

## TDD red/green

- Baseline focused command:
  - `uv run --extra dev pytest tests/test_model_router_behavior.py tests/test_model_router_defaults.py tests/test_engine/test_savings_score.py tests/test_engine/test_routing_history_store.py tests/test_engine/test_runtime_cost_source.py tests/test_engine/test_pricing.py -q`
  - Baseline result: `91 passed, 2 skipped`.
- Failing test commands:
  - Worker A/B/C RED commands listed above.
- Expected red failures:
  - New helper module or helper behavior unavailable before extraction.
  - New boundary tests fail for missing isolated API or currently coupled
    behavior.
- Behavior compatibility coverage:
  - Existing router behavior/defaults/pricing/runtime-cost/history suites stay
    green.
- Module-batch implementation:
  - Workers commit only their owned files, then main thread reviews diffs and
    runs combined focused verification.
- Focused green command after worker integration:
  - `uv run --extra dev pytest tests/test_model_router_turn_boundary.py tests/test_squilla_router_v4_phase3_adapter.py tests/test_engine/test_pricing_boundaries.py tests/test_model_router_behavior.py tests/test_model_router_defaults.py tests/test_engine/test_savings_score.py tests/test_engine/test_routing_history_store.py tests/test_engine/test_runtime_cost_source.py tests/test_engine/test_pricing.py tests/test_inference_postprocess_rules.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/engine src/opensquilla/squilla_router tests/test_model_router_turn_boundary.py tests/test_squilla_router_v4_phase3_adapter.py tests/test_engine/test_pricing_boundaries.py`
  - `git diff --check`

## Files

- Create:
  - `tests/test_model_router_turn_boundary.py`
  - `tests/test_squilla_router_v4_phase3_adapter.py`
  - `tests/test_engine/test_pricing_boundaries.py`
  - private helper modules as needed under `src/opensquilla/engine/` and
    `src/opensquilla/engine/steps/`
- Modify:
  - `src/opensquilla/engine/steps/squilla_router.py`
  - `src/opensquilla/squilla_router/v4_phase3.py`
  - `src/opensquilla/engine/pricing.py`
- Test:
  - Router, v4 adapter, pricing, savings, runtime-cost, routing-history suites.
- Documentation:
  - This stage record.

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty` in integration.
- [x] Create fixed child worktree `../opensquilla-refactor-active`.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-model-router-runtime-scoring-batch`.
- [x] Run focused baseline and record `91 passed, 2 skipped`.
- [x] Dispatch Worker A/B/C with explicit ownership and TDD RED/GREEN.
- [x] Review each worker diff for ownership, public API compatibility, and
      behavior preservation.
- [x] Run the combined focused GREEN command.
- [x] Run touched-file Ruff and `git diff --check`.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
  - Result through `scripts/refactor_gate.sh`: `All checks passed!`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - Initial child gate caught
    `src/opensquilla/engine/steps/_squilla_router_turn_boundary.py:47:
    error: Returning Any ... [no-any-return]`.
  - Fixed with an explicit cast around `history_store.get(...)`.
  - Rerun result through `scripts/refactor_gate.sh`: `Success: no issues found
    in 528 source files`.
- `git diff --check`
  - Result: clean.
- `uv run --extra dev pytest`
  - Result through `scripts/refactor_gate.sh`: `2538 passed, 8 skipped,
    2 warnings in 34.27s`.
- gateway smoke through `scripts/refactor_gate.sh`
  - Result: gateway start/status/stop/status smoke returned `ok: true`;
    final status was `not_started`.

## Integration gate

- `uv run --extra dev ruff check src tests`
  - Result through `scripts/refactor_gate.sh`: `All checks passed!`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
  - Result through `scripts/refactor_gate.sh`: `Success: no issues found
    in 528 source files`.
- `git diff --check HEAD^ HEAD`
  - Result through `scripts/refactor_gate.sh`: clean.
- `uv run --extra dev pytest`
  - Result through `scripts/refactor_gate.sh`: `2540 passed, 6 skipped,
    2 warnings in 26.28s`.
- gateway smoke through `scripts/refactor_gate.sh`
  - Result: gateway start/status/stop/status smoke returned `ok: true`;
    final status was `not_started`.

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `645c998` (`Refactor model router runtime scoring boundaries`)
- Integration merge: `0e87da7` (`Merge model router runtime scoring batch`)
- Integration gate record: `31abce8` (`Record model router runtime scoring integration gate`)
- Verification evidence:
  - Baseline before edits:
    `91 passed, 2 skipped` for router/pricing/history/runtime focused suite.
  - Worker A RED:
    `uv run --extra dev pytest tests/test_model_router_turn_boundary.py -q`
    failed with missing `_squilla_router_turn_boundary` import before
    production code.
  - Worker A GREEN:
    `uv run --extra dev pytest tests/test_model_router_turn_boundary.py tests/test_model_router_behavior.py tests/test_engine/test_routing_history_store.py -q`
    returned `23 passed, 2 skipped`.
  - Worker B RED:
    `uv run --extra dev pytest tests/test_squilla_router_v4_phase3_adapter.py -q`
    failed with missing `_v4_phase3_adapter` module before production code.
  - Worker B GREEN:
    `uv run --extra dev pytest tests/test_squilla_router_v4_phase3_adapter.py tests/test_model_router_defaults.py tests/test_inference_postprocess_rules.py -q`
    returned `41 passed`.
  - Worker C RED:
    `uv run --extra dev pytest tests/test_engine/test_pricing_boundaries.py -q`
    failed with missing `_pricing_cache` / `_pricing_live` internal modules
    before production code.
  - Worker C GREEN:
    `uv run --extra dev pytest tests/test_engine/test_pricing_boundaries.py tests/test_engine/test_pricing.py tests/test_engine/test_savings_score.py tests/test_engine/test_runtime_cost_source.py -q`
    returned `40 passed`.
  - Combined focused GREEN:
    `uv run --extra dev pytest tests/test_model_router_turn_boundary.py tests/test_squilla_router_v4_phase3_adapter.py tests/test_engine/test_pricing_boundaries.py tests/test_model_router_behavior.py tests/test_model_router_defaults.py tests/test_engine/test_savings_score.py tests/test_engine/test_routing_history_store.py tests/test_engine/test_runtime_cost_source.py tests/test_engine/test_pricing.py tests/test_inference_postprocess_rules.py -q`
    returned `104 passed, 2 skipped`.
  - Touched-area Ruff:
    `uv run --extra dev ruff check src/opensquilla/engine src/opensquilla/squilla_router tests/test_model_router_turn_boundary.py tests/test_squilla_router_v4_phase3_adapter.py tests/test_engine/test_pricing_boundaries.py`
    returned `All checks passed!`.
  - Child full gate: `scripts/refactor_gate.sh` returned `Refactor gate
    complete`.
- Residual risk:
  - Pricing private helpers are intentionally importable for structural tests;
    public callers should continue using `opensquilla.engine.pricing`.
  - Router turn boundary keeps `RoutingHistoryStore` and `_history_store`
    facades in place for gateway session cleanup compatibility.
- Next recommended slice:
  - Continue with a coarse routing-adjacent boundary that does not reopen these
    files immediately, such as route envelope normalization across
    `session/subagent_routing.py`, `scheduler/routing.py`, and
    `gateway/routing.py`, or move to the next provider/session boundary if that
    has clearer ownership.
- Cleanup:
  - Removed `../opensquilla-refactor-active`.
  - Ran `git worktree prune`.
  - Deleted merged child branch `codex/refactor-model-router-runtime-scoring-batch`.
  - Verified the sibling `opensquilla-refactor-*` worktree listing contains only
    the integration worktree.
