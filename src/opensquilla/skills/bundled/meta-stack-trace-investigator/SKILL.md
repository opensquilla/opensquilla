---
name: meta-stack-trace-investigator
description: "Use this meta-skill instead of answering directly when the user gives a stack trace, traceback, runtime error, or failing log that benefits from multi-skill orchestration across trace parsing, repo/history inspection, patch-target analysis, reproduction guidance, and verification commands."
kind: meta
meta_priority: 60
always: false
final_text_mode: "step:degraded_summary"
triggers:
  - "traceback"
  - "stack trace"
  - "runtime error"
  - "failing log"
  - "keyerror"
  - "typeerror"
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
      kind: llm_classify
      output_choices: [python, javascript, typescript, go, rust, unknown]
      with:
        text: "{{ inputs.user_message | xml_escape | truncate(2000) }}"
    - id: parse_trace
      kind: llm_chat
      depends_on: [classify_language]
      with:
        system: "You parse stack traces. Return only the requested JSON object."
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
      kind: tool_call
      tool: exec_command
      tool_allowlist: [exec_command]
      depends_on: [parse_trace]
      tool_args:
        command: "rg -n --hidden --max-count 5 -- 'parse_tool_result|run_step|json.loads|KeyError|result' ."
        workdir: "{{ inputs.workspace_dir }}"
        timeout: 12
    - id: search_issues
      kind: tool_call
      tool: exec_command
      tool_allowlist: [exec_command]
      depends_on: [parse_trace]
      tool_args:
        command: "gh issue list --search 'KeyError result parse_tool_result' --json number,title,url --limit 10"
        workdir: "{{ inputs.workspace_dir }}"
        timeout: 12
    - id: git_history
      kind: tool_call
      tool: exec_command
      tool_allowlist: [exec_command]
      depends_on: [parse_trace]
      tool_args:
        command: "git log --since='30 days ago' --oneline -- src/agent/tools.py src/agent/runtime.py"
        workdir: "{{ inputs.workspace_dir }}"
        timeout: 12
    - id: diff_context
      kind: skill_exec
      skill: git-diff
      depends_on: [parse_trace]
      on_failure: diff_context_degraded
      with:
        mode: worktree
        cwd: "{{ inputs.workspace_dir | default('.') }}"
    - id: diff_context_degraded
      kind: llm_chat
      with:
        system: "You return a fixed degraded-evidence marker."
        task: |
          Return exactly:
          DIFF_CONTEXT: DEGRADED - current workspace is not a readable git
          worktree or git-diff failed. Continue using traceback evidence,
          repo grep output, and explicit user-provided paths.
    - id: history_patterns
      kind: skill_exec
      skill: history-explorer
      depends_on: [parse_trace]
      on_failure: history_patterns_degraded
      with:
        query: "{{ outputs.parse_trace | truncate(512) }}"
        window_days: "30"
        include: "meta_usage,co_occurrences"
    - id: history_patterns_degraded
      kind: llm_chat
      with:
        system: "You return a fixed degraded-evidence marker."
        task: |
          Return exactly:
          HISTORY_PATTERNS: DEGRADED - history-explorer failed or no local
          decision history is available. Continue without prior-pattern
          evidence.
    - id: memory_recall
      kind: tool_call
      tool: memory_search
      tool_allowlist: [memory_search]
      depends_on: [parse_trace]
      tool_args:
        query: "{{ outputs.parse_trace | truncate(400) }}"
        max_results: 3
    - id: language_probe
      kind: agent
      skill: stack-trace-generic-probe
      depends_on: [parse_trace]
      route:
        - when: "outputs.classify_language == 'python'"
          to: stack-trace-python-probe
        - when: "outputs.classify_language in ('javascript', 'typescript')"
          to: stack-trace-js-probe
        - when: "outputs.classify_language == 'go'"
          to: stack-trace-go-probe
        - when: "outputs.classify_language == 'rust'"
          to: stack-trace-rust-probe
      with:
        task: |
          Run a language-specific stack-trace probe. Use the parsed trace and
          evidence gathered so far to propose language-idiomatic checks,
          minimal reproducer shape, and patch targets. Do not claim repository
          evidence that is absent.

          Language classification:
          {{ outputs.classify_language | truncate(400) }}

          Trace parse:
          {{ outputs.parse_trace | truncate(1200) }}

          Original user request:
          {{ inputs.user_message | xml_escape | truncate(2000) }}
    - id: root_cause
      kind: llm_chat
      depends_on: [grep_repo, search_issues, git_history, diff_context, history_patterns, memory_recall, language_probe]
      with:
        system: "You synthesize bounded root-cause hypotheses from stack traces and explicit evidence."
        task: |
          Synthesize a root-cause hypothesis from these parallel
          investigations and the original trace parse.

          Trace parse:
          {{ outputs.parse_trace | truncate(600) }}

          Repo grep:
          {{ outputs.grep_repo | truncate(1200) }}

          Related GH issues:
          {{ outputs.search_issues | truncate(800) }}

          Recent commits on affected files:
          {{ outputs.git_history | truncate(800) }}

          Current git diff context:
          {{ outputs.diff_context | truncate(1200) }}

          Prior OpenSquilla skill/router history patterns:
          {{ outputs.history_patterns | truncate(1200) }}

          Prior similar incidents (may be empty on a fresh install — if
          this section is empty or returns no matches, IGNORE it and
          synthesize the root cause from the other available investigations
          alone; do not invent prior incidents that are not listed):
          {{ outputs.memory_recall | truncate(800) }}

          Language-specific probe:
          {{ outputs.language_probe | truncate(1200) }}

          If repository search returned NO_HITS or the referenced files are
          absent, still derive a bounded hypothesis from the stack trace
          contract itself. Clearly say the repository evidence is degraded;
          do not pretend that files or symbols were inspected.

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
      kind: llm_chat
      depends_on: [root_cause]
      with:
        system: "You propose safe, minimal verification commands for debugging."
        task: |
          Propose the smallest safe verification command(s) for this root-cause
          hypothesis. Prefer existing tests, targeted unit tests, or a minimal
          reproducer command. Do not propose destructive commands.

          Language classification:
          {{ outputs.classify_language | truncate(400) }}

          Trace parse:
          {{ outputs.parse_trace | truncate(600) }}

          Root-cause report:
          {{ outputs.root_cause | truncate(1200) }}

          Language-specific probe:
          {{ outputs.language_probe | truncate(1200) }}

          Reply with:
          CONFIDENCE: <low|medium|high>
          VERIFY:
            - <command or manual check>
            - <minimal reproducer command or snippet for the parsed language>
          FIX_FIRST:
            - <first file/action>
          PATCH_SHAPE:
            - <specific defensive-code shape to try first>
    - id: degraded_summary
      kind: llm_chat
      depends_on: [grep_repo, search_issues, git_history, diff_context, history_patterns, memory_recall, language_probe, repro_suggestion]
      with:
        system: "You write final user-facing debugging reports. Be concise, concrete, and evidence-aware."
        task: |
          Produce the final user-facing investigation. If any evidence source
          returned NO_HITS, NO_MATCHING_ISSUES, NO_RECENT_COMMITS, auth errors,
          or empty memory, label that source as DEGRADED instead of hiding it.
          This is the final answer shown to the user: do not mention
          meta-skill step ids, memory persistence, internal tools, or that
          anything was saved.

          When repository evidence is degraded, do not stop at a short
          conclusion. Provide a useful fallback investigation based on the
          trace contract:
          - say that the referenced files/symbols were not found in the
            current workspace when that is true;
          - include exact repo search commands the user can run in the real
            target repository;
          - include a minimal reproducer snippet or command for the parsed
            language/runtime;
          - include a defensive patch direction with expected failure mode;
          - include exact verification commands.

          Root cause:
          {{ outputs.root_cause | truncate(1200) }}

          Trace parse:
          {{ outputs.parse_trace | truncate(800) }}

          Language classification:
          {{ outputs.classify_language | truncate(400) }}

          Verification plan:
          {{ outputs.repro_suggestion | truncate(1000) }}

          Language-specific probe:
          {{ outputs.language_probe | truncate(1000) }}

          Evidence sources:
          repo={{ outputs.grep_repo | truncate(800) }}
          issues={{ outputs.search_issues | truncate(800) }}
          history={{ outputs.git_history | truncate(800) }}
          diff={{ outputs.diff_context | truncate(800) }}
          skill_history={{ outputs.history_patterns | truncate(800) }}
          memory={{ outputs.memory_recall | truncate(800) }}

          Reply in Markdown with these sections and no preamble:
          ## Diagnosis
          ## Evidence Status
          ## Assumptions / Constraints
          ## Repo Search Targets
          ## Reproduction
          ## Patch Direction
          ## Patch Target Checklist
          ## Verification Commands
    - id: persist
      kind: tool_call
      tool: memory_save
      tool_allowlist: [memory_save]
      depends_on: [degraded_summary]
      tool_args:
        path: "memory/traceback.md"
        mode: "append"
        content: |
          === stack-trace investigation ===
          parse: {{ outputs.parse_trace | truncate(400) }}
          hypothesis: {{ outputs.degraded_summary | truncate(1000) }}
---

# Stack-Trace Investigator (Meta-Skill)

A **combinator-style** meta-skill that converts a pasted stack trace into a
structured root-cause report. It now classifies Python, JavaScript,
TypeScript, Go, Rust, or unknown traces before running the investigation. After
parsing the trace once, heterogeneous investigations run in parallel:

1. **`grep_repo`** — ripgrep for the symbols in the current repo
2. **`search_issues`** — `gh issue list` for similar reported problems
3. **`git_history`** — recent commits touching the affected files
4. **`diff_context`** — `git-diff` skill for current worktree context
5. **`history_patterns`** — `history-explorer` skill for prior skill/router
   usage patterns
6. **`memory_recall`** — prior incidents stored under the `traceback` topic
7. **`language_probe`** — routed to the language-specific helper skill
   (`stack-trace-python-probe`, `stack-trace-js-probe`,
   `stack-trace-go-probe`, `stack-trace-rust-probe`, or generic fallback)

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
