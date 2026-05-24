# Meta-Skill Authoring Guide

This guide is the user-facing contract for creating OpenSquilla meta-skills.
A meta-skill is a `SKILL.md` with `kind: meta` and a `composition:` DAG. The
model activates it by calling `meta_invoke(name="<meta-skill-name>")`; the
runtime executes the steps and returns the final result.

## Required Shape

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
---
```

Use `metadata.opensquilla.risk` to declare the highest unattended auto-enable
risk: `low`, `medium`, or `high`. Use `metadata.opensquilla.capabilities` to
make side effects explicit. Common capabilities are:

- `filesystem-write`, `artifact-write`, `document-export`: writes local files or artifacts.
- `network`, `network-read`: reads external network resources.
- `network-write`, `external-side-effect`, `credential-use`, `process-control`, `shell`: high-risk side effects.

If a referenced sub-skill lacks this metadata, auto-enable falls back to a
small legacy compatibility list. New skills should not rely on that fallback.

## Step Types

Use these step kinds:

- `agent`: ask an existing skill to solve part of the task.
- `llm_classify`: choose one value from `output_choices`.
- `tool_call`: call a tool directly. This is high risk and must include an allowlist.
- `skill_exec`: run a wrapped-CLI skill entrypoint. This is at least medium risk.

Prefer `agent` and `llm_classify` for user-facing meta-skills. Use direct
`tool_call` or `skill_exec` only when the target operation is deterministic and
the risk is declared in metadata.

## Template Safety

Templates are Jinja expressions. Treat user input and previous step output as
untrusted:

- For user text, start with `xml_escape` or `slugify`, then bound it with `truncate`.
- For `outputs.<step_id>`, always bound or encode with `truncate`, `xml_escape`, `slugify`, or `tojson`.
- Do not pass raw `{{ inputs.user_message }}` into a downstream step.
- Do not pass raw `{{ outputs.some_step }}` into another step.

Examples:

```yaml
query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
text: "{{ outputs.search | truncate(2000) }}"
payload: "{{ outputs.plan | tojson }}"
```

## Validation Checklist

Before sharing a meta-skill:

1. Parse and lint it with the meta-skill creator gates.
2. Run deterministic trigger checks:
   `scripts/meta_trigger_accuracy.py`.
3. Run model-decision soft activation checks:
   `scripts/live_meta_soft_activation_e2e.py --env-file /path/to/.env`.
4. For generated skills, inspect the Web UI proposal detail and its
   auto-enable audit before accepting or enabling.

## Example: history-summary

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
of previous OpenSquilla work. The first step retrieves relevant history; the
second step turns it into a concise operational answer.
```

## Example: classification gate

```markdown
---
name: safe-routing-check
kind: meta
description: Decide whether a user request should use a local read-only flow.
triggers:
  - check routing safety
metadata:
  opensquilla:
    risk: low
    capabilities: []
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices: [READ_ONLY, NEEDS_REVIEW]
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(512) }}"
final_text_mode: "step:classify"
---

# safe-routing-check
```
