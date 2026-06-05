# TUI Router HUD Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show how OpenSquilla selects models per turn through a renderer-independent router HUD plugin.

**Architecture:** `RouterHudPlugin` consumes normalized `router_decision` domain events and publishes a compact slot snapshot. The terminal backend renders that snapshot in the toolbar/status region, while future renderers can show richer inspector panels from the same plugin state.

**Tech Stack:** Python 3.12, existing `RouterDecisionEvent`, TUI plugin runtime, prompt-toolkit toolbar projection, pytest.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan owns router decision display only. It must not modify router
classification, tier selection, pricing, rollout, or provider behavior.

## Files

- Create: `src/opensquilla/cli/tui/plugins/__init__.py`
- Create: `src/opensquilla/cli/tui/plugins/router_hud.py`
- Create: `tests/unit/cli/tui/test_router_hud_plugin.py`
- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `src/opensquilla/cli/tui/adapters/turn_stream_defaults.py`
- Modify: `src/opensquilla/cli/tui/terminal/app.py`
- Modify: `src/opensquilla/cli/tui/terminal/prompt.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`
- Modify: `tests/test_engine/test_router_decision_event.py` only if display requires an additional stable field

## Router HUD Snapshot

Snapshot fields:

- `tier`
- `tier_index`
- `model`
- `baseline_model`
- `source`
- `confidence`
- `savings_pct`
- `fallback`
- `thinking_mode`
- `prompt_policy`
- `routing_applied`
- `rollout_phase`
- `label`
- `style`

Label examples:

- full routing: `route t2 -> claude-sonnet-4.6 71% save 64%`
- observe mode: `observe t2 -> claude-sonnet-4.6 71%`
- fallback: `fallback -> claude-sonnet-4.6`

## Tasks

### Task 1: Surface router decisions through turn streams

**Files:**

- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `tests/unit/cli/tui/test_router_hud_plugin.py`

- [ ] Import `RouterDecisionEvent` in standalone runtime streaming.
- [ ] When standalone turn streaming sees `RouterDecisionEvent`, emit a
  `router_decision` domain event through the optional TUI event sink.
- [ ] When gateway streaming sees `session.event.router_decision`, emit the same
  normalized domain event shape.
- [ ] Add tests proving standalone and gateway payloads normalize to the same
  fields.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_router_hud_plugin.py tests/unit/cli/repl/test_turn_stream_boundaries.py -q
```

Expected: both stream paths surface router decisions without renderer output changes.

### Task 2: Add router HUD plugin

**Files:**

- Create: `src/opensquilla/cli/tui/plugins/__init__.py`
- Create: `src/opensquilla/cli/tui/plugins/router_hud.py`
- Modify: `tests/unit/cli/tui/test_contracts.py`
- Modify: `tests/unit/cli/tui/test_router_hud_plugin.py`

- [ ] Add `RouterHudPlugin` implementing `TuiPlugin`.
- [ ] Add label formatting with full, observe, fallback, forced, and no-baseline
  cases.
- [ ] Add style selection: normal for applied routing, dim for observe mode,
  warning for fallback.
- [ ] Add tests for t0/t1 natural tier indexes, observe mode, fallback, and
  malformed confidence.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_router_hud_plugin.py tests/test_engine/test_router_decision_event.py -q
```

Expected: router plugin snapshots match engine event semantics.

### Task 3: Render router HUD in terminal toolbar

**Files:**

- Modify: `src/opensquilla/cli/tui/terminal/app.py`
- Modify: `src/opensquilla/cli/tui/terminal/prompt.py`
- Modify: `src/opensquilla/cli/tui/adapters/turn_stream_defaults.py`
- Modify: `tests/unit/cli/repl/test_interactive_session_lifecycle.py`
- Modify: `tests/unit/cli/tui/test_router_hud_plugin.py`

- [ ] Add a toolbar context key for router HUD text and style.
- [ ] Wire the plugin manager snapshot into the terminal surface after each
  router decision event.
- [ ] Ensure toolbar invalidation is bounded to router/status updates, not every
  text delta.
- [ ] Add headless prompt-toolkit tests proving the toolbar changes after router
  decision and remains stable during text deltas.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/tui/test_router_hud_plugin.py tests/unit/cli/repl/test_interactive_session_lifecycle.py -q
```

Expected: terminal toolbar displays router decisions and does not refresh per token.

## Phase Gate

```bash
uv run pytest tests/unit/cli/tui/test_router_hud_plugin.py tests/test_engine/test_router_decision_event.py tests/test_gateway/test_chat_view_static.py -q
uv run pytest tests/unit/cli/repl/test_turn_stream_boundaries.py tests/unit/cli/repl/test_interactive_session_lifecycle.py -q
uv run mypy src/opensquilla/cli/chat/turn_stream.py src/opensquilla/cli/tui/plugins src/opensquilla/cli/tui/terminal --show-error-codes
uv run ruff check src/opensquilla/cli/chat/turn_stream.py src/opensquilla/cli/tui tests/unit/cli/tui
```

## Acceptance Criteria

- Router decisions appear in TUI through plugin state, not direct engine
  coupling.
- Observe mode is visibly different from applied routing.
- Fallback routing is visible.
- Terminal HUD updates are decoupled from token streaming.
- Existing WebUI router event tests still pass.
