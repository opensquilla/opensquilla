# TUI Renderer Backend Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate whether Textual should become the richer structured UI backend while preserving the streaming fast path and current terminal backend as the default.

**Architecture:** Add an experimental renderer backend behind explicit selection. It consumes the same plugin snapshots, transcript projections, and replay fixtures as the terminal backend. It is promoted only after benchmark evidence shows acceptable behavior for long streams and dense histories.

**Tech Stack:** Python 3.12, optional Textual dependency, existing TUI backend contracts, replay benchmark harness, pytest.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan evaluates a renderer backend. It must not change the default CLI
backend. Any production dependency change requires explicit leader and user
approval before merge.

## Files

- Create: `src/opensquilla/cli/tui/renderers/__init__.py`
- Create: `src/opensquilla/cli/tui/renderers/selection.py`
- Create: `src/opensquilla/cli/tui/renderers/textual_backend.py`
- Create: `tests/unit/cli/tui/test_renderer_backend_contract.py`
- Modify: `scripts/bench_tui_replay.py`
- Modify: `pyproject.toml` only if the evaluation dependency is accepted
- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py` only when wiring an explicit backend flag

## Evaluation Thresholds

Textual can be recommended only if all are true on replay fixtures:

- long-stream replay preserves final text exactly.
- long-stream coalesced flush count stays within 25% of terminal backend.
- dense-history visible item count remains bounded by viewport projection.
- no benchmark run reports plugin dispatch errors.
- no existing prompt-toolkit backend behavior changes.

These are relative gates, not claims that Textual is universally faster.

## Tasks

### Task 1: Add renderer selection contract

**Files:**

- Create: `src/opensquilla/cli/tui/renderers/__init__.py`
- Create: `src/opensquilla/cli/tui/renderers/selection.py`
- Create: `tests/unit/cli/tui/test_renderer_backend_contract.py`

- [ ] Define `TuiRendererBackend` protocol with `backend_id`, `create_renderer()`,
  `supports_structured_ui`, and `supports_streaming_fast_path`.
- [ ] Add terminal backend adapter registration without changing current launch
  behavior.
- [ ] Add tests proving terminal remains the default selection.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py -q
```

Expected: backend selection exists and defaults to terminal.

### Task 2: Add experimental Textual backend

**Files:**

- Create: `src/opensquilla/cli/tui/renderers/textual_backend.py`
- Modify: `tests/unit/cli/tui/test_renderer_backend_contract.py`

- [ ] Implement the backend so importing OpenSquilla does not require Textual
  unless the Textual backend is selected.
- [ ] Provide a graceful unavailable result when Textual is not installed.
- [ ] Render plugin snapshots and transcript viewport projections in a minimal
  structured layout.
- [ ] Keep token streaming through the streaming plane rather than full app
  refresh per delta.
- [ ] Add tests for unavailable Textual behavior and renderer contract shape.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py -q
```

Expected: tests pass whether Textual is installed or absent.

### Task 3: Benchmark terminal versus Textual

**Files:**

- Modify: `scripts/bench_tui_replay.py`
- Modify: `tests/unit/cli/tui/test_tui_replay_harness.py`
- Runtime output: `.artifacts/tui/*textual*.json`

- [ ] Add `--renderer textual` support that skips with a clear message if the
  optional dependency is unavailable.
- [ ] Run terminal and Textual replay for both fixtures when Textual is present.
- [ ] Write comparison summaries with relative flush count, wall time, and error
  fields.
- [ ] Run:

```bash
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/terminal-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture long-stream --summary-json .artifacts/tui/textual-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/terminal-dense-history.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture dense-history --summary-json .artifacts/tui/textual-dense-history.json
```

Expected: terminal always runs; Textual either runs cleanly or reports unavailable
without breaking the suite.

### Task 4: Write renderer recommendation

**Files:**

- Create: `docs/superpowers/plans/tui-frontend/renderer-evaluation-result.md`

- [ ] Summarize benchmark evidence.
- [ ] Recommend one of: keep terminal only, keep terminal plus experimental
  Textual, or promote Textual behind an explicit flag.
- [ ] Include exact commands used and paths to local JSON summaries.
- [ ] Do not change default backend in this task.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py tests/unit/cli/tui/test_tui_replay_harness.py -q
uv run mypy src/opensquilla/cli/tui/renderers scripts/bench_tui_replay.py --show-error-codes
uv run ruff check src/opensquilla/cli/tui/renderers scripts/bench_tui_replay.py tests/unit/cli/tui
```

## Acceptance Criteria

- Backend selection defaults to the current terminal backend.
- Textual can be evaluated without forcing a production dependency.
- Benchmark evidence drives the renderer recommendation.
- The streaming fast path remains part of the design even for structured
  backends.
