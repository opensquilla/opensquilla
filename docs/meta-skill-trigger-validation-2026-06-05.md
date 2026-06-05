# Meta-Skill Trigger Boundary Validation

Date: 2026-06-05

## Scope

This pass validates positive and negative activation boundaries for the stable
bundled MetaSkills:

- `meta-competitive-intel`
- `meta-daily-operator-brief`
- `meta-document-to-decision`
- `meta-job-search-pipeline`
- `meta-kid-project-planner`
- `meta-paper-write`
- `meta-short-drama`
- `meta-skill-creator`
- `meta-web-research-to-report`

The main regression target is that a single-company profile request such as:

```text
inception labs,创始团队和核心员工有哪些？现在估值，核心技术路线和进展是啥？
然后每一轮交割大概节奏和估值股东等信息列出来。
```

must not activate `meta-competitive-intel`.

## Code Changes Persisted

- `src/opensquilla/skills/meta/semantic_guards.py`
  - Added explicit semantic positive/negative cues for
    `meta-job-search-pipeline`.
  - The stable bundled MetaSkill guard matrix now covers all nine stable
    bundled MetaSkills.
- `tests/test_skills_default_prompt_contract.py`
  - Added positive/negative semantic-guard assertions for all nine stable
    bundled MetaSkills.
  - Added filter-level positive/negative assertions for all nine stable bundled
    MetaSkills when a retriever proposes that MetaSkill.

## Deterministic Trigger Matrix

In-memory run against `scripts/meta_trigger_accuracy.py` logic:

```json
{
  "total": 18,
  "passed": 18,
  "failed": 0,
  "accuracy": 1.0,
  "false_positives": 0,
  "false_negatives": 0,
  "wrong_skill": 0
}
```

Coverage: one positive and one neighboring negative prompt for each stable
bundled MetaSkill.

## Unit / Filter Verification

Command:

```sh
uv --cache-dir /tmp/uv-cache run pytest \
  tests/test_skills_default_prompt_contract.py::test_semantic_guards_cover_stable_bundled_meta_skill_boundaries \
  tests/test_skills_default_prompt_contract.py::test_hybrid_filter_applies_stable_meta_boundary_guards_both_directions \
  tests/test_skills_default_prompt_contract.py::test_hybrid_filter_hides_competitive_intel_for_single_company_profile \
  tests/test_skills_default_prompt_contract.py::test_hybrid_filter_hides_neighboring_meta_workflows -q
```

Result:

```text
22 passed in 3.61s
```

Command:

```sh
uv --cache-dir /tmp/uv-cache run pytest \
  tests/test_skills/test_meta_mvp.py::test_meta_resolution_semantic_fallback_blocks_competitive_intel_without_cue -q
```

Result:

```text
1 passed in 0.43s
```

## Live Gateway Verification

Provider: OpenRouter using a local credential supplied through the environment.
The key was not printed.

The temporary gateway was bound to `127.0.0.1` and stopped after each run.

### Baseline Gateway + LLM Smoke

Command:

```sh
OPENSQUILLA_GATEWAY_LLM_E2E=1 \
OPENROUTER_API_KEY=... \
LLM_TEST_MODEL=deepseek/deepseek-v4-flash \
uv --cache-dir /tmp/uv-cache run pytest \
  tests/functional/test_gateway_llm_e2e.py::test_gateway_session_send_reaches_live_llm -q
```

Result:

```text
1 passed in 7.31s
```

### Company Profile Boundary

Default `skills.filter_enabled=false`:

- The full skill prompt still included `meta-competitive-intel`, as expected
  when filtering is off.
- `meta_resolution.matched` did not appear.
- No `meta_invoke` tool call appeared.
- No `session.event.error` appeared.

Manual `skills.filter_enabled=true`:

- The same company-profile prompt produced `filtered_skills=[]`.
- `meta-competitive-intel` was absent from the filtered list.
- `meta_resolution.matched` count: `0`.
- `meta_invoke` count: `0`.
- No `session.event.error` appeared.

### Representative Gateway Routing Matrix

To avoid real side effects from high-cost workflows such as video generation,
LaTeX compilation, file writes, or memory persistence, positive gateway routing
used a temporary validation sentinel that short-circuited the MetaSkill DAG
after the real gateway, real LLM, real skill loader, and real `meta_resolution`
selected `meta_invoke`. The sentinel returned
`VALIDATED_META:<meta-skill-name>`.

Negative cases did not use the sentinel path because they should not call
`meta_invoke` at all.

Representative results:

| Case | Expected | Observed | Result |
| --- | --- | --- | --- |
| competitive positive | `meta-competitive-intel` | `meta_invoke`, `VALIDATED_META:meta-competitive-intel` | pass |
| competitive negative company profile | no MetaSkill | no tools, normal company-research handling text | pass |
| job-search positive | `meta-job-search-pipeline` | `meta_invoke`, `VALIDATED_META:meta-job-search-pipeline` | pass |
| job-search negative generic career advice | no MetaSkill | no tools, normal advice text | pass |
| meta-skill-creator positive | `meta-skill-creator` | `meta_invoke`, `VALIDATED_META:meta-skill-creator` | pass |
| meta-skill-creator negative normal skill | no `meta_invoke` | `skill_view` only, normal standalone-skill clarification | pass |
| web-report positive with topic | `meta-web-research-to-report` | `meta_invoke`, `VALIDATED_META:meta-web-research-to-report` | pass |
| web-report negative brief fact | no MetaSkill | no tools, brief fact answer | pass |

Observed `meta_resolution.matched` examples:

- `meta-competitive-intel`, trigger `盯一下这两个对手`
- `meta-job-search-pipeline`, trigger `tailor my resume`
- `meta-skill-creator`, trigger `create a meta-skill`
- `meta-web-research-to-report`, trigger `cited research report`

One earlier web-report positive prompt,
`Write a cited research report with sources, key findings, and risks.`, was too
underspecified. It did match `meta-web-research-to-report`, but the runtime
asked for a report topic instead of producing the sentinel. The prompt was
corrected to include a topic and then passed.

## Interpretation

- The original Inception Labs company-profile prompt no longer activates
  `meta-competitive-intel` through deterministic trigger matching, semantic
  fallback, filter retrieval, or representative live gateway routing.
- The nine stable bundled MetaSkills still activate on explicit positive
  workflow prompts.
- Adjacent negative prompts are blocked at the semantic guard and filter layer.
- In live gateway routing, representative positive prompts still reach
  `meta_invoke`, while representative negative prompts do not.

## Known Limits

- The live gateway positive matrix validates routing to `meta_invoke`; it does
  not execute full MetaSkill DAGs for high-side-effect workflows.
- Experimental MetaSkills under `src/opensquilla/skills/exp` were not changed
  by this pass and are outside the stable bundled guard matrix.
