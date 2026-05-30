---
name: meta-account-watch
description: "Use this meta-skill instead of answering directly when a Connector / sales / BD / competitive-intel user wants to monitor one or several target accounts (competitors, prospects, partners) across pricing, product, leadership, hiring, partnerships, funding, and news dimensions over a defined time window. Prefer this over daily-operator briefs when the user asks to watch competitors/accounts, compare against a prior baseline, prepare a sales-group update, or decide who to follow up with because of account signals. The skill fans out web + deep research per account, extracts signals from search results, diffs against a pasted baseline, classifies the overall signal level (NO_NEW_SIGNAL through URGENT), and produces a brief with concrete next-actions. Read-only — never sends emails or posts."
kind: meta
meta_priority: 72
always: false
final_text_mode: "step:watch_brief_audit"
triggers:
  - "watch this account"
  - "monitor competitor"
  - "竞品监控"
  - "account watch"
  - "本周对手动作"
  - "competitive intel"
  - "对标公司动态"
  - "competitor brief"
  - "track these companies"
  - "盯一下这两个对手"
  - "盯一下这些对手"
  - "最近有没有值得提醒老板的动作"
  - "销售群里的简报"
  - "能发到销售群里的简报"
  - "和基线相比"
  - "和上次基线相比"
  - "账户 x 维度表"
  - "今天该跟进谁"
  - "最近一个月的产品"
  - "产品、价格"
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
        role: "Gather current account, competitor, product, hiring, and pricing signals."
      - skill: "Deep Researcher / deep research family"
        local_skill: deep-research
        rank_source: "ClawHub research-skill family, verified via current search results"
        role: "Run a focused account dive when one company needs deeper coverage."
      - skill: "Excel / XLSX"
        local_skill: xlsx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 21
        role: "Export signal tables for account review when requested."
      - skill: "Word / DOCX"
        local_skill: docx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 28
        role: "Export an executive account brief when requested."
composition:
  steps:
    - id: preferences
      kind: llm_chat
      with:
        system: "You extract account-watch preferences. Return only the requested contract."
        task: |
          Extract the watch brief.

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
    - id: watch_clarify
      kind: user_input
      depends_on: [preferences]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.preferences"
      clarify:
        mode: form
        intro: |
          账户监控还缺一些信息，麻烦补齐 / Need a few details to run the watch.
        nl_extract: true
        fields:
          - name: accounts
            type: string
            required: true
            prompt: "要监控的公司（逗号分隔；建议 1-5 个）/ Companies to watch (comma-separated; 1-5)"
            max_chars: 240
          - name: dimensions
            type: string
            required: true
            prompt: "关注维度（逗号分隔：PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS, PARTNERSHIPS, FUNDING）/ Dimensions"
            max_chars: 200
          - name: time_window
            type: enum
            choices: [LAST_WEEK, LAST_MONTH, LAST_QUARTER]
            default: LAST_MONTH
            prompt: "时间窗口 / Time window"
          - name: baseline_text
            type: string
            prompt: "上次监控结论（粘贴；可留空）/ Prior baseline brief (optional, paste)"
            max_chars: 4000
          - name: language
            type: enum
            choices: [en, zh, mixed]
            default: en
            prompt: "输出语言 / Output language"
          - name: export_docx
            type: enum
            choices: ["YES", "NO"]
            default: "NO"
            prompt: "DOCX 导出 / Export to DOCX"
        cancel_keywords: ["算了", "取消", "cancel", "stop", "abort"]
        timeout_hours: 24
    - id: depth
      kind: llm_classify
      depends_on: [preferences, watch_clarify]
      output_choices:
        - SINGLE_DEEP
        - MULTI_QUICK
        - DIFF_VS_BASELINE
        - EXEC_BRIEF
      with:
        text: |
          Classify the watch depth.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(800) }}

          Clarification:
          {{ inputs.get('collected', {}).get('watch_clarify', {}) | tojson }}

          Decision rules:
          - SINGLE_DEEP: exactly one account in scope, user wants
            comprehensive multi-source dive.
          - MULTI_QUICK: 2-5 accounts, scan-level coverage per account.
          - DIFF_VS_BASELINE: baseline text was pasted; the value of
            this run is the diff, not the absolute snapshot.
          - EXEC_BRIEF: user asks for a 5-bullet executive-style summary
            for someone else to skim; minimise raw research dump.
    - id: watch_context
      kind: llm_chat
      depends_on: [depth, watch_clarify]
      with:
        system: "You extract the durable account-watch context from the raw user request and any clarification payload. Return only the requested contract. Preserve pasted baseline facts exactly enough for later diffing. Never infer current signals from baseline facts."
        task: |
          Build the account-watch context that all later steps must use.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}

          Clarification:
          {{ inputs.get('collected', {}).get('watch_clarify', {}) | tojson | truncate(1200) }}

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
            watch_clarify did not run.
          - Keep baseline facts separate from current signals. They are
            comparison material, not evidence that something happened now.
          - If account or dimension names are visible in the raw user request,
            do not ask for them again.
    - id: recall_baseline
      kind: agent
      skill: memory
      depends_on: [depth, watch_context, watch_clarify]
      on_failure: recall_baseline_fallback
    - id: recall_baseline_fallback
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for account watch."
        task: |
          No durable prior account brief was read. Continue using only pasted
          baseline text and current visible research evidence. Do not mention
          runtime errors to the user.
    - id: web_research
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [depth, watch_context]
      on_failure: web_research_fallback
      with:
        query: "{{ outputs.get('watch_context', '') | truncate(900) }} {{ inputs.user_message | truncate(220) }} current product pricing campaign hiring partnership funding news"
        engines: [brave, tavily, duckduckgo]
        max_results: 15
    - id: web_research_fallback
      kind: llm_chat
      with:
        system: "You produce a no-web fallback note for account watch."
        task: |
          Web research was not available. Extract accounts, baseline facts,
          requested dimensions, time window, and decision audience only from
          the pasted request. Mark current external signals as not verified.
          Do not expose tool names, paths, stack traces, connector wording, or
          runtime failures.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}
    - id: summarize_web
      kind: llm_chat
      depends_on: [web_research, watch_context]
      with:
        system: "You compress account-watch research into a source-faithful signal digest. Do not expose tool names, connector failures, paths, stack traces, or runtime details."
        task: |
          Compress the web research into a compact account-watch digest.

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(2000) }}

          Web research:
          {{ outputs.web_research | truncate(5000) }}

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
          - Do not expose tool names, search errors, connector wording,
            workspace paths, or runtime details.
    - id: deep_dive
      kind: skill_exec
      skill: deep-research
      depends_on: [depth, watch_context]
      when: "outputs.depth == 'SINGLE_DEEP'"
      with:
        query: "{{ outputs.get('watch_context', '') | truncate(900) }} comprehensive account watch"
        depth: "deep"
        max_rounds: 3
    - id: enrich_accounts
      kind: llm_chat
      depends_on: [depth, web_research, summarize_web, watch_context, watch_clarify]
      with:
        system: "You produce firmographic-style account briefs from web search results. Be conservative; mark UNKNOWN when sources disagree. Never invent leadership names or numbers."
        task: |
          Produce one brief per account, grounded ONLY in web research.

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(2000) }}

          Compressed web summary (preferred):
          {{ outputs.get('summarize_web', '') | truncate(2000) }}

          Raw web research (fallback context):
          {{ outputs.get('web_research', '') | truncate(2500) }}

          For each account output exactly:

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
      kind: llm_chat
      depends_on:
        - depth
        - web_research
        - summarize_web
        - deep_dive
        - enrich_accounts
        - watch_context
        - watch_clarify
      with:
        system: "You extract concrete signals from research results, organised by account × dimension. Be specific (price changes with numbers, leadership moves with names, product launches with feature names). Never invent signals; only emit grounded ones."
        task: |
          Extract signals.

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(2500) }}

          Compressed web summary (preferred):
          {{ outputs.get('summarize_web', '') | truncate(3000) }}

          Web research:
          {{ outputs.get('web_research', '') | truncate(3000) }}

          Deep dive (if SINGLE_DEEP):
          {{ outputs.get('deep_dive', '') | truncate(2500) }}

          Account enrichment:
          {{ outputs.get('enrich_accounts', '') | truncate(2000) }}

          Dimensions to focus on:
          {{ outputs.get('watch_context', '') | truncate(1200) }}

          Output a markdown table:
          account | dimension | signal | strength (LOW|MED|HIGH) |
          source_hint | one_line_implication.

          Rules:
          - Do not return only the table header.
          - If current research has no verified signal for a requested cell,
            emit one row per requested account × dimension with signal
            "未见已核验新信号 / no verified new signal", strength LOW,
            source_hint "source limit / 未核验", and a practical implication.
          - Do not convert PASTED_BASELINE facts into current signals. Baseline
            facts can be mentioned only as comparison context.
          - Preserve account names and requested dimensions from watch_context
            even when web research is sparse.

          Sort by strength desc, then account.
          Drop signals where strength is LOW and the source hint is
          vague ("unconfirmed", "rumour") unless the row is one of the
          requested no-verified-new-signal placeholder rows.
    - id: baseline_diff
      kind: llm_chat
      depends_on: [extract_signals, recall_baseline, depth, watch_context, watch_clarify]
      when: "outputs.depth == 'DIFF_VS_BASELINE' or 'BASELINE_TEXT_PRESENT: yes' in outputs.preferences or (inputs.get('collected', {}).get('watch_clarify', {}).get('baseline_text', '') | length) > 0 or (outputs.get('recall_baseline', '') | length) > 0"
      with:
        system: "You diff the current signals against a baseline brief. The baseline may be pasted text from the user, OR a recalled brief from durable memory (from a prior run of this meta-skill). Surface what's new, what's gone, what shifted."
        task: |
          Diff current signals vs baseline.

          Account-watch context, including PASTED_BASELINE from inputs.user_message:
          {{ outputs.get('watch_context', '') | truncate(2500) }}

          Original user request:
          {{ inputs.user_message | xml_escape | truncate(2200) }}

          Current signals:
          {{ outputs.extract_signals | truncate(3000) }}

          Baseline — pasted by user (if any):
          {{ inputs.get('collected', {}).get('watch_clarify', {}).get('baseline_text', '') | xml_escape | truncate(2000) }}

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
          - Treat PASTED_BASELINE in watch_context as the primary baseline
            when watch_clarify is empty.
          - If current signals are all source-limited, say "未见已核验新增"
            rather than inventing a change.
          - Still list unchanged baseline claims under Shifted/Unchanged
            wording when useful for the user's requested comparison.
    - id: verdict
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
          Classify the overall watch verdict.

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
            incident at the watched account that the user can take
            advantage of OR must defend against).
    - id: recommend_actions
      kind: llm_chat
      depends_on: [verdict, extract_signals, baseline_diff, watch_context, watch_clarify]
      with:
        system: "You produce concrete next-actions grounded in the verdict and signals. Each action must reference a specific signal."
        task: |
          Produce next-actions.

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(1500) }}

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
          "Continue watching — re-run in <time_window>".
    - id: signals_xlsx
      kind: skill_exec
      skill: xlsx
      depends_on: [extract_signals, verdict, watch_clarify]
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
        output_path: "/tmp/account_watch_signals_{{ inputs.get('collected', {}).get('watch_clarify', {}).get('accounts', 'untitled') | slugify | truncate(60) }}.xlsx"
    - id: deliver_watch_brief
      kind: llm_chat
      depends_on:
        - preferences
        - watch_clarify
        - watch_context
        - depth
        - extract_signals
        - baseline_diff
        - verdict
        - recommend_actions
        - recall_baseline
        - summarize_web
        - signals_xlsx
      with:
        system: "You assemble the final account-watch brief. Return the complete brief inline in chat. Do not create, save, export, attach, or point primarily to an artifact unless the user explicitly asked for a file export. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details. Lead with the verdict, then signals, baseline diff, and actions."
        task: |
          Assemble the final watch brief.

          Verdict: {{ outputs.verdict }}
          Depth: {{ outputs.depth }}

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(2000) }}

          Structure depends on depth:

          - EXEC_BRIEF → only the 5-bullet exec summary, then verdict
            line, then top 3 actions. Nothing else.
          - SINGLE_DEEP → full structure below.
          - MULTI_QUICK → full structure below, but trim signal table
            to top 10 rows.
          - DIFF_VS_BASELINE → lead with the baseline_diff section,
            then signals, then actions.

          Full structure:

          # <Verdict emoji> <Verdict label> — Account Watch <date range>

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
          WATCH_VERDICT: {{ outputs.verdict }}
    - id: watch_brief_audit
      kind: llm_chat
      depends_on:
        - deliver_watch_brief
        - extract_signals
        - baseline_diff
        - recommend_actions
        - verdict
        - preferences
        - watch_context
      with:
        system: "You are the final quality gate for an account-watch brief. Return only the cleaned final answer the user should read. Do not explain the audit. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, runtime details, or internal artifacts."
        task: |
          Rewrite the draft below into a clean account-watch brief for the user.

          Account-watch context:
          {{ outputs.get('watch_context', '') | truncate(2500) }}

          Draft brief:
          {{ outputs.get('deliver_watch_brief', '') | truncate(8000) }}

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
          WATCH_VERDICT: {{ outputs.verdict }}
    - id: store_brief
      kind: agent
      skill: memory
      depends_on: [watch_brief_audit, watch_clarify, verdict]
      on_failure: store_brief_fallback
    - id: store_brief_fallback
      kind: llm_chat
      with:
        system: "You produce an internal no-op fallback when account-watch memory persistence is unavailable."
        task: |
          Memory persistence was unavailable. Return exactly:
          MEMORY_STORE_SKIPPED
          Do not mention this to the user.
    - id: export_docx
      kind: skill_exec
      skill: docx
      depends_on: [watch_brief_audit, watch_clarify]
      when: "(inputs.get('collected', {}).get('watch_clarify', {}).get('export_docx', 'NO') == 'YES') or ('EXPORT_DOCX_REQUESTED: yes' in outputs.get('preferences', ''))"
      with:
        markdown: "{{ outputs.watch_brief_audit }}"
        output_path: "/tmp/account_watch_{{ inputs.get('collected', {}).get('watch_clarify', {}).get('accounts', 'untitled') | slugify | truncate(60) }}.docx"
---

# meta-account-watch

Connector / competitive-intel meta-skill. Monitors one to a handful of
target accounts across pricing, product, leadership, hiring, and news
dimensions; extracts grounded signals; classifies a verdict; produces
a brief with concrete actions. Always read-only — never sends emails,
posts, or modifies tracker data.

## Composition philosophy — multi-skill bundled orchestration

This meta-skill uses **only OpenSquilla-bundled atomic skills** plus
the five built-in step kinds — no external dependencies. The DAG calls
into **5 distinct bundled atomic skills**:

| Skill | Step(s) | Role in the DAG |
|---|---|---|
| `multi-search-engine` | `web_research` | Primary research source across all accounts |
| `deep-research` | `deep_dive` | Extra rounds for `SINGLE_DEEP` mode only |
| `memory` | `recall_baseline`, `store_brief` | Cross-session continuity. `recall_baseline` pulls the last brief from durable memory automatically so `baseline_diff` works even when the user didn't paste a baseline; `store_brief` writes this run for next time. **This pair effectively delivers what the proposed `state:` primitive would give us.** |
| `xlsx` | `signals_xlsx` | When the user explicitly asks for a spreadsheet / `xlsx` / download / export, export the signal table + baseline diff as a workbook |
| `docx` | `export_docx` | Optional final DOCX export |

Step kinds used: `llm_chat`, `llm_classify`, `user_input`, `skill_exec`,
`agent`.

Direct URL fetching of competitor pages is intentionally out of scope
for this skill — the search results from `web_research` are normally
enough, and adding URL-scrape would require a compliance-aware fetcher
not currently bundled. If the user wants page-level detail, they can
paste the page content into the next turn.

Persistence to Notion / external knowledge bases is also out of scope:
the deliverable is the markdown emitted by `deliver_watch_brief`; the
user copies it wherever they want.

## Mode design

Four depth labels via `llm_classify: depth`:

- `SINGLE_DEEP` — one account, multi-round deep-research, full
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
- **No `foreach`.** When 5 accounts are watched, the LLM steps see
  all 5 in one prompt. With `foreach`, each account would get its own
  isolated step + audit trail per account.
- **No alerting.** The skill produces a brief on demand; it doesn't
  push notifications. A future combination with `cron` (bundled) +
  the proposed `event_trigger` primitive would give a "watch this
  every Monday" mode.
