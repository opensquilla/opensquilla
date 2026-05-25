---
name: meta-web-research-to-report
description: "Use when the user asks for a cited research report, market/technical briefing, or written report from web sources and wants an artifact rather than a short chat answer."
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
    - id: preferences
      kind: agent
      skill: sub-agent
      with:
        task: |
          Infer the report contract from the request. If details are missing,
          choose conservative defaults and mark them as assumptions instead of
          asking follow-up questions.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          AUDIENCE: <reader>
          REPORT_TYPE: <technical|market|policy|general>
          TARGET_LENGTH: <short|standard|long>
          LANGUAGE: <language>
          CITATION_STYLE: <inline links|footnotes|bibliography>
          ASSUMPTIONS:
            - <assumption>
    - id: search
      skill: multi-search-engine
      depends_on: [preferences]
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, tavily, duckduckgo]
        max_results: 20
    - id: source_quality
      kind: agent
      skill: sub-agent
      depends_on: [search]
      with:
        task: |
          Rank and deduplicate these web results for report writing.
          Prefer primary sources, official docs, reputable publications, and
          recent sources when the topic is time-sensitive. Remove low-quality
          SEO pages and repeated mirrors.

          Report preferences:
          {{ outputs.preferences | truncate(1200) }}

          Search results:
          {{ outputs.search | truncate(8000) }}

          Return a concise source pack with 8-15 sources. For each source,
          include title, URL, credibility reason, and the claim it supports.
    - id: research
      skill: deep-research
      depends_on: [source_quality]
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.source_quality }}"
        rounds: 2
    - id: outline
      kind: agent
      skill: sub-agent
      depends_on: [research]
      with:
        task: |
          Create a report outline before drafting. The outline must match the
          audience, report type, and target length below. Include sections for
          executive summary, key findings, evidence, risks/limits, and source
          list unless the user explicitly requested another structure.

          Preferences:
          {{ outputs.preferences | truncate(1200) }}

          Research:
          {{ outputs.research | truncate(8000) }}
    - id: report_draft
      skill: summarize
      depends_on: [outline]
      with:
        text: "Preferences:\n{{ outputs.preferences }}\n\nOutline:\n{{ outputs.outline }}\n\nResearch:\n{{ outputs.research }}"
        style: cited_report
        max_words: 3500
    - id: quality_gate
      kind: agent
      skill: sub-agent
      depends_on: [report_draft, source_quality]
      with:
        task: |
          Review the report draft for artifact readiness. Verify:
          - every major claim has a source or clear caveat
          - source list contains credible URLs
          - executive summary and limitations are present
          - output is in the requested language

          If acceptable, return the polished report body. If not, repair it
          directly and return the repaired report body. Do not include process
          commentary.

          Source pack:
          {{ outputs.source_quality | truncate(4000) }}

          Draft:
          {{ outputs.report_draft | truncate(8000) }}
    - id: export
      skill: docx
      depends_on: [quality_gate]
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        body: "{{ outputs.quality_gate }}"
---

# Web Research to Report (Meta-Skill)

Produce a cited Word report from a single research question. The workflow
first derives the report contract, ranks sources, drafts from an outline, and
runs a readiness gate before exporting.

## Fallback

If the orchestrator fails, the LLM should manually drive each step using
the corresponding skill's SKILL.md as guidance.
