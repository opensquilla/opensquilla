# Squilla Tree Router Driven LLM Ensemble Planner Spec

Status: draft

Source design: `docs/llm-router-ensemble-planner.html`

## 1. Scope

This spec only covers `llm_ensemble.enabled=true`.

The planner converts Squilla tree-router metadata into an `ensemble_plan` containing:

- proposer members
- aggregator member
- selection scores and reasons
- hard-filtered candidates
- repeat-model policy

The planner does not depend on an LLM router, task tags, runtime-accumulated fields, or per-turn semantic model capability inference.

## 2. Inputs

### 2.1 Router Metadata

Required fields:

```json
{
  "routed_tier": "c2",
  "routed_model": "z-ai/glm-5.2",
  "routing_confidence": 0.74,
  "routing_source": "v4_phase3",
  "routing_extra": {
    "margin": 0.56,
    "confidence_gate_applied": false,
    "anti_downgrade_applied": false,
    "large_context_floor_applied": false
  }
}
```

The router provides strength and risk signals only. It does not provide task type, model expertise tags, or response shape tags.
Thinking level and synthesis prompt policy are resolved by the ensemble policy/provider builder, not by the tree-router contract.

### 2.2 Configured Proposer Pool

Path:

```text
llm_ensemble.profiles[llm_ensemble.active_profile].proposers
```

This is the operator-controlled candidate pool. Its order is a stable tie-breaker, not the primary selection algorithm.

### 2.3 Configured Aggregator

Path:

```text
llm_ensemble.profiles[llm_ensemble.active_profile].aggregator
```

This is the operator-configured default synthesis model.

### 2.4 Model Feature Catalog

Planner-owned static catalog. It can be initialized from `llm_ensemble.model_options`, `squilla_router.tiers`, and a static default table.

Required fields per model:

```json
{
  "provider": "openrouter",
  "model": "deepseek/deepseek-v4-pro",
  "family": "deepseek",
  "tier_bucket": "c1",
  "quality_prior": 0.72,
  "cost_prior": 0.35,
  "latency_prior": 0.40,
  "context_window_tokens": 128000,
  "supports_image": false,
  "synthesis_capable": true
}
```

All values are static configuration or operator-maintained defaults. No runtime-accumulated fields are part of this spec.

## 3. Tier Policies

Tier policy produces three things:

- `proposer_count`
- `base_weights`
- `slot_specs`

`slot` is an input to scoring, not something inferred from the final scalar score. The planner fills slots sequentially. For each slot, the tier policy provides the slot target and optional weight overrides, then every remaining candidate is scored for that specific slot.

### 3.0 Terminology Invariants

| Term | Invariant |
| --- | --- |
| `slot_target` | Desired role for the current slot. It is a scoring input, not a model name. |
| slot-local `score` | Meaningful only under one `slot_spec` and one merged weight vector. A scalar score cannot identify a slot. |
| `active_profile` | Config source for candidate expansion only. It is not the selected runtime plan. |
| `role_match` | Candidate fit for the current `slot_target`. |
| `diversity_gain` | Candidate complementarity against already selected proposers. |
| `aggregator_plan` | Conceptual synthesis-member plan, serialized as `ensemble_plan.aggregator`. It is selected after proposers with a separate synthesis objective. |

### 3.1 Policy Matrix

| Router tier | Policy | Proposers | Aggregator target |
| --- | --- | ---: | --- |
| `c0` | `tier_c0_light` | 2 | configured aggregator |
| `c1` | `tier_c1_light` | 2 | configured aggregator |
| `c2` | `tier_c2_standard` | 3 | configured aggregator |
| `c3` | `tier_c3_heavy` | 4 | strong aggregator preferred |
| `image_model` | `vision_ensemble` | 2 | vision-capable aggregator |

`c1` and `c2` may add one proposer when router uncertainty is high, for example low `margin`, `confidence_gate_applied=true`, or `anti_downgrade_applied=true`, capped by configured limits.

### 3.2 Slot Specs

Slot specs are soft hints for `role_match` plus optional per-slot weight overrides. They are not hard requirements and do not name specific models.

| Policy | Slot specs |
| --- | --- |
| `tier_c0_light` | `slot1=anchor`, `slot2=low_cost_contrast` |
| `tier_c1_light` | `slot1=anchor`, `slot2=balanced_contrast` |
| `tier_c2_standard` | `slot1=anchor`, `slot2=adjacent_tier_check`, `slot3=orthogonal_family` |
| `tier_c3_heavy` | `slot1=anchor`, `slot2=strong_critic`, `slot3=orthogonal_family`, `slot4=fast_sanity_check` |

Example `tier_c2_standard` policy shape:

```json
{
  "proposer_count": 3,
  "base_weights": {
    "w_quality": 0.30,
    "w_affinity": 0.20,
    "w_diversity": 0.20,
    "w_role": 0.10,
    "w_repeat": 0.15,
    "w_cost": 0.10,
    "w_latency": 0.05,
    "w_hard_penalty": 0.20
  },
  "slot_specs": {
    "1": {"target": "anchor"},
    "2": {
      "target": "adjacent_tier_check",
      "weight_overrides": {
        "w_affinity": 0.25,
        "w_role": 0.20,
        "w_cost": 0.12
      }
    },
    "3": {
      "target": "orthogonal_family",
      "weight_overrides": {
        "w_diversity": 0.30,
        "w_role": 0.20
      }
    }
  }
}
```

In this example, the same candidate can score differently in slot 2 and slot 3 because the scorer receives a different `slot_spec`.

### 3.3 Weight Intent

| Policy | Weight intent |
| --- | --- |
| `tier_c0_light` | Higher cost and latency penalties; lower quality weight. |
| `tier_c1_light` | Balanced quality, cost, and latency. |
| `tier_c2_standard` | Higher affinity, diversity, and role-match weights. |
| `tier_c3_heavy` | Higher quality and role-match weights; lower cost penalty impact. |

## 4. Proposer Selection

### 4.1 Candidate Expansion

Candidate sources:

1. router anchor from `metadata.routed_model`
2. configured proposer pool
3. tier ladder candidates from `squilla_router.tiers`
4. allowed catalog candidates when enabled by config

The router anchor is selected first as `slot1=anchor`.

### 4.2 Hard Filters

Hard filters remove only candidates that cannot execute:

- missing provider credentials
- insufficient context window
- incompatible modality, for example image input with text-only model

Duplicate `(provider, model)` candidates are not hard-filtered.

### 4.3 Repeat Policy

Repeated models are allowed with a soft penalty.

```json
{
  "mode": "soft_penalty",
  "same_model_penalty": 0.15,
  "same_family_penalty": 0.08,
  "allowed_when_score_still_wins": true
}
```

If a repeated model still has the highest score after penalty, it can be selected again.

### 4.4 Objective

For each slot after the anchor, first resolve the slot spec and slot weights:

```text
slot_spec = policy.slot_specs[slot]
weights = merge(policy.base_weights, slot_spec.weight_overrides)

score(c) =
  weights.w_quality      * quality_prior(c)
+ weights.w_affinity     * router_affinity(c, routed_tier)
+ weights.w_diversity    * diversity_gain(c, selected)
+ weights.w_role         * role_match(c, slot_spec.target)
- weights.w_repeat       * repeat_penalty(c, selected)
- weights.w_cost         * normalized_cost(c)
- weights.w_latency      * normalized_latency(c)
- weights.w_hard_penalty * hard_penalty(c)
```

The scalar `score` is only meaningful for the current slot. It should not be reused across slots without recomputing with the next slot spec.

`role_match(c, slot_target)` is target-specific:

| `slot_target` | High score when |
| --- | --- |
| `low_cost_contrast` | Candidate is lower cost/latency than the anchor and not the anchor family. |
| `balanced_contrast` | Candidate is same-or-neighbor tier, non-anchor family, and moderate cost. |
| `adjacent_tier_check` | Candidate tier is one step from `routed_tier`; same tier gets partial credit. |
| `orthogonal_family` | Candidate family/provider/architecture tags differ from selected proposers. |
| `strong_critic` | Candidate is same-or-higher tier with high static `quality_prior`. |
| `fast_sanity_check` | Candidate has low latency with adequate static quality. |

`role_match` complements `diversity_gain`; it does not replace it.

Tie-breakers:

1. higher score
2. lower configured index
3. lexical `(provider, model)` for determinism

### 4.5 Algorithm

```python
def select_proposers(ctx, config):
    tier = normalize_tier(ctx.metadata["routed_tier"])
    policy = policy_for_tier(tier, ctx.metadata)
    selected = [anchor_from(ctx.metadata["routed_model"])]

    candidates = expand_candidate_pool(config, tier)
    candidates = [
        enrich(candidate, config.model_feature_catalog)
        for candidate in candidates
        if hard_constraints_ok(candidate, ctx)
    ]

    rank_trace = []
    while len(selected) < policy.proposer_count:
        slot = len(selected) + 1
        slot_spec = policy.slot_specs[slot]
        weights = merge_weights(policy.base_weights, slot_spec.weight_overrides)
        scored = [
            score_candidate(candidate, selected, ctx, slot_spec, weights)
            for candidate in candidates
        ]
        scored.sort(key=lambda x: (-x.score, x.config_index, x.model))
        if not scored:
            raise EnsembleConfigError("no executable proposer candidates")

        chosen = scored[0]
        selected.append(chosen.candidate)
        rank_trace.append({
            "slot": slot,
            "slot_target": slot_spec.target,
            "chosen": chosen.candidate.model,
            "score": chosen.score,
            "weights": weights,
            "components": chosen.components,
            "top_rejected": scored[1:4],
        })
        candidates = mark_selected_for_repeat_penalty(candidates, chosen.candidate)

    return selected, rank_trace
```

### 4.6 Worked Example: 8 Candidate Pool

Router output:

```json
{
  "routed_tier": "c2",
  "routed_model": "z-ai/glm-5.2"
}
```

`tier_c2_standard` requires 3 proposers:

- `slot1=anchor`
- `slot2=adjacent_tier_check`
- `slot3=orthogonal_family`

Candidate pool after hard filters:

| # | Candidate | Family | Tier | Note |
| ---: | --- | --- | --- | --- |
| 1 | `z-ai/glm-5.2` | `glm` | `c2` | router anchor |
| 2 | `deepseek/deepseek-v4-pro` | `deepseek` | `c1` | neighbor tier |
| 3 | `anthropic/claude-sonnet-4.6` | `claude` | `c2` | high quality, higher cost |
| 4 | `google/gemini-3-flash-preview` | `gemini` | `c1` | low latency, orthogonal family |
| 5 | `qwen/qwen3.7-plus` | `qwen` | `c1` | balanced contrast |
| 6 | `openai/gpt-5.4-mini` | `openai` | `c2` | same tier |
| 7 | `z-ai/glm-5.2` | `glm` | `c2` | duplicate candidate, still eligible |
| 8 | `anthropic/claude-opus-4.8` | `claude` | `c3` | strong critic, expensive |

`slot1` is fixed:

```text
selected = [z-ai/glm-5.2]
```

For `slot2=adjacent_tier_check`, use:

```json
{
  "w_quality": 0.25,
  "w_affinity": 0.25,
  "w_diversity": 0.13,
  "w_role": 0.22,
  "w_repeat": 0.10,
  "w_cost": 0.03,
  "w_latency": 0.02
}
```

| Candidate | quality | affinity | diversity | role | repeat | cost | latency | score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `deepseek/deepseek-v4-pro` | 0.76 | 0.85 | 0.90 | 0.95 | 0.00 | 0.35 | 0.40 | **0.710** |
| `anthropic/claude-sonnet-4.6` | 0.88 | 1.00 | 0.90 | 0.65 | 0.00 | 0.75 | 0.65 | 0.694 |
| `openai/gpt-5.4-mini` | 0.80 | 1.00 | 0.90 | 0.60 | 0.00 | 0.50 | 0.40 | 0.676 |
| `z-ai/glm-5.2` duplicate | 0.82 | 1.00 | 0.00 | 0.45 | 1.00 | 0.55 | 0.45 | 0.429 |

`slot2` chooses `deepseek/deepseek-v4-pro`.

For `slot3=orthogonal_family`, recompute every candidate with a different target and weights:

```json
{
  "w_quality": 0.20,
  "w_affinity": 0.15,
  "w_diversity": 0.30,
  "w_role": 0.25,
  "w_repeat": 0.07,
  "w_cost": 0.02,
  "w_latency": 0.01
}
```

| Candidate | quality | affinity | diversity | role | repeat | cost | latency | score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `google/gemini-3-flash-preview` | 0.70 | 0.75 | 0.95 | 0.95 | 0.00 | 0.25 | 0.25 | **0.768** |
| `qwen/qwen3.7-plus` | 0.74 | 0.75 | 0.95 | 0.88 | 0.00 | 0.30 | 0.35 | 0.756 |
| `anthropic/claude-sonnet-4.6` | 0.88 | 1.00 | 0.80 | 0.70 | 0.00 | 0.75 | 0.65 | 0.720 |
| `z-ai/glm-5.2` duplicate | 0.82 | 1.00 | 0.00 | 0.20 | 1.00 | 0.55 | 0.45 | 0.279 |

`slot3` chooses `google/gemini-3-flash-preview`.

The duplicate `z-ai/glm-5.2` candidate remains eligible in both slots. It loses because `repeat_penalty` and low diversity reduce its slot-local score, not because the planner hard-dedupes `(provider, model)`.

The final trace records slot-local weights and scores:

```json
[
  {
    "slot": 2,
    "slot_target": "adjacent_tier_check",
    "chosen": "deepseek/deepseek-v4-pro",
    "score": 0.710,
    "weights": {
      "w_quality": 0.25,
      "w_affinity": 0.25,
      "w_diversity": 0.13,
      "w_role": 0.22,
      "w_repeat": 0.10,
      "w_cost": 0.03,
      "w_latency": 0.02
    },
    "components": {
      "quality_prior": 0.76,
      "router_affinity": 0.85,
      "diversity_gain": 0.90,
      "role_match": 0.95,
      "repeat_penalty": 0.00,
      "normalized_cost": 0.35,
      "normalized_latency": 0.40
    },
    "top_rejected": [
      {"model": "anthropic/claude-sonnet-4.6", "score": 0.694},
      {"model": "openai/gpt-5.4-mini", "score": 0.676}
    ]
  },
  {
    "slot": 3,
    "slot_target": "orthogonal_family",
    "chosen": "google/gemini-3-flash-preview",
    "score": 0.768,
    "weights": {
      "w_quality": 0.20,
      "w_affinity": 0.15,
      "w_diversity": 0.30,
      "w_role": 0.25,
      "w_repeat": 0.07,
      "w_cost": 0.02,
      "w_latency": 0.01
    },
    "components": {
      "quality_prior": 0.70,
      "router_affinity": 0.75,
      "diversity_gain": 0.95,
      "role_match": 0.95,
      "repeat_penalty": 0.00,
      "normalized_cost": 0.25,
      "normalized_latency": 0.25
    },
    "top_rejected": [
      {"model": "qwen/qwen3.7-plus", "score": 0.756},
      {"model": "anthropic/claude-sonnet-4.6", "score": 0.720}
    ]
  }
]
```

`slot2` score `0.710` and `slot3` score `0.768` are not cross-slot comparable because they were computed under different targets and weight vectors.

## 5. Aggregator Selection

Aggregator selection uses a separate synthesis objective. It does not optimize for proposer diversity.

Candidate sources:

1. configured aggregator
2. `squilla_router.tiers.c3.model`
3. catalog models marked `synthesis_capable=true`
4. `image_model` when the turn has image input

Hard filters:

- missing credentials
- insufficient synthesis context window
- incompatible modality

Objective:

```text
score(a) =
  0.35 * synthesis_quality_prior(a)
+ 0.20 * context_fit(a, ctx, proposers)
+ 0.15 * policy_affinity(a, routed_tier)
+ 0.10 * disagreement_capacity(a, proposers)
+ 0.05 * configured_stability_bonus(a)
- 0.10 * normalized_cost(a)
- 0.05 * normalized_latency(a)
- 0.20 * hard_penalty(a)
```

The selected aggregator must be able to read the original input, proposer outputs, and synthesis prompt.

## 6. Output Contract

Planner writes `ctx.metadata["ensemble_plan"]`.

Required shape:

```json
{
  "schema": "opensquilla.ensemble_plan.v1",
  "mode": "ensemble_fanout_synthesis",
  "policy": "tier_c2_standard",
  "router": {
    "tier": "c2",
    "confidence": 0.74,
    "source": "v4_phase3"
  },
  "selection_algorithm": {
    "name": "slot_local_greedy_optimizer",
    "policy_details": {
      "base_weights": {},
      "slot_specs": {}
    },
    "objective": [
      "quality_prior",
      "router_affinity",
      "diversity_gain",
      "role_match",
      "repeat_penalty",
      "cost_penalty",
      "latency_penalty"
    ]
  },
  "proposers": [],
  "rank_trace": [],
  "aggregator": {},
  "filtered_candidates": [],
  "repeat_policy": {
    "mode": "soft_penalty",
    "same_model_penalty": 0.15,
    "same_family_penalty": 0.08,
    "allowed_when_score_still_wins": true
  },
  "strategy": "optimized_fanout_then_synthesis"
}
```

The public JSON field for `aggregator_plan` is `aggregator`.

Each proposer entry must include:

- `provider`
- `model`
- `source`
- `score`
- `reasons`

Each `rank_trace` entry must include:

- `slot`
- `slot_target`
- `chosen`
- `score`
- `components`
- `weights`
- `top_rejected`

## 7. Runtime Integration

Execution order:

1. `apply_squilla_router`
2. `resolve_ensemble_policy`
3. `enrich_candidates`
4. `score_proposer_slots`
5. `score_aggregator_plan`
6. write `ctx.metadata["ensemble_plan"]`
7. build `EnsembleProvider` from the plan
8. run fan-out and synthesis

Planner should be implemented as a pure function over config, router metadata, request modality, and token estimates.

## 8. Acceptance Criteria

- For every text tier `c0..c3`, planner returns an ensemble plan.
- `routed_model` is always selected as `slot1=anchor` unless it fails a hard execution constraint.
- Proposer selection is deterministic for identical config and metadata.
- Duplicate models are allowed only through `repeat_penalty`; they are not silently hard-deduped.
- No runtime-accumulated field is required.
- Image turns only select vision-capable proposers and aggregators.
- Every selected proposer has score components and reasons.
- Every skipped hard-filter candidate has a machine-readable reason.
- If no executable proposer or aggregator exists, planner raises `ensemble_config_error`.

## 9. Open Decisions

- Exact default values for tier-policy weights.
- Exact default values for `same_model_penalty` and `same_family_penalty`.
- Initial location and override mechanism for `Model Feature Catalog`.
- Whether `c3` aggregator should always prefer `squilla_router.tiers.c3.model` or only prefer it through scoring.
