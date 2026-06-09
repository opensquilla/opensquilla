# OpenSquilla MetaSkill User Guide

MetaSkill lets OpenSquilla move from figuring out complex work from scratch on
every turn to reusable, triggerable, auditable, and improvable task protocols.

A normal conversation solves one request. A MetaSkill preserves a way of doing
high-value work.

## Important Notice

Some MetaSkills in OpenSquilla, and some of the skills they call, are authored,
revised, or composed with AI assistance based on intended functionality,
available capabilities, and usage scenarios.

This means:

- MetaSkills are not merely a collection of fully hand-written scripts. They are
  part of a system where AI can help formalize and evolve reusable task
  protocols.
- AI-authored or AI-assisted MetaSkills should be reviewed through structural
  validation, trigger-surface checks, runtime testing, human review, and
  safety-boundary assessment before they are treated as ready for use.
- MetaSkill outputs are decision-support materials and work-product drafts. They
  are not final professional advice in legal, medical, financial, hiring,
  academic, security, or other high-stakes contexts.
- Actions such as publishing, applying, installing, paying, signing, messaging,
  or modifying production systems require explicit user authorization and remain
  the user's responsibility.
- When a MetaSkill relies on search, document parsing, LLM judgment, or
  third-party tools, the result may be affected by source quality, model
  limitations, tool availability, context completeness, and time-sensitive
  changes.
- Users should review facts, citations, assumptions, risks, and unverifiable
  claims, especially in high-stakes situations.

In short: MetaSkill turns high-value work into reusable, auditable, and
improvable AI collaboration protocols. It does not remove the need for review,
judgment, or accountability.

## What It Is

OpenSquilla is an open-source AI agent runtime. MetaSkill is its task-protocol
layer.

A MetaSkill does not introduce new execution atoms. It defines a way to organize
existing atoms, such as skills, tools, LLM calls, and sub-agents, into a
reusable task protocol.

The analogy is a Makefile and shell commands. A Makefile does not replace
commands; it defines how commands are composed. A MetaSkill does not replace
skills or tools; it tells OpenSquilla how a class of high-value work should be
understood, structured, checked, and delivered.

MetaSkill provides four main advantages:

- protocolized capability captured in a `SKILL.md` file with `kind: meta` and
  `composition.steps`;
- triggerable by user intent in natural language;
- auditable and replayable step inputs, outputs, status, and results;
- improvable over time as repeated collaboration patterns become proposals.

## User Mental Model

Using a MetaSkill is not just asking a question. It is delegating OpenSquilla to
produce a reviewable result.

A strong MetaSkill request contains four things:

1. Outcome: what you want to receive.
2. Context: materials, entities, time range, and constraints that matter.
3. Standard: what "good" means for this task.
4. Boundaries: what must not happen, what must not be invented, and what requires
   confirmation.

Example:

```text
Use meta-skill `meta-document-to-decision`.

I need a decision memo, not a generic explanation.
Use only the contract terms I pasted unless you can cite sources.
Separate facts, assumptions, risks, and next actions.
Do not invent missing dates, and do not sign or send anything for me.
```

The user defines the target and standard; OpenSquilla organizes the execution.

## Current Built-In MetaSkills

The retained built-in MetaSkills cover a focused set of high-value task classes.

| MetaSkill | Positioning |
| --- | --- |
| `meta-competitive-intel` | Turns account or competitor signals into sales, BD, or competitive-intel briefs. |
| `meta-daily-operator-brief` | Turns today/tomorrow tasks, context, and constraints into an operating brief. |
| `meta-document-to-decision` | Turns contracts, quotes, renewals, notices, or spreadsheets into sign, reject, or negotiate decisions. |
| `meta-job-search-pipeline` | Turns a JD, resume, and application goal into an application package and interview prep. |
| `meta-kid-project-planner` | Produces safe, age-appropriate plans for school projects, show-and-tell, or science activities. |
| `meta-paper-write` | Supports academic drafts, manuscript structure, citation planning, experiment placeholders, and LaTeX/PDF paths. |
| `meta-short-drama` | Produces short-drama scripts, visual prompts, video assembly plans, subtitles, and rendered local video artifacts. |
| `meta-skill-creator` | Turns repeated multi-skill collaboration patterns into new MetaSkill proposals. |
| `meta-web-research-to-report` | Turns source-backed research needs into reports, briefs, or decision memos. |

These are designed around quality over quantity. Immature, duplicate, or
single-skill wrapper MetaSkills should not remain in the bundled catalog.

## Requirements Before Running MetaSkills

The Skill page is the source of truth for current readiness. Open the skill
detail dialog and check the **Requirements** section before running workflows
that export files, compile PDFs, or render video.

Common setup surfaces:

- Paper/PDF workflows such as `meta-paper-write` require `xelatex` and
  `bibtex` on `PATH`. Install a TeX distribution such as TeX Live, MiKTeX, or
  BasicTeX before requesting compiled PDFs.
- Video workflows such as `meta-short-drama` require `ffmpeg` and `ffprobe` on
  `PATH` for clip animation, merging, and subtitle burn-in.
- Office-document workflows roll up requirements from child skills such as
  `docx`, `xlsx`, `pdf-toolkit`, and `pptx`; these usually surface Python
  package requirements in the Skill page.
- Search, weather, image, and video-provider steps may require configured API
  keys or provider credentials. The workflow should treat missing credentials as
  setup blockers rather than silently degrading output.

## Two Ways to Use MetaSkill

### Natural Delegation

Describe the outcome directly:

```text
Research whether my parents should use a travel eSIM, carrier roaming, or a
local SIM for an 8-day Japan trip, and produce a source-backed decision memo.
```

OpenSquilla selects the appropriate MetaSkill based on current intent. This is
best for ordinary usage when the user does not want to remember names. If the
request is broad or close to another task category, explicit delegation is more
stable.

### Explicit Delegation

Name the capability:

```text
Use meta-skill `meta-web-research-to-report`.

Research whether my parents should use a travel eSIM, carrier roaming, or a
local SIM for an 8-day Japan trip, and produce a source-backed decision memo.
```

This is best for important, expensive, or easily confused tasks.

## Low-Cost, High-Quality Request Template

Recommended template:

```text
Use meta-skill `<name>`.

Outcome:
Context:
Decision standard:
Expected output:
Constraints:
Do not:
```

Example:

```text
Use meta-skill `meta-document-to-decision`.

Outcome: decide whether to sign, reject, or negotiate this vendor renewal.
Context: annual fee RMB 18,600; payment due June 3; auto-renewal unless
cancelled 30 days before renewal; 30% penalty after the notice window.
Decision standard: include an evidence table, risks, vendor questions, and next
24-hour actions.
Expected output: a decision memo I can forward to my manager.
Constraints: use only the terms I provided; do not invent missing dates.
Do not: sign, send, or commit payment for me.
```

Useful constraints:

- Do not invent missing facts.
- Separate facts, assumptions, and recommendations.
- Use only pasted material unless sources are available.
- Do not submit, publish, install, pay, send, or sign automatically.
- Ask me if a decision depends on missing information.

## Built-In MetaSkill Usage Patterns

### `meta-web-research-to-report`

Use for source-backed research deliverables.

Good fit:

- decision memo with sources;
- market or technical brief;
- option comparison;
- search-backed recommendation.

Poor fit:

- one-off fact lookup;
- generic advice;
- academic paper writing;
- simple translation or summarization.

High-quality request:

```text
Use meta-skill `meta-web-research-to-report`.

Research whether my parents should use a travel eSIM, carrier roaming, or a
local SIM for an 8-day Japan trip. They mainly need messaging, maps,
translation, and occasional video calls. They are not comfortable changing phone
settings.

Give me:
- key findings with sources
- option comparison
- risks
- recommendation
- what I should order tonight
```

Expected result: key findings, sources or source limits, option comparison,
risks, recommendation, and next action.

### `meta-document-to-decision`

Use when documents must become a decision, not merely a summary.

Good fit:

- vendor renewal;
- contract excerpt;
- quote;
- payment or cancellation-window risk;
- sign, reject, or negotiate decision.

High-quality request:

```text
Use meta-skill `meta-document-to-decision`.

I need to decide tomorrow whether to sign this vendor renewal. Key terms:
annual fee RMB 18,600, payment due June 3, auto-renewal unless cancelled 30 days
before renewal, and a 30% penalty after the notice window.

Give me:
- sign, reject, or negotiate recommendation
- evidence table
- risks
- vendor questions
- next 24-hour actions

Do not invent missing dates.
```

Expected result: decision-support material, not a plain document recap.

### `meta-competitive-intel`

Use for account or competitor monitoring, not generic company research.

Good fit:

- competitor monitoring;
- account signal tracking;
- baseline comparison;
- sales, BD, or competitive-intel follow-up.

High-quality request:

```text
Use meta-skill `meta-competitive-intel`.

Monitor ByteDance and Xiaohongshu for the last 30 days. Compare product,
pricing, hiring, partnerships, leadership, funding, and news signals against
this baseline: last month ByteDance had no visible pricing change and
Xiaohongshu was hiring for merchant tooling.

Give me:
- signal table
- changes against baseline
- source limits
- high, medium, or low urgency
- who I should follow up with today
```

Expected result: account- and dimension-structured output, not a generic company
profile.

### `meta-daily-operator-brief`

Use when a day needs to become an actionable operating brief.

Good fit:

- morning brief;
- today/tomorrow plan;
- task priority;
- time blocks;
- follow-up list;
- weather or commute caveats.

High-quality request:

```text
Use meta-skill `meta-daily-operator-brief`.

Build my morning brief for today. I have a customer demo at 15:00, finance needs
my reimbursement answer before 11:30, HR asked about interview timing, and my
boss asked me yesterday to finish the router evaluation sheet. I am in Shanghai.

Give me:
- top three priorities
- time blocks
- risks
- follow-ups
- weather or commute caveats
- assumptions
```

Expected result: an operating brief, not generic productivity advice.

### `meta-job-search-pipeline`

Use when job-search material needs to become application-ready.

Good fit:

- tailoring a resume to a JD;
- cover note;
- interview prep;
- role-fit analysis;
- application tracker review.

High-quality request:

```text
Use meta-skill `meta-job-search-pipeline`.

Tailor my resume to this Product Operations Manager role. The JD focuses on
merchant tooling, KPI dashboards, launch coordination, and cross-functional
execution. My resume includes internal operations dashboards, beta launches, and
sales/support collaboration.

Give me:
- rewritten resume bullets
- cover note
- interview prep
- gaps I should explain

Do not auto-apply.
```

Expected result: application preparation, with no claim that the application was
submitted.

### `meta-kid-project-planner`

Use for child school projects, show-and-tell, science demos, and safe creative
activities.

Good fit:

- science fair;
- show-and-tell;
- classroom demonstration;
- child-safe craft or experiment;
- low-burden parent preparation.

High-quality request:

```text
Use meta-skill `meta-kid-project-planner`.

Help my child prepare a second-grade science fair project about plant growth. We
have beans, paper cups, cotton, water, and a sunny windowsill.

Keep it safe and simple.

Give me:
- materials list
- 3-day plan
- what the child should observe
- short presentation script
- what remains unknown
```

Expected result: safe, age-appropriate, source-strict output. It should not
invent weather, school requirements, or child preferences.

### `meta-paper-write`

Use for academic papers, research manuscripts, and LaTeX-oriented deliverables.

Good fit:

- compact paper skeleton;
- section structure;
- citation plan;
- experiment and figure/table placeholders;
- LaTeX/PDF path when explicitly requested.

PDF compilation requires `xelatex` and `bibtex` on `PATH`. If those binaries are
missing, use the LaTeX source output or install TeX Live, MiKTeX, or BasicTeX
before asking for a compiled PDF.

High-quality request:

```text
Use meta-skill `meta-paper-write`.

Draft a compact research paper skeleton on retrieval-augmented generation for
customer-support knowledge bases.

Include:
- title
- abstract
- related work plan
- method outline
- experiment placeholders
- figure/table placeholders
- citation plan

Keep it compact first. Do not write a full manuscript unless I ask.
```

Expected result: a paper-shaped deliverable, not a generic essay. Citations
should not be presented as verified sources unless actually verified.

### `meta-skill-creator`

Use to create a new MetaSkill proposal.

Good fit:

- turning repeated multi-skill collaboration into a reusable capability;
- defining trigger surfaces;
- composing existing skills;
- adding validation and risk checks;
- producing a proposal for review.

Poor fit:

- creating a normal single-purpose skill;
- analyzing existing skill lists without creating anything;
- asking what MetaSkill is;
- pasting old pages for diagnosis.

High-quality request:

```text
Use meta-skill `meta-skill-creator`.

Create a new meta-skill for product launch briefs. It should search current
sources, collect product context, draft a launch memo, generate a DOCX handoff,
check evidence gaps, and avoid publishing anything automatically.

Please propose:
- name
- description
- triggers
- steps
- validation gates
- collision checks
```

Expected result: a proposal, not an immediate unreviewed production rollout.

## Avoiding Accidental Activation

If you paste old chat history, Web UI dumps, prompt examples, skill lists, or
test material, mark it as quoted context:

```text
The following is quoted context, not my current request.
Do not run any skill.
Do not create or persist any proposal.
Only analyze this text.
```

This matters because historical material may contain trigger words. Without a
clear boundary, the system may confuse quoted content with current intent.

If you only want to analyze a MetaSkill and do not want proposal creation:

```text
Only analyze. Do not create, assemble, preview, or persist any meta-skill
proposal.
```

## Reading the Result

A strong MetaSkill result should explain:

- what it produced;
- what facts or sources it used;
- what is inferred or assumed;
- what risks remain;
- what the next action is;
- what could not be verified;
- whether any artifact or proposal was actually created.

Be cautious if the output:

- claims current facts without sources;
- claims a file was created but no artifact exists;
- hides tool failures as success;
- gives generic advice instead of the requested deliverable;
- ignores "do not create", "do not send", "do not publish", or "do not install".

## Correcting a Bad Run

If the wrong MetaSkill triggered:

```text
Stop using the previous MetaSkill. Treat my earlier text as context only. Now
use meta-skill `<correct_name>` for this goal: ...
```

If no MetaSkill triggered:

```text
Please rerun and explicitly use meta-skill `<name>`.
```

If the output is too generic:

```text
Redo this as a decision-ready deliverable with evidence, assumptions, risks, and
next actions.
```

If creator starts creating but you do not want creation:

```text
Do not create, assemble, preview, or persist any meta-skill proposal. Only
analyze.
```

## Building Your Own MetaSkill

A task is a good MetaSkill candidate when:

- you repeatedly perform the same high-value task;
- each run has multiple steps;
- inputs are similar but details vary;
- the output format is relatively stable;
- review, audit, replay, or confirmation matters;
- ordinary prompts require you to restate too many rules every time.

Poor candidates include one-line fact queries, single tool calls, casual
conversation, brainstorming without stable output criteria, and high-risk
automated action without human confirmation.

For the authoring protocol, read [`../authoring/meta-skills.md`](../authoring/meta-skills.md).

---

[Docs index](../README.md) · [Product guide](../../README.product.md) · [Improve this page](../contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
