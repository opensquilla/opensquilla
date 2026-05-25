---
name: meta-paper-write
description: "Use when the user asks to draft a research paper, academic paper, or long-form LaTeX manuscript from a topic phrase or research direction."
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

## Phase 1: Preferences
Invoke `paper-preference-planner` as agent with:
- user_message: `{{ inputs.user_message | xml_escape | truncate(1200) }}`
Save as `paper_preferences`.

## Phase 2: Foundation [parallel]
Run `multi-search-engine`. Save as `search_papers`.
Run `paper-experiment-stub`. Save as `experiment`.

## Phase 3: Bibliography [depends_on: search_papers]
Run `paper-refbib-stub`. Save as `refbib`.

## Phase 4: Source Curation [depends_on: [search_papers, refbib]]
Invoke `paper-source-curator` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- search_results: `{{ outputs.search_papers | truncate(8000) }}`
- bibliography: `{{ outputs.refbib | truncate(8000) }}`
Save as `source_pack`.

## Phase 5: Outline [depends_on: source_pack]
Invoke `paper-outline-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- source_pack: `{{ outputs.source_pack | truncate(8000) }}`
- cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
Save as `outline`.

## Phase 6: Citation Plan [depends_on: [outline, source_pack, refbib]]
Invoke `paper-citation-planner` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- outline: `{{ outputs.outline }}`
- source_pack: `{{ outputs.source_pack | truncate(8000) }}`
- bibliography: `{{ outputs.refbib | truncate(8000) }}`
Save as `citation_plan`.

## Phase 7: Plot [depends_on: experiment]
Run `paper-plot-stub`. Save as `plot`.

## Phase 8: Body Drafting [parallel for_each: section; depends_on: [outline, citation_plan, refbib, plot]]
```yaml for_each
section:
  - {id: draft_intro,      name: introduction}
  - {id: draft_method,     name: method}
  - {id: draft_results,    name: results, figure_path: paper/figure_1.pdf}
  - {id: draft_discussion, name: discussion}
```

Invoke `paper-section-author` as agent with:
- section: `{{ section.name }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- outline: `{{ outputs.outline }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- cite_keys_hint: `{{ outputs.refbib | truncate(8000) }}`
- figure_path: `{{ section.figure_path }}`
Save as `{{ section.id }}`.

## Phase 9: Global Revision [depends_on: [draft_intro, draft_method, draft_results, draft_discussion]]
Invoke `paper-revision-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- outline: `{{ outputs.outline }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- introduction: `{{ outputs.draft_intro }}`
- method: `{{ outputs.draft_method }}`
- results: `{{ outputs.draft_results }}`
- discussion: `{{ outputs.draft_discussion }}`
Save as `revised_body`.

## Phase 10: Abstract [depends_on: [revised_body, citation_plan]]
Invoke `paper-abstract-author` as agent with:
- topic: `{{ inputs.user_message | xml_escape | truncate(200) }}`
- paper_preferences: `{{ outputs.paper_preferences | truncate(4000) }}`
- citation_plan: `{{ outputs.citation_plan | truncate(8000) }}`
- revised_body: `{{ outputs.revised_body | truncate(8000) }}`
Save as `draft_abstract`.

## Phase 11: Pre-Compile Quality Gates [parallel; depends_on: [draft_abstract, revised_body, citation_plan, refbib]]
Invoke `sub-agent` as agent with:
- task: |
    Check whether the manuscript is long enough before LaTeX compilation.
    Requirements:
    - target 10+ compiled pages
    - substantial introduction, method, results, and discussion sections
    - no placeholder-only paragraphs
    - report estimated page count and missing sections

    Paper preferences:
    `{{ outputs.paper_preferences | truncate(4000) }}`

    Abstract:
    `{{ outputs.draft_abstract | truncate(2000) }}`

    Body:
    `{{ outputs.revised_body | truncate(8000) }}`
Save as `paper_length_gate`.

Invoke `sub-agent` as agent with:
- task: |
    Validate citation integrity before LaTeX compilation.
    Requirements:
    - at least 20 references in the bibliography when sources allow it
    - at least 20 distinct citation keys used or planned in the body
    - no citation keys absent from references.bib
    - every major claim has nearby citation support or an explicit caveat

    Citation plan:
    `{{ outputs.citation_plan | truncate(8000) }}`

    Bibliography:
    `{{ outputs.refbib | truncate(8000) }}`

    Body:
    `{{ outputs.revised_body | truncate(8000) }}`
Save as `citation_integrity_gate`.

## Phase 12: LaTeX Sanitizer [depends_on: [paper_length_gate, citation_integrity_gate]]
Invoke `sub-agent` as agent with:
- task: |
    Sanitize the final LaTeX workspace before compilation. Remove process
    commentary, markdown fences, chat preambles, debug logs, and any text that
    is not intended to appear in the paper. Preserve valid LaTeX, CJK text,
    citations, figure references, and section files. Reply with a concise
    readiness note only after the workspace is clean.

    Length gate:
    `{{ outputs.paper_length_gate | truncate(2000) }}`

    Citation gate:
    `{{ outputs.citation_integrity_gate | truncate(2000) }}`
Save as `latex_sanitizer`.

## Phase 13: Compile [depends_on: latex_sanitizer]
Run `latex-compile`. Save as `compile_latex`.
