# Real Terminal TUI Harness

The real-terminal harness launches the OpenTUI chat surface in a child process,
drives it through tmux when available, falls back to PTY when needed, and stores
evidence under `.artifacts/tui-real-terminal/runs`.

## Platform requirements (Windows needs WSL2)

The harness drives a real terminal through tmux or a Unix pseudo-terminal
(Python's `pty` module). Both are Unix-only:

- `pty` ships in the Python standard library **only on Unix**; on native Windows
  `import pty` fails, so there is no PTY driver.
- `tmux` has no native Windows build.

**Native PowerShell is not supported for this harness, and Windows users must run
it under WSL2.** Inside a WSL2 distro the Linux `pty`/`tmux` stack works exactly
as on Linux:

```bash
# In an elevated PowerShell, once:
wsl --install            # installs WSL2 + a default Ubuntu distro

# Then inside the WSL2 shell, install tmux and run the harness:
sudo apt-get update && sudo apt-get install -y tmux
uv run pytest tests/integration/cli/tui_real_terminal -q
```

When neither tmux nor PTY is available (e.g. native-Windows CI),
`probe_terminal_capabilities()` reports `preferred_driver="none"` and every
scenario test is skipped with a `pytest.skip` reason that names the missing
capability — the run does not fail. The pure-logic driver, capability-probe, and
scenario-model unit tests run on every platform.

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
