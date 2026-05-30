---
name: meta-kid-project-planner
description: "Use this meta-skill instead of answering directly when the current user asks for a child-appropriate school project, show-and-tell object, classroom demonstration, science fair idea, hobby kit, or kid-sized creative activity. It keeps ordinary parent/guardian requests short, uses durable child memory when available, refuses unsafe topics, and can generate one child-safe cover illustration when explicitly requested. Do not use it for adult maker projects, generic science explanations, family scheduling, or pasted old project examples."
kind: meta
meta_priority: 60
always: false
final_text_mode: "step:project_pack"
triggers:
  - "school project for my child"
  - "child school project"
  - "kid school project"
  - "science project for my child"
  - "child science project"
  - "kid science project"
  - "science fair"
  - "child science fair"
  - "kid science fair"
  - "weather day at school"
  - "weather project for school"
  - "child needs to bring"
  - "kid needs to bring"
  - "show-and-tell at school"
  - "show and tell at school"
  - "child has a class presentation"
  - "kid has a class presentation"
  - "child class presentation"
  - "kid class presentation"
  - "classroom demonstration for kids"
  - "kid science"
  - "kid project"
  - "plant growth project"
  - "plant growth school project"
  - "孩子做项目"
  - "孩子做手工"
  - "小朋友做手工"
  - "科学课作业"
  - "孩子科学课作业"
  - "help my kid build"
  - "help my child build"
  - "孩子要做火山"
  - "child diy project"
  - "kid diy project"
  - "课外动手项目"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: medium
    capabilities: [network, filesystem-write, artifact-write, image-generation]
    clawhub_top100_composition:
      - skill: "Multi Search Engine"
        local_skill: multi-search-engine
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 11
        role: "Lightweight reference check for safe child-friendly project ideas; capped to a few results so ordinary prompts stay fast."
      - skill: "Weather"
        local_skill: weather
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        role: "Heavy route only: use a forecast when the user gives a real location and asks for outdoor/weather planning."
      - skill: "PowerPoint / PPTX"
        local_skill: pptx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        role: "Heavy route only: create a deck only when the user explicitly asks for slides or PPT."
      - skill: "Image Generation"
        local_skill: image_generate
        role: "Create one school-ready cover illustration when the user asks for 配图, image, illustration, poster, or a visual pack."
composition:
  steps:
    - id: preferences
      kind: llm_chat
      with:
        system: "You extract kid-project preferences. Return only the requested contract. Refuse clearly unsafe projects by setting PROJECT_SAFE: no."
        task: |
          Extract the kid-project brief.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1800) }}

          Clarification policy:
          - If the request already includes a project topic, child age or age
            band, and deadline or rough time window, set
            NEEDS_CLARIFICATION: no and MISSING_FIELDS: none.
          - Budget, exact presentation format, exact weather, and exact
            sunshine direction can remain explicitly unknown assumptions; do
            not block on them and do not invent precise values.
          - For common school projects, proceed with explicit assumptions or
            UNKNOWN markers instead of asking a form unless safety or the core
            topic is unclear.

          Return exactly:
          TOPIC: <short project description>
          AGE_BAND: <PRE_K|EARLY_GRADE|TWEEN|TEEN|UNKNOWN>
          DEADLINE_DAYS: <integer days until due, or UNKNOWN>
          BUDGET_BAND: <SHOESTRING|MODEST|COMFORTABLE|UNKNOWN>
          PARENT_SUPERVISION: <SOLO|LIGHT|HANDS_ON|UNKNOWN>
          LANGUAGE: <en|zh|mixed>
          PROJECT_SAFE: <yes|no>
          UNSAFE_REASON: <one phrase if PROJECT_SAFE is no, else none>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <topic|age_band|deadline|none>
          ASSUMPTIONS:
            - <assumption>

    - id: project_clarify
      kind: user_input
      depends_on: [preferences]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.preferences and 'PROJECT_SAFE: yes' in outputs.preferences and 'MISSING_FIELDS:\n  - none' not in outputs.preferences"
      clarify:
        mode: form
        intro: |
          再确认核心信息，然后给你一个短项目方案 / A few core details and I'll build a short project plan.
        nl_extract: true
        fields:
          - name: topic
            type: string
            required: true
            prompt: "项目主题 / Project topic"
            max_chars: 200
          - name: age_band
            type: enum
            required: true
            choices: [PRE_K, EARLY_GRADE, TWEEN, TEEN]
            prompt: "孩子年龄段 / Child age band"
          - name: deadline_days
            type: int
            min: 0
            max: 365
            default: 1
            prompt: "几天后要交 / Days until due"
        cancel_keywords: ["算了", "换个项目", "cancel", "stop"]
        timeout_hours: 48

    - id: feasibility
      kind: llm_classify
      depends_on: [preferences, project_clarify]
      output_choices:
        - STRAIGHTFORWARD
        - NEEDS_ADULT_HELP
        - NEEDS_SHOPPING
        - SAFETY_REVIEW_REQUIRED
        - INAPPROPRIATE
      with:
        text: |
          Classify project feasibility for this child.

          Preferences:
          {{ outputs.get('preferences', '') | truncate(900) }}
          Clarification:
          {{ inputs.get('collected', {}).get('project_clarify', {}) | tojson }}

          Decision rules:
          - INAPPROPRIATE: weapons, fireworks, drugs, harmful chemistry,
            self-harm-adjacent themes, or other clearly unsafe topics.
          - SAFETY_REVIEW_REQUIRED: heat, sharp blades, mains electricity,
            or moderately reactive chemistry.
          - NEEDS_SHOPPING: likely requires a special kit or specialty material.
          - NEEDS_ADULT_HELP: age-appropriate but needs an adult hand.
          - STRAIGHTFORWARD: safe household or classroom project.

    - id: project_route
      kind: llm_classify
      depends_on: [preferences, feasibility, project_clarify]
      output_choices:
        - LIGHT_PROJECT_PACK
        - HEAVY_PROJECT_PACK
      with:
        text: |
          Route this child project request.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1800) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(900) }}

          Feasibility:
          {{ outputs.get('feasibility', '') }}

          Choose LIGHT_PROJECT_PACK for:
          - one-evening, tonight, due tomorrow, few steps, simple, low-mess
          - show-and-tell, class presentation, weather day, small worksheet
          - requests where the user wants a quick usable answer, not research

          Choose HEAVY_PROJECT_PACK only when the user explicitly asks for:
          - full pack, detailed steps, thorough research, sources, web lookup
          - multi-day science fair plan, rubric, safety review, materials table
          - live weather forecast with a real location, outdoor scheduling
          - slide deck, PPT, export, printable file, vocabulary cards
          - feasibility says SAFETY_REVIEW_REQUIRED or NEEDS_SHOPPING

    - id: redirect_unsafe
      kind: llm_chat
      depends_on: [preferences, feasibility]
      when: "'PROJECT_SAFE: no' in outputs.preferences or outputs.feasibility == 'INAPPROPRIATE'"
      with:
        system: "You write a gentle, non-shaming redirect when a project topic is unsafe. Offer 3 safer alternatives in the same spirit."
        task: |
          Topic:
          {{ inputs.user_message | xml_escape | truncate(500) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(700) }}

          Write:
          1. One sentence acknowledging the curiosity.
          2. One concrete sentence explaining why this version is not a good
             kid project.
          3. Three safe alternatives, each with one line for what the child
             will make or learn.

          Language: match preferences.
          End with:
          UNSAFE_REDIRECT: yes

    - id: recall_past_projects
      kind: agent
      skill: memory
      depends_on: [feasibility, project_clarify]
      when: "outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences"
      on_failure: recall_past_projects_fallback
      with:
        task: |
          Recall durable memory for this child's project planning context.
          Return only remembered facts; do not curate memory files, summarize
          the memory skill workflow, list workspace paths, or write new memory.

          Current request:
          {{ inputs.user_message | xml_escape | truncate(1400) }}

          Search/read MEMORY.md and memory/**/*.md for facts relevant to:
          child age, drawing/writing preferences, parent supervision time,
          prior completed school/science projects, lessons learned, and
          constraints that should affect this new project.

          Return exactly:
          REMEMBERED_CHILD_PROFILE:
            - <fact or none>
          REMEMBERED_PARENT_CONSTRAINTS:
            - <fact or none>
          REMEMBERED_PRIOR_PROJECTS:
            - <project name> — <lesson or none>
          REMEMBERED_PLANNING_RULES:
            - <rule or none>
          MEMORY_LIMITS:
            - <only facts that were missing or uncertain>

    - id: recall_past_projects_fallback
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for child project planning."
        task: |
          No durable project memory was read. Continue using only the pasted
          child age, deadline, materials, budget, supervision, location, and
          project context. Do not mention runtime errors to the user.

    - id: quick_reference
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [feasibility, project_route]
      when: "outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences and ('school project' in (inputs.user_message | lower) or 'school' in (inputs.user_message | lower) or 'science project' in (inputs.user_message | lower) or 'weather' in (inputs.user_message | lower) or 'weather day' in (inputs.user_message | lower) or 'weather project' in (inputs.user_message | lower) or 'show-and-tell' in (inputs.user_message | lower) or 'show and tell' in (inputs.user_message | lower) or 'class presentation' in (inputs.user_message | lower) or 'class' in (inputs.user_message | lower) or '科学课作业' in inputs.user_message or '天气' in inputs.user_message)"
      on_failure: quick_reference_fallback
      with:
        query: "{{ outputs.get('preferences', '') | truncate(220) }} child-safe simple school project one evening observation sheet class presentation"
        engines: [duckduckgo]
        max_results: 3

    - id: quick_reference_fallback
      kind: llm_chat
      with:
        system: "You produce a no-search fallback note for child project planning."
        task: |
          No external project reference was available. Continue using the
          user's request and durable memory only. Do not mention search errors
          or connector details to the user.

    - id: heavy_research
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [project_route, feasibility]
      when: "outputs.get('project_route') == 'HEAVY_PROJECT_PACK' and outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences"
      on_failure: heavy_research_fallback
      with:
        query: "{{ outputs.get('preferences', '') | truncate(260) }} kid science project safe materials step by step source"
        engines: [brave, duckduckgo]
        max_results: 6

    - id: heavy_research_fallback
      kind: llm_chat
      with:
        system: "You produce a no-heavy-research fallback note for child project planning."
        task: |
          Heavy-route research was unavailable. Continue from user-provided
          facts, durable memory, and quick_reference only. Do not mention
          connector details.

    - id: weather_location
      kind: llm_chat
      depends_on: [project_route, preferences, feasibility]
      when: "outputs.get('project_route') == 'HEAVY_PROJECT_PACK' and outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences and ('weather' in (inputs.user_message | lower) or 'forecast' in (inputs.user_message | lower) or 'rain' in (inputs.user_message | lower) or 'temperature' in (inputs.user_message | lower) or '天气' in inputs.user_message or '下雨' in inputs.user_message or '气温' in inputs.user_message)"
      with:
        system: "You extract a real user-supplied weather location. Return only the requested two-line contract."
        task: |
          Extract a city, region, airport code, or unambiguous place supplied
          by the user. Do not use runtime timestamps, timezone labels, source
          names, or workspace paths as locations. If no real place is supplied,
          return UNKNOWN.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1800) }}

          Return exactly:
          DESTINATION: <city/region/place or UNKNOWN>
          LOCATION_SOURCE: <user_request|unknown>

    - id: weather_check
      kind: skill_exec
      skill: weather
      depends_on: [project_route, feasibility, weather_location]
      when: "outputs.get('project_route') == 'HEAVY_PROJECT_PACK' and outputs.feasibility != 'INAPPROPRIATE' and 'DESTINATION: UNKNOWN' not in outputs.get('weather_location', '') and (outputs.get('weather_location', '') | length) > 0"
      on_failure: weather_check_fallback
      with:
        location: "{{ outputs.get('weather_location', '') | truncate(160) }}"
        days: 7

    - id: weather_check_fallback
      kind: llm_chat
      with:
        system: "You produce a no-live-weather fallback note for child project planning."
        task: |
          Live weather was not verified. Continue using only the user's
          supplied light/outdoor/indoor context. Do not infer forecasts,
          temperature ranges, rainfall, balcony direction, sunshine hours, or
          season-specific claims.

    - id: project_pack
      kind: llm_chat
      depends_on:
        - preferences
        - feasibility
        - project_route
        - redirect_unsafe
        - recall_past_projects
        - quick_reference
        - heavy_research
        - weather_check
      with:
        system: "You write the final child-project answer directly. Keep it lightweight, practical, and parent-friendly. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details."
        task: |
          Write the final answer the user should read.

          Original user request:
          {{ inputs.user_message | xml_escape | truncate(3200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(1400) }}

          Feasibility:
          {{ outputs.get('feasibility', '') }}

          Route:
          {{ outputs.get('project_route', '') }}

          Unsafe redirect, if any:
          {{ outputs.get('redirect_unsafe', '') | truncate(1200) }}

          Durable memory / past-project recall:
          {{ outputs.get('recall_past_projects', '') | truncate(1800) }}

          Lightweight project reference, if available:
          {{ outputs.get('quick_reference', '') | truncate(1200) }}

          Heavy-route research, if available:
          {{ outputs.get('heavy_research', '') | truncate(1800) }}

          Weather check, if available:
          {{ outputs.get('weather_check', '') | truncate(900) }}

          If the project is unsafe or inappropriate:
          - Return only the safe redirect from redirect_unsafe, cleaned for
            normal chat.
          - Do not include project instructions for the unsafe topic.

          For safe projects:
          - Return the complete response inline in chat.
          - Do not create, save, export, attach, or claim downloadable files.
          - Never mention workflow, meta-skill, tool names, connector failures,
            workspace paths, or runtime details.
          - Preserve every explicit user constraint: age, deadline, available
            materials, budget, parent time, requested sheet/script/image, and
            "finish tonight" or "few steps" constraints.
          - Use remembered child facts when present, but weave them into
            choices instead of listing memory unless the user asked what memory
            was used.
          - Use quick_reference only for safe, generic project inspiration.
            Do not cite it as live-verified science unless it clearly contains
            a source. If it is missing or weak, ignore it.
          - Do not invent calendar dates. Do not invent exact calendar dates, weather, school rules,
            measurements, allergies, local forecasts, or fake sample data.
          - If the user gives only a relative deadline, do not convert it into a calendar date.
          - Do not prefill observation tables with fake measurements; leave measurement cells blank or as placeholders.
          - Do not suggest tasting or eating the experiment materials.
          - Prefer a clear comparison design when it fits: same container,
            same water, same paper towel/soil, one changed variable.
          - Treat requests for a printable worksheet as print-ready markdown included inline. "Printable" means a clean markdown table,
            checklist, or fill-in sheet that can be copied or printed. Do not
            create or refer to PDFs, HTML files, downloads, or attachments
            unless the user explicitly asked for a file/PDF/export/download.

          For English one-evening school projects due tomorrow/tonight, use
          this compact one-evening school-project structure and keep the whole
          answer about 350-650 words:

          # <warm project title>
          One short line explaining why it is low-stress and school-ready.
          ## Make this
          Name one concrete artifact, give it a memorable title, say what goes
          on the front, and include a memorable visual theme.
          ## Tonight plan
          Exactly 3-4 main steps, timed for 30-40 minutes. Use simple
          child-facing actions and include one parent line to say aloud per
          step.
          ## Tiny observation sheet
          A very small blank table/checklist the child can fill in tonight;
          make it a drawing-heavy record sheet if memory says she likes
          drawing.
          ## What she can say in class
          3-5 short lines, using "I noticed...", "I predicted...", and
          "I learned..." when appropriate.
          ## Illustration
          If the user asked for image/illustration/poster/visual/配图, say to
          use the generated image as the cover/front image, then give one
          sentence of alt text. Do not expose artifact metadata, file paths,
          IDs, hashes, or download URLs.

          Layout rules for one-evening school projects:
          - Make the answer look like a one-page project card, not a report.
          - Use a short title, compact sections, and scannable markdown.
          - Prefer one small table and one short checklist over paragraphs.
          - Use simple labels a child can copy onto paper: Cover, Tonight,
            My Weather Clue, I Noticed, I Learned.
          - Keep each numbered step to 1-2 short sentences.
          - Add a tiny front-cover layout line such as: top title, center
            picture, bottom 3 weather words.
          - Keep whitespace clean; no dense walls of text.

          For Chinese safe school projects, use concise Simplified Chinese
          headings and the same short shape: 做什么、今晚步骤、小记录表、上台怎么说、配图建议.

          For casual at-home activities, keep it warmer and shorter:
          # <warm activity title>
          ## What you need
          ## 20-minute plan
          ## If she gets stuck
          ## Optional 10-minute extension
          ## Why it works

          Avoid report-like sections unless the user explicitly asks for a
          full pack, detailed steps, research, poster-board layout, weather
          adjustment, safety review, rubric, vocabulary cards, slide deck, or
          multi-day plan.

          If Route is HEAVY_PROJECT_PACK, provide a fuller but still
          user-facing pack. Include only requested heavy sections from this
          list: known facts and assumptions, detailed plan, materials and
          substitutes, safety and failure modes, worksheet, poster layout,
          simple science explanation, weather/light adjustment, parent check,
          sources or evidence limits, slides/PPT note. Keep it grounded in the
          user request, memory, heavy_research, and weather_check. Do not
          include weather claims unless weather_check contains a real result.

          End with:
          PACK_DELIVERED: {{ outputs.feasibility }}

    - id: visual_brief
      kind: llm_chat
      depends_on: [project_pack, preferences, feasibility]
      when: "outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences and ('配图' in inputs.user_message or 'image' in (inputs.user_message | lower) or 'illustration' in (inputs.user_message | lower) or 'poster' in (inputs.user_message | lower) or 'visual' in (inputs.user_message | lower) or 'cover' in (inputs.user_message | lower) or 'front' in (inputs.user_message | lower))"
      with:
        system: "You create one concise image-generation brief for a child-safe school-project cover. Do not write final prose."
        task: |
          Build a cover illustration prompt from the final project pack.

          Final project pack:
          {{ outputs.get('project_pack', '') | truncate(2200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(700) }}

          Return exactly:
          IMAGE_PROMPT: <one vivid child-safe prompt, no text labels unless simple and legible, no brand names, no real child identity>
          ALT_TEXT: <one sentence>
          USE_IN_PACK: cover/front image

    - id: kid_deck
      kind: skill_exec
      skill: pptx
      depends_on: [project_pack, project_route, feasibility]
      when: "outputs.get('project_route') == 'HEAVY_PROJECT_PACK' and outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences and ('ppt' in (inputs.user_message | lower) or 'powerpoint' in (inputs.user_message | lower) or 'slide deck' in (inputs.user_message | lower) or 'slides' in (inputs.user_message | lower) or '幻灯片' in inputs.user_message or 'PPT' in inputs.user_message)"
      on_failure: kid_deck_fallback
      with:
        mode: create
        title: "Kid project"
        slides:
          - title: "Project"
            body: "{{ outputs.get('project_pack', '') | truncate(900) }}"
          - title: "Tonight / Plan"
            body: "{{ outputs.get('project_pack', '') | truncate(900) }}"
          - title: "Show and Tell"
            body: "{{ outputs.get('project_pack', '') | truncate(900) }}"
        output_path: "/tmp/kid_project_deck.pptx"

    - id: kid_deck_fallback
      kind: llm_chat
      with:
        system: "You produce a silent deck fallback note."
        task: |
          PPT generation was unavailable. The chat answer already contains
          the usable project plan. Do not append runtime details.

    - id: project_illustration
      kind: tool_call
      tool: image_generate
      tool_allowlist: [image_generate]
      depends_on: [visual_brief]
      on_failure: project_illustration_fallback
      when: "(outputs.get('visual_brief', '') | length) > 0"
      with:
        prompt: "Generate the child-safe school-project cover illustration described by this brief. Use the IMAGE_PROMPT as the primary prompt, and respect the ALT_TEXT/USE_IN_PACK constraints. {{ outputs.get('visual_brief', '') | truncate(1600) }}"
        filename: "kid_project_illustration.png"

    - id: project_illustration_fallback
      kind: llm_chat
      with:
        system: "You provide a reusable image prompt when image generation is unavailable."
        task: |
          Image generation was unavailable. Return only this contract, with no
          runtime details:
          IMAGE_PROMPT_TO_REUSE: <concise prompt>
          ALT_TEXT: <one sentence>

          Visual brief:
          {{ outputs.get('visual_brief', '') | truncate(1200) }}

    - id: store_project
      kind: agent
      skill: memory
      depends_on: [project_pack, project_clarify, feasibility]
      on_failure: store_project_fallback
      when: "outputs.feasibility != 'INAPPROPRIATE' and 'PROJECT_SAFE: yes' in outputs.preferences and ('remember this project' in (inputs.user_message | lower) or 'save this project' in (inputs.user_message | lower) or 'archive this project' in (inputs.user_message | lower) or '记录这个项目' in inputs.user_message or '保存这个项目' in inputs.user_message)"
      with:
        task: |
          Archive the accepted child project plan only because the user
          explicitly asked to remember/save/archive it.

          Store only concise durable facts:
          - project title/topic
          - child age/preferences used
          - parent constraints used
          - prior projects avoided
          - the single most important planning lesson

          Do not rewrite the project pack. Do not include workspace paths.
          Final project pack:
          {{ outputs.get('project_pack', '') | truncate(2000) }}

    - id: store_project_fallback
      kind: llm_chat
      with:
        system: "You produce a silent archival fallback note for child project planning."
        task: |
          Project memory archive was not updated. The user-facing project
          pack has already been produced, so no additional text should be
          appended to the final answer.
---

# meta-kid-project-planner

Lightweight child-project planner for ordinary parent requests. The main path
is intentionally short:

Light route:

`preferences -> feasibility -> project_route -> memory recall + quick_reference -> project_pack -> visual_brief -> image_generate`

Heavy route:

`preferences -> feasibility -> project_route -> memory recall + quick_reference + heavy_research (+ weather_check when location exists) -> project_pack -> optional pptx/image_generate`

The previous heavy composition (full web research, weather lookup, fact ledger,
outline, materials, safety, learning objectives, PPTX deck, vocab cards,
deliver, audit) was removed from the default flow because ordinary school-night
requests need a fast usable answer, not a full report. The skill still records
its ClawHub component lineage in metadata, but ordinary execution now uses a
small reference check, memory, and optional image generation.

## Safety

`preferences` and `feasibility` reject clearly inappropriate projects. Unsafe
requests route to `redirect_unsafe`, and `project_pack` returns only the clean
redirect.

## Memory

`recall_past_projects` reads durable memory for child age, preferences, parent
time, prior projects, and planning rules. The final answer uses those facts
quietly unless the user explicitly asks to see memory.

## Images

When the user asks for 配图, image, illustration, poster, visual, cover, or front
art, `visual_brief` creates one child-safe image prompt and `project_illustration`
calls `image_generate`. The final markdown tells the user to use the generated
image as the cover/front image without exposing artifact metadata.
