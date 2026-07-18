# Ranking User Profile Spec

Date: 2026-07-18
Status: Draft (revised — profile history is now derived from Dream-consolidated
memory rather than a standalone tally; see Design)

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

- Replace the hardcoded mock with a single global profile. Its `history` is
  *derived* from Dream-consolidated memory (not a store of its own); its
  hand-editable `permission`/`preference` live in one local JSON file.
- Derive `history` from the thumbs feedback that is already being collected — by
  transcribing each thumb into a preference memory that rides the Dream
  pipeline — so `S_user` varies per candidate and can affect ordering.
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
convention — this is where `profile.json` lives, sibling of `active`. Conventions
carried over from `feedback.py` / `store.py`: pure functions, injectable `home`,
no raw prompt text, best-effort reads that never fail a turn. (The profile no
longer *writes* on the turn path — its learned half is derived from memory — so
there is no read-modify-write lock to copy; the append to the Dream scan note is
`O_APPEND`-atomic and needs none.)

## Design

The learned half of the profile — `history` — is not stored. It is **derived at
read time** from the same Dream-consolidated memory the rest of the system
already keeps, so there is no second evidence store to keep reconciled with the
first. A thumb becomes a preference *memory*; Dream promotes it into `MEMORY.md`
like any other durable fact; and the read seam projects the consolidated lines
back into the history shape ranking already consumes.

Four changes. Changes 1-3 are one unit (the transcription, the projection, the
hand-edit file). Change 4 depends on nothing here and ships first on its own.

Why derive instead of store: the earlier draft of this spec accumulated a
standalone `model_counts` tally in `profile.json`, written on every thumb. That
put a second system of record beside Dream's — one that could disagree with the
operator's own consolidated memory, needed its own lock and atomic-write path,
and its own retention story. Routing preference is a *memory* ("this operator
prefers Sonnet for coding"), and the codebase already has a component whose job
is to accumulate, deduplicate, and consolidate memories. Reusing it means the
preference the operator can read in `MEMORY.md` and the preference ranking acts
on are the *same* sentence, not two representations that drift.

### 1. Transcribing a thumb into a preference memory

On `router.feedback.submit`, after `write_feedback()` succeeds, the handler
transcribes the thumb into one preference line and appends it to the Dream scan
note. New module `self_learning/preference_projection.py`,
`transcribe_thumb(model, rating) -> str | None`:

- `up`   → `` - prefers routing to `model:<id>` ``
- `down` → `` - do not route to `model:<id>` ``
- `neutral`, or a model that cannot be resolved → `None` (write nothing).

The line is appended to `<global-workspace>/memory/routing-preferences.md`
(`ROUTING_PREF_FILENAME`). That directory is exactly where Dream scans for
evidence; the file is **not** `MEMORY.md`, which Dream treats as the
consolidation *target* and skips as a scan source — a preference written
straight there would never become evidence.

**Two contracts make the line survive the pipeline.** Both are load-bearing and
both are covered by tests:

1. **The verb lands in Dream's classifier.** Dream's `classify_signal`
   (`memory/dream/candidates.py`) buckets a line by keyword — `"prefers"` →
   positive, `"do not"`/`"don't"` → correction. `transcribe_thumb` picks its
   verbs to match, so a transcribed thumb is classified as evidence Dream will
   promote rather than discarded as chatter.
2. **The model id rides in a backticked marker.** Dream promotes by an LLM patch
   that may reword a bullet, so the id cannot live in prose — it lives in an
   inline-code token `` `model:<id>` ``. `promotion_patch_prompt`
   (`memory/dream/prompts.py`) is instructed to preserve that token verbatim,
   backticks and all, because splitting or unquoting it silently drops a routing
   preference. The projection matches the marker, never the prose.

**Which model the thumb names is still the load-bearing detail** — attributing
to the wrong one trains on a model the user never read. The rated model is
resolved exactly as before: on an ensemble turn it is the **aggregator**, in
**config space** (`RankedModel.model_id`), the namespace `_user_score` matches
against — not `usage.model` (response space, forensics only). When the model
cannot be resolved, `transcribe_thumb` returns `None` and no line is written:
fail closed, never credit a guess. (`executed_kind = "ensemble"` still credits
the aggregator alone — provisional, see "Revisit".)

**No lock, no read-before-write, no decrement.** This is the whole payoff of
deriving. Appending a line is `O_APPEND`-atomic for a short bullet, so
concurrent submits need no `profile_update_lock` — the entire race class the
standalone tally required is gone. A thumb toggled to `neutral` does not
decrement anything: neutral simply writes nothing. A revocation is expressed the
way memory expresses everything else — a later, contradicting line ("do not
route to X" after "prefers X"), which the projection collapses to *neither*
list. The tradeoff: a neutral cannot cleanly un-say a past `prefers`; only an
explicit opposite thumb, or Dream consolidating the contradiction away, retracts
it. For a single-operator preference nudge that is the honest behavior, and it
buys the deletion of the lock, the ordering contract, and the "impossible
replay" problem the tally had.

**`feedback.jsonl` is untouched.** `write_feedback()` / `load_feedback_map()`
still record the raw thumb stream for the offline trainer
(`alignment`/`dataset`); this change only *adds* the transcription beside it. The
effective-rating semantics that trainer relies on (merge-then-filter,
last-write-wins) are unchanged and still tested.

**Privacy contract.** Model identity tokens, enum tokens, and integers only. No
prompt text, no response text. The transcribed line carries a model id and a
fixed verb, nothing from the request or reply — same bar as `feedback.jsonl`.

### 2. Projecting memory into history

`project_history(memory_text) -> {positive_model_ids, negative_model_ids,
feedback_count}` (also in `preference_projection.py`) is a pure string function:
it scans consolidated `MEMORY.md` text for `` `model:<id>` `` markers, reads each
line's direction from the same verbs Dream classified on, and folds them into the
history shape.

Rules, chosen to say the same thing `_user_score` would compute anyway:

- A model asserted in **both** directions lands in **neither** list. `_user_score`
  computes `signal = int(in_positive) - int(in_negative)` (`:3000-3002`), so
  membership in both cancels to zero; excluding it says so honestly and matches
  how a consolidated contradiction reads.
- `feedback_count` is the number of preference lines seen. It drives
  `confidence = min(1.0, feedback_count / 20)`, so `S_user` ramps with how much
  the memory actually says about routing rather than swinging to an extreme on
  one line.
- A line with no marker, or no preference verb, contributes nothing — ordinary
  memories (`- The user likes dark mode`) are invisible to the projection.

The projection imports only the standard library — no `provider`, `agents`, or
`memory` — so it stays on the clean side of the `self_learning` layering rule
and the engine seam owns path resolution.

### 3. The hand-edit file and reading the profile

`profile.json` **survives, but only as the hand-edit surface** for
`permission`/`preference` — `deny_models` has no TOML key, so the file is the
only place to set it. Its write path is deleted: `update_profile_for_rating`,
`_apply`, `_derive_history`, `_atomic_write`, `profile_update_lock`, and the
`model_counts` field are all gone. What remains in `self_learning/profile.py` is
a read surface: `load_profile()` (absent/malformed/non-object → `None`), a
mtime-keyed cache handing out copies, `content_version()`, and `profile_path()`.

The read seam is `_resolve_user_profile` in `engine/runtime.py`, called from the
runtime injection point (formerly `mock_user_profile(...)` at `runtime.py:5508`).
It composes the two sources:

```
base      = mock_user_profile(ranking_config)          # deterministic skeleton
memory    = read <global-workspace>/MEMORY.md          # None if absent/unreadable
history   = project_history(memory or "")              # overlaid into base["history"]
stored    = load_profile()                             # hand-edit permission/preference
```

- The **global workspace** is `resolve_agent_workspace_dir("main", config)` —
  the same resolution Dream uses at both its wiring sites, so the note Dream
  scans, the `MEMORY.md` Dream writes, and the `MEMORY.md` this seam reads are
  guaranteed the same file with no manager logic duplicated.
- Projected history overlays **only keys the base already defines**. A hand-edit
  file overlays **only** `permission`/`preference`, and only after passing
  `validate_user_profile`; an invented key is dropped, an invalid enum
  (`cost_sensitivity: "very_high"`) **refuses the whole file and drops the
  derived history too** — a config the operator got half-wrong is untrustworthy
  whole, and `_cost_latency_weights` would silently route as if the typo were
  unmade.

**Provenance describes the read, never the file.** `profile_source` is
`"dream_memory"` when memory was read (even if it was present-but-empty) or a
valid hand-edit file was used; `"fallback_mock"` only when neither source was
read (memory absent *and* no valid file) or on any exception. Distinguishing
present-empty from absent is why the memory read returns `None` (absent) vs `""`
(present, says nothing about routing). `profile_version` is a content hash taken
*after* the overlay, so it changes exactly when what ranking ranked with changes;
a `profile_source`/`profile_version` written *into* the file is ignored, because
a hand-editable file could otherwise claim `fallback_mock` while ranking uses it.

Any failure — unreadable memory, malformed file, failed validation, an exception
mid-resolution — degrades to a freshly rebuilt `mock_user_profile(...)` with
`profile_source = "fallback_mock"` and logs a warning. Never raises, never fails
a turn, never returns a half-merge.

`ensemble.py`'s fallback **stays on `mock_user_profile()`**. Pointing it at the
derived profile would silently feed the operator's personal memory into
benchmarks and the routing experiment runner, which must stay reproducible. The
runtime seam is the one place a real profile enters. `mock_user_profile()` and
its JSON block **stay** — the deterministic fixture and the `enabled = false`
ablation baseline.

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

New coverage, grouped by the seam each covers:

*Transcription* (`test_gateway/test_rpc_router_decisions.py`):

- A thumb-up submit writes a `prefers routing to \`model:<id>\`` line into
  `memory/routing-preferences.md`, and `project_history` over that line yields
  the model as positive — the end-to-end join from click to ranking-visible
  history.
- A neutral thumb appends nothing.
- A down-after-up reads back through the projection as a contradiction (neither
  list) — revocation without a decrement path.
- Concurrent submits need no lock: N parallel appends all land, and the
  projection folds them correctly.
- The transcription is additive — the `feedback.jsonl` sidecar write still
  happens (existing sidecar test unchanged).

*Projection* (`test_router_self_learning_preference_projection.py`): direction
by verb; the backticked marker is required (prose id ignored); both-directions →
neither list; `feedback_count` = lines seen; non-preference memories invisible.

*Read seam* (`test_engine/test_resolve_user_profile.py`):

- **Ordering changes.** The point of the feature: memory carrying a preference
  produces a different history than empty memory.
- No memory and no file → `fallback_mock`; present-but-empty memory →
  `dream_memory` (the honest "read it, it said nothing" case).
- A valid hand-edited `deny_models` rides through beside the derived history; an
  invented key is not overlaid; an invalid enum or risk level refuses the file
  *and* drops the derived history to `fallback_mock`.
- The file cannot pin provenance: a `profile_source`/`profile_version` written
  into the file is ignored.
- A hand-edit moves `profile_version`; a raise mid-resolution reports
  `fallback_mock`, not a half-merge; a malformed file with no memory reports
  `fallback_mock`.

*Read surface* (`test_router_self_learning_profile.py`): absent/malformed/
non-object file → `None`; `load_profile` hands out a copy; a hand-edit is picked
up on mtime without a restart; `content_version` moves with the body and ignores
the timestamp and its own stamped output.

*Layering* (`test_router_self_learning_layering.py`): `preference_projection`
imports only the standard library, so `self_learning` never reaches into
`opensquilla.provider`.

- Privacy: no prompt or response text can reach the transcribed line or
  `profile.json`.
- Dropped fields still fail loudly: a ranking config still carrying
  `capability_prior`, `allow_tools`, or `preferred_formats` is rejected by the
  exact-key-set validator.

## Rollout

1. Change 4 (analyzer de-exposure) ships first, alone. It is a pure deletion,
   depends on nothing else here, and closes the exposure before any real data
   can flow.
2. Changes 1-3 ship together. On first run there is no preference memory and no
   `profile.json`, so memory reads empty, the projection is empty, and behavior
   is identical to today.
3. The profile only starts affecting routing after thumbs accumulate **and Dream
   consolidates them into `MEMORY.md`** — the derivation is deliberately slower
   than a direct write, trading immediacy for a single system of record. It also
   ramps gradually: `confidence` saturates at 20 preference lines, so early
   history moves `S_user` very little by design.

No migration, no backfill. Existing installs have no preference memory and
resolve to `fallback_mock` until the first thumb is clicked and consolidated. A
transcribed line becomes ranking-visible only once Dream promotes it; between the
click and the next consolidation the preference is pending, not lost.

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

Revisit once real preference memory accumulates. The signal to watch: an
aggregator collecting `do not route` lines while its own single-model turns rate
well suggests the blame is misplaced and proposer-level attribution is worth the
complexity. Transcribing proposer-level preferences into a separate, unscored
memory would make that diagnosable without changing `S_user`.
