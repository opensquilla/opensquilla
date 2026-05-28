# TUI Frontend Architecture Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an extensible, low-latency OpenSquilla TUI frontend architecture with plugin-visible model routing, a fast token streaming path, bounded history/tool-card rendering, and a measured path toward Textual.

**Architecture:** The system is split into a streaming plane for token deltas and a structured UI plane for plugins, router HUD, tool cards, usage, and history. Existing prompt-toolkit/Rich remains the production backend while event contracts, plugin projections, and performance gates are established. Textual is evaluated behind the same contracts and promoted only if replay benchmarks pass.

**Tech Stack:** Python 3.12, asyncio, prompt-toolkit, Rich, pytest, mypy, ruff, optional Textual evaluation behind an explicit backend flag.

---

## Plan Map

This master plan coordinates the child plans. Each child plan is owned as a
coarse logical block and should be implemented as one milestone before running
its phase gate.

- [00 Baseline And Replay Harness](tui-frontend/00-baseline-and-replay-harness-plan.md)
- [01 Event And Plugin Runtime](tui-frontend/01-event-and-plugin-runtime-plan.md)
- [02 Streaming Plane](tui-frontend/02-streaming-plane-plan.md)
- [03 Transcript Viewport](tui-frontend/03-transcript-viewport-plan.md)
- [04 Router HUD Plugin](tui-frontend/04-router-hud-plugin-plan.md)
- [05 Renderer Backend Evaluation](tui-frontend/05-renderer-backend-evaluation-plan.md)
- [06 Integration And Release Gate](tui-frontend/06-integration-and-release-gate-plan.md)

The architecture design that explains the decision is
[`docs/superpowers/specs/2026-05-28-tui-frontend-architecture-design.md`](../specs/2026-05-28-tui-frontend-architecture-design.md).

## Execution Principles

- Implement by coherent subsystem, not by scattered micro-fixes.
- Run focused tests while a subsystem is being built.
- Run the child-plan phase gate after the subsystem is complete.
- Run broad CLI/TUI gates only at integration milestones.
- Keep renderer-independent contracts under `src/opensquilla/cli/tui/backend`.
- Keep prompt-toolkit/Rich specifics under `src/opensquilla/cli/tui/terminal`.
- Keep chat turn event bridging under `src/opensquilla/cli/chat`.
- Do not change router model-selection semantics.
- Do not add Textual as a required production dependency until the evaluation
  plan passes and the project accepts that backend.

## Branch And Checkout Constraint

Implementation for this plan lives on local branch `codex/tui-frontend`, created
from `dev` at commit `69097de2` (`Preserve router decision semantics across
replay`). Do not implement this TUI frontend work directly on `dev`.

Before starting or resuming implementation, run:

```bash
git branch --show-current
git status --short --branch
```

Expected:

```text
codex/tui-frontend
## codex/tui-frontend
```

If the checkout is on `dev`, switch back before editing:

```bash
git switch codex/tui-frontend
```

Only rebase or merge from `dev` under leader control, after checking current
worktree status and preserving user/agent changes.

## Tooling And Agent Orchestration Requirements

Every implementation session for this plan must start from the repository root
`/Users/cwan0785/opensquilla` on `codex/tui-frontend` unless the leader
explicitly creates an isolated worktree from that branch. Before editing code,
the leader and each child agent must do the following:

1. Read the applicable `AGENTS.md` instructions.
2. Use the Superpowers skill surface. For implementation, prefer
   `superpowers:subagent-driven-development`; use
   `superpowers:executing-plans` only when running inline without child agents.
3. Call Serena `initial_instructions` and activate the OpenSquilla project.
4. Use Serena for symbol-level code exploration when investigating Python
   modules, especially shared files such as `turn_stream.py`, `contracts.py`,
   `runtime_bridge.py`, and terminal renderer modules.
5. Use `rg`/`rg --files` for broad text and file discovery.
6. Use `apply_patch` for manual edits and avoid destructive git commands.
7. Keep an active checklist for the current child plan and mark items as they
   are completed.

Use native Codex subagents for independent child plans once their dependencies
are satisfied. The leader should pass each subagent a single child-plan path,
its owned files, phase gate commands, and a warning that other agents may be
editing nearby code. Subagents should not switch plans, widen scope, or edit
shared files without escalating to the leader.

Parallel execution is encouraged only where the dependency graph allows it:

- `00` must finish before `01`.
- `01` must finish before `02`, `03`, and `04`.
- `02`, `03`, and `04` may run in parallel with separate file ownership.
- `05` may start after replay fixtures and backend contracts exist.
- `06` is leader-owned and runs after the implementation lanes converge.

The leader owns merge order and integration verification. Do not run broad
repo-wide gates after every tiny edit; run focused tests inside each child plan,
then the child phase gate, then the milestone/final gates from this master plan.

## Dependency Graph

```text
00 baseline/replay harness
  -> 01 event/plugin runtime
      -> 02 streaming plane
      -> 03 transcript viewport
      -> 04 router HUD plugin
          -> 06 integration gate
  -> 05 renderer backend evaluation
      -> 06 integration gate
```

`02`, `03`, and `04` may run in parallel after `01` lands, as long as each agent
respects the ownership boundaries below.

## Multi-Agent Ownership

Use one leader agent to own coordination, merge order, and final verification.
Use child agents only for complete child-plan blocks.

| Agent Lane | Owns | Shared Files To Avoid Without Leader Approval |
| --- | --- | --- |
| Leader | merge order, test gates, shared contract decisions | all shared files |
| Baseline Agent | replay fixtures and benchmark script | none after `00` lands |
| Event Agent | plugin runtime and event bridge contracts | `turn_stream.py`, `contracts.py`, `events.py` |
| Streaming Agent | token batching and fast flush policy | `terminal/renderer.py`, `terminal/stream.py` |
| Transcript Agent | transcript store and viewport projection | backend transcript modules only |
| Router HUD Agent | router plugin and terminal HUD projection | `turn_stream.py`, `terminal/app.py` |
| Renderer Agent | Textual evaluation backend and benchmark comparison | `pyproject.toml`, backend contract files |
| Verification Agent | gate commands, review notes, regression checks | docs and tests only unless fixing tests |

When two child plans need the same shared file, the leader sequences those
patches. The child agent reports the required change and waits for the leader to
assign ownership.

## Milestones

### Milestone A: Baseline And Contracts

Implement child plans `00` and `01`.

Acceptance:

- replay harness can generate long-stream and dense-history runs without a live
  provider.
- plugin runtime dispatches normalized domain events and catches plugin errors.
- backend import-boundary tests still prove prompt-toolkit is not imported by
  backend core modules.

Gate:

```bash
uv run pytest tests/unit/cli/tui/test_contracts.py tests/unit/cli/tui/test_runtime.py -q
uv run pytest tests/unit/cli/tui/test_plugin_runtime.py tests/unit/cli/tui/test_tui_replay_harness.py -q
uv run mypy src/opensquilla/cli/tui/backend src/opensquilla/cli/chat/turn_stream.py --show-error-codes
uv run ruff check src/opensquilla/cli/tui src/opensquilla/cli/chat tests/unit/cli/tui
```

### Milestone B: Performance Core

Implement child plans `02` and `03`.

Acceptance:

- text delta rendering is batched by a measurable flush policy.
- dense histories project to a bounded viewport slice.
- tool cards default to summaries and expose detail only through selected state.

Gate:

```bash
uv run pytest tests/unit/cli/tui/test_streaming_plane.py tests/unit/cli/tui/test_transcript_viewport.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/dense-history.json
uv run mypy src/opensquilla/cli/tui/backend src/opensquilla/cli/tui/terminal --show-error-codes
```

### Milestone C: Router Visibility

Implement child plan `04`.

Acceptance:

- standalone and gateway turn streams both surface router decisions to the TUI
  event/plugin layer.
- terminal HUD shows model route, baseline, source, confidence, savings,
  fallback, rollout, and observe/full state.
- existing WebUI router event behavior remains unchanged.

Gate:

```bash
uv run pytest tests/test_engine/test_router_decision_event.py tests/test_gateway/test_chat_view_static.py -q
uv run pytest tests/unit/cli/tui/test_router_hud_plugin.py tests/unit/cli/repl/test_turn_stream_boundaries.py -q
uv run mypy src/opensquilla/engine/types.py src/opensquilla/cli/chat/turn_stream.py src/opensquilla/cli/tui --show-error-codes
```

### Milestone D: Renderer Decision

Implement child plan `05`.

Acceptance:

- Textual evaluation backend runs against the same replay fixtures.
- evaluation produces a written pass/fail recommendation with latency,
  throughput, memory, and dense-history evidence.
- no production dependency or default backend changes unless the evaluation
  explicitly passes.

Gate:

```bash
uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/terminal-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture long-stream --summary-json .artifacts/tui/textual-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/terminal-dense-history.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture dense-history --summary-json .artifacts/tui/textual-dense-history.json
```

### Milestone E: Integration And Release Gate

Implement child plan `06`.

Acceptance:

- backend selection is explicit and defaults to the existing terminal backend.
- docs explain plugin slots, router HUD behavior, benchmark use, and fallback
  behavior.
- all broad CLI/TUI gates pass or have documented external blockers.

Gate:

```bash
uv run pytest tests/unit/cli/tui tests/unit/cli/repl tests/test_cli/test_chat_cmd.py tests/test_engine/test_router_decision_event.py tests/test_gateway/test_chat_view_static.py -q
uv run ruff check src tests
uv run mypy src/opensquilla/cli src/opensquilla/engine --show-error-codes
python -m compileall src/opensquilla
git diff --check
```

## Commit Strategy

Use one meaningful commit per child plan or per milestone-sized slice. Do not
commit after each tiny internal step. Commit messages must follow the root
AGENTS Lore protocol.

Suggested commit grouping:

- `Plan TUI frontend architecture rollout`
- `Add TUI replay benchmark harness`
- `Add TUI event plugin runtime`
- `Batch terminal token streaming`
- `Add transcript viewport projection`
- `Show router decisions in TUI HUD`
- `Evaluate Textual renderer backend`
- `Wire TUI frontend integration gates`

## Stop Conditions

Stop and ask the leader, not the user, when a child agent needs to change files
outside its ownership block. Stop and ask the user only if the implementation
requires a new production dependency, changes default CLI behavior, or changes
router model-selection semantics.

## Execution Handoff

Plan package complete. Recommended execution mode is subagent-driven:

1. Start with `00` in one lane.
2. Run `01` after `00` passes.
3. Run `02`, `03`, and `04` in parallel after `01` lands.
4. Run `05` after replay fixtures and backend contracts exist.
5. Run `06` as a leader-owned integration pass.
