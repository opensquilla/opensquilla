# Meta Skill Validation Report - 2026-05-31

## Scope

This report records the meta skill validation performed on the `dev` branch.

The validation covered:

- Meta skill parser, trigger matching, soft activation, and `meta_invoke`.
- Meta orchestrator step execution for `llm_chat`, `llm_classify`,
  `skill_exec`, `agent`, and `user_input`.
- Pause/form rendering and user input collection behavior.
- End-to-end gateway runs through a real LLM provider.
- `meta-skill-creator` activation from dialogue, cron auto-propose, and dream
  post-hook paths.
- Chinese and English language behavior, including the requirement that English
  responses must not contain Chinese text.
- Fixture and validation-matrix material setup.

## Environment

Dependencies verified as importable:

| Package | Version |
| --- | --- |
| `numpy` | `2.4.6` |
| `joblib` | `1.5.3` |
| `scikit-learn` | `1.8.0` |
| `lightgbm` | `4.6.0` |
| `onnxruntime` | `1.26.0` |
| `tokenizers` | `0.23.1` |

Temporary validation gateway:

- URL: `ws://127.0.0.1:18793/ws`
- Config: temporary validation config.
- Auth mode: `none`
- Provider: OpenRouter
- Configured default model: `deepseek/deepseek-v4-pro`
- Observed routed model in live runs: `deepseek/deepseek-v4-flash-20260423`
- Router evidence:
  - `gateway.squilla_router_preloaded`
  - `squilla_router.routed ... source=v4_phase3`
  - `meta_resolution.matched`
  - `meta_orchestrator.step_started`
  - `meta_orchestrator.step_finished`

The temporary `18793` gateway was stopped after validation. Existing public
gateways on `8081` and `18792` were not modified by this validation pass.

## Local Tests

Targeted and aggregate tests run during the pass:

| Command / Test Group | Result |
| --- | --- |
| `pytest tests/test_skills/test_meta_mvp.py` | `88 passed` |
| Lifestyle + meta MVP + validation matrix + paused finalizer | `137 passed` |
| `pytest tests/test_skills/test_meta_user_input_executor.py tests/test_engine/turn_runner/test_turn_finalizer_paused.py -q` | `9 passed` |
| Final aggregate: lifestyle comparison, meta MVP, validation matrix, paused finalizer, user input executor, meta invoke tool | `161 passed in 3.87s` |
| Creator activation coverage: gateway boot wiring, cron handler, dream handler, auto-propose, creator E2E | `47 passed in 4.60s` |
| Regression set for remaining live failures: agent final text, migration assistant, code review, runtime E2E, creator E2E | `23 passed in 4.41s` |
| Runtime E2E prompt regression set | `8 passed in 0.79s` |
| `ruff check` on changed files and new validation script/tests | `All checks passed` |
| `git diff --check` | passed |

The final aggregate command was:

```bash
uv run pytest \
  tests/test_meta_skill_openclaw_lifestyle_comparison.py \
  tests/test_skills/test_meta_mvp.py \
  tests/test_scripts/test_meta_skill_validation_matrix.py \
  tests/test_engine/turn_runner/test_turn_finalizer_paused.py \
  tests/test_skills/test_meta_user_input_executor.py \
  tests/test_skills/test_meta_invoke_tool.py -q
```

The creator activation coverage command was:

```bash
uv run pytest \
  tests/test_gateway/test_router_boot.py::test_start_gateway_server_wires_meta_skill_auto_propose_routes \
  tests/test_scheduler/test_auto_propose_handler.py \
  tests/test_scheduler/test_dream_handler.py \
  tests/test_skills/test_creator_auto_propose.py \
  tests/test_skills/test_meta_skill_creator_e2e.py -q
```

## Live Gateway + LLM Runs

The following cases were run through the gateway WebSocket path with a real LLM
provider, not only by unit tests.

| Case | Skill | Result | Notes |
| --- | --- | --- | --- |
| Chinese document vendor decision | `meta-document-to-decision` | Passed | Chinese output allowed. |
| English document vendor decision | `meta-document-to-decision` | Passed | `contains_cjk=false`. |
| Chinese kid balcony plants | `meta-kid-project-planner` | Passed | Chinese output allowed. |
| English daily operator | `meta-daily-operator-brief` | Passed | Score `6/6`, `contains_cjk=false`. |
| `C2_meta_skill_creator_preview_en` | `meta-skill-creator` | Passed | `ok=true`, `contains_cjk=false`. |
| `B1_web_research_clarify_en_after_force` | `meta-web-research-to-report` | Passed after fix | `ok=true`, routed model `deepseek/deepseek-v4-flash-20260423`, `contains_cjk=false`. |
| `B6_kid_project_safe_en` | `meta-kid-project-planner` | Passed | `ok=true`, routed model `deepseek/deepseek-v4-flash-20260423`, `contains_cjk=false`. |

### Meta Skill Creator Activation Surfaces

Seeded history was created before cron and dream validation. Each isolated run
wrote a `decisions-20260531.jsonl` file under its own temporary
`OPENSQUILLA_LOG_DIR` with these co-occurrence rows:

- `history-explorer` + `summarize`: 7 occurrences.
- `multi-search-engine` + `summarize`: 4 occurrences.
- `weather` + `summarize`: 2 occurrences.

Verified creator surfaces:

| Surface | Result | Evidence |
| --- | --- | --- |
| Direct creator pipeline | Passed | `scripts/live_meta_skill_creator_e2e.py` produced proposal `c4897d75`, passed lint/smoke, and auto-enabled low-risk `history-digest` in an isolated home. |
| Dialogue through `/api/chat` | Passed after fix | Explicit user-specified `PREVIEW_ONLY` request for `release-readiness-brief` matched `meta-skill-creator`, ran on t3 (`final_tier=t3`, `thinking_mode=T3`, model `deepseek/deepseek-v4-flash-20260423`), skipped `harvest` because the request was not cron/dream/auto-propose, produced a proposal preview, and skipped `persist`. Local evidence retained outside the repository. |
| Actual cron scheduler | Passed | Gateway boot registered `auto_propose:main`; the real scheduler naturally fired, completed one run, and generated proposal `8b21e930`. Local evidence retained outside the repository; scheduler summary `auto_propose proposals=1 enabled=0 skipped=0 errors=0 via=cron`, `delivery_status=delivered`, `success=true`. |
| Cron handler | Passed | `scripts/live_meta_skill_creator_auto_propose_e2e.py --trigger cron --via-handler --seed-history` completed with `delivery_status=delivered`, `auto_propose proposals=2 enabled=0 skipped=0 errors=0 via=cron`, proposal ids `592c5d49` and `6a791662`, and `gates.json` provenance `triggered_by=auto_cron`. |
| Actual dream scheduler + post-hook | Passed | `memory_dream:main` ran successfully, `auto_propose.dream_hook.complete` logged `auto_propose proposals=1 enabled=0 skipped=0 errors=0 via=dream`, proposal id `7eb40363`, and `gates.json` provenance `triggered_by=auto_dream` with `source_context` from the dream summary. |

The cron and dream proposals were intentionally not auto-enabled because the
gates were conservative: lint and smoke passed, but acceptance/runtime E2E or
collision gates marked the generated candidates below the auto-enable bar.
The cron/dream auto-propose orchestrator uses the configured t3 tier for judge
and runtime comparison calls: gateway boot clones the provider selector,
overrides it to `squilla_router.tiers.t3.model`, records `routed_tier=t3`, and
passes that same model as `baseline_model` to runtime E2E.

### Remaining Three-Case Recheck

After the first report, three previously open areas were re-run through
temporary live gateways with the OpenRouter model
`deepseek/deepseek-v4-flash-20260423`.

| Area | Result | Evidence |
| --- | --- | --- |
| `B3` attachment/material upload for `meta-migration-assistant` | Passed after fix | Inline attachments using `application/json`, `text/plain`, and `text/markdown` were accepted with no real `HTTP 415`. The request matched `meta-migration-assistant`, `migration_intake` ran, clarification continuation was accepted, `classify` returned `CJS_TO_ESM`, and `fetch_guide` ran as `skill_exec` through `multi-search-engine` and returned guide content. Local evidence retained outside the repository. |
| `C1` dirty-repo code review material for `meta-codereview-current-diff` | Passed after fix | The dirty repo fixture was initialized, the corrected patch applied, attachments were accepted with no real `HTTP 415`, and the request matched `meta-codereview-current-diff`. `git-diff` returned the expected diff; `review_safety`, `review_tests`, and `review_style` ran as `llm_chat`; final arbitration blocked the redacted placeholder credential. Local evidence retained outside the repository. |
| Dialogue `/api/chat` `FULL_GATED` creator request | Runtime path passed after fix; auto-enable correctly remained blocked | The dialogue request matched `meta-skill-creator`, routed to t3 (`final_tier=t3`, `thinking_mode=T3`), skipped `harvest` because this was not unattended history observation, classified `creator_mode=FULL_GATED`, assembled `release-readiness-brief`, ran collision, lint, risk, smoke, acceptance comparison, runtime E2E, preview, and persist. Runtime E2E now used the candidate trigger prompt `please use release readiness brief`, ran the candidate `git-diff -> summarize -> summarize` chain, and returned `passed=true`, `winner=meta`. The proposal was persisted as a redacted local test proposal; `auto_enable_eligible=false` because `acceptance_compare` judged the candidate definition below the quality bar. Local evidence retained outside the repository. |

This recheck changes the prior MIME conclusion: the original attachment gap is
not still reproduced when the upload uses accepted MIME types. The execution
defects found in the first recheck were fixed by routing deterministic helper
steps through `skill_exec`/`llm_chat`, preserving `DoneEvent.text` from
agent-kind steps, creating a scratch git repository for creator runtime E2E, and
using candidate trigger prompts for runtime E2E rather than the outer creator
request.

The B1 English clarification case originally exposed two runtime issues:

- The model could emit malformed `meta_invoke` arguments after deterministic
  meta matching.
- In another run, the model bypassed the matched meta skill and answered
  directly in Chinese.

Both behaviors are now covered by regression tests and guarded in the dispatch
path.

## Functional Areas Verified

### Meta Skill Parser and Activation

Verified:

- Meta skill parsing from `SKILL.md` frontmatter and composition.
- Step DAG construction.
- Cycle rejection.
- Duplicate step id rejection.
- Undefined dependency rejection.
- Trigger matching and soft activation hint injection.
- Deterministic trigger match forcing `meta_invoke` as the first tool choice.
- `skill_view` calls for meta skills are coerced into `meta_invoke`.
- Malformed `meta_invoke` arguments can be repaired from the deterministic
  `meta_match`.
- If a deterministic meta match exists and the model calls an ordinary tool
  first, the first call is rewritten to `meta_invoke`.
- `meta-skill-creator` can be entered by explicit dialogue trigger phrases,
  cron auto-propose, and dream post-hook auto-propose.

### Orchestrator and Step Execution

Verified:

- `llm_chat` step prompt rendering and execution.
- `llm_classify` step prompt rendering and execution.
- `skill_exec` execution path.
- `agent` step execution path.
- `user_input` pause behavior.
- Step skip behavior.
- Failover behavior.
- Final text modes including raw, step-selected, and summary/repair paths.

### User Input and Pause Rendering

Verified:

- `MetaPaused` carries language metadata.
- English pause rendering uses English labels and English field prompts.
- Chinese cancel keywords are removed from English pause output.
- Required, optional, and default field display.
- DAO awaiting claim behavior.
- Current environment hang with `asyncio.to_thread(...)` in the user-input
  claim path was avoided by using the synchronous DAO call directly.

### Language Behavior

Verified:

- Plain English user messages are detected as English.
- Chinese user messages are detected as Chinese.
- Language instructions are injected into meta step prompts.
- `agent` and `llm_classify` executors receive the language rule.
- English final text gets a last-mile repair pass if CJK leaks.
- English `user_input` pause text is English-only.
- English daily operator template no longer emits bilingual headings.
- English kid planner and web research clarify live runs return no CJK text.

### Safety

Verified:

- Safe kid project planning works for a balcony herb garden science project.
- Unsafe kid project requests preserve refusal/safe-alternative behavior.
- `meta-kid-project-planner` unsafe redirect behavior is covered by regression
  tests.

### Fixture and Matrix Material

Added and verified fixture material for the validation matrix, including:

- `tests/fixtures/meta_skill_inputs/meta_validation_cases.json`
- `tests/fixtures/meta_skill_inputs/kid_project/`
- `tests/fixtures/meta_skill_inputs/code_review_dirty_repo/`
- `tests/fixtures/meta_skill_inputs/auto_propose/`
- `scripts/meta_skill_validation_matrix.py`
- `tests/test_scripts/test_meta_skill_validation_matrix.py`

The matrix script validates declared fixture materials and supports judging a
captured E2E bundle with a strict JSON rubric.

## Fixes Driven by Validation

The validation pass led to these fixes:

- Added shared meta input language detection and language instructions.
- Propagated language rules into meta step prompts and executor prompts.
- Localized English pause/form rendering.
- Removed Chinese cancel keywords from English pause output.
- Added final English repair for CJK leakage.
- Adjusted daily operator template to produce English-only headings and labels
  for English requests.
- Preserved unsafe kid planner refusal/safe alternative behavior.
- Stabilized `skill_exec` subprocess execution in the current test environment.
- Stabilized user input DAO claim behavior in the current test environment.
- Hardened `meta_invoke` dispatch against malformed model arguments and
  ordinary-tool bypass after deterministic meta matching.
- Converted `meta-skill-creator`'s dialogue intent, collision, risk, and
  preview reasoning steps to no-tool `llm_chat` so explicit user-specified
  creator requests do not fail on sub-agent workspace probing.
- Gated `meta-skill-creator` history harvest to unattended cron/dream
  auto-propose context; direct dialogue creation now relies on the user's
  explicit request instead of observing prior history.
- Converted generated `summarize` steps to `llm_chat` and made `llm_chat`
  include rendered upstream context arguments, so generated synthesis steps see
  prior DAG outputs without spawning a tool-capable sub-agent.
- Routed `meta-migration-assistant` guide lookup through `multi-search-engine`
  as direct `skill_exec`, avoiding empty sub-agent final text.
- Converted `meta-codereview-current-diff` reviewer/arbitration steps to
  `llm_chat` and selected final text from the arbitration step.
- Preserved `DoneEvent.text` in the generic agent executor when no
  `TextDeltaEvent` is emitted.
- Gave creator runtime E2E a scratch git workspace when the caller workspace is
  not a git repository, and changed the gate to evaluate candidate-trigger
  prompts instead of the outer creator request.

## Known Gaps

No blocking meta-skill functional gap remains from the validated matrix. The
dialogue `FULL_GATED` path can still legitimately persist a proposal with
`auto_enable_eligible=false` when `acceptance_compare` judges the generated
candidate below the quality bar; that is the intended conservative gate behavior,
not an activation or runtime failure.

Additional residual observation:

- The kid planner `store_project` memory step can perform extra probing and add
  runtime cost/noise. It did not block the final user-facing result.

## Conclusion

Meta skill core behavior is verified for parser, activation, orchestration,
pause handling, LLM-backed live execution, router-backed gateway execution, and
Chinese/English language control.

`meta-skill-creator` is verified for direct creator execution, actual cron
auto-propose, cron handler auto-propose, and dream post-hook auto-propose with
seeded user history and real LLM calls. Dialogue activation is verified for a
user-specified `PREVIEW_ONLY` request without history observation and for a
user-specified `FULL_GATED` request: both route to `meta-skill-creator`, use t3,
and skip history harvest. The `FULL_GATED` run executes candidate runtime E2E
end to end and persists the proposal while leaving auto-enable disabled when the
quality gate fails.

English meta skill outputs are now verified not to mix Chinese in the covered
live gateway cases. The previous MIME/upload, empty sub-agent final text, and
creator dialogue `FULL_GATED` runtime E2E defects are fixed and covered by
targeted regression tests plus live gateway evidence.
