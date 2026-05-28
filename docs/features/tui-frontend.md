# TUI Frontend

OpenSquilla terminal chat uses a Python TUI frontend built around two separate
planes:

- **Streaming plane:** batches token deltas before writing to the terminal, so
  long answers do not redraw the whole interface for every token.
- **Structured UI plane:** sends normalized TUI domain events to plugins. Plugin
  snapshots can be rendered by the current terminal backend and by future
  renderer backends.

The production backend remains the existing prompt-toolkit and Rich terminal
surface.

## Plugin Slots

Plugins consume renderer-independent events and publish small snapshots through
named slots. Current slots include:

| Slot | Purpose |
| --- | --- |
| `router_hud` | Active-turn model-routing decision. |
| `status` | Compact status or queue notices. |
| `tool_activity` | Tool cards and tool summary history. |
| `usage` | Token, cache, and cost summary. |
| `inspector` | Optional detail panel state for selected items. |

The first production plugin is `RouterHudPlugin`. It listens for
`router_decision` events and updates the bottom toolbar without changing router
selection behavior.

## Router HUD

When routing metadata is available, the terminal toolbar can show:

- selected tier and model;
- baseline model;
- route source;
- confidence;
- estimated savings;
- fallback state;
- thinking mode;
- prompt policy;
- whether routing was applied;
- rollout phase.

`routing_applied=true` with a full rollout is shown as an active route.
`routing_applied=false` or an observe rollout is shown as observe-only. Fallback
routes use warning styling.

## Backend Selection

The default backend is `terminal`.

For developer evaluation, the internal backend selector reads
`OPENSQUILLA_TUI_BACKEND`. Unknown values fail before chat launch with the valid
backend list. The current non-terminal backend is `textual`, which is optional
and remains an evaluation scaffold until it is installed and benchmarked.

```sh
OPENSQUILLA_TUI_BACKEND=terminal opensquilla chat
```

Do not add Textual as a required dependency or change the default backend based
only on selector availability. Promotion requires fresh long-stream and
dense-history replay evidence.

## Replay Benchmarks

The replay harness measures both rendering paths without a live provider:

```sh
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/terminal-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/terminal-dense-history.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture long-stream --summary-json .artifacts/tui/textual-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture dense-history --summary-json .artifacts/tui/textual-dense-history.json
```

Summary fields include `renderer`, `fixture`, `available`, `skip_reason`,
`event_count`, `text_chars`, `tool_count`, `router_decision_count`, `wall_ms`,
`flush_count`, `max_buffer_chars`, `coalescing_ratio`, `transcript_items`,
`visible_items`, `expanded_tools`, `projection_wall_ms`,
`rendered_text_matches`, `plugin_error_count`, and `errors`.

Use the terminal results as the production baseline. Textual results either run
against the same fixtures or report a clean unavailable skip when the optional
dependency is absent.
