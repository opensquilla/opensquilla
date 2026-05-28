# Real Terminal TUI Harness

The real-terminal harness launches the production prompt-toolkit/Rich terminal
surface in a child process, drives it through tmux when available, falls back to
PTY when needed, and stores evidence under `.artifacts/tui-real-terminal/runs`.

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
uv run python scripts/tui_real_terminal_lab.py --scenario long_streaming --backend terminal
```

Backend comparison path:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
```

The `textual` backend reports an explicit skip until a live Textual app target
exists. Production acceptance remains the `terminal` backend.

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
