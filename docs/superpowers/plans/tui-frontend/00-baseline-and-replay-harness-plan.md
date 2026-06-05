# TUI Baseline And Replay Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a deterministic replay harness that measures long token streams and dense history/tool-card scenarios without requiring a live provider.

**Architecture:** Synthetic fixtures generate normalized turn events and drive existing renderers through the same public renderer contracts used by the CLI. The harness writes JSON summaries under `.artifacts/tui/` so later phases can compare regressions without broad test runs.

**Tech Stack:** Python 3.12, asyncio, pytest, prompt-toolkit/Rich terminal renderer, JSON summary output.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan owns benchmark and fixture files only. It must not change production
TUI behavior except for narrowly exposing already-existing renderer factories if
needed by the harness.

## Files

- Create: `scripts/bench_tui_replay.py`
- Create: `tests/unit/cli/tui/test_tui_replay_harness.py`
- Create: `tests/unit/cli/tui/replay_fixtures.py`
- Modify only if necessary: `tests/unit/cli/tui/test_contracts.py`
- Output at runtime, not committed: `.artifacts/tui/*.json`

## Fixture Shapes

`long-stream`:

- one user input
- one router decision event
- 4,000 text deltas
- 160,000 total streamed characters
- 4 tool start/end pairs interleaved between text sections
- one done event with usage

`dense-history`:

- 250 assistant/user message pairs
- 120 tool cards
- 20 expanded tool-card candidates
- 4 router decisions from different tiers
- enough text to exceed one terminal viewport by at least 30x

## Tasks

### Task 1: Add replay fixtures

**Files:**

- Create: `tests/unit/cli/tui/replay_fixtures.py`
- Test: `tests/unit/cli/tui/test_tui_replay_harness.py`

- [ ] Define `ReplayEvent` as a frozen dataclass with `kind: str`, `payload: dict[str, object]`, and `timestamp_ms: int`.
- [ ] Add `build_long_stream_events()` returning the long-stream fixture shape.
- [ ] Add `build_dense_history_events()` returning the dense-history fixture shape.
- [ ] Add tests asserting event counts, text byte counts, tool counts, and router decision counts.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_tui_replay_harness.py -q
```

Expected: tests pass and do not import a live provider.

### Task 2: Add benchmark runner

**Files:**

- Create: `scripts/bench_tui_replay.py`
- Modify: `tests/unit/cli/tui/test_tui_replay_harness.py`

- [ ] Implement CLI args: `--renderer`, `--fixture`, `--summary-json`, and `--repeat`.
- [ ] Support `--renderer terminal` by driving the current terminal renderer through a dummy output handle.
- [ ] Support `--fixture long-stream` and `--fixture dense-history`.
- [ ] Write a JSON summary with `renderer`, `fixture`, `event_count`, `text_chars`, `tool_count`, `router_decision_count`, `wall_ms`, `flush_count`, `max_buffer_chars`, and `errors`.
- [ ] Test the summary writer with a temp path.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_tui_replay_harness.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/baseline-long-stream.json
```

Expected: the command exits with status 0 and writes a JSON summary.

### Task 3: Record baseline evidence

**Files:**

- Modify: no source files
- Runtime output: `.artifacts/tui/baseline-long-stream.json`
- Runtime output: `.artifacts/tui/baseline-dense-history.json`

- [ ] Run long-stream replay three times:

```bash
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --repeat 3 --summary-json .artifacts/tui/baseline-long-stream.json
```

- [ ] Run dense-history replay three times:

```bash
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --repeat 3 --summary-json .artifacts/tui/baseline-dense-history.json
```

- [ ] Confirm both summaries include no errors.
- [ ] Keep the summaries as local evidence for later comparison; do not commit `.artifacts/`.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_tui_replay_harness.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/baseline-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/baseline-dense-history.json
uv run ruff check scripts/bench_tui_replay.py tests/unit/cli/tui/test_tui_replay_harness.py tests/unit/cli/tui/replay_fixtures.py
```

## Acceptance Criteria

- The harness requires no network, API keys, or live provider.
- The harness can replay both target performance scenarios.
- JSON summaries are stable enough for later relative comparisons.
- The production TUI remains behaviorally unchanged.
