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
metadata:
  opensquilla:
    risk: low
    capabilities:
      - filesystem-write
composition:
  steps:
    - id: paper_collect
      kind: user_input
      clarify:
        mode: form
        intro: |
          开始之前，请确认 5 件事 —— 我会用它生成完整论文 / Before drafting,
          please confirm 5 items — I'll use them to generate the manuscript.
        # skip_if lets E2E tests pre-populate inputs.collected.paper_collect
        # and bypass the live pause; production turns leave it empty so the
        # form fires.
        skip_if: "inputs.collected.paper_collect is defined"
        # Accept natural-language replies — when the deterministic
        # parser fails the runtime falls through to an LLM extractor
        # that maps free-form prose onto the schema fields.
        nl_extract: true
        fields:
          - name: topic
            type: string
            required: true
            prompt: "论文主题 / Paper topic"
            max_chars: 200
          - name: paper_mode
            type: enum
            required: true
            choices:
              - FULL_MANUSCRIPT
              - COMPACT_SKELETON
              - REPAIR_EXISTING
              - COMPILE_ONLY
            prompt: "类型 / Mode (FULL_MANUSCRIPT=10+页完整稿; COMPACT_SKELETON=骨架; REPAIR_EXISTING=修复; COMPILE_ONLY=只编译)"
          - name: language
            type: enum
            choices: [en, zh, ja, other]
            default: en
            prompt: "语言 / Language"
          - name: target_length_pages
            type: int
            min: 1
            max: 50
            default: 10
            prompt: "目标页数 / Target pages (1–50)"
          - name: audience
            type: enum
            choices: [academic, technical, business, general]
            default: academic
            prompt: "受众 / Audience"
        cancel_keywords: ["算了", "取消", "cancel", "stop", "abort"]
        timeout_hours: 24
    - id: paper_preferences
      kind: llm_chat
      depends_on: [paper_collect]
      with:
        system: "You expand user-confirmed paper requirements into a structured planning contract."
        task: |
          Expand the user-confirmed paper facts into a full planning contract.

          User-confirmed facts (DO NOT override these):
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}
          PAPER_MODE: {{ inputs.collected.paper_collect.paper_mode }}
          LANGUAGE: {{ inputs.collected.paper_collect.language }}
          TARGET_PAGES: {{ inputs.collected.paper_collect.target_length_pages }}
          AUDIENCE: {{ inputs.collected.paper_collect.audience }}

          Original user request (context only, do NOT override confirmed facts):
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          PAPER_MODE: {{ inputs.collected.paper_collect.paper_mode }}
          MODE: DIRECT
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}
          AUDIENCE: {{ inputs.collected.paper_collect.audience }}
          VENUE_STYLE: <generic research paper or inferred venue>
          LANGUAGE: {{ inputs.collected.paper_collect.language }}
          TARGET_LENGTH: {{ inputs.collected.paper_collect.target_length_pages }}+ compiled pages
          MIN_REFERENCES: 20
          CITATION_STYLE: BibTeX cite keys, LaTeX \cite{...}
          ASSUMPTIONS:
            - <assumption>
    - id: search_papers
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [paper_preferences]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        query: "{{ inputs.collected.paper_collect.topic | xml_escape | truncate(512) }}"
        engines: [brave, duckduckgo, tavily]
        max_results: 25
    - id: experiment
      kind: skill_exec
      skill: paper-experiment-stub
      depends_on: [paper_preferences]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        topic: "{{ inputs.collected.paper_collect.topic | xml_escape | truncate(200) }}"
    - id: refbib
      kind: skill_exec
      skill: paper-refbib-stub
      depends_on: [search_papers]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        search_results: "{{ outputs.search_papers | truncate(8000) }}"
    - id: source_pack
      kind: llm_chat
      depends_on: [search_papers, refbib]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
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
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You design long-form LaTeX paper outlines with citation plans."
        task: |
          Create a {{ inputs.collected.paper_collect.target_length_pages }}+ page
          research-paper outline with enough section depth for a substantial
          manuscript. Every section must name planned cite keys from the
          bibliography.

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Source pack:
          {{ outputs.source_pack | truncate(8000) }}

          Cite keys hint:
          {{ outputs.refbib | truncate(8000) }}
    - id: citation_plan
      kind: llm_chat
      depends_on: [outline, source_pack, refbib]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You plan citation placement for clean BibTeX/LaTeX manuscripts."
        task: |
          Build a citation plan that uses at least 20 distinct citation keys
          when the bibliography provides them. Use only keys that appear in
          the BibTeX below. Attach citations to claims, not paragraphs in bulk.

          Topic:
          {{ inputs.collected.paper_collect.topic | xml_escape | truncate(200) }}

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
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        results_csv: "paper/results.csv"
    - id: final_manuscript_package
      kind: llm_chat
      depends_on: [paper_collect, outline, citation_plan, refbib, plot]
      with:
        system: "You write clean LaTeX manuscripts. Output only the requested manuscript package."
        task: |
          Draft a full manuscript package. The default output must be clean
          LaTeX-ready paper text, not planning notes. Do not include markdown
          fences, chat commentary, progress notes, or tool logs.

          Paper mode:
          {{ inputs.collected.paper_collect.paper_mode }}

          Mode behavior:
          - FULL_MANUSCRIPT: produce enough substance for
            {{ inputs.collected.paper_collect.target_length_pages }}+ compiled
            pages (default 10+ compiled pages), at least 20 references when
            provided, and at least 20 distinct citation keys used across
            abstract, introduction, related work, method, results, discussion,
            limitations, and conclusion.
          - COMPACT_SKELETON: produce a compact LaTeX-ready manuscript
            skeleton with section goals, planned citations, and expansion
            notes; do not pretend it is a 10+ page finished paper. Keep
            MANUSCRIPT_TEX short enough that the output always includes a
            complete REFERENCES_BIB block and COMPILE_NOTES. For compact
            skeletons, prefer concise section stubs over long prose and cap
            the manuscript body at roughly 1,500 words before REFERENCES_BIB.
          - REPAIR_EXISTING: return a repaired clean LaTeX package focused on
            citation integrity, structure, and removal of process text.
          - COMPILE_ONLY: return a compile handoff package and blockers only;
            do not invent missing manuscript body.

          Shared requirements:
          - include Figure~\ref{fig:main} only if the plot step produced a figure
          - keep every \cite{...} key present in the bibliography
          - never omit REFERENCES_BIB; if the provided bibliography has fewer
            than 20 usable entries, include all provided entries and add clearly
            marked placeholder BibTeX stubs such as @misc{placeholderNN,...}
            until the output contains at least 20 reference entries
          - in COMPACT_SKELETON mode, citation integrity beats prose length:
            output a complete skeleton plus complete REFERENCES_BIB rather than
            an overlong body without references

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
          through conclusion; compact mode must include all requested sections
          but stay brief enough to leave room for references>

          REFERENCES_BIB:
          <at least 20 BibTeX entries or clearly marked placeholder BibTeX
          stubs; every \cite{...} key in MANUSCRIPT_TEX must appear here>

          COMPILE_NOTES:
          - <short note about figure/reference assumptions>
    - id: paper_length_gate
      kind: llm_chat
      depends_on: [final_manuscript_package, citation_plan, refbib]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You verify manuscript length requirements without rewriting the paper."
        task: |
          Check whether the manuscript package is long enough before LaTeX
          compilation. Estimate compiled pages and identify any section that
          needs expansion. Do not include process commentary.

          Requirements:
          - target {{ inputs.collected.paper_collect.target_length_pages }}+ compiled pages
          - substantial introduction, method, results, and discussion sections
          - no placeholder-only paragraphs

          Manuscript:
          {{ outputs.final_manuscript_package | truncate(12000) }}

          Citation plan:
          {{ outputs.citation_plan | truncate(4000) }}
    - id: citation_integrity_gate
      kind: llm_chat
      depends_on: [final_manuscript_package, citation_plan, refbib]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'REPAIR_EXISTING')"
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
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'REPAIR_EXISTING', 'COMPILE_ONLY')"
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
      when: "inputs.collected.paper_collect.paper_mode == 'COMPILE_ONLY'"
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

1. **`paper_collect`** (user_input) — confirm topic, mode, language, target
   length, and audience with the user before any DAG branching. Replaces
   the previous `paper_mode` (llm_classify) + `paper_preferences`
   inference of these same facts; the model no longer guesses what the
   user wanted.
2. Save as `paper_preferences` (now expands the collected facts into a
   planning contract).
3. Run `multi-search-engine` and `paper-experiment-stub`.
4. Run `paper-refbib-stub` to create references from search output.
5. Build a source pack. Save as `source_pack`.
6. Build an outline and citation plan. Save as `citation_plan`.
7. Build the manuscript package. Save as `final_manuscript_package`.
8. Run `paper-plot-stub` for a deterministic figure artifact.
9. Run length, citation-integrity, sanitizer, and compile-readiness gates.

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
- The `paper_mode` step (llm_classify) was removed; downstream `when:`
  clauses now reference `inputs.collected.paper_collect.paper_mode`
  instead of `outputs.paper_mode`.
