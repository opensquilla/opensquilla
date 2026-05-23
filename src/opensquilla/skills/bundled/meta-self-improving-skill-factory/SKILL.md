---
name: meta-self-improving-skill-factory
description: "Author-by-agent: design a new AgentSkill from a requirement, delegate implementation to sub-agent, then open a PR on GitHub."
kind: meta
meta_priority: 35
always: false
triggers:
  - "新增 skill"
  - "create skill"
  - "skill factory"
  - "author a skill"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: design
      skill: skill-creator
      with:
        task: "Draft a SKILL.md + directory layout for the new skill described in: {{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: implement
      skill: sub-agent
      depends_on: [design]
      with:
        task: "Implement the scripts/ and references/ for this skill blueprint."
        blueprint: "{{ outputs.design }}"
    - id: publish
      skill: github
      depends_on: [implement]
      with:
        task: "Open a feature branch and PR with the new skill. PR description: {{ outputs.implement }}"
---

# Self-Improving Skill Factory (Meta-Skill)

Agent-authored skills: design → implement (delegated to `sub-agent`)
→ PR (via `github` skill / `gh` CLI). High-leverage automation, but
requires write access to the repo — review carefully before merging.

## Fallback

LLM should call skill-creator to draft the structure, then run
sub-agent (or shell tooling) to fill in scripts, then open a PR.
