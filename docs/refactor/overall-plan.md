# OpenSquilla Refactor Control Plan

> For agentic workers: this plan is the durable control surface for the long-running
> architecture refactor. Before starting any implementation slice, use
> `superpowers:using-git-worktrees`, `superpowers:writing-plans`,
> `superpowers:test-driven-development`, and
> `superpowers:verification-before-completion`.

## Goal

Progressively refactor OpenSquilla with isolated worktrees, narrow integration
slices, complete quality gates, and user-facing compatibility preserved at every
stage.

The active integration branch is `codex/refactor-architecture`. Keep the
integration worktree separate from the main checkout. The main checkout is
observe-only for this refactor line.

## Operating Rules

1. Inspect current state before trusting prior context: `git status --short --branch`,
   `git rev-parse --short HEAD`, `git log --oneline -8`, and
   `find . -name AGENTS.md -print`.
2. Create one child worktree per slice from the integration branch.
3. Keep slices behavior-compatible and independently mergeable.
4. Prefer explicit boundaries already used in this repo:
   `*_workflows.py`, `*_presenters.py`, `*_gateway_queries.py`,
   `*_config_mutations.py`, `*_rpc_payload.py`, and focused runtime/operation
   modules.
5. Start each implementation slice with a stage plan derived from
   `docs/refactor/stage-template.md`.
6. Write a failing test before implementation when the slice changes code or
   executable behavior.
7. Commit child work only after local verification passes.
8. Merge child work into integration with `git merge --no-ff`.
9. Rerun the integration gate after each merge.
10. Do not mark the long-running goal complete until a requirement-by-requirement
    completion audit proves the full objective is satisfied.

## Current Architecture Map

- CLI: Typer commands in `src/opensquilla/cli`, progressively split into command
  entrypoints, presenters, gateway queries, config mutations, and workflows.
- Gateway/RPC/WebSocket: Starlette gateway surfaces in `src/opensquilla/gateway`
  with RPC tests under `tests/test_gateway`.
- Session/runtime: session management, task runtime, terminal replies, compaction,
  spawn groups, and persistence live under `src/opensquilla/session` and
  `src/opensquilla/gateway`.
- Provider/model routing: provider adapters, model catalog, pricing, router
  behavior, and runtime status live under `src/opensquilla/provider*` and
  `src/opensquilla/squilla_router`.
- Channels: adapter entries, webhook/websocket transports, dispatch, and inbound
  normalization live under `src/opensquilla/channels`.
- Tools/sandbox/MCP: builtin tools, shell/filesystem/network policy, MCP discovery,
  and safety contracts live under `src/opensquilla/tools`, `src/opensquilla/sandbox`,
  and related tests.
- Skills/memory/search/scheduler: skills loader/hub/runtime, memory sources,
  search runtime, and scheduler workflows live under `src/opensquilla/skills`,
  `src/opensquilla/memory`, `src/opensquilla/search`, and
  `src/opensquilla/scheduler`.
- Web UI static assets: gateway static views and browser-facing contracts live
  under `src/opensquilla/gateway/static` and `tests/test_gateway/*static*`.

## Risk Map

- User-facing behavior: CLI text, RPC payloads, WebSocket events, Web UI behavior,
  provider routing defaults, and channel replies must remain compatible.
- Public imports: do not remove compatibility imports until every reference and
  public contract has been audited.
- Concurrency: session lifecycle, task runtime, queue/admission, terminal cleanup,
  and WebSocket writers require focused tests before changes.
- Security: shell/filesystem/network tools, sandbox policy, uploads, SSRF checks,
  credentials, and MCP visibility require conservative changes and regression
  coverage.
- Test fragility: keep default tests offline, deterministic, credential-free, and
  safe for forks.

## Phase Roadmap

### Phase 1: CLI Boundary Thinning

- Target: continue reducing command files by moving display, gateway query,
  mutation, and workflow logic into focused modules.
- Candidate slices: remaining `chat_cmd.py` slash workflows, `gateway_cmd.py`
  lifecycle presentation, `cron_cmd.py` workflows, and any command file still
  mixing RPC, formatting, and command parsing.
- Do not change: command names, flags, JSON output shape, terminal text unless a
  test is intentionally updated.
- Gate: focused CLI tests, full ruff/mypy/pytest, gateway smoke.

### Phase 2: Gateway RPC Payload Boundaries

- Target: explicit request/response payload boundaries for sessions, tools, skills,
  config, usage, logs, approvals, and agent RPC surfaces.
- Do not change: public RPC method names or payload keys without compatibility
  coverage.
- Gate: RPC payload tests, public surface baseline tests, full quality gate.

### Phase 3: Session and Runtime Services

- Target: isolate task runtime, terminal lifecycle, spawn groups, queues,
  compaction, and persistence into service boundaries.
- Do not change: task completion ordering, cancellation semantics, terminal
  cleanup, or session key contracts.
- Gate: runtime/session concurrency tests plus full quality gate.

### Phase 4: Provider and Model Routing

- Target: decouple provider registry/factory/runtime support/model catalog/pricing
  from concrete provider classes.
- Do not change: default model selection, provider attribution, usage accounting,
  or compatibility payloads.
- Gate: provider factory, catalog, routing, pricing, and usage tests.

### Phase 5: Channels

- Target: separate webhook/websocket transports, message normalization, dispatch,
  and reply contracts.
- Do not change: adapter configuration fields, dedupe behavior, or inbound reply
  semantics.
- Gate: channel contract tests, adapter tests, gateway dispatch tests.

### Phase 6: Tools, Sandbox, and Security

- Target: make permissions and policy boundaries explicit for shell, filesystem,
  network, patch, uploads, web fetch, MCP, and skills hub operations.
- Do not change: safe default policy or approval behavior without regression
  tests.
- Gate: security, sandbox, tool policy, and public tool surface tests.

### Phase 7: Web UI Contracts

- Target: isolate browser-side RPC client/view state/payload assumptions.
- Do not change: visible Web UI workflows without browser/static tests.
- Gate: static view tests and browser smoke when applicable.

### Phase 8: Release and Documentation Convergence

- Target: update architecture maps, refactor reports, contribution guidance, and
  release checklists after implementation evidence exists.
- Gate: README/link/release hygiene tests plus `uv build --wheel` when preparing a PR.

## Standard Slice Lifecycle

1. Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture`
   in the integration worktree.
2. Create a child branch and worktree:
   `git worktree add ../opensquilla-refactor-<slice> -b codex/refactor-<slice>`.
3. Generate or copy a stage plan from `docs/refactor/stage-template.md`.
4. Use `superpowers:writing-plans` to turn the stage into concrete tasks.
5. Use `superpowers:test-driven-development` for code or executable behavior.
6. Run focused tests, then `scripts/refactor_gate.sh`.
7. Commit with the required co-author trailer.
8. Merge into integration with `git merge --no-ff`.
9. Run `scripts/refactor_gate.sh` again from integration.
10. Record child hash, integration hash, verification output, and next slice.

## Standard Gate

Use `scripts/refactor_gate.sh` for the complete gate. It includes:

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway start/status/stop/status smoke with isolated state and workspace dirs

When preparing a public PR, also run `uv build --wheel`.

## Context Recovery

If context was compacted, interrupted, or resumed:

1. Run `scripts/refactor_preflight.sh --allow-dirty` in the current worktree.
2. Read this file and the active stage plan.
3. Re-check actual git state before continuing.
4. Treat old chat summaries as hints only.
5. Resume the smallest unfinished step; do not restart broad refactors from memory.
