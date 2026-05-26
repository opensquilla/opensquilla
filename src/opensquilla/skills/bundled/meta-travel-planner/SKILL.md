---
name: meta-travel-planner
description: "Use this meta-skill instead of answering directly when the user needs a trip plan, travel itinerary, business-trip schedule, or day-by-day travel brief that benefits from multi-skill orchestration across preference inference, weather, place search, constraint extraction, itinerary drafting, variants, and optional artifact guidance."
kind: meta
meta_priority: 50
always: false
final_text_mode: "step:final_plan"
triggers:
  - "travel plan"
  - "trip plan"
  - "trip itinerary"
  - "travel itinerary"
  - "day-by-day travel"
  - "旅游计划"
  - "出差行程"
  - "行程安排"
  - "规划行程"
  - "帮我安排"
  - "怎么玩"
  - "做个行程"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: trip_preferences
      kind: llm_chat
      with:
        system: "You infer practical travel-planning constraints. Return only the requested contract."
        task: |
          Infer the travel-planning contract from the request. If date, party
          size, budget, pace, or interests are missing, choose practical
          defaults and list them as assumptions.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          DESTINATION: <city/region>
          DATES: <dates or assumed trip length>
          PARTY: <party size/type>
          BUDGET: <budget level>
          PACE: <relaxed|balanced|packed>
          INTERESTS:
            - <interest>
          CONSTRAINTS:
            - <constraint or assumption>
    - id: weather
      kind: skill_exec
      skill: weather
      depends_on: [trip_preferences]
      with:
        location: "{{ outputs.trip_preferences | truncate(512) }}"
        days: 3
        max_chars: 2200
    - id: poi
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [trip_preferences]
      with:
        query: "{{ outputs.trip_preferences | truncate(512) }} sights restaurants transport hours neighborhoods"
        engines: [brave, duckduckgo]
        max_results: 15
    - id: constraints
      kind: llm_chat
      depends_on: [weather, poi]
      with:
        system: "You convert weather and search results into itinerary constraints."
        task: |
          Extract itinerary constraints from weather and POI results: opening
          hours, transit time assumptions, weather risks, neighborhoods to
          group together, and any likely booking constraints.

          Preferences:
          {{ outputs.trip_preferences | truncate(1200) }}

          Weather:
          {{ outputs.weather | truncate(2000) }}

          POI search:
          {{ outputs.poi | truncate(6000) }}
    - id: itinerary
      kind: llm_chat
      depends_on: [constraints]
      with:
        system: "You write complete, practical travel itineraries. Return only the itinerary."
        task: |
          Build the primary day-by-day itinerary. It must be complete enough
          to use without reading any later step.

          Include:
          - assumptions
          - one section per day with morning / afternoon / evening
          - neighborhood grouping and transit notes
          - food suggestions
          - rain-aware risks and substitutions
          - rough budget notes

          Trip preferences:
          {{ outputs.trip_preferences | truncate(1200) }}

          Weather forecast:
          {{ outputs.weather | truncate(2000) }}

          POI search:
          {{ outputs.poi | truncate(5000) }}

          Constraints:
          {{ outputs.constraints | truncate(3000) }}
    - id: final_plan
      kind: llm_chat
      depends_on: [itinerary, constraints, weather, poi]
      with:
        system: "You assemble complete travel plans for users. Return only the final answer."
        task: |
          Assemble the complete travel product. Do not return only variants.
          Do not include process commentary.
          Return every required section. Keep the whole answer compact enough
          to fit in one model response: 4,500-6,500 characters is preferred.
          If space is tight, shorten day descriptions before omitting the
          variants, evidence, next-step, or artifact sections.

          Required sections:
          1. Assumptions
          2. Primary 3-day itinerary
          3. Weather-aware risks and rain backups
          4. Variants
          5. Budget and booking notes
          6. Evidence and source notes
          7. Next steps

          Preserve concrete timings, neighborhoods, transit grouping, food
          ideas, weather constraints, and budget constraints. Keep each day to
          5-7 highly actionable bullets or a compact schedule. Include:
          - relaxed version
          - efficient/packed version
          - bad-weather backup
          - rough daily budget notes
          - specific checks before booking, including opening-hours checks,
            timed-entry reservations, and transit-pass choice
          - a short note that a styled HTML itinerary can be generated only if
            the user explicitly asks for a file

          If search or weather evidence is thin, state assumptions plainly
          instead of inventing sources. Include map/search links only as
          plain URLs when useful. Use the words Evidence, Source notes,
          Reference checks, Next steps, Verify, HTML, and Report
          only where they fit naturally in the final sections.

          Itinerary:
          {{ outputs.itinerary | truncate(7000) }}

          Constraint notes:
          {{ outputs.constraints | truncate(2500) }}

          Weather evidence:
          {{ outputs.weather | truncate(1600) }}

          POI/source notes:
          {{ outputs.poi | truncate(2000) }}
---

# Travel Planner (Meta-Skill)

Weather + POI/restaurant/transport search + constraints + a complete itinerary
with variants. The default answer is a complete travel plan; HTML export is an
optional handoff when the user explicitly asks for a file.

## Fallback

Manually call weather, multi-search-engine, summarize. If the user explicitly
asks for HTML export, ask the LLM to write a styled `travel-itinerary.html`
and `publish_artifact` it.
