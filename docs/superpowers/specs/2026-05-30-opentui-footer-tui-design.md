# OpenTUI Footer TUI Design

## Goal

Replace the current live Textual TUI direction with an OpenTUI-based bottom
interaction layer while preserving terminal-native transcript output.

The approved user experience is not a full-screen transcript application. Model
output, tool calls, intermediate process rows, and final answers continue to
print into the real terminal so users can rely on normal shell or tmux
scrollback. OpenTUI owns only the stable bottom interaction layer: the composer
and a compact Router plugin anchored at the lower right.

## Approved Direction

Use an "A plus B" hybrid:

- keep the Claude Code classic-style append-only transcript;
- do not render an application-owned transcript viewport;
- do not draw a custom scrollbar;
- use OpenTUI for a stable bottom safe area;
- render a clean input composer in the lower left;
- render Router as a compact single-column plugin block in the lower right;
- keep tool output and model output visually distinct in the terminal stream.

This replaces the Textual live surface as the experimental rich frontend. The
existing prompt-toolkit/Rich terminal backend remains the fallback and evidence
baseline until the OpenTUI backend passes real-terminal gates.

## Current Repository Anchors

- `src/opensquilla/cli/tui/backend/contracts.py` defines `TuiSurface`,
  `TuiOutputHandle`, and renderer contracts that the new backend must satisfy.
- `src/opensquilla/cli/tui/backend/runtime.py` owns the frontend-neutral input
  and turn loop.
- `src/opensquilla/cli/tui/terminal/stream.py` is the reference append-only
  streaming path and already avoids Rich Live full redraw behavior.
- `src/opensquilla/cli/tui/terminal/app.py` owns the current prompt-toolkit
  composer, output lock, and toolbar state.
- `src/opensquilla/cli/tui/textual/` is the live Textual surface to replace or
  demote to an optional comparison backend.
- `src/opensquilla/cli/tui/plugins/router_hud.py` is the renderer-neutral router
  projection source for the Router plugin.
- `tests/integration/cli/tui_real_terminal/` provides the tmux/PTY acceptance
  harness that must cover the new backend.

## OpenTUI Dependency Position

As of 2026-05-30, `@opentui/core` and `@opentui/react` are published at `0.3.0`,
MIT licensed, from `github.com/anomalyco/opentui`. Treat OpenTUI as a frontend
runtime dependency behind an explicit backend flag until packaging and
terminal-behavior gates pass.

The first implementation phase must validate the exact OpenTUI primitive used
for the bottom layer. The required behavior is a reserved footer/safe-area that
does not force OpenSquilla to render an application-owned transcript viewport.
If OpenTUI cannot support that cleanly, stop and keep the terminal-native Python
path rather than rebuilding a full-screen transcript app.

## Visual Layout

### Transcript

The transcript is ordinary terminal output. It is not an OpenTUI widget tree.

Rows use semantic terminal rendering:

- user prompt: warm accent, compact;
- running thought/process: amber, spinner on the left while active;
- completed process: stable completion icon;
- tool call header: cyan and noticeable;
- tool details: subdued gray, folded by default;
- final answer: high-contrast readable foreground, not dim gray;
- usage/cost footer: low-emphasis metadata after the final answer.

Tool call spacing must be tight. A tool call should normally occupy one compact
header row, zero or more folded detail rows, and one completion row. Consecutive
tool calls should not accumulate blank-line gaps.

### Bottom Safe Area

OpenTUI owns a bottom safe area. The safe area reserves vertical space so the
composer and Router plugin do not cover transcript output.

The safe area contains:

- lower-left composer;
- lower-right Router plugin;
- optional active-state text near the composer when a turn is running.

The safe area may grow on narrow terminals, but the default desktop layout
should fit in roughly two input-line heights.

### Composer

The composer is clean and visually separate from Router.

Requirements:

- placeholder text is exactly `send a message`;
- no `you` or `你` label;
- transparent or near-transparent background;
- rounded rectangle border;
- CJK input and paste stay visible while typing;
- resizing does not overlap Router or transcript output.

### Router Plugin

Router appears as a compact rectangular plugin anchored at the lower right.

Default single-column rows:

- `model`: selected model, for example `gpt-5.5`;
- `route`: tier and confidence, for example `T3 · 91%`;
- `saving`: savings percent and estimated delta, for example `42% · -$0.021`;
- `ctx`: context capacity and usage, for example `128k · 37%`.

The plugin may expose more detail through a future expanded state, but the
default state must stay compact. Router must not sit inside the input box and
must not become a full-width footer bar.

## Architecture

Add an OpenTUI backend beside the terminal and Textual backends:

```text
src/opensquilla/cli/tui/opentui/
  __init__.py
  bridge.py
  messages.py
  runtime.py
  surface.py
  package/
    package.json
    src/
      main.ts
      components/
        Composer.tsx
        RouterPlugin.tsx
        FooterLayer.tsx
```

Python remains the chat/runtime owner. OpenTUI is a frontend host for the bottom
layer, not a second chat engine.

### Python Responsibilities

- select the OpenTUI backend explicitly;
- spawn and supervise the OpenTUI host process;
- keep `run_tui_runtime()` as the input/turn lifecycle owner;
- write transcript output through the terminal-native streaming renderer;
- send composer, status, and Router snapshots to OpenTUI;
- receive submitted user input, cancel, EOF, and resize messages from OpenTUI;
- shut the host down cleanly on `/exit`, EOF, or exceptions.

### OpenTUI Host Responsibilities

- reserve and redraw the bottom safe area;
- render the composer and compact Router plugin;
- handle keyboard input, paste, cursor, and CJK composition behavior;
- emit submitted lines and control commands over IPC;
- adapt layout on resize without covering transcript output;
- avoid owning model output, tool output, or chat semantics.

### IPC

Use newline-delimited JSON over stdio for the first backend. Keep messages small
and typed.

Python to OpenTUI:

- `init`: terminal/session metadata and initial layout settings;
- `composer.set`: placeholder, disabled state, current status;
- `router.update`: compact Router plugin state;
- `turn.status`: current stage such as thinking, tool_call, streaming, idle;
- `layout.resize`: terminal dimensions when known;
- `shutdown`: graceful exit request.

OpenTUI to Python:

- `input.submit`: submitted prompt text;
- `input.cancel`: cancel current turn;
- `input.eof`: end session;
- `resize`: observed terminal dimensions;
- `ready`: footer host has mounted and is safe to use;
- `error`: frontend-side error with a bounded message.

## Data Flow

1. CLI selects the OpenTUI backend.
2. Python launches the OpenTUI host and waits for `ready`.
3. `OpenTuiSurface.next_line()` waits for `input.submit` or EOF.
4. `run_tui_runtime()` dispatches the turn through the existing backend.
5. Streaming text, tool calls, and final answer print to terminal scrollback via
   the terminal-native output path.
6. Router and status domain events update renderer-neutral plugin projections.
7. The Python bridge sends compact snapshots to OpenTUI.
8. OpenTUI redraws only the bottom safe area.

## Error Handling

- If OpenTUI is missing or fails to start, backend selection fails with a clear
  diagnostic and suggests the terminal backend.
- If the OpenTUI host exits mid-session, Python restores terminal state and
  falls back to plain terminal prompt only if no turn is currently streaming.
- If IPC messages are malformed, the bridge logs the bad message, ignores it
  when safe, and fails closed for input/control messages.
- If footer reservation corrupts scrollback or overlaps output in the harness,
  the OpenTUI backend is not promoted.
- Terminal resize must never leave hidden cursor, alternate screen state, or
  stale footer fragments behind.

## Testing Strategy

### Deterministic Unit Gates

- message schema round trips for Python and TypeScript;
- Router projection maps to the compact plugin rows;
- composer events map to `TuiSurface.next_line()`;
- malformed IPC is bounded and logged;
- backend selection reports missing OpenTUI clearly.

### Replay Gates

Use existing replay fixtures to render semantic terminal events without a live
model:

- long model stream;
- dense tool-call sequence;
- architecture prompt replay;
- CJK prompt and paste;
- Router decision updates during an active turn.

### Real-Terminal Gates

Extend `tests/integration/cli/tui_real_terminal/` with an OpenTUI target.

Required scenarios:

- launch readiness in tmux;
- user types and sees CJK/ASCII input;
- submitted prompt appears in scrollback;
- long output remains scrollable through terminal/tmux scrollback;
- tool call blocks render without excessive spacing;
- final answer renders high contrast;
- Router plugin appears lower right, compact, single-column;
- Router plugin does not cover input or tool output;
- resize keeps the footer readable and restores terminal state.

### Manual Lab

Add a manual lab command matching the current Textual lab pattern. It should
start a real tmux session, launch the OpenTUI backend, feed the saved
architecture prompt scenario, and preserve captured scrollback plus screen
frames for visual inspection.

## Migration Plan Shape

The implementation plan should be staged:

1. OpenTUI spike proving footer reservation and IPC in a minimal host.
2. Python bridge and backend selection behind an explicit backend id.
3. Compact Router plugin and composer rendering.
4. Terminal stream style cleanup for tool blocks and final answer contrast.
5. Replay and real-terminal OpenTUI target.
6. Demote Textual live backend to optional comparison or remove it after parity.

Do not change router semantics, model selection, provider behavior, gateway
protocols, or engine runtime in this migration.

## Self Review

- Placeholder scan: no TBD/TODO markers remain.
- Internal consistency: the design consistently avoids an OpenTUI transcript
  viewport and keeps transcript output terminal-native.
- Scope check: this is one backend migration and visual redesign track; the
  implementation plan can be split into staged tasks.
- Ambiguity check: OpenTUI is approved only for the bottom interaction layer;
  the first implementation phase must prove footer reservation before broader
  migration.
- Risk check: the largest risk is terminal ownership between OpenTUI and raw
  transcript output, so promotion is gated on tmux real-terminal evidence.
