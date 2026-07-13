# TUI Frontend

OpenSquilla terminal chat exposes one public UI policy over two renderers:

| Backend or target | Status | How to use | Requirements |
| --- | --- | --- | --- |
| `auto` | Final rollout policy / RC opt-in | `opensquilla chat --ui auto` | Packaged host preferred; startup-only plain fallback |
| `tui` | Supported RC full-screen TUI | `opensquilla chat --ui tui` | Same-version platform companion |
| `plain` | RC default and minimal rescue surface | `opensquilla chat` or `--ui plain` | Python package only |
| `live-opentui` | Manual harness target | Real-terminal harness only | tmux, OpenTUI deps, and live provider config |

`live-opentui` is not an `OPENSQUILLA_TUI_BACKEND` value. It is a guarded test
target that launches the OpenTUI path through the real CLI.

The TUI contracts are renderer-independent and built around two separate planes:

- **Streaming plane:** batches token deltas before writing to the terminal, so
  long answers do not redraw the whole interface for every token.
- **Structured UI plane:** sends normalized TUI domain events to plugins. Plugin
  snapshots can be rendered by capable TUI backends and by future renderers.

The core wheel remains platform-neutral. Release installers add a same-version
`opensquilla-tui-host` companion containing a self-contained OpenTUI host; Bun,
npm, node modules, and source files are not runtime requirements.

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
HUD. In the current implementation, the OpenTUI footer is the primary terminal
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

## UI Selection

The public selector is `--ui auto|tui|plain`. `auto` may fall back only before
alternate-screen startup. Explicit `tui` fails clearly when the host is absent
or incompatible. A host crash after startup restores the terminal and exits;
it does not switch renderers during a turn.

The internal `OPENSQUILLA_TUI_BACKEND` selector remains a compatibility and
source-development override when `--ui` is omitted. New user instructions must
use `--ui`.

```sh
bun install --frozen-lockfile --cwd=src/opensquilla/cli/tui/opentui/package
OPENSQUILLA_TUI_DEV_SOURCE_HOST=1 uv run opensquilla chat --ui tui
```

The source backend is loaded only under an explicit developer override. Normal
release installs resolve the companion package instead.

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

Use the OpenTUI results as renderer regression evidence. Release readiness
also requires the packaged-host, real-terminal macOS gate; source-host results
alone are not release evidence.

For terminal-level launch and rendering evidence, use the
[real-terminal TUI harness](../tui-real-terminal-harness.md).

The product ownership and legacy-freeze rules are defined in
[`tui-product-contract.md`](tui-product-contract.md).
