---
name: meta-paper-write
description: "Draft a demo research paper end-to-end from a topic phrase: web search → source curation → BibTeX → citation plan → topic-aware outline → figure → section drafts → global revision → abstract-last → xelatex compile → PDF."
kind: meta
meta_priority: 50
always: false
triggers:
  - "写论文"
  - "draft a paper"
  - "写篇论文"
  - "write paper"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: search_papers
      kind: skill_exec
      skill: multi-search-engine
    - id: experiment
      kind: skill_exec
      skill: paper-experiment-stub
    - id: refbib
      kind: skill_exec
      skill: paper-refbib-stub
      depends_on: [search_papers]
    - id: source_pack
      kind: agent
      skill: paper-source-curator
      depends_on: [search_papers, refbib]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        search_results: "{{ outputs.search_papers | truncate(8000) }}"
        bibliography: "{{ outputs.refbib | truncate(8000) }}"
    - id: outline
      kind: agent
      skill: paper-outline-author
      depends_on: [source_pack]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        source_pack: "{{ outputs.source_pack | truncate(8000) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(8000) }}"
    - id: citation_plan
      kind: agent
      skill: paper-citation-planner
      depends_on: [outline, source_pack, refbib]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        outline: "{{ outputs.outline }}"
        source_pack: "{{ outputs.source_pack | truncate(8000) }}"
        bibliography: "{{ outputs.refbib | truncate(8000) }}"
    - id: plot
      kind: skill_exec
      skill: paper-plot-stub
      depends_on: [experiment]
    - id: draft_intro
      kind: agent
      skill: paper-section-author
      depends_on: [outline, citation_plan, refbib, plot]
      with:
        section: "introduction"
        outline: "{{ outputs.outline }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(8000) }}"
    - id: draft_method
      kind: agent
      skill: paper-section-author
      depends_on: [outline, citation_plan, refbib, plot]
      with:
        section: "method"
        outline: "{{ outputs.outline }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(8000) }}"
    - id: draft_results
      kind: agent
      skill: paper-section-author
      depends_on: [outline, citation_plan, refbib, plot]
      with:
        section: "results"
        outline: "{{ outputs.outline }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(8000) }}"
        figure_path: "paper/figure_1.pdf"
    - id: draft_discussion
      kind: agent
      skill: paper-section-author
      depends_on: [outline, citation_plan, refbib, plot]
      with:
        section: "discussion"
        outline: "{{ outputs.outline }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(8000) }}"
    - id: revised_body
      kind: agent
      skill: paper-revision-author
      depends_on: [draft_intro, draft_method, draft_results, draft_discussion]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        outline: "{{ outputs.outline }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        introduction: "{{ outputs.draft_intro }}"
        method: "{{ outputs.draft_method }}"
        results: "{{ outputs.draft_results }}"
        discussion: "{{ outputs.draft_discussion }}"
    - id: draft_abstract
      kind: agent
      skill: paper-abstract-author
      depends_on: [revised_body, citation_plan]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        citation_plan: "{{ outputs.citation_plan | truncate(8000) }}"
        revised_body: "{{ outputs.revised_body | truncate(8000) }}"
    - id: compile_latex
      kind: skill_exec
      skill: latex-compile
      depends_on: [draft_abstract]
---

# meta-paper-write (Meta-Skill, demo)

Take a research topic and produce a compiled PDF paper.

Pipeline (14 steps; search/experiment start concurrently, body sections run in
parallel after source curation, citation planning, and plotting):

| # | step | kind | skill |
|---|------|------|-------|
| ① | search_papers | skill_exec | multi-search-engine |
| ② | experiment | skill_exec | paper-experiment-stub |
| ③ | refbib | skill_exec | paper-refbib-stub (reads ① on stdin) |
| ④ | source_pack | agent | paper-source-curator |
| ⑤ | outline | agent | paper-outline-author |
| ⑥ | citation_plan | agent | paper-citation-planner |
| ⑦ | plot | skill_exec | paper-plot-stub (reads ②'s results.csv) |
| ⑧ | draft_intro | agent | paper-section-author |
| ⑨ | draft_method | agent | paper-section-author |
| ⑩ | draft_results | agent | paper-section-author |
| ⑪ | draft_discussion | agent | paper-section-author |
| ⑫ | revised_body | agent | paper-revision-author |
| ⑬ | draft_abstract | agent | paper-abstract-author |
| ⑭ | compile_latex | skill_exec | latex-compile (assembles paper.tex, xelatex×3 + bibtex) |

## Fallback

If the orchestration fails mid-pipeline, retry the failing step manually or
run the pieces directly. The script that compiles the LaTeX is
`paper/compile.py`; it expects `paper/paper.tex` and `paper/references.bib`
to exist.
