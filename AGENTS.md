# OpenSquilla Agent Instructions

These instructions apply to the whole repository unless a deeper `AGENTS.md`
overrides them.

## Working Rules

- Treat current git state as authoritative. Before changing files, inspect
  `git status --short --branch`, recent commits, and any relevant `AGENTS.md`
  files in scope.
- Preserve user-facing behavior unless the task explicitly asks to change it.
  CLI text, flags, JSON/RPC payloads, WebSocket events, provider defaults,
  channel replies, and public imports need compatibility coverage.
- Keep edits narrowly scoped to the active task. Do not rewrite unrelated files,
  generated assets, dependency locks, or user changes.
- Use `rg`/`rg --files` for repository searches when available.
- Use `apply_patch` for manual edits.

## Refactor Workflow

- For the active architecture refactor, use the integration branch
  `codex/refactor-architecture` and create one isolated child git worktree per
  independently mergeable slice.
- Start each slice from `docs/refactor/stage-template.md` and record current
  audit evidence, boundary decisions, TDD commands, verification, hashes, and
  the next recommended slice under `docs/refactor/stages/`.
- Use Superpowers checkpoints for refactor work:
  `superpowers:using-git-worktrees`, `superpowers:writing-plans`,
  `superpowers:test-driven-development`, and
  `superpowers:verification-before-completion`.
- Use multiple agents for independent subdomains when possible. Give each agent
  explicit file/module ownership and constraints, then have the main thread
  review, integrate, and run the full gate.
- If agent spawning is unavailable or a thread limit is reached, record the
  fallback in the stage plan and continue sequentially.

## Testing And Gates

- For code or executable behavior changes, write the failing test first and
  confirm the expected red failure before production edits.
- Run focused tests for the touched behavior, then run `scripts/refactor_gate.sh`
  before committing a child slice.
- After merging a child slice into integration with `git merge --no-ff`, run
  `scripts/refactor_gate.sh` again from integration.
- Do not claim completion without fresh verification output.

## Commits

- Commit messages must include this trailer exactly once:

```text
Co-authored-by: Codex <noreply@openai.com>
```
