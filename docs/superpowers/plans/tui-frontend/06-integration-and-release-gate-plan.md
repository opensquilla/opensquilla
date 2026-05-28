# TUI Integration And Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the TUI frontend architecture slices, document the new plugin/rendering model, and run the final verification gate.

**Architecture:** The leader wires completed child-plan outputs into the default CLI path with conservative defaults. The terminal backend remains default, plugin runtime is enabled for structured events, and renderer evaluation remains explicit.

**Tech Stack:** Python 3.12, prompt-toolkit, Rich, pytest, mypy, ruff, project docs.

---

Before implementation, read the master plan's tooling and agent orchestration
requirements in `../2026-05-28-tui-frontend-master-plan.md`.

## Ownership

This plan is leader-owned. It touches shared files only after the relevant child
plans have landed and passed their phase gates.

## Files

- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Modify: `src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py`
- Modify: `src/opensquilla/cli/chat/turn_stream.py`
- Modify: `docs/cli.md`
- Modify: `docs/features/squilla-router.md`
- Modify: `docs/diagnostics-and-replay.md`
- Create: `docs/features/tui-frontend.md`
- Modify: `tests/unit/cli/tui/test_contracts.py`
- Modify: `tests/unit/cli/repl/test_runtime_bridge.py`
- Modify: `tests/test_cli/test_chat_cmd.py`

## Integration Defaults

- Default backend remains terminal.
- Plugin runtime is enabled only inside TUI launch composition.
- Router HUD plugin is registered by default for TUI surfaces.
- Benchmark scripts remain developer tools and do not run in normal CLI launch.
- Textual backend remains explicit unless the renderer evaluation result
  recommends promotion and the user approves the dependency.

## Tasks

### Task 1: Wire plugin manager into TUI launch

**Files:**

- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Modify: `src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py`
- Modify: `src/opensquilla/cli/tui/adapters/turn_stream_defaults.py`
- Modify: `tests/unit/cli/repl/test_runtime_bridge.py`

- [ ] Instantiate `TuiPluginManager` during terminal TUI launch.
- [ ] Register `RouterHudPlugin`.
- [ ] Pass the manager dispatch method as `tui_event_sink` to turn-stream
  dependencies.
- [ ] Keep non-TUI chat command imports lazy.
- [ ] Add tests proving launch wiring installs the plugin sink only in TUI paths.
- [ ] Run:

```bash
uv run pytest tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/tui/test_contracts.py -q
```

Expected: launch wiring works and import-laziness contracts pass.

### Task 2: Add explicit backend selection

**Files:**

- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Modify: `src/opensquilla/cli/tui/renderers/selection.py`
- Modify: `tests/test_cli/test_chat_cmd.py`
- Modify: `tests/unit/cli/tui/test_renderer_backend_contract.py`

- [ ] Add an internal backend selector that accepts `terminal` and any
  available experimental backend.
- [ ] Keep public CLI defaults unchanged.
- [ ] If an environment variable is used for evaluation, name it
  `OPENSQUILLA_TUI_BACKEND` and reject unknown values with a clear message.
- [ ] Add tests that unknown backend selection fails before runtime launch.
- [ ] Run:

```bash
uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/tui/test_renderer_backend_contract.py -q
```

Expected: terminal default remains unchanged and invalid backend selection is
clear.

### Task 3: Update user and developer docs

**Files:**

- Create: `docs/features/tui-frontend.md`
- Modify: `docs/cli.md`
- Modify: `docs/features/squilla-router.md`
- Modify: `docs/diagnostics-and-replay.md`

- [ ] Document the streaming plane, structured UI plane, and plugin slots.
- [ ] Document Router HUD fields and the difference between full and observe
  routing.
- [ ] Document replay benchmark commands and JSON summary fields.
- [ ] Document backend selection only if an explicit selector exists.
- [ ] Run:

```bash
uv run ruff check docs || true
```

Expected: docs are written; ruff may not apply to Markdown and should not block.

### Task 4: Run final verification

**Files:**

- Modify: no source files unless fixing integration failures

- [ ] Run focused TUI/CLI tests:

```bash
uv run pytest tests/unit/cli/tui tests/unit/cli/repl tests/test_cli/test_chat_cmd.py -q
```

- [ ] Run router and gateway regression tests:

```bash
uv run pytest tests/test_engine/test_router_decision_event.py tests/test_gateway/test_chat_view_static.py -q
```

- [ ] Run static checks:

```bash
uv run ruff check src tests
uv run mypy src/opensquilla/cli src/opensquilla/engine --show-error-codes
python -m compileall src/opensquilla
git diff --check
```

- [ ] Run replay benchmarks:

```bash
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/final-terminal-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/final-terminal-dense-history.json
```

Expected: all commands pass, or any external blocker is documented with command
output and scope.

## Phase Gate

This plan's phase gate is the final verification task above.

## Acceptance Criteria

- TUI plugin runtime is wired into the production terminal path.
- Router HUD is visible without changing router decisions.
- Long-stream and dense-history benchmarks run locally.
- Default CLI behavior remains compatible.
- Documentation explains the new architecture and developer workflow.
