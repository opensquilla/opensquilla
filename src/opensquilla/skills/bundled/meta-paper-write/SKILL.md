---
name: meta-paper-write
description: "Draft a demo research paper end-to-end from a topic phrase: web search → BibTeX → stub experiment → outline → matplotlib figure → 5 parallel section drafts → xelatex compile → PDF."
kind: meta_sop
meta_priority: 50
always: false
triggers:
  - "draft a paper"
  - "write paper"
  - "写篇论文"
  - "写一篇论文"
  - "撰写论文"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
---

# meta-paper-write (SOP form)

## Phase 1: Foundation [parallel]
Run `multi-search-engine`. Save as `search_papers`.
Run `paper-experiment-stub`. Save as `experiment`.

## Phase 2: Bibliography [depends_on: search_papers]
Run `paper-refbib-stub`. Save as `refbib`.

## Phase 3: Outline
Invoke `paper-outline-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
Save as `outline`.

## Phase 4: Plot [depends_on: experiment]
Run `paper-plot-stub`. Save as `plot`.

## Phase 5: Drafting [parallel for_each: section; depends_on: [outline, refbib, plot]]
```yaml for_each
section:
  - {id: draft_abstract,   name: abstract}
  - {id: draft_intro,      name: introduction}
  - {id: draft_method,     name: method}
  - {id: draft_results,    name: results, figure_path: paper/figure_1.pdf}
  - {id: draft_discussion, name: discussion}
```

Invoke `paper-section-author` as agent with:
- section: `{{ section.name }}`
    - outline: `{{ outputs.outline }}`
    - cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
- figure_path: `{{ section.figure_path }}`
Save as `{{ section.id }}`.

## Phase 6: Compile [depends_on: [draft_abstract, draft_intro, draft_method, draft_results, draft_discussion]]
Run `latex-compile`. Save as `compile_latex`.
