# TUI Frontend

OpenSquilla terminal chat exposes one public UI policy over two renderers:

| Backend or target | Status | How to use | Requirements |
| --- | --- | --- | --- |
| `auto` | Default policy | `opensquilla chat` or `--ui auto` | Packaged host preferred; startup-only plain fallback |
| `tui` | Strict full-screen TUI | `opensquilla chat --ui tui` | Same-version platform companion |
| `plain` | Minimal rescue surface | `opensquilla chat --ui plain` | Python package only |
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
routes use warning styling. A real normal decision remains visible in the
compact footer (for example, `router c0 60%`); transport bootstrap placeholders
such as `gateway` are not presented as decisions. The decision state is cleared
at the start of every turn so a bypassed turn cannot inherit an earlier route.

## Responsive Transcript and Context

OpenTUI keeps one linear, scrollable transcript. Once `context.update` arrives,
a fixed one-line identity header presents the product, task, canonical Agent,
shared surface, and Gateway state. The same Agent label is used on retained and
new turn cards, including after a session context refresh.

At 132 terminal columns or wider, a 30–36-column context rail occupies the full
terminal height. Both the transcript and composer are inset by the rail width;
the rail does not introduce an independently scrolling message pane. At narrower
widths it collapses into a single priority-fitted footer strip. Layout and
clipping use terminal display cells, so CJK and emoji labels do not corrupt
borders or wrap the fixed header.

The additive `context.update` frame can carry Agent identity, task, surface,
Gateway state, model, permission, workspace, queue, and context information.
Older parents that do not send the frame retain the previous geometry and
router-only footer behavior.

An empty canonical history mounts a transcript-native welcome view with the
OpenSquilla wordmark, positioning, resolved runtime context, and first-action
shortcuts. The display typography selects a six-row `block`, two-row `tiny`, or
plain-text mode from the transcript's actual width and terminal height. History
replacement is authoritative: resumed content removes the welcome view, while
an empty `/new` or `/reset` snapshot remounts it.

Terminal viewport recovery reconciles the direct PTY size on resize,
`SIGWINCH`, and focus-in, then requests one native full repaint. Codex and VS
Code can also remount a same-size physical alternate-screen surface without
emitting any of those events, so only those embedded hosts receive a restrained
event-independent recovery watchdog. Each recovery first reasserts alternate
screen, focus, mouse, SGR-mouse, and bracketed-paste modes, then performs the
native full repaint; this prevents whole TUI frames from accumulating in normal
scrollback and restores the hardware caret inside the composer. Ordinary
terminals remain event-driven.
Maintainers can set `OPENSQUILLA_TUI_REPAINT_WATCHDOG_MS=0` to disable that
fallback or a positive millisecond value (clamped to 250ms) to exercise it in
the real-terminal harness.

## Complete Process Detail

`turn.begin` also opens a stable reasoning activity block immediately. It first
renders `Waiting for model output…`; real provider reasoning deltas append to
that same block and render incrementally. The live peek grows from three to at
most eight visual rows based on terminal height, emphasizing the newest line.
No synthetic reasoning is generated: a sub-second empty block disappears, a
longer empty block may settle as `Worked for Ns`, and a block containing provider
reasoning settles as `Thought for Ns`.

Thinking, reasoning, and tool renderers accumulate every delta delivered by the
host protocol. Tool detail includes full arguments, process updates, results,
and errors. Completed blocks are folded into compact previews by default and
show the number of hidden visual lines; this is a presentation choice, not data
discarding. Late deltas received after `block.end` are retained as part of the
same block.

When an ensemble actually executes, provider lifecycle events create one
in-place `Ensemble · n/m complete` block. `Ctrl+O` discloses public member model,
provider, status, elapsed time, tokens, cost, and error metadata. The completed
receipt and fallback reason survive history hydration. Candidate answer bodies
and private reasoning are never copied into this block. Configuration alone is
not treated as evidence that an Ensemble executed. The footer separately shows
the Gateway-owned `direct | router | ensemble` strategy. `/router` and
`/ensemble` update that canonical state through `models.routing.set`; during an
active Turn the footer labels it as the next-Turn strategy while the Turn keeps
rendering its captured Router decision or Ensemble lifecycle.

The composer remains interactive during streaming. Local UI commands execute
immediately. In Gateway mode, busy **Enter** requests native turn steering and
busy **Tab** explicitly queues a follow-up; a late/unavailable steer visibly
falls back to the bounded queue. Standalone turns keep their in-process
tool-boundary injection contract. History hydration and unresolved attachments
may still disable or block submission explicitly.

`Ctrl+O` expands or collapses all retained process detail without taking focus
from the composer. Expansion uses sanitized terminal text and the transcript's
current content width, including the wide-rail inset. This frontend guarantee
starts at the host-protocol boundary: upstream tool-result compression or
provider truncation remains governed by the separate
[`tool-compression.md`](tool-compression.md) contract.

## UI Selection

The public selector is `--ui auto|tui|plain`, and omitted `--ui` means `auto`.
`auto` may fall back only before alternate-screen startup. Explicit `tui` fails
clearly when the host is absent or incompatible. A host crash after startup
restores the terminal and exits; it does not switch renderers during a turn.

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
