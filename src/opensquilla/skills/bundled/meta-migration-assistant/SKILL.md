---
name: meta-migration-assistant
description: "Produce a concrete migration plan: classify the migration kind, fetch the right authoritative guide (SDK release notes / framework docs / synthesized research), then write a step-by-step checklist."
kind: meta
meta_priority: 50
always: false
triggers:
  - "migration plan"
  - "migrate from"
  - "upgrade from"
  - "升级指南"
  - "迁移方案"
  - "迁移步骤"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices:
        - PY2_TO_PY3
        - VUE2_TO_VUE3
        - REACT_CLASS_TO_HOOKS
        - OPENAI_V0_TO_V1
        - CJS_TO_ESM
        - OTHER
      with:
        text: |
          User said: {{ inputs.user_message | xml_escape | truncate(400) }}

          Identify the migration kind.

          Decision rules:
          - PY2_TO_PY3        → mentions Python 2 → 3 / py2 → py3
          - VUE2_TO_VUE3      → mentions Vue 2 → Vue 3 / options → composition
          - REACT_CLASS_TO_HOOKS → React class component → hooks
          - OPENAI_V0_TO_V1   → openai SDK v0 → v1, ChatCompletion → chat.completions.create
          - CJS_TO_ESM        → CommonJS require / module.exports → ESM import/export
          - OTHER             → any other migration request
    - id: fetch_guide
      skill: deep-research
      depends_on: [classify]
      route:
        - when: "'OPENAI_V0_TO_V1' in outputs.classify"
          to: github
        - when: "outputs.classify in ('PY2_TO_PY3', 'VUE2_TO_VUE3', 'REACT_CLASS_TO_HOOKS', 'CJS_TO_ESM')"
          to: multi-search-engine
      with:
        query: |
          Authoritative migration guide for: {{ inputs.user_message | xml_escape | truncate(300) }}.
          Classifier verdict: {{ outputs.classify }}.
          Return the most relevant excerpt with source URL(s).
    - id: write_plan
      skill: coding-agent
      depends_on: [fetch_guide]
      with:
        task: |
          Migration kind: {{ outputs.classify }}
          User request: {{ inputs.user_message | xml_escape | truncate(300) }}

          Authoritative guide excerpt:
          {{ outputs.fetch_guide | truncate(2000) }}

          Produce a concrete migration checklist as Markdown with these sections:
          ## Summary
          ## Breaking changes
          ## Step-by-step
          ## Files likely affected (grep patterns the user can run)
          ## Validation (tests/checks to confirm the migration)
---

# Migration Assistant (Meta-Skill)

Take a "help me migrate X → Y" request and produce a concrete, runnable
checklist. The pipeline does three things:

1. **classify** the migration kind via an LLM tag (one of six tokens).
2. **fetch_guide** the most authoritative source for THAT migration:

   | Classifier verdict          | Best source            | Routed skill          |
   |-----------------------------|------------------------|-----------------------|
   | `OPENAI_V0_TO_V1`           | repo release notes     | `github`              |
   | `PY2_TO_PY3`                | framework migration doc| `multi-search-engine` |
   | `VUE2_TO_VUE3`              | framework migration doc| `multi-search-engine` |
   | `REACT_CLASS_TO_HOOKS`      | framework migration doc| `multi-search-engine` |
   | `CJS_TO_ESM`                | (fuzzy, synthesize)    | `multi-search-engine` |
   | `OTHER` (default)           | (synthesize)           | `deep-research`       |

3. **write_plan** uses `coding-agent` regardless of branch — the plan
   format is identical across migrations.

## Fallback

If the orchestration fails: ask the user to specify the migration tag
manually, run the matching skill yourself, then write the checklist.
