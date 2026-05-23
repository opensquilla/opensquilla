---
name: meta-stack-trace-investigator
description: "Investigate a Python traceback by fanning out across 4 independent data sources (repo grep + GitHub issues + git history + prior memory), then fan in to a root-cause hypothesis plus 3 file:line suggestions. Use when pasting a stack trace and wanting structured root-cause analysis instead of a one-shot agent guess."
kind: meta
meta_priority: 60
always: false
triggers:
  - "investigate stack trace"
  - "trace investigator"
  - "诊断 traceback"
  - "调查 stack trace"
  - "查 traceback"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: parse_trace
      kind: agent
      skill: coding-agent
      with:
        task: |
          You are the *trace parser* for a stack-trace investigation bundle.
          Extract structured info from the Python traceback below; do not
          speculate about root cause yet.

          Traceback under investigation:
          ---
          {{ inputs.user_message | xml_escape | truncate(3000) }}
          ---

          Reply with EXACTLY one JSON object on a single line, no preamble:
            {"exception_class": "<ClassName>", "exception_message": "<head of message; ≤120 chars>", "primary_file": "<path/file.py or empty>", "primary_line": <int or 0>, "symbols": ["sym1", "sym2", ...]}

          The "symbols" list contains the function/method names that appear in
          the top 3 frames; include at most 6 distinct entries.
    - id: grep_repo
      kind: agent
      skill: coding-agent
      depends_on: [parse_trace]
      with:
        task: |
          Search the current working-directory repository for the symbols
          referenced in this trace.

          Trace-parse output:
          {{ outputs.parse_trace | truncate(800) }}

          For each symbol, run `rg -n --hidden --max-count 5 -- <symbol>` in the
          repo root (skip vendored / dot-directories). Return up to 10 hits in
          the form `<file>:<line>: <code-line head>`. If none found, reply
          `NO_HITS`.
    - id: search_issues
      kind: agent
      skill: github
      depends_on: [parse_trace]
      with:
        task: |
          Search this project's GitHub repository for issues that look related
          to this exception. Use `gh issue list --search "<query>" --json
          number,title,url --limit 10` where the query combines the
          exception_class + the exception_message head.

          Trace-parse output:
          {{ outputs.parse_trace | truncate(800) }}

          Return up to 5 results as `#<number> <title> (<url>)` per line. If
          none, reply `NO_MATCHING_ISSUES`.
    - id: git_history
      kind: agent
      skill: history-explorer
      depends_on: [parse_trace]
      with:
        task: |
          List recent commits (last 30 days) that touched the file(s) named in
          this trace.

          Trace-parse output:
          {{ outputs.parse_trace | truncate(800) }}

          Use `git log --since="30 days ago" --oneline -- <primary_file>` (and
          for each frame file mentioned in symbols if applicable). Return up to
          10 commits in the form `<sha7> <date> <subject>`. If the file does
          not exist or has no recent commits, reply `NO_RECENT_COMMITS`.
    - id: memory_recall
      kind: agent
      skill: memory
      depends_on: [parse_trace]
      with:
        action: search
        topic: "traceback"
        query: "{{ outputs.parse_trace | truncate(400) }}"
        limit: 5
    - id: root_cause
      kind: agent
      skill: coding-agent
      depends_on: [grep_repo, search_issues, git_history, memory_recall]
      with:
        task: |
          Synthesize a root-cause hypothesis from these 4 parallel
          investigations and the original trace parse.

          Trace parse:
          {{ outputs.parse_trace | truncate(600) }}

          Repo grep:
          {{ outputs.grep_repo | truncate(1200) }}

          Related GH issues:
          {{ outputs.search_issues | truncate(800) }}

          Recent commits on affected files:
          {{ outputs.git_history | truncate(800) }}

          Prior similar incidents (may be empty on a fresh install — if
          this section is empty or returns no matches, IGNORE it and
          synthesize the root cause from the other three investigations
          alone; do not invent prior incidents that are not listed):
          {{ outputs.memory_recall | truncate(800) }}

          Reply with this exact structure (no preamble):

          ROOT_CAUSE: <one-sentence hypothesis>
          EVIDENCE:
            - <which investigation supported it; cite line>
            - <which investigation supported it; cite line>
          SUGGESTIONS:
            - <file:line> — <action>
            - <file:line> — <action>
            - <file:line> — <action>
    - id: persist
      kind: agent
      skill: memory
      depends_on: [root_cause]
      with:
        action: save
        topic: "traceback"
        content: |
          === stack-trace investigation ===
          parse: {{ outputs.parse_trace | truncate(400) }}
          hypothesis: {{ outputs.root_cause | truncate(800) }}
---

# Stack-Trace Investigator (Meta-Skill)

A **combinator-style** meta-skill that converts a pasted Python
traceback into a structured root-cause report. After parsing the
trace once, four heterogeneous investigations run in parallel:

1. **`grep_repo`** — ripgrep for the symbols in the current repo
2. **`search_issues`** — `gh issue list` for similar reported problems
3. **`git_history`** — recent commits touching the affected files
4. **`memory_recall`** — prior incidents stored under the `traceback` topic

The fifth step (`root_cause`) fans the four signals into a single
hypothesis with citations and 3 concrete fix targets. The final
`persist` step writes the hypothesis to long-term memory so the next
occurrence of the same exception class can short-circuit via
`memory_recall`.

## Trigger surface

Fire by saying `investigate stack trace` (English) or `诊断
traceback` / `调查 stack trace` / `查 traceback` (Chinese), with the
traceback pasted into the same turn.

## Fallback

If any leaf step fails, the orchestrator surfaces partial outputs in
`step_outputs`. Operator should manually run `rg <symbols>`,
`gh issue list --search`, `git log`, and `memory search` and
synthesize the report by hand.
