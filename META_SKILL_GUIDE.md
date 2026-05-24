# Meta-Skill User Guide and Templates

This guide explains how to use, write, validate, and review OpenSquilla
meta-skills. It is intentionally user-facing: copy a template, fill in the
workflow, run the checks, then install or propose the skill.

## What Is a Meta-Skill?

A meta-skill is a `SKILL.md` file with:

- `kind: meta`
- one or more natural-language `triggers`
- a `composition:` block that defines a directed acyclic graph of steps

At runtime, the model sees the available meta-skills and may call:

```text
meta_invoke(name="<meta-skill-name>")
```

OpenSquilla then executes the composition step by step and returns the final
result to the user. The model chooses the workflow, but the runtime enforces
the declared graph, dependency order, template safety, risk metadata, recursion
guards, and tool gates.

## When to Use a Meta-Skill

Use a meta-skill when a task is repeatable and naturally decomposes into a
small workflow, for example:

- classify the user request, then route to the right specialist skill
- run two independent analysis skills, then merge their outputs
- search or inspect context, then summarize it into a user-facing answer
- execute a deterministic CLI-backed skill, then review or persist the result

Do not use a meta-skill for one-off instructions, open-ended planning that
should remain conversational, or flows that need arbitrary recursion. A
meta-skill cannot compose another meta-skill.

## Where to Put a Meta-Skill

For local managed skills, create:

```text
~/.opensquilla/skills/<skill-name>/SKILL.md
```

For repository-bundled skills, place the skill under the bundled skills tree:

```text
src/opensquilla/skills/bundled/<skill-name>/SKILL.md
```

Generated proposals are reviewed before installation. After accepting a
proposal, OpenSquilla promotes it into the managed skills directory and refreshes
the live skill loader.

## Basic Usage Flow

1. Copy one of the templates below into a new `SKILL.md`.
2. Replace the name, description, triggers, risk metadata, and steps.
3. Keep each step id short, lowercase, and stable, for example `classify`,
   `search`, `summarize`, or `persist`.
4. Add `depends_on` whenever a step needs output from earlier steps.
5. Filter all user input and previous step output in templates.
6. Run the validation checklist before sharing or enabling the skill.
7. Test the natural trigger phrasing in a real chat turn or with the live
   soft-activation harness.

Users can activate a meta-skill in two ways:

- Soft activation: ask naturally, and let the model choose the right
  `meta_invoke` call.
- Explicit activation: ask for the named meta-skill when debugging or testing,
  for example, "Run the `history-summary` meta-skill on this request."

## Required Frontmatter

Every meta-skill should declare:

```yaml
---
name: short-stable-name
kind: meta
description: One sentence that tells the model when this workflow applies.
triggers:
  - short phrase users naturally type
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps: []
final_text_mode: auto
---
```

The frontmatter fields have these meanings:

- `name`: stable identifier used by `meta_invoke`.
- `kind`: must be `meta`.
- `description`: model-facing description for when to use the workflow.
- `triggers`: phrases used by deterministic and model-assisted activation.
- `metadata.opensquilla.risk`: highest unattended auto-enable risk, one of
  `low`, `medium`, or `high`.
- `metadata.opensquilla.capabilities`: explicit side-effect capabilities.
- `composition.steps`: ordered DAG definition.
- `final_text_mode`: how the final answer is derived.

## Risk Metadata

Use `metadata.opensquilla.risk` to declare the highest risk level required by
the workflow:

- `low`: read-only reasoning, classification, summarization, or safe local
  inspection.
- `medium`: local file or artifact writes, deterministic document generation,
  or network reads.
- `high`: shell/process control, credential use, network writes, external side
  effects, or direct tool calls that can alter state.

Use `metadata.opensquilla.capabilities` to make side effects explicit. Common
capabilities include:

- `filesystem-write`
- `artifact-write`
- `document-export`
- `network`
- `network-read`
- `network-write`
- `external-side-effect`
- `credential-use`
- `process-control`
- `shell`

If a referenced sub-skill lacks risk metadata, unattended auto-enable treats
the dependency conservatively. New skills should declare risk and capabilities
instead of relying on legacy compatibility fallbacks.

## Step Types

Meta-skill steps support four execution kinds.

### `agent`

Use `agent` for a normal skill-backed sub-agent turn. This is the best default
for user-facing reasoning and synthesis.

```yaml
- id: summarize
  kind: agent
  skill: summarize
  with:
    text: "{{ outputs.search | truncate(2000) }}"
```

### `llm_classify`

Use `llm_classify` when the step should return exactly one value from a closed
set. This is useful for routing, triage, and compact decisions.

```yaml
- id: classify
  kind: llm_classify
  output_choices: [BUG, FEATURE, QUESTION]
  with:
    text: "{{ inputs.user_message | xml_escape | truncate(512) }}"
```

### `tool_call`

Use `tool_call` only for deterministic direct tool execution. Declare a
`tool_allowlist`, keep arguments narrow, and mark the meta-skill as high risk
when the tool can change state.

```yaml
- id: persist
  kind: tool_call
  tool: memory_save
  tool_allowlist: [memory_save]
  tool_args:
    text: "{{ outputs.summary | truncate(2000) }}"
```

### `skill_exec`

Use `skill_exec` for a skill with an `entrypoint:` manifest that should run as
a subprocess. This is appropriate for deterministic CLI-backed skills such as
document conversion or report generation.

```yaml
- id: render
  kind: skill_exec
  skill: html-to-pdf
  with:
    html: "{{ outputs.report | truncate(12000) }}"
```

## Dependencies and Parallelism

Steps without dependencies may run in parallel. A step with `depends_on` waits
for all named steps to finish.

```yaml
composition:
  steps:
    - id: inspect_code
      kind: agent
      skill: code-reviewer
      with:
        request: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: inspect_tests
      kind: agent
      skill: test-engineer
      with:
        request: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: merge
      kind: agent
      skill: summarize
      depends_on: [inspect_code, inspect_tests]
      with:
        text: |
          Code review:
          {{ outputs.inspect_code | truncate(2000) }}

          Test review:
          {{ outputs.inspect_tests | truncate(2000) }}
```

The graph must be acyclic. A step may only depend on step ids declared in the
same composition.

## Routing and Failure Handling

Use `route` when an `agent` or `skill_exec` step should choose a skill based on
previous outputs:

```yaml
- id: classify
  kind: llm_classify
  output_choices: [DOCS, BUG, SECURITY]
  with:
    text: "{{ inputs.user_message | xml_escape | truncate(512) }}"

- id: handle
  kind: agent
  skill: summarize
  depends_on: [classify]
  route:
    - when: "outputs.classify == 'DOCS'"
      to: writer
    - when: "outputs.classify == 'BUG'"
      to: debugger
    - when: "outputs.classify == 'SECURITY'"
      to: security-reviewer
  with:
    request: "{{ inputs.user_message | xml_escape | truncate(512) }}"
```

Use `on_failure` for a single substitute step. The substitute must exist in the
same plan, must not have its own dependencies, and must not have its own
`on_failure`.

```yaml
- id: primary_summary
  kind: agent
  skill: summarize
  on_failure: fallback_summary
  with:
    text: "{{ inputs.user_message | xml_escape | truncate(512) }}"

- id: fallback_summary
  kind: llm_classify
  output_choices: [NEEDS_MANUAL_REVIEW]
  with:
    text: "The primary summary failed."
```

## Final Text Modes

Use `final_text_mode` to control the final user-facing result:

- `auto`: default. The orchestrator summarizes step outputs into a concise
  final answer.
- `raw`: return the last non-substitute step output verbatim.
- `step:<step_id>`: return one specific step output verbatim.

Examples:

```yaml
final_text_mode: auto
final_text_mode: raw
final_text_mode: "step:summarize"
```

Use `step:<step_id>` when one step is the intended deliverable. Use `raw` when
the final step already formats a complete report. Use `auto` when the workflow
produces several intermediate outputs that need a compact user-facing summary.

## Template Safety

Templates are Jinja expressions. Treat user input and previous step output as
untrusted:

- For user text, start with `xml_escape` or `slugify`, then bound it with
  `truncate`.
- For `outputs.<step_id>`, always bound or encode with `truncate`,
  `xml_escape`, `slugify`, or `tojson`.
- Do not pass raw `{{ inputs.user_message }}` into a downstream step.
- Do not pass raw `{{ outputs.some_step }}` into another step.
- Keep prompt-shaped strings explicit, short, and task-specific.

Safe examples:

```yaml
query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
text: "{{ outputs.search | truncate(2000) }}"
slug: "{{ inputs.user_message | slugify | truncate(80) }}"
payload: "{{ outputs.plan | tojson }}"
```

Unsafe examples:

```yaml
query: "{{ inputs.user_message }}"
text: "{{ outputs.search }}"
```

## Activation Guidance

Write triggers as short phrases users naturally type:

- Prefer: `summarize recent history`
- Prefer: `review current diff`
- Avoid: `run the internal OpenSquilla DAG composition meta skill`

Use two to five triggers. Avoid triggers that collide with explanation
questions such as "how does this meta-skill work?" A user asking about a
meta-skill should not accidentally run it.

Set `description` to explain when the model should choose the workflow. Do not
hide critical constraints in the body only; the model primarily sees the
frontmatter and injected skill summary.

## Validation Checklist

Before sharing or enabling a meta-skill:

1. Confirm the frontmatter parses as YAML.
2. Confirm `kind: meta` and `composition.steps` are present.
3. Confirm all `depends_on`, `route.to`, and `on_failure` references point to
   valid steps or skills.
4. Confirm the graph has no cycles.
5. Confirm all user input and step outputs are filtered.
6. Confirm `metadata.opensquilla.risk` and `metadata.opensquilla.capabilities`
   reflect the workflow's true side effects.
7. Run deterministic trigger checks with:
   `scripts/meta_trigger_accuracy.py`.
8. Run model-decision soft activation checks with:
   `scripts/live_meta_soft_activation_e2e.py --env-file /path/to/.env`.
9. For generated skills, inspect the Web UI proposal detail and its
   auto-enable audit before accepting or enabling.

## Troubleshooting

If the meta-skill does not appear to run:

- Check that the `SKILL.md` is under a loaded skill directory.
- Refresh or restart the gateway if the skill was added outside the proposal
  accept flow.
- Confirm `disable-model-invocation` is not set for a meta-skill you expect the
  model to invoke.
- Confirm the skill has `kind: meta` and a non-empty `composition.steps` list.
- Confirm the user wording matches the triggers or description.

If parsing fails:

- Check duplicate step ids.
- Check unknown `kind` values.
- Check missing `skill` for `agent` or `skill_exec` steps.
- Check missing `output_choices` for `llm_classify`.
- Check missing `tool`, invalid `tool_args`, or mismatched `tool_allowlist` for
  `tool_call`.
- Check cycles and undefined `depends_on` references.

If auto-enable is skipped:

- Inspect the proposal's auto-enable audit in the Web UI.
- Add missing risk metadata to referenced sub-skills.
- Lower the workflow's side effects, or require manual review for medium/high
  risk workflows.

## Template: Minimal Read-Only Classifier

Use this for a read-only decision that returns one label.

```markdown
---
name: classify-request-type
kind: meta
description: Classify a user request into a small set of operational categories.
triggers:
  - classify request type
  - route this request
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices: [BUG, FEATURE, QUESTION, OTHER]
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(512) }}"
final_text_mode: "step:classify"
---

# classify-request-type

Use this when the user wants a compact routing label for a request.
```

## Template: Sequential Research and Summary

Use this when one skill gathers facts and another skill turns them into the
final answer.

```markdown
---
name: history-summary
kind: meta
description: Inspect recent OpenSquilla history and summarize operational facts.
triggers:
  - summarize recent history
  - inspect decision history
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: find_history
      kind: agent
      skill: history-explorer
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: summarize_history
      kind: agent
      skill: summarize
      depends_on: [find_history]
      with:
        text: "{{ outputs.find_history | truncate(2000) }}"
        focus: "facts, file paths, commands, and remaining risks"
final_text_mode: "step:summarize_history"
---

# history-summary

Use this when the user asks what happened recently or wants a concise summary
of previous OpenSquilla work.
```

## Template: Parallel Review and Merge

Use this when independent review lanes can run at the same time and a final
step merges the results.

```markdown
---
name: current-diff-review-bundle
kind: meta
description: Review the current diff from code, test, and risk perspectives.
triggers:
  - review current diff
  - inspect uncommitted changes
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: code_review
      kind: agent
      skill: code-reviewer
      with:
        request: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: test_review
      kind: agent
      skill: test-engineer
      with:
        request: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: merge_findings
      kind: agent
      skill: summarize
      depends_on: [code_review, test_review]
      with:
        text: |
          Code review:
          {{ outputs.code_review | truncate(3000) }}

          Test review:
          {{ outputs.test_review | truncate(3000) }}
        focus: "ranked findings, evidence, and recommended next actions"
final_text_mode: "step:merge_findings"
---

# current-diff-review-bundle

Use this when the user wants a structured review of local changes.
```

## Template: Router With Specialist Dispatch

Use this when the first step chooses a lane and the second step dispatches to a
specialist skill.

```markdown
---
name: support-request-router
kind: meta
description: Route a support request to the right specialist workflow.
triggers:
  - route support request
  - triage this issue
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices: [BUG, DOCS, SECURITY]
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: handle
      kind: agent
      skill: debugger
      depends_on: [classify]
      route:
        - when: "outputs.classify == 'BUG'"
          to: debugger
        - when: "outputs.classify == 'DOCS'"
          to: writer
        - when: "outputs.classify == 'SECURITY'"
          to: security-reviewer
      with:
        request: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        classification: "{{ outputs.classify | xml_escape | truncate(64) }}"
final_text_mode: "step:handle"
---

# support-request-router

Use this when the user wants the request handled by the most relevant
specialist.
```

## Template: Deterministic Tool Call

Use this only when a direct tool call is safer and more deterministic than a
sub-agent turn. Keep it review-gated unless the side effect is truly low risk.

```markdown
---
name: save-summary-note
kind: meta
description: Summarize a request and save a bounded note through an allowlisted tool.
triggers:
  - save summary note
metadata:
  opensquilla:
    risk: high
    capabilities: [external-side-effect]
composition:
  steps:
    - id: summarize
      kind: agent
      skill: summarize
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(1000) }}"

    - id: persist
      kind: tool_call
      tool: memory_save
      tool_allowlist: [memory_save]
      depends_on: [summarize]
      tool_args:
        text: "{{ outputs.summarize | truncate(2000) }}"
final_text_mode: "step:summarize"
---

# save-summary-note

Use this only after confirming the user wants the note persisted.
```

## Template: CLI-Backed Artifact Generation

Use this for a skill with an `entrypoint:` manifest that generates a local
artifact. Mark it medium or high risk depending on the side effects.

```markdown
---
name: report-to-pdf
kind: meta
description: Convert a bounded report draft into a PDF artifact.
triggers:
  - render report pdf
metadata:
  opensquilla:
    risk: medium
    capabilities: [filesystem-write, artifact-write, document-export]
composition:
  steps:
    - id: draft
      kind: agent
      skill: summarize
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(4000) }}"
        focus: "a concise Markdown report"

    - id: render
      kind: skill_exec
      skill: html-to-pdf
      depends_on: [draft]
      with:
        html: "{{ outputs.draft | truncate(12000) }}"
final_text_mode: "step:render"
---

# report-to-pdf

Use this when the user explicitly asks for a PDF artifact.
```
