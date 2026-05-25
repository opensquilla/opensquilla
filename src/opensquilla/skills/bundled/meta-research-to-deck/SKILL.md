---
name: meta-research-to-deck
description: "Use when the user asks for a research-backed presentation, pitch deck, briefing deck, or PPT artifact from a topic or research question."
kind: meta
meta_priority: 70
always: false
triggers:
  - "研究 PPT"
  - "research deck"
  - "汇报 PPT"
  - "pitch deck"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: deck_preferences
      kind: agent
      skill: sub-agent
      with:
        task: |
          Infer the deck contract from the request. Do not ask follow-up
          questions; use sensible defaults and list assumptions.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          AUDIENCE: <reader>
          DECK_TYPE: <briefing|pitch|technical|executive>
          TARGET_SLIDES: <number or range>
          TONE: <tone>
          LANGUAGE: <language>
          ASSUMPTIONS:
            - <assumption>
    - id: search
      skill: multi-search-engine
      depends_on: [deck_preferences]
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        engines: [brave, duckduckgo, tavily]
        max_results: 15
    - id: research
      skill: deep-research
      depends_on: [search]
      with:
        question: "{{ inputs.user_message | xml_escape | truncate(512) }}"
        sources: "{{ outputs.search }}"
        rounds: 2
    - id: storyline
      kind: agent
      skill: sub-agent
      depends_on: [research]
      with:
        task: |
          Convert the research into a presentation storyline. Prefer a clear
          arc such as problem -> evidence -> insight -> recommendation. Each
          slide should have a takeaway title, not a generic topic label.

          Deck preferences:
          {{ outputs.deck_preferences | truncate(1200) }}

          Research:
          {{ outputs.research | truncate(8000) }}
    - id: slide_outline
      skill: summarize
      depends_on: [storyline]
      with:
        text: "Preferences:\n{{ outputs.deck_preferences }}\n\nStoryline:\n{{ outputs.storyline }}\n\nResearch:\n{{ outputs.research }}"
        style: slide_outline
        max_words: 1400
    - id: speaker_notes
      kind: agent
      skill: sub-agent
      depends_on: [slide_outline]
      with:
        task: |
          Write concise speaker notes for each slide in this outline. Keep each
          note to 2-4 bullets and include source reminders where useful.

          Slide outline:
          {{ outputs.slide_outline | truncate(6000) }}
    - id: slide_quality_gate
      kind: agent
      skill: sub-agent
      depends_on: [slide_outline, speaker_notes]
      with:
        task: |
          Review the deck outline before rendering. Verify:
          - every slide title states a takeaway
          - the deck has an opening summary and closing recommendation
          - unsupported claims are removed or caveated
          - speaker notes align with slides

          Return a final slide outline ready for PPTX rendering. Include the
          speaker notes inline under each slide. No process commentary.

          Outline:
          {{ outputs.slide_outline | truncate(6000) }}

          Speaker notes:
          {{ outputs.speaker_notes | truncate(4000) }}
    - id: deck
      skill: pptx
      depends_on: [slide_quality_gate]
      with:
        title: "{{ inputs.user_message | xml_escape | truncate(128) }}"
        outline: "{{ outputs.slide_quality_gate }}"
---

# Research-to-Deck (Meta-Skill)

Turns a research question into a PowerPoint deck. The workflow infers the
audience, builds a storyline, adds speaker notes, and validates the outline
before rendering the artifact.

## Fallback

LLM should sequentially call search, deep-research, summarize, and
`pptx` create-from-scratch.
