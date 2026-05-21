---
name: meta-skill-creator
description: "Synthesize a new meta-skill: harvest skill co-occurrence history → classify the right composition pattern → fill the slot schema → assemble SKILL.md → lint + smoke-test → persist to ~/.opensquilla/proposals/."
kind: meta
meta_priority: 30
always: false
triggers:
  - "新增 meta 技能"
  - "组合现有 skill 成 meta-skill"
  - "synthesize meta-skill"
  - "compose meta-skill"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: harvest
      kind: skill_exec
      skill: history-explorer
      on_failure: harvest_empty
      with:
        query: |
          Co-occurring skill chains and meta-skill usage for: {{ inputs.user_message | xml_escape | truncate(512) }}
        window_days: 30
        include: [co_occurrences, meta_usage, router_fixtures]

    - id: harvest_empty
      kind: tool_call
      tool: emit_text
      tool_args:
        text: "no history available; downstream should rely on user intent only"

    - id: pick_pattern
      kind: llm_classify
      depends_on: [harvest]
      output_choices: [p1_sequential, p2_fan_out_merge]
      with:
        history_summary: "{{ outputs.harvest | truncate(2000) }}"
        user_intent: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: fill_slots
      kind: tool_call
      depends_on: [pick_pattern]
      tool: meta_skill_fill_slots
      tool_args:
        pattern_id: "{{ outputs.pick_pattern }}"
        history_summary: "{{ outputs.harvest | truncate(2000) }}"
        user_intent: "{{ inputs.user_message | xml_escape | truncate(512) }}"

    - id: assemble
      kind: tool_call
      depends_on: [fill_slots]
      tool: meta_skill_assemble
      tool_args:
        pattern_id: "{{ outputs.pick_pattern }}"
        slots_json: "{{ outputs.fill_slots }}"

    - id: lint
      kind: tool_call
      depends_on: [assemble]
      tool: meta_skill_lint_run
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        gates: "G1,G2"

    - id: smoke
      kind: tool_call
      depends_on: [lint]
      tool: meta_skill_smoke_run
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        fixture_gen_model: openai/gpt-4o-mini
        classifier_model: anthropic/claude-3.5-haiku

    - id: persist
      kind: tool_call
      depends_on: [smoke]
      tool: meta_skill_persist_proposal
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        lint_result: "{{ outputs.lint }}"
        smoke_result: "{{ outputs.smoke }}"
---

# Meta-Skill Creator

7-step DAG that synthesizes a new bundled meta-skill from observed skill
co-occurrence patterns + user description of the desired workflow.

Output is a SKILL.md candidate written to `~/.opensquilla/proposals/<id>/`,
not auto-loaded. Run `opensquilla meta accept <id>` (Phase 2) to enable.

## Fallback

If creator's pipeline fails at any step, **report the failure verbatim** to the
user:

1. State which step failed (e.g. "harvest", "lint")
2. Quote the error message from the orchestrator's structured log
3. Stop. Do NOT improvise.

Do NOT:
- Claim a proposal was written unless you have verified it by reading
  `~/.opensquilla/proposals/<id>/SKILL.md` with the `read_file` tool
- Invent file paths, proposal IDs, or skill names that you have not seen
  in the orchestrator's actual output
- "Manually run" the individual skills as a recovery — that bypasses
  the validation gates the user explicitly opted into

If the user wants to retry, suggest they re-issue the request after the
underlying error is resolved (often a sandbox or provider issue), not a
manual workaround.
