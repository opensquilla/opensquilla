# TUI Frontend Architecture Design

## Goal

Build a high-performance, low-latency, extensible command-line frontend for
OpenSquilla that can show model-routing decisions, tool activity, history, and
future TUI features through stable plugin boundaries.

## Approved Direction

The frontend should not start as a from-scratch terminal rendering framework and
should not immediately split into a TypeScript frontend plus Python backend. The
current Python TUI boundary is already valuable: `cli.chat` owns frontend-neutral
turn streaming, `cli.tui.backend` owns runtime contracts, and
`cli.tui.terminal` owns prompt-toolkit/Rich terminal behavior.

The chosen design is a dual-plane Python TUI architecture:

- **Streaming plane:** a low-level fast path for long token streams. It batches
  text deltas, flushes on a short time budget or content boundary, and avoids
  full UI tree refreshes per token.
- **Structured UI plane:** a plugin-driven UI projection for router decisions,
  tool cards, usage, status, and history. It can be rendered first by the
  existing prompt-toolkit/Rich terminal layer and then by a richer Textual
  backend if benchmarks justify it.

## Current Repository Anchors

- `src/opensquilla/cli/tui/backend/contracts.py` defines renderer and surface
  protocols that new backends should implement.
- `src/opensquilla/cli/tui/backend/runtime.py` owns the submitted-line and turn
  loop without importing prompt-toolkit.
- `src/opensquilla/cli/chat/turn_stream.py` bridges gateway/runtime events to a
  renderer and is the correct place to introduce renderer-neutral event taps.
- `src/opensquilla/cli/tui/terminal/app.py` owns the prompt-toolkit application,
  toolbar state, output lock, and terminal region handling.
- `src/opensquilla/cli/tui/terminal/stream.py` already documents why raw token
  streaming must avoid Rich Live style full redraw loops.
- `src/opensquilla/engine/types.py` defines `RouterDecisionEvent`, including the
  fields needed by a router HUD plugin.
- `src/opensquilla/engine/runtime.py` emits `RouterDecisionEvent` once per turn
  before agent bootstrap.
- `src/opensquilla/gateway/channel_dispatch.py` already exposes router decisions
  to WebUI as `session.event.router_decision`.

## Performance Design

Long token streams and dense histories have different bottlenecks.

For token streams, the bottleneck is terminal I/O and redraw policy. The TUI must
not convert every `TextDeltaEvent` into a full layout pass. It should accumulate
deltas in memory and flush at most every 20-50 ms, while still flushing promptly
on newline, code-fence, or finalization boundaries. The current terminal renderer
keeps a raw streaming path; the next layer should make that policy explicit and
measurable.

For hundreds of messages and tool cards, the bottleneck is live widget count and
rendered text volume. The transcript model must be separate from the visible UI
projection. Only the visible viewport plus a small overscan region should be
rendered as rich widgets. Tool outputs default to summary cards and expand on
request, with explicit caps for line count and rendered bytes.

## Plugin Design

Plugins consume normalized TUI domain events and update bounded projections. A
plugin should not own terminal I/O, prompt-toolkit widgets, engine state, or
provider calls. Renderers consume plugin projections through named slots.

Initial plugin slots:

- `status`: compact one-line status and queue notices.
- `router_hud`: model-routing decision for the active turn.
- `tool_activity`: active tool cards and tool summary history.
- `usage`: token, cache, and cost summary.
- `inspector`: optional detail panel for selected message, tool, or router
  decision.

The first production plugin is `RouterHudPlugin`. It consumes
`RouterDecisionEvent` and displays tier, model, baseline model, source,
confidence, savings percentage, fallback state, thinking mode, prompt policy,
`routing_applied`, and `rollout_phase`.

## Renderer Strategy

Phase 1 keeps the existing prompt-toolkit/Rich backend as the production
renderer. This preserves current CLI behavior and lets the event/plugin
contracts mature under focused tests.

Phase 2 evaluates Textual behind the same backend contracts. Textual should be
used for structured UI layout only after replay benchmarks show acceptable input
latency, streaming throughput, and dense-history behavior. The streaming plane
remains available as a fast path even when Textual is used for the rest of the
interface.

TypeScript, Go, or Rust TUI frontends remain non-goals for this project slice.
They can be reconsidered if OpenSquilla intentionally ships a standalone TUI
binary with a stable IPC protocol. That is a product packaging decision, not a
necessary performance fix for the current Python CLI.

## Testing Strategy

The implementation should avoid running broad test suites after every small
edit. Each child plan defines focused tests for its logical block. A phase gate
runs after the full block is implemented, and the final integration plan runs
the broad CLI/TUI gates.

Required validation themes:

- Import boundaries: backend contracts must not import prompt-toolkit or Rich
  terminal adapters.
- Event correctness: router decisions, tool lifecycle, usage, warning, error,
  and done events must reach the plugin/event layer in stable shapes.
- Streaming latency: long token streams must be batched and must not trigger a
  full structured UI render per token.
- Dense history: hundreds of messages/tool cards must project to a bounded
  visible item set.
- Compatibility: existing prompt-toolkit CLI behavior, cancellation, approval,
  EOF, queueing, and slash handling must remain intact.

## Self Review

- Placeholder scan: no placeholder markers or open-ended implementation slots.
- Scope check: this design is one architecture track split into separate child
  implementation plans.
- Ambiguity check: Textual is a measured backend candidate, not a mandatory
  dependency in the first production phase.
- Risk check: engine routing semantics stay unchanged; this work exposes and
  renders events rather than changing model-selection behavior.
