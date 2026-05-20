---
name: meta-web-research-to-report
description: "From a single research question to a fully-cited Word report: multi-engine search → deep-research iteration → structured summary → docx export."
kind: meta
meta_priority: 80
always: false
triggers:
  - "调研报告"
  - "research report"
  - "写一份报告"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: search
      skill: multi-search-engine
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, tavily, duckduckgo]
        max_results: 15
    - id: research
      skill: deep-research
      depends_on: [search]
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.search }}"
        rounds: 1
    - id: condense
      skill: summarize
      depends_on: [research]
      with:
        text: "{{ outputs.research }}"
        style: structured
        max_words: 2000
    - id: export
      skill: docx
      depends_on: [condense]
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        body: "{{ outputs.condense }}"
---

# Web Research to Report (Meta-Skill)

Produce a fully-cited Word report from a single research question.
Steps: search → multi-round research → structured summary → docx render.

## Fallback

If the orchestrator fails, the LLM should manually drive each step using
the corresponding skill's SKILL.md as guidance.
