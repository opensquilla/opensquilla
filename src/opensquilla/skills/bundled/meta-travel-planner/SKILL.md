---
name: meta-travel-planner
description: "Use when the user asks for a trip plan, travel itinerary, business-trip schedule, or day-by-day travel brief."
kind: meta
meta_priority: 50
always: false
triggers:
  - "travel plan"
  - "旅游计划"
  - "出差行程"
  - "行程安排"
  - "规划行程"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: trip_preferences
      kind: agent
      skill: sub-agent
      with:
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
      skill: weather
      depends_on: [trip_preferences]
      with:
        location: "{{ outputs.trip_preferences | truncate(512) }}"
    - id: poi
      skill: multi-search-engine
      depends_on: [trip_preferences]
      with:
        query: "{{ outputs.trip_preferences | truncate(512) }} sights restaurants transport hours neighborhoods"
        engines: [brave, duckduckgo]
        max_results: 15
    - id: constraints
      kind: agent
      skill: sub-agent
      depends_on: [weather, poi]
      with:
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
      skill: summarize
      depends_on: [constraints]
      with:
        text: "Trip preferences:\n{{ outputs.trip_preferences }}\n\nWeather forecast:\n{{ outputs.weather }}\n\nPOI search:\n{{ outputs.poi }}\n\nConstraints:\n{{ outputs.constraints }}"
        style: daily_itinerary
        max_words: 1800
    - id: variants
      kind: agent
      skill: sub-agent
      depends_on: [itinerary]
      with:
        task: |
          Add practical variants to this itinerary:
          - relaxed version
          - efficient/packed version
          - bad-weather backup
          - rough daily budget notes

          Keep the original itinerary as the primary plan, then append the
          variants. Include map/search links only as plain URLs when useful.

          Itinerary:
          {{ outputs.itinerary | truncate(6000) }}
    - id: export
      kind: agent
      skill: sub-agent
      depends_on: [variants]
      with:
        task: |
          Render the day-by-day travel itinerary below into a single
          self-contained HTML file, then publish it as a downloadable
          artifact. Reply ONLY with `DONE` after publish_artifact succeeds.

          ## Style requirements
          - One file, all CSS inline in a `<style>` block; no external
            stylesheets, no JS, no remote images.
          - `<meta name="viewport" content="width=device-width, initial-scale=1">`
          - `max-width: 820px` centered body, system sans-serif stack.
          - Top banner with destination title and a short weather summary line.
          - Each day as a card: light background, ~24px padding, rounded
            corners, soft shadow.
          - Activities/meals/transport as `<ul>` lists; subtle 1px dividers
            between items.
          - Mobile: single column under 600px (use a media query).
          - Use semantic HTML (`<h1>`, `<h2>`, `<section>`, `<article>`).

          ## Steps
          1. Convert the markdown itinerary into the HTML structure above.
          2. Write to `travel-itinerary.html` in the workspace directory
             using `write_file`.
          3. Call `publish_artifact(name="travel-itinerary.html")` to
             register the file. The WebUI will surface a download link.
          4. Reply with exactly: `DONE`

          ## Itinerary content (markdown)

          {{ outputs.variants | xml_escape }}
---

# Travel Planner (Meta-Skill)

Weather + POI/restaurant/transport search + constraints + variants, exported
as a self-contained HTML file. Useful for personal trips, business trips, and
assistant-prepared travel briefs.

## Fallback

Manually call weather, multi-search-engine, summarize. For the HTML
export, ask the LLM to write a styled `travel-itinerary.html` and
`publish_artifact` it.
