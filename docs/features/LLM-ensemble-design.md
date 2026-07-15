# LLM Ensemble Design: Static Lineups & Dynamic Router Selection

`llm_ensemble` runs a **B5 fusion** turn: several *proposer* models each draft
an answer, and one *aggregator* model fuses those drafts into the final
response. This document describes how the **set of models** is chosen for a
turn. It does not cover the ensemble runtime mechanics (streaming, timeouts,
quorum, fallback) — only model selection.

## Why an ensemble instead of a single model

Any single model has a fixed set of blind spots: the failure modes of its
training data, its decoding randomness, and its particular biases. Asking that
one model again doesn't remove them — it re-rolls the *same* distribution. An
ensemble attacks the problem from a different angle: draft an answer with
several *different* models, then have an aggregator reconcile them. The wins
over a single-model turn:

- **Error cancellation / higher accuracy.** Independent models rarely make the
  *same* mistake on the same input. When drafts disagree, the aggregator can
  cross-check them and keep the answer the majority supports; when they agree,
  that agreement is real signal that the answer is solid. Idiosyncratic
  one-off errors get outvoted instead of shipped.
- **Coverage through diversity.** Different vendors/families/architectures have
  genuinely different strengths — one is better at code, another at long-form
  reasoning, another at careful instruction-following. A lineup that spans them
  covers more of the input space than any single model's strong suit. This is
  exactly why selection *rewards diversity* (distinct vendor/family/
  architecture) rather than picking the top-N by raw quality.
- **Robustness & availability.** A single model is a single point of failure —
  one timeout, rate-limit, or degraded response fails the whole turn. With a
  quorum of proposers the turn still succeeds as long as *enough* drafts come
  back, and the aggregator simply fuses what arrived.
- **Reduced variance.** Fusing several drafts smooths out per-call sampling
  noise, so repeated runs of the same prompt are more stable and less
  sensitive to an unlucky roll of the dice on any one model.
- **A critic pass, not just a vote.** The aggregator is a model in its own
  right: it can spot a draft that's confidently wrong, prefer the
  better-reasoned answer over the more verbose one, and synthesize the best
  parts of several drafts — a step a single-model turn never gets.

The cost is real — an N-proposer turn spends roughly N+1 model calls and its
latency is bounded by the slowest proposer plus the aggregator. The selection
strategies below exist to spend that budget well: match ensemble size and
composition to how hard the turn actually is, rather than always paying for the
largest lineup. Lower-difficulty turns get a small, cheap lineup; harder turns
get more proposers and stronger critics.

## Selection strategies

There are four selection modes, dispatched by
`llm_ensemble.selection_mode` in
`build_ensemble_provider_from_config`
(`src/opensquilla/provider/ensemble.py`):

| `selection_mode` | Family | Status |
|------------------|--------|--------|
| `static_openrouter_b5` | Static lineup | Default for fresh configs |
| `static_tokenrhythm_b5` | Static lineup | Supported |
| `custom_b5` | Static lineup (user-authored) | Supported |
| `router_dynamic` | Dynamic Step2 ranking | Supported (config-only) |

The first three modes are **static**: the lineup is fixed ahead of the turn,
either from a packaged preset or from an explicit user-authored list. The last
is **dynamic**: the lineup is scored and assembled per turn from the router's
own tier decision.

Fresh configs default to `static_openrouter_b5`. The Web UI offers only the
static families (preset + custom); `router_dynamic` is no longer offered there
and stored configs surface a one-click migration to `custom_b5`. Direct
TOML/RPC configuration keeps working for every mode.

---

# Part 1 — Static Lineups (current design)

A static lineup is fixed before the turn runs: a set of proposer models plus one
aggregator model, all known ahead of time. No per-turn scoring happens. Two
variants share this shape:

- **Presets** — `static_openrouter_b5` / `static_tokenrhythm_b5`: packaged,
  hard-coded lineups on a single provider.
- **Custom** — `custom_b5`: an explicit user-authored lineup with
  role-labelled candidates and a single aggregator.

Both variants belong to the same **fixed-lineup defaults family**
(`is_static_b5` in the builder) and therefore inherit the same runtime defaults
(quorum, timeouts, no shuffle, quorum grace) — see
[Shared fixed-lineup defaults](#shared-fixed-lineup-defaults).

## 1.1 Static presets

Source: `_build_static_b5_members`, `STATIC_B5_PROFILES`
(`src/opensquilla/provider/ensemble.py`).

Each preset is a `StaticB5Profile` — four fixed proposers plus one aggregator,
all bound to a single provider:

| Profile | Provider | Proposers | Aggregator |
|---------|----------|-----------|------------|
| `static_openrouter_b5` | `openrouter` | `deepseek/deepseek-v4-pro`, `z-ai/glm-5.2`, `moonshotai/kimi-k2.7-code`, `qwen/qwen3.7-max` | `z-ai/glm-5.2` |
| `static_tokenrhythm_b5` | `tokenrhythm` | `deepseek-v4-pro`, `glm-5.2`, `kimi-k2.7-code`, `qwen3.7-max` | `glm-5.2` |

The TokenRhythm profile is a mirror of the OpenRouter one: same aggregation
shape and defaults, the same four models, only the provider and the model-id
naming differ (OpenRouter-style `vendor/model` slugs vs. TokenRhythm's bare
names).

`_build_static_b5_members` simply materializes the profile: each proposer model
becomes an `EnsembleMemberConfig` labeled `proposer_1..N`, the aggregator model
becomes one labeled `aggregator`, and the selection plan records the profile
name, proposer/aggregator models, and proposer count. There is nothing to score
— the lineup is the profile.

### Credential gate

`static_b5_credential_available` decides whether the ensemble may run: it
resolves an API key for every member (all four proposers + aggregator) using the
same key-resolution order as the runtime (see
[Member provider resolution](#member-provider-resolution)). A user whose active
provider differs but whose environment carries the profile provider's env key
(e.g. `OPENROUTER_API_KEY`, `TOKENRHYTHM_API_KEY`) is treated as opted in. If any
member cannot resolve a key, the ensemble is skipped rather than posting a turn
upstream with an empty bearer token.

## 1.2 Custom lineup (`custom_b5`)

Source: `_build_custom_b5_members`, `_custom_b5_candidates`
(`src/opensquilla/provider/ensemble.py`); schema `LlmEnsembleCandidateConfig`
(`src/opensquilla/gateway/config.py`).

`custom_b5` lets an operator author the lineup explicitly via
`llm_ensemble.candidates`. Each candidate row carries:

- **`provider`** / **`model`** — required, non-empty; provider is lower-cased.
- **`role`** — advisory label, one of `""` (unassigned), `primary`, `contrast`,
  `fast_check`, `critic`, or the structural `aggregator`. Unknown values coerce
  to `""` instead of failing, so a hand-edited config never blocks boot.
- **`enabled`** — disabled rows are kept for read compatibility but never
  counted or run.

Lineup assembly (`_build_custom_b5_members`):

1. Every enabled row whose role is **not** `aggregator` runs as a proposer,
   labeled by its role (or `proposer_N` when unassigned).
2. The single row with role `aggregator` fuses the drafts. Proposer rows dedupe
   on `(provider, model)`; the aggregator row may legitimately reuse a
   proposer's model (a model both drafts and fuses).
3. **Fallback:** if no `aggregator` row exists, the aggregator falls back to the
   currently routed model — the same model the user would have gotten without
   the ensemble — so a proposer-only config still runs instead of erroring at
   turn time. The plan records `aggregator.source` as `candidate_role` or
   `inherited_model` accordingly.

### Lineup bounds & validation

Enforced by `LlmEnsembleConfig._validate_custom_b5_lineup`
(`src/opensquilla/gateway/config.py`), checked **only** when
`selection_mode == "custom_b5"` (presets carry fixed lineups; `router_dynamic`
selects per turn):

- At most **one** enabled candidate may carry role `aggregator`.
- Enabled proposer count must stay within
  `[CUSTOM_B5_MIN_PROPOSERS=2, CUSTOM_B5_MAX_PROPOSERS=6]`.
- Total per-turn calls are capped at `CUSTOM_B5_MAX_TOTAL_CALLS=8`
  (proposers + aggregator).

### Readiness gate

`custom_b5_lineup_ready` returns `(ready, reason)` before wrapping the turn. It
fails closed with a machine-readable reason when the lineup is not runnable:
`no_proposers`, `unknown_provider:<p>`, or `missing_credential:<p>` (a member
whose provider requires a key but resolves none). This mirrors the static-preset
gate — a member with an empty bearer token would post the conversation upstream
unauthenticated, so the wrap is skipped.

## 1.3 Shared fixed-lineup defaults

Both static families set `is_static_b5 = True` in
`build_ensemble_provider_from_config`, which swaps the legacy per-turn defaults
for the fixed-lineup family defaults. The swap is **only** applied when the
configured value still equals the legacy default (`_static_default_if_legacy`),
so any operator override is preserved:

| Parameter | `router_dynamic` default | Fixed-lineup default |
|-----------|---------------------------|----------------------|
| `min_successful_proposers` | 1 | 3 (presets) / `N-1` (custom, "all but one") |
| `proposer_timeout_seconds` | 3600 | 300 |
| `aggregator_timeout_seconds` | 3600 | 480 |
| `shuffle_candidates` | `True` | `False` |
| `quorum_grace_seconds` | 0 | 30 |

`min_successful_proposers` is additionally clamped down to the actual proposer
count. Both the configured and effective values (min-success, timeouts, shuffle)
are recorded in the selection plan for debugging.

## 1.4 Member provider resolution

Every member (static or custom) resolves its concrete `ProviderConfig` through
`_member_provider_config`, which layers member intent over the inherited/routed
provider config:

- **API key** — a member-level `api_key_env` env var if set; else the inherited
  key when the member's provider matches the active provider; else the provider
  registry's env key (e.g. `OPENROUTER_API_KEY`).
- **`base_url`** — member override, else the inherited base URL (same provider)
  or the provider spec's default base URL.
- **`proxy` / `org_id` / `provider_routing`** — inherited only when the member
  shares the active provider; otherwise reset.

This is what lets a static/custom lineup run against a provider the user isn't
actively routing to, as long as that provider's credential is present in the
environment.

## 1.5 Configuration surface

```toml
[llm_ensemble]
enabled = true
selection_mode = "static_openrouter_b5"   # or static_tokenrhythm_b5 / custom_b5
```

Custom lineup:

```toml
[llm_ensemble]
enabled = true
selection_mode = "custom_b5"

[[llm_ensemble.candidates]]
provider = "openrouter"
model = "deepseek/deepseek-v4-pro"
role = "primary"

[[llm_ensemble.candidates]]
provider = "openrouter"
model = "z-ai/glm-5.2"
role = "contrast"

[[llm_ensemble.candidates]]
provider = "openrouter"
model = "z-ai/glm-5.2"
role = "aggregator"
```

Static presets expose no lineup tuning — the models are fixed in code. Custom
lineups are tuned entirely through the `candidates` list (subject to the bounds
above). Both share the fixed-lineup runtime defaults, which an operator may
still override explicitly (`min_successful_proposers`,
`proposer_timeout_seconds`, `aggregator_timeout_seconds`, `shuffle_candidates`).

---

# Part 2 — `router_dynamic` Step2 Ranking

> **Status: supported, config-only.** The Web UI still offers the static
> families and migration to `custom_b5`, but existing TOML/RPC configs can use
> `router_dynamic`. Its implementation is the profile-driven Step2 ranking
> pipeline, not the former fixed slot-template algorithm.

`router_dynamic` chooses proposer set `P` and aggregator `A` independently for
every turn. The implementation is split across:

- `src/opensquilla/provider/ranking_router.py` — context adapters, task-profile
  validation, hard filters, scoring, greedy selection, and trace generation;
- `src/opensquilla/provider/router_dynamic_model_profiles.json` — versioned
  mock model registry and static/online profiles;
- `src/opensquilla/provider/router_dynamic_ranking_config.json` — the complete
  dynamic-routing parameter set, including limits, fallback/mock defaults,
  hard-filter states, ranking, reranking, proposer count, and session behavior;
- `src/opensquilla/provider/ensemble.py` — deployment availability and member
  construction;
- `src/opensquilla/engine/runtime.py` — analyzer invocation, per-session route
  continuity, usage accounting, and single-provider fail-open behavior.

## 2.1 Per-turn inputs

Before ranking, runtime builds four replaceable inputs:

1. **Request context** — bounded conversation summary/recent turns, tool and
   workspace state, attachment references and actual input modalities, token
   budgets, and the previous route. Caller-supplied context is projected onto
   this fixed schema; unknown fields are dropped and every text/list field is
   bounded before it reaches the analyzer. The trace stores a SHA-256 hash
   rather than raw prompt content.
2. **Task profile** — a dedicated OpenRouter deployment of
   `anthropic/claude-opus-4.8` is called once as the JSON classifier. It never
   reuses the model selected by the single-model route. The result must contain
   normalized capability, domain, and tier distributions plus cost, latency,
   context, modality, risk, and session-intent constraints. Invalid JSON,
   timeout, provider errors, an omitted real input modality, an invalid schema,
   or an unavailable OpenRouter credential falls back to a conservative profile
   derived from SquillaRouter's `c0`-`c3` result.
3. **User profile** — currently a versioned global mock with permissions,
   cost/latency preference, and empty feedback priors.
4. **Model registry snapshot** — composed from the routed model, enabled
   `llm_ensemble.candidates`, non-default legacy `model_options`, configured
   SquillaRouter tiers, and the packaged twenty-model mock registry. Unknown
   deployments receive deterministic synthesized priors. Credential presence
   is added as an availability fact before ranking. Malformed profile rows and
   duplicate case-normalized deployment identities are rejected before pool
   composition; they are never silently dropped or merged.

The analyzer defaults to a 20-second outer timeout, bounded input/output sizes,
and `temperature=0`; those values and its thinking mode are read from the
ranking JSON. It records token and billed-cost usage in the normal session usage
tracker. A syntactically valid JSON fragment is accepted only after the provider
emits its terminal `DoneEvent`; incomplete streams use the fallback profile.

## 2.2 Hard filters

Every candidate is checked separately for proposer and aggregator roles before
it can be scored. A candidate is rejected for any of these reasons:

- disabled/unhealthy deployment, missing credential, exhausted quota, or rate
  limit;
- unsupported role, user model allow/deny policy, or disallowed task-risk level;
- missing any required input modality;
- insufficient context window.

Context need includes the expected output, not just the prompt:

```text
C_proposer   = C_input + C_tools + C_candidate
C_aggregator = C_input + C_tools + |P| * C_candidate + C_aggregator_output
```

`C_tools` is derived from the bounded tool state when no larger caller token
estimate is available. Candidate text caps use a conservative one-token-per-
retained-character bound; they do not assume four characters per token or
reduce that bound using the routed anchor's model-specific generation cap.

Aggregator feasibility is checked during every proposer-selection step, so the
greedy selector cannot build a proposer set that no remaining aggregator can
consume.

## 2.3 Base scoring

For each eligible proposer, task match combines capability, domain, and tier
profile expectations. It is blended with the mock user score, then adjusted by
weak session continuity and normalized cost/latency penalties:

```text
S_match_raw  = 0.45 * capability + 0.25 * domain + 0.30 * tier
S_match      = 0.82 * S_match_raw + 0.18 * proposer_role_fit
S_qual_clean = 0.85 * S_match + 0.15 * S_user
S_qual       = clamp(S_qual_clean + S_session)
S_base       = S_qual - w_cost * cost - w_latency * latency
```

`S_user` starts at `0.50`; positive/negative model feedback contributes up to
`+/-0.50`, with confidence saturated after 20 observations. Cost is
`(0.30 * input_price + 0.70 * output_price) / 40`, and latency is
`p95_ms / 30000`, both clamped to `[0, 1]`. Their weights come from task
constraints plus user preference. Ties are deterministic: higher score, then
higher quality, then lexical deployment identity. These defaults, including
normalization denominators and blend weights, come from the ranking JSON.

## 2.4 Dynamic proposer count

The effective tier is the rounded expectation of `tier_dist`:

| Effective tier | SquillaRouter tier | `N_min` | `N_max` |
|----------------|--------------------|---------|---------|
| 1 | `c0` | 1 | 1 |
| 2 | `c1` | 1 | 2 |
| 3 | `c2` | 2 | 3 |
| 4 | `c3` | 3 | 5 |

High-risk work raises the target to at least four proposers (maximum five).
Hard cost/latency constraints cap the set at two; when filters or the candidate
pool prevent `N_min`, ranking returns the best feasible set and records
`coverage_shortfall=true` instead of violating a hard filter.

## 2.5 Greedy proposer selection

This stage is a deterministic feature-based rerank; it does **not** call an
additional LLM or cross-encoder reranker. Ranking keeps the top
`L = max(8, 2*N_max)` base-score rows (bounded by pool size), then applies the
quality floor below. The default margin is `0.28` for low risk, `0.20` for
medium risk, and `0.12` for high risk:

```text
quality_floor = max(S_base_clean in top-L) - risk_margin
```

Candidates below that floor cannot enter `P`. For every remaining candidate at
every step, the selector first checks that at least one aggregator could still
consume the complete proposed set. It then recomputes the candidate's marginal
gain against the already selected models:

```text
marginal = 0.55 * quality
         + 0.30 * capability_coverage_gain
         + 0.10 * error_complementarity
         - 0.25 * max_similarity_to_selected
```

`capability_coverage_gain` is the task-profile-weighted positive improvement
over the best selected model for each requested capability. Similarity is
`0.50 * cosine(capability vectors) + 0.50 * lineage`, where lineage is `1.0`
for the same family, `0.50` for only the same vendor, and `0` otherwise. Error
complementarity is `1 - max cosine` over the configured online error-rate
dimensions (`hallucination`, `omission`, `format_error`, `tool_error`, and
`timeout` by default); it is zero before the first selection or when the
candidate has no error signal.

Marginal rows sort by marginal gain, clean base score, quality, then lexical
deployment identity. Once `N_min` is satisfied, selection stops if the best
marginal gain is below the configured threshold (`0.0` by default). The trace
records each component and the top three alternatives for every step, plus
whether selection reached `N_max`, exhausted the pool/quality floor, or could
not preserve aggregator feasibility.

## 2.6 Aggregator selection

After `P` is fixed, all aggregator-eligible models are rescored with the full
aggregator context requirement:

```text
S_agg_qual = 0.78 * task_match + 0.22 * aggregator_role_fit
Score_agg  = S_agg_qual + S_session
           - overlap_bias - w_cost * cost - w_latency * latency
```

Reusing a proposer incurs a self-overlap penalty; sharing its family or vendor
adds a related-model penalty (`0.08` and `0.05` by default). Aggregator rows
sort by final score, quality, then lexical deployment identity. Candidate
drafts are always anonymized. If the chosen aggregator overlaps a proposer,
candidate order is randomized to reduce position/self-preference bias. Each
aggregation trace records both the random seed and the resulting candidate-index
order so the exact aggregator input can be replayed without relying on
process-global RNG state.

## 2.7 Session intent

Session adjustments activate only when analyzer confidence is at least `0.60`
and a previous dynamic route exists:

- `continue` adds at most `+0.10` (scaled by prior quality feedback) to models
  from the previous `P/A`;
- `redo` subtracts `0.10` from the previous `P/A` and shifts `tier_dist` up one
  tier, with at most two consecutive escalations;
- `new_task` clears escalation state.

Runtime keeps only route identities, feedback, and escalation level in a
bounded in-memory cache of 1,024 sessions. It never stores prompt or candidate
content there.

## 2.8 Output, fallback, and observability

`_build_router_dynamic_members` returns `router_dynamic/c0` through
`router_dynamic/c3`, `proposer_1...N`, one `aggregator`, and a replay-oriented
selection plan. When the configured quorum is still the legacy value `1`, the
effective quorum becomes the ranking result's `N_min`, clamped to the selected
proposer count. Explicit timeouts remain unchanged.

If config/context preparation fails, or no proposer or aggregator survives hard
filtering, ranking raises `DynamicRankingError`; runtime records
`router_dynamic_ranking_unavailable` and continues with the already selected
single-model provider. Failure to resolve or construct the fixed analyzer itself
uses the deterministic task-profile fallback locally and does not abort ranking.

The plan/logs include analyzer provenance and usage, task/profile/request
hashes, registry version and exact snapshot hash, per-model profile hashes,
hard-filter reasons, all base scores, `N_min/N_max`, every greedy step, selected
`P/A`, aggregator overlap/bias, coverage shortfall, stop reason, and session
escalation. It also stores the ranking-config schema version, config version,
SHA-256 hash, and complete parameter snapshot. The execution trace additionally
records `candidate_order_seed` and
`candidate_display_order`. Structured lifecycle events are:

- `task_analyzer_started`, `task_analyzer_completed`, or
  `task_analyzer_fallback`;
- `candidate_pool_recorded` and `model_scores_recorded`;
- `proposer_selection_recorded` and `aggregator_selection_recorded`;
- `router_decision_recorded`.

All use the `llm_ensemble.router_dynamic.` event prefix and omit raw user or
candidate content.

## 2.9 Configuration surface

```toml
[llm_ensemble]
enabled = true
selection_mode = "router_dynamic"
```

Operators can extend the deployment pool with `llm_ensemble.candidates`,
non-default `llm_ensemble.model_options`, and `squilla_router.tiers`. All
tunable Step2 behavior lives in
`src/opensquilla/provider/router_dynamic_ranking_config.json`:

| JSON group | Controls |
|------------|----------|
| `validation`, `trace` | sum tolerance, trace precision, and nonzero epsilon |
| `routing_tiers` | `c0`-`c3` mapping and default tier |
| `context` | context buckets, request truncation, token estimates, output budgets |
| `task_profile_schema` | accepted task constraints and session intents |
| `task_analyzer` | timeout, input/response limits, output tokens, temperature, thinking |
| `fallback_task_profile` | deterministic analyzer-failure profile and tier risk |
| `mock_user_profile` | current global mock permissions, preferences, and history |
| `synthetic_model` | facts and priors for deployments missing a catalog profile |
| `hard_filter` | eligible/unavailable states and default required modalities |
| `exploration` | reserved trace declaration; must remain `false` / propensity `1.0` until exploration is implemented |
| `normalization` | input/output price blend and cost/latency denominators |
| `task_match`, `user_score`, `quality` | base task, role, user, and quality weights |
| `penalties` | task/user cost and latency weights and trade-off adjustments |
| `session` | intent threshold, continuity delta, feedback default, redo ceiling |
| `proposer_count` | tier/risk bounds and cost/latency caps |
| `rerank` | top-L, quality floors, marginal weights, similarity, errors, stop rule |
| `aggregator` | task/role blend and overlap penalties |

Runtime loads one versioned snapshot and passes it through context construction,
task analysis, registry synthesis, and final ranking. The loader validates
the exact key set at every fixed object, distributions, normalized weight
groups, numeric ranges, protocol-valued maps, and count bounds before selection.
Unknown, misspelled, missing, or currently inactive settings therefore fail
explicitly instead of appearing to take effect. A malformed config raises
`DynamicRankingError`, so runtime follows the existing single-model fail-open
path. The packaged config is cached; editing it requires a process restart.
The twenty catalog mock profiles remain separately versioned in
`router_dynamic_model_profiles.json`; defaults used to synthesize an unknown
deployment are in the ranking JSON. Protocol enums, probability bounds, and
deterministic tie-break order remain code contracts rather than tuning knobs.
`router_dynamic` retains its 3,600-second proposer/aggregator timeouts and zero
quorum-grace default.

The fixed task analyzer resolves its OpenRouter credential from the active or
primary OpenRouter config, `[llm_profiles.openrouter]`, or
`OPENROUTER_API_KEY`. If none is available, task analysis uses the deterministic
fallback profile; it does not call the routed single-model provider.
