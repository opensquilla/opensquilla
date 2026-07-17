# Ranking User Profile Spec

Date: 2026-07-17
Status: Draft

## Problem

`docs/features/LLM-ensemble-design.md` §3.1 lists the user profile as one of
four per-turn inputs to `router_dynamic` ranking. Every consumer of that input
is built and wired. The input itself is not: it is a hardcoded global mock.

The mock is inert, not merely approximate. With the shipped
`mock_user_profile` block:

- `permission.allow_models` and `permission.deny_models` are empty and
  `permission.risk_allowlist` is `["low", "medium", "high"]`, so every
  permission hard filter in `_hard_filter_reasons` is a no-op.
- `history` is empty, so `_user_score` returns `neutral_score` (`0.50`) for
  every candidate. Because `quality_clean = 0.85 * task_match + 0.15 * S_user`,
  a constant `S_user` is a uniform offset across all candidates and **cannot
  change model ordering**.

The observable consequence: toggling `ranking_user_profile_enabled` today
changes rankings only through `_proposer_bounds` and `_cost_latency_weights`,
both of which read the same all-neutral mock preferences. The scoring half of
the feature has never affected a routing decision.

Meanwhile real thumbs up/down feedback is already collected and persisted
(`self_learning/feedback.py`), with a live Web UI and RPC intake. Nothing reads
it for routing.

There is also a privacy defect that is latent today: `ranking_router.py:2069`
places the entire profile into the task analyzer's prompt and ships it to a
third-party provider unredacted. `_canonical_hash` is applied to `task_profile`
and `request_context` but never to `user_profile`. This contradicts the design
doc's §3.8 claim that routing events carry no "raw user-profile payload" — the
events are clean, but the analyzer request is not. It costs nothing today
(the mock is all-neutral) and costs something the moment the profile is real.

## Goals

- Replace the hardcoded mock with a single global profile stored as one local
  JSON file.
- Derive `history` from the feedback that is already being collected, so
  `S_user` varies per candidate and can affect ordering.
- Stop sending the profile to the task analyzer.
- Preserve the existing fail-open contract: no profile failure may fail a turn
  or abort ranking.
- Keep `ranking_user_profile_enabled = false` a true ablation.

## Non-Goals

- **No new database tables, no new migration, no new sqlite schema.** The
  profile is a file. The one existing table this reads (`router_decisions`,
  V017) is read-only and already present.
- **No user identity.** OpenSquilla is a local, single-operator application.
  There is no `user_id` anywhere in the codebase and this spec does not add one.
  "User" here means "the person using this install" — a set of size one.
- **No per-agent profiles.** One global profile, matching the existing
  `profile_source: "mock_global_default"` contract and the global `active` file
  precedent. Feedback given to any agent updates the same profile.
- Do not change the ranking formulas or the `user_score` JSON block. This spec
  changes what feeds `S_user`, not how `S_user` is computed.
- Do not change the four fixed/custom/tree selection modes.
- Do not expose the profile in the Web UI settings surface.
- Do not implement exploration; `exploration` stays `false` / propensity `1.0`.

## Existing Surfaces

Ranking consumers (all already built, none change):

- `mock_user_profile()` — `ranking_router.py:1449`.
- Profile shape validated at `ranking_router.py:851-913`; key whitelist at
  `:366`, `:451-471`.
- `_hard_filter_reasons(...)` — `ranking_router.py:2860`. Reads
  `permission.allow_models` / `deny_models` / `risk_allowlist` (task risk
  compared at `:2891`).
- `_user_score(...)` — `ranking_router.py:3023`. Reads
  `history.positive_model_ids`, `history.negative_model_ids`,
  `history.feedback_count`, `preference.preferred_formats`.
- `_cost_latency_weights(...)` — `:3128`. `_proposer_bounds(...)` — `:3536`.
- None-vs-empty split — `:3713-3714`.
- `_permission_matches` — `:2751`, case-insensitive against `model.model_id` or
  `model.identity`.

Injection seams (two; they must not diverge):

- `runtime.py:5508` — `mock_user_profile(ranking_config) if ranking_user_profile_enabled else None`.
- `ensemble.py:1715-1724` — prefers `inputs["user_profile"]` when supplied,
  falls back to `mock_user_profile(ranking_config)`.

Feedback:

- `self_learning/feedback.py` — append-only JSONL. `write_feedback()` (`:73`),
  `load_feedback_map()` (`:149`, effective rating per `decision_id`,
  last-write-wins), `scan_feedback_stats()` (`:175`).
- `FeedbackEntry` carries `rating` and `executed_kind` only — not the model. The
  JSONL sidecar alone cannot answer "which model was rated".
- RPC intake: `gateway/rpc_router.py:114` `router.feedback.submit`. The handler
  resolves the full decision row before writing (`:144-158`) and already derives
  `session_key`, `turn_index`, and `executed_kind` from it.
- `RouterDecisionWriter.get_decision(decision_id)` —
  `persistence/router_decision_writer.py:411`. Selects all of `_COLUMNS`,
  including `model` (`:65`), a sanitized token column. Docstring: "Reverse-lookup
  surface for feedback attribution."
- `router_decisions` (V017) — `decision_id` PK, with `provider`, `model`,
  `final_tier`, `executed_kind`. The only place `decision_id → model` exists,
  and it is already being read on every feedback submit.

File layout precedent — `self_learning/store.py:1-17`:

```text
~/.opensquilla/router/
    data/<agent_id>/samples-YYYYMMDD.jsonl   # per-agent
    data/<agent_id>/feedback.jsonl           # per-agent
    learned/<version>/
    active                                   # global, not agent-scoped
```

`active` establishes that a global file at the router root is an existing
convention. Conventions to copy from `feedback.py` / `store.py`: pure
functions, injectable `home`, no raw prompt text, best-effort writes wrapped so
a turn never fails, `_write_lock` serializing read-modify-write.

## Design

Four changes. Changes 1-3 are one unit (the file, its writer, its reader).
Change 4 depends on nothing here and ships first on its own.

### 1. The file

`~/.opensquilla/router/profile.json` — one global file, sibling of `active`.
New module `self_learning/profile.py`, following `feedback.py`'s conventions
exactly.

```json
{
  "schema_version": 1,
  "permission": {
    "allow_models": [],
    "deny_models": [],
    "risk_allowlist": ["low", "medium", "high"]
  },
  "preference": {
    "quality_latency_tradeoff": "balanced",
    "cost_sensitivity": "medium"
  },
  "model_counts": {"<model_id>": {"up": 0, "down": 0}},
  "history": {
    "positive_model_ids": [],
    "negative_model_ids": [],
    "feedback_count": 0,
    "last_updated_at": "<iso8601>"
  }
}
```

`permission` and `preference` are hand-editable — this file *is* the
configuration surface, so no new TOML keys are needed. `history` is
machine-written.

`model_counts` is the raw per-model tally and the only new field. It is written
and read only by `profile.py` and stripped before the profile reaches ranking,
so what ranking receives is exactly the mapping shape its consumers already
expect. `positive_model_ids` / `negative_model_ids` / `feedback_count` are
derived from the tally on write. Keeping the raw tally is what lets a rating be
revised or revoked without replaying the whole JSONL.

**The tally is the system of record, not a cache of the log.** Replay is not
merely unimplemented, it is impossible: `feedback.jsonl` is pruned by
`retention_days` (default 30) while `model_counts` accumulates forever, so the
log is lossy by design and cannot rebuild the tally. Nothing reconciles the two
because nothing can. This is the right trade — replay would mean retaining the
log indefinitely, against the same retention and privacy posture that makes the
file storable — but it is what puts the whole weight of correctness on the delta
path: a lost or double-counted delta is permanent. That is why the merge-then-
filter order in `load_feedback_map` and the lock spanning read-append-fold are
tested rather than merely documented.

**Validation.** `profile.py` needs its own loader-validator: the existing
checks at `ranking_router.py:851-913` read
`config["mock_user_profile"][...]` and validate the *ranking config*, not a
free-standing profile file. The new validator must enforce the same
vocabularies — `risk_allowlist` values, `quality_latency_tradeoff`,
`cost_sensitivity` — and a test must pin both to the same enum sources so the
two cannot drift apart. Drift here is not a crash; it is a hand-edited value
that one validator accepts and the other silently ignores.

**Provenance is not in the file.** `profile_version` and `profile_source`
describe a *read* — which profile ranking got, and what was in it — so the read
seam derives both and the writer stores neither. `profile_version` is a content
hash of the resolved profile, taken after the overlay, so it changes exactly
when what ranking ranked with changes; `profile_source` is `global_json`, or
`fallback_mock` when the file is missing or unusable.

Storing them would be worse than redundant. The file is hand-editable, so a
stored `profile_source` lets it claim `fallback_mock` while ranking uses it, and
a stored `profile_version` misses the one edit the file exists for: `deny_models`
has no TOML key, and editing it never runs the write path that would stamp a new
version. A stored hash would also be computed over a different body than the
emitted one — two values under one name, so an operator matching a decision's
version against the file finds a mismatch for an unchanged profile.

Writes are atomic (`tmp` + `os.replace`) under a module-level `_write_lock`,
mirroring `feedback.py:_write_lock` — RPC submissions run on worker threads and
a lost rating is a defect.

**Privacy contract.** Model identity tokens, enum tokens, and integers only. No
prompt text, no response text. Same bar as `feedback.jsonl`.

### 2. Updating history on feedback

`router.feedback.submit` **already resolves the decision row it needs**
(`rpc_router.py:144-158`):

```python
record = await anyio.to_thread.run_sync(writer.get_decision, decision_id)
if record is None:
    return {"accepted": False, "reason": "decision_not_found"}
```

`get_decision` (`router_decision_writer.py:411`) selects every column of
`_COLUMNS`, which includes `model` (`:65`) — already a sanitized token column
(`_TEXT_TOKEN_COLUMNS`, `:81`). Its docstring names this exact use: "Reverse-
lookup surface for **feedback attribution**".

The lookup needs no new query and no new schema, and it is already off the event
loop and already fail-open. **But the column does not yet hold the right value.**
On ensemble turns `record["model"]` names the *classifier's* pick, not the model
that authored the reply: `router_decision_record.py:227` stages the classifier's
choice, and the realignment at `:268-273` is guarded `if not ensemble_enabled:`.
Attributing feedback to it would train the profile on a model the user never
read. Unit 2.A fixes the writer first; only then is the column a valid key.

The corrected key is `final_request["execution"]["model"]`, staged by
`_member_execution_trace` (`ensemble.py:1457`) from `cfg.model`.

**Which namespace the key inhabits is the load-bearing detail**, and getting it
wrong survived three review rounds. The key must live in **config space** — the
same namespace as `RankedModel.model_id`, which is what `_user_score` matches
`positive_model_ids`/`negative_model_ids` against. `cfg.model ≡
RankedModel.model_id` holds by construction (`ensemble.py:1830` sets
`model=decision.aggregator.model_id`; `_member_provider_config` only strips), so
the join is safe. `usage.model` (`:1520`) is **response space** — what the
provider reports it actually ran — and is forensics only. Sourcing the key there
would silently mismatch the registry on any provider that renames or versions a
model in its response. When the key cannot be resolved, fail **closed**: write
`None` and skip the update rather than attribute to a guess.

The change is: after `write_feedback()` succeeds, increment
`model_counts[<key>][rating]` and rewrite the derived fields.

Rules:

- **Read `load_feedback_map()` before `write_feedback()` appends.** The
  decrement rule below needs the *previous* effective rating for this
  `decision_id`; reading after the append returns the new one and the decrement
  silently becomes a no-op. Ordering is part of the contract, not an
  implementation detail.
- Use the effective rating, not the raw append. `load_feedback_map()`
  (`feedback.py:149`) already resolves last-write-wins, so a thumb toggled back
  to `neutral` must **decrement** the previous rating rather than be ignored.
  Getting this wrong makes revocation impossible.
- `neutral` contributes to neither list and does not count toward
  `feedback_count`.
- A model goes in `positive_model_ids` when `up > down`, `negative_model_ids`
  when `down > up`, and **neither when equal**. `_user_score` computes `signal`
  as `int(in_positive) - int(in_negative)` (`:3000-3002`), so membership in both
  would silently cancel to zero — excluding it says the same thing honestly.
- `feedback_count` is the total of non-neutral ratings. It drives
  `confidence = min(1.0, feedback_count / 20)`, so `S_user` ramps in gradually
  instead of swinging to an extreme on the first click.
- `executed_kind = "ensemble"` attributes to the aggregator only. It authored
  the text the user actually read; the proposers' drafts were never shown. This
  is **provisional** — see "Revisit" below.
- The whole update is wrapped `try/except` → `log.warning`. The RPC already
  refuses to fail a client on a feedback write error (`rpc_router.py:194-198`);
  a profile update failure must be no louder.

Because counts accumulate in the file, they do not decay when
`router_decision_writer` prunes at 30 days — the decision row only needs to
exist at the moment the thumb is clicked. A thumb on a pruned decision already
returns `decision_not_found` and writes no feedback at all
(`rpc_router.py:151-158`); that is pre-existing behavior this spec neither
worsens nor fixes.

### 3. Reading it

`runtime.py:5508` becomes:

```python
user_profile = load_profile() if ranking_user_profile_enabled else None
```

Cached in-process, **invalidated on mtime change** — not on write alone.

The packaged ranking config is cached and requires a restart to pick up edits
(design doc §3.9), but copying that here would be wrong. `profile.json` is
unlike that file in one decisive way: it *rewrites itself* while the process
runs, every time a thumb is clicked. So an invalidation path has to exist
regardless. Keying it on write alone produces genuinely confusing behavior —
the file updates itself when you click a thumb, but ignores you when you
hand-edit `deny_models`. An `os.stat` per turn is microseconds against a turn
that already spends seconds in LLM calls, and it makes the file behave the way
its being hand-editable implies.

Any failure — missing file, malformed JSON, failed validation — degrades to
`mock_user_profile(ranking_config)` with `profile_source = "fallback_mock"` and
logs a warning. Never raises, never fails a turn.

`ensemble.py:1718` already prefers `inputs["user_profile"]`, so the runtime path
needs no change there. Its `:1724` fallback **stays on `mock_user_profile()`**.
Pointing it at `load_profile()` would be actively harmful: that fallback is what
callers with no `inputs["user_profile"]` get — benchmarks and the routing
experiment runner among them — and it would silently feed the operator's
personal profile into runs that must stay deterministic and reproducible. The
two seams *should* disagree: `runtime.py:5508` is the one place a real user's
profile enters, and it is the only read seam this spec adds.

`mock_user_profile()` and its JSON block **stay** — they are the deterministic
test fixture and the `enabled = false` ablation baseline, and removing them
would churn the config validator's exact-key-set contract for no benefit.

### 4. Analyzer de-exposure

Delete `analyzer_input["user_profile"] = user_profile`
(`ranking_router.py:2069-2070`).

The analyzer's job is to classify the *task* — capability, domain, tier, and
constraint distributions. Those are properties of the request, not of who is
asking. Every real consumer of the profile is local and deterministic, and
nothing downstream reads a profile-derived field *from* the analyzer's
response, so removing it from the prompt costs no signal.

`analyze_task_with_provider(...)` keeps its `user_profile` parameter for one
release, ignored except for the `user_profile_enabled` log field it already
emits (`:1999`, `:2080`, `:2168`, `:2203`), then drops it. This avoids a
same-release signature break at `runtime.py:5517-5531`.

### Observability

`user_profile_version` and `user_profile_source` are already written into the
plan (`ranking_router.py:4040-4042`) and turn metadata (`runtime.py:5547-5559`),
but `ensemble_observability.py` never reads them. Emit both on
`llm_ensemble.routing.decision_completed`, next to the `user_profile_enabled`
bit it already emits at `:314`. Without this, a decision influenced by a learned
profile is not explainable after the fact — the log says a profile was on, but
not which one. Both values are already safe to log: a hash and an enum.

### Dead fields

Three fields are validated but not honored. A real profile forces a decision on
each rather than leaving them as false affordances:

- **`history.capability_prior`** — validated at `:885-903`, read by nothing.
  **Drop.** Thumbs up/down attributes a rating to a *model*, not a capability.
  There is no signal that could populate it without inventing one.
- **`permission.allow_tools`** — validated at `:853`, never consulted by
  `_hard_filter_reasons`. **Drop.** Tool permissions are owned by
  `safety/permission_matrix.py` and `safety/tool_tiers.py`. A second per-profile
  tool list would be a competing authority over the same question.
- **`preference.preferred_formats`** — gates a bonus at `:3054-3061`, but the
  format *values* are never compared against the model; the bonus keys off
  generic `format_following` strength, so `["json"]` and `["markdown"]` are
  identical. **Drop**, for two reasons beyond the false name:

  1. **The real format mechanism already exists and is untouched.** `_task_match`
     (`:3008-3017`) handles a task-pinned format properly, multiplying match by
     `format_base_multiplier + format_strength_multiplier * format_following`.
     The `_user_score` branch fires only when the task did *not* pin a format
     (`:3054`), so the two never overlap — deleting the user-side one loses no
     format handling, only a vague "this user likes tidy output" nudge.
  2. **Its magnitude is noise.** `0.05 * strength` (strength ≈ 0.7–0.97) lands in
     `S_user`, which carries `quality.user_score_weight = 0.15` — a maximum
     contribution of **0.0075** to quality, against a `risk_margin` quality floor
     of 0.12–0.28. It cannot decide anything.

  Deletion sites (the exact-key-set validator will catch a miss): `:467` and
  `:527` (key whitelists), `:878-882` (validation), `:1015` (unit-interval
  paths), `:3051-3061` (the branch), and `router_dynamic_ranking_config.json:118`
  and `:198`. `format_following` stays — it is a capability dimension every model
  declares, still consumed by `_task_match` and the capability distribution.

  Note `_user_score`'s `task_profile` parameter becomes unused once the branch is
  gone (`optional_constraints` was its only reader). Drop it from the signature.

All three drops are config-schema changes guarded by the validator's
exact-key-set contract, so they fail loudly rather than silently.

`permission.risk_allowlist` stays. Note its `low`/`medium`/`high` vocabulary
deliberately does **not** match `RiskTier`'s `SAFE`/`CONFIRM`/`ADMIN_ONLY`
(`tool_tiers.py:31-36`): the profile's values are compared against
`task_profile.constraints.risk` (`:2891`), a *task* risk level, not a tool tier.
These are different axes and must not be unified.

## Test Plan

Existing coverage to preserve:

- `tests/test_ranking_router.py:1051` —
  `test_ranking_without_user_profile_bypasses_all_profile_effects`. The
  `enabled = false` ablation must stay exact.
- `tests/test_ranking_router.py:854` —
  `test_task_analyzer_uses_provider_interface_and_validates_json`. This is the
  test Change 4 inverts: it supplies a profile and asserts it reaches the
  analyzer payload, which is the privacy defect itself. It now asserts absence.
- `tests/test_ranking_router.py:858` —
  `test_task_analyzer_omits_disabled_user_profile_and_correlates_logs`. Its
  assertion still holds unchanged, but the name no longer describes it: omission
  is unconditional now, not a property of the disabled path. Renamed to
  `test_task_analyzer_omits_user_profile_and_correlates_logs`; it keeps the
  `user_profile_enabled is False` log assertion for the `None` case.

New coverage:

- **Ordering changes.** The regression that matters most, and the one that
  would fail today: a profile with non-empty history must produce a *different*
  proposer set than the same turn with empty history. This is the entire point.
- Revocation: `up` then `neutral` on one `decision_id` returns `model_counts` to
  its prior state; `up` then `down` moves the model between lists.
- Equal up/down lands in neither list.
- `feedback_count` counts only non-neutral ratings; confidence clamps at 20.
- Fail-open: missing file, malformed JSON, and a profile failing validation each
  degrade to the mock and complete the turn. An unresolvable `decision_id` never
  reaches the profile code — `rpc_router.py:151-158` returns early — so the
  profile update must tolerate a `record["model"]` that is `NULL` or absent
  rather than assume the row is well-formed.
- Concurrency: parallel `router.feedback.submit` calls do not lose a rating
  (the `feedback.py` read-rewrite-replace precedent).
- Privacy: no prompt or response text can reach `profile.json`.
- Seam agreement: `runtime.py` and `ensemble.py` resolve the same profile.
- Hand-edit reload: writing a new `deny_models` to the file takes effect on the
  next turn without a restart, and the mtime check does not re-read an unchanged
  file.
- Dropped fields fail loudly: a ranking config still carrying
  `capability_prior`, `allow_tools`, `preferred_formats`, or
  `preferred_format_bonus` is rejected by the exact-key-set validator; a
  `profile.json` carrying them is rejected by the new loader rather than
  silently ignored. This is what stops a stale hand-edited file from looking
  like it still works.
- Validator agreement: the `profile.py` loader and
  `ranking_router.py:851-913` accept and reject the same vocabularies, pinned to
  shared enum sources.

## Rollout

1. Change 4 (analyzer de-exposure) ships first, alone. It is a pure deletion,
   depends on nothing else here, and closes the exposure before any real data
   can flow.
2. Changes 1-3 ship together. On first run there is no `profile.json`, so the
   fallback is the mock and behavior is identical to today.
3. The profile only starts affecting routing as feedback accumulates, and only
   gradually — `confidence` saturates at 20 ratings, so early history moves
   `S_user` very little by design.

No migration, no backfill. Existing installs have no `profile.json` and resolve
to `fallback_mock` until the first thumb is clicked.

`docs/features/LLM-ensemble-design.md` §3.1 item 3, §3.9, and the
`mock_user_profile` row of the §3.9 JSON table describe the mock as the
implementation. Update them in the same change as 1-3.

## Revisit: ensemble attribution

Crediting the aggregator alone is provisional, and it is the one decision here
taken against a standing precedent in this codebase. `feedback.py`'s module
docstring warns that an ensemble rating "judges the whole
candidates-plus-aggregator chain" and must not be naively attributed, and
`FeedbackStats` acts on that warning: `downvote_rate` slices to
`down_single / total_single`, so the rollback monitor consumes **no** ensemble
ratings at all.

This spec does not follow that precedent, because it cannot. The profile is
consumed only by `router_dynamic` — an ensemble mode. Slicing ensemble ratings
out would starve the profile of exactly the turns it exists to improve, leaving
`S_user` constant and the feature inert, which is the problem this spec opens
with.

So the aggregator gets the signal, on the grounds that it authored the text the
user judged. The known weakness: a bad answer may originate in a weak proposer
that the aggregator faithfully relayed, and the aggregator is then blamed for
carrying it. Attributing to every proposer instead is not a fix — it inflates
one click into N signals and would drive `feedback_count` toward its saturation
of 20 on a handful of real clicks, making the profile look far more confident
than the evidence supports.

Revisit once `model_counts` holds real data. The signal to watch: an aggregator
accumulating down-votes while its own single-model turns rate well suggests the
blame is misplaced and proposer-level attribution is worth the complexity.
Recording proposer-level counts as a separate, unscored field would make that
diagnosable without changing `S_user`.
