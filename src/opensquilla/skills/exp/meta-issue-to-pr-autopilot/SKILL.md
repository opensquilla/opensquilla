---
name: meta-issue-to-pr-autopilot
description: "Triage a GitHub issue, delegate a fix to sub-agent, draft the PR description, and open the PR. Use when the user names a specific issue (e.g. `#123` or full URL) and asks to fix it / open a PR for it / autopilot the issue end-to-end. NOT for: exploratory bug investigation (issue context too thin), issues blocked on cross-team discussion (auto-fix premature), or repos without `gh` auth configured."
kind: meta
meta_priority: 35
always: false
triggers:
  - "issue 自动修"
  - "issue to pr"
  - "autopilot pr"
  - "fix issue"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: fetch_issue
      skill: github
      with:
        task: "Fetch the issue referenced in the user request and gather the relevant repo context: {{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: patch
      skill: sub-agent
      depends_on: [fetch_issue]
      with:
        task: "Implement a fix for this issue."
        issue: "{{ outputs.fetch_issue }}"
    - id: pr_body
      skill: summarize
      depends_on: [patch]
      with:
        text: "{{ outputs.patch }}"
        style: pr_description
        max_words: 400
    - id: open_pr
      skill: github
      depends_on: [pr_body]
      with:
        task: "Open a pull request with the fix. Title: fix: {{ inputs.user_message | xml_escape | truncate(80) }}. Body: {{ outputs.pr_body }}"
---

# Issue-to-PR Autopilot (Meta-Skill)

Triages an issue, delegates the fix to `sub-agent`, drafts a PR
description with `summarize`, and opens the PR via `gh`. Best used on
small, well-scoped issues with clear acceptance criteria.

## Fallback

Manually call `gh issue view`, code the fix, write the PR body, then
`gh pr create`.
