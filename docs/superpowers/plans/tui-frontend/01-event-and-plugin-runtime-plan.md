# TUI Event And Plugin Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a renderer-independent TUI event bus and plugin runtime that can consume structured turn events without coupling backend code to prompt-toolkit, Rich, or a specific renderer.

**Architecture:** `cli.chat.turn_stream` emits normalized TUI domain events through an optional sink. `cli.tui.backend` owns the domain event and plugin protocols. Plugins update small projections that renderers can read through named slots.

**Tech Stack:** Python 3.12, dataclasses, Protocol, pytest, mypy.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan owns the shared event/plugin contract. Because it touches shared files,
the leader should land this plan before `02`, `03`, and `04` begin.

## Files

- Create: `src/opensquilla/cli/tui/backend/domain_events.py`
- Create: `src/opensquilla/cli/tui/backend/plugins.py`
- Create: `tests/unit/cli/tui/test_plugin_runtime.py`
- Modify: `src/opensquilla/cli/tui/backend/events.py`
- Modify: `src/opensquilla/cli/tui/backend/contracts.py`
- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `src/opensquilla/cli/tui/adapters/turn_stream_defaults.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`

## Domain Model

Create `TuiDomainEvent` with:

- `kind: str`
- `source: Literal["runtime", "gateway", "turn_runner", "renderer"]`
- `payload: Mapping[str, Any]`
- `turn_id: str | None`
- `timestamp_ms: int`

Create event kind constants for:

- `text_delta`
- `text_flush`
- `tool_started`
- `tool_finished`
- `router_decision`
- `warning`
- `error`
- `done`
- `status`

Create `TuiPlugin` protocol with:

- `plugin_id: str`
- `slots: frozenset[str]`
- `on_event(event: TuiDomainEvent, context: TuiPluginContext) -> None`
- `snapshot(slot: str) -> object | None`

Create `TuiPluginManager` with:

- ordered plugin registration
- non-throwing dispatch
- per-plugin error capture
- `snapshot(slot)` combining plugin snapshots by priority

## Tasks

### Task 1: Define domain events

**Files:**

- Create: `src/opensquilla/cli/tui/backend/domain_events.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`

- [ ] Add the `TuiDomainEvent` dataclass and event kind constants.
- [ ] Add `now_ms()` helper for event construction.
- [ ] Update backend package contract lists in `test_contracts.py` so the new backend module is allowed.
- [ ] Add tests proving the new module imports without prompt-toolkit and Rich.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_contracts.py -q
```

Expected: contract tests pass.

### Task 2: Define plugin runtime

**Files:**

- Create: `src/opensquilla/cli/tui/backend/plugins.py`
- Create: `tests/unit/cli/tui/test_plugin_runtime.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`

- [ ] Add `TuiPluginContext` with `set_state(key, value)`, `get_state(key, default)`, and `record_error(plugin_id, message)`.
- [ ] Add `TuiPlugin` protocol and `TuiPluginManager`.
- [ ] Ensure plugin exceptions are captured and do not stop event dispatch.
- [ ] Add tests for registration order, snapshot lookup, and error capture.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_plugin_runtime.py tests/unit/cli/tui/test_contracts.py -q
```

Expected: plugin runtime and boundary tests pass.

### Task 3: Add optional turn-stream event sink

**Files:**

- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `src/opensquilla/cli/tui/adapters/turn_stream_defaults.py`
- Modify: `tests/unit/cli/repl/test_turn_stream_boundaries.py`
- Modify: `tests/unit/cli/tui/test_plugin_runtime.py`

- [ ] Extend `TurnStreamDependencies` with `tui_event_sink: Callable[[TuiDomainEvent], None] | None = None`.
- [ ] Add a local helper in `turn_stream.py` that emits only when the sink is present.
- [ ] Emit structured events for tool start, tool finish, warning, error, done, and status paths.
- [ ] Keep text delta emission out of this generic sink until the streaming plane plan adds coalesced flush events.
- [ ] Ensure default dependencies pass `None`, preserving current behavior.
- [ ] Add tests with a fake sink proving gateway and standalone paths emit the same event kind names for tool and done events.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_plugin_runtime.py tests/unit/cli/repl/test_turn_stream_boundaries.py -q
```

Expected: event sink behavior is covered and existing turn-stream boundary tests pass.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_plugin_runtime.py tests/unit/cli/tui/test_contracts.py tests/unit/cli/repl/test_turn_stream_boundaries.py -q
uv run mypy src/opensquilla/cli/tui/backend src/opensquilla/cli/chat/turn_stream.py --show-error-codes
uv run ruff check src/opensquilla/cli/tui/backend src/opensquilla/cli/chat/turn_stream.py tests/unit/cli/tui tests/unit/cli/repl/test_turn_stream_boundaries.py
```

## Acceptance Criteria

- Plugin contracts live in backend modules and do not import terminal adapters.
- Turn streaming can emit structured domain events without changing renderer
  output.
- Plugin failures are contained and observable.
- Existing CLI behavior remains unchanged when no plugin manager is installed.
