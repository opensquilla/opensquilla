# TUI Transcript Viewport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support hundreds of history messages and tool cards by separating transcript data from visible UI projection.

**Architecture:** A backend transcript store records messages, tool cards, router decisions, warnings, and usage summaries. A viewport projector returns only visible items plus overscan, and tool cards render as summaries unless selected for detail.

**Tech Stack:** Python 3.12, dataclasses, immutable snapshots, pytest.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan owns transcript state and viewport projection. It must not choose a
renderer backend or modify terminal keybindings except through integration tasks
assigned by the leader.

## Files

- Create: `src/opensquilla/cli/tui/backend/transcript.py`
- Create: `tests/unit/cli/tui/test_transcript_viewport.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`
- Modify: `scripts/bench_tui_replay.py`

## Data Model

Transcript items:

- `MessageItem`: role, text, run id, timestamp
- `ToolItem`: tool id, name, status, args preview, output preview, expanded flag
- `RouterDecisionItem`: tier, model, baseline, confidence, rollout state
- `StatusItem`: message and style
- `UsageItem`: token and cost summary

Viewport projection:

- input: transcript snapshot, scroll offset, viewport height, overscan
- output: ordered `VisibleTranscriptItem` list
- invariant: output length is bounded by viewport height and overscan, not by
  total transcript length

## Tasks

### Task 1: Add transcript store

**Files:**

- Create: `src/opensquilla/cli/tui/backend/transcript.py`
- Create: `tests/unit/cli/tui/test_transcript_viewport.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`

- [ ] Add dataclasses for message, tool, router, status, and usage items.
- [ ] Add `TranscriptStore.append(item)`, `snapshot()`, `clear()`, and `__len__()`.
- [ ] Add stable item ids for messages and tools.
- [ ] Add tests for append order, snapshot immutability, and clear behavior.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_transcript_viewport.py tests/unit/cli/tui/test_contracts.py -q
```

Expected: transcript store tests pass and backend boundaries remain clean.

### Task 2: Add tool summary caps

**Files:**

- Modify: `src/opensquilla/cli/tui/backend/transcript.py`
- Modify: `tests/unit/cli/tui/test_transcript_viewport.py`

- [ ] Add `ToolPreviewPolicy` with `max_arg_chars`, `max_output_lines`, and `max_output_chars`.
- [ ] Add preview builders that preserve text order and mark truncation.
- [ ] Add tests for long JSON args, long stdout, image placeholders, and error output.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_transcript_viewport.py -q
```

Expected: long tool payloads project to bounded summaries.

### Task 3: Add viewport projector

**Files:**

- Modify: `src/opensquilla/cli/tui/backend/transcript.py`
- Modify: `tests/unit/cli/tui/test_transcript_viewport.py`

- [ ] Add `ViewportRequest` and `ViewportProjection`.
- [ ] Add projection by row estimate, where collapsed items cost one row and
  expanded items cost their capped row count.
- [ ] Add overscan support.
- [ ] Add tests with 250 messages and 120 tool cards proving visible output is
  bounded.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_transcript_viewport.py -q
```

Expected: dense history projection is bounded and deterministic.

### Task 4: Connect replay harness to transcript projection

**Files:**

- Modify: `scripts/bench_tui_replay.py`
- Modify: `tests/unit/cli/tui/test_tui_replay_harness.py`
- Modify: `tests/unit/cli/tui/test_transcript_viewport.py`

- [ ] Add dense-history summary fields: `transcript_items`, `visible_items`,
  `expanded_tools`, and `projection_wall_ms`.
- [ ] Confirm dense-history replay uses viewport projection rather than rendering
  every item.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_tui_replay_harness.py tests/unit/cli/tui/test_transcript_viewport.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/transcript-dense-history.json
```

Expected: dense-history summary shows bounded visible item count.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_transcript_viewport.py tests/unit/cli/tui/test_tui_replay_harness.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/transcript-dense-history.json
uv run mypy src/opensquilla/cli/tui/backend/transcript.py --show-error-codes
uv run ruff check src/opensquilla/cli/tui/backend/transcript.py tests/unit/cli/tui/test_transcript_viewport.py
```

## Acceptance Criteria

- Transcript state is renderer-independent.
- Tool cards have deterministic summary caps.
- Dense history projection is bounded by viewport size and overscan.
- Replay summaries can prove dense-history behavior without a live terminal.
