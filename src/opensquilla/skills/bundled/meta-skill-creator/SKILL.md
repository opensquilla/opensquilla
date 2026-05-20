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
      skill: history-explorer
      with:
        query: |
          Co-occurring skill chains and meta-skill usage for: {{ inputs.user_message | xml_escape | truncate(512) }}
        window_days: 30
        include: [co_occurrence, meta_usage, router_misses]

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
      skill: meta-skill-linter
      depends_on: [assemble]
      with:
        skill_md: "{{ outputs.assemble }}"
        gates: [G1, G2]

    - id: smoke
      skill: meta-skill-smoke-test
      depends_on: [lint]
      with:
        skill_md: "{{ outputs.assemble }}"
        gates: [G3, G4]
        fixture_gen_model: openai/gpt-4o-mini
        classifier_model: anthropic/claude-3.5-haiku

    - id: persist
      skill: meta-skill-proposals
      depends_on: [smoke]
      with:
        action: write_proposal
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

If creator's pipeline fails, fall back to: invoke `history-explorer` to view
co-occurrences, draft a SKILL.md by hand using the patterns documented in
`src/opensquilla/skills/creator/patterns/`, then run `meta-skill-linter` to
validate it before placing it under `~/.opensquilla/skills/<name>/`.
