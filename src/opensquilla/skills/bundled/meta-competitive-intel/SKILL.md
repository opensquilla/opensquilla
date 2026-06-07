---
name: meta-competitive-intel
description: "Use this meta-skill instead of answering directly when the current user asks for competitive-intel monitoring over a defined company, competitor, prospect, or partner set and time window. It is for sales/BD/strategy briefs: current signals across pricing, product, leadership, hiring, partnerships, funding, and news; optional baseline diff; and follow-up recommendations. Do not use it for a generic daily plan, generic company research, product comparison without named target companies, or pasted old competitive-intel examples."
kind: meta
meta_priority: 72
always: false
final_text_mode: "step:intel_brief_audit"
request_template:
  outcome: "Competitive-intel brief with current signals, evidence, and recommended actions."
  outcome_zh: "包含最新信号、证据和行动建议的竞品情报简报。"
  outcome_en: "Competitive-intel brief with current signals, evidence, and recommended actions."
  fields:
    - name: target_companies
      label_zh: "目标公司"
      label_en: "Target companies"
      required: true
    - name: time_window
      label_zh: "时间窗口"
      label_en: "Time window"
      required: false
      default: "recent/current"
      default_zh: "最近或当前"
      default_en: "recent/current"
    - name: focus_areas
      label_zh: "关注维度"
      label_en: "Focus areas"
      required: false
      default: "pricing, product, leadership, hiring, partnerships, funding, news"
      default_zh: "价格、产品、领导层、招聘、合作、融资、新闻"
      default_en: "pricing, product, leadership, hiring, partnerships, funding, news"
    - name: baseline_context
      label_zh: "基线背景"
      label_en: "Baseline context"
      required: false
    - name: audience
      label_zh: "受众"
      label_en: "Audience"
      required: false
      default: "sales, BD, or strategy stakeholder"
      default_zh: "销售、商务拓展或战略相关方"
      default_en: "sales, BD, or strategy stakeholder"
    - name: language
      label_zh: "输出语言"
      label_en: "Output language"
      required: false
      default: "match the user's language"
      default_zh: "跟随用户语言"
      default_en: "match the user's language"
  assumptions:
    - "Use public/current evidence when browsing is available."
    - "Do not treat stale pasted examples as current facts."
  assumptions_zh:
    - "浏览可用时，优先使用公开且当前的证据。"
    - "不要把用户粘贴的旧示例当作当前事实。"
  assumptions_en:
    - "Use public/current evidence when browsing is available."
    - "Do not treat stale pasted examples as current facts."
output_contract:
  required_sections:
    - "Executive summary"
    - "Signal table with evidence"
    - "Risks and unknowns"
    - "Recommended follow-up actions"
  assumptions:
    - "Currentness depends on available browsing/source access."
  unverified:
    - "Private pricing, roadmap, and non-public account data."
  artifacts: []
eval_prompts:
  - name: "competitive-intel-baseline"
    prompt: "Prepare a competitive-intel brief on two named competitors over the last month for a sales lead."
    rubric:
      - "Executive summary"
      - "Signal table with evidence"
      - "Risks and unknowns"
      - "Recommended follow-up actions"
preference_keys:
  - preferred_language
  - audience_profile
policy_tags:
  - public-data-only
  - no-private-account-data
triggers:
  - "competitive intelligence"
  - "watch this account"
  - "monitor these competitor accounts"
  - "竞品监控"
  - "竞品情报"
  - "competitive intel"
  - "本周对手动作"
  - "对标公司动态"
  - "competitor brief"
  - "track these companies"
  - "盯一下这两个对手"
  - "盯一下这些对手"
  - "竞品最近有没有值得提醒老板的动作"
  - "竞品销售群简报"
  - "销售群里的简报"
  - "对手动态和基线相比"
  - "这些公司和上次基线相比"
  - "账户 x 维度表"
  - "根据账户信号今天该跟进谁"
  - "这些竞品最近一个月的产品和价格"
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
        role: "Gather current company, competitor, product, hiring, and pricing signals."
      - skill: "Deep Researcher / deep research family"
        local_skill: deep-research
        rank_source: "ClawHub research-skill family, verified via current search results"
        role: "Run a focused company dive when one target needs deeper coverage."
      - skill: "Excel / XLSX"
        local_skill: xlsx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 21
        role: "Export signal tables for competitive-intel review when requested."
      - skill: "Word / DOCX"
        local_skill: docx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 28
        role: "Export an executive intel brief when requested."
composition:
  steps:
    - id: preferences
      label: "偏好提取"
      label_en: "Preference extraction"
      kind: llm_chat
      with:
        system: "You extract competitive-intel preferences. Return only the requested contract."
        task: |
          Extract the intel brief.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1800) }}

          Return exactly:
          ACCOUNTS:
            - <company name as written>
          DIMENSIONS:
            - <PRICING|PRODUCT|LEADERSHIP|HIRING|NEWS|PARTNERSHIPS|FUNDING>
          TIME_WINDOW: <LAST_WEEK|LAST_MONTH|LAST_QUARTER|UNSPECIFIED>
          BASELINE_TEXT_PRESENT: <yes|no>
          LANGUAGE: <en|zh|mixed>
          EXPORT_DOCX_REQUESTED: <yes|no>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <accounts|dimensions|time_window|none>
          CLARIFY_REASON: <one concise reason, or none>
          ASSUMPTIONS:
            - <assumption>
    - id: intel_clarify
      label: "情报澄清"
      label_en: "Intel clarification"
      kind: user_input
      depends_on: [preferences]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.preferences"
      clarify:
        mode: form
        intro: |
          竞品情报还缺一些信息，麻烦补齐 / Need a few details to run the intel brief.
        intro_zh: "竞品情报还缺一些信息，麻烦补齐后我会继续生成简报。"
        intro_en: "Need a few details to run the competitive-intel brief."
        nl_extract: true
        fields:
          - name: accounts
            type: string
            required: true
            prompt: "要监控的公司/竞品（逗号分隔；建议 1-5 个）/ Companies or competitors to monitor (comma-separated; 1-5)"
            prompt_zh: "要监控的公司或竞品（逗号分隔，建议 1-5 个）"
            prompt_en: "Companies or competitors to monitor (comma-separated; 1-5)"
            max_chars: 240
          - name: dimensions
            type: string
            required: true
            prompt: "关注维度（逗号分隔：PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS, PARTNERSHIPS, FUNDING）/ Dimensions"
            prompt_zh: "关注维度（逗号分隔：PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS, PARTNERSHIPS, FUNDING）"
            prompt_en: "Dimensions to monitor (comma-separated: PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS, PARTNERSHIPS, FUNDING)"
            max_chars: 200
          - name: time_window
            type: enum
            choices: [LAST_WEEK, LAST_MONTH, LAST_QUARTER]
            default: LAST_MONTH
            prompt: "时间窗口 / Time window"
            prompt_zh: "时间窗口"
            prompt_en: "Time window"
          - name: baseline_text
            type: string
            prompt: "上次情报基线（粘贴；可留空）/ Prior intel baseline brief (optional, paste)"
            prompt_zh: "上次情报基线（可留空，直接粘贴即可）"
            prompt_en: "Prior intel baseline brief (optional; paste if available)"
            max_chars: 4000
          - name: language
            type: enum
            choices: [en, zh, mixed]
            default: en
            prompt: "输出语言 / Output language"
            prompt_zh: "输出语言"
            prompt_en: "Output language"
          - name: export_docx
            type: enum
            choices: ["YES", "NO"]
            default: "NO"
            prompt: "DOCX 导出 / Export to DOCX"
            prompt_zh: "是否导出 DOCX"
            prompt_en: "Export to DOCX?"
        cancel_keywords: ["算了", "取消", "cancel", "stop", "abort"]
        timeout_hours: 24
    - id: depth
      label: "深度判断"
      label_en: "Depth decision"
      kind: llm_classify
      depends_on: [preferences, intel_clarify]
      output_choices:
        - SINGLE_DEEP
        - MULTI_QUICK
        - DIFF_VS_BASELINE
        - EXEC_BRIEF
      with:
        text: |
          Classify the intel depth.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(800) }}

          Clarification:
          {{ inputs.get('collected', {}).get('intel_clarify', {}) | tojson }}

          Decision rules:
          - SINGLE_DEEP: exactly one target in scope, user wants
            comprehensive multi-source dive.
          - MULTI_QUICK: 2-5 accounts, scan-level coverage per account.
          - DIFF_VS_BASELINE: baseline text was pasted; the value of
            this run is the diff, not the absolute snapshot.
          - EXEC_BRIEF: user asks for a 5-bullet executive-style summary
            for someone else to skim; minimise raw research dump.
    - id: intel_context
      label: "情报上下文"
      label_en: "Intel context"
      kind: llm_chat
      depends_on: [depth, intel_clarify]
      with:
        system: "You extract the durable competitive-intel context from the raw user request and any clarification payload. Return only the requested contract. Preserve pasted baseline facts exactly enough for later diffing. Never infer current signals from baseline facts."
        task: |
          Build the competitive-intel context that all later steps must use.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}

          Clarification:
          {{ inputs.get('collected', {}).get('intel_clarify', {}) | tojson | truncate(1200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(1000) }}

          Depth: {{ outputs.depth }}

          Return exactly:
          ACCOUNTS:
            - <company/account as written by the user>
          DIMENSIONS:
            - <PRODUCT|PRICING_OR_CAMPAIGN|HIRING|PARTNERSHIPS|FUNDING|LEADERSHIP|NEWS>
          TIME_WINDOW: <plain-language time window from the user, or UNSPECIFIED>
          AUDIENCE: <sales group|boss|BD team|self|other/UNKNOWN>
          USER_MARKET_POSITION: <what the user's company does, if stated, else UNKNOWN>
          PASTED_BASELINE:
            - <baseline statement explicitly pasted by the user, or none>
          ACCOUNT_DIMENSION_GRID:
            - <account> | <dimension> | <what to check>
          OUTPUT_LANGUAGE: <zh|en|mixed>
          EXPORT_DOCX_REQUESTED: <yes|no>
          MISSING_CONTEXT:
            - <missing but useful context; use none if enough to proceed>

          Rules:
          - If the user says "上次", "基线", "last time", or "baseline",
            capture those statements under PASTED_BASELINE even if
            intel_clarify did not run.
          - Keep baseline facts separate from current signals. They are
            comparison material, not evidence that something happened now.
          - If account or dimension names are visible in the raw user request,
            do not ask for them again.
    - id: recall_baseline
      label: "基线召回"
      label_en: "Baseline recall"
      kind: tool_call
      tool: memory_search
      tool_allowlist: [memory_search]
      depends_on: [depth, intel_context, intel_clarify]
      on_failure: recall_baseline_fallback
      tool_args:
        query: "competitive intel baseline prior brief competitors {{ outputs.get('intel_context', '') | truncate(1000) }} {{ inputs.user_message | xml_escape | truncate(800) }}"
        max_results: 6
        source: memory
    - id: recall_baseline_fallback
      label: "基线召回兜底"
      label_en: "Baseline recall fallback"
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for competitive intel."
        task: |
          No durable prior intel brief was read. Continue using only pasted
          baseline text and current visible research evidence. Do not mention
          runtime errors to the user.
    - id: search_strategy
      label: "检索策略"
      label_en: "Search strategy"
      kind: llm_chat
      depends_on: [depth, intel_context]
      with:
        system: "You turn competitive-intel context into search-engine-ready queries. Return only the requested contract. Prefer broad recall over brittle syntax."
        task: |
          Build robust web search queries for this competitive intel.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2500) }}

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          SEARCH_QUERY: <one concise query, max 260 chars>
          FALLBACK_SEARCH_QUERY: <one alternate concise query, max 260 chars>
          ALIASES:
            - <account> | <common aliases in the user's language and English, comma-separated>
          SOURCE_TARGETS:
            - <source category to prioritize>

          Rules:
          - SEARCH_QUERY and FALLBACK_SEARCH_QUERY must be plain search
            strings, not YAML, JSON, markdown, field labels, or a copied
            account grid.
          - Include useful aliases for each account. For Chinese AI companies,
            include Chinese name, English name, product names, and common
            romanization when obvious (for example Kimi / Moonshot AI,
            MiniMax / 海螺AI / abab).
          - Include the user's time window and requested dimensions as short
            natural-language search terms.
          - Do not include internal context keys like ACCOUNTS, DIMENSIONS,
            ACCOUNT_DIMENSION_GRID, USER_MARKET_POSITION, or PASTED_BASELINE
            in either query.
          - Avoid long Boolean expressions. If there are many accounts or
            dimensions, choose the terms most likely to retrieve current
            company news, product/pricing pages, funding, hiring, and
            partnership announcements.
    - id: web_research
      label: "网页研究"
      label_en: "Web research"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [depth, intel_context, search_strategy]
      on_failure: web_research_fallback
      with:
        query: "{{ outputs.get('search_strategy', '') | truncate(700) }}"
        engines: [brave, tavily, duckduckgo]
        max_results: 15
    - id: web_research_fallback
      label: "网页研究兜底"
      label_en: "Web research fallback"
      kind: llm_chat
      with:
        system: "You produce a no-web fallback note for competitive intel."
        task: |
          Web research was not available. Extract accounts, baseline facts,
          requested dimensions, time window, and decision audience only from
          the pasted request. Mark current external signals as not verified.
          Do not expose tool names, paths, stack traces, connector wording, or
          runtime failures.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}
    - id: target_search_query_1
      label: "目标1检索词"
      label_en: "Target 1 query"
      kind: llm_chat
      depends_on: [intel_context, search_strategy]
      with:
        system: "You produce one target-specific search query. Return only SEARCH_QUERY or NO_TARGET."
        task: |
          Build a focused search query for the 1st target listed under
          ACCOUNTS in the competitive-intel context.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2200) }}

          Search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1000) }}

          Return exactly one line:
          SEARCH_QUERY: <1st target aliases + time window + product pricing hiring funding partnership leadership news terms, max 220 chars>

          If there is no 1st target, return exactly:
          NO_TARGET

          Rules:
          - Include only this one monitored target and its aliases.
          - Do not include other monitored targets, the user's own company, or market
            comparables.
          - Use plain search text, not YAML or JSON.
    - id: web_research_target_1
      label: "目标1研究"
      label_en: "Target 1 research"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [target_search_query_1]
      when: "'NO_TARGET' not in outputs.get('target_search_query_1', '')"
      on_failure: web_research_target_1_fallback
      with:
        query: "{{ outputs.get('target_search_query_1', '') | truncate(400) }}"
        engines: [duckduckgo, brave, tavily]
        max_results: 8
    - id: web_research_target_1_fallback
      label: "目标1研究兜底"
      label_en: "Target 1 research fallback"
      kind: llm_chat
      with:
        system: "You produce a source-unavailable fallback note for one target search."
        task: |
          Target-specific search was unavailable. Mark this target's current
          external signals as not verified. Do not expose tool names, paths,
          stack traces, connector wording, or runtime failures.
    - id: target_search_query_2
      label: "目标2检索词"
      label_en: "Target 2 query"
      kind: llm_chat
      depends_on: [intel_context, search_strategy]
      with:
        system: "You produce one target-specific search query. Return only SEARCH_QUERY or NO_TARGET."
        task: |
          Build a focused search query for the 2nd target listed under
          ACCOUNTS in the competitive-intel context.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2200) }}

          Search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1000) }}

          Return exactly one line:
          SEARCH_QUERY: <2nd target aliases + time window + product pricing hiring funding partnership leadership news terms, max 220 chars>

          If there is no 2nd target, return exactly:
          NO_TARGET

          Rules:
          - Include only this one monitored target and its aliases.
          - Do not include other monitored targets, the user's own company, or market
            comparables.
          - Use plain search text, not YAML or JSON.
    - id: web_research_target_2
      label: "目标2研究"
      label_en: "Target 2 research"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [target_search_query_2]
      when: "'NO_TARGET' not in outputs.get('target_search_query_2', '')"
      on_failure: web_research_target_2_fallback
      with:
        query: "{{ outputs.get('target_search_query_2', '') | truncate(400) }}"
        engines: [duckduckgo, brave, tavily]
        max_results: 8
    - id: web_research_target_2_fallback
      label: "目标2研究兜底"
      label_en: "Target 2 research fallback"
      kind: llm_chat
      with:
        system: "You produce a source-unavailable fallback note for one target search."
        task: |
          Target-specific search was unavailable. Mark this target's current
          external signals as not verified. Do not expose tool names, paths,
          stack traces, connector wording, or runtime failures.
    - id: target_search_query_3
      label: "目标3检索词"
      label_en: "Target 3 query"
      kind: llm_chat
      depends_on: [intel_context, search_strategy]
      with:
        system: "You produce one target-specific search query. Return only SEARCH_QUERY or NO_TARGET."
        task: |
          Build a focused search query for the 3rd target listed under
          ACCOUNTS in the competitive-intel context.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2200) }}

          Search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1000) }}

          Return exactly one line:
          SEARCH_QUERY: <3rd target aliases + time window + product pricing hiring funding partnership leadership news terms, max 220 chars>

          If there is no 3rd target, return exactly:
          NO_TARGET

          Rules:
          - Include only this one monitored target and its aliases.
          - Do not include other monitored targets, the user's own company, or market
            comparables.
          - Use plain search text, not YAML or JSON.
    - id: web_research_target_3
      label: "目标3研究"
      label_en: "Target 3 research"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [target_search_query_3]
      when: "'NO_TARGET' not in outputs.get('target_search_query_3', '')"
      on_failure: web_research_target_3_fallback
      with:
        query: "{{ outputs.get('target_search_query_3', '') | truncate(400) }}"
        engines: [duckduckgo, brave, tavily]
        max_results: 8
    - id: web_research_target_3_fallback
      label: "目标3研究兜底"
      label_en: "Target 3 research fallback"
      kind: llm_chat
      with:
        system: "You produce a source-unavailable fallback note for one target search."
        task: |
          Target-specific search was unavailable. Mark this target's current
          external signals as not verified. Do not expose tool names, paths,
          stack traces, connector wording, or runtime failures.
    - id: research_status
      label: "研究状态"
      label_en: "Research status"
      kind: llm_classify
      depends_on:
        - web_research
        - web_research_target_1
        - web_research_target_2
        - web_research_target_3
        - search_strategy
      output_choices:
        - SEARCH_OK
        - SEARCH_EMPTY
        - SEARCH_UNAVAILABLE
      with:
        text: |
          Classify the competitive-intel search result quality.

          Search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1200) }}

          Search result JSON or fallback note:
          {{ outputs.get('web_research', '') | truncate(3500) }}

          Target-specific result 1:
          {{ outputs.get('web_research_target_1', '') | truncate(1800) }}

          Target-specific result 2:
          {{ outputs.get('web_research_target_2', '') | truncate(1800) }}

          Target-specific result 3:
          {{ outputs.get('web_research_target_3', '') | truncate(1800) }}

          Decision rules:
          - SEARCH_OK: at least one relevant result/title/snippet is available
            for a monitored target and can plausibly inform the requested
            time window or dimensions.
          - SEARCH_EMPTY: search ran but returned no clearly relevant result.
          - SEARCH_UNAVAILABLE: no usable result is available because all or
            most engines failed, returned request errors, missing-key errors,
            parse failures, or the output is a no-web fallback.
    - id: search_retry_query
      label: "重试检索词"
      label_en: "Retry query"
      kind: llm_chat
      depends_on: [research_status, search_strategy, intel_context]
      when: "outputs.get('research_status', '') != 'SEARCH_OK'"
      with:
        system: "You produce one fallback search query. Return exactly one SEARCH_QUERY line."
        task: |
          The first competitive-intel search did not return usable evidence.
          Produce a broader fallback query that is still search-engine-ready.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(1800) }}

          Previous search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1400) }}

          Return exactly:
          SEARCH_QUERY: <one broader query, max 220 chars>

          Rules:
          - Use aliases and product names, not the structured account grid.
          - Drop lower-value dimensions if needed. Prefer company news,
            product, pricing, funding, hiring, partnership, and leadership
            terms.
          - Do not mention tool failures or internal execution.
    - id: web_research_retry
      label: "重试研究"
      label_en: "Retry research"
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [search_retry_query]
      when: "outputs.get('research_status', '') != 'SEARCH_OK'"
      on_failure: web_research_retry_fallback
      with:
        query: "{{ outputs.get('search_retry_query', '') | truncate(500) }}"
        engines: [duckduckgo, brave, tavily]
        max_results: 10
    - id: web_research_retry_fallback
      label: "重试研究兜底"
      label_en: "Retry research fallback"
      kind: llm_chat
      with:
        system: "You produce a source-unavailable fallback note for competitive intel."
        task: |
          Fallback search was not available. Mark current external signals as
          not verified. Do not expose tool names, paths, stack traces,
          connector wording, or runtime failures.
    - id: research_status_final
      label: "最终状态"
      label_en: "Final status"
      kind: llm_classify
      depends_on:
        - research_status
        - web_research
        - web_research_target_1
        - web_research_target_2
        - web_research_target_3
        - web_research_retry
      output_choices:
        - SEARCH_OK
        - SEARCH_EMPTY
        - SEARCH_UNAVAILABLE
      with:
        text: |
          Classify final competitive-intel search quality after any retry.

          First-pass status:
          {{ outputs.get('research_status', '') }}

          First-pass result:
          {{ outputs.get('web_research', '') | truncate(2500) }}

          Target-specific result 1:
          {{ outputs.get('web_research_target_1', '') | truncate(1800) }}

          Target-specific result 2:
          {{ outputs.get('web_research_target_2', '') | truncate(1800) }}

          Target-specific result 3:
          {{ outputs.get('web_research_target_3', '') | truncate(1800) }}

          Retry result:
          {{ outputs.get('web_research_retry', '') | truncate(2500) }}

          Decision rules:
          - SEARCH_OK: at least one relevant result/title/snippet is available
            for a monitored target and can plausibly inform the requested
            time window or dimensions.
          - SEARCH_EMPTY: at least one search pass ran successfully but no
            relevant result was found.
          - SEARCH_UNAVAILABLE: no usable search evidence is available because
            both passes failed, were skipped into fallback, returned only
            request/key/parse errors, or yielded no result objects.
    - id: summarize_web
      label: "网页摘要"
      label_en: "Web summary"
      kind: llm_chat
      depends_on:
        - web_research
        - web_research_target_1
        - web_research_target_2
        - web_research_target_3
        - web_research_retry
        - research_status_final
        - search_strategy
        - intel_context
      with:
        system: "You compress competitive-intel research into a source-faithful signal digest. Do not expose tool names, connector failures, paths, stack traces, or runtime details."
        task: |
          Compress the web research into a compact competitive-intel digest.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2000) }}

          Search strategy:
          {{ outputs.get('search_strategy', '') | truncate(1200) }}

          Final search status:
          {{ outputs.get('research_status_final', '') }}

          Primary web research:
          {{ outputs.web_research | truncate(5000) }}

          Target-specific web research:
          {{ outputs.get('web_research_target_1', '') | truncate(2500) }}
          {{ outputs.get('web_research_target_2', '') | truncate(2500) }}
          {{ outputs.get('web_research_target_3', '') | truncate(2500) }}

          Retry web research:
          {{ outputs.get('web_research_retry', '') | truncate(3500) }}

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Output exactly:
          ## Account signal digest
          - <account> | <dimension> | <signal> | <source hint or source limit>

          Rules:
          - Keep only pricing/activity, product, hiring, partnerships, funding,
            leadership, and news signals relevant to the user's accounts.
          - Do not invent missing facts, numbers, funding, leaders, hiring
            trends, or pricing changes.
          - If a search result is ambiguous or not clearly current, mark
            "source limit / 未核验" instead of presenting it as fact.
          - If final search status is SEARCH_UNAVAILABLE, say the current
            source set was unavailable and mark every requested account ×
            dimension as unverified; do not summarize this as "confirmed no
            signal".
          - If final search status is SEARCH_EMPTY, distinguish "no usable
            result returned" from "nothing changed".
          - Do not expose tool names, search errors, connector wording,
            workspace paths, or runtime details.
    - id: deep_dive
      label: "深度挖掘"
      label_en: "Deep dive"
      kind: skill_exec
      skill: deep-research
      depends_on: [depth, intel_context, search_strategy]
      when: "outputs.depth == 'SINGLE_DEEP'"
      with:
        query: "{{ outputs.get('search_strategy', '') | truncate(700) }} comprehensive competitive intel"
        depth: "deep"
        max_rounds: 3
    - id: enrich_accounts
      label: "账户补全"
      label_en: "Account completion"
      kind: llm_chat
      depends_on: [depth, web_research, web_research_retry, research_status_final, summarize_web, intel_context, intel_clarify]
      with:
        system: "You produce firmographic-style company briefs from web search results. Be conservative; mark UNKNOWN when sources disagree. Never invent leadership names or numbers."
        task: |
          Produce one brief per target, grounded ONLY in web research.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2000) }}

          Compressed web summary (preferred):
          {{ outputs.get('summarize_web', '') | truncate(2000) }}

          Raw web research (fallback context):
          {{ outputs.get('web_research', '') | truncate(2500) }}

          Retry web research:
          {{ outputs.get('web_research_retry', '') | truncate(1800) }}

          Final search status:
          {{ outputs.get('research_status_final', '') }}

          For each target output exactly:

          ## <Account name>
          INDUSTRY: <or UNKNOWN>
          STAGE: <PUBLIC|UNICORN|LATE_STAGE|GROWTH|SEED|UNKNOWN>
          SIZE_BAND: <1-10|11-50|51-200|201-1000|1000+|UNKNOWN>
          KEY_LEADERS:
            - <Name, Title — only if sourced>
          RECENT_MOVES:
            - <bullet, source>
          HIRING_SIGNAL: <ACCELERATING|FLAT|SLOWING|UNKNOWN>
    - id: extract_signals
      label: "信号提取"
      label_en: "Signal extraction"
      kind: llm_chat
      depends_on:
        - depth
        - web_research
        - web_research_retry
        - research_status_final
        - summarize_web
        - deep_dive
        - enrich_accounts
        - intel_context
        - intel_clarify
      with:
        system: "You extract concrete signals from research results, organised by account × dimension. Be specific (price changes with numbers, leadership moves with names, product launches with feature names). Never invent signals; only emit grounded ones."
        task: |
          Extract signals.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2500) }}

          Compressed web summary (preferred):
          {{ outputs.get('summarize_web', '') | truncate(3000) }}

          Web research:
          {{ outputs.get('web_research', '') | truncate(3000) }}

          Retry web research:
          {{ outputs.get('web_research_retry', '') | truncate(2500) }}

          Final search status:
          {{ outputs.get('research_status_final', '') }}

          Deep dive (if SINGLE_DEEP):
          {{ outputs.get('deep_dive', '') | truncate(2500) }}

          Account enrichment:
          {{ outputs.get('enrich_accounts', '') | truncate(2000) }}

          Dimensions to focus on:
          {{ outputs.get('intel_context', '') | truncate(1200) }}

          Output a markdown table:
          account | dimension | signal | strength (LOW|MED|HIGH) |
          source_hint | one_line_implication.

          Rules:
          - Do not return only the table header.
          - If current research has no verified signal for a requested cell,
            emit one row per requested account × dimension with signal
            "未见已核验新信号 / no verified new signal", strength LOW,
            source_hint "source limit / 未核验", and a practical implication.
          - If final search status is SEARCH_UNAVAILABLE, use
            "检索不可用 / source unavailable" in source_hint and make the
            implication ask for source repair or manual verification. Do not
            imply that a real scan found no activity.
          - If final search status is SEARCH_EMPTY, use
            "未返回可用结果 / source limit" in source_hint and keep the wording
            cautious.
          - Do not convert PASTED_BASELINE facts into current signals. Baseline
            facts can be mentioned only as comparison context.
          - Preserve account names and requested dimensions from intel_context
            even when web research is sparse.

          Sort by strength desc, then account.
          Drop signals where strength is LOW and the source hint is
          vague ("unconfirmed", "rumour") unless the row is one of the
          requested no-verified-new-signal placeholder rows.
    - id: baseline_diff
      label: "基线对比"
      label_en: "Baseline comparison"
      kind: llm_chat
      depends_on: [extract_signals, recall_baseline, depth, intel_context, intel_clarify]
      when: "outputs.depth == 'DIFF_VS_BASELINE' or 'BASELINE_TEXT_PRESENT: yes' in outputs.preferences or (inputs.get('collected', {}).get('intel_clarify', {}).get('baseline_text', '') | length) > 0 or (outputs.get('recall_baseline', '') | length) > 0"
      with:
        system: "You diff the current signals against a baseline brief. The baseline may be pasted text from the user, OR a recalled brief from durable memory (from a prior run of this meta-skill). Surface what's new, what's gone, what shifted."
        task: |
          Diff current signals vs baseline.

          Competitive-intel context, including PASTED_BASELINE from inputs.user_message:
          {{ outputs.get('intel_context', '') | truncate(2500) }}

          Original user request:
          {{ inputs.user_message | xml_escape | truncate(2200) }}

          Current signals:
          {{ outputs.extract_signals | truncate(3000) }}

          Baseline — pasted by user (if any):
          {{ inputs.get('collected', {}).get('intel_clarify', {}).get('baseline_text', '') | xml_escape | truncate(2000) }}

          Baseline — recalled from durable memory (if any):
          {{ outputs.get('recall_baseline', '') | truncate(2000) }}

          Output sections:
          ## 🆕 New since baseline
          (signals present now, absent in baseline)
          ## 🔄 Shifted
          (signals present in both but value / strength changed)
          ## 🪦 Stopped
          (signals present in baseline but not now)

          Each entry: account | dimension | one-line description |
          confidence (LOW|MED|HIGH).

          Rules:
          - Treat PASTED_BASELINE in intel_context as the primary baseline
            when intel_clarify is empty.
          - If current signals are all source-limited, say "未见已核验新增"
            rather than inventing a change.
          - Still list unchanged baseline claims under Shifted/Unchanged
            wording when useful for the user's requested comparison.
    - id: verdict
      label: "结论"
      label_en: "Conclusion"
      kind: llm_classify
      depends_on: [extract_signals, baseline_diff]
      output_choices:
        - NO_NEW_SIGNAL
        - LOW_SIGNAL
        - MEDIUM_SIGNAL
        - HIGH_SIGNAL
        - URGENT
      with:
        text: |
          Classify the overall intel verdict.

          Extracted signals:
          {{ outputs.extract_signals | truncate(2500) }}

          Baseline diff (may be empty):
          {{ outputs.get('baseline_diff', '') | truncate(2000) }}

          Decision rules:
          - NO_NEW_SIGNAL: nothing notable; all signals LOW strength or
            all "Stopped" / unchanged.
          - LOW_SIGNAL: 1-2 MEDIUM signals, nothing HIGH.
          - MEDIUM_SIGNAL: 3-5 MEDIUM signals OR 1 HIGH signal.
          - HIGH_SIGNAL: 2+ HIGH signals, OR clear strategic move (M&A
            rumour, product pivot, key exec hire).
          - URGENT: signal directly threatens or unlocks the user's
            position (pricing collision, key customer poached, security
            incident at the monitored target that the user can take
            advantage of OR must defend against).
    - id: recommend_actions
      label: "行动建议"
      label_en: "Action recommendations"
      kind: llm_chat
      depends_on: [verdict, extract_signals, baseline_diff, intel_context, intel_clarify]
      with:
        system: "You produce concrete next-actions grounded in the verdict and signals. Each action must reference a specific signal."
        task: |
          Produce next-actions.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(1500) }}

          Verdict: {{ outputs.verdict }}

          Signals:
          {{ outputs.extract_signals | truncate(2500) }}

          Baseline diff:
          {{ outputs.get('baseline_diff', '') | truncate(1500) }}

          Output 3-5 bullets. Each bullet:
          - The action (verb-first, concrete)
          - Why (which signal it ties to)
          - Owner (the user, or "assign to <role>")
          - Time horizon (TODAY | THIS_WEEK | THIS_MONTH | WATCHING)

          If the verdict is NO_NEW_SIGNAL, the only bullet should be
          "Continue monitoring — re-run in <time_window>".
    - id: signals_xlsx
      label: "信号表格"
      label_en: "Signal table"
      kind: skill_exec
      skill: xlsx
      depends_on: [extract_signals, verdict, intel_clarify]
      when: "'xlsx' in (inputs.user_message | lower) or 'spreadsheet' in (inputs.user_message | lower) or 'download' in (inputs.user_message | lower) or '导出' in inputs.user_message or '下载' in inputs.user_message"
      with:
        mode: create
        sheets:
          - name: "Signals"
            rows:
              - ["account", "dimension", "signal", "strength", "source_hint", "implication"]
            from_markdown: "{{ outputs.extract_signals }}"
          - name: "vs Baseline"
            from_markdown: "{{ outputs.get('baseline_diff', '') }}"
        output_path: "/tmp/competitive_intel_signals_{{ inputs.get('collected', {}).get('intel_clarify', {}).get('accounts', 'untitled') | slugify | truncate(60) }}.xlsx"
    - id: deliver_intel_brief
      label: "情报交付"
      label_en: "Intel delivery"
      kind: llm_chat
      depends_on:
        - preferences
        - intel_clarify
        - intel_context
        - depth
        - extract_signals
        - baseline_diff
        - verdict
        - recommend_actions
        - recall_baseline
        - summarize_web
        - research_status_final
        - signals_xlsx
      with:
        system: "You assemble the final competitive-intel brief. Return the complete brief inline in chat. Do not create, save, export, attach, or point primarily to an artifact unless the user explicitly asked for a file export. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details. Lead with the verdict, then signals, baseline diff, and actions."
        task: |
          Assemble the final intel brief.

          Verdict: {{ outputs.verdict }}
          Depth: {{ outputs.depth }}

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2000) }}

          Final search status:
          {{ outputs.get('research_status_final', '') }}

          Structure depends on depth:

          - EXEC_BRIEF → only the 5-bullet exec summary, then verdict
            line, then top 3 actions. Nothing else.
          - SINGLE_DEEP → full structure below.
          - MULTI_QUICK → full structure below, but trim signal table
            to top 10 rows.
          - DIFF_VS_BASELINE → lead with the baseline_diff section,
            then signals, then actions.

          Full structure:

          # <Verdict emoji> <Verdict label> — Competitive Intel <date range>

          Verdict emoji: 🟢 NO_NEW_SIGNAL, 🟡 LOW_SIGNAL, 🟠 MEDIUM_SIGNAL,
          🔴 HIGH_SIGNAL, ⛔ URGENT.

          ## TL;DR
          A 2-sentence summary grounded in the top signals.

          ## Signals
          {{ outputs.extract_signals | truncate(3000) }}

          ## vs Baseline
          {{ outputs.get('baseline_diff', '') | truncate(2000) }}
          (or "No baseline provided." if empty)

          ## Recommended Actions
          {{ outputs.recommend_actions | truncate(1500) }}

          Language: per preferences (default en).

          If the user wants to keep this brief somewhere (Notion / Google
          Doc / personal intel database), they can copy the markdown
          directly from this output — this is read-only and
          does not push to any external surface.

          End with a single line:
          INTEL_VERDICT: {{ outputs.verdict }}
    - id: intel_brief_audit
      label: "情报审稿"
      label_en: "Intel review"
      kind: llm_chat
      depends_on:
        - deliver_intel_brief
        - extract_signals
        - baseline_diff
        - recommend_actions
        - verdict
        - preferences
        - intel_context
        - research_status_final
      with:
        system: "You are the final quality gate for an competitive-intel brief. Return only the cleaned final answer the user should read. Do not explain the audit. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, runtime details, or internal artifacts."
        task: |
          Rewrite the draft below into a clean competitive-intel brief for the user.

          Competitive-intel context:
          {{ outputs.get('intel_context', '') | truncate(2500) }}

          Final search status:
          {{ outputs.get('research_status_final', '') }}

          Draft brief:
          {{ outputs.get('deliver_intel_brief', '') | truncate(8000) }}

          Extracted signals:
          {{ outputs.get('extract_signals', '') | truncate(3500) }}

          Baseline diff:
          {{ outputs.get('baseline_diff', '') | truncate(2500) }}

          Recommended actions:
          {{ outputs.get('recommend_actions', '') | truncate(1800) }}

          Verdict: {{ outputs.verdict }}
          Preferences:
          {{ outputs.get('preferences', '') | truncate(800) }}

          Required audit rules:
          - Remove runtime commentary, tool/debug narration, path references,
            connector wording, search-failure chatter, and any statement that
            internal steps ran or failed.
          - Remove artifact or attachment claims. Do not claim that a file was generated,
            downloaded, attached, saved, or can be fetched unless the user
            explicitly requested export and an export step is present.
          - If a signal has no source hint, no clear research evidence, or came
            only from the user's baseline, mark it as "未核验 / source limit"
            instead of presenting it as current fact.
          - If final search status is SEARCH_UNAVAILABLE, lead with
            "本轮信源检索不可用，不能据此判断是否有新增信号" and use
            "检索不可用 / source unavailable" rather than "未见已核验新信号"
            as if a scan succeeded.
          - If final search status is SEARCH_EMPTY, say "检索未返回可用材料"
            and keep conclusions source-limited; do not say "确认无变化".
          - When all current rows are "未见已核验新信号" or source-limited,
            lead with "未见已核验新增" rather than "确认无变化" or "无新信号".
            Source-limited evidence is not proof that nothing changed.
          - Do not say baseline judgments remain confirmed, still valid, or
            still hold unless there is current verified evidence supporting
            that exact judgment. Say "基线暂未被已核验证据推翻" instead.
          - Do not say public channels had no evidence, no public evidence was
            found, or no verified public updates unless the research output
            contains explicit checked-source coverage. Prefer "本轮可用证据未
            支撑新增判断".
          - For source-limited table rows, do not use words such as
            稳定、无变化、维持、沿用、继续主打、无扰动, or English equivalents
            like stable / unchanged / keep as-is. Use cautious implications
            such as "暂不作为优先跟进依据", "需要补充来源后再调整判断", or
            "可先保持观察，不把它当作已确认变化".
          - Do not name specific sources in the source-limit section unless
            extracted signals cite those exact sources with enough context to
            connect the source to the signal. If sources are not explicitly
            tied to rows, say "本轮可用材料未提供足够来源细节" instead of
            listing media, official sites, apps, or channels.
          - Preserve the user's requested structure: first say whether there are
            new signals, then account x dimension table, changes vs baseline,
            signal strength, high/medium/low priority, and who to follow up
            with today.
          - Do not invent leadership, funding, pricing, hiring, partnership,
            complaint, revenue, traffic, or ranking numbers. Use UNKNOWN or
            "未核验" when evidence is missing.
          - For Chinese requests, write concise Simplified Chinese suitable for
            a sales group. Avoid English headings unless the user asked.

          Output structure:
          ## 先说结论
          ## 账户 x 维度表
          ## 和上次基线相比
          ## 信号强度与优先级
          ## 今天该跟进谁
          ## 来源限制 / 未核验点

          End with:
          INTEL_VERDICT: {{ outputs.verdict }}
    - id: store_brief
      label: "存储简报"
      label_en: "Store brief"
      kind: tool_call
      tool: memory_save
      tool_allowlist: [memory_save]
      depends_on: [intel_brief_audit, intel_clarify, verdict]
      on_failure: store_brief_fallback
      tool_args:
        path: "memory/meta-competitive-intel.md"
        mode: append
        content: |
          ## Competitive intel meta run

          Context:
          {{ outputs.get('intel_context', '') | truncate(1800) }}

          Verdict:
          {{ outputs.get('verdict', '') }}

          Final brief excerpt:
          {{ outputs.get('intel_brief_audit', '') | truncate(3000) }}
    - id: store_brief_fallback
      label: "存储简报兜底"
      label_en: "Store brief fallback"
      kind: llm_chat
      with:
        system: "You produce an internal no-op fallback when competitive-intel memory persistence is unavailable."
        task: |
          Memory persistence was unavailable. Return exactly:
          MEMORY_STORE_SKIPPED
          Do not mention this to the user.
    - id: export_docx
      label: "导出 DOCX"
      label_en: "Export DOCX"
      kind: skill_exec
      skill: docx
      depends_on: [intel_brief_audit, intel_clarify]
      when: "(inputs.get('collected', {}).get('intel_clarify', {}).get('export_docx', 'NO') == 'YES') or ('EXPORT_DOCX_REQUESTED: yes' in outputs.get('preferences', ''))"
      with:
        markdown: "{{ outputs.intel_brief_audit }}"
        output_path: "/tmp/competitive_intel_{{ inputs.get('collected', {}).get('intel_clarify', {}).get('accounts', 'untitled') | slugify | truncate(60) }}.docx"
---

# meta-competitive-intel

Connector / competitive-intel meta-skill. Monitors one to a handful of
target companies across pricing, product, leadership, hiring, and news
dimensions; extracts grounded signals; classifies a verdict; produces
a brief with concrete actions. Always read-only — never sends emails,
posts, or modifies tracker data.

## Composition philosophy — multi-skill bundled orchestration

This meta-skill uses **only OpenSquilla-bundled atomic skills** plus
the five built-in step kinds — no external dependencies. The DAG calls
into **5 distinct bundled atomic skills**:

| Skill | Step(s) | Role in the DAG |
|---|---|---|
| `multi-search-engine` | `web_research`, `web_research_target_1..3`, `web_research_retry` | Primary, target-level, and fallback research source, fed by LLM-generated short search queries rather than raw target grids |
| `deep-research` | `deep_dive` | Extra rounds for `SINGLE_DEEP` mode only |
| `memory` | `recall_baseline`, `store_brief` | Cross-session continuity. `recall_baseline` pulls the last brief from durable memory automatically so `baseline_diff` works even when the user didn't paste a baseline; `store_brief` writes this run for next time. **This pair effectively delivers what the proposed `state:` primitive would give us.** |
| `xlsx` | `signals_xlsx` | When the user explicitly asks for a spreadsheet / `xlsx` / download / export, export the signal table + baseline diff as a workbook |
| `docx` | `export_docx` | Optional final DOCX export |

Step kinds used: `llm_chat`, `llm_classify`, `user_input`, `skill_exec`,
`agent`.

Before search, `search_strategy` uses the LLM to translate structured intel
context into compact `SEARCH_QUERY` lines with target aliases and product
names. The flow then adds focused target-specific searches for the first
three monitored targets, so a broad competitive-intel request does not depend
on one generic multi-company result. This keeps generalized inputs such as
Chinese company names, baseline-diff requests, and "all dimensions" replies
from becoming brittle YAML-like search strings.

Direct URL fetching of competitor pages is intentionally out of scope
for this skill — the search results from `web_research` are normally
enough, and adding URL-scrape would require a compliance-aware fetcher
not currently bundled. If the user wants page-level detail, they can
paste the page content into the next turn.

Persistence to Notion / external knowledge bases is also out of scope:
the deliverable is the markdown emitted by `deliver_intel_brief`; the
user copies it wherever they want.

## Mode design

Four depth labels via `llm_classify: depth`:

- `SINGLE_DEEP` — one target, multi-round deep-research, full
  signal table, full actions. Best for "tell me everything about
  $competitor's last quarter."
- `MULTI_QUICK` — 2-5 accounts, scan-level coverage, top-10 signal
  table. Best for "what did these 5 do this month?"
- `DIFF_VS_BASELINE` — baseline text was pasted, the run leads with
  the diff section. Best for "what's new since I last looked?"
- `EXEC_BRIEF` — 5-bullet executive summary + verdict + top 3
  actions, nothing else. Best for "give me something to forward to
  the CEO."

## Honest limitations (first-wave)

- **No `state:` primitive.** Baselines are pasted each turn; the
  proposed `state:` would persist last run's signals automatically.
- **No `foreach`.** The first three targets get focused search lanes; beyond
  that, remaining targets share the broad query context. With `foreach`, each
  target would get its own isolated step + audit trail per target.
- **No alerting.** The skill produces a brief on demand; it doesn't
  push notifications. A future combination with `cron` (bundled) +
  the proposed `event_trigger` primitive would give a "monitor this
  every Monday" mode.
