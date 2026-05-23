---
name: meta-travel-planner
description: "Plan a trip: destination weather + POI/restaurant/transport search + day-by-day itinerary summary + self-contained HTML export (browser-openable, mobile-responsive, no external resources)."
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
    - id: weather
      skill: weather
      with:
        location: "{{ inputs.user_message | xml_escape | truncate(128) }}"
    - id: poi
      skill: multi-search-engine
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(256) }} sights restaurants transport"
        engines: [brave, duckduckgo]
        max_results: 10
    - id: itinerary
      skill: summarize
      depends_on: [weather, poi]
      with:
        text: "Weather forecast:\n{{ outputs.weather }}\n\nPOI search:\n{{ outputs.poi }}"
        style: daily_itinerary
        max_words: 1200
    - id: export
      kind: agent
      skill: sub-agent
      depends_on: [itinerary]
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

          {{ outputs.itinerary | xml_escape }}
---

# Travel Planner (Meta-Skill)

Weather + POI/restaurant/transport search + day-by-day itinerary, exported
as a self-contained HTML file (browser-openable, mobile-responsive, no
external resources). Useful for personal trips and assistant-prepared VIP
travel briefs.

## Fallback

Manually call weather, multi-search-engine, summarize. For the HTML
export, ask the LLM to write a styled `travel-itinerary.html` and
`publish_artifact` it.
