---
name: meta-daily-operator-brief
description: "Use this meta-skill instead of answering directly when the current user asks for a practical today/tomorrow operating brief, morning plan, daily priority list, or day schedule that combines pasted calendar/task context, weather, memory, open loops, or optional reminders. Do not use it for account monitoring, family-only logistics, generic productivity advice, setting one reminder, moving one meeting, or isolated scheduling requests that a single tool can handle."
kind: meta
meta_priority: 64
always: false
final_text_mode: "step:final_brief_audit"
triggers:
  - "daily operating brief"
  - "daily brief"
  - "morning brief"
  - "today operating plan"
  - "今天优先级和时间块"
  - "今日简报"
  - "早上简报"
  - "今天先做什么"
  - "今天先帮我排一下优先级"
  - "今天前三优先级"
  - "今天时间块"
  - "今天工作该跟进谁"
  - "今天客户 demo 安排"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: low
    capabilities: [network, memory, scheduler]
    clawhub_top100_composition:
      - skill: "Weather"
        local_skill: weather
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 10
        role: "Add weather and commute implications to the daily plan."
      - skill: "Multi Search Engine"
        local_skill: multi-search-engine
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 11
        role: "Scan current local/work context that may affect the day."
      - skill: "Elite Longterm Memory"
        local_skill: memory
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 35
        role: "Recall preferences, open loops, and recurring priorities."
      - skill: "Gog / Caldav Calendar / Notion"
        local_skill: "optional connector family"
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        role: "Connector targets to name as missing when not installed."
composition:
  steps:
    - id: intake
      kind: llm_chat
      with:
        system: "You extract a daily operating brief contract without asking unless the date or timezone is unusable."
        task: |
          Parse the request into a practical daily brief contract. Treat pasted
          calendar, email, chat, task, or reminder text as source material.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Return exactly:
          DATE_SCOPE: <today|tomorrow|this_week|explicit>
          TIMEZONE: <timezone or ASSUMED: local>
          LOCATION: <city or ASSUMED: unknown>
          SOURCE_STATUS: <pasted_context|needs_external_connectors|mixed|none>
          OUTPUT_STYLE: <compact|detailed>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <date|timezone|none>
          ASSUMPTIONS:
            - <assumption>
          Set NEEDS_CLARIFICATION: no when the request, runtime timestamp, or
          pasted context gives a usable date scope and timezone. If you can
          assume local timezone from the timestamp, use ASSUMED: local and
          MISSING_FIELDS must be exactly "- none".
    - id: clarify
      kind: user_input
      depends_on: [intake]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.intake and '- none' not in outputs.intake"
      clarify:
        mode: form
        intro: "今天的简报缺少关键时间信息。补齐后我会继续整理优先级。"
        nl_extract: true
        fields:
          - name: date_scope
            type: string
            required: true
            prompt: "日期范围 / Date scope"
            max_chars: 80
          - name: timezone
            type: string
            prompt: "时区 / Timezone"
            max_chars: 80
          - name: location
            type: string
            prompt: "城市 / Location"
            max_chars: 80
        cancel_keywords: ["取消", "算了", "cancel", "stop"]
        timeout_hours: 24
    - id: memory_recall
      kind: tool_call
      tool: memory_search
      tool_allowlist: [memory_search]
      depends_on: [intake, clarify]
      on_failure: memory_recall_fallback
      tool_args:
        query: "daily priorities open loops preferences {{ outputs.intake | truncate(400) }}"
        max_results: 8
    - id: memory_recall_fallback
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for a daily operating brief."
        task: |
          No runnable memory skill is available. Return a compact note that no
          stored preferences or open loops were read, then extract any recurring
          preferences or open loops only from the pasted request.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Intake:
          {{ outputs.intake | truncate(1000) }}
    - id: weather_check
      kind: skill_exec
      skill: weather
      depends_on: [intake, clarify]
      on_failure: weather_check_fallback
      with:
        location: "{{ outputs.intake | truncate(400) }}"
        days: 2
    - id: weather_check_fallback
      kind: llm_chat
      with:
        system: "You produce a no-live-weather fallback note for a daily brief."
        task: |
          Return a compact user-facing note: live weather was not verified.
          Do not mention tools, connector failures, API errors, workspaces, or
          runtime details. Give generic commute buffers only.

          Request:
          {{ inputs.user_message | xml_escape | truncate(2500) }}
    - id: context_digest
      kind: llm_chat
      depends_on: [intake, clarify]
      with:
        system: "You digest pasted daily calendar, task, email, and chat context only."
        task: |
          Build a compact digest from pasted calendar/email/task/chat context.
          If connector skills such as Gmail, CalDAV, Apple Reminders, Notion,
          Trello, or Slack are not installed, do not claim live access; use
          only the user's pasted context and name missing connector inputs.
          Do not audit or mention the meta-skill's own workflow, sub-agent,
          tools, workspace, working directory, runtime, or connector mechanics.
          Do not say you had a path or working-directory problem.

          Request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}

          Intake:
          {{ outputs.intake | truncate(1000) }}
    - id: news_scan
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [intake]
      on_failure: news_scan_fallback
      with:
        query: "{{ outputs.intake | truncate(220) }} local commute weather market work news"
        engines: [duckduckgo, brave]
        max_results: 8
    - id: news_scan_fallback
      kind: llm_chat
      with:
        system: "You produce a no-live-news/search fallback note for a daily brief."
        task: |
          Return a compact user-facing note: live local/news/search context was
          not verified. Do not mention tools, connector failures, API errors,
          workspaces, or runtime details.

          Request:
          {{ inputs.user_message | xml_escape | truncate(2500) }}
    - id: final_brief
      kind: llm_chat
      depends_on: [memory_recall, weather_check, context_digest, news_scan]
      with:
        system: "You produce concise daily operating briefs that users can act on immediately."
        task: |
          Produce the final daily brief in the user's language. Include:
          1. Top 3 priorities
          2. Calendar/task risks. Use the literal label "Risk / 风险 / 冲突"
             and name any schedule conflicts, delay risk, or impossible
             sequencing.
          3. Weather/commute implications
          4. Messages or people to follow up with
          5. Suggested time blocks
          6. Missing connector/data limits. Use the literal label "Data
             limits / 数据限制" and state "only pasted / 仅根据" when no live
             calendar, email, reminder, weather, or location connector data was
             actually read.
          7. Optional reminders worth scheduling
          Never expose raw tool/runtime failure details. Do not mention HTTP status codes, API failures, connector stack traces, or search errors.
          Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details.
          When live data is unavailable, summarize only the user-facing limit:
          for example, "live weather/calendar/email was not verified; check the
          relevant app before leaving." Do not narrate which tool failed.
          If the user asks for a morning brief, produce a morning-first plan
          for the day even when the runtime timestamp is later. Do not rewrite
          the answer as an afternoon-only rescue plan unless the user explicitly
          asks for "from now", "剩余时间", or "现在开始".
          Clear one-minute social debts before deep work when they unblock other people,
          especially overdue school, caregiver, vendor, HR, finance, or customer replies
          that can be sent in under 5 minutes. Keep the top priorities focused
          on impact, but let the schedule clear these tiny blockers early.
          If an external reply was due yesterday or is blocking another
          person's planning, clear them in the first 15 minutes of the plan
          unless the user gives a stronger fixed conflict. For follow-ups,
          include ready-to-send message drafts when the user named recipients
          or obvious reply contexts. Include ready-to-send drafts for named recipients or roles;
          examples include school, caregiver, HR, finance, customer, vendor, and quote replies
          when enough context exists.
          Do not rely on remembered or previous-day weather. If live weather
          is unavailable, write "live weather not verified" and give generic
          commute buffers instead of citing stale weather facts.

          Intake:
          {{ outputs.intake | truncate(1200) }}
          Memory:
          {{ outputs.memory_recall | truncate(2500) }}
          Weather:
          {{ outputs.weather_check | truncate(1800) }}
          Context:
          {{ outputs.context_digest | truncate(4000) }}
          News/search:
          {{ outputs.news_scan | truncate(3000) }}
    - id: final_brief_audit
      kind: llm_chat
      depends_on: [final_brief, intake, weather_check, context_digest, news_scan]
      with:
        system: "You audit daily briefs for user-facing quality, no runtime leakage, and explicit risk/data limits."
        task: |
          Repair the brief so it is directly usable by the user and faithful to
          the pasted context. Return only the final brief body.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Intake:
          {{ outputs.intake | truncate(1200) }}

          Draft brief:
          {{ outputs.final_brief | truncate(9000) }}

          Hard requirements:
          - Never mention workflow, meta-skill, tool names, connector failures,
            workspace paths, working directory problems, runtime timestamps,
            internal path problems, or runtime details.
          - If the draft says it had a path/workspace/meta-skill problem,
            remove that sentence and reconstruct the brief from the pasted
            request.
          - If the user asks for "早上能照着做" or a morning brief, keep the
            schedule morning-first. Do not turn it into an afternoon-only
            recovery plan merely because the runtime timestamp is later.
          - In a morning-first plan, do not mark same-day future deadlines as
            missed, overdue, or already late merely because runtime execution
            happened later. For example, a "11:30 要回" finance item should be
            "before 11:30 / 11:30 前完成" unless the user says it was already
            missed.
          {% if inputs.get('user_language') == 'en' %}
          - English-only output: do not include Chinese characters, bilingual
            headings, or slash-paired Chinese labels anywhere in the final
            user-facing brief.
          - Use these exact top-level headings when applicable:
            "Top 3",
            "Time Blocks",
            "Risk / Conflicts",
            "Weather & Commute",
            "Follow-ups",
            "Data limits".
          - The "Risk / Conflicts" section must include fixed-time conflicts,
            deadline/order risks, handoff blockers, and any likely sequence
            failure such as demo preparation being interrupted.
          {% else %}
          - Use these exact top-level headings when applicable:
            "Top 3 / 前三优先级",
            "Time Blocks / 时间块",
            "Risk / 风险 / 冲突",
            "Weather & Commute / 天气与通勤",
            "Follow-ups / 该跟进谁",
            "Data limits / 数据限制".
          - The "Risk / 风险 / 冲突" section must include fixed-time conflicts,
            deadline/order risks, handoff blockers, and any likely sequence
            failure such as demo preparation being interrupted.
          {% endif %}
          - Rank priorities by consequence and reversibility: fixed external
            events with audience/customer impact outrank flexible internal
            work; hard deadlines outrank soft replies; same-day boss
            deliverables stay in the top three when they can be squeezed by
            meetings.
          - When the request contains an external demo, a hard finance
            deadline, and a boss-requested same-day deliverable, the top three
            must cover all three unless the user explicitly says one is
            already done.
          - Put a 5-15 minute quick reply sweep near the start of a morning
            plan for overdue or unblocker replies such as teacher, caregiver,
            HR, quote, finance, and customer messages.
            Do not defer a yesterday teacher/caregiver headcount reply until
            after a late-afternoon demo unless morning is completely blocked.
          {% if inputs.get('user_language') == 'en' %}
          - The "Data limits" section must include the phrase "only pasted"
            when live calendar, email, reminders, exact locations, or original
            message bodies were not read.
          {% else %}
          - The "Data limits / 数据限制" section must include the phrase
            "only pasted / 仅根据" when live calendar, email, reminders,
            exact locations, or original message bodies were not read.
          {% endif %}
          - If live weather was not verified, say "live weather not verified"
            and give generic commute buffers instead of exact weather.
          - If weather is provided, caveat it as source-dependent and do not
            invent precise commute conditions from generic weather alone.
          - Include short ready-to-send drafts for named recipients when enough
            context exists: finance, teacher, Li/Mr. Li, HR, boss, customer, or
            friends.
          - Include a "Drafts" section when the prompt names two or more
            people waiting on replies. Drafts may be short placeholders when
            details are missing, but must preserve uncertainty instead of
            inventing amounts, prices, times, or attendance numbers.
          - Drafts must use placeholders such as [人数], [金额], [日期1],
            [日期2], [时间1], [时间2], [报价版本], or [材料位置] when the prompt
            does not provide those details. Do not invent weekdays, month-day
            dates, interview slots, attendance numbers, quote amounts,
            reimbursement amounts, or file locations.
          - In ready-to-send drafts, remove absolute dates, month-day dates,
            named weekdays, and concrete interview windows unless they were
            explicitly pasted by the user or a cited source. Use
            "[日期1] [时间1] 或 [日期2] [时间2]" instead of guessing candidate
            slots.
          - Keep the answer practical and concise; no emoji decorations.
---

# Daily Operator Brief

Creates a practical daily command brief from available local context, memory,
weather, and pasted or connector-backed calendar/mail/task material.
