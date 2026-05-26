---
name: meta-web-research-to-report
description: "Use this meta-skill instead of answering directly when the user needs a cited research report, market/technical briefing, or source-backed writeup that benefits from multi-skill orchestration across preference inference, web research, drafting, quality review, and export."
kind: meta
meta_priority: 80
always: false
final_text_mode: "step:final_report"
triggers:
  - "调研报告"
  - "research report"
  - "写一份报告"
  - "write up the findings"
  - "source-backed writeup"
  - "technical briefing"
  - "market briefing"
  - "cited report"
  - "查一下并写报告"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: preferences
      kind: llm_chat
      with:
        system: "You infer report requirements. Return only the requested contract."
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
    - id: report_mode
      kind: llm_classify
      depends_on: [preferences]
      output_choices:
        - QUICK_DECISION_MEMO
        - DEEP_REPORT
        - EXPORT_DOCX
      with:
        text: |
          Classify the report request.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Preferences:
          {{ outputs.preferences | truncate(1200) }}

          Decision rules:
          - QUICK_DECISION_MEMO: user wants a concise answer, quick brief,
            comparison memo, or decision aid.
          - DEEP_REPORT: user wants a source-backed report/briefing/writeup
            but did not explicitly request a file export.
          - EXPORT_DOCX: user explicitly asks for a Word/docx/file/report
            artifact export.
    - id: search
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [report_mode]
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, tavily, duckduckgo]
        max_results: 20
    - id: source_quality
      kind: llm_chat
      depends_on: [search]
      with:
        system: "You curate search results for cited report writing. Be selective and source-aware."
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
      when: "outputs.report_mode in ('DEEP_REPORT', 'EXPORT_DOCX')"
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.source_quality }}"
        rounds: 2
    - id: outline
      kind: llm_chat
      depends_on: [source_quality, research]
      with:
        system: "You design concise, evidence-backed report outlines."
        task: |
          Create a report outline before drafting. The outline must match the
          audience, report type, and target length below. Include sections for
          executive summary, key findings, evidence, risks/limits, and source
          list unless the user explicitly requested another structure.

          Preferences:
          {{ outputs.preferences | truncate(1200) }}

          Report mode:
          {{ outputs.report_mode }}

          Source pack:
          {{ outputs.source_quality | truncate(4000) }}

          Research:
          {{ outputs.research | truncate(8000) }}
    - id: report_draft
      skill: summarize
      depends_on: [outline]
      with:
        text: "Report mode:\n{{ outputs.report_mode }}\n\nPreferences:\n{{ outputs.preferences }}\n\nOutline:\n{{ outputs.outline }}\n\nSource pack:\n{{ outputs.source_quality }}\n\nResearch:\n{{ outputs.research }}"
        style: cited_report
        max_words: 3500
    - id: source_to_claim
      kind: llm_chat
      depends_on: [report_draft, source_quality]
      with:
        system: "You audit report claims against source packs."
        task: |
          Build a concise source-to-claim map for the draft. Keep only
          claims that are supported by the source pack or explicitly mark a
          caveat. Do not add process commentary.

          Source pack:
          {{ outputs.source_quality | truncate(6000) }}

          Draft:
          {{ outputs.report_draft | truncate(8000) }}
    - id: quality_gate
      kind: llm_chat
      depends_on: [report_draft, source_quality, source_to_claim]
      with:
        system: "You polish final reports and remove process commentary."
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

          Source-to-claim map:
          {{ outputs.source_to_claim | truncate(4000) }}

          Draft:
          {{ outputs.report_draft | truncate(8000) }}
    - id: final_report
      kind: llm_chat
      depends_on: [quality_gate]
      with:
        system: "You produce the final user-facing report body."
        task: |
          Return the final report body only. Use the requested language and
          keep the report mode in mind:
          - QUICK_DECISION_MEMO: concise decision memo with bullets, sources,
            and caveats.
          - DEEP_REPORT: full cited report with executive summary, findings,
            evidence, limitations, and sources.
          - EXPORT_DOCX: same as DEEP_REPORT, suitable for DOCX export.

          Report mode:
          {{ outputs.report_mode }}

          Polished report:
          {{ outputs.quality_gate | truncate(10000) }}
    - id: export
      skill: docx
      depends_on: [final_report]
      when: "outputs.report_mode == 'EXPORT_DOCX'"
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        body: "{{ outputs.final_report }}"
---

# Web Research to Report (Meta-Skill)

Produce a cited Word report from a single research question. The workflow
first derives the report contract, ranks sources, drafts from an outline, and
runs a readiness gate before exporting.

## Fallback

If the orchestrator fails, the LLM should manually drive each step using
the corresponding skill's SKILL.md as guidance.
