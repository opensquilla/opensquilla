---
name: meta-paper-write
description: "Use this meta-skill instead of answering directly when the user needs a research paper, academic paper, or long-form LaTeX manuscript that benefits from multi-skill orchestration across source search, citation planning, experiment design, placeholder figures/tables, section drafting, length checks, citation integrity, and LaTeX compilation."
kind: meta
meta_priority: 50
always: false
final_text_mode: "step:deliver_paper"
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
        skip_if: "inputs.collected.paper_collect is defined"
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
        system: "You expand extracted paper requirements into a structured planning contract."
        task: |
          Expand the extracted paper facts into a full planning contract.

          Extracted paper contract (DO NOT override these):
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}, MODE: {{ inputs.collected.paper_collect.paper_mode }}, PAGES: {{ inputs.collected.paper_collect.target_length_pages }}

          Original user request (context only, do NOT override confirmed facts):
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          PAPER_MODE: <copy PAPER_MODE from extracted contract>
          MODE: DIRECT
          TOPIC: <copy TOPIC from extracted contract>
          AUDIENCE: <copy AUDIENCE from extracted contract>
          VENUE_STYLE: <generic research paper or inferred venue>
          LANGUAGE: <copy LANGUAGE from extracted contract>
          TARGET_LENGTH: <copy TARGET_PAGES from extracted contract>+ compiled pages
          MIN_REFERENCES: 20
          CITATION_STYLE: BibTeX cite keys, LaTeX \cite{...}
          ASSUMPTIONS:
            - <assumption>
    - id: search_query_translation
      kind: llm_chat
      depends_on: [paper_collect]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You translate paper topics into concise English academic search queries. Output only the query text."
        task: |
          Translate the user-confirmed paper topic into one concise
          English academic search query optimised for arXiv / ACL
          Anthology / ACM DL / OpenReview / IEEE / Nature / Science.

          Strict rules:
          - Output ONLY the English query text on a single line.
          - Do NOT include preambles, labels (no "Query:", "Translation:"),
            quotes, the word "search", boolean operators, site filters,
            or the year — those are appended downstream by the runtime.
          - Keep it ≤ 12 words; prefer the canonical English term for any
            non-English research area (e.g. 检索增强生成 → retrieval-augmented
            generation; 大模型对齐 → large language model alignment).
          - If the topic is already in English, return it unchanged
            (clean up only obvious typos / extraneous words).

          Topic (may be Chinese, Japanese, or English):
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}, MODE: {{ inputs.collected.paper_collect.paper_mode }}, PAGES: {{ inputs.collected.paper_collect.target_length_pages }}
    - id: search_papers
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [paper_preferences, search_query_translation]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        # search_query_translation returns ONLY the English query text
        # (no labels / no preamble), so we can inline it directly.
        # Academic-site bias filters out blog/wiki/social.
        query: "{{ outputs.search_query_translation | xml_escape | truncate(200) }} (site:arxiv.org OR site:aclanthology.org OR site:dl.acm.org OR site:openreview.net OR site:ieee.org OR site:nature.com OR site:science.org)"
        engines: [brave, duckduckgo, tavily]
        max_results: 25
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
    - id: experiment_design
      kind: llm_chat
      depends_on: [paper_preferences, source_pack]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON')"
      with:
        system: "You design rigorous, falsifiable experiments. You also decide how many figures and tables the paper needs based on the target page budget, the research questions, and the analysis dimensions — do not over- or under-provision."
        task: |
          Design the experiments and supporting figures/tables for this
          paper. The design must be tight enough that downstream LaTeX
          generation can render placeholder figure/table environments
          straight from your output.

          Paper facts:
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}, MODE: {{ inputs.collected.paper_collect.paper_mode }}, PAGES: {{ inputs.collected.paper_collect.target_length_pages }}

          Preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Source pack (cite keys must come from here):
          {{ outputs.source_pack | truncate(6000) }}

          Provisioning rules (you decide the actual count within these):
          - target ≤8 pages    → 1–2 figures, 0–1 tables
          - target 9–14 pages  → 2–4 figures, 1–2 tables
          - target 15–24 pages → 4–6 figures, 2–3 tables
          - target ≥25 pages   → 6–10 figures, 3–5 tables
          Every figure/table MUST trace to a research question or an
          analysis dimension. Do not invent purely decorative figures.

          Reply with EXACTLY this structure (verbatim section headers, no
          markdown fences):

          RESEARCH_QUESTIONS:
            - id: RQ1
              question: <one sentence>
            - id: RQ2
              question: <one sentence>
            - id: RQ3
              question: <one sentence>

          HYPOTHESES:
            - id: H1; supports: RQ1; statement: <one sentence>
            - id: H2; supports: RQ2; statement: <one sentence>

          VARIABLES:
            independent: <list>
            dependent: <list>
            controlled: <list>

          DATASETS:
            - name; size; split; license/source; rationale

          BASELINES:
            - name; rationale; cite_key (from source_pack); ablation_relationship

          METRICS:
            - name; definition; supports: RQ#

          FIGURE_PLAN:
            - id: fig1
              type: <line|bar|scatter|heatmap|violin|timeline|cdf|box|matrix>
              x_axis: <semantic + unit>
              y_axis: <semantic + unit>
              comparison_groups: <list>
              supports: <RQ#|H#>
              caption_hint: <short, factual>
            - id: fig2
              ... (repeat per provisioning rules)

          TABLE_PLAN:
            - id: tab1
              columns: <list of column headers>
              rows_shape: <e.g. "one row per baseline + ours + 2 ablations">
              supports: <RQ#|H#>
              caption_hint: <short, factual>
            - id: tab2
              ... (repeat per provisioning rules)

          ANALYSIS_DIMENSIONS:
            - dimension: performance; figures: [fig1]; tables: [tab1]; coverage_note: <why this matters>
            - dimension: ablation; figures: [fig2]; tables: [tab2]; coverage_note: <...>
            - dimension: sensitivity_or_robustness; figures: [...]; tables: [...]; coverage_note: <...>
            - dimension: efficiency; figures: [...]; tables: [...]; coverage_note: <...>
            - dimension: failure_analysis_or_qualitative; figures: [...]; tables: [...]; coverage_note: <...>

          Strict rules:
          - Every figure/table id appears in at least one ANALYSIS_DIMENSIONS row.
          - Every RESEARCH_QUESTION is supported by ≥1 figure AND/OR ≥1 table.
          - cite_key fields must reference IDs that exist in source_pack;
            do not invent new ref keys here.
    - id: figure_placeholders
      kind: llm_chat
      depends_on: [experiment_design]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON')"
      with:
        system: "You render LaTeX placeholder figure environments from a structured figure plan. Output is pure LaTeX, ready to inline into a manuscript."
        task: |
          For EACH figure listed in FIGURE_PLAN below, emit one LaTeX
          ``figure`` environment. Use ``\fbox{\parbox{0.8\linewidth}{...}}``
          as the placeholder body — DO NOT use ``\includegraphics``
          because no PDFs exist yet.

          Body of each placeholder MUST list:
            * the figure's id (fig1, fig2, …)
            * the chart type
            * x_axis / y_axis labels with units
            * comparison_groups
            * RQ/H it supports

          Caption must come from caption_hint verbatim (escape LaTeX
          specials). Label MUST be ``\label{fig:<id>}`` so analysis_outline
          and final_manuscript_package can ``\ref{fig:<id>}`` them.

          Experiment design:
          {{ outputs.experiment_design | truncate(8000) }}

          Reply with ONLY the concatenated LaTeX figure environments,
          one per FIGURE_PLAN entry, separated by a blank line. No
          preamble, no markdown, no commentary. Wrap the entire block
          between sentinel comments so downstream sanitizer can locate
          it:

          % BEGIN_FIGURE_PLACEHOLDERS
          \begin{figure}[t]
            \centering
            \fbox{\parbox{0.8\linewidth}{\centering\vspace{1em}
              \textbf{[Placeholder] fig1: line plot}\\
              x: training step (1k iter); y: validation accuracy (\%)\\
              groups: ours / baseline-A / baseline-B\\
              supports: RQ1
              \vspace{1em}}}
            \caption{<caption_hint>}
            \label{fig:fig1}
          \end{figure}

          \begin{figure}[t]
            ... (repeat per FIGURE_PLAN entry)
          \end{figure}
          % END_FIGURE_PLACEHOLDERS
    - id: table_placeholders
      kind: llm_chat
      depends_on: [experiment_design]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON')"
      with:
        system: "You render LaTeX placeholder table environments from a structured table plan. Output is pure LaTeX, ready to inline into a manuscript."
        task: |
          For EACH table listed in TABLE_PLAN below, emit one LaTeX
          ``table`` environment with a ``tabular`` body. Use ``---`` or
          ``<TBD>`` for cells (DO NOT fabricate numbers). Use booktabs
          (``\toprule``, ``\midrule``, ``\bottomrule``) for clean spacing.

          Header row comes from TABLE_PLAN columns; row labels come from
          rows_shape (expand the shape into concrete row names like
          "Baseline-A", "Baseline-B", "Ours", "Ours w/o module X", …).
          Caption is caption_hint verbatim. Label MUST be
          ``\label{tab:<id>}``.

          Experiment design:
          {{ outputs.experiment_design | truncate(8000) }}

          Reply with ONLY the concatenated LaTeX table environments,
          one per TABLE_PLAN entry, between sentinel comments:

          % BEGIN_TABLE_PLACEHOLDERS
          \begin{table}[t]
            \centering
            \begin{tabular}{lccc}
              \toprule
              Method & Acc & F1 & Latency \\
              \midrule
              Baseline-A & --- & --- & --- \\
              Baseline-B & --- & --- & --- \\
              Ours       & --- & --- & --- \\
              \bottomrule
            \end{tabular}
            \caption{<caption_hint>}
            \label{tab:tab1}
          \end{table}
          ... (repeat per TABLE_PLAN entry)
          % END_TABLE_PLACEHOLDERS
    - id: analysis_outline
      kind: llm_chat
      depends_on: [experiment_design, figure_placeholders, table_placeholders]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON')"
      with:
        system: "You design analysis-chapter outlines that bind every figure/table to a claim and an analysis dimension."
        task: |
          Produce the Analysis chapter outline. Each subsection must
          ``\ref{fig:...}`` or ``\ref{tab:...}`` AT LEAST ONE artefact
          you actually have (do not reference figures/tables that don't
          exist in the placeholders below). Cover every ANALYSIS_DIMENSION
          from experiment_design.

          Experiment design:
          {{ outputs.experiment_design | truncate(8000) }}

          Figure placeholders (label IDs you may \ref):
          {{ outputs.figure_placeholders | truncate(3000) }}

          Table placeholders (label IDs you may \ref):
          {{ outputs.table_placeholders | truncate(3000) }}

          PAPER_MODE depth control:
          - FULL_MANUSCRIPT: 1 subsection per analysis dimension; each
            with potential_findings (3 bullets) + threats_to_validity
            (1–2 bullets).
          - COMPACT_SKELETON: 1 subsection per dimension; potential_findings
            (1 bullet); skip threats_to_validity.

          Reply in this exact shape between sentinels:

          % BEGIN_ANALYSIS_OUTLINE
          \subsection{Performance}
          \label{sec:analysis-performance}
          References: \ref{fig:fig1}, \ref{tab:tab1}.
          Potential findings:
          \begin{itemize}
            \item ...
          \end{itemize}
          Threats to validity:
          \begin{itemize}
            \item ...
          \end{itemize}

          \subsection{Ablation}
          ... (repeat per ANALYSIS_DIMENSION)
          % END_ANALYSIS_OUTLINE
    - id: outline
      kind: llm_chat
      depends_on: [source_pack, experiment_design]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You design long-form LaTeX paper outlines with citation plans."
        task: |
          Create a paper outline matching TARGET_PAGES from paper_preferences
          research-paper outline with enough section depth for a substantial
          manuscript. Every section must name planned cite keys from the
          bibliography. Tie the Method section to experiment_design's
          variables/datasets/baselines and the Results section to the
          figure/table plan (by id).

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Source pack:
          {{ outputs.source_pack | truncate(6000) }}

          Experiment design:
          {{ outputs.experiment_design | truncate(6000) }}

          Cite keys hint:
          {{ outputs.refbib | truncate(8000) }}
    - id: citation_plan
      kind: llm_chat
      depends_on: [outline, source_pack, refbib]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You plan citation placement for clean BibTeX/LaTeX manuscripts. You ONLY use cite keys that exist in the provided bibliography — never invent keys."
        task: |
          Build a citation plan that uses at least 20 distinct citation keys
          when the bibliography provides them. Use only keys that appear in
          the BibTeX below (every key must be present verbatim — verify by
          string match before you write it). Attach citations to claims,
          not paragraphs in bulk.

          Topic and mode:
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}, MODE: {{ inputs.collected.paper_collect.paper_mode }}, PAGES: {{ inputs.collected.paper_collect.target_length_pages }}

          Outline:
          {{ outputs.outline | truncate(6000) }}

          Source pack:
          {{ outputs.source_pack | truncate(8000) }}

          Bibliography (authoritative — cite keys MUST come from here):
          {{ outputs.refbib | truncate(8000) }}
    # ─── Plan→Write→Unify (FULL_MANUSCRIPT mode only) ──────────────────
    # COMPACT_SKELETON / REPAIR_EXISTING still use the single-shot
    # `final_manuscript_package` step further below; this branch is
    # the section-by-section flow for 10+/20+ page papers that hit
    # the LLM single-call token cap.
    - id: writing_plan
      kind: llm_chat
      depends_on: [paper_preferences, outline, citation_plan, experiment_design, figure_placeholders, table_placeholders, analysis_outline, refbib]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You build a writing blueprint for a long-form academic manuscript. The blueprint is consumed verbatim by per-section authors; precision matters more than prose."
        task: |
          Synthesize the upstream planning outputs into a single
          authoritative WRITING_PLAN that every section author must
          obey. Lock terminology, notation, claim mapping, and
          per-section length budget BEFORE any prose is written.

          Paper facts:
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}
          MODE: {{ inputs.collected.paper_collect.paper_mode }}
          LANGUAGE: {{ inputs.collected.paper_collect.language }}
          TARGET_PAGES: {{ inputs.collected.paper_collect.target_length_pages }}
          AUDIENCE: {{ inputs.collected.paper_collect.audience }}

          Preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Outline:
          {{ outputs.outline | truncate(6000) }}

          Experiment design:
          {{ outputs.experiment_design | truncate(6000) }}

          Citation plan:
          {{ outputs.citation_plan | truncate(6000) }}

          Bibliography (cite keys MUST come from here):
          {{ outputs.refbib | truncate(4000) }}

          Figure placeholders (IDs only):
          {{ outputs.figure_placeholders | truncate(1500) }}

          Table placeholders (IDs only):
          {{ outputs.table_placeholders | truncate(1500) }}

          Length budget rules:
          - target_pages 10 → roughly 4500 words total
          - target_pages 15 → roughly 7000 words total
          - target_pages 20 → roughly 9500 words total
          - target_pages 30 → roughly 14000 words total
          Allocate words across sections roughly: 5% abstract, 18%
          introduction, 12% related_work, 22% method, 24% experiments,
          12% discussion, 7% conclusion. Tune ±20% based on contributions.

          Return EXACTLY this structure (no preamble, no markdown headings):

          TITLE:
          <final paper title, ≤16 words>

          ABSTRACT_DRAFT:
          <120-220 word draft abstract — section authors may polish but
          may not change claims/numbers>

          NARRATIVE_ARC:
          - thesis: <one sentence>
          - story_beats:
              1. <intro beat>
              2. <related-work positioning>
              3. <method core idea>
              4. <experimental verification>
              5. <discussion+conclusion takeaway>

          KEY_CLAIMS:
          - C1: <one sentence, must be defensible by an experiment>
          - C2: ...
          - ...
          - Cn: ... (5-8 total)

          NOTATION_LOCK:
          - symbol: $\theta$  meaning: model parameters
          - symbol: $\mathcal{D}$  meaning: dataset
          - (list every symbol that will appear in math)

          TERMINOLOGY_LOCK:
          - "ours" (proposed method)  forbidden_aliases: ["our method", "the proposed", "本文方法", "the method"]
          - "DPR" (baseline)  forbidden_aliases: ["dpr", "Dpr"]
          - ... (every named entity that appears more than once)

          PER_SECTION_BLUEPRINT:
            abstract:
              target_words: <int>
              key_claims: [C1, C2, ...]
              cite_keys: []           # abstract never cites
              figures: []
              must_mention: [TITLE, headline_result_number]
            introduction:
              target_words: <int>
              key_claims: [C1, C2]
              cite_keys: [ref_x, ref_y, ...]   # from citation_plan
              figures: []
              structure: [motivation, problem, contributions]
              contributions_count: <int>
            related_work:
              target_words: <int>
              key_claims: []
              cite_keys: [ref_x, ...]
              figures: []
              structure: [survey by axis]
            method:
              target_words: <int>
              key_claims: [C3, C4]
              cite_keys: [...]
              figures: [fig1, ...]
              tables: []
              structure: [overview → component A → component B → algorithm box]
              notation_introduced: [θ, f_φ, ...]
            experiments:
              target_words: <int>
              key_claims: [C5, C6]
              cite_keys: [...]
              figures: [fig2, ...]
              tables: [tab1, ...]
              structure: [setup → main results → ablations]
              must_include_baselines: [...]
            discussion:
              target_words: <int>
              key_claims: [C7]
              cite_keys: [...]
              figures: []
              structure: [insights → limitations → threats_to_validity]
            conclusion:
              target_words: <int>
              key_claims: [C1-Cn 重申]
              cite_keys: []
              figures: []
              must_call_back_to_abstract: yes

          CROSS_SECTION_DEPENDENCIES:
          - method.NOTATION_LOCK symbols MUST be reused verbatim in experiments + discussion
          - intro.contributions_count MUST equal method.structure step count
          - abstract.headline_result_number == experiments.main_result_number

          WRITING_VOICE:
          - tense: <e.g. "we present / we observe", active>
          - perspective: <e.g. third-person except contributions list>
          - formality: academic; no contractions, no marketing language
          - language: {{ inputs.collected.paper_collect.language }}
    - id: section_abstract
      kind: agent
      skill: paper-section-author
      depends_on: [writing_plan]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        task: |
          You are writing the ABSTRACT section. Follow the writing plan
          and produce a single dense paragraph 4-6 sentences covering
          problem → approach → key result → significance.

          section: abstract
          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan:
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint:
          {{ outputs.refbib | truncate(2000) }}

          Output rules:
          - Use \begin{abstract} ... \end{abstract}.
          - Do not include \cite{...}.
          - Match TERMINOLOGY_LOCK and NOTATION_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.abstract.target_words
          - Only output the LaTeX fragment. No commentary, no fences.
    - id: section_introduction
      kind: agent
      skill: paper-section-author
      depends_on: [writing_plan, section_abstract]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        task: |
          You are writing the INTRODUCTION section.

          section: introduction
          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          previous_section_tail (last paragraphs of the abstract):
          {{ outputs.section_abstract | truncate(2000) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan (your assigned cite keys are listed under introduction:):
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint (only these keys exist in the bibliography):
          {{ outputs.refbib | truncate(2000) }}

          Output rules:
          - Start with \section{Introduction}.
          - Structure: motivation → problem → prior-work clusters → gap →
            our contributions (numbered \begin{enumerate}) → paper roadmap.
          - Use only cite keys assigned to introduction in citation_plan,
            and only keys present in cite_keys_hint.
          - Match TERMINOLOGY_LOCK and NOTATION_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.introduction.target_words.
          - Output ONLY the LaTeX fragment for this section. No fences.
    - id: section_related_work
      kind: llm_chat
      depends_on: [writing_plan, section_introduction]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You author the Related Work section of an academic paper as a pure LaTeX fragment. NEVER invent cite keys."
        task: |
          Write the RELATED WORK section.

          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          previous_section_tail (last paragraphs of the introduction):
          {{ outputs.section_introduction | truncate(2000) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan (your assigned cite keys are listed under related_work:):
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint (only these keys exist in the bibliography):
          {{ outputs.refbib | truncate(2500) }}

          Output rules:
          - Start with \section{Related Work}.
          - Survey by 2-4 thematic axes (e.g. efficiency / fidelity /
            agentic / dataset construction). Use \subsection for each.
          - Cite from your assigned keys; do not introduce new claims.
          - Do NOT include figures/tables here.
          - Match TERMINOLOGY_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.related_work.target_words.
          - Output ONLY the LaTeX fragment. No fences, no preamble.
    - id: section_method
      kind: agent
      skill: paper-section-author
      depends_on: [writing_plan, section_related_work, figure_placeholders]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        task: |
          You are writing the METHOD section.

          section: method
          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          previous_section_tail (last paragraphs of related work):
          {{ outputs.section_related_work | truncate(2000) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan:
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint:
          {{ outputs.refbib | truncate(2500) }}

          figure_placeholders (you may reference these via \ref{fig:<id>} when relevant):
          {{ outputs.figure_placeholders | truncate(2000) }}

          Output rules:
          - Start with \section{Method}.
          - Use \subsection{Setup}, \subsection{Algorithm} (or {Approach}),
            \subsection{Instrumentation}, and \subsection{Baselines}.
          - Introduce notation per writing_plan.NOTATION_LOCK
            (every symbol used later in experiments/discussion MUST
            be defined here).
          - You may inline ONE figure environment from figure_placeholders
            that supports method exposition; reference it via \ref{fig:<id>}.
          - Match TERMINOLOGY_LOCK / NOTATION_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.method.target_words.
          - Output ONLY the LaTeX fragment. No fences.
    - id: section_experiments
      kind: agent
      skill: paper-section-author
      depends_on: [writing_plan, section_method, figure_placeholders, table_placeholders]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        task: |
          You are writing the EXPERIMENTS / RESULTS section. Use the
          paper-section-author "results" contract.

          section: results
          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          previous_section_tail (last paragraphs of method):
          {{ outputs.section_method | truncate(2500) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan:
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint:
          {{ outputs.refbib | truncate(2500) }}

          figure_placeholders (inline ALL remaining figures here):
          {{ outputs.figure_placeholders | truncate(4000) }}

          table_placeholders (inline ALL tables here):
          {{ outputs.table_placeholders | truncate(4000) }}

          Output rules:
          - Start with \section{Experiments}.
          - Inline EVERY figure and table from figure_placeholders /
            table_placeholders that has not already been inlined in method.
          - Reference via \ref{fig:<id>} and \ref{tab:<id>}.
          - Structure: \subsection{Setup} → \subsection{Main Results} →
            \subsection{Ablations} → \subsection{Sensitivity}.
          - Headline result number MUST equal writing_plan.ABSTRACT_DRAFT's
            headline number.
          - Use ONLY notation/terminology locked in writing_plan.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.experiments.target_words.
          - Output ONLY the LaTeX fragment. No fences.
    - id: section_discussion
      kind: agent
      skill: paper-section-author
      depends_on: [writing_plan, section_experiments, analysis_outline]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        task: |
          You are writing the DISCUSSION section.

          section: discussion
          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          previous_section_tail (last paragraphs of experiments):
          {{ outputs.section_experiments | truncate(2500) }}

          outline:
          {{ outputs.outline | truncate(3000) }}

          citation_plan:
          {{ outputs.citation_plan | truncate(3000) }}

          cite_keys_hint:
          {{ outputs.refbib | truncate(2500) }}

          analysis_outline (use this as the structural blueprint):
          {{ outputs.analysis_outline | truncate(4000) }}

          Output rules:
          - Start with \section{Discussion}.
          - Inline the analysis_outline subsections verbatim where they
            fit, but expand each with 1-2 paragraphs of substantive
            commentary referencing concrete experiment results.
          - End the section with explicit \subsection{Limitations} and
            \subsection{Threats to Validity}.
          - Match TERMINOLOGY_LOCK / NOTATION_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.discussion.target_words.
          - Output ONLY the LaTeX fragment.
    - id: section_conclusion
      kind: llm_chat
      depends_on: [writing_plan, section_discussion, section_abstract]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You author the Conclusion section of an academic paper as a pure LaTeX fragment."
        task: |
          Write the CONCLUSION section. Must close the loop on the abstract.

          writing_plan:
          {{ outputs.writing_plan | truncate(8000) }}

          abstract (the conclusion must echo its claims):
          {{ outputs.section_abstract | truncate(1500) }}

          previous_section_tail (discussion ending):
          {{ outputs.section_discussion | truncate(2000) }}

          Output rules:
          - Start with \section{Conclusion}.
          - 2-3 paragraphs covering: 1) restated thesis + headline result,
            2) key contributions reiterated, 3) future-work pointer.
          - No new claims, no new figures, no \cite{}.
          - Match TERMINOLOGY_LOCK exactly.
          - target_words from writing_plan.PER_SECTION_BLUEPRINT.conclusion.target_words.
          - Output ONLY the LaTeX fragment.
    - id: assemble_manuscript_tex
      kind: tool_call
      tool: exec_command
      tool_allowlist: [exec_command]
      depends_on: [writing_plan, section_abstract, section_introduction, section_related_work, section_method, section_experiments, section_discussion, section_conclusion, refbib]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      tool_args:
        # Concatenate all section outputs into a full LaTeX document
        # wrapped with \documentclass + preamble + \begin{document} +
        # \end{document}. Emit the canonical MANUSCRIPT_TEX: /
        # REFERENCES_BIB: envelope so downstream citation_map /
        # compile_pdf parse the same shape as the old single-shot path.
        command: |
          python3 - <<'PY'
          import os, re, sys
          # Helper to strip ```latex fences and surrounding markdown.
          def clean(text):
              text = re.sub(r'^```(?:latex|tex)?\s*\n', '', text or '', flags=re.MULTILINE)
              text = re.sub(r'\n```\s*$', '', text)
              return text.strip()
          sections = {
              'abstract':     os.environ.get('SEC_ABSTRACT', ''),
              'introduction': os.environ.get('SEC_INTRO', ''),
              'related_work': os.environ.get('SEC_RELATED', ''),
              'method':       os.environ.get('SEC_METHOD', ''),
              'experiments':  os.environ.get('SEC_EXPERIMENTS', ''),
              'discussion':   os.environ.get('SEC_DISCUSSION', ''),
              'conclusion':   os.environ.get('SEC_CONCLUSION', ''),
          }
          for k in list(sections):
              sections[k] = clean(sections[k])
          bib = os.environ.get('BIB_TEXT', '').strip()
          # Build preamble — load xeCJK if any section has CJK
          any_cjk = any(re.search(r'[一-鿿]', v) for v in sections.values())
          preamble = [
              r"\documentclass{article}",
              r"\usepackage{xeCJK}" if any_cjk else r"% no CJK",
              r"\usepackage{graphicx}",
              r"\usepackage{booktabs}",
              r"\usepackage{amsmath,amssymb}",
              r"\usepackage{hyperref}",
              r"\usepackage{geometry}",
              r"\geometry{margin=2.5cm}",
              r"\title{From writing_plan TITLE — see paper.tex header}",
              r"\author{OpenSquilla meta-paper-write}",
              r"\date{\today}",
              r"\begin{document}",
              r"\maketitle",
          ]
          body_parts = [
              sections['abstract'],     # \begin{abstract}...\end{abstract}
              sections['introduction'], # \section{Introduction}...
              sections['related_work'],
              sections['method'],
              sections['experiments'],
              sections['discussion'],
              sections['conclusion'],
          ]
          tail = [
              r"\bibliographystyle{plain}",
              r"\bibliography{references}",
              r"\end{document}",
          ]
          tex = '\n'.join(preamble) + '\n\n' + '\n\n'.join(p for p in body_parts if p) + '\n\n' + '\n'.join(tail)
          print('MANUSCRIPT_TEX:')
          print(tex)
          print()
          print('REFERENCES_BIB:')
          print(bib if bib else '% no verified references')
          print()
          print('COMPILE_NOTES:')
          print('- assembled section-by-section via paper-section-author')
          print(f'- sections present: {", ".join(k for k, v in sections.items() if v)}')
          print(f'- total chars: {sum(len(v) for v in sections.values())}')
          PY
        workdir: "{{ inputs.workspace_dir }}"
        timeout: 30
        env:
          SEC_ABSTRACT:    "{{ outputs.section_abstract }}"
          SEC_INTRO:       "{{ outputs.section_introduction }}"
          SEC_RELATED:     "{{ outputs.section_related_work }}"
          SEC_METHOD:      "{{ outputs.section_method }}"
          SEC_EXPERIMENTS: "{{ outputs.section_experiments }}"
          SEC_DISCUSSION:  "{{ outputs.section_discussion }}"
          SEC_CONCLUSION:  "{{ outputs.section_conclusion }}"
          BIB_TEXT:        "{{ outputs.refbib }}"
    - id: consistency_pass
      kind: llm_chat
      depends_on: [writing_plan, assemble_manuscript_tex]
      when: "inputs.collected.paper_collect.paper_mode == 'FULL_MANUSCRIPT'"
      with:
        system: "You are the consistency editor. You only fix term/notation/number drift across an academic manuscript. You do NOT add new content, new claims, new citations, or new figures. Pure LaTeX in, pure LaTeX out."
        task: |
          Scan the assembled manuscript for drift versus the writing plan
          and produce a corrected copy. Do not invent content; only
          unify what already exists.

          Drift to fix:
          1. Terminology: any synonym variant of a TERMINOLOGY_LOCK term
             gets replaced with the locked spelling.
          2. Notation: any math symbol that disagrees with NOTATION_LOCK
             gets normalized.
          3. Numbers: if abstract / experiments / discussion mention the
             same headline metric with different values, pick the
             experiments-section value (authoritative) and propagate.
          4. Cite keys: ensure every \cite{...} key exists in the
             REFERENCES_BIB block. Replace stray keys with the closest
             match by ref# proximity; if none plausible, replace with
             [citation needed].
          5. Section ordering: keep abstract → intro → related → method →
             experiments → discussion → conclusion.

          Writing plan (authoritative):
          {{ outputs.writing_plan | truncate(8000) }}

          Assembled draft (input):
          {{ outputs.assemble_manuscript_tex | truncate(15000) }}

          Output EXACTLY:
          MANUSCRIPT_TEX:
          <corrected LaTeX, full \documentclass … \end{document} block>

          REFERENCES_BIB:
          <verbatim copy of the REFERENCES_BIB block from the input>

          COMPILE_NOTES:
          - consistency_pass_changes: <one line per fix applied, OR "none">

    - id: final_manuscript_package
      kind: llm_chat
      depends_on: [paper_collect, outline, citation_plan, refbib, figure_placeholders, table_placeholders, analysis_outline]
      when: "inputs.collected.paper_collect.paper_mode in ('COMPACT_SKELETON', 'REPAIR_EXISTING')"
      with:
        system: "You write clean LaTeX manuscripts. Output only the requested manuscript package. NEVER invent cite keys — every \\cite{...} you emit MUST exist verbatim in REFERENCES_BIB below."
        task: |
          Draft a full manuscript package. The default output must be clean
          LaTeX-ready paper text, not planning notes. Do not include markdown
          fences, chat commentary, progress notes, or tool logs.

          Paper mode:
          TOPIC: {{ inputs.collected.paper_collect.topic | xml_escape }}, MODE: {{ inputs.collected.paper_collect.paper_mode }}, PAGES: {{ inputs.collected.paper_collect.target_length_pages }}

          Mode behavior:
          - FULL_MANUSCRIPT: produce enough substance for
            TARGET_PAGES from paper_preferences as compiled
            pages (default 10+ compiled pages), at least 20 references when
            provided, and at least 20 distinct citation keys used across
            abstract, introduction, related work, method, results, discussion,
            limitations, and conclusion.
          - COMPACT_SKELETON: produce a compact LaTeX-ready manuscript
            skeleton with section goals, planned citations, and expansion
            notes; do not pretend it is a 10+ page finished paper. For this
            mode, the final package MUST include an explicit manuscript plan,
            a 10+ page expansion plan, limitations/threats-to-validity, and
            at least 20 reference placeholders when verified BibTeX entries
            are unavailable. Keep the compact package short enough that all
            required sections are visible before any evaluator truncation:
            put the plan and expansion plan before the LaTeX skeleton, and
            keep MANUSCRIPT_TEX under 2,500 words.
          - REPAIR_EXISTING: return a repaired clean LaTeX package focused on
            citation integrity, structure, and removal of process text.
          - COMPILE_ONLY: return a compile handoff package and blockers only;
            do not invent missing manuscript body.

          CITATION CONTRACT (load-bearing):
          - DO NOT invent cite keys. Use ONLY keys that appear verbatim in
            REFERENCES_BIB below.
          - DO NOT cite a key that REFERENCES_BIB does not contain.
          - Every claim that needs evidence MUST cite at least one key from
            REFERENCES_BIB.
          - Distribute citations: avoid citing the same key 10+ times.
          - If REFERENCES_BIB is empty or lacks enough verified entries, do
            not emit \cite{...}. Use visible placeholders such as
            [REF-01 needed: agent benchmark survey] in the LaTeX text and
            list them under REFERENCE_PLACEHOLDERS instead. Placeholder
            references are safer than fabricated BibTeX.

          FIGURE/TABLE CONTRACT:
          - Inline the figure_placeholders block verbatim into Results.
          - Inline the table_placeholders block verbatim into Method or
            Results (split by purpose).
          - Inline the analysis_outline block verbatim into Discussion.
          - Reference figures/tables via \\ref{fig:<id>} and \\ref{tab:<id>}
            where they appear in the body; never reference an id not present
            in the placeholders.

          Paper preferences:
          {{ outputs.paper_preferences | truncate(2000) }}

          Outline:
          {{ outputs.outline | truncate(8000) }}

          Citation plan:
          {{ outputs.citation_plan | truncate(8000) }}

          Figure placeholders (inline this verbatim somewhere in Results):
          {{ outputs.figure_placeholders | truncate(4000) }}

          Table placeholders (inline this verbatim in Method/Results):
          {{ outputs.table_placeholders | truncate(4000) }}

          Analysis outline (inline this verbatim in Discussion):
          {{ outputs.analysis_outline | truncate(4000) }}

          Bibliography (cite keys MUST come from here):
          {{ outputs.refbib | truncate(8000) }}

          CRITICAL OUTPUT CONTRACT (load-bearing — the downstream
          compile_pdf step parses these markers literally):

          - The MANUSCRIPT_TEX section is MANDATORY and MUST come first.
            It MUST start with the literal token `MANUSCRIPT_TEX:` on its
            own line, immediately followed by `\documentclass{article}`
            and end with `\end{document}`. Do NOT wrap in ```latex
            fences. Do NOT prefix with markdown headings.
          - If you find yourself running out of tokens, shorten section
            bodies — DO NOT omit MANUSCRIPT_TEX. A short complete
            \documentclass…\end{document} block is FAR more useful than
            a long MANUSCRIPT_PLAN with no LaTeX.
          - REFERENCES_BIB is the second mandatory section. Use
            `REFERENCES_BIB:` on its own line followed by BibTeX entries.
            If the bibliography is empty, output `REFERENCES_BIB:`
            followed by a single line `% no verified references` (the
            \cite{} keys in MANUSCRIPT_TEX should then be visible
            placeholders, not BibTeX-keyed cites).

          Return EXACTLY in this order (no preamble, no markdown headings):

          MANUSCRIPT_TEX:
          \documentclass{article}
          \usepackage{xeCJK}
          \usepackage{graphicx}
          \usepackage{booktabs}
          \usepackage{amsmath}
          \usepackage{hyperref}
          \title{...}
          \author{...}
          \date{\today}
          \begin{document}
          \maketitle
          \begin{abstract}...\end{abstract}
          \section{Introduction}...
          \section{Related Work}...
          \section{Method}...
          \section{Experiments}...
          (inline the figure_placeholders, table_placeholders, and
          analysis_outline blocks verbatim where appropriate)
          \section{Discussion}...
          \section{Limitations}...
          \section{Conclusion}...
          \bibliographystyle{plain}
          \bibliography{references}
          \end{document}

          REFERENCES_BIB:
          <BibTeX entries copied verbatim from the provided bibliography —
          only the entries actually cited in MANUSCRIPT_TEX. If empty,
          output a single `% no verified references` line.>

          MANUSCRIPT_PLAN:
          - (optional) section-by-section plan with target pages and
            contribution. Skip this section if MANUSCRIPT_TEX is already
            tight on tokens.

          REFERENCE_PLACEHOLDERS:
          - (optional) placeholder reference notes if REFERENCES_BIB is
            empty or sparse.

          COMPILE_NOTES:
          - <short note about figure/reference assumptions>
    - id: citation_map
      kind: llm_chat
      depends_on: [final_manuscript_package, refbib]
      when: "inputs.collected.paper_collect.paper_mode != 'COMPILE_ONLY'"
      with:
        system: "You audit citation provenance. You read manuscript LaTeX and a BibTeX file and emit a strict markdown table. NEVER invent titles or URLs — copy fields verbatim from the BibTeX block."
        task: |
          Parse every \\cite{key} occurrence in MANUSCRIPT below, then
          match each key against REFERENCES_BIB. Produce an exhaustive
          audit table.

          Manuscript:
          {% if outputs.consistency_pass %}{{ outputs.consistency_pass | truncate(12000) }}{% elif outputs.assemble_manuscript_tex %}{{ outputs.assemble_manuscript_tex | truncate(12000) }}{% else %}{{ outputs.final_manuscript_package | truncate(12000) }}{% endif %}

          References bib (authoritative source for title/url/eprint/doi):
          {{ outputs.refbib | truncate(8000) }}

          Reply with this exact structure (no preamble):

          CITATION_MAP:

          | Cite Key | Cited Times | Title | URL / DOI / arXiv | Source Quality |
          |---|---|---|---|---|
          | ref1 | 5 | Attention Is All You Need | https://arxiv.org/abs/1706.03762 (arXiv:1706.03762) | STRONG |
          | ref7 | 2 | Some blog | https://medium.com/... | WEAK |
          | ref42 | 1 | (MISSING IN BIB) | — | INVALID |
          | refX | 0 | (declared but never cited) | https://... | UNUSED |

          Source Quality buckets:
          - STRONG: arxiv.org / aclanthology.org / dl.acm.org / openreview.net /
                    ieee.org / nature.com / science.org / biorxiv.org / pnas.org /
                    any URL with a real DOI or arXiv eprint identifier
          - OK:     other .edu / .gov / .org venues, journal portals
          - WEAK:   blog / medium / wikipedia / github / stackoverflow /
                    social media / news / generic .com
          - INVALID: cite key referenced in MANUSCRIPT but absent from REFERENCES_BIB
          - UNUSED:  bib entry declared but no \\cite{...} occurrence in MANUSCRIPT

          Strict rules:
          - Read the URL from the howpublished/url/eprint/doi BibTeX fields
            of the matching entry — do not invent.
          - If a row is INVALID or WEAK or UNUSED, add a one-line bullet
            after the table explaining what to do (replace, drop, find a
            real arxiv/doi source).

          After the table, emit a one-line summary:
          SUMMARY: total_cite_keys=<N>, strong=<n>, ok=<n>, weak=<n>, invalid=<n>, unused=<n>
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
          - target TARGET_PAGES from paper_preferences as compiled pages
          - substantial introduction, method, results, and discussion sections
          - no placeholder-only paragraphs (placeholder figures/tables ARE
            allowed and expected — only flag if the text body around them is
            also empty)

          Manuscript:
          {% if outputs.consistency_pass %}{{ outputs.consistency_pass | truncate(12000) }}{% elif outputs.assemble_manuscript_tex %}{{ outputs.assemble_manuscript_tex | truncate(12000) }}{% else %}{{ outputs.final_manuscript_package | truncate(12000) }}{% endif %}

          Citation plan:
          {{ outputs.citation_plan | truncate(4000) }}
    - id: citation_integrity_gate
      kind: llm_chat
      depends_on: [final_manuscript_package, citation_plan, refbib, citation_map]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON', 'REPAIR_EXISTING')"
      with:
        system: "You verify LaTeX/BibTeX citation integrity."
        task: |
          Validate citation integrity before LaTeX compilation.

          Requirements (LOAD-BEARING — block compilation if any fails):
          - at least 20 references in REFERENCES_BIB when sources allow it
          - at least 20 distinct citation keys used or planned in the body
          - NO citation keys absent from references.bib (citation_map column
            "INVALID" must be 0)
          - every cited entry MUST have a verifiable URL or DOI or arXiv
            eprint field in REFERENCES_BIB; entries with only howpublished
            text are degraded but acceptable; entries with no URL/DOI/eprint
            at all are blockers
          - no Source Quality == WEAK in citation_map for primary claims
            (introduction headline / method core / results headline);
            warn but do not block for related-work / motivation context
          - every major claim has nearby citation support or an explicit caveat

          Citation plan:
          {{ outputs.citation_plan | truncate(8000) }}

          Bibliography:
          {{ outputs.refbib | truncate(8000) }}

          Manuscript:
          {% if outputs.consistency_pass %}{{ outputs.consistency_pass | truncate(12000) }}{% elif outputs.assemble_manuscript_tex %}{{ outputs.assemble_manuscript_tex | truncate(12000) }}{% else %}{{ outputs.final_manuscript_package | truncate(12000) }}{% endif %}

          Citation audit table (read this — do NOT re-derive):
          {{ outputs.citation_map | truncate(4000) }}

          Reply with:
          INTEGRITY: <pass|warn|block>
          INVALID_COUNT: <int>
          WEAK_PRIMARY_COUNT: <int>
          UNUSED_COUNT: <int>
          BLOCKERS:
            - <blocker or none>
          WARNINGS:
            - <warning or none>
    - id: latex_sanitizer
      kind: llm_chat
      depends_on: [paper_length_gate, citation_integrity_gate]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON', 'REPAIR_EXISTING', 'COMPILE_ONLY')"
      with:
        system: "You sanitize LaTeX deliverables and reject process text."
        task: |
          Sanitize the final LaTeX package contract before compilation. Confirm
          that process commentary, markdown fences, chat preambles, debug logs,
          and non-paper text are absent from MANUSCRIPT_TEX and REFERENCES_BIB.
          Preserve valid LaTeX, CJK text, citations, figure references,
          placeholder figure/table blocks (\fbox + tabular), and section content.
          Reply with a concise readiness note and any blocking issue only.

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
    - id: compile_pdf
      kind: tool_call
      tool: exec_command
      tool_allowlist: [exec_command]
      depends_on: [latex_sanitizer]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON', 'REPAIR_EXISTING')"
      tool_args:
        # Runs the actual xelatex × bibtex × xelatex × 2 cycle so the
        # user gets a real PDF, not just LaTeX source. Extracts
        # MANUSCRIPT_TEX / REFERENCES_BIB from the final_manuscript_package
        # contract (passed via env var to dodge shell-escape hell).
        command: |
          python3 - <<'PY'
          import os, re, subprocess, sys
          from pathlib import Path

          pkg = os.environ.get('MANUSCRIPT_PKG', '')

          # 1. Try MANUSCRIPT_TEX: / REFERENCES_BIB: contract markers first.
          m = re.search(r'MANUSCRIPT_TEX:\s*(.+?)(?:REFERENCES_BIB:|COMPILE_NOTES:|\Z)', pkg, re.DOTALL)
          tex_body = m.group(1).strip() if m else ''
          mb = re.search(r'REFERENCES_BIB:\s*(.+?)(?:COMPILE_NOTES:|\Z)', pkg, re.DOTALL)
          bib = mb.group(1).strip() if mb else ''

          # 2. Fallback A: maybe LLM wrapped LaTeX in ```latex fences without the marker.
          if not tex_body:
              fenced = re.search(r'```(?:latex|tex)?\s*(\\documentclass[\s\S]+?\\end\{document\})', pkg)
              if fenced:
                  tex_body = fenced.group(1).strip()

          # 3. Fallback B: maybe there's a raw \documentclass…\end{document} block.
          if not tex_body:
              raw = re.search(r'(\\documentclass[\s\S]+?\\end\{document\})', pkg)
              if raw:
                  tex_body = raw.group(1).strip()

          # 4. Strip any leftover markdown fences from extracted bodies.
          tex_body = re.sub(r'^```(?:latex|tex)?\s*\n', '', tex_body)
          tex_body = re.sub(r'\n```\s*$', '', tex_body)

          # 5. If still empty, wrap whatever we got as a degraded skeleton so
          #    the user sees SOMETHING (and an explicit warning in the PDF).
          if not tex_body:
              snippet = pkg[:4000].replace('\\', r'\textbackslash{}')
              for ch in '{}#$%_&^~':
                  snippet = snippet.replace(ch, '\\' + ch)
              tex_body = (
                  r"\documentclass{article}" "\n"
                  r"\usepackage{xeCJK}" "\n"
                  r"\usepackage{geometry}\geometry{margin=2.5cm}" "\n"
                  r"\title{Degraded Output: MANUSCRIPT\_TEX block not provided by LLM}" "\n"
                  r"\author{meta-paper-write}" "\n"
                  r"\begin{document}\maketitle" "\n"
                  r"\section*{Warning}" "\n"
                  r"The LLM did not emit a \texttt{MANUSCRIPT\_TEX:} section. "
                  r"Raw output captured below for inspection." "\n\n"
                  r"\begin{verbatim}" "\n" + pkg[:4000] + "\n" r"\end{verbatim}" "\n"
                  r"\end{document}" "\n"
              )

          # 6. Auto-wrap if the LLM gave a body fragment but no \documentclass.
          if '\\documentclass' not in tex_body:
              tex_body = (
                  r"\documentclass{article}" "\n"
                  r"\usepackage{xeCJK}" "\n"
                  r"\usepackage{graphicx}\usepackage{booktabs}\usepackage{amsmath}\usepackage{hyperref}" "\n"
                  r"\begin{document}" "\n"
                  + tex_body + "\n"
                  r"\bibliographystyle{plain}" "\n"
                  r"\bibliography{references}" "\n"
                  r"\end{document}" "\n"
              )

          # 7. Auto-add xeCJK if the body contains CJK chars but doesn't load it.
          if re.search(r'[一-鿿]', tex_body) and 'xeCJK' not in tex_body:
              tex_body = tex_body.replace(
                  r'\documentclass{article}',
                  r'\documentclass{article}' + '\n' + r'\usepackage{xeCJK}',
                  1,
              )

          paper = Path('paper'); paper.mkdir(exist_ok=True)
          (paper / 'paper.tex').write_text(tex_body, encoding='utf-8')
          (paper / 'references.bib').write_text(bib, encoding='utf-8')

          logs = []
          for cmd in (
              ['xelatex','-interaction=nonstopmode','paper.tex'],
              ['bibtex','paper'],
              ['xelatex','-interaction=nonstopmode','paper.tex'],
              ['xelatex','-interaction=nonstopmode','paper.tex'],
          ):
              r = subprocess.run(cmd, cwd='paper', capture_output=True, text=True)
              logs.append(f"--- {' '.join(cmd)} (rc={r.returncode}) ---")

          pdf = (paper / 'paper.pdf').resolve()
          if pdf.is_file():
              log_text = (paper / 'paper.log').read_text(encoding='utf-8', errors='ignore') if (paper / 'paper.log').is_file() else ''
              pm = re.search(r'Output written on .+?\((\d+) pages?', log_text)
              pages = pm.group(1) if pm else '?'
              print(f'PDF_PATH: {pdf}')
              print(f'PDF_PAGES: {pages}')
              print(f'PDF_BYTES: {pdf.stat().st_size}')
              print(f'TEX_BYTES: {(paper / "paper.tex").stat().st_size}')
              print(f'BIB_BYTES: {(paper / "references.bib").stat().st_size}')
          else:
              tail = '\n'.join(logs[-3:])
              # Dump the last 80 lines of paper.log so the failure mode is visible.
              log_text = (paper / 'paper.log').read_text(encoding='utf-8', errors='ignore') if (paper / 'paper.log').is_file() else ''
              log_tail = '\n'.join(log_text.splitlines()[-80:])
              print(f'COMPILE_FAILED:\n{tail}\n\n=== paper.log tail ===\n{log_tail}')
              sys.exit(1)
          PY
        workdir: "{{ inputs.workspace_dir }}"
        timeout: 120
        env:
          MANUSCRIPT_PKG: "{% if outputs.consistency_pass %}{{ outputs.consistency_pass }}{% elif outputs.assemble_manuscript_tex %}{{ outputs.assemble_manuscript_tex }}{% else %}{{ outputs.final_manuscript_package }}{% endif %}"
    - id: publish_pdf
      kind: tool_call
      tool: publish_artifact
      tool_allowlist: [publish_artifact]
      depends_on: [compile_pdf]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON', 'REPAIR_EXISTING')"
      tool_args:
        path: "paper/paper.pdf"
        name: "paper.pdf"
        mime: "application/pdf"
    - id: deliver_paper
      kind: llm_chat
      depends_on: [final_manuscript_package, compile_pdf, publish_pdf, citation_map]
      when: "inputs.collected.paper_collect.paper_mode in ('FULL_MANUSCRIPT', 'COMPACT_SKELETON', 'REPAIR_EXISTING')"
      with:
        system: "You write a one-paragraph delivery note for a compiled academic paper. Output is concise — no LaTeX source, no markdown fences."
        task: |
          Produce the user-facing delivery message. Confirm the PDF
          is ready, name its location, page count, citation summary,
          and list any open warnings from the citation audit. Keep
          the message under 200 words. Reply in the same language as
          the user's original request.

          Original request:
          {{ inputs.user_message | xml_escape | truncate(400) }}

          PDF compile result (paths are absolute):
          {{ outputs.compile_pdf | truncate(800) }}

          Artifact publication result:
          {{ outputs.publish_pdf | truncate(800) }}

          Citation audit summary tail:
          {{ outputs.citation_map | truncate(2000) }}

          Format:
          📄 论文已生成 / Paper compiled

          - PDF: <absolute path or artifact id>
          - 页数 / Pages: <N>
          - 引用 / Citations: <total / strong / weak / invalid>
          - 备注 / Notes: <one line about figures, tables, analysis dimensions>

          If the audit shows INVALID > 0, prefix the message with
          "⚠️ 注意 / Warning: <N> 处引用未在 bib 中，建议重新生成" and list
          the offending cite keys.
---

# meta-paper-write (Meta-Skill)

Draft a long LaTeX manuscript by orchestrating paper-specific skills and
bounded LLM synthesis. The pipeline now leads with explicit experiment
design + placeholder figures/tables + citation provenance audit so the
deliverable can be reviewed for academic rigor, not just length.

DAG (in order):

1. **`paper_collect`** — extracts topic, mode, language, target length,
   audience, and reference count from the same turn without pausing for a
   form. Missing facts are marked as assumptions so first-pass paper
   requests complete inline.
2. **`paper_preferences`** — expand the collected facts into a planning
   contract.
3. **`search_papers`** — `multi-search-engine` query biased toward arXiv
   / ACL Anthology / ACM DL / OpenReview / IEEE / Nature / Science so
   the returned URLs translate into real bibliographic identifiers.
4. **`refbib`** — `paper-refbib-stub` now extracts ``eprint``/``doi``
   from arXiv/DOI URLs and tags each entry with ``note = {source: <domain>}``
   so downstream gates can classify provenance without re-fetching.
5. **`source_pack`** — curate references and enforce ≥20-source coverage.
6. **`experiment_design`** — **decides** how many figures and tables the
   paper needs based on RQs, hypotheses, analysis dimensions, and the
   target page budget. Every figure/table is tied to an RQ or analysis
   dimension; no decorative artefacts.
7. **`figure_placeholders`** — render LaTeX ``\fbox{\parbox{...}}``
   placeholder figure environments for each entry in FIGURE_PLAN. Zero
   matplotlib dependency.
8. **`table_placeholders`** — render LaTeX ``\begin{tabular}`` placeholder
   tables for each entry in TABLE_PLAN. Cells contain ``---``/``<TBD>``;
   no fabricated numbers.
9. **`analysis_outline`** — bind every figure/table id to a Discussion
   subsection that names potential findings + threats to validity, and
   covers every ANALYSIS_DIMENSION.
10. **`outline`** — paper outline that ties Method to experiment design
    and Results to the figure/table plan.
11. **`citation_plan`** — assigns concrete cite keys from `refbib` to
    claims; cannot invent keys.
12. **`final_manuscript_package`** — produces MANUSCRIPT_TEX with the
    figure/table/analysis blocks inlined verbatim, plus
    REFERENCES_BIB containing only the entries actually cited.
13. **`citation_map`** — strict markdown audit table:
    ``Cite Key | Cited Times | Title | URL/DOI/arXiv | Source Quality``
    with INVALID / UNUSED / WEAK detection. Inlined into the final
    deliverable AND queryable per-run via
    ``opensquilla skills meta runs show``.
14. **`paper_length_gate`** — page-count check (FULL_MANUSCRIPT only).
15. **`citation_integrity_gate`** — reads `citation_map` directly; blocks
    when INVALID > 0 or any primary claim cites a WEAK source.
16. **`latex_sanitizer`** — strips process text without rewriting the
    paper.
17. **`compile_latex`** — handoff note (COMPILE_ONLY mode).

Removed from the previous version:

- `paper_mode` (llm_classify) — superseded by `paper_collect`
- `experiment` (skill_exec → `paper-experiment-stub`, fake CSV) —
  superseded by `experiment_design` (real plan, not data). The
  bundled `paper-experiment-stub` skill was deleted with this rewrite.
- `plot` (skill_exec → `paper-plot-stub`, matplotlib line chart) —
  superseded by `figure_placeholders` (zero-dependency LaTeX). The
  bundled `paper-plot-stub` skill was deleted with this rewrite.

The default path intentionally returns `final_manuscript_package` instead
of running `latex-compile`. This avoids timeout and prevents process
text from being inserted into the paper. If the user explicitly asks
for a compiled PDF, run `latex-compile` as the second-stage artifact
step after inspecting the manuscript package.
