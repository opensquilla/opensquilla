---
name: meta-travel-planner
description: "Plan a trip: destination weather + POI/restaurant/transport search + day-by-day itinerary summary + .docx export."
kind: meta
meta_priority: 50
always: false
triggers:
  - "行程"
  - "travel plan"
  - "旅游计划"
  - "出差行程"
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
        engines: [duckduckgo, brave]
        max_results: 10
    - id: itinerary
      skill: summarize
      depends_on: [weather, poi]
      with:
        text: "Weather forecast:\n{{ outputs.weather }}\n\nPOI search:\n{{ outputs.poi }}"
        style: daily_itinerary
        max_words: 1200
    - id: export
      skill: docx
      depends_on: [itinerary]
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        body: "{{ outputs.itinerary }}"
---

# Travel Planner (Meta-Skill)

Weather + POI/restaurant/transport search + day-by-day itinerary, exported
as a printable .docx. Useful for personal trips and assistant-prepared
VIP travel briefs.

## Fallback

Manually call weather, multi-search-engine, summarize, docx create.
