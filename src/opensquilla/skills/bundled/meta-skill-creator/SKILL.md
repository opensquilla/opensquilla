---
name: meta-skill-creator
description: "Use when the user explicitly asks to compose, synthesize, or create a new meta-skill that orchestrates existing skills."
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
    - id: clarify_intent
      kind: agent
      skill: sub-agent
      with:
        task: |
          Clarify whether the user wants a meta-skill, not a normal standalone
          skill. If the request is generic skill creation, return
          ROUTE: normal-skill. If it requires orchestrating multiple existing
          skills, return ROUTE: meta-skill. Also summarize desired inputs,
          outputs, trigger phrases, and whether a human preference branch is
          needed.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

    - id: harvest
      kind: skill_exec
      skill: history-explorer
      depends_on: [clarify_intent]
      on_failure: harvest_empty
      with:
        query: |
          Co-occurring skill chains and meta-skill usage for: {{ outputs.clarify_intent | truncate(1000) }}
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
        user_intent: "{{ outputs.clarify_intent | truncate(1000) }}"

    - id: fill_slots
      kind: tool_call
      depends_on: [pick_pattern]
      tool: meta_skill_fill_slots
      tool_args:
        pattern_id: "{{ outputs.pick_pattern }}"
        history_summary: "{{ outputs.harvest | truncate(2000) }}"
        user_intent: "{{ outputs.clarify_intent | truncate(1000) }}"

    - id: assemble
      kind: tool_call
      depends_on: [fill_slots]
      tool: meta_skill_assemble
      tool_args:
        pattern_id: "{{ outputs.pick_pattern }}"
        slots_json: "{{ outputs.fill_slots }}"

    - id: collision_check
      kind: agent
      skill: sub-agent
      depends_on: [assemble]
      with:
        task: |
          Review this generated meta-skill proposal for trigger collisions with
          existing bundled skills. Flag generic triggers, overlaps with
          meta-skill-creator, and broad phrases that would steal unrelated user
          intent. Return PASS or REVISE_NEEDED plus reasons.

          Candidate SKILL.md:
          {{ outputs.assemble | truncate(8000) }}

    - id: lint
      kind: tool_call
      depends_on: [collision_check]
      tool: meta_skill_lint_run
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        gates: "G1,G2"

    - id: risk_classify
      kind: agent
      skill: sub-agent
      depends_on: [lint]
      with:
        task: |
          Classify operational risk for the generated meta-skill. Consider file
          writes, network access, GitHub/gh actions, shell commands, memory
          writes, and destructive operations. Return:
          RISK: low|medium|high
          CAPABILITIES:
            - <capability>
          REQUIRED_GATES:
            - <gate>

          Candidate SKILL.md:
          {{ outputs.assemble | truncate(8000) }}

          Lint result:
          {{ outputs.lint | truncate(2000) }}

    - id: smoke
      kind: tool_call
      depends_on: [risk_classify]
      tool: meta_skill_smoke_run
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        fixture_gen_model: openai/gpt-4o-mini
        classifier_model: anthropic/claude-3.5-haiku

    - id: preview
      kind: agent
      skill: sub-agent
      depends_on: [smoke]
      with:
        task: |
          Produce a concise proposal preview for the user/operator before
          persistence. Include proposed name, triggers, DAG summary, collision
          result, risk classification, lint status, smoke status, and whether
          it appears eligible for acceptance. Do not invent paths or proposal
          IDs.

          Candidate SKILL.md:
          {{ outputs.assemble | truncate(8000) }}

          Collision check:
          {{ outputs.collision_check | truncate(1200) }}

          Risk:
          {{ outputs.risk_classify | truncate(1200) }}

          Lint:
          {{ outputs.lint | truncate(2000) }}

          Smoke:
          {{ outputs.smoke | truncate(2000) }}

    - id: persist
      kind: tool_call
      depends_on: [preview]
      tool: meta_skill_persist_proposal
      tool_args:
        skill_md: "{{ outputs.assemble }}"
        lint_result: "{{ outputs.lint }}"
        smoke_result: "{{ outputs.smoke }}"
---

# Meta-Skill Creator

Safeguarded DAG that synthesizes a new bundled meta-skill from observed skill
co-occurrence patterns + user description of the desired workflow. It now
separates generic skill creation from meta-skill composition, checks trigger
collisions, classifies operational risk, and previews the proposal before
persisting it.

Output is a SKILL.md candidate written to `~/.opensquilla/proposals/<id>/`.
By default it is not auto-loaded; run `opensquilla meta accept <id>` (Phase 2)
to enable. If the operator has enabled the auto-propose `auto_enable` setting,
this manual path also runs the same conservative static safety preflight used by
cron/dream auto-propose and may promote a low-risk gated proposal immediately.

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
