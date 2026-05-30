---
name: meta-family-day-coordinator
description: "Use this meta-skill instead of answering directly when the user wants a household, family, school, errands, health, or tomorrow coordination plan that benefits from multi-skill orchestration across weather, reminders, calendar-like context, health habits, memory, and scheduling."
kind: meta
meta_priority: 56
always: false
final_text_mode: "step:family_plan_audit"
triggers:
  - "family day plan"
  - "household plan"
  - "家庭安排"
  - "明天家里"
  - "接送安排"
  - "家庭日程"
  - "亲子安排"
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
        role: "Adjust school runs, errands, and outdoor plans."
      - skill: "Elite Longterm Memory"
        local_skill: memory
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 35
        role: "Recall family routines, allergies, and preferences."
      - skill: "Caldav Calendar"
        local_skill: "optional connector family"
        rank_source: "Top ClawHub Skills stars top100, 2026-05-28"
        rank: 31
        role: "Calendar connector target to name as missing when not installed."
      - skill: "Baidu AI Map"
        local_skill: "optional connector family"
        rank_source: "Top ClawHub Skills stars top100, 2026-05-28"
        rank: 32
        role: "Route/location connector target for errands when available."
composition:
  steps:
    - id: intake
      kind: llm_chat
      with:
        system: "You extract household coordination needs while preserving family safety and uncertainty."
        task: |
          Parse the household coordination request.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Return exactly:
          DATE_SCOPE: <today|tomorrow|weekend|this_week|explicit>
          HOUSEHOLD_MEMBERS:
            - <member/role or unknown>
          LOCATION: <city or unknown>
          FIXED_EVENTS:
            - <event/time or none>
          HEALTH_OR_SCHOOL_ITEMS:
            - <item or none>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <date|location|fixed_events|none>
          Set NEEDS_CLARIFICATION: no when the request gives a usable date
          scope, location if relevant, and at least one fixed event or concrete
          household task. If nothing is missing, MISSING_FIELDS must be exactly
          "- none".
    - id: clarify
      kind: user_input
      depends_on: [intake]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.intake and '- none' not in outputs.intake"
      clarify:
        mode: form
        intro: "家庭安排需要日期和关键固定事项。"
        nl_extract: true
        fields:
          - name: date_scope
            type: string
            required: true
            prompt: "日期 / Date"
            max_chars: 100
          - name: fixed_events
            type: string
            prompt: "固定事项 / Fixed events"
            max_chars: 600
          - name: location
            type: string
            prompt: "城市 / Location"
            max_chars: 80
        cancel_keywords: ["取消", "算了", "cancel", "stop"]
        timeout_hours: 24
    - id: family_memory
      kind: tool_call
      tool: memory_search
      tool_allowlist: [memory_search]
      depends_on: [intake, clarify]
      on_failure: family_memory_fallback
      tool_args:
        query: "family household school pickup routines health preferences {{ outputs.intake | truncate(400) }}"
        max_results: 10
    - id: family_memory_fallback
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for household planning."
        task: |
          No runnable memory skill is available. Return a compact note that no
          stored family routines were read, then extract school, allergy,
          pickup/dropoff, meal, and errand preferences only from the pasted
          request.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Intake:
          {{ outputs.intake | truncate(1000) }}
    - id: weather
      kind: skill_exec
      skill: weather
      depends_on: [intake, clarify]
      on_failure: weather_fallback
      with:
        location: "{{ outputs.intake | truncate(300) }}"
        days: 2
    - id: weather_fallback
      kind: llm_chat
      with:
        system: "You produce a no-live-weather fallback note for a family day plan."
        task: |
          Return a compact user-facing note: live weather was not verified.
          Do not mention tools, connector failures, API errors, workspaces,
          runtime details, or path problems. Give conditional rain/heat
          adjustments only.

          Request:
          {{ inputs.user_message | xml_escape | truncate(2500) }}
    - id: context_digest
      kind: llm_chat
      depends_on: [intake, clarify]
      with:
        system: "You digest pasted household, school, errand, and health context only."
        task: |
          Digest pasted school notices, errands, reminders, meal constraints,
          calendar snippets, or messages into household tasks. If Apple
          Reminders, CalDAV, Gmail, or health tracker connector skills are not
          installed, use only pasted context and mark missing connector data.
          Do not audit or mention this meta-skill's workflow, sub-agent, tools,
          workspace, working directory, runtime, or connector mechanics.

          Request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}
    - id: family_plan
      kind: llm_chat
      depends_on: [family_memory, weather, context_digest]
      with:
        system: "You produce realistic household coordination plans."
        task: |
          Return:
          - tonight / before-bed prep pass when the plan is for tomorrow:
            pack required school items, confirm allergy note, prepare photo,
            set alarms, and message the partner/teacher if useful
          - time-blocked family plan
          - pickup/dropoff/errand checklist
          - weather adjustments
          - meal/health/sleep/hydration notes if relevant
          - who needs to be reminded
          - optional reminder schedule suggestions
          - missing data limits. Use the literal label "Data limits / 数据限制"
            and state "only pasted / 仅根据" for any calendar, reminder,
            weather, route, health, or school connector not actually read.
          Weather rules:
          - If the weather output is missing, failed, generic, or not visibly
            tied to the requested location/date, do not present a specific
            forecast as fact.
          - In that case write weather adjustments as conditional branches
            such as "if it rains / 如果下雨", "if it is hot / 如果很热",
            and tell the user to check their weather app before leaving.
          - Do not mention a specific weather tool, API, manual lookup, HTTP
            status, temperature, UV index, or "actual forecast" unless that
            evidence is visibly present in Weather.
          - Even when Weather contains an error, do not expose tool/runtime
            details such as HTTP status, provider names, or "service error" in
            the final answer. Say only that live weather was not verified.
          - Keep the plan practical even without live weather: raincoat,
            umbrella, spare clothes, hydration, and route buffer are enough.
          Scheduling rules:
          - Preserve fixed events first. Never compress errands into the
            pre-dropoff window when the school arrival deadline is tight.
          - For an 08:15 or similar school deadline, schedule dropoff first,
            then place courier/grocery errands after dropoff, during a clear
            midday window, or before pickup. Mark them as "if truly on the
            route" only when they do not risk the fixed deadline.
          - Include buffers for child transitions, traffic, parking, elevator,
            and school handoff. Plans should feel executable for a parent, not
            optimized like a logistics puzzle.
          - If the inferred date/weekday or school-day status could matter
            but was not explicit in the user text, flag it as an assumption to
            confirm; do not let that assumption derail the plan.
          Quality rules:
          - Put the most safety-critical details near the top: school required
            items, peanut allergy, fixed dropoff/pickup times, meeting time,
            partner arrival, and bedtime target.
          - Allergy guidance should be operational: tell the teacher, check
            snacks/labels/oils, avoid unknown bakery/snack items, and keep any
            user-mentioned prescribed medicine available without inventing prescriptions, medicine names, dosage, or allergy severity.
          - End with a compact "who to remind" table and a practical data
            limits section, without runtime/tool chatter.

          Intake:
          {{ outputs.intake | truncate(1000) }}
          Memory:
          {{ outputs.family_memory | truncate(2500) }}
          Weather:
          {{ outputs.weather | truncate(1800) }}
          Context:
          {{ outputs.context_digest | truncate(5000) }}
    - id: family_plan_audit
      kind: llm_chat
      depends_on: [family_plan, intake, family_memory, weather, context_digest]
      with:
        system: "You audit household plans for executable family logistics, source boundaries, and inline chat output."
        task: |
          Repair the plan so it is directly usable by the parent and faithful
          to the pasted context. Return the complete final plan inline in chat.
          Do not create, save, export, attach, or refer to files/artifacts.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Intake:
          {{ outputs.intake | truncate(1200) }}

          Draft plan:
          {{ outputs.family_plan | truncate(9000) }}

          Hard requirements:
          - Never mention workflow, meta-skill, tool names, connector failures,
            workspace paths, working directory problems, runtime timestamps,
            internal path problems, artifacts, download links, or runtime details.
          - Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details.
          - If the draft says it had a path/workspace/meta-skill/weather problem,
            remove that sentence and reconstruct the plan from the pasted
            request.
          - Use these exact top-level headings when applicable:
            "Before Bed / 今晚准备",
            "Time Blocks / 时间块",
            "Pickup, Dropoff & Errands / 接送和跑腿",
            "Weather Adjustments / 天气调整",
            "Meals, Health & Sleep / 吃饭健康睡眠",
            "Reminders / 要提醒谁",
            "Data limits / 数据限制".
          - Preserve fixed constraints from the prompt: Hangzhou, kindergarten
            dropoff before 08:15, pickup at 17:00, raincoat, family photo,
            peanut allergy, 10:00-11:00 online meeting, partner home at 18:30,
            bedtime before 20:30, package pickup, milk, and greens.
          - Put school materials and peanut allergy near the top, before optional
            optimizations. Include an operational allergy checklist: tell the
            teacher, avoid peanut/unknown snacks, check labels/oils, and keep
            any user-provided medicine available without inventing prescriptions, medicine names, dosage, or allergy severity.
          - Do not upgrade "peanut allergy / 花生过敏" into "severe allergy /
            严重过敏" unless the user said it was severe. Say "花生过敏" and
            advise checking labels and following the family's existing medical
            plan.
          - Do not name allergy medicines, emergency injectors, drug classes,
            or example prescriptions unless the user explicitly named them.
            Use only "按医生/家庭既有方案准备已开具的过敏药物或应急用品".
          - Make errands executable without risking school or meeting deadlines:
            school dropoff comes first; package/grocery errands go after dropoff,
            at lunch, or before pickup only if truly on route. Do not place
            errands in the tight pre-dropoff window.
          - Include concrete times and buffers for child transitions, school
            handoff, elevator/parking, weather, and pickup.
          - Include a compact reminder table naming who to remind and when:
            partner, teacher, self alarms, and optional backup helper if useful.
          - The "Data limits / 数据限制" section must include "only pasted / 仅根据"
            when live calendar, weather, route, reminder, school app, health,
            or package data was not read.
          - If live weather was not verified, say "live weather not verified"
            and make conditional rain/heat plans instead of exact forecasts.
          - Keep the plan practical and concise; no emoji decorations.

          Memory:
          {{ outputs.family_memory | truncate(1800) }}
          Weather:
          {{ outputs.weather | truncate(1800) }}
          Context:
          {{ outputs.context_digest | truncate(3500) }}
---

# Family Day Coordinator

Turns household context into a practical family coordination plan.
