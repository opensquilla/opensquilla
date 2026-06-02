# Real Terminal TUI Harness

The real-terminal harness launches the OpenTUI chat surface in a child process,
drives it through tmux when available, falls back to PTY when needed, and stores
evidence under `.artifacts/tui-real-terminal/runs`.

## Commands

Fast smoke:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
```

Full deterministic suite:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q
```

Manual lab:

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario long_streaming --backend opentui
```

OpenTUI backend path:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend opentui
```

The `opentui` backend runs deterministic fake-provider apps through the real
terminal harness. A guarded `live-opentui` backend exists for manual real CLI
smoke checks:

```bash
OPENSQUILLA_TUI_LIVE_REAL=1 uv run pytest \
  tests/integration/cli/tui_real_terminal/test_live_opentui_real_cli.py -q \
  --tui-backend live-opentui --tui-driver tmux

OPENSQUILLA_TUI_LIVE_REAL=1 uv run python scripts/tui_real_terminal_lab.py \
  --scenario live_opentui_architecture_prompt --backend live-opentui
```

The live smoke launches `opensquilla chat --standalone` with
`OPENSQUILLA_TUI_BACKEND=opentui`, drives it through tmux, sends a real prompt,
and captures text evidence. Use it deliberately because it may hit the
configured live provider.

## Evidence

Each run writes:

- `scenario.json`
- `terminal.log`
- `app.log`
- `transcript.txt`
- `frames/*.txt`
- `screenshots/`
- `result.json`
- `visual-verdict.json`

Capability misses are explicit skips. Deterministic assertion failures block.
Visual verdicts with `inspect` preserve evidence without blocking unrelated
backend changes.
