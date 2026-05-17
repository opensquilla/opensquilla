# Agent Worktree Ignore Governance Plan

> For agentic workers: REQUIRED SUB-SKILL: Use `superpowers:using-git-worktrees`
> for this slice. This is a non-code governance update, so TDD red/green is not
> applicable; use verification-before-completion before claiming completion.

## Stage

- Name: agent-worktree-ignore
- Date: 2026-05-17
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-agent-worktree-ignore`
- Child worktree: `../opensquilla-refactor-agent-worktree-ignore`
- Owner: Codex main thread. A read-only explorer review was attempted for
  `AGENTS.md` and `.gitignore`, but spawning failed with `agent thread limit
  reached`; this stage proceeds sequentially and records the fallback per root
  `AGENTS.md`.

## Goal

Make refactor-agent guidance explicit on the refactor line: root `AGENTS.md`
stays tracked there, and project-local agent worktree directories are explicitly
ignored by git.

## Current-state audit

- Current HEAD: `b207aec`
- Worktree status: clean before this slice.
- AGENTS.md files in scope: `AGENTS.md`; template-only
  `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is out of scope.
- Files inspected:
  - `AGENTS.md`
  - `.gitignore`
  - `docs/refactor/stage-template.md`
- Existing boundary pattern this stage follows:
  - Root `AGENTS.md` governs the whole refactor line.
  - `.gitignore` already unignores root `AGENTS.md` on the refactor line.

## Boundary decision

- Responsibilities moving out:
  - None; this is governance documentation and ignore-rule clarification.
- Responsibilities staying in place:
  - Source code, tests, package metadata, generated files, and main checkout.
- New module/file responsibility:
  - None.
- Public behavior that must not change:
  - Runtime code and CLI behavior are untouched.
- Files explicitly out of scope:
  - `src/`, `tests/`, packaging metadata, and main branch checkout.

## Verification

- `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-agent-worktree-ignore`
- `git check-ignore -v .worktrees/ worktrees/`
- `git diff --check`
- `git diff --cached --check`

## Files

- Create:
  - `docs/refactor/stages/2026-05-17-agent-worktree-ignore.md`
- Modify:
  - `.gitignore`
  - `AGENTS.md`
- Test:
  - Not applicable; no executable behavior changed.
- Documentation:
  - `docs/refactor/stages/2026-05-17-agent-worktree-ignore.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-agent-worktree-ignore`.
- [x] Make `.worktrees/` and `worktrees/` explicit gitignore entries.
- [x] Clarify in root `AGENTS.md` that the file is tracked on the refactor line and may be absent from main checkout.
- [x] Verify ignore behavior and whitespace.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Record child hash, integration hash, verification, and next slice.

## Rollback

- Revert the integration merge commit if the guidance or ignore rules interfere
  with repository workflows.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit:
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-agent-worktree-ignore` passed on branch `codex/refactor-agent-worktree-ignore` at `b207aec`.
  - Ignore check: `git check-ignore -v .worktrees/ worktrees/` reported `.gitignore:21:.worktrees/` and `.gitignore:22:worktrees/`.
  - Whitespace: `git diff --check` passed.
- Residual risk:
  - Low. The slice only clarifies agent guidance and local worktree ignore rules.
- Next recommended slice:
  - Continue the CLI chat reduction with standalone `/new` session creation or gateway `/save` transcript dispatch.
