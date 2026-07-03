# Real Terminal TUI Harness

The real-terminal harness launches the OpenTUI chat surface in a child process,
drives it through tmux when available, falls back to PTY when needed, and stores
evidence under `.artifacts/tui-real-terminal/runs`.

## Platform requirements

The harness runs on Unix-like terminal environments. Linux and macOS can run it
directly. Windows users need WSL2 because the harness depends on Unix terminal
primitives. It prefers tmux when available and falls back to a Unix
pseudo-terminal (Python's `pty` module) when tmux is missing.

- Linux and macOS can run the deterministic suite with either tmux or the PTY
  fallback.
- Native Windows shells such as PowerShell and `cmd.exe` are not supported:
  Python's `pty` module is Unix-only, and tmux has no native Windows build.
- WSL2 is mentioned only as the Windows compatibility path; inside WSL2 this is
  just the Linux path.

Install tmux when you want the tmux driver:

```bash
# Debian/Ubuntu Linux, including WSL2:
sudo apt-get update && sudo apt-get install -y tmux

# macOS:
brew install tmux
```

Windows-only setup:

```bash
# In an elevated PowerShell, once:
wsl --install            # installs WSL2 + a default Ubuntu distro

# Then inside the WSL2 shell:
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
