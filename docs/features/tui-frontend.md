# TUI Frontend

OpenSquilla terminal chat uses renderer-independent TUI contracts built around
two separate planes:

- **Streaming plane:** batches token deltas before writing to the terminal, so
  long answers do not redraw the whole interface for every token.
- **Structured UI plane:** sends normalized TUI domain events to plugins. Plugin
  snapshots can be rendered by the current terminal backend and by future
  renderer.

The stable default terminal chat is Python-native and does not require Bun,
npm, or OpenTUI node modules. OpenTUI is a preview backend selected explicitly
with `OPENSQUILLA_TUI_BACKEND=opentui`.

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

The first plugin is `RouterHudPlugin`. It listens for
`router_decision` events and updates the bottom toolbar without changing router
selection behavior.

## Router HUD

When routing metadata is available, the OpenTUI footer can show:

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

The default backend is stable terminal chat.

The internal backend selector reads `OPENSQUILLA_TUI_BACKEND`. Unset or empty
values select stable terminal chat. Legacy values fail before chat launch with
a clear unsupported-backend error.

```sh
OPENSQUILLA_TUI_BACKEND=opentui opensquilla chat
```

The preview backend requires Bun and the local OpenTUI package dependencies:

```sh
npm install --prefix src/opensquilla/cli/tui/opentui/package
```

Do not add parallel terminal/frontend implementations without fresh product
direction and replay plus real-terminal evidence.

## Replay Benchmarks

The replay harness measures the OpenTUI rendering path without a live provider:

```sh
uv run python scripts/bench_tui_replay.py --renderer opentui --fixture long-stream --summary-json .artifacts/tui/opentui-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer opentui --fixture dense-history --summary-json .artifacts/tui/opentui-dense-history.json
```

Summary fields include `renderer`, `fixture`, `available`, `skip_reason`,
`event_count`, `text_chars`, `tool_count`, `router_decision_count`, `wall_ms`,
`flush_count`, `max_buffer_chars`, `coalescing_ratio`, `transcript_items`,
`visible_items`, `expanded_tools`, `projection_wall_ms`,
`rendered_text_matches`, `plugin_error_count`, and `errors`.

Use the OpenTUI results as preview backend evidence.
