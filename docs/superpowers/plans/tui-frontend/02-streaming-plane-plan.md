# TUI Streaming Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make long token streams low-latency and measurable by batching text deltas through a dedicated streaming plane instead of triggering structured UI refreshes for every token.

**Architecture:** A renderer-neutral `StreamingPlane` buffers text deltas and flushes by time, byte count, newline, or finalization. The terminal renderer keeps its raw output fast path, while plugins receive coalesced `text_flush` events rather than every token.

**Tech Stack:** Python 3.12, asyncio, monotonic clocks, prompt-toolkit/Rich terminal adapter, pytest.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan owns token streaming policy and terminal renderer integration. It must
not change router semantics or transcript viewport logic.

## Files

- Create: `src/opensquilla/cli/tui/backend/streaming.py`
- Create: `tests/unit/cli/tui/test_streaming_plane.py`
- Modify: `src/opensquilla/cli/tui/backend/contracts.py`
- Modify: `src/opensquilla/cli/tui/terminal/renderer.py`
- Modify: `src/opensquilla/cli/tui/terminal/stream.py`
- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `scripts/bench_tui_replay.py`

## Flush Policy

Default policy:

- `max_delay_ms = 33`
- `max_chars = 2048`
- flush immediately when finalized
- flush immediately when a delta contains `\n` and the buffer has at least 256
  chars
- emit one `text_flush` domain event per flush when an event sink is present

The policy should be configurable in tests but stable in production defaults.

## Tasks

### Task 1: Add streaming buffer policy

**Files:**

- Create: `src/opensquilla/cli/tui/backend/streaming.py`
- Create: `tests/unit/cli/tui/test_streaming_plane.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`

- [ ] Add `StreamingFlushPolicy`.
- [ ] Add `StreamingPlane` with `append(delta)`, `flush(force=False)`, and `finish()`.
- [ ] Add counters: `delta_count`, `flush_count`, `text_chars`, `max_buffer_chars`.
- [ ] Add tests for delay-based, size-based, newline-based, and final flush.
- [ ] Add import-boundary coverage so `backend.streaming` does not import prompt-toolkit.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_streaming_plane.py tests/unit/cli/tui/test_contracts.py -q
```

Expected: streaming policy tests pass.

### Task 2: Integrate coalesced text flushes

**Files:**

- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `tests/unit/cli/tui/test_streaming_plane.py`

- [ ] Wrap renderer `aappend_text()` calls in a streaming plane when a TUI output handle or event sink is present.
- [ ] Preserve exact final `renderer.buffer` content.
- [ ] Emit `text_flush` events to the optional event sink only after coalesced flushes.
- [ ] Keep the fallback renderer behavior unchanged when no output handle exists.
- [ ] Add a fake renderer test that feeds 4,000 deltas and asserts far fewer flush events than deltas.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_streaming_plane.py tests/unit/cli/repl/test_turn_stream_boundaries.py -q
```

Expected: text is preserved and flush count is bounded.

### Task 3: Preserve terminal raw streaming behavior

**Files:**

- Modify: `src/opensquilla/cli/tui/terminal/renderer.py`
- Modify: `src/opensquilla/cli/tui/terminal/stream.py`
- Modify: `tests/unit/cli/tui/test_streaming_plane.py`
- Modify: `tests/test_cli/test_repl_waiting_indicator.py`

- [ ] Ensure `TerminalRenderer.aappend_text()` accepts already-coalesced chunks.
- [ ] Keep `stream_output()` as the low-level output region for current assistant messages.
- [ ] Ensure the waiting indicator and footer finalization still behave as before.
- [ ] Add tests that no Rich Live render path is introduced for streaming text.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_streaming_plane.py tests/test_cli/test_repl_waiting_indicator.py -q
```

Expected: terminal streaming remains raw and bounded.

### Task 4: Add benchmark counters

**Files:**

- Modify: `scripts/bench_tui_replay.py`
- Modify: `tests/unit/cli/tui/test_tui_replay_harness.py`

- [ ] Capture `flush_count`, `max_buffer_chars`, and `coalescing_ratio`.
- [ ] Add assertions that long-stream replay reports fewer flushes than deltas.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_tui_replay_harness.py tests/unit/cli/tui/test_streaming_plane.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/streaming-plane-long-stream.json
```

Expected: summary includes streaming counters and no errors.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_streaming_plane.py tests/unit/cli/tui/test_tui_replay_harness.py tests/test_cli/test_repl_waiting_indicator.py -q
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/streaming-plane-long-stream.json
uv run mypy src/opensquilla/cli/tui/backend src/opensquilla/cli/tui/terminal src/opensquilla/cli/chat/turn_stream.py --show-error-codes
uv run ruff check src/opensquilla/cli/tui src/opensquilla/cli/chat/turn_stream.py tests/unit/cli/tui
```

## Acceptance Criteria

- Long token streams do not cause one structured UI update per token.
- Final assistant text remains byte-for-byte equivalent after coalescing.
- Terminal output keeps the existing raw streaming fast path.
- Bench summaries expose flush behavior for regression comparison.
