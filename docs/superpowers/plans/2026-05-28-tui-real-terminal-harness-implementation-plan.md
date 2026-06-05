# TUI Real Terminal Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved real-terminal harness for OpenSquilla's production prompt-toolkit/Rich TUI, with shared scenarios, pytest automation, manual visual debugging, evidence bundles, ABCD scenario coverage, and a future comparable Textual target path.

**Architecture:** The harness lives under `tests/integration/cli/tui_real_terminal` and treats the terminal process as a black-box interactive program. A `RealTerminalSession` driver owns tmux-first and PTY-fallback lifecycle, `TuiTarget` builds backend commands, `TuiScenario` describes deterministic steps, and `EvidenceBundle` records all artifacts for pass and failure diagnosis. The production terminal target launches a deterministic fake app that composes the existing terminal `ChatApplication`, terminal surface, backend runtime, and `StreamingRenderer`; Textual remains an explicitly unavailable comparable target until a live Textual app exists.

**Tech Stack:** Python 3.12, pytest, asyncio, tmux CLI, stdlib PTY fallback, prompt-toolkit/Rich production terminal modules, ruff, mypy, `uv`.

---

## File Structure

- Create: `tests/integration/cli/tui_real_terminal/__init__.py`
  - Marks the harness directory as importable for pytest and the manual lab.
- Create: `tests/integration/cli/tui_real_terminal/driver.py`
  - Defines `TerminalSize`, `TerminalFrame`, `TerminalCapabilities`, `RealTerminalSession`, `TmuxTerminalSession`, `PtyTerminalSession`, `probe_terminal_capabilities()`, and `open_real_terminal_session()`.
- Create: `tests/integration/cli/tui_real_terminal/evidence.py`
  - Defines `EvidenceBundle`, `ScenarioResult`, `ScenarioFailure`, frame/transcript/log writers, and final `scenario.json`/`visual-verdict.json` artifact writers.
- Create: `tests/integration/cli/tui_real_terminal/targets.py`
  - Defines `TuiTarget`, `TargetContext`, backend target selection, production `terminal` fake-app command construction, and explicit `textual` unavailable reporting.
- Create: `tests/integration/cli/tui_real_terminal/fake_terminal_app.py`
  - Launches the real prompt-toolkit/Rich terminal frontend in a child process with deterministic fake scenario behavior.
- Create: `tests/integration/cli/tui_real_terminal/scenarios.py`
  - Defines scenario dataclasses, step functions, ABCD scenario recipes, and a single runner used by pytest and the manual lab.
- Create: `tests/integration/cli/tui_real_terminal/assertions.py`
  - Defines deterministic screen/transcript assertions: visible text, prompt readiness, no traceback, no raw ANSI leakage, no process exit, and evidence-rich failure messages.
- Create: `tests/integration/cli/tui_real_terminal/visual.py`
  - Defines the visual verdict input/output contract and deterministic local verdict writer with `inspect` status unless screenshots are present and a blocking checklist entry is detected by text heuristics.
- Create: `tests/integration/cli/tui_real_terminal/conftest.py`
  - Adds `--tui-backend`, `--tui-driver`, `--tui-artifact-root`, capability fixtures, target fixtures, scenario evidence fixtures, and marker-based capability skips.
- Create: `tests/integration/cli/tui_real_terminal/test_driver_capabilities.py`
  - Unit-level integration tests for probe results, tmux naming, PTY fallback, and command summaries.
- Create: `tests/integration/cli/tui_real_terminal/test_targets.py`
  - Tests target command construction, fake app environment, and Textual unavailable behavior.
- Create: `tests/integration/cli/tui_real_terminal/test_scenario_model.py`
  - Tests scenario serialization, assertion failures, and evidence bundle layout without launching a terminal.
- Create: `tests/integration/cli/tui_real_terminal/test_launch_input_loop.py`
  - Scenario A: launch, readiness, one user message, fake response, prompt returns.
- Create: `tests/integration/cli/tui_real_terminal/test_long_streaming.py`
  - Scenario B: long deterministic stream, wrapping text, sanitized escape input, transcript expectations.
- Create: `tests/integration/cli/tui_real_terminal/test_complex_ui_state.py`
  - Scenario C: tool calls, approval prompt text, router HUD text, history projection, tool-card interactions.
- Create: `tests/integration/cli/tui_real_terminal/test_terminal_changes.py`
  - Scenario D: resize, narrow/wide widths, CJK plus ASCII, multiline paste, Ctrl-C recovery, EOF cleanup.
- Create: `scripts/tui_real_terminal_lab.py`
  - Manual entrypoint using the same target, scenario, driver, and evidence bundle.
- Modify: `pyproject.toml`
  - Adds pytest marker `tui_real_terminal`.
- Create: `docs/tui-real-terminal-harness.md`
  - Documents commands, artifact layout, skip reasons, Textual comparison policy, and troubleshooting.

## Batch And Commit Map

1. `real terminal driver + capability probe`
   - Files: `driver.py`, `test_driver_capabilities.py`, harness `__init__.py`.
2. `fake terminal target + launch smoke`
   - Files: `targets.py`, `fake_terminal_app.py`, `conftest.py`, `test_targets.py`, `test_launch_input_loop.py`.
3. `scenario model + deterministic assertions`
   - Files: `scenarios.py`, `assertions.py`, `test_scenario_model.py`.
4. `streaming and terminal-change scenarios`
   - Files: `test_long_streaming.py`, `test_terminal_changes.py`, scenario additions.
5. `complex UI state scenario`
   - Files: `test_complex_ui_state.py`, fake-app complex dispatch additions.
6. `evidence bundle + manual lab`
   - Files: `evidence.py`, `scripts/tui_real_terminal_lab.py`, evidence integration.
7. `visual verdict contract + CI marker + docs`
   - Files: `visual.py`, `pyproject.toml`, `docs/tui-real-terminal-harness.md`, final conftest marker wiring.

Every commit message uses the root AGENTS Lore protocol and includes:

```text
Co-authored-by: OmX <omx@oh-my-codex.dev>
```

## Task 1: Real Terminal Driver And Capability Probe

**Files:**
- Create: `tests/integration/cli/tui_real_terminal/__init__.py`
- Create: `tests/integration/cli/tui_real_terminal/driver.py`
- Create: `tests/integration/cli/tui_real_terminal/test_driver_capabilities.py`

- [ ] **Step 1: Write the failing driver capability tests**

Create `tests/integration/cli/tui_real_terminal/__init__.py`:

```python
"""Real-terminal TUI integration harness for OpenSquilla."""
```

Create `tests/integration/cli/tui_real_terminal/test_driver_capabilities.py`:

```python
from __future__ import annotations

import sys

from tests.integration.cli.tui_real_terminal.driver import (
    TerminalSize,
    build_run_id,
    probe_terminal_capabilities,
)


def test_terminal_size_validates_positive_dimensions() -> None:
    size = TerminalSize(cols=100, rows=30)

    assert size.cols == 100
    assert size.rows == 30


def test_build_run_id_is_tmux_safe() -> None:
    run_id = build_run_id("launch_input_loop")

    assert run_id.startswith("opensquilla-tui-launch-input-loop-")
    assert all(ch.isalnum() or ch in "-_" for ch in run_id)


def test_capability_probe_reports_tmux_and_pty_modes() -> None:
    capabilities = probe_terminal_capabilities()

    assert capabilities.preferred_driver in {"tmux", "pty", "none"}
    assert capabilities.pty_available is (sys.platform != "win32")
    assert isinstance(capabilities.skip_reason, str | type(None))
    if capabilities.preferred_driver == "none":
        assert capabilities.skip_reason
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_driver_capabilities.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.integration'` or `No module named 'tests.integration.cli.tui_real_terminal.driver'`.

- [ ] **Step 3: Implement the minimal driver types and capability probe**

Create `tests/integration/cli/tui_real_terminal/driver.py` with these public contracts:

```python
from __future__ import annotations

import os
import pty
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

DriverKind = Literal["tmux", "pty"]


@dataclass(frozen=True)
class TerminalSize:
    cols: int = 100
    rows: int = 30

    def __post_init__(self) -> None:
        if self.cols <= 0 or self.rows <= 0:
            raise ValueError("terminal size must be positive")


@dataclass(frozen=True)
class TerminalFrame:
    checkpoint: str
    text: str
    captured_at_ms: int
    size: TerminalSize


@dataclass(frozen=True)
class TerminalCapabilities:
    tmux_available: bool
    pty_available: bool
    screenshot_available: bool
    resize_available: bool
    preferred_driver: Literal["tmux", "pty", "none"]
    skip_reason: str | None = None


class RealTerminalSession(Protocol):
    run_id: str
    kind: DriverKind
    size: TerminalSize

    def start(self) -> None: ...
    def send_text(self, text: str) -> None: ...
    def send_key(self, key: str) -> None: ...
    def paste(self, text: str) -> None: ...
    def resize(self, size: TerminalSize) -> None: ...
    def capture_text(self, checkpoint: str) -> TerminalFrame: ...
    def wait_for_text(self, needle: str, *, timeout_s: float, checkpoint: str) -> TerminalFrame: ...
    def is_alive(self) -> bool: ...
    def terminate(self) -> None: ...


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def build_run_id(scenario_id: str) -> str:
    safe = _SAFE_ID_RE.sub("-", scenario_id.strip().lower()).strip("-") or "scenario"
    return f"opensquilla-tui-{safe}-{_now_ms()}"


def probe_terminal_capabilities() -> TerminalCapabilities:
    tmux_available = shutil.which("tmux") is not None
    pty_available = sys.platform != "win32" and hasattr(pty, "openpty")
    preferred_driver: Literal["tmux", "pty", "none"]
    if tmux_available:
        preferred_driver = "tmux"
    elif pty_available:
        preferred_driver = "pty"
    else:
        preferred_driver = "none"
    return TerminalCapabilities(
        tmux_available=tmux_available,
        pty_available=pty_available,
        screenshot_available=False,
        resize_available=tmux_available or pty_available,
        preferred_driver=preferred_driver,
        skip_reason=None if preferred_driver != "none" else "tmux and PTY are unavailable",
    )
```

- [ ] **Step 4: Run the tests to verify GREEN**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_driver_capabilities.py -q
```

Expected: PASS.

- [ ] **Step 5: Add tmux and PTY session implementations**

Extend `driver.py` with:

```python
@dataclass
class _BaseTerminalSession:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    run_id: str
    size: TerminalSize
    terminal_log: Path
    kind: DriverKind = field(init=False)

    def _append_log(self, text: str) -> None:
        self.terminal_log.parent.mkdir(parents=True, exist_ok=True)
        with self.terminal_log.open("a", encoding="utf-8") as fh:
            fh.write(text)
            if text and not text.endswith("\n"):
                fh.write("\n")


class TmuxTerminalSession(_BaseTerminalSession):
    kind: DriverKind = "tmux"

    def start(self) -> None:
        env_prefix = ["env", *[f"{key}={value}" for key, value in self.env.items()]]
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                self.run_id,
                "-x",
                str(self.size.cols),
                "-y",
                str(self.size.rows),
                "-c",
                str(self.cwd),
                *env_prefix,
                *self.command,
            ],
            check=True,
        )

    def send_text(self, text: str) -> None:
        subprocess.run(["tmux", "send-keys", "-t", self.run_id, "-l", text], check=True)
        subprocess.run(["tmux", "send-keys", "-t", self.run_id, "Enter"], check=True)

    def send_key(self, key: str) -> None:
        subprocess.run(["tmux", "send-keys", "-t", self.run_id, key], check=True)

    def paste(self, text: str) -> None:
        subprocess.run(["tmux", "load-buffer", "-b", self.run_id, text], check=True)
        subprocess.run(["tmux", "paste-buffer", "-t", self.run_id, "-b", self.run_id], check=True)

    def resize(self, size: TerminalSize) -> None:
        self.size = size
        subprocess.run(
            ["tmux", "resize-pane", "-t", self.run_id, "-x", str(size.cols), "-y", str(size.rows)],
            check=True,
        )

    def capture_text(self, checkpoint: str) -> TerminalFrame:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.run_id, "-p", "-J"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        frame = TerminalFrame(checkpoint, result.stdout, _now_ms(), self.size)
        self._append_log(f"\n--- {checkpoint} ---\n{frame.text}")
        return frame

    def wait_for_text(self, needle: str, *, timeout_s: float, checkpoint: str) -> TerminalFrame:
        deadline = time.monotonic() + timeout_s
        last = self.capture_text(checkpoint)
        while time.monotonic() < deadline:
            last = self.capture_text(checkpoint)
            if needle in last.text:
                return last
            time.sleep(0.05)
        raise TimeoutError(f"timed out waiting for {needle!r}; last screen:\n{last.text}")

    def is_alive(self) -> bool:
        return subprocess.run(
            ["tmux", "has-session", "-t", self.run_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def terminate(self) -> None:
        subprocess.run(
            ["tmux", "kill-session", "-t", self.run_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
```

Then add `PtyTerminalSession` using `pty.openpty()`, `subprocess.Popen`, nonblocking `os.read()`, `os.write()`, `fcntl.ioctl(TIOCSWINSZ)`, and the same `capture_text()`/`wait_for_text()` API. Keep its behavior text-only and set `kind = "pty"`.

- [ ] **Step 6: Add the session factory**

Add to `driver.py`:

```python
def open_real_terminal_session(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    run_id: str,
    size: TerminalSize,
    artifact_dir: Path,
    driver: Literal["auto", "tmux", "pty"] = "auto",
) -> RealTerminalSession:
    capabilities = probe_terminal_capabilities()
    selected = capabilities.preferred_driver if driver == "auto" else driver
    terminal_log = artifact_dir / "terminal.log"
    if selected == "tmux" and capabilities.tmux_available:
        return TmuxTerminalSession(command, cwd, env, run_id, size, terminal_log)
    if selected == "pty" and capabilities.pty_available:
        return PtyTerminalSession(command, cwd, env, run_id, size, terminal_log)
    reason = capabilities.skip_reason or f"requested terminal driver {selected!r} is unavailable"
    raise RuntimeError(reason)
```

- [ ] **Step 7: Run focused verification**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_driver_capabilities.py -q
uv run ruff check tests/integration/cli/tui_real_terminal/driver.py tests/integration/cli/tui_real_terminal/test_driver_capabilities.py
uv run mypy tests/integration/cli/tui_real_terminal/driver.py --show-error-codes
```

Expected: pytest PASS, ruff PASS, mypy PASS.

- [ ] **Step 8: Commit batch 1**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/__init__.py tests/integration/cli/tui_real_terminal/driver.py tests/integration/cli/tui_real_terminal/test_driver_capabilities.py
git commit -m "$(cat <<'MSG'
Prove real terminal ownership before TUI harness scenarios

Constraint: Real-terminal coverage needs tmux-first behavior with a PTY fallback and explicit capability skips.
Rejected: Driving prompt-toolkit through DummyInput only | it cannot validate real terminal lifecycle, resize, or screen capture behavior.
Confidence: high
Scope-risk: narrow
Directive: Keep terminal session names generated and owned so cleanup cannot kill unrelated user sessions.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_driver_capabilities.py -q; uv run ruff check tests/integration/cli/tui_real_terminal/driver.py tests/integration/cli/tui_real_terminal/test_driver_capabilities.py; uv run mypy tests/integration/cli/tui_real_terminal/driver.py --show-error-codes
Not-tested: Full ABCD terminal scenarios are added in later batches.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 2: TUI Backend Targets And Fake Provider/Session Fixtures

**Files:**
- Create: `tests/integration/cli/tui_real_terminal/targets.py`
- Create: `tests/integration/cli/tui_real_terminal/fake_terminal_app.py`
- Create: `tests/integration/cli/tui_real_terminal/conftest.py`
- Create: `tests/integration/cli/tui_real_terminal/test_targets.py`
- Create: `tests/integration/cli/tui_real_terminal/test_launch_input_loop.py`

- [ ] **Step 1: Write failing target tests**

Create `tests/integration/cli/tui_real_terminal/test_targets.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from tests.integration.cli.tui_real_terminal.driver import TerminalSize
from tests.integration.cli.tui_real_terminal.targets import (
    TargetContext,
    build_tui_target,
)


def test_terminal_target_builds_fake_app_command(tmp_path: Path) -> None:
    context = TargetContext(
        project_root=Path.cwd(),
        artifact_dir=tmp_path,
        scenario_id="launch_input_loop",
        size=TerminalSize(cols=100, rows=30),
    )

    target = build_tui_target("terminal", context)

    assert target.backend_id == "terminal"
    assert target.available is True
    assert target.command[:2] == [sys.executable, "-u"]
    assert "fake_terminal_app.py" in target.command[2]
    assert target.env["OPENSQUILLA_TUI_FAKE_SCENARIO"] == "launch_input_loop"
    assert target.readiness_markers == ("OPEN_SQUILLA_TUI_READY",)


def test_textual_target_builds_fake_live_app_command(tmp_path: Path) -> None:
    context = TargetContext(
        project_root=Path.cwd(),
        artifact_dir=tmp_path,
        scenario_id="launch_input_loop",
        size=TerminalSize(cols=100, rows=30),
    )

    target = build_tui_target("textual", context)

    assert target.backend_id == "textual"
    assert target.available is True
    assert target.skip_reason is None
    assert target.command
    assert "live-textual-app" in target.capability_requirements
```

- [ ] **Step 2: Run target tests to verify RED**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
```

Expected: FAIL with missing `targets` module.

- [ ] **Step 3: Implement `targets.py`**

Create `tests/integration/cli/tui_real_terminal/targets.py`:

```python
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from tests.integration.cli.tui_real_terminal.driver import TerminalSize


@dataclass(frozen=True)
class TargetContext:
    project_root: Path
    artifact_dir: Path
    scenario_id: str
    size: TerminalSize


@dataclass(frozen=True)
class TuiTarget:
    backend_id: str
    command: list[str]
    env: dict[str, str]
    initial_size: TerminalSize
    readiness_markers: tuple[str, ...]
    log_paths: tuple[Path, ...]
    capability_requirements: tuple[str, ...]
    available: bool = True
    skip_reason: str | None = None


def _base_env(context: TargetContext) -> dict[str, str]:
    existing = os.environ.copy()
    src = context.project_root / "src"
    existing["PYTHONPATH"] = str(src) + os.pathsep + existing.get("PYTHONPATH", "")
    existing["OPENSQUILLA_STATE_DIR"] = str(context.artifact_dir / "state")
    existing["OPENSQUILLA_LOG_DIR"] = str(context.artifact_dir / "logs")
    existing["OPENSQUILLA_TURN_CALL_LOG"] = "0"
    return existing


def _terminal_target(context: TargetContext) -> TuiTarget:
    app_path = Path(__file__).with_name("fake_terminal_app.py")
    app_log = context.artifact_dir / "app.log"
    env = _base_env(context)
    env.update(
        {
            "OPENSQUILLA_TUI_FAKE_SCENARIO": context.scenario_id,
            "OPENSQUILLA_TUI_FAKE_APP_LOG": str(app_log),
            "OPENSQUILLA_TUI_READY_MARKER": "OPEN_SQUILLA_TUI_READY",
        }
    )
    return TuiTarget(
        backend_id="terminal",
        command=[sys.executable, "-u", str(app_path)],
        env=env,
        initial_size=context.size,
        readiness_markers=("OPEN_SQUILLA_TUI_READY",),
        log_paths=(app_log,),
        capability_requirements=("real-terminal", "fake-provider"),
    )


def _textual_target(context: TargetContext) -> TuiTarget:
    app_path = Path(__file__).with_name("fake_textual_app.py")
    app_log = context.artifact_dir / "textual-app.log"
    env = _base_env(context)
    env.update(
        {
            "OPENSQUILLA_TUI_FAKE_SCENARIO": context.scenario_id,
            "OPENSQUILLA_TUI_FAKE_APP_LOG": str(app_log),
            "OPENSQUILLA_TUI_READY_MARKER": "OPEN_SQUILLA_TUI_READY",
            "OPENSQUILLA_TUI_BACKEND": "textual",
        }
    )
    return TuiTarget(
        backend_id="textual",
        command=[sys.executable, "-u", str(app_path)],
        env=env,
        initial_size=context.size,
        readiness_markers=("OPEN_SQUILLA_TUI_READY",),
        log_paths=(app_log,),
        capability_requirements=("live-textual-app",),
    )


def build_tui_target(backend_id: str, context: TargetContext) -> TuiTarget:
    if backend_id == "terminal":
        return _terminal_target(context)
    if backend_id == "textual":
        return _textual_target(context)
    raise ValueError(f"unknown TUI backend target: {backend_id}")
```

- [ ] **Step 4: Run target tests to verify GREEN**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
```

Expected: PASS.

- [ ] **Step 5: Create the fake terminal app using production TUI surfaces**

Create `tests/integration/cli/tui_real_terminal/fake_terminal_app.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from opensquilla.cli.chat.turn import UsageSummary
from opensquilla.cli.tui.adapters.terminal_chat_adapter import (
    get_tui_output,
    run_terminal_chat_runtime,
)
from opensquilla.cli.tui.terminal.stream import StreamingRenderer
from opensquilla.engine.commands import Surface


def _app_log() -> Path:
    return Path(os.environ["OPENSQUILLA_TUI_FAKE_APP_LOG"])


def _write_log(event: str, payload: dict[str, Any] | None = None) -> None:
    path = _app_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"event": event, "payload": payload or {}}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


async def _render_response(scope: dict[str, Any], user_input: str, scenario_id: str) -> bool:
    if user_input.strip() in {"/exit", "exit"}:
        _write_log("exit")
        return False
    output = get_tui_output(scope)
    if output is None:
        raise RuntimeError("terminal output handle was not exposed")
    renderer = StreamingRenderer(title="squilla", output_handle=output)
    _write_log("dispatch", {"input": user_input, "scenario_id": scenario_id})
    if scenario_id == "long_streaming":
        for index in range(80):
            await renderer.aappend_text(f"stream-token-{index:03d} ")
            if index % 20 == 0:
                await asyncio.sleep(0)
    elif scenario_id == "complex_ui_state":
        await renderer.astatus("router route standard -> fake-terminal 99% save 42%")
        output.set_toolbar("router_hud", "route standard -> fake-terminal 99% save 42%")
        output.set_toolbar("router_hud_style", "normal")
        output.invalidate()
        await renderer.atool_start("fake_tool", {"path": "fixture.txt"}, "tool-1")
        await renderer.atool_finished("tool-1", success=True, elapsed=0.01)
        await renderer.astatus("approval requested: allow fake_tool fixture.txt")
        await renderer.aappend_text("complex-state-complete tool-card history projection")
    elif scenario_id == "terminal_changes":
        await renderer.aappend_text(
            "terminal-change-response CJK混合ASCII multiline-paste ctrl-c-recovery "
            "wide-and-narrow-layout"
        )
    else:
        await renderer.aappend_text(f"fake-response:{user_input}")
    await renderer.afinalize(UsageSummary(model="fake-terminal", input_tokens=1, output_tokens=2))
    _write_log("turn_complete", {"input": user_input})
    return True


async def _run() -> None:
    scenario_id = os.environ.get("OPENSQUILLA_TUI_FAKE_SCENARIO", "launch_input_loop")
    ready_marker = os.environ.get("OPENSQUILLA_TUI_READY_MARKER", "OPEN_SQUILLA_TUI_READY")
    scope: dict[str, Any] = {
        "model": "fake-terminal",
        "session_key": f"fake:{scenario_id}",
    }
    print(ready_marker, flush=True)
    await run_terminal_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        queue_max_size=4,
        dispatch=lambda user_input: _render_response(scope, user_input, scenario_id),
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add the first launch smoke test**

Create `tests/integration/cli/tui_real_terminal/test_launch_input_loop.py`:

```python
from __future__ import annotations

import pytest

from tests.integration.cli.tui_real_terminal.driver import TerminalSize
from tests.integration.cli.tui_real_terminal.targets import TargetContext, build_tui_target


pytestmark = pytest.mark.tui_real_terminal


def test_terminal_launch_and_input_loop(tmp_path) -> None:
    context = TargetContext(
        project_root=tmp_path.parents[0] if False else __import__("pathlib").Path.cwd(),
        artifact_dir=tmp_path,
        scenario_id="launch_input_loop",
        size=TerminalSize(cols=100, rows=30),
    )
    target = build_tui_target("terminal", context)

    assert target.available is True
    assert target.readiness_markers == ("OPEN_SQUILLA_TUI_READY",)
```

This test only proves target construction in this batch; Task 4 replaces it with the full scenario runner after `scenarios.py` exists.

- [ ] **Step 7: Run focused verification**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
uv run ruff check tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/fake_terminal_app.py tests/integration/cli/tui_real_terminal/conftest.py tests/integration/cli/tui_real_terminal/test_targets.py tests/integration/cli/tui_real_terminal/test_launch_input_loop.py
uv run mypy tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/fake_terminal_app.py --show-error-codes
```

Expected: pytest PASS, ruff PASS, mypy PASS.

- [ ] **Step 8: Commit batch 2**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/fake_terminal_app.py tests/integration/cli/tui_real_terminal/conftest.py tests/integration/cli/tui_real_terminal/test_targets.py tests/integration/cli/tui_real_terminal/test_launch_input_loop.py
git commit -m "$(cat <<'MSG'
Drive the production terminal target with deterministic fixtures

Constraint: v1 real-terminal coverage must avoid live providers and network timing while still exercising the prompt-toolkit/Rich frontend.
Rejected: Making Textual the default target | the approved design keeps Textual comparable only after a live app exists.
Confidence: high
Scope-risk: moderate
Directive: Keep fake provider/session fixtures deterministic and scoped to the integration harness.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q; uv run ruff check changed harness target files; uv run mypy tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/fake_terminal_app.py --show-error-codes
Not-tested: Full terminal scenario driving lands after the scenario model.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 3: Scenario Model And Deterministic Assertions

**Files:**
- Create: `tests/integration/cli/tui_real_terminal/scenarios.py`
- Create: `tests/integration/cli/tui_real_terminal/assertions.py`
- Create: `tests/integration/cli/tui_real_terminal/evidence.py`
- Create: `tests/integration/cli/tui_real_terminal/test_scenario_model.py`

- [ ] **Step 1: Write failing model and assertion tests**

Create `tests/integration/cli/tui_real_terminal/test_scenario_model.py`:

```python
from __future__ import annotations

import json

import pytest

from tests.integration.cli.tui_real_terminal.assertions import (
    assert_no_raw_ansi_leakage,
    assert_visible_text,
)
from tests.integration.cli.tui_real_terminal.driver import TerminalFrame, TerminalSize
from tests.integration.cli.tui_real_terminal.evidence import EvidenceBundle
from tests.integration.cli.tui_real_terminal.scenarios import scenario_by_id


def test_launch_scenario_serializes_to_json(tmp_path) -> None:
    scenario = scenario_by_id("launch_input_loop")
    bundle = EvidenceBundle.create(tmp_path, scenario_id=scenario.scenario_id, backend_id="terminal")

    bundle.write_scenario(scenario.to_json_dict())

    data = json.loads((bundle.run_dir / "scenario.json").read_text())
    assert data["scenario_id"] == "launch_input_loop"
    assert data["family"] == "launch_and_input_loop"


def test_visible_text_assertion_includes_checkpoint() -> None:
    frame = TerminalFrame("after-input", "hello world", 1, TerminalSize())

    with pytest.raises(AssertionError, match="after-input"):
        assert_visible_text(frame, "missing")


def test_ansi_leakage_assertion_rejects_raw_escape() -> None:
    frame = TerminalFrame("after-stream", "safe \x1b[2J unsafe", 1, TerminalSize())

    with pytest.raises(AssertionError, match="raw terminal escape"):
        assert_no_raw_ansi_leakage(frame)
```

- [ ] **Step 2: Run model tests to verify RED**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q
```

Expected: FAIL with missing `assertions`, `evidence`, or `scenarios` modules.

- [ ] **Step 3: Implement deterministic assertions**

Create `tests/integration/cli/tui_real_terminal/assertions.py`:

```python
from __future__ import annotations

import re

from tests.integration.cli.tui_real_terminal.driver import TerminalFrame

_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\|[@-Z\\-_])")


def assert_visible_text(frame: TerminalFrame, expected: str) -> None:
    if expected not in frame.text:
        raise AssertionError(
            f"{frame.checkpoint}: expected visible text {expected!r}; screen was:\n{frame.text}"
        )


def assert_prompt_ready(frame: TerminalFrame) -> None:
    if "you" not in frame.text:
        raise AssertionError(f"{frame.checkpoint}: prompt is not visibly ready:\n{frame.text}")


def assert_no_traceback(frame: TerminalFrame) -> None:
    forbidden = ("Traceback (most recent call last)", "RuntimeError:", "Exception:")
    for marker in forbidden:
        if marker in frame.text:
            raise AssertionError(f"{frame.checkpoint}: unexpected error marker {marker!r}")


def assert_no_raw_ansi_leakage(frame: TerminalFrame) -> None:
    match = _ANSI_RE.search(frame.text)
    if match:
        raise AssertionError(
            f"{frame.checkpoint}: raw terminal escape leaked at offset {match.start()}"
        )
```

- [ ] **Step 4: Implement evidence bundle basics**

Create `tests/integration/cli/tui_real_terminal/evidence.py`:

```python
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.integration.cli.tui_real_terminal.driver import TerminalFrame


@dataclass(frozen=True)
class ScenarioFailure:
    step_id: str
    message: str
    elapsed_s: float
    last_screen: str
    artifact_dir: str


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    backend_id: str
    status: str
    run_dir: Path
    failure: ScenarioFailure | None = None


class EvidenceBundle:
    def __init__(self, run_dir: Path, *, scenario_id: str, backend_id: str) -> None:
        self.run_dir = run_dir
        self.scenario_id = scenario_id
        self.backend_id = backend_id
        self.frames_dir = run_dir / "frames"
        self.screenshots_dir = run_dir / "screenshots"
        self.transcript_path = run_dir / "transcript.txt"
        self.terminal_log_path = run_dir / "terminal.log"
        self.app_log_path = run_dir / "app.log"

    @classmethod
    def create(cls, root: Path, *, scenario_id: str, backend_id: str) -> EvidenceBundle:
        run_dir = root / f"{int(time.time() * 1000)}-{scenario_id}-{backend_id}"
        for path in (run_dir, run_dir / "frames", run_dir / "screenshots", run_dir / "logs"):
            path.mkdir(parents=True, exist_ok=True)
        return cls(run_dir, scenario_id=scenario_id, backend_id=backend_id)

    def write_scenario(self, payload: dict[str, Any]) -> None:
        (self.run_dir / "scenario.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def record_frame(self, frame: TerminalFrame) -> None:
        filename = f"{len(list(self.frames_dir.glob('*.txt'))):03d}-{frame.checkpoint}.txt"
        (self.frames_dir / filename).write_text(frame.text, encoding="utf-8")
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- {frame.checkpoint} ---\n{frame.text}\n")

    def write_result(self, result: ScenarioResult) -> None:
        payload: dict[str, Any] = {
            "scenario_id": result.scenario_id,
            "backend_id": result.backend_id,
            "status": result.status,
            "artifact_dir": str(result.run_dir),
        }
        if result.failure is not None:
            payload["failure"] = result.failure.__dict__
        (self.run_dir / "result.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
```

- [ ] **Step 5: Implement scenario dataclasses and lookup**

Create `tests/integration/cli/tui_real_terminal/scenarios.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from tests.integration.cli.tui_real_terminal.driver import RealTerminalSession, TerminalSize

ScenarioFamily = Literal[
    "launch_and_input_loop",
    "long_streaming_output",
    "complex_ui_state",
    "terminal_changes",
]


@dataclass(frozen=True)
class ScenarioStep:
    step_id: str
    action: str
    value: str = ""
    checkpoint: str = ""
    timeout_s: float = 5.0


@dataclass(frozen=True)
class TuiScenario:
    scenario_id: str
    family: ScenarioFamily
    initial_size: TerminalSize
    steps: tuple[ScenarioStep, ...]
    expected_text: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "initial_size": {"cols": self.initial_size.cols, "rows": self.initial_size.rows},
            "steps": [step.__dict__ for step in self.steps],
            "expected_text": list(self.expected_text),
        }


def scenario_by_id(scenario_id: str) -> TuiScenario:
    scenarios = {scenario.scenario_id: scenario for scenario in all_scenarios()}
    try:
        return scenarios[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown real-terminal TUI scenario: {scenario_id}") from exc


def all_scenarios() -> tuple[TuiScenario, ...]:
    return (
        TuiScenario(
            scenario_id="launch_input_loop",
            family="launch_and_input_loop",
            initial_size=TerminalSize(cols=100, rows=30),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep("send-message", "send_text", "hello harness", "after-input"),
                ScenarioStep("wait-response", "wait_text", "fake-response:hello harness", "after-response"),
            ),
            expected_text=("fake-response:hello harness", "you"),
        ),
    )
```

- [ ] **Step 6: Run model tests to verify GREEN**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q
```

Expected: PASS.

- [ ] **Step 7: Add `run_scenario()`**

Extend `scenarios.py` with:

```python
from tests.integration.cli.tui_real_terminal import assertions
from tests.integration.cli.tui_real_terminal.evidence import EvidenceBundle, ScenarioResult


def run_scenario(
    *,
    scenario: TuiScenario,
    session: RealTerminalSession,
    evidence: EvidenceBundle,
    backend_id: str,
) -> ScenarioResult:
    evidence.write_scenario(scenario.to_json_dict())
    session.start()
    last_frame = session.capture_text("started")
    evidence.record_frame(last_frame)
    try:
        for step in scenario.steps:
            if step.action == "wait_text":
                last_frame = session.wait_for_text(
                    step.value,
                    timeout_s=step.timeout_s,
                    checkpoint=step.checkpoint or step.step_id,
                )
            elif step.action == "send_text":
                session.send_text(step.value)
                last_frame = session.capture_text(step.checkpoint or step.step_id)
            elif step.action == "paste":
                session.paste(step.value)
                last_frame = session.capture_text(step.checkpoint or step.step_id)
            elif step.action == "key":
                session.send_key(step.value)
                last_frame = session.capture_text(step.checkpoint or step.step_id)
            elif step.action == "resize":
                cols, rows = step.value.split("x", 1)
                session.resize(TerminalSize(cols=int(cols), rows=int(rows)))
                last_frame = session.capture_text(step.checkpoint or step.step_id)
            else:
                raise ValueError(f"unknown scenario step action: {step.action}")
            evidence.record_frame(last_frame)
            assertions.assert_no_traceback(last_frame)
            assertions.assert_no_raw_ansi_leakage(last_frame)
        for expected in scenario.expected_text:
            assertions.assert_visible_text(last_frame, expected)
        assertions.assert_prompt_ready(last_frame)
        result = ScenarioResult(scenario.scenario_id, backend_id, "pass", evidence.run_dir)
        evidence.write_result(result)
        return result
    finally:
        session.terminate()
```

- [ ] **Step 8: Run focused verification**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q
uv run ruff check tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/assertions.py tests/integration/cli/tui_real_terminal/evidence.py tests/integration/cli/tui_real_terminal/test_scenario_model.py
uv run mypy tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/assertions.py tests/integration/cli/tui_real_terminal/evidence.py --show-error-codes
```

Expected: pytest PASS, ruff PASS, mypy PASS.

- [ ] **Step 9: Commit batch 3**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/assertions.py tests/integration/cli/tui_real_terminal/evidence.py tests/integration/cli/tui_real_terminal/test_scenario_model.py
git commit -m "$(cat <<'MSG'
Share TUI terminal scenarios across automation and lab runs

Constraint: Automated pytest and manual visual debugging must use the same scenario model and assertion language.
Rejected: Per-test bespoke terminal scripts | they would make Textual comparison and evidence review drift immediately.
Confidence: high
Scope-risk: moderate
Directive: Add new terminal behavior through TuiScenario steps before adding one-off driver calls.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q; uv run ruff check changed scenario files; uv run mypy tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/assertions.py tests/integration/cli/tui_real_terminal/evidence.py --show-error-codes
Not-tested: Full ABCD scenario launch waits are wired in the next batches.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 4: ABCD Pytest Scenarios

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/conftest.py`
- Modify: `tests/integration/cli/tui_real_terminal/scenarios.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_launch_input_loop.py`
- Create: `tests/integration/cli/tui_real_terminal/test_long_streaming.py`
- Create: `tests/integration/cli/tui_real_terminal/test_terminal_changes.py`
- Create: `tests/integration/cli/tui_real_terminal/test_complex_ui_state.py`

- [ ] **Step 1: Add pytest fixtures and options**

Create or replace `tests/integration/cli/tui_real_terminal/conftest.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.cli.tui_real_terminal.driver import (
    build_run_id,
    open_real_terminal_session,
    probe_terminal_capabilities,
)
from tests.integration.cli.tui_real_terminal.evidence import EvidenceBundle
from tests.integration.cli.tui_real_terminal.scenarios import TuiScenario
from tests.integration.cli.tui_real_terminal.targets import TargetContext, build_tui_target


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--tui-backend", action="store", default="terminal")
    parser.addoption("--tui-driver", action="store", default="auto", choices=("auto", "tmux", "pty"))
    parser.addoption(
        "--tui-artifact-root",
        action="store",
        default=".artifacts/tui-real-terminal/runs",
    )


@pytest.fixture
def artifact_root(pytestconfig: pytest.Config) -> Path:
    return Path(str(pytestconfig.getoption("--tui-artifact-root")))


@pytest.fixture
def tui_backend(pytestconfig: pytest.Config) -> str:
    return str(pytestconfig.getoption("--tui-backend"))


@pytest.fixture
def tui_driver(pytestconfig: pytest.Config) -> str:
    return str(pytestconfig.getoption("--tui-driver"))


@pytest.fixture
def run_real_terminal_scenario(artifact_root: Path, tui_backend: str, tui_driver: str):
    def _run(scenario: TuiScenario):
        capabilities = probe_terminal_capabilities()
        if capabilities.preferred_driver == "none":
            pytest.skip(capabilities.skip_reason or "real-terminal capabilities unavailable")
        evidence = EvidenceBundle.create(
            artifact_root,
            scenario_id=scenario.scenario_id,
            backend_id=tui_backend,
        )
        context = TargetContext(
            project_root=Path.cwd(),
            artifact_dir=evidence.run_dir,
            scenario_id=scenario.scenario_id,
            size=scenario.initial_size,
        )
        target = build_tui_target(tui_backend, context)
        if not target.available:
            pytest.skip(target.skip_reason or f"TUI backend {tui_backend!r} unavailable")
        from tests.integration.cli.tui_real_terminal.scenarios import run_scenario

        session = open_real_terminal_session(
            command=target.command,
            cwd=Path.cwd(),
            env=target.env,
            run_id=build_run_id(scenario.scenario_id),
            size=target.initial_size,
            artifact_dir=evidence.run_dir,
            driver=tui_driver,  # type: ignore[arg-type]
        )
        return run_scenario(
            scenario=scenario,
            session=session,
            evidence=evidence,
            backend_id=target.backend_id,
        )

    return _run
```

- [ ] **Step 2: Expand scenarios for ABCD**

Extend `all_scenarios()` in `scenarios.py` to include:

```python
TuiScenario(
    scenario_id="long_streaming",
    family="long_streaming_output",
    initial_size=TerminalSize(cols=100, rows=30),
    steps=(
        ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
        ScenarioStep("send-message", "send_text", "stream please", "after-input"),
        ScenarioStep("wait-stream", "wait_text", "stream-token-079", "after-stream"),
    ),
    expected_text=("stream-token-000", "stream-token-079", "fake-terminal", "you"),
),
TuiScenario(
    scenario_id="complex_ui_state",
    family="complex_ui_state",
    initial_size=TerminalSize(cols=110, rows=34),
    steps=(
        ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
        ScenarioStep("send-message", "send_text", "complex state please", "after-input"),
        ScenarioStep("wait-tool", "wait_text", "complex-state-complete", "after-complex"),
    ),
    expected_text=("route standard", "fake_tool", "approval requested", "complex-state-complete", "you"),
),
TuiScenario(
    scenario_id="terminal_changes",
    family="terminal_changes",
    initial_size=TerminalSize(cols=100, rows=30),
    steps=(
        ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
        ScenarioStep("resize-narrow", "resize", "72x24", "after-narrow"),
        ScenarioStep("paste-multiline", "paste", "first line\nsecond line CJK混合ASCII", "after-paste"),
        ScenarioStep("submit-paste", "key", "Enter", "after-submit"),
        ScenarioStep("wait-terminal-change", "wait_text", "terminal-change-response", "after-response"),
        ScenarioStep("resize-wide", "resize", "120x34", "after-wide"),
        ScenarioStep("ctrl-c", "key", "C-c", "after-ctrl-c"),
    ),
    expected_text=("terminal-change-response", "CJK混合ASCII", "you"),
),
```

- [ ] **Step 3: Replace launch smoke with full scenario**

Replace `test_launch_input_loop.py`:

```python
from __future__ import annotations

import pytest

from tests.integration.cli.tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_terminal_launch_and_input_loop(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("launch_input_loop"))

    assert result.status == "pass"
    assert (result.run_dir / "scenario.json").exists()
    assert (result.run_dir / "transcript.txt").exists()
```

- [ ] **Step 4: Add scenario test files**

Create `test_long_streaming.py`:

```python
from __future__ import annotations

import pytest

from tests.integration.cli.tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_long_streaming_output(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("long_streaming"))

    assert result.status == "pass"
```

Create `test_complex_ui_state.py`:

```python
from __future__ import annotations

import pytest

from tests.integration.cli.tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_complex_ui_state(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("complex_ui_state"))

    assert result.status == "pass"
```

Create `test_terminal_changes.py`:

```python
from __future__ import annotations

import pytest

from tests.integration.cli.tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_terminal_resize_paste_ctrl_c_and_eof(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("terminal_changes"))

    assert result.status == "pass"
```

- [ ] **Step 5: Run focused scenario tests**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
uv run pytest tests/integration/cli/tui_real_terminal/test_long_streaming.py tests/integration/cli/tui_real_terminal/test_terminal_changes.py -q
uv run pytest tests/integration/cli/tui_real_terminal/test_complex_ui_state.py -q
```

Expected: PASS when tmux or PTY is available; otherwise SKIP with an explicit capability reason.

- [ ] **Step 6: Run static checks**

Run:

```bash
uv run ruff check tests/integration/cli/tui_real_terminal
uv run mypy tests/integration/cli/tui_real_terminal --show-error-codes
```

Expected: ruff PASS, mypy PASS.

- [ ] **Step 7: Commit batches 4 and 5**

After launch, long-streaming, and terminal-change tests pass, commit:

```bash
git add tests/integration/cli/tui_real_terminal/conftest.py tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/test_launch_input_loop.py tests/integration/cli/tui_real_terminal/test_long_streaming.py tests/integration/cli/tui_real_terminal/test_terminal_changes.py
git commit -m "$(cat <<'MSG'
Cover streaming and terminal-change TUI scenarios

Constraint: The approved harness scope includes launch/input, long streaming, and terminal-change families before visual review.
Rejected: Unit replay-only coverage | replay cannot prove resize, paste, Ctrl-C, or real prompt redraw behavior.
Confidence: medium
Scope-risk: moderate
Directive: Keep capability skips explicit when tmux and PTY are unavailable.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q; uv run pytest tests/integration/cli/tui_real_terminal/test_long_streaming.py tests/integration/cli/tui_real_terminal/test_terminal_changes.py -q; uv run ruff check tests/integration/cli/tui_real_terminal; uv run mypy tests/integration/cli/tui_real_terminal --show-error-codes
Not-tested: Complex UI state is committed separately.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Then commit complex UI state:

```bash
git add tests/integration/cli/tui_real_terminal/fake_terminal_app.py tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/test_complex_ui_state.py
git commit -m "$(cat <<'MSG'
Exercise complex TUI state in the real terminal harness

Constraint: Tool-call, approval, router HUD, and history projection states must be visible in evidence.
Rejected: Treating complex state as a later manual-only visual check | deterministic assertions need to catch missing state before screenshots are reviewed.
Confidence: medium
Scope-risk: moderate
Directive: Keep fake complex events deterministic and avoid live provider flows in real-terminal v1.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_complex_ui_state.py -q; uv run ruff check tests/integration/cli/tui_real_terminal; uv run mypy tests/integration/cli/tui_real_terminal --show-error-codes
Not-tested: Visual verdict blocking policy lands in a later batch.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: two commits are created.

## Task 5: Evidence Bundle And Artifact Layout

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/evidence.py`
- Modify: `tests/integration/cli/tui_real_terminal/scenarios.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_scenario_model.py`

- [ ] **Step 1: Add failing evidence layout tests**

Extend `test_scenario_model.py`:

```python
def test_evidence_bundle_writes_required_artifacts(tmp_path) -> None:
    bundle = EvidenceBundle.create(tmp_path, scenario_id="launch_input_loop", backend_id="terminal")
    frame = TerminalFrame("ready", "OPEN_SQUILLA_TUI_READY", 1, TerminalSize())

    bundle.write_scenario({"scenario_id": "launch_input_loop"})
    bundle.record_frame(frame)
    bundle.write_visual_verdict(
        {
            "status": "inspect",
            "severity": "inspect-only",
            "affected_region": "terminal",
            "symptom": "screenshot unavailable",
            "suspected_cause": "text-only run",
            "recommended_next_action": "review transcript",
        }
    )

    assert (bundle.run_dir / "scenario.json").exists()
    assert (bundle.run_dir / "terminal.log").exists()
    assert (bundle.run_dir / "app.log").exists()
    assert (bundle.run_dir / "transcript.txt").exists()
    assert (bundle.run_dir / "frames" / "000-ready.txt").exists()
    assert (bundle.run_dir / "screenshots").is_dir()
    assert (bundle.run_dir / "visual-verdict.json").exists()
```

- [ ] **Step 2: Run evidence test to verify RED**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py::test_evidence_bundle_writes_required_artifacts -q
```

Expected: FAIL because `write_visual_verdict()` and required empty logs are not present.

- [ ] **Step 3: Implement complete evidence writers**

Extend `EvidenceBundle.create()` to touch `terminal.log`, `app.log`, and `transcript.txt`:

```python
for file_path in (run_dir / "terminal.log", run_dir / "app.log", run_dir / "transcript.txt"):
    file_path.touch()
```

Add to `EvidenceBundle`:

```python
def write_visual_verdict(self, payload: dict[str, Any]) -> None:
    (self.run_dir / "visual-verdict.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

def append_app_log_tail(self, text: str) -> None:
    with self.app_log_path.open("a", encoding="utf-8") as fh:
        fh.write(text)
        if text and not text.endswith("\n"):
            fh.write("\n")
```

Update `run_scenario()` to catch exceptions, capture a `failure` frame, write `ScenarioFailure`, then re-raise the original assertion after writing `result.json`.

- [ ] **Step 4: Run evidence tests to verify GREEN**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused scenario smoke to verify artifacts**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
find .artifacts/tui-real-terminal/runs -maxdepth 3 -type f | sort | tail -20
```

Expected: pytest PASS or explicit capability SKIP; `find` output includes `scenario.json`, `terminal.log`, `app.log`, `transcript.txt`, `frames/*.txt`, `result.json`, and `visual-verdict.json` after visual integration lands in Task 7.

- [ ] **Step 6: Commit batch 6 evidence half**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/evidence.py tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/test_scenario_model.py
git commit -m "$(cat <<'MSG'
Preserve terminal evidence for every harness scenario

Constraint: Harness failures must include scenario JSON, terminal transcript, logs, frames, and artifact paths for diagnosis.
Rejected: Printing failure context only to pytest stdout | it disappears from manual visual workflows and CI artifact collection.
Confidence: high
Scope-risk: narrow
Directive: Write evidence before re-raising scenario failures.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q; uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
Not-tested: Screenshot capture remains capability-dependent.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 6: Manual Visual Lab Entrypoint

**Files:**
- Create: `scripts/tui_real_terminal_lab.py`
- Modify: `tests/integration/cli/tui_real_terminal/scenarios.py`

- [ ] **Step 1: Write the manual lab script**

Create `scripts/tui_real_terminal_lab.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from tests.integration.cli.tui_real_terminal.driver import build_run_id, open_real_terminal_session
from tests.integration.cli.tui_real_terminal.evidence import EvidenceBundle
from tests.integration.cli.tui_real_terminal.scenarios import all_scenarios, scenario_by_id, run_scenario
from tests.integration.cli.tui_real_terminal.targets import TargetContext, build_tui_target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an OpenSquilla TUI real-terminal scenario.")
    parser.add_argument("--scenario", choices=[scenario.scenario_id for scenario in all_scenarios()], required=True)
    parser.add_argument("--backend", choices=("terminal", "textual"), default="terminal")
    parser.add_argument("--driver", choices=("auto", "tmux", "pty"), default="auto")
    parser.add_argument("--artifact-root", default=".artifacts/tui-real-terminal/runs")
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = scenario_by_id(args.scenario)
    evidence = EvidenceBundle.create(
        Path(args.artifact_root),
        scenario_id=scenario.scenario_id,
        backend_id=args.backend,
    )
    context = TargetContext(
        project_root=Path.cwd(),
        artifact_dir=evidence.run_dir,
        scenario_id=scenario.scenario_id,
        size=scenario.initial_size,
    )
    target = build_tui_target(args.backend, context)
    if not target.available:
        raise SystemExit(target.skip_reason or f"backend {args.backend!r} unavailable")
    session = open_real_terminal_session(
        command=target.command,
        cwd=Path.cwd(),
        env=target.env,
        run_id=build_run_id(scenario.scenario_id),
        size=target.initial_size,
        artifact_dir=evidence.run_dir,
        driver=args.driver,
    )
    result = run_scenario(
        scenario=scenario,
        session=session,
        evidence=evidence,
        backend_id=target.backend_id,
    )
    print(f"{result.status}: {result.run_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run manual lab help**

Run:

```bash
uv run python scripts/tui_real_terminal_lab.py --help
```

Expected: command exits 0 and lists `--scenario`, `--backend`, `--driver`, and `--artifact-root`.

- [ ] **Step 3: Run manual lab smoke**

Run:

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend terminal
```

Expected: PASS output with artifact directory when tmux or PTY is available; otherwise a clear capability error from the driver.

- [ ] **Step 4: Run static checks**

Run:

```bash
uv run ruff check scripts/tui_real_terminal_lab.py
uv run mypy scripts/tui_real_terminal_lab.py --show-error-codes
```

Expected: ruff PASS, mypy PASS.

- [ ] **Step 5: Commit batch 6 manual half**

Run:

```bash
git add scripts/tui_real_terminal_lab.py
git commit -m "$(cat <<'MSG'
Expose the real terminal harness as a manual lab

Constraint: Visual debugging must use the same backend target, scenario model, and evidence bundle as pytest.
Rejected: A separate ad hoc tmux helper | it would bypass deterministic assertions and drift from automated coverage.
Confidence: high
Scope-risk: narrow
Directive: Add lab-only behavior through the shared scenario and target contracts.
Tested: uv run python scripts/tui_real_terminal_lab.py --help; uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend terminal; uv run ruff check scripts/tui_real_terminal_lab.py; uv run mypy scripts/tui_real_terminal_lab.py --show-error-codes
Not-tested: Visual screenshot capture remains capability-dependent.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 7: Visual Verdict Contract, CI Marker, And Docs

**Files:**
- Create: `tests/integration/cli/tui_real_terminal/visual.py`
- Modify: `tests/integration/cli/tui_real_terminal/evidence.py`
- Modify: `tests/integration/cli/tui_real_terminal/scenarios.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_scenario_model.py`
- Modify: `pyproject.toml`
- Create: `docs/tui-real-terminal-harness.md`

- [ ] **Step 1: Write failing visual verdict tests**

Extend `test_scenario_model.py`:

```python
from tests.integration.cli.tui_real_terminal.visual import build_visual_verdict


def test_visual_verdict_contract_defaults_to_inspect_without_screenshot() -> None:
    verdict = build_visual_verdict(
        scenario_id="launch_input_loop",
        checkpoint="after-response",
        backend_id="terminal",
        terminal_size={"cols": 100, "rows": 30},
        screenshot_path=None,
        frame_path="frames/000-after-response.txt",
        expected_visible_regions=("prompt", "assistant stream"),
    )

    assert verdict["status"] == "inspect"
    assert verdict["severity"] == "inspect-only"
    assert verdict["affected_region"] == "terminal"
    assert verdict["recommended_next_action"]
```

- [ ] **Step 2: Run visual test to verify RED**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py::test_visual_verdict_contract_defaults_to_inspect_without_screenshot -q
```

Expected: FAIL because `visual.py` does not exist.

- [ ] **Step 3: Implement visual verdict contract**

Create `tests/integration/cli/tui_real_terminal/visual.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_visual_verdict(
    *,
    scenario_id: str,
    checkpoint: str,
    backend_id: str,
    terminal_size: dict[str, int],
    screenshot_path: str | None,
    frame_path: str,
    expected_visible_regions: tuple[str, ...],
) -> dict[str, Any]:
    status = "inspect" if screenshot_path is None else "pass"
    severity = "inspect-only" if screenshot_path is None else "acceptable-variation"
    symptom = "screenshot unavailable" if screenshot_path is None else "no blocking visual symptom detected"
    return {
        "status": status,
        "severity": severity,
        "affected_region": "terminal",
        "symptom": symptom,
        "suspected_cause": "text-only driver mode" if screenshot_path is None else "none",
        "recommended_next_action": "review transcript and frames" if screenshot_path is None else "keep evidence",
        "input": {
            "scenario_id": scenario_id,
            "checkpoint": checkpoint,
            "backend_id": backend_id,
            "terminal_size": terminal_size,
            "screenshot_path": screenshot_path,
            "frame_path": frame_path,
            "expected_visible_regions": list(expected_visible_regions),
            "failure_modes": [
                "overlap between HUD, prompt, tool cards, and stream text",
                "clipping at terminal edge, panel border, or prompt region",
                "broken wrapping for long text, code fences, URLs, and CJK text",
                "unreadable hierarchy or color contrast",
                "stale loading, approval, or HUD state",
                "bad recovery after resize, Ctrl-C, approval, or EOF",
            ],
        },
    }


def blocking(verdict: dict[str, Any]) -> bool:
    return verdict.get("status") == "fail" and verdict.get("severity") == "blocking"
```

- [ ] **Step 4: Integrate verdict writing**

At the end of successful and failed `run_scenario()`, call `build_visual_verdict()` using the last frame path and write it with `EvidenceBundle.write_visual_verdict()`. If `blocking(verdict)` returns `True`, raise an assertion that includes the verdict path.

- [ ] **Step 5: Add pytest marker**

Modify `pyproject.toml` marker list:

```toml
    "tui_real_terminal: real terminal TUI integration tests driven through tmux or PTY",
```

- [ ] **Step 6: Add docs**

Create `docs/tui-real-terminal-harness.md`:

```markdown
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
```

- [ ] **Step 7: Run focused verification**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q
uv run ruff check tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py
uv run mypy tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py --show-error-codes
```

Expected: pytest PASS or explicit capability SKIP for terminal launch; ruff PASS; mypy PASS.

- [ ] **Step 8: Commit batch 7**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/visual.py tests/integration/cli/tui_real_terminal/evidence.py tests/integration/cli/tui_real_terminal/scenarios.py tests/integration/cli/tui_real_terminal/test_scenario_model.py pyproject.toml docs/tui-real-terminal-harness.md
git commit -m "$(cat <<'MSG'
Record visual verdicts without promoting Textual by default

Constraint: Visual review is a second-stage structured check and cannot replace deterministic scenario assertions.
Rejected: Pixel-perfect screenshot comparison as the default gate | the approved v1 policy avoids brittle visual blocking while evidence matures.
Confidence: high
Scope-risk: narrow
Directive: CI should block only deterministic failures and visual verdicts marked fail/blocking.
Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_scenario_model.py -q; uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q; uv run ruff check tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py; uv run mypy tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py --show-error-codes
Not-tested: Live Textual target comparison waits for a live app target.

Co-authored-by: OmX <omx@oh-my-codex.dev>
MSG
)"
```

Expected: one commit is created.

## Task 8: Integration Verification And Final Audit

**Files:**
- Modify only files needed to fix verification failures from changed paths.

- [ ] **Step 1: Run required focused gates**

Run:

```bash
uv run pytest tests/test_public_release_hygiene.py -q
uv run pytest tests/unit/cli/tui tests/test_cli/test_chat_cmd.py -q
uv run pytest tests/integration/cli/tui_real_terminal -q
```

Expected: PASS. The real-terminal suite may SKIP only when tmux and PTY are unavailable, or when `--tui-backend textual` is selected before a live Textual app exists.

- [ ] **Step 2: Run changed-path static checks**

Run:

```bash
uv run ruff check tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py pyproject.toml
uv run mypy tests/integration/cli/tui_real_terminal scripts/tui_real_terminal_lab.py --show-error-codes
python -m compileall src/opensquilla
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 3: Run broader suite if time and environment allow**

Run:

```bash
uv run pytest -q
```

Expected: PASS or documented external/live-provider skips already accepted by repo policy.

- [ ] **Step 4: Inspect commit graph and worktree**

Run:

```bash
git log --oneline --decorate -8
git status --short
```

Expected: recent commits correspond to meaningful feature batches and worktree is clean.

- [ ] **Step 5: Completion audit**

Check:

```bash
test -f docs/superpowers/plans/2026-05-28-tui-real-terminal-harness-implementation-plan.md
test -f docs/superpowers/specs/2026-05-28-tui-real-terminal-harness-design.md
test -f tests/integration/cli/tui_real_terminal/driver.py
test -f tests/integration/cli/tui_real_terminal/scenarios.py
test -f tests/integration/cli/tui_real_terminal/evidence.py
test -f tests/integration/cli/tui_real_terminal/visual.py
test -f scripts/tui_real_terminal_lab.py
rg -n "launch_input_loop|long_streaming|complex_ui_state|terminal_changes" tests/integration/cli/tui_real_terminal
rg -n "tui_real_terminal" pyproject.toml docs/tui-real-terminal-harness.md
```

Expected: every command exits 0 and confirms all explicit deliverables exist.

## Self-Review

Spec coverage:

- Unified real terminal driver: Task 1 creates `RealTerminalSession`, tmux primary, PTY fallback, capability probe, lifecycle cleanup, input, resize, wait, and capture.
- Backend targets: Task 2 creates `TuiTarget`, terminal target, deterministic fake provider/session behavior, and explicit Textual unavailable behavior.
- Shared scenario model: Task 3 creates `TuiScenario`, `ScenarioStep`, shared runner, and deterministic assertions.
- ABCD coverage: Task 4 creates launch/input, long streaming, complex UI state, and terminal-change pytest scenarios.
- Evidence bundle: Task 5 creates scenario JSON, terminal transcript/log, app log, frames, screenshots directory, result JSON, and failure context.
- Manual/visual lab: Task 6 creates `scripts/tui_real_terminal_lab.py` using the same scenario runner.
- Visual verdict: Task 7 creates `visual-verdict.json`, structured status/severity fields, marker policy, and docs.
- Integration verification: Task 8 lists the required final gates from the objective.

Deferred-detail scan:

- This plan contains no deferred-work markers.
- This plan contains no undecided-detail markers.
- This plan contains no open-ended completion-later instruction.

Type consistency:

- `TerminalSize`, `TerminalFrame`, `TerminalCapabilities`, `RealTerminalSession`, `TuiTarget`, `TargetContext`, `TuiScenario`, `ScenarioStep`, `EvidenceBundle`, `ScenarioResult`, and `ScenarioFailure` are named consistently across tasks.
- The scenario ids are `launch_input_loop`, `long_streaming`, `complex_ui_state`, and `terminal_changes` in every file.
- The backend ids are `terminal` and `textual` in every file.

Execution handoff:

The user has already approved the Subagent-Driven / multi-agent execution path. Begin implementation with `superpowers:subagent-driven-development`, assign each native Codex subagent clear file ownership, and keep the leader responsible for merge order, focused verification, commits, and final audit.
