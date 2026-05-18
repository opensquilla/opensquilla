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
  `codex/refactor-architecture` and the sibling integration worktree
  `../opensquilla-refactor-integration`.
- Use one reusable active child worktree at the sibling path
  `../opensquilla-refactor-active`. Do not create a new
  `opensquilla-refactor-*` directory per slice unless the user explicitly
  approves it. After each child slice is merged and recorded, remove the active
  worktree and run `git worktree prune` so only the integration worktree remains
  for the refactor line.
- The root `AGENTS.md` is intentionally tracked on the refactor line. If it
  appears absent, verify that you are in a refactor worktree rather than the
  main checkout before creating another copy.
- Prefer coarser, module-level or module-family refactor slices over
  helper-sized moves. Use Superpowers to plan batches across related
  CLI/Gateway/Session/Provider/Channels/Tools/Web UI boundaries, then run
  unified focused tests and the full refactor gate for the batch. Do not
  simplify implementation or drop behavior relative to the original main branch
  to make a larger slice pass.
- Start each slice from `docs/refactor/stage-template.md` and record current
  audit evidence, boundary decisions, TDD commands, verification, hashes, and
  the next recommended module batch under `docs/refactor/stages/`.
- Use Superpowers checkpoints for refactor work:
  `superpowers:using-git-worktrees`, `superpowers:writing-plans`,
  `superpowers:test-driven-development`, and
  `superpowers:verification-before-completion`.
- Use multiple agents for independent subdomains when possible. Give each agent
  explicit file/module ownership and constraints, then have the main thread
  review, integrate, and run the full gate.
- If same-thread `spawn_agent` is unavailable or a thread limit is reached, do
  not silently shrink back to serial work. First use
  `scripts/refactor_external_agent.sh` to run independent Codex CLI workers in
  fixed sibling worktree slots such as `../opensquilla-refactor-agent-provider`
  or `../opensquilla-refactor-agent-session`. Keep each worker on its own child
  branch, give it explicit file/module ownership, and remove/prune the worktree
  after its branch is merged. Record any remaining sequential fallback in the
  stage plan only after the external-agent route is blocked too.

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
