---
name: meta-paper-write
description: "Draft a demo research paper end-to-end from a topic phrase: web search → source curation → BibTeX → citation plan → topic-aware outline → figure → section drafts → global revision → abstract-last → xelatex compile → PDF."
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

## Phase 3: Source Curation [depends_on: [search_papers, refbib]]
Invoke `paper-source-curator` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- search_results: `{{ outputs.search_papers | truncate(8000) }}`
- bibliography: `{{ outputs.refbib | truncate(8000) }}`
Save as `source_pack`.

## Phase 4: Outline [depends_on: source_pack]
Invoke `paper-outline-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- source_pack: `{{ outputs.source_pack | truncate(8000) }}`
- cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
Save as `outline`.

## Phase 5: Citation Plan [depends_on: [outline, source_pack, refbib]]
Invoke `paper-citation-planner` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- outline: `{{ outputs.outline }}`
- source_pack: `{{ outputs.source_pack | truncate(8000) }}`
- bibliography: `{{ outputs.refbib | truncate(8000) }}`
Save as `citation_plan`.

## Phase 6: Plot [depends_on: experiment]
Run `paper-plot-stub`. Save as `plot`.

## Phase 7: Body Drafting [parallel for_each: section; depends_on: [outline, citation_plan, refbib, plot]]
```yaml for_each
section:
  - {id: draft_intro,      name: introduction}
  - {id: draft_method,     name: method}
  - {id: draft_results,    name: results, figure_path: paper/figure_1.pdf}
  - {id: draft_discussion, name: discussion}
```

Invoke `paper-section-author` as agent with:
- section: `{{ section.name }}`
- outline: `{{ outputs.outline }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
- figure_path: `{{ section.figure_path }}`
Save as `{{ section.id }}`.

## Phase 8: Global Revision [depends_on: [draft_intro, draft_method, draft_results, draft_discussion]]
Invoke `paper-revision-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- outline: `{{ outputs.outline }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- introduction: `{{ outputs.draft_intro }}`
- method: `{{ outputs.draft_method }}`
- results: `{{ outputs.draft_results }}`
- discussion: `{{ outputs.draft_discussion }}`
Save as `revised_body`.

## Phase 9: Abstract [depends_on: [revised_body, citation_plan]]
Invoke `paper-abstract-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- revised_body: `{{ outputs.revised_body | truncate(8000) }}`
Save as `draft_abstract`.

## Phase 10: Compile [depends_on: draft_abstract]
Run `latex-compile`. Save as `compile_latex`.
