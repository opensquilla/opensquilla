# Coarse Parallel Module Dispatch

> For agentic workers: each worker owns its own large refactor substage and
> must create a dedicated stage record from `docs/refactor/stage-template.md`.
> Each worker must use and record Superpowers evidence for
> `using-git-worktrees`, `writing-plans`, `test-driven-development`, and
> `verification-before-completion`.

## Stage

- Name: coarse-parallel-module-dispatch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Integration HEAD before dispatch: `b7422a3` (`Record chat REPL cleanup`)
- Owner: main Codex thread coordinates dispatch, review, merge ordering,
  conflict resolution, full integration gates, and cleanup.

## Goal

Start independent coarse-grained architecture refactor workers for the next
large module families so the project can move faster without overlapping file
ownership.

## Current-state audit

- `git status --short --branch` in integration: clean on
  `codex/refactor-architecture`.
- `git worktree list` after chat REPL cleanup contained no
  `opensquilla-refactor-*` worktrees other than
  `../opensquilla-refactor-integration`.
- Same-thread `spawn_agent` was available but hit the thread limit after five
  workers.
- External fallback script exists: `scripts/refactor_external_agent.sh`.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: Superpowers entrypoint read and used for stage skill selection.
- `superpowers:using-git-worktrees`:
  - Evidence: integration status and worktree list inspected before creating
    fixed worker worktrees.
- `superpowers:writing-plans`:
  - Evidence: this dispatch record defines coarse stage ownership and each
    worker was instructed to create its own full stage record before
    implementation.
- `superpowers:test-driven-development`:
  - Evidence: each worker prompt requires RED boundary/behavior tests before
    production edits and focused GREEN verification afterward.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: Gateway, Session, Provider, Channels, Tools, and Web UI scopes
    have disjoint worktrees, branches, and primary file ownership.
- `superpowers:verification-before-completion`:
  - Evidence: each worker prompt requires focused checks, touched-file checks,
    `scripts/refactor_gate.sh` if feasible, commit hashes, and residual-risk
    reporting before the main thread may merge.

## Worker Dispatch

- Gateway WebSocket connection core:
  - Worktree: `../opensquilla-refactor-agent-gateway`
  - Branch: `codex/refactor-gateway-websocket-connection-core`
  - Agent: `019e3e48-1ab0-7c31-82cc-0753af3d59ba`
  - Ownership: `src/opensquilla/gateway/websocket.py`, new gateway websocket
    helper modules, and focused gateway websocket tests.
- Session persistence/transcript repository:
  - Worktree: `../opensquilla-refactor-agent-session`
  - Branch: `codex/refactor-session-persistence-transcript-repository`
  - Agent: `019e3e48-1bf3-7a31-89d5-5c91f252bc5c`
  - Ownership: session manager/storage/model persistence boundary and focused
    session tests.
- Provider runtime/status boundary:
  - Worktree: `../opensquilla-refactor-agent-provider`
  - Branch: `codex/refactor-provider-runtime-status-boundary`
  - Agent: `019e3e48-1d11-7dd1-bc63-163278ddaa28`
  - Ownership: provider runtime status/model listing boundary and focused
    provider tests.
- Channels delivery boundary:
  - Worktree: `../opensquilla-refactor-agent-channels`
  - Branch: `codex/refactor-channels-delivery-boundary`
  - Agent: `019e3e48-1e1a-7d03-a800-6e4fafb037e4`
  - Ownership: channel manager/ingress/delivery helpers and focused channel
    tests.
- Tools MCP registry boundary:
  - Worktree: `../opensquilla-refactor-agent-tools`
  - Branch: `codex/refactor-tools-mcp-registry-boundary`
  - Agent: `019e3e48-1f94-7d11-b604-6f281a3910d4`
  - Ownership: tools registry/services/dispatch/visibility/MCP lifecycle and
    focused tool/MCP tests.
- Web UI browser runtime contract:
  - Worktree: `../opensquilla-refactor-agent-webui`
  - Branch: `codex/refactor-webui-browser-runtime-contract`
  - Agent route: external fallback because same-thread `spawn_agent` hit
    `agent thread limit reached`.
  - External worker PID: `39885`
  - Log: `.git/refactor-agents/20260519T133008+1000-webui.log`
  - Last message: `.git/refactor-agents/20260519T133008+1000-webui.last.md`
  - Ownership: gateway static JS/browser runtime contract harness and static
    Web UI tests.

## Integration Rules

- Do not merge a worker until its branch has a commit with a stage record,
  RED/GREEN evidence, focused checks, and gate evidence or an explicit
  infeasibility note.
- Merge completed workers one at a time into integration with `git merge
  --no-ff`, run focused conflict checks, then run full `scripts/refactor_gate.sh`
  after each accepted batch or compatible merge group.
- Record each merge hash, integration gate, and cleanup evidence in the
  worker's own stage record.
- Remove worker worktrees and branches only after their branch is merged and
  recorded.
