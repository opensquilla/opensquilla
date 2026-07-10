# LLM Ensemble: `router_dynamic` Selection Strategy (legacy)

> **Status: legacy.** `router_dynamic` remains fully supported for existing
> configs but is no longer offered in the Web UI, which now presents two
> schemes: the provider's static preset (`static_openrouter_b5` /
> `static_tokenrhythm_b5`) or an explicit user-authored lineup
> (`custom_b5`, role-labelled candidates with a single aggregator). Stored
> `router_dynamic` configs surface a one-click migration to `custom_b5` in
> the settings UI. Direct TOML/RPC configuration keeps working as described
> below.

`router_dynamic` is the dynamic model-selection strategy used by
`llm_ensemble` to pick which models act as proposers and which model acts as
the aggregator for a given turn. It uses a scoring system driven by
SquillaRouter's tier decision for that turn. Fresh configs default to the
packaged `static_openrouter_b5` profile; set
`llm_ensemble.selection_mode = "router_dynamic"` to use this strategy.

This document describes how `router_dynamic` works. It does not cover the
ensemble runtime mechanics (streaming, timeouts, fallback) — only how the set
of models is chosen.

Source: `src/opensquilla/provider/ensemble.py`
(`_candidate_pool`, `_score_dynamic_candidate`, `_select_dynamic_candidate`,
`_build_router_dynamic_members`).

## Why Dynamic Selection

A fixed proposer/aggregator list can't adapt to the model actually chosen for
a turn, and forces operators to hand-tune which models pair well together at
each router tier. `router_dynamic` instead:

- reuses the model SquillaRouter already picked for the turn as the **anchor**
  proposer, so the ensemble never contradicts the router's own tier decision;
- fills the remaining proposer slots and the aggregator slot by scoring a pool
  of candidate models against a per-tier "slot template";
- penalizes re-selecting a model that's already in the ensemble, so proposers
  stay diverse instead of collapsing onto a few high-quality models.

## Inputs

`_build_router_dynamic_members` takes three things:

1. **`inherited_provider_config`** — the provider/model SquillaRouter already
   resolved for this turn (becomes the anchor).
2. **`turn_metadata`** — carries `routed_tier` (`c0`–`c3`), `routing_confidence`
   (0.0–1.0), and `routing_extra` (`final_tier`/`base_tier` fallbacks used if
   `routed_tier` is missing). Defaults to tier `c1` if nothing usable is found.
3. **`config`** — `llm_ensemble.model_options` and `squilla_router.tiers`,
   used to build the candidate pool.

## Candidate Pool

`_candidate_pool` assembles a deduplicated list of `(provider, model)`
candidates, in this order:

1. **Router anchor** — the inherited provider/model (`source="router_anchor"`).
   This is always `pool[0]` and always becomes the first proposer.
2. **`llm_ensemble.model_options`** — the operator-configured candidate list
   (`source="model_options"`). If a model string contains `/` it's assumed to
   be an OpenRouter-style id and routed via `openrouter`; otherwise it inherits
   the anchor's provider.
3. **`squilla_router.tiers[*].model`** — every model configured for a
   SquillaRouter tier (`source="router_tier:<tier>"`), so tier-specific models
   the operator has wired into the router are eligible even if not listed in
   `model_options`.

Each candidate is annotated with priors from `_DYNAMIC_MODEL_CATALOG` — a
built-in table of ~14 known models with `tier`, `quality` (0–1), `cost_latency`
(0–1, higher = cheaper/faster), `family`, `vendor`, and `architecture`. Models
not in the catalog fall back to tier-average priors (`_tier_quality_prior`,
`_tier_cost_latency_prior`) derived from the model string or tier hint.

## Slot Templates

Each router tier maps to an ordered list of proposer "slots"
(`_DYNAMIC_TIER_SLOTS`):

| Tier | Slots |
|------|-------|
| `c0` | `anchor`, `cheap_contrast` |
| `c1` | `anchor`, `balanced_contrast` |
| `c2` | `anchor`, `adjacent_tier_check`, `orthogonal_family` |
| `c3` | `anchor`, `strong_critic`, `orthogonal_family`, `fast_sanity` |

Lower tiers (cheap/simple turns) get a small, cost-biased ensemble; higher
tiers (hard turns) get more proposers with slots biased toward quality and
contrast. The `anchor` slot is always filled by the router's own model and is
never scored — it's taken as-is.

Each tier also maps to an aggregator slot (`_DYNAMIC_AGGREGATOR_SLOT`):
`c0→aggregator_fast`, `c1→aggregator_balanced`, `c2`/`c3→aggregator_strong`.

## Scoring a Candidate for a Slot

For every non-anchor slot, every pool candidate is scored and the best one is
selected (`_select_dynamic_candidate` → `_score_dynamic_candidate`):

```
score = weights.quality   * quality_prior
      + weights.affinity  * router_affinity_score
      + weights.diversity * diversity_score
      + weights.cost      * cost_latency_prior
      + weights.role      * role_match_score(slot)
      - duplicate_penalty
```

Each slot has its own weight vector (`_DYNAMIC_SLOT_WEIGHTS`), e.g.
`cheap_contrast` weights `cost` and `role` heavily and `affinity` lightly,
while `strong_critic` weights `quality` and `role` heavily and `cost` almost
not at all.

### Score components

- **`router_affinity_score`** — how close the candidate's tier prior is to the
  turn's `routed_tier`, scaled by `routing_confidence`. Low router confidence
  relaxes tier matching instead of forcing a brittle lock, since a low-
  confidence route is itself uncertain about the right tier.
- **`diversity_score`** — rewards a candidate whose family/vendor/provider/
  tier/architecture aren't already represented among the proposers picked so
  far in this turn (checked incrementally, slot by slot).
- **`role_match_score`** — slot-specific logic (see below), combining tier
  targeting, contrast against the anchor, quality, or cost depending on what
  that slot is supposed to contribute.
- **`duplicate_penalty`** — `_DYNAMIC_SELECTED_PENALTY[slot] * times_already_selected`.
  Selecting the same `(provider, model)` again is allowed but costs
  increasingly more as the same model keeps winning slots.

### Role match by slot

`_role_match_score` differs by slot — this is where each slot's intent is
actually encoded:

- **`cheap_contrast`** — favors tier `c0`/`c1`, contrast with the anchor, and
  cost/latency. A cheap "second opinion."
- **`balanced_contrast`** — favors tier `c1`/`c2`, contrast, and quality.
- **`adjacent_tier_check`** — favors a tier one step above/below the routed
  tier (`adjacent_distance == 1`), plus quality. Checks whether a
  slightly-different-strength model agrees.
- **`orthogonal_family`** — favors contrast and diversity above all — a
  model from a different vendor/family/architecture than the anchor.
- **`strong_critic`** — favors tier `c3` and quality heavily — the strongest
  available model as a critic, used only at higher tiers.
- **`fast_sanity`** — favors tier `c0`/`c1` and cost/latency — a fast,
  cheap sanity check, used only at `c3`.
- **`aggregator_fast` / `aggregator_balanced` / `aggregator_strong`** — each
  balances tier targeting and quality differently; `aggregator_strong`
  weights quality highest and cost lowest, since the aggregator's output is
  the final response.

### Tie-breaking

Candidates are sorted by `(score, quality_prior, cost_latency_prior,
-pool_index)` descending, so ties fall back to higher quality, then higher
cost/latency score, then earlier pool position (closer to the anchor/operator-
configured list) wins.

## Selection Order

`_build_router_dynamic_members` runs slots in the tier's template order:

1. `anchor` — taken directly, no scoring.
2. Remaining proposer slots, in order — each selection is added to `selected`
   and `selected_counts` before the next slot is scored, so later slots see
   updated diversity/duplicate state.
3. The aggregator slot, scored last, against the same accumulated `selected`
   state as the proposers (so it also gets a duplicate penalty if it repeats
   a proposer's model).

## Output

The function returns `(profile_name, proposers, aggregator, selection_plan)`:

- `profile_name` — `"router_dynamic/<tier>"`, e.g. `"router_dynamic/c2"`.
- `proposers` — one `EnsembleMemberConfig` per slot, labeled by slot name
  (`anchor`, `cheap_contrast`, ...).
- `aggregator` — one `EnsembleMemberConfig`, labeled `aggregator`.
- `selection_plan` — a full trace for observability, including the resolved
  tier/confidence, the anchor, the slot template, per-slot score breakdowns
  (`_score_trace`, including the top-3 scored candidates per slot for
  debugging near-misses), the aggregator's score breakdown, the full
  candidate pool, and `duplicate_policy: "selected_penalty"`.

`build_ensemble_provider_from_config` (the public entrypoint) additionally
clamps `min_successful_proposers` down to `len(proposers)` if the configured
value exceeds how many proposer slots the tier's template actually produced
— e.g. configuring `min_successful_proposers=4` at tier `c0` (2 slots) yields
an effective minimum of 2. Both the configured and effective values are
recorded in `selection_plan` for debugging.

## Configuration Surface

Operators enable this strategy with:

```toml
[llm_ensemble]
enabled = true
selection_mode = "router_dynamic"
```

What operators can tune:

- `llm_ensemble.model_options` — extends the candidate pool beyond the router
  anchor and configured router tiers.
- `llm_ensemble.min_successful_proposers` — desired minimum successful
  proposers (clamped per-turn as described above).
- `squilla_router.tiers[*].model` — indirectly expands the candidate pool and
  determines which model becomes the anchor for a given tier.

There is no operator control over slot templates, weights, or the model
catalog priors — those are fixed in code.
