---
name: meta-paper-write
description: "Draft a demo research paper end-to-end from a topic phrase: web search → BibTeX → stub experiment → outline → matplotlib figure → 5 parallel section drafts → xelatex compile → PDF."
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
    - id: outline
      kind: agent
      skill: paper-outline-author
      depends_on: [refbib]
      with:
        topic: "{{ inputs.user_message | xml_escape | truncate(200) }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: plot
      kind: skill_exec
      skill: paper-plot-stub
      depends_on: [experiment]
    - id: draft_abstract
      kind: agent
      skill: paper-section-author
      depends_on: [outline, refbib, plot]
      with:
        section: "abstract"
        outline: "{{ outputs.outline }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: draft_intro
      kind: agent
      skill: paper-section-author
      depends_on: [outline, refbib, plot]
      with:
        section: "introduction"
        outline: "{{ outputs.outline }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: draft_method
      kind: agent
      skill: paper-section-author
      depends_on: [outline, refbib, plot]
      with:
        section: "method"
        outline: "{{ outputs.outline }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: draft_results
      kind: agent
      skill: paper-section-author
      depends_on: [outline, refbib, plot]
      with:
        section: "results"
        outline: "{{ outputs.outline }}"
        figure_path: "paper/figure_1.pdf"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: draft_discussion
      kind: agent
      skill: paper-section-author
      depends_on: [outline, refbib, plot]
      with:
        section: "discussion"
        outline: "{{ outputs.outline }}"
        cite_keys_hint: "{{ outputs.refbib | truncate(1500) }}"
    - id: compile_latex
      kind: skill_exec
      skill: latex-compile
      depends_on:
        - draft_abstract
        - draft_intro
        - draft_method
        - draft_results
        - draft_discussion
---

# meta-paper-write (Meta-Skill, demo)

Take a research topic and produce a compiled PDF paper.

Pipeline (11 steps; ① and ② start concurrently, ⑥–⑩ run in parallel after
their join):

| # | step | kind | skill |
|---|------|------|-------|
| ① | search_papers | skill_exec | multi-search-engine |
| ② | experiment | skill_exec | paper-experiment-stub |
| ③ | refbib | skill_exec | paper-refbib-stub (reads ① on stdin) |
| ④ | outline | agent | paper-outline-author |
| ⑤ | plot | skill_exec | paper-plot-stub (reads ②'s results.csv) |
| ⑥ | draft_abstract | agent | paper-section-author |
| ⑦ | draft_intro | agent | paper-section-author |
| ⑧ | draft_method | agent | paper-section-author |
| ⑨ | draft_results | agent | paper-section-author |
| ⑩ | draft_discussion | agent | paper-section-author |
| ⑪ | compile_latex | skill_exec | latex-compile (assembles paper.tex, xelatex×3 + bibtex) |

## Fallback

If the orchestration fails mid-pipeline, retry the failing step manually or
run the pieces directly. The script that compiles the LaTeX is
`paper/compile.py`; it expects `paper/paper.tex` and `paper/references.bib`
to exist.
