---
name: meta-web-research-to-report
description: "Use this meta-skill instead of answering directly when the current user asks for a source-backed web research deliverable: cited research report, market or technical briefing, decision memo with sources, or a researched writeup after web lookup. It uses multi-skill orchestration for preference inference, search/research, drafting, review, and optional export. Do not use it for generic summarization, academic manuscript writing, document-decision analysis, or isolated fact lookup that does not require a report."
kind: meta
meta_priority: 80
always: false
final_text_mode: "step:final_report_audit"
request_template:
  outcome: "Source-backed research report or decision memo with citations and tradeoffs."
  outcome_zh: "带来源引用、权衡和建议的研究报告或决策备忘录。"
  outcome_en: "Source-backed research report or decision memo with citations and tradeoffs."
  fields:
    - name: research_question
      label_zh: "研究问题"
      label_en: "Research question"
      required: true
    - name: output_format
      label_zh: "输出格式"
      label_en: "Output format"
      required: false
      default: "brief report or decision memo inferred from request"
      default_zh: "根据请求推断为简报、报告或决策备忘录"
      default_en: "brief report or decision memo inferred from request"
    - name: source_constraints
      label_zh: "来源限制"
      label_en: "Source constraints"
      required: false
    - name: time_window
      label_zh: "时间窗口"
      label_en: "Time window"
      required: false
    - name: audience
      label_zh: "受众"
      label_en: "Audience"
      required: false
      default: "decision maker or report reader"
      default_zh: "决策者或报告读者"
      default_en: "decision maker or report reader"
    - name: language
      label_zh: "输出语言"
      label_en: "Output language"
      required: false
      default: "match the user's language"
      default_zh: "跟随用户语言"
      default_en: "match the user's language"
  assumptions:
    - "Use current sources when browsing is available."
    - "Separate evidence, assumptions, and recommendations."
  assumptions_zh:
    - "浏览可用时使用当前来源。"
    - "区分证据、假设和建议。"
  assumptions_en:
    - "Use current sources when browsing is available."
    - "Separate evidence, assumptions, and recommendations."
output_contract:
  append_to_final_text: false
  required_sections:
    - "Key findings"
    - "Source-backed evidence"
    - "Tradeoffs and risks"
    - "Recommendation or synthesis"
    - "Unverified assumptions"
  assumptions:
    - "Currentness depends on browsing/source availability."
  unverified:
    - "Claims from inaccessible or paywalled sources."
  artifacts:
    - name: "research_report"
      required: false
eval_prompts:
  - name: "web-research-report-baseline"
    prompt: "Research a current product decision and produce a source-backed report with recommendation and assumptions."
    rubric:
      - "Key findings"
      - "Source-backed evidence"
      - "Tradeoffs and risks"
      - "Recommendation or synthesis"
      - "Unverified assumptions"
preference_keys:
  - preferred_language
  - report_depth
policy_tags:
  - cite-sources
  - separate-assumptions
triggers:
  - "调研报告"
  - "research report"
  - "decision memo"
  - "decision memo with sources"
  - "short decision memo"
  - "source-backed key findings"
  - "research tradeoffs and risks"
  - "travel esim research report"
  - "carrier roaming vs local sim report"
  - "mobile data plan decision memo"
  - "research what i should order"
  - "写一份报告"
  - "write up the findings"
  - "source-backed writeup"
  - "technical briefing"
  - "market briefing"
  - "cited report"
  - "查一下并写报告"
  - "查一下并写"
  - "决策 memo"
  - "决策备忘"
  - "来源、关键发现"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: low
    capabilities: [network, filesystem-write]
    clawhub_top100_composition:
      - skill: "Multi Search Engine"
        local_skill: multi-search-engine
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 11
        role: "Gather current multi-engine sources before drafting."
      - skill: "Deep Researcher / deep research family"
        local_skill: deep-research
        rank_source: "ClawHub research-skill family, verified via current search results"
        role: "Run deeper source-backed research for long reports."
      - skill: "Word / DOCX"
        local_skill: docx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 28
        role: "Export polished report artifacts when requested."
composition:
  steps:
    - id: preferences
      label: "偏好提取"
      label_en: "Preference extraction"
      kind: llm_chat
      with:
        system: "You infer report requirements. Return only the requested contract."
        task: |
          Infer the report contract from the request. If details are missing,
          choose conservative defaults and mark them as assumptions instead of
          asking follow-up questions. Set NEEDS_CLARIFICATION: yes only when the topic is too broad
          to search usefully, or when the user asks for a decision-support
          report but the audience or decision context is missing. Do not ask
          for citation style, length, or language when a conservative default
          works.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          SEARCH_QUERY: <short web-search query, no benchmark/control instructions>
          AUDIENCE: <reader>
          REPORT_TYPE: <technical|market|policy|general>
          TARGET_LENGTH: <short|standard|long>
          LANGUAGE: <language>
          CITATION_STYLE: <inline links|footnotes|bibliography>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <topic|audience|decision_context|none>
          CLARIFY_REASON: <one concise reason, or none>
          ASSUMPTIONS:
            - <assumption>
    - id: report_clarify
      label: "报告澄清"
      label_en: "Report clarification"
      kind: user_input
      depends_on: [preferences]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.preferences"
      clarify:
        mode: form
        intro: |
          报告主题或决策场景还不够明确。请补齐最小信息，我再继续检索和写作。
        intro_zh: "报告主题或决策场景还不够明确。请补齐最小信息，我再继续检索和写作。"
        intro_en: "The report topic or decision context is not clear enough. Fill in the minimum details and I will continue research and writing."
        nl_extract: true
        fields:
          - name: topic
            type: string
            required: true
            prompt: "报告主题 / Report topic"
            prompt_zh: "报告主题"
            prompt_en: "Report topic"
            max_chars: 240
          - name: audience
            type: string
            required: true
            prompt: "读者或受众 / Audience"
            prompt_zh: "读者或受众"
            prompt_en: "Audience"
            max_chars: 160
          - name: decision_context
            type: string
            required: true
            prompt: "要支持的决策或使用场景 / Decision context"
            prompt_zh: "要支持的决策或使用场景"
            prompt_en: "Decision or use case to support"
            max_chars: 300
          - name: source_preferences
            type: string
            prompt: "偏好的来源或范围 / Preferred sources or scope"
            prompt_zh: "偏好的来源或范围"
            prompt_en: "Preferred sources or scope"
            max_chars: 300
        cancel_keywords: ["算了", "取消", "cancel", "stop", "abort"]
        timeout_hours: 24
    - id: report_mode
      label: "报告模式"
      label_en: "Report mode"
      kind: llm_classify
      depends_on: [preferences, report_clarify]
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

          Clarification answers (may be empty when not needed):
          {{ inputs.get('collected', {}).get('report_clarify', {}) | tojson }}

          Decision rules:
          - QUICK_DECISION_MEMO: user wants a concise answer, quick brief,
            compact research report, planning-meeting memo, comparison memo,
            CTO/leadership decision aid, or explicitly says compact/concise/
            paste into a decision memo. Prefer this even when the phrase
            "research report" appears.
          - DEEP_REPORT: user wants a comprehensive, long, detailed, or
            multi-round source-backed report/briefing/writeup and did not
            explicitly request a file export.
          - EXPORT_DOCX: user explicitly asks for a Word/docx/file/report
            artifact export.
    - id: source_seed
      label: "源头种子"
      label_en: "Source seeds"
      kind: llm_chat
      depends_on: [preferences, report_mode]
      with:
        system: "You prepare conservative source targets for later verification."
        task: |
          Produce a compact list of official or near-official source targets
          that should be checked for this report. This is a fallback and
          query-planning aid, not proof that the source was checked.

          User request:
          {{ inputs.user_message | xml_escape | truncate(2000) }}

          Preferences:
          {{ outputs.preferences | truncate(1200) }}

          Rules:
          - Prefer official sources: regulator/agency pages, vendor pricing
            pages, product docs, carrier pages, destination tourism boards,
            standards bodies, or primary company docs.
          - For travel-connectivity decisions, include source target categories
            for home-carrier roaming pages, destination tourism-board internet
            guidance, eSIM provider official plan pages, and local carrier
            tourist SIM pages.
          - Include a URL only when it is a likely stable official homepage or
            obvious product page. Mark every URL as "verification target, not
            live-checked" unless it appears in the live search output later.
          - Do not infer current prices, coverage, availability, or support
            quality from this seed list.

          Return:
          SOURCE_TARGETS:
            - <title> — <URL or no URL> — verification target, not live-checked
    - id: search
      label: "检索"
      label_en: "Search"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [preferences, report_clarify, report_mode, source_seed]
      on_failure: search_fallback
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(240) }}"
        engines: [brave, tavily, duckduckgo]
        max_results: 20
    - id: search_fallback
      label: "检索兜底"
      label_en: "Search fallback"
      kind: llm_chat
      with:
        system: "You summarize that live web search was unavailable without exposing runtime details."
        task: |
          Return a concise source-limit note for report writing.
          Do not mention tool names, connector failures, workspaces, working
          directories, provider errors, or internal meta-skill mechanics.
          Say that live source verification was not completed and that the
          final memo must clearly mark evidence limits instead of inventing
          current prices, providers, or availability.

          Request:
          {{ inputs.user_message | xml_escape | truncate(2500) }}
    - id: source_quality
      label: "源质量"
      label_en: "Source quality"
      kind: llm_chat
      depends_on: [search, source_seed]
      with:
        system: "You curate search results for cited report writing. Be selective and source-aware."
        task: |
          Rank and deduplicate these web results for report writing.
          Prefer primary sources, official docs, reputable publications, and
          recent sources when the topic is time-sensitive. Remove low-quality
          SEO pages and repeated mirrors.

          Report preferences:
          {{ outputs.preferences | truncate(1200) }}

          Source targets (fallback/query planning only, not live-checked
          unless repeated in search results):
          {{ outputs.source_seed | truncate(3000) }}

          Search results:
          {{ outputs.search | truncate(8000) }}

          Return a concise numbered source pack with 8-15 sources. For each
          source, include:
          [S#] Title — URL
          Credibility: <why this source is usable>
          Supports: <specific claim(s)>
          Evidence type: <direct|indirect|background>

          If a search result lacks a URL, omit it. Do not create placeholder
          source numbers. Prefer fewer credible sources over many weak ones.
          If live search returned no usable URLs, create a separate section
          titled "Verification targets, not live-checked" from the source
          targets. These may be used in the final answer only as tonight's
          check list or evidence limits, not as proof for factual claims.
          For quick decision memos, prioritize the best 5-8 sources over a
          long source list. Prefer official/vendor docs, standards, primary
          surveys, reputable engineering publications, and current release
          notes. Avoid Reddit, anonymous forums, content farms, and generic SEO
          listicles as primary evidence; include them only as background or
          evidence-limit notes when no stronger source exists.
          Label secondary roundup/blog/stat pages as indirect/background unless
          they are the source of the specific statistic being used. Do not let
          indirect sources support causal, benchmark, cost, or adoption claims
          without an explicit caveat.
    - id: research
      label: "研究"
      label_en: "Research"
      skill: deep-research
      depends_on: [source_quality]
      when: "outputs.report_mode in ('DEEP_REPORT', 'EXPORT_DOCX')"
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.source_quality }}"
        rounds: 2
    - id: outline
      label: "大纲"
      label_en: "Outline"
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
      label: "报告初稿"
      label_en: "Draft report"
      kind: llm_chat
      depends_on: [outline]
      with:
        system: "You draft concise cited reports directly in chat."
        task: |
          Draft the report body from the outline and source pack. Do not use
          external tools, do not create files, and do not publish artifacts.
          The draft must be complete enough to paste directly into chat.

          Report mode:
          {{ outputs.report_mode }}

          Preferences:
          {{ outputs.preferences }}

          Outline:
          {{ outputs.outline }}

          Source pack:
          {{ outputs.source_quality }}

          Research:
          {{ outputs.research }}
    - id: source_to_claim
      label: "源到论断"
      label_en: "Source-to-claim mapping"
      kind: llm_chat
      depends_on: [report_draft, source_quality]
      when: "outputs.report_mode != 'QUICK_DECISION_MEMO'"
      with:
        system: "You audit report claims against source packs."
        task: |
          Build a concise source-to-claim map for the draft. Keep only
          claims that are supported by the source pack or explicitly mark a
          caveat. Do not add process commentary.
          Every mapped claim must cite one or more existing source IDs from
          the source pack, e.g. [S1], [S3]. Do not cite source numbers that
          are absent from the source pack.
          For each major claim, mark SUPPORT as DIRECT, INDIRECT, or
          INFERENCE. Claims with INDIRECT/INFERENCE support must be phrased as
          caveats or removed from the final recommendation.

          Source pack:
          {{ outputs.source_quality | truncate(6000) }}

          Draft:
          {{ outputs.report_draft | truncate(8000) }}
    - id: quality_gate
      label: "质量门"
      label_en: "Quality gate"
      kind: llm_chat
      depends_on: [report_draft, source_quality, source_to_claim]
      when: "outputs.report_mode != 'QUICK_DECISION_MEMO'"
      with:
        system: "You polish final reports and remove process commentary."
        task: |
          Review the report draft for artifact readiness. Verify:
          - every major claim has a source or clear caveat
          - source list contains credible URLs
          - executive summary and limitations are present
          - output is in the requested language
          - claims marked INDIRECT or INFERENCE are not stated as direct facts

          If acceptable, return the polished report body. If not, repair it
          directly and return the repaired report body. Do not include process
          commentary.
          The repaired report must include a visible "Sources" or "Source
          list" section with source titles and URLs. If the draft references
          numbered sources, the same numbers must appear in that source list.
          Remove or caveat quantitative claims that are not mapped to a source.

          Source pack:
          {{ outputs.source_quality | truncate(4000) }}

          Source-to-claim map:
          {{ outputs.source_to_claim | truncate(4000) }}

          Draft:
          {{ outputs.report_draft | truncate(8000) }}
    - id: final_report
      label: "终稿"
      label_en: "Final draft"
      kind: llm_chat
      depends_on: [quality_gate, source_quality, source_to_claim]
      with:
        system: "You produce the final user-facing report body."
        task: |
          Return the complete final report body inline in chat only. Use the requested language and
          keep the report mode in mind:
          - QUICK_DECISION_MEMO: concise decision memo with bullets, sources,
            and caveats.
          - DEEP_REPORT: full cited report with executive summary, findings,
            evidence, limitations, and sources.
          - EXPORT_DOCX: same as DEEP_REPORT, suitable for DOCX export.

          Report mode:
          {{ outputs.report_mode }}

          Source pack:
          {{ outputs.source_quality | truncate(5000) }}

          Source-to-claim map (may be empty for quick decision memos):
          {{ outputs.get('source_to_claim', '') | truncate(4000) }}

          Polished report or quick memo draft:
          {{ (outputs.get('quality_gate') or outputs.get('report_draft') or '') | truncate(10000) }}

          Final output contract:
          - Never return JSON, artifact references, attachment metadata,
            download URLs, or a wrapper like {"text": ..., "artifacts": ...}.
          - Never mention workflow, meta-skill, tool names, connector failures,
            workspace paths, working directory problems, or runtime details.
          - Preserve the user's language. If the request is in English, write
            the memo/report in English with English section headings only; do
            not default to Chinese or bilingual headings. If the request is in
            Chinese, write Simplified Chinese and do not default to English.
          - Never say the memo was saved, exported, attached, generated as a
            file, or available via artifact unless the user explicitly asked
            for DOCX/file export and the export step ran.
          - For decision-memo requests, keep it compact and memo-ready:
            use exactly these top-level sections in this order:
            Assumptions / Decision Context; Recommendation; Five Key Findings;
            Practical Risks / Tradeoffs; Evidence Limits / 证据局限; Next Steps; Sources.
            Keep the body under 900 words before the Sources section unless
            the user asks for a long report.
          - The Assumptions / Decision Context section must explicitly state
            the audience, decision being made, scope, and key assumptions from
            the preferences step. Do not omit this section when the user asks
            for assumptions, CTO context, planning context, or a decision memo.
          - The Five Key Findings section must contain exactly five numbered
            findings when the user asks for five. Each finding must cite at
            least one source ID or explicitly say "inference from [S#]" /
            "not directly proven by the source pack".
          - Treat the Source pack below as authoritative evidence input. If
            the Polished report says no sources were provided but the Source
            pack contains `[S#] Title — URL` entries, ignore that sentence and
            restore sources from the Source pack.
          - The Source list must copy title + URL entries from the Source pack
            verbatim or near-verbatim. Never output "No sources were provided"
            unless the Source pack is empty or contains no URLs.
          - Include a visible Source list with title + URL for every cited
            source ID. Do not cite [S#] or "Source #N" unless that source
            appears in the Source list.
          - Every non-obvious quantitative claim must be cited or explicitly
            marked as an assumption/inference. Remove invented cost, latency,
            benchmark, plan-price, availability, or quality numbers that are
            not supported by the source pack.
          - Key findings must cite only source IDs that appear in the Source
            list. When evidence is indirect, say "inference" or "not directly
            proven by the source pack" in the finding or limitations.
          - Add a short Evidence limits note when the source pack relies on
            secondary or indirect sources for strategic claims.
          - Do not use Reddit, anonymous forums, or generic listicles to support
            the final recommendation unless explicitly framed as anecdotal or
            background evidence. Prefer to omit them from Sources for quick
            decision memos when stronger sources exist.
          - If sources are weak or stale, say so in Limitations instead of
            overstating certainty.
          - Do not announce that a file was generated unless the user explicitly
            asked for DOCX/file export and the export step ran. For ordinary
            memo requests, the final chat reply must contain the complete memo
            body inline.
    - id: final_report_audit
      label: "终稿审稿"
      label_en: "Final review"
      kind: llm_chat
      depends_on: [preferences, report_mode, source_quality, final_report]
      with:
        system: "You audit the final report for inline chat delivery and source honesty."
        task: |
          Repair the final answer so the user receives the actual report body
          inline in chat. Preserve good content, but remove delivery wrappers
          and internal process commentary.

          User request:
          {{ inputs.user_message | xml_escape | truncate(2000) }}

          Preferences:
          {{ outputs.preferences | truncate(1200) }}

          Report mode:
          {{ outputs.report_mode }}

          Source pack:
          {{ outputs.source_quality | truncate(3000) }}

          Draft final:
          {{ outputs.final_report | truncate(7000) }}

          Hard requirements:
          - Return the complete final user-facing memo/report body inline in chat, not JSON.
          - If the draft contains artifact references, download URLs, file
            names, or a JSON wrapper, discard the wrapper and reconstruct the
            complete memo inline from the source pack and user request.
          - Preserve the user's language. For English requests, return
            English-only prose and English headings; remove Chinese headings
            and bilingual labels unless they are quoted source text. For
            Chinese requests, write Simplified Chinese and do not switch to
            English headings.
          - Remove phrases such as "元技能", "meta-skill", "workflow",
            "工作流", "工作目录", "workspace", "connector", "tool failure",
            "手动做研究", "信息收集充分", and any runtime apology.
          - Never mention workflow, meta-skill, tool names, connector failures,
            workspace paths, working directory problems, or runtime details.
          - Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details.
          - For the Japan eSIM/roaming/local SIM decision-memo pattern, include
            the requested sections: assumptions/decision context,
            recommendation, key findings, risks/tradeoffs, evidence limits,
            next steps for tonight, and how to teach parents to use it.
          - Use the exact heading "Evidence Limits / 证据局限" for evidence
            limits so readers and automated checks can find the caveats.
          - Include visible source titles and URLs copied from the source pack
            when source URLs are available. If live verification was limited,
            say that clearly and avoid invented current prices or availability.
          - If the source pack only has verification targets, include them in
            "Sources / 来源" as "to check tonight, not live-verified" and do
            not cite them as support for exact prices.
          - Do not create, save, export, attach, or claim a file for ordinary
            memo requests.
    - id: export
      label: "导出"
      label_en: "Export"
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
