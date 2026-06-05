# Live Textual TUI Design

## Goal

Build a real, interactively launchable Textual TUI for OpenSquilla. The first
acceptance target is the existing real-terminal harness: `--tui-backend textual`
must launch a live Textual app, drive input through a real terminal session, and
pass the same deterministic scenario families as the production terminal target
without a Textual-specific skip for missing live-app support.

After the harness target is live, connect the same Textual surface to the real
chat/gateway runtime so Textual can be launched as an actual OpenSquilla TUI,
not only as a deterministic fixture app.

## Approved Direction

Use a shared runtime plus a Textual surface adapter.

The Textual app must not grow a second chat engine. It should implement the
existing `TuiSurface` and `TuiOutputHandle` contracts, then reuse
`run_tui_runtime()` for input classification, queued turns, exit handling,
cancel behavior, and dispatch lifecycle.

This keeps terminal and Textual behavior comparable:

- terminal uses `open_terminal_surface()`;
- Textual uses `open_textual_surface()`;
- both compose with `run_tui_runtime()`;
- both expose an output handle through the runtime scope;
- both are tested through the real-terminal scenario contract.

## Current Repository Anchors

- `src/opensquilla/cli/tui/backend/contracts.py` defines `TuiSurface`,
  `TuiOutputHandle`, `TuiRuntimeConfig`, and `TuiRuntimeHooks`.
- `src/opensquilla/cli/tui/backend/runtime.py` owns the input/turn loop and is
  already frontend-neutral.
- `src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py` composes the
  terminal surface with the shared runtime and chat dispatch.
- `src/opensquilla/cli/tui/terminal/surface.py` is the reference adapter shape
  for a concrete frontend surface.
- `src/opensquilla/cli/tui/renderers/textual_backend.py` is a headless replay
  renderer. It remains useful for replay benchmarks but is not the live app.
- `tests/integration/cli/tui_real_terminal/targets.py` currently declares a
  Textual target id but marks it unavailable.
- `tests/integration/cli/tui_real_terminal/scenarios.py` already defines the
  acceptance scenario families that Textual must run.

## Architecture

Add a new Textual live surface package:

```text
src/opensquilla/cli/tui/textual/
  __init__.py
  app.py
  surface.py
  runtime.py
  stream.py
```

`app.py` owns the Textual `App` subclass and widgets. `surface.py` adapts the
app to `TuiSurface`. `runtime.py` composes the Textual surface with
`run_tui_runtime()`. `stream.py` owns Textual-native output helpers, keeping the
headless replay renderer separate from live UI code.

The live app has four visible regions:

- a header/status area with model/session/router state;
- a scrollable transcript/output area;
- an input row for submitted user text;
- a footer/status line for cancel, exit, and transient notices.

The first implementation can keep the layout intentionally simple. Correct live
interaction, streaming visibility, prompt readiness, and harness parity are more
important than visual polish. Visual polish comes after the harness can drive the
live app.

## Components

### TextualChatApp

`TextualChatApp` subclasses Textual's `App`.

Responsibilities:

- compose widgets for output, input, and status;
- emit a readiness marker when mounted so the real-terminal harness can wait for
  a stable launch point;
- convert submitted input events into queued lines for `TextualSurface`;
- expose cancel and shutdown actions to the surface callbacks;
- update visible output and status widgets on the Textual message loop.

The app should treat Textual as the UI loop owner. Long-running chat turns stay
outside widget event handlers and run through `run_tui_runtime()` tasks.

### TextualSurface

`TextualSurface` implements `TuiSurface`.

Responsibilities:

- `next_line()` waits for the next submitted input or EOF;
- `write_through()` appends rendered output to the Textual transcript;
- `emit_eof()` terminates the input stream;
- `set_cancel_callback()` and `set_shutdown_callback()` register runtime-owned
  callbacks;
- `redraw_callback` invalidates or refreshes the app.

This is the boundary that keeps Textual from owning chat semantics.

### TextualOutputHandle

`TextualOutputHandle` implements `TuiOutputHandle`.

Responsibilities:

- expose an approval surface compatible with existing dispatch code;
- write one-shot payloads into the transcript;
- provide a `stream_output()` context manager for streaming text;
- support `set_toolbar()` and `invalidate()` so router HUD and fake harness state
  can surface in the app.

The initial stream path can append coalesced text chunks into the transcript. It
does not need to recreate every Rich formatting detail from the terminal backend
in the first pass.

### Textual Runtime Adapter

Add `run_textual_chat_runtime()` beside the terminal adapter shape.

Responsibilities:

- construct a chat runtime context with the default plugin manager;
- use `open_textual_surface()` as the surface factory;
- reuse `classify_chat_input()`, queued-input hooks, cancel hooks, and output
  exposure behavior;
- provide Textual-friendly notice rendering instead of printing notices to the
  Rich console.

The adapter should share as much logic as practical with
`run_terminal_chat_runtime()` without forcing prompt-toolkit details into the
Textual layer.

## Harness Target

Replace the current unavailable Textual target with a real command.

Add a deterministic harness launcher, likely:

```text
tests/integration/cli/tui_real_terminal/fake_textual_app.py
```

This launcher mirrors `fake_terminal_app.py` but calls the Textual runtime
adapter. It should use the same scenario environment variables and fake dispatch
behavior so terminal and Textual scenario output remains comparable.

`build_tui_target("textual", context)` must return:

- `available=True`;
- a real Python command that launches the live Textual app;
- the same readiness marker contract as terminal;
- a Textual app log path;
- capability requirements that describe real terminal plus live Textual support,
  not a missing-app skip.

`test_textual_target_is_explicitly_unavailable` must be replaced with tests that
prove the Textual target builds a real command and carries no live-app skip.

## Production Target

After the deterministic target passes, connect the same Textual runtime adapter
to the real chat/gateway path.

The production integration should be explicit behind a backend selection path.
The existing terminal frontend remains the conservative default until Textual has
matching real-terminal evidence and no known blocking visual defects.

The production path must not depend on the harness fake app. The fake app depends
on production Textual surface/runtime modules, not the other way around.

## Data Flow

### Deterministic Harness Flow

1. Pytest selects `--tui-backend textual`.
2. `build_tui_target()` returns the Textual fake-app command.
3. `RealTerminalSession` launches the command in tmux or PTY.
4. `TextualChatApp` mounts and emits `OPEN_SQUILLA_TUI_READY`.
5. Scenario steps send text, paste, resize, and press keys.
6. `TextualSurface.next_line()` returns submitted input.
7. `run_tui_runtime()` dispatches to the fake scenario response.
8. The fake response writes through `TextualOutputHandle`.
9. Scenario assertions inspect captured terminal frames and evidence.

### Production Flow

1. The CLI selects the Textual live backend explicitly.
2. `run_textual_chat_runtime()` opens `TextualSurface`.
3. Submitted Textual input flows through `run_tui_runtime()`.
4. Chat/gateway dispatch writes through the exposed Textual output handle.
5. Textual widgets show streaming output, tool/status events, and prompt
   readiness.

## Error Handling

- Missing Textual dependency should fail fast with a clear backend-unavailable
  error in production selection paths. It should not be represented as a skipped
  live-app target when Textual is installed in the dev environment.
- Harness target construction should not silently return `command=[]`.
- Textual app startup failures should surface in the harness app log and fail the
  scenario instead of turning into capability skips.
- Exceptions in dispatch should write a visible error status and preserve logs.
- EOF and `/exit` must shut down cleanly so terminal sessions do not linger.

## Testing Strategy

Use test-driven implementation in two batches.

### Batch 1: Live Textual Harness Target

Acceptance:

- `uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q`
  proves Textual builds a real command and no missing-live-app skip remains.
- `uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual`
  launches a live Textual app and passes the deterministic scenario suite.
- `uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend textual`
  starts a manually inspectable Textual session.

### Batch 2: Production Textual Runtime

Acceptance:

- targeted unit tests prove `run_textual_chat_runtime()` exposes a
  `TuiOutputHandle` and routes submitted input through `run_tui_runtime()`;
- backend selection or CLI launch tests prove Textual can be selected explicitly;
- real-terminal terminal backend tests still pass;
- real-terminal Textual backend tests still pass.

### Regression Matrix

Run at least:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
uv run pytest tests/unit/cli/tui -q
uv run ruff check src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
uv run mypy src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
```

If Textual-specific production wiring touches CLI chat/gateway launch code, add
the adjacent `tests/test_cli` and `tests/unit/cli/repl` targets.

## Non-Goals

- Do not promote Textual to the default frontend in the first implementation.
- Do not rewrite the terminal prompt-toolkit/Rich surface.
- Do not merge the headless replay renderer and live Textual app into one class.
- Do not create a second chat runtime with separate queue, slash, cancel, or exit
  semantics.
- Do not keep a Textual live-app skip after the target has a real command.

## Completion Criteria

The work is complete when:

- Textual has a real `App` subclass and launchable surface;
- real-terminal Textual scenarios pass without the missing-live-app skip;
- the manual lab can launch Textual for visual inspection;
- production Textual launch is explicit and uses the shared runtime;
- terminal backend behavior remains green;
- docs and tests no longer describe Textual as a missing live-app target.
