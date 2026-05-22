---
name: meta-research-to-deck
description: "From a research question to a structured PowerPoint deck: search → deep-research → slide outline → pptx render."
kind: meta
meta_priority: 70
always: false
triggers:
  - "研究 PPT"
  - "research deck"
  - "汇报 PPT"
  - "pitch deck"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: search
      skill: multi-search-engine
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, duckduckgo, tavily]
        max_results: 10
    - id: research
      skill: deep-research
      depends_on: [search]
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.search }}"
        rounds: 1
    - id: outline
      skill: summarize
      depends_on: [research]
      with:
        text: "{{ outputs.research }}"
        style: slide_outline
        max_words: 800
    - id: deck
      skill: pptx
      depends_on: [outline]
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        outline: "{{ outputs.outline }}"
---

# Research-to-Deck (Meta-Skill)

Turns a research question into a PowerPoint pitch deck. Each step's
output flows into the next; the final `pptx` skill writes an artifact
under the workspace.

## Fallback

LLM should sequentially call search, deep-research, summarize, and
`pptx` create-from-scratch.
