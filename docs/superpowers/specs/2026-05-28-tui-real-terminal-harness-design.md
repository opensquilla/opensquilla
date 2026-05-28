# TUI Real Terminal Harness Design

## Goal

Build a real-terminal test environment for OpenSquilla's TUI surfaces. The
environment must launch an actual terminal-hosted TUI process, drive it through
interactive input, capture screen evidence, and support both automated pytest
regression tests and manual visual debugging.

The harness must validate both the current production terminal frontend and a
future live Textual frontend through the same scenario contract. The production
prompt-toolkit/Rich terminal path remains the first acceptance target. Textual is
added as a comparable backend target only after the live app exists.

## Approved Direction

Use a hybrid real-terminal harness:

- one shared real-terminal session driver;
- one shared scenario model for automated and manual runs;
- one evidence bundle format for deterministic checks, screenshots, logs, and
  visual review notes;
- production terminal and Textual targets behind the same backend interface.

The initial scope includes all four scenario families:

- launch and input loop;
- long streaming output;
- complex UI state;
- terminal changes.

## Current Repository Anchors

- `src/opensquilla/cli/tui/backend/contracts.py` defines the frontend-neutral
  runtime and output contracts.
- `src/opensquilla/cli/tui/backend/runtime.py` owns the submitted-line and turn
  loop without importing prompt-toolkit.
- `src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py` composes the
  current terminal chat runtime.
- `src/opensquilla/cli/tui/terminal/app.py` owns prompt-toolkit terminal region
  handling, output locking, and prompt redraw behavior.
- `src/opensquilla/cli/tui/terminal/stream.py` owns low-latency terminal token
  streaming and escape-sequence sanitization.
- `src/opensquilla/cli/tui/renderers/selection.py` selects terminal versus
  Textual renderer backends.
- `src/opensquilla/cli/tui/renderers/textual_backend.py` is currently a
  headless Textual evaluation renderer, not a live app.
- `scripts/bench_tui_replay.py` and `tests/unit/cli/tui/replay_fixtures.py`
  provide replay evidence but do not launch a real terminal.

## Architecture

The core primitive is `RealTerminalSession`. It owns terminal process lifecycle
and exposes a small driver API:

- start a command in a real terminal context;
- send text and special keys;
- paste multiline input;
- resize the terminal;
- wait for visible markers or process/log events;
- capture current screen text;
- capture screenshots when the host supports it;
- detect process exit and clean up owned resources.

Scenario code must depend on the `RealTerminalSession` interface, not on tmux
commands or PTY implementation details.

The harness has four layers:

- `RealTerminalSession`: terminal lifecycle, input, resize, capture, cleanup.
- `TuiTarget`: backend-specific command and environment construction.
- `EvidenceBundle`: transcripts, screen frames, screenshots, logs, scenario
  JSON, and visual verdict JSON.
- `VisualVerdict`: structured visual review over screenshots and scenario
  intent.

## Driver Strategy

Use tmux first and PTY fallback.

The tmux-backed driver is the primary implementation because it supports
human-visible sessions, pane capture, resize, and iterative visual debugging. It
is the best fit for the requested workflow: launch a real TUI, interact with it,
inspect what actually rendered, and feed screenshots into visual review.

The PTY-backed driver is a fallback for environments where tmux is unavailable
or where CI needs a smaller dependency surface. PTY mode can support text
assertions and process lifecycle checks, but it is not the primary source of
visual fidelity.

Each run must use generated session names, run IDs, and owned process metadata
so cleanup never touches unrelated user terminal sessions.

## Backend Targets

`TuiTarget` describes how to launch a concrete backend under the real-terminal
driver. It provides:

- backend id;
- command arguments;
- environment variables;
- initial terminal size;
- readiness markers;
- log paths;
- capability requirements.

Initial targets:

- `terminal`: the existing production prompt-toolkit/Rich chat frontend.
- `textual`: a future live Textual app target that uses the same scenario
  contract after it exists.

The Textual target must not get a separate bespoke test universe. Promotion
requires comparable evidence from the same scenarios used for the production
terminal target.

## Scenario Model

Represent scenarios with Python dataclasses and pytest fixtures in the first
version. Do not introduce a YAML or external scenario parser until the scenario
steps stabilize.

Each scenario is a recipe:

- Given: backend target, command, terminal size, fake provider fixture, session
  fixture, and timeout budget.
- When: send text, press keys, paste multiline input, resize, trigger tool
  events, trigger approval prompts, and capture checkpoints.
- Then: assert visible text, prompt readiness, process health, no traceback, no
  raw terminal escape leakage, transcript expectations, and visual verdicts.
- Artifacts: screen frames, transcript, logs, screenshots, scenario result JSON,
  and visual review notes.

Scenario families:

### Launch And Input Loop

Starts the TUI, waits for a prompt-ready state, sends one user message, receives
a deterministic fake-provider response, and verifies the prompt returns to an
input-ready state.

This is the first smoke scenario because it proves the harness can launch and
drive a real interactive frontend.

### Long Streaming Output

Uses a deterministic fake provider to emit long token streams. Checks include:

- streamed text reaches the screen and transcript;
- prompt line is not corrupted;
- wrapping stays readable;
- output is not swallowed or reordered;
- no untrusted escape sequence leaks into the terminal.

### Complex UI State

Exercises tool calls, approval prompts, router HUD, history projection, and
tool-card interactions. The scenario must checkpoint before, during, and after
state transitions so failures can be diagnosed from screenshots and logs.

### Terminal Changes

Exercises resize, narrow and wide terminal widths, mixed-width CJK and ASCII
content, multiline paste, Ctrl-C recovery, EOF exit, and final cleanup. These
cases are required because many terminal layout bugs only appear after state
transitions or width changes.

## Visual Verdict

Visual review is a second-stage check over evidence. It does not replace
deterministic assertions and does not drive the terminal directly.

The visual verdict input contains:

- screenshot or frame path;
- scenario id and checkpoint name;
- terminal size;
- backend id;
- expected visible regions;
- checklist of relevant failure modes.

The output is structured:

- status: `pass`, `fail`, or `inspect`;
- severity: `blocking`, `inspect-only`, or `acceptable-variation`;
- affected region;
- symptom;
- suspected cause;
- recommended next action.

Initial visual failure checklist:

- overlap between HUD, prompt, tool cards, and stream text;
- clipping at terminal edge, panel border, or prompt region;
- broken wrapping for long text, code fences, URLs, and CJK text;
- unreadable hierarchy or color contrast;
- stale loading, approval, or HUD state after the scenario has advanced;
- bad recovery after resize, Ctrl-C, approval, or EOF.

CI should block on deterministic failures and visual verdicts marked
`blocking`. Verdicts marked `inspect` preserve evidence and create follow-up
work without blocking unrelated backend changes.

## Project Shape

Proposed automated test layout:

```text
tests/integration/cli/tui_real_terminal/
  conftest.py
  driver.py
  targets.py
  scenarios.py
  assertions.py
  test_launch_input_loop.py
  test_long_streaming.py
  test_complex_ui_state.py
  test_terminal_changes.py
```

Proposed manual entrypoint:

```text
scripts/tui_real_terminal_lab.py
```

The lab command starts a real terminal session for a named scenario and backend,
then preserves screenshots and transcripts for visual debugging.

Proposed artifact layout:

```text
.artifacts/tui-real-terminal/runs/<timestamp>-<scenario>/
  scenario.json
  terminal.log
  app.log
  transcript.txt
  frames/
  screenshots/
  visual-verdict.json
```

## Commands

Fast smoke:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
```

Full deterministic real-terminal suite:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q
```

Manual visual lab:

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario long_streaming --backend terminal
```

Backend comparison:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
```

Exact CLI flags can change during implementation, but the split between fast
smoke, full deterministic suite, manual lab, and backend comparison should stay
stable.

## Capability And Error Handling

Each run starts with a capability probe:

- tmux availability;
- PTY fallback availability;
- screenshot capability;
- terminal resize support;
- backend availability;
- fake-provider fixture availability.

Missing capabilities must produce explicit skip reasons or downgraded modes. A
scenario must not silently claim coverage it did not run.

Waits must be event-driven. Prefer visible markers, prompt-ready state, process
output, app log events, or transcript changes with bounded polling. Avoid blind
sleeps as the primary synchronization mechanism.

Timeout and failure reports must include:

- current scenario step;
- expected marker or condition;
- elapsed time;
- last captured screen;
- recent terminal transcript;
- app log tail;
- command and environment summary;
- artifact directory path.

## CI Policy

Real-terminal tests use a separate pytest marker. Default CI can start with the
fast smoke where tmux or PTY support exists. The full deterministic suite should
be opt-in until the driver proves stable across environments. Visual verdict
checks should remain opt-in until false-positive behavior is understood.

Unit replay tests remain the fast default for renderer contracts and streaming
metrics. The real-terminal harness is an integration gate, not a replacement for
unit replay coverage.

## Phased Rollout

### Phase 1: Real Terminal Driver And Launch Smoke

- Implement `RealTerminalSession` with a tmux-backed driver.
- Add production terminal `TuiTarget`.
- Add deterministic fake-provider fixture.
- Add launch/input-loop pytest scenario.
- Save evidence bundle on pass and failure.

### Phase 2: Streaming And Terminal Changes

- Add long-streaming scenario.
- Add resize, narrow/wide, CJK mixed-width, multiline paste, Ctrl-C, and EOF
  scenarios.
- Preserve screen frames around each transition.

### Phase 3: Complex UI State

- Add tool-call, approval, router HUD, history projection, and tool-card
  scenarios.
- Capture checkpoints before, during, and after each state transition.

### Phase 4: Visual Verdict And Manual Lab

- Add the manual lab command.
- Add screenshot capture where supported.
- Add visual verdict JSON format and severity policy.
- Keep visual blocking gates opt-in at first.

### Phase 5: Textual Backend Comparison

- Add a live Textual `TuiTarget` after a live Textual app exists.
- Run the same ABCD scenario families against terminal and Textual targets.
- Use comparable evidence before any backend promotion decision.

## Acceptance Criteria

- The harness launches and drives an actual terminal-hosted TUI process.
- The same scenario model supports automated pytest and manual visual debugging.
- Launch/input loop, long streaming, complex UI state, and terminal changes are
  all represented as scenario families.
- Failures always preserve evidence that can diagnose the current step and
  visible terminal state.
- Production terminal remains the default acceptance target.
- Textual uses the same scenario contract for future comparison.
- CI policy distinguishes fast unit replay, real-terminal deterministic tests,
  and visual verdict gates.

## Non-Goals

- Do not test real providers or network latency in the first version.
- Do not require every terminal emulator in the first version.
- Do not add pixel-perfect screenshot comparisons as the default pass condition.
- Do not make Textual a production default as part of this harness.
- Do not let visual verdicts drive terminal state directly.

## Self Review

- Placeholder scan: no placeholder markers or open-ended sections remain.
- Consistency check: production terminal is first target, Textual is a future
  comparable target under the same scenario contract.
- Scope check: ABCD are all in scope, delivered through staged implementation
  rather than separate ad hoc scripts.
- Ambiguity check: deterministic gates and visual verdicts have separate roles
  and separate CI policies.
- Risk check: tmux is primary for visual fidelity, PTY is fallback for
  constrained environments.
