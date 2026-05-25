---
name: meta-stack-trace-investigator
description: "Use when the user pastes a stack trace or runtime error and wants structured root-cause analysis with repository evidence and next verification commands."
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
    - id: classify_language
      kind: agent
      skill: sub-agent
      with:
        task: |
          Classify the stack trace language/runtime. Support Python,
          JavaScript, TypeScript, Go, Rust, and unknown text logs. Do not
          speculate about root cause yet.

          Stack trace under investigation:
          ---
          {{ inputs.user_message | xml_escape | truncate(3000) }}
          ---

          Reply with EXACTLY one JSON object on a single line, no preamble:
            {"language": "<python|javascript|typescript|go|rust|unknown>", "runtime": "<runtime or empty>", "confidence": "<low|medium|high>"}
    - id: parse_trace
      kind: agent
      skill: sub-agent
      depends_on: [classify_language]
      with:
        task: |
          You are the trace parser for a stack-trace investigation bundle.
          Extract structured info from the stack trace below; do not speculate
          about root cause yet.

          Language classification:
          {{ outputs.classify_language | truncate(400) }}

          Traceback under investigation:
          ---
          {{ inputs.user_message | xml_escape | truncate(3000) }}
          ---

          Reply with EXACTLY one JSON object on a single line, no preamble:
            {"exception_class": "<ClassNameOrErrorKind>", "exception_message": "<head of message; <=120 chars>", "primary_file": "<path/file or empty>", "primary_line": <int or 0>, "symbols": ["sym1", "sym2", ...], "language": "<python|javascript|typescript|go|rust|unknown>"}

          The "symbols" list contains the function/method names that appear in
          the top 3 frames; include at most 6 distinct entries.
    - id: grep_repo
      kind: agent
      skill: sub-agent
      depends_on: [parse_trace]
      with:
        task: |
          Search the current working-directory repository for the symbols and
          file paths referenced in this trace. Use language-appropriate file
          extensions when useful: Python .py, JavaScript .js/.jsx, TypeScript
          .ts/.tsx, Go .go, Rust .rs.

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
      skill: sub-agent
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
    - id: repro_suggestion
      kind: agent
      skill: sub-agent
      depends_on: [root_cause]
      with:
        task: |
          Propose the smallest safe verification command(s) for this root-cause
          hypothesis. Prefer existing tests, targeted unit tests, or a minimal
          reproducer command. Do not propose destructive commands.

          Language classification:
          {{ outputs.classify_language | truncate(400) }}

          Root-cause report:
          {{ outputs.root_cause | truncate(1200) }}

          Reply with:
          CONFIDENCE: <low|medium|high>
          VERIFY:
            - <command or manual check>
          FIX_FIRST:
            - <first file/action>
    - id: degraded_summary
      kind: agent
      skill: sub-agent
      depends_on: [grep_repo, search_issues, git_history, memory_recall, repro_suggestion]
      with:
        task: |
          Produce the final user-facing investigation. If any evidence source
          returned NO_HITS, NO_MATCHING_ISSUES, NO_RECENT_COMMITS, auth errors,
          or empty memory, label that source as DEGRADED instead of hiding it.

          Root cause:
          {{ outputs.root_cause | truncate(1200) }}

          Verification plan:
          {{ outputs.repro_suggestion | truncate(1000) }}

          Evidence sources:
          repo={{ outputs.grep_repo | truncate(800) }}
          issues={{ outputs.search_issues | truncate(800) }}
          history={{ outputs.git_history | truncate(800) }}
          memory={{ outputs.memory_recall | truncate(800) }}
    - id: persist
      kind: agent
      skill: memory
      depends_on: [degraded_summary]
      with:
        action: save
        topic: "traceback"
        content: |
          === stack-trace investigation ===
          parse: {{ outputs.parse_trace | truncate(400) }}
          hypothesis: {{ outputs.degraded_summary | truncate(1000) }}
---

# Stack-Trace Investigator (Meta-Skill)

A **combinator-style** meta-skill that converts a pasted stack trace into a
structured root-cause report. It now classifies Python, JavaScript,
TypeScript, Go, Rust, or unknown traces before running the investigation. After
parsing the trace once, four heterogeneous investigations run in parallel:

1. **`grep_repo`** — ripgrep for the symbols in the current repo
2. **`search_issues`** — `gh issue list` for similar reported problems
3. **`git_history`** — recent commits touching the affected files
4. **`memory_recall`** — prior incidents stored under the `traceback` topic

The `root_cause` and `repro_suggestion` steps fan the signals into a
hypothesis, concrete fix targets, and verification commands. The final summary
labels degraded evidence sources explicitly before persisting the incident.

## Trigger surface

Fire by saying `investigate stack trace` or one of the localized triggers
listed in the frontmatter, with the traceback pasted into the same turn.

## Fallback

If any leaf step fails, the orchestrator surfaces partial outputs in
`step_outputs`. Operator should manually run `rg <symbols>`,
`gh issue list --search`, `git log`, and `memory search` and
synthesize the report by hand.
