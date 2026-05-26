---
name: meta-paper-write
description: "Use this meta-skill instead of answering directly when the user needs a research paper, academic paper, or long-form LaTeX manuscript that benefits from multi-skill orchestration across source search, citation planning, section drafting, length checks, bibliography integrity, and LaTeX compilation."
kind: meta
meta_priority: 50
always: false
final_text_mode: "step:final_manuscript_package"
triggers:
  - "draft a paper"
  - "write paper"
  - "academic manuscript"
  - "research manuscript"
  - "latex manuscript"
  - "long-form paper"
  - "写篇论文"
  - "写一篇论文"
  - "撰写论文"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: paper_mode
      kind: llm_classify
      output_choices:
        - FULL_MANUSCRIPT
        - COMPACT_SKELETON
        - REPAIR_EXISTING
        - COMPILE_ONLY
      with:
        text: |
          Classify the paper-writing request.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Decision rules:
          - FULL_MANUSCRIPT: user asks to write/draft a full paper, manuscript,
            long LaTeX article, 10+ pages, or citation-heavy deliverable.
          - COMPACT_SKELETON: user asks for outline, proposal, structure,
            citation plan, or a lightweight paper draft.
          - REPAIR_EXISTING: user asks to fix, expand, sanitize, or repair an
            existing paper/manuscript/LaTeX text.
          - COMPILE_ONLY: user explicitly asks to compile/export an existing
            LaTeX paper into PDF.
    - id: paper_preferences
      kind: llm_chat
      depends_on: [paper_mode]
      with:
        system: "You infer academic-paper requirements. Return only the requested contract."
        task: |
          Infer a paper-writing contract from the user request. Do not ask
          follow-up questions in the default path; use conservative academic
          defaults and mark them explicitly.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          PAPER_MODE: {{ outputs.paper_mode }}
          MODE: DIRECT
          TOPIC: <topic>
          AUDIENCE: <academic|technical|business|general>
          VENUE_STYLE: <generic research paper or inferred venue>
          LANGUAGE: <language>
          TARGET_LENGTH: 10+ compiled pages
          MIN_REFERENCES: 20
          CITATION_STYLE: BibTeX cite keys, LaTeX \cite{...}
          ASSUMPTIONS:
            - <assumption>
    - id: search_papers
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [paper_preferences]
      when: "outputs.paper_mode != 'COMPILE_ONLY'"
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, duckduckgo, tavily]
        max_results: 25
    - id: experiment
      kind: skill_exec
      skill: paper-experiment-stub
      depends_on: [paper_preferences]
      when: "outputs.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
    - id: refbib
      kind: skill_exec
      skill: paper-refbib-stub
      depends_on: [search_papers]
      when: "outputs.paper_mode != 'COMPILE_ONLY'"
      with:
        search_results: "{{ outputs.search_papers | truncate(8000) }}"
    - id: source_pack
      kind: llm_chat
      depends_on: [search_papers, refbib]
      when: "outputs.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You curate paper sources and enforce citation coverage."
        task: |
          Build a source pack for a paper draft. Prefer primary papers,
          official documentation, surveys, and reputable technical reports.
          Keep at least 20 usable references when the search results allow it.
          If fewer than 20 credible references are available, keep all credible
          references and state the gap.

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Search results:
          {{ outputs.search_papers | truncate(8000) }}

          Bibliography:
          {{ outputs.refbib | truncate(8000) }}

          Return:
          SOURCE_PACK:
          PRIMARY_REFERENCES:
            - refN | title | supported claim
          COVERAGE_GAPS:
            - <gap or none>
    - id: outline
      kind: llm_chat
      depends_on: [source_pack]
      when: "outputs.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You design long-form LaTeX paper outlines with citation plans."
        task: |
          Create a 10+ page research-paper outline with enough section depth
          for a substantial manuscript. Every section must name planned cite
          keys from the bibliography.

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Source pack:
          {{ outputs.source_pack | truncate(8000) }}

          Cite keys hint:
          {{ outputs.refbib | truncate(8000) }}
    - id: citation_plan
      kind: llm_chat
      depends_on: [outline, source_pack, refbib]
      when: "outputs.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You plan citation placement for clean BibTeX/LaTeX manuscripts."
        task: |
          Build a citation plan that uses at least 20 distinct citation keys
          when the bibliography provides them. Use only keys that appear in
          the BibTeX below. Attach citations to claims, not paragraphs in bulk.

          Topic:
          {{ inputs.user_message | xml_escape | truncate(200) }}

          Outline:
          {{ outputs.outline | truncate(6000) }}

          Source pack:
          {{ outputs.source_pack | truncate(8000) }}

          Bibliography:
          {{ outputs.refbib | truncate(8000) }}
    - id: plot
      kind: skill_exec
      skill: paper-plot-stub
      depends_on: [experiment]
      when: "outputs.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        results_csv: "paper/results.csv"
    - id: final_manuscript_package
      kind: llm_chat
      depends_on: [paper_mode, outline, citation_plan, refbib, plot]
      with:
        system: "You write clean LaTeX manuscripts. Output only the requested manuscript package."
        task: |
          Draft a full manuscript package. The default output must be clean
          LaTeX-ready paper text, not planning notes. Do not include markdown
          fences, chat commentary, progress notes, or tool logs.

          Paper mode:
          {{ outputs.paper_mode }}

          Mode behavior:
          - FULL_MANUSCRIPT: produce enough substance for 10+ compiled pages,
            at least 20 references when provided, and at least 20 distinct
            citation keys used across abstract, introduction, related work,
            method, results, discussion, limitations, and conclusion.
          - COMPACT_SKELETON: produce a compact LaTeX-ready manuscript
            skeleton with section goals, planned citations, and expansion
            notes; do not pretend it is a 10+ page finished paper.
          - REPAIR_EXISTING: return a repaired clean LaTeX package focused on
            citation integrity, structure, and removal of process text.
          - COMPILE_ONLY: return a compile handoff package and blockers only;
            do not invent missing manuscript body.

          Shared requirements:
          - include Figure~\ref{fig:main} only if the plot step produced a figure
          - keep every \cite{...} key present in the bibliography

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Outline:
          {{ outputs.outline | truncate(8000) }}

          Citation plan:
          {{ outputs.citation_plan | truncate(8000) }}

          Plot artifact:
          {{ outputs.plot | truncate(1000) }}

          Bibliography:
          {{ outputs.refbib | truncate(8000) }}

          Return exactly:
          MANUSCRIPT_TEX:
          <clean LaTeX body, starting with \begin{abstract} and continuing
          through conclusion>

          REFERENCES_BIB:
          <BibTeX entries copied from the provided bibliography>

          COMPILE_NOTES:
          - <short note about figure/reference assumptions>
    - id: paper_length_gate
      kind: llm_chat
      depends_on: [final_manuscript_package, citation_plan, refbib]
      when: "outputs.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You verify manuscript length requirements without rewriting the paper."
        task: |
          Check whether the manuscript package is long enough before LaTeX
          compilation. Estimate compiled pages and identify any section that
          needs expansion. Do not include process commentary.

          Requirements:
          - target 10+ compiled pages
          - substantial introduction, method, results, and discussion sections
          - no placeholder-only paragraphs

          Manuscript:
          {{ outputs.final_manuscript_package | truncate(12000) }}

          Citation plan:
          {{ outputs.citation_plan | truncate(4000) }}
    - id: citation_integrity_gate
      kind: llm_chat
      depends_on: [final_manuscript_package, citation_plan, refbib]
      when: "outputs.paper_mode in ('FULL_MANUSCRIPT', 'REPAIR_EXISTING')"
      with:
        system: "You verify LaTeX/BibTeX citation integrity."
        task: |
          Validate citation integrity before LaTeX compilation.

          Requirements:
          - at least 20 references in REFERENCES_BIB when sources allow it
          - at least 20 distinct citation keys used or planned in the body
          - no citation keys absent from references.bib
          - every major claim has nearby citation support or an explicit caveat

          Citation plan:
          {{ outputs.citation_plan | truncate(8000) }}

          Bibliography:
          {{ outputs.refbib | truncate(8000) }}

          Manuscript:
          {{ outputs.final_manuscript_package | truncate(12000) }}
    - id: latex_sanitizer
      kind: llm_chat
      depends_on: [paper_length_gate, citation_integrity_gate]
      when: "outputs.paper_mode in ('FULL_MANUSCRIPT', 'REPAIR_EXISTING', 'COMPILE_ONLY')"
      with:
        system: "You sanitize LaTeX deliverables and reject process text."
        task: |
          Sanitize the final LaTeX package contract before compilation. Confirm
          that process commentary, markdown fences, chat preambles, debug logs,
          and non-paper text are absent from MANUSCRIPT_TEX and REFERENCES_BIB.
          Preserve valid LaTeX, CJK text, citations, figure references, and
          section content. Reply with a concise readiness note and any blocking
          issue only.

          Length gate:
          {{ outputs.paper_length_gate | truncate(2000) }}

          Citation gate:
          {{ outputs.citation_integrity_gate | truncate(2000) }}
    - id: compile_latex
      kind: llm_chat
      depends_on: [latex_sanitizer]
      when: "outputs.paper_mode == 'COMPILE_ONLY'"
      with:
        system: "You prepare compile handoff notes without invoking LaTeX in the default path."
        task: |
          Produce a concise compile handoff note. Do not run xelatex in the
          default meta-skill path; the manuscript text is the user-facing
          deliverable and real compilation is an explicit follow-up action.

          Sanitizer result:
          {{ outputs.latex_sanitizer | truncate(2000) }}

          Reply exactly:
          COMPILE_READY: <yes|blocked>
          NEXT_STEP: run latex-compile explicitly when the user asks for a PDF
          BLOCKERS:
            - <blocker or none>
---

# meta-paper-write (Meta-Skill)

Draft a long LaTeX manuscript by orchestrating paper-specific skills and
bounded LLM synthesis:

1. Save as `paper_preferences`.
2. Run `multi-search-engine` and `paper-experiment-stub`.
3. Run `paper-refbib-stub` to create references from search output.
4. Build a source pack. Save as `source_pack`.
5. Build an outline and citation plan. Save as `citation_plan`.
6. Build the manuscript package. Save as `final_manuscript_package`.
7. Run `paper-plot-stub` for a deterministic figure artifact.
8. Run length, citation-integrity, sanitizer, and compile-readiness gates.

The default path intentionally returns `final_manuscript_package` instead of
running `latex-compile`. This avoids timeout and prevents process text from
being inserted into the paper. If the user explicitly asks for a compiled PDF,
run `latex-compile` as the second-stage artifact step after inspecting the
manuscript package.

Compatibility notes for older contract readers:
- `paper-preference-planner`, `paper-source-curator`,
  `paper-citation-planner`, `paper-revision-author`, and
  `paper-abstract-author` were the original heavy sub-agent stages.
- The compact path keeps their responsibilities but performs them as bounded
  `llm_chat` glue around the real skill outputs.
- Citation templates still use `{{ outputs.refbib | truncate(8000) }}` and
  the quality gates preserve `paper_length_gate`, `citation_integrity_gate`,
  `latex_sanitizer`, and `compile_latex`.
