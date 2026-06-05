# Meta-Skill Trigger Narrowing Design

Date: 2026-06-05

## Goal

Reduce accidental activation for the stable bundled MetaSkills without deleting
any built-in workflow and without making any stable workflow explicit-only.

The change targets the default stable bundled catalog documented in
`docs/features/meta-skills.md`:

- `meta-competitive-intel`
- `meta-daily-operator-brief`
- `meta-document-to-decision`
- `meta-job-search-pipeline`
- `meta-kid-project-planner`
- `meta-paper-write`
- `meta-short-drama`
- `meta-skill-creator`
- `meta-web-research-to-report`

## Non-Goals

- Do not remove `SKILL.md` files.
- Do not move stable MetaSkills to `src/opensquilla/skills/exp`.
- Do not add `disable_model_invocation` to stable bundled MetaSkills.
- Do not alter `composition.steps`, step prompts, tool calls, risk metadata, or
  runtime orchestration behavior.
- Do not change experimental MetaSkills under `src/opensquilla/skills/exp`.

## Current Activation Model

MetaSkill activation is handled by
`src/opensquilla/engine/steps/meta_resolution.py`.

The relevant behavior:

- Deterministic trigger matches scan loaded skills with `kind: meta`.
- ASCII triggers use normalized word-boundary matching.
- CJK triggers use substring matching because word boundaries are unreliable.
- Deterministic matches set `meta_match_tool_choice` so the first tool call is
  forced to `meta_invoke`.
- Semantic matches are advisory only, but can still bias the model toward a
  MetaSkill.
- Sticky continuation can replay the last chosen MetaSkill for up to 30 minutes
  and three follow-up turns unless cancelled or superseded.
- Long pasted context is narrowed to the leading user intent before trigger
  scanning.

This means trigger precision matters most. A too-broad trigger is not merely a
hint; on deterministic activation it can force the turn toward `meta_invoke`.

## Design Principle

Every trigger should express both:

1. the domain, and
2. an end-to-end deliverable or workflow intent.

Weak trigger shape:

```text
decision memo
today plan
school project
写一份报告
```

Better trigger shape:

```text
source-backed decision memo
daily operating brief
plan my child's school project
查资料并写带来源的报告
```

CJK triggers should be especially specific because the runtime currently uses
substring matching for non-ASCII triggers.

## Catalog Decisions

All nine stable bundled MetaSkills remain model-invokable. The design changes
only their trigger and description boundaries.

### `meta-web-research-to-report`

Risk of accidental activation: high.

Reason: several triggers describe generic writing or common business language:
`research report`, `decision memo`, `write up the findings`, `写一份报告`,
`查一下并写`.

Keep automatic activation for requests that clearly ask for source-backed web
research, cited findings, current-source lookup, or a report/brief after search.

Narrowing:

- Replace generic English triggers with source-backed variants.
- Replace generic Chinese triggers with triggers that mention lookup, sources,
  citations, or web research.
- Keep specific examples such as travel eSIM and carrier/local-SIM reports.
- Description should say not to use for quick fact lookup, normal writing,
  document-decision analysis, academic manuscripts, or ordinary summarization.

Negative tests:

- "Write a decision memo from these notes, no web research."
- "Explain what a research report meta-skill does."
- "Can you summarize this paragraph and write up the findings?"
- "帮我写一份报告，不需要查资料。"

### `meta-daily-operator-brief`

Risk of accidental activation: high.

Reason: triggers like `today plan` and `今天安排` can appear in ordinary schedule
or reminder requests.

Keep automatic activation for practical operating briefs that combine priorities,
calendar/task context, memory, weather, or open-loop review.

Narrowing:

- Replace `today plan` with `daily operating brief` or `today operating plan`.
- Replace `今天安排` with phrases that imply priority planning or full-day
  operating brief, such as `今天优先级和时间块`.
- Keep `daily brief`, `morning brief`, and specific priority/time-block triggers.
- Description should say not to use for setting one reminder, moving one meeting,
  answering whether the user is free, or generic productivity advice.

Negative tests:

- "What is my plan today?" when no pasted context or operating-brief request is
  present.
- "Remind me today to call Alex."
- "今天安排一个提醒。"
- "Can you give generic advice on planning my day?"

### `meta-document-to-decision`

Risk of accidental activation: medium.

Reason: most triggers are decision-oriented, but `contract excerpt` and
`读完告诉我怎么做` can be broad.

Keep automatic activation for document-backed decisions: sign, reject,
negotiate, renew, ask vendor questions, evidence table, or concrete next action
from document materials.

Narrowing:

- Replace `contract excerpt` with `analyze this contract excerpt for a decision`.
- Replace `读完告诉我怎么做` with `读完这份合同告诉我签不签` or similarly
  document-specific variants.
- Keep vendor renewal, quote analysis, contract risk, and sign/negotiate
  triggers.
- Description should keep the "document text quoted as historical context"
  exclusion.

Negative tests:

- "Explain this contract term generally."
- "Summarize this document."
- "Here is an old quote from a previous chat; do not analyze it."

### `meta-job-search-pipeline`

Risk of accidental activation: low to medium.

Reason: most triggers are specific, but `求职准备` and `career application` can
catch generic career advice.

Keep automatic activation for concrete job-search workflows with a JD, resume,
named interview, application tracker, role comparison, or target company.

Narrowing:

- Replace `求职准备` with `针对这个岗位做求职准备`.
- Replace `career application` with `job application pack`.
- Keep resume tailoring, JD-based resume edits, interview prep for a named
  target, and application tracker triggers.
- Description should continue excluding generic career advice and generic resume
  comments without a target role/JD.

Negative tests:

- "Give me career advice."
- "How do I write a better resume in general?"
- "What does career application mean?"

### `meta-kid-project-planner`

Risk of accidental activation: medium.

Reason: `school project` and `做一个手工` are broad and can apply to adult,
generic, or non-child creative requests.

Keep automatic activation for child/guardian school projects, science fair
entries, kid-safe DIY, and parent-supervised educational plans.

Narrowing:

- Replace `school project` with `plan my child's school project`.
- Replace `做一个手工` with `孩子做一个安全手工项目`.
- Keep `science fair`, `kid science`, child DIY, and Chinese child/school
  phrases.
- Description should say not to use for adult craft projects, generic art
  prompts, or unsafe build requests.

Negative tests:

- "I have a school project about databases" from an adult context.
- "帮我做一个手工 logo."
- "Explain the science fair format."

### `meta-paper-write`

Risk of accidental activation: medium.

Reason: academic triggers are fairly specific, but the workflow is high-risk and
depends on local LaTeX tools. It should still auto-trigger only for paper
production, not generic writing about papers.

Keep automatic activation for drafting, repairing, compiling, or producing an
academic/research paper or LaTeX manuscript.

Narrowing:

- Keep `draft a paper`, `write a research paper`, `academic manuscript`,
  `research manuscript`, `latex manuscript`, `写篇论文`, and `撰写论文`.
- Remove or replace `long-form paper` with `long-form research paper`.
- Description should explicitly exclude blog posts, reports, literature-review
  questions that do not ask for a manuscript, slide decks, and generic plotting.

Negative tests:

- "What is a research paper?"
- "Summarize this paper."
- "Write a blog post about research."
- "Find papers about RAG, do not draft a manuscript."

### `meta-short-drama`

Risk of accidental activation: low to medium.

Reason: triggers are mostly specific, but the workflow is high-cost and has
media side effects. Natural triggers should require final video or
shot-to-video intent, not isolated script writing.

Keep automatic activation for AI short-drama generation, shot-list-to-video
workflows, or topic-to-final-MP4 requests.

Narrowing:

- Keep Chinese short-drama and shot-to-video phrases.
- Keep English triggers that include short drama generation or final MP4.
- Avoid adding generic script-writing, storyboard, or video idea triggers.
- Description should continue excluding slide decks, single-image generation,
  isolated script writing, and historical examples.

Negative tests:

- "Write a short script."
- "Give me a storyboard idea."
- "Explain how the short-drama meta-skill works."

### `meta-skill-creator`

Risk of accidental activation: medium.

Reason: it is a meta-workflow that creates new workflow proposals. It already
has collision tests for generic skill creation, but triggers like
`orchestrates search` may be too broad.

Keep automatic activation only when the user explicitly asks to create,
compose, synthesize, or propose a new MetaSkill that orchestrates existing
skills.

Narrowing:

- Remove `orchestrates search` unless paired with explicit meta-skill creation.
- Keep `create a meta-skill`, `new meta-skill`, `compose meta-skill`,
  `synthesize meta-skill`, and Chinese meta-skill creation phrases.
- Description should keep exclusions for normal standalone skill creation,
  explaining meta-skills, pasted skill lists, and discussing existing
  MetaSkills.

Negative tests:

- "Create a normal skill."
- "Explain how meta-skills work."
- "This old workflow orchestrates search and summarize; analyze it."
- "Search for skills in the marketplace."

### `meta-competitive-intel`

Risk of accidental activation: low.

Reason: triggers are domain-specific and mostly require competitors, accounts,
or monitoring. Some CJK phrases are colloquial but still competitive-intel
specific.

Keep automatic activation for named company, account, competitor, prospect, or
partner monitoring with a time window or business-intel deliverable.

Narrowing:

- Keep most triggers.
- Replace `watch this account` with `watch this account for competitive intel`
  to avoid generic account support monitoring.
- Replace `track these companies` with `track these companies for competitive
  intel`.
- Description should continue excluding generic company research and product
  comparison without named target companies.

Negative tests:

- "Watch this account login issue."
- "Track these companies in my CRM without research."
- "Compare two products but no named competitors."

## Test Strategy

Use the existing deterministic harness:

- `tests/test_skills/test_high_value_meta_trigger_coverage.py`
- `tests/test_skills/test_creator_trigger_no_collision.py`
- `tests/test_skills/test_meta_trigger_accuracy_harness.py`

Add or update trigger cases for:

- Positive natural prompts for each retained MetaSkill.
- Negative neighboring-domain prompts for each risky trigger.
- MetaSkill explanation questions.
- Generic skill creation prompts that must not select `meta-skill-creator`.
- Long pasted context that includes old trigger phrases but has a different
  leading current intent.

Expected verification:

```sh
pytest tests/test_skills/test_high_value_meta_trigger_coverage.py \
  tests/test_skills/test_creator_trigger_no_collision.py \
  tests/test_skills/test_meta_trigger_accuracy_harness.py -q
```

If frontmatter edits affect broader parser or loader contracts, also run:

```sh
pytest tests/test_skills/test_meta_skill_linter.py \
  tests/test_ci/test_meta_skill_lint.py -q
```

## Acceptance Criteria

- All nine stable bundled MetaSkills remain installed and model-invokable.
- No stable bundled MetaSkill is physically removed.
- No stable bundled MetaSkill is changed to explicit-only.
- Trigger lists avoid generic writing, planning, search, schedule, or
  explanation phrases.
- Existing positive high-value trigger cases still pass after updating expected
  wording where necessary.
- New negative cases prove that common neighboring prompts do not produce a
  deterministic MetaSkill match.
- Runtime behavior for matched MetaSkills is unchanged because `composition`
  remains untouched.
