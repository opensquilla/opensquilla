# TUI Frontend

OpenSquilla terminal chat has one stable default backend and one opt-in preview
backend:

| Backend or target | Status | How to use | Requirements |
| --- | --- | --- | --- |
| `native` | Stable default | `opensquilla chat` | Python package only |
| `opentui` | Preview opt-in | `OPENSQUILLA_TUI_BACKEND=opentui uv run opensquilla chat` | Source checkout, Bun, and local OpenTUI package dependencies |
| `live-opentui` | Manual harness target | Real-terminal harness only | tmux, OpenTUI deps, and live provider config |

`live-opentui` is not an `OPENSQUILLA_TUI_BACKEND` value. It is a guarded test
target that launches the OpenTUI preview path through the real CLI.

The TUI contracts are renderer-independent and built around two separate planes:

- **Streaming plane:** batches token deltas before writing to the terminal, so
  long answers do not redraw the whole interface for every token.
- **Structured UI plane:** sends normalized TUI domain events to plugins. Plugin
  snapshots can be rendered by capable TUI backends and by future renderers.

The stable default terminal chat is Python-native and does not require Bun,
npm, or OpenTUI node modules. OpenTUI is a source-checkout preview backend
selected explicitly with `OPENSQUILLA_TUI_BACKEND=opentui`.

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

When routing metadata is available, capable TUI backends can render a Router
HUD. In the current implementation, the OpenTUI footer is the primary preview
display for this HUD. The HUD is display-only: it consumes turn metadata and
does not change model selection.

The HUD can show:

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

The default backend is stable Python-native terminal chat.

The internal backend selector reads `OPENSQUILLA_TUI_BACKEND`. Unset or empty
values select stable terminal chat. Set the variable to `opentui` only in a
source checkout when evaluating the preview backend. Legacy values fail before
chat launch with a clear unsupported-backend error.

```sh
bun install --frozen-lockfile --cwd=src/opensquilla/cli/tui/opentui/package
OPENSQUILLA_TUI_BACKEND=opentui uv run opensquilla chat
```

The preview backend is loaded from the OpenTUI package next to the running
source tree; it is not required for normal terminal chat.

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

For terminal-level launch and rendering evidence, use the
[real-terminal TUI harness](../tui-real-terminal-harness.md).
