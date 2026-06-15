---
name: code-task
description: "PREFERRED way to change code in a REAL repository: fix a GitHub issue, fix a bug, add/implement a function or feature, or make any edit to a project the user names by a filesystem path (e.g. /tmp/foo, ~/code/bar) or a git URL. Clones the repo, runs an OpenSquilla agent on the host to make the change on a task branch, then independently VERIFIES it with a red→green→regression test loop and reports a structured result. STRONGLY prefer this over hand-editing the user's files yourself in this session: editing files directly skips the isolation and the runner-verified red→green proof, so it is not equivalent. Use it whenever the request names a real on-disk repo/path or a repo URL and asks to fix/add/implement/change code. Examples: 'fix issue 412 in github.com/acme/widgets', '给 /tmp/calc 加个 average 函数', '帮我改一下 ~/proj 里的 X', 'implement CSV export in my project'. Docker-free host execution; treat the target repo as TRUSTED. GitHub issue mode needs the `gh` CLI. (Do NOT use for conceptual coding questions, code snippets with no target repo, or repos the user has not pointed at.)"
triggers:
  - "code-task"
  - "fix the issue"
  - "fix issue"
  - "fix the bug"
  - "implement this feature"
  - "add a function"
  - "add a feature"
  - "change the code"
  - "解决 issue"
  - "给项目加功能"
  - "给项目加"
  - "加个函数"
  - "加一个函数"
  - "改一下代码"
  - "修复仓库"
  - "修复 bug"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
  maintained_by: OpenSquilla
metadata:
  {
    "platform":
      {
        "emoji": "🛠️",
        "requires": { "bins": ["git"], "env": ["OPENROUTER_API_KEY"] },
        "install": [],
      },
  }
---

# code-task

Solve a real-repository coding task end to end: clone the repo to a
disposable working directory, run an OpenSquilla agent to make the change on
a task branch, then **independently verify** it with a red→green→regression
loop. Host mode (no Docker) in v1.

## Use this — do not hand-edit the repo yourself

When the user asks to fix/add/implement/change code in a repository they
name by path or URL, route it through `opensquilla code-task solve` — even
if the change looks small enough to do by hand. Editing the files yourself
in this session is **not equivalent**: it skips the disposable clone, the
task branch, and (most importantly) the runner-verified red→green→regression
proof, so neither you nor the user gets evidence the change actually works.
The only time to do it inline instead is when there is no target repo at all
(a throwaway snippet, a conceptual question). When in doubt and a real repo
is named, prefer code-task.

## Translating the user's request

The user speaks naturally ("fix issue 412 in github.com/acme/widgets",
"add CSV BOM support to my project at ~/code/foo"). Map that to the command:

```
opensquilla code-task solve --repo <url-or-path> ( --issue N | --task "<text>" | --task-file <path> ) [--yes]
```

- **A GitHub issue** → `--issue N` (needs `gh`; see below).
- **A short request in the message** → `--task "<their request>"`.
- **A long spec, or pasted from Jira/GitLab/内网** → save it to a file and
  use `--task-file <path>`.
- Always pass `--repo`. If the user is already in a local checkout, use that
  path; otherwise the GitHub/remote URL.
- Pass `--yes` to skip the interactive trusted-host confirmation (you are
  acting on the user's behalf), but only after the safety check below.

## Before you run — two checks

1. **Trusted repo**: code-task runs an agent on the host that may install
   dependencies and execute the repo's code. It is NOT a sandbox. Only run
   it against repositories the user trusts. If the repo's provenance is
   unclear, ask first.
2. **Enough information**: you must be able to state the expected behavior
   change ("what is wrong/missing now, what should be true after"). If the
   request is too vague to write an acceptance test for, ask the user to
   clarify BEFORE running — do not burn a run on a guess.

## GitHub issue mode needs `gh`

`--issue` shells out to the GitHub CLI (`gh`). If `gh` is missing or not
authenticated, tell the user to `gh auth login`, or fall back: have them
paste the issue text and use `--task` / `--task-file` instead. The issue
body AND comments are pulled in (comments often hold the repro steps).

## Reading the result

`--json` prints a result object; key fields:

- `state`: `verified` (acceptance test went red→green, no regressions),
  `already_satisfied` (the behavior already held on the base commit),
  `not_testable` (work done but not expressible as a test),
  `environment_blocked` (could not build/test the repo),
  `invalid_acceptance_test` (agent produced no valid verification manifest),
  `failed` (acceptance not green or a regression appeared).
- `branch`, `commits`, `files_changed`, `diffstat`, `patch_path`.
- `acceptance`: each test with `before`→`after` (e.g. `fail`→`pass`).
- `regression`: existing-suite result and `new_failures`.
- `assumptions`: **surface these to the user** — a wrong assumption means a
  wrong fix.
- `usage`: cost / tokens.

## What to tell the user

1. Up front: cloning + dependency install + the agent loop can take several
   minutes; you'll report when done.
2. After: report `state`, what changed (diffstat), the acceptance red→green
   evidence, any `assumptions`, the cost, and where the branch/diff lives.
3. On `failed` / `environment_blocked`: quote `error` and point at the
   `agent_stdout.log` under the artifact dir.

## Constraints

- Runs on the gateway host — git, the toolchain, and disk all come from
  there. Works the same from TUI, Web UI, or any channel.
- v1 is host-only and always clones fresh (no `--in-place`). For untrusted
  repositories, a Docker-isolated backend is planned but not in v1.
