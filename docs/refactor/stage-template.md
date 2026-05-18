# Refactor Stage Plan Template

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name:
- Date:
- Integration branch: `codex/refactor-architecture`
- Child branch:
- Child worktree:
- Owner:

## Goal

State the cohesive behavior-compatible module or module-family architecture
improvement this stage will make. Prefer batching related boundaries instead of
planning helper-sized moves.

## Current-state audit

- Current HEAD:
- Worktree status:
- AGENTS.md files in scope:
- Files inspected:
- Symbols or command surfaces inspected:
- Tests inspected:
- Existing boundary pattern this stage follows:

## Boundary decision

- Module batch:
- Responsibilities moving out:
- Responsibilities staying in place:
- New module/file responsibility:
- Public behavior that must not change:
- Files explicitly out of scope:

## TDD red/green

- Failing test command:
- Expected red failure:
- Behavior compatibility coverage:
- Module-batch implementation:
- Focused green command:
- Additional touched-file checks:

## Files

- Create:
- Modify:
- Test:
- Documentation:

## Steps

- [ ] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [ ] Write the failing test or executable contract.
- [ ] Run the focused test and confirm the expected failure.
- [ ] Implement the cohesive behavior-compatible module batch without dropping
      existing feature coverage.
- [ ] Run the focused test and touched-file checks.
- [ ] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.
- [ ] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit:
- Integration merge:
- Verification evidence:
- Residual risk:
- Next recommended slice:
