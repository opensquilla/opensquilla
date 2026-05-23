---
name: git-diff
description: "Capture the current git diff (staged, working-tree, or staged file list) as text. Used by meta-skills that review uncommitted code (meta-codereview-current-diff, meta-pre-commit-quality-gate). Direct shell call — no LLM agent loop."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  requires:
    bins: ["git"]
entrypoint:
  command: python {baseDir}/scripts/git_diff.py
  args:
    - --mode
    - "{{ with.mode | default('cached_fallback_worktree') }}"
    - --cwd
    - "{{ with.cwd | default('.') }}"
  parse: text
  timeout: 30
---

# git-diff (sub-skill)

Direct shell invocation that returns the current git diff as text.
Replaces ``sub-agent`` sub-Agent steps that just shell out to
``git diff`` — order-of-magnitude faster (no LLM round-trip).

## Modes

| mode (`with.mode`)            | behaviour                                          |
|-------------------------------|----------------------------------------------------|
| `cached_fallback_worktree`    | `git diff --cached HEAD`; falls back to `git diff HEAD` if staged diff is empty. Default. |
| `cached`                      | `git diff --cached HEAD` only                      |
| `worktree`                    | `git diff HEAD` only                               |
| `staged_files`                | `git diff --cached --name-only` (path list)        |

## Output

- Non-empty diff: raw unified diff text on stdout.
- Empty (no changes): exits 0 with the literal `NO_DIFF` on stdout so
  downstream meta-step prompts can short-circuit reviewers.
- git not a repo / git error: exit 1, stderr carries the cause.

## Fallback

If this skill is unavailable, callers should spawn ``sub-agent``
with a ``git diff`` task — same output, ~10× the latency.
