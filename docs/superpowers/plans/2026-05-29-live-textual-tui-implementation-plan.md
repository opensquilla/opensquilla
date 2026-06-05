# Live Textual TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real, interactively launchable Textual TUI that passes the deterministic real-terminal harness under `--tui-backend textual` and can be selected explicitly for production chat/gateway sessions.

**Architecture:** Add a live Textual surface adapter that implements the existing `TuiSurface` and `TuiOutputHandle` contracts, then compose it with `run_tui_runtime()` exactly as the terminal adapter does. Keep the existing `TextualReplayRenderer` as the headless replay backend and keep production Textual launch explicit through backend selection, with terminal remaining the default.

**Tech Stack:** Python 3.12, Textual 8.2.7, Rich, pytest, real-terminal tmux/PTY harness, `uv`, ruff, mypy.

---

## File Structure

- Create `src/opensquilla/cli/tui/textual/__init__.py`
  - Public package marker for the live Textual surface. Export only live-app names from this package.
- Create `src/opensquilla/cli/tui/textual/app.py`
  - Own `TextualChatApp`, a real `textual.app.App` subclass. Compose `Header`, `RichLog`, `Input`, `Static`, and `Footer`. Convert `Input.Submitted` events into queued submitted lines. Emit the configured readiness marker from `on_mount()`.
- Create `src/opensquilla/cli/tui/textual/stream.py`
  - Own `TextualStream`, the streaming context manager used by the live output handle. Coalesce chunks and write to the app transcript without importing the headless replay renderer.
- Create `src/opensquilla/cli/tui/textual/surface.py`
  - Own `TextualSurface`, `TextualOutputHandle`, and `open_textual_surface()`. This file is the live adapter boundary that satisfies `TuiSurface` and `TuiOutputHandle`.
- Create `src/opensquilla/cli/tui/textual/runtime.py`
  - Own `TextualChatRuntimeContext`, `textual_notice()`, and `run_textual_chat_runtime()`. Compose `open_textual_surface()` with `run_tui_runtime()` and reuse `classify_chat_input()`, `surface_task_name()`, `clear_current_cancel()`, and `default_tui_plugin_manager()`.
- Create `src/opensquilla/cli/tui/adapters/textual_bridge.py`
  - Bridge production gateway/standalone runtime loops to `run_textual_chat_runtime()` without importing Textual into core chat modules.
- Modify `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
  - Select terminal or Textual bridge from `OPENSQUILLA_TUI_BACKEND`, while preserving terminal as default.
- Modify `src/opensquilla/cli/tui/adapters/__init__.py`
  - Export `textual_bridge`.
- Modify `src/opensquilla/cli/tui/__init__.py`
  - Export `textual` and `textual_bridge`.
- Modify `tests/integration/cli/tui_real_terminal/targets.py`
  - Replace the unavailable Textual target with a real fake app command.
- Create `tests/integration/cli/tui_real_terminal/fake_textual_app.py`
  - Mirror `fake_terminal_app.py`, but call `run_textual_chat_runtime()` and use live Textual output.
- Modify `tests/integration/cli/tui_real_terminal/test_targets.py`
  - Replace the unavailable-target assertion with real command and no-skip assertions.
- Create `tests/unit/cli/tui/test_textual_surface.py`
  - Unit-test live app/surface/output handle contracts without a real terminal.
- Create `tests/unit/cli/repl/test_textual_chat_adapter.py`
  - Unit-test `run_textual_chat_runtime()` output exposure and runtime reuse.
- Modify `tests/unit/cli/repl/test_runtime_bridge.py`
  - Prove explicit `OPENSQUILLA_TUI_BACKEND=textual` selection routes production chat loops through `textual_bridge`.
- Modify `tests/unit/cli/repl/test_launch_bridge.py`
  - Prove terminal remains default and explicit Textual validation is honored before interactive preparation.
- Modify `tests/unit/cli/tui/test_contracts.py`
  - Add Textual adapter modules to the allowed adapter/package surfaces if the package-boundary assertions require it.

## External API Notes

Context7 was checked against the official Textual documentation for Textual 8.x:

- `App.run_async()` runs the app asynchronously.
- `Input.Submitted` carries `event.value` and `event.input.clear()`.
- `RichLog.write(content)` appends strings or Rich renderables to a scrollable live log.
- `App.exit()` exits the live app.
- Textual event handlers may be async, but slow work should run outside widget handlers.

These notes are the API contract for implementation; local Textual 8.2.7 is installed in this environment.

## Commit Checkpoints

Use the repository Lore Commit Protocol for every commit. Do not commit a red test state.

1. Plan commit after this file passes self-review.
2. Live Textual app/surface/output handle skeleton after targeted unit tests pass.
3. Real-terminal harness Textual target after `test_targets.py` and a minimal launch scenario pass.
4. Full deterministic Textual scenario parity after the textual real-terminal path passes all scenario families.
5. Production explicit Textual runtime after unit tests prove gateway and standalone bridge selection.
6. Cleanup and final verification after the full acceptance matrix passes.

---

### Task 1: Commit This Implementation Plan

**Files:**
- Create: `docs/superpowers/plans/2026-05-29-live-textual-tui-implementation-plan.md`

- [ ] **Step 1: Verify the plan has no deferred implementation markers**

Run:

```bash
uv run python -c 'from pathlib import Path; text=Path("docs/superpowers/plans/2026-05-29-live-textual-tui-implementation-plan.md").read_text(); needles=["TB"+"D","TO"+"DO","implement "+"later","fill in "+"details","add "+"validation","handle "+"edge cases","Write tests for "+"the above","Similar to "+"Task"]; bad=[n for n in needles if n in text]; print("\n".join(bad)); raise SystemExit(1 if bad else 0)'
```

Expected: exit code `0` with no output.

- [ ] **Step 2: Verify the plan names the required acceptance commands**

Run:

```bash
rg -n -- "uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q|--tui-backend textual|uv run mypy src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal" docs/superpowers/plans/2026-05-29-live-textual-tui-implementation-plan.md
```

Expected: matches for the target test, Textual backend scenario run, and mypy gate.

- [ ] **Step 3: Commit the plan**

Run:

```bash
git add docs/superpowers/plans/2026-05-29-live-textual-tui-implementation-plan.md
git commit -m "Plan live Textual TUI delivery around runtime reuse" \
  -m "Constraint: Approved Goal C requires deterministic real-terminal Textual first, then explicit production Textual selection." \
  -m "Rejected: Keep live Textual represented as a skipped target | the acceptance goal requires a real textual.app.App launch path." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Directive: Keep TextualReplayRenderer headless and separate from the live Textual app." \
  -m "Tested: rg plan placeholder scan; rg acceptance-command coverage scan" \
  -m "Not-tested: Implementation and runtime matrix are planned in later commits."
```

Expected: new commit created on the implementation branch.

---

### Task 2: Write Failing Unit Tests for the Live Textual Surface

**Files:**
- Create: `tests/unit/cli/tui/test_textual_surface.py`
- Create later in this task group: `src/opensquilla/cli/tui/textual/__init__.py`
- Create later in this task group: `src/opensquilla/cli/tui/textual/app.py`
- Create later in this task group: `src/opensquilla/cli/tui/textual/surface.py`
- Create later in this task group: `src/opensquilla/cli/tui/textual/stream.py`

- [ ] **Step 1: Add the first failing surface contract tests**

Write this file:

```python
from __future__ import annotations

import asyncio

import pytest

from opensquilla.cli.tui.backend.contracts import TuiOutputHandle, TuiSurface
from opensquilla.engine.commands import Surface


@pytest.mark.asyncio
async def test_textual_surface_queues_submitted_input_and_eof() -> None:
    from opensquilla.cli.tui.textual.app import TextualChatApp
    from opensquilla.cli.tui.textual.surface import TextualSurface

    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    surface = TextualSurface(app, approval_surface=Surface.CLI_GATEWAY)

    assert isinstance(surface, TuiSurface)

    app.submit_text("hello textual")
    assert await asyncio.wait_for(surface.next_line(), timeout=1.0) == "hello textual"

    surface.emit_eof()
    assert await asyncio.wait_for(surface.next_line(), timeout=1.0) is None


@pytest.mark.asyncio
async def test_textual_output_handle_writes_and_streams_to_transcript() -> None:
    from opensquilla.cli.tui.textual.app import TextualChatApp
    from opensquilla.cli.tui.textual.surface import TextualOutputHandle

    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    output = TextualOutputHandle(app, approval_surface=Surface.CLI_GATEWAY)

    assert isinstance(output, TuiOutputHandle)
    assert output.approval_surface is Surface.CLI_GATEWAY

    await output.write_through("one-shot payload")
    async with output.stream_output() as write:
        write("stream ")
        write("payload")

    assert "one-shot payload" in app.transcript_text
    assert "stream payload" in app.transcript_text


def test_textual_output_handle_toolbar_invalidates_status() -> None:
    from opensquilla.cli.tui.textual.app import TextualChatApp
    from opensquilla.cli.tui.textual.surface import TextualOutputHandle

    app = TextualChatApp(
        model="fake-model",
        session_id="fake-session",
        ready_marker=None,
        print_ready_marker=False,
    )
    output = TextualOutputHandle(app, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "route standard -> fake-textual")
    output.set_toolbar("router_hud_style", "normal")
    output.invalidate()

    assert "route standard -> fake-textual" in app.status_text
```

- [ ] **Step 2: Run the tests to prove they fail for missing live modules**

Run:

```bash
uv run pytest tests/unit/cli/tui/test_textual_surface.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'opensquilla.cli.tui.textual'`.

---

### Task 3: Implement the Minimal Live Textual App and Surface

**Files:**
- Create: `src/opensquilla/cli/tui/textual/__init__.py`
- Create: `src/opensquilla/cli/tui/textual/app.py`
- Create: `src/opensquilla/cli/tui/textual/surface.py`
- Create: `src/opensquilla/cli/tui/textual/stream.py`
- Modify: `src/opensquilla/cli/tui/__init__.py`

- [ ] **Step 1: Add the package export**

Create `src/opensquilla/cli/tui/textual/__init__.py`:

```python
"""Live Textual TUI surface for OpenSquilla chat."""

from __future__ import annotations

from opensquilla.cli.tui.textual.app import TextualChatApp
from opensquilla.cli.tui.textual.surface import (
    TextualOutputHandle,
    TextualSurface,
    open_textual_surface,
)

__all__ = [
    "TextualChatApp",
    "TextualOutputHandle",
    "TextualSurface",
    "open_textual_surface",
]
```

- [ ] **Step 2: Add the live app**

Create `src/opensquilla/cli/tui/textual/app.py` with this shape:

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static


class TextualChatApp(App[None]):
    """Live Textual chat app with runtime-owned chat semantics."""

    CSS: ClassVar[str] = """
    Screen {
        layout: vertical;
    }
    #status {
        dock: top;
        height: 1;
    }
    #transcript {
        height: 1fr;
        border: solid $accent;
    }
    #input {
        dock: bottom;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+c", "cancel_turn", "Cancel"),
        ("ctrl+d", "request_shutdown", "Exit"),
    ]

    def __init__(
        self,
        *,
        model: str | None,
        session_id: str | None,
        ready_marker: str | None = "OPEN_SQUILLA_TUI_READY",
        print_ready_marker: bool = True,
    ) -> None:
        super().__init__()
        self.model = model
        self.session_id = session_id
        self.ready_marker = ready_marker
        self.print_ready_marker = print_ready_marker
        self.submitted_lines: asyncio.Queue[str | None] = asyncio.Queue()
        self.transcript_text = ""
        self.status_text = self._initial_status()
        self._cancel_callback: Callable[[], None] | None = None
        self._shutdown_callback: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical():
            yield Static(self.status_text, id="status")
            yield RichLog(id="transcript", wrap=True, markup=True, highlight=False)
            yield Input(placeholder="you", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        if self.ready_marker:
            self.append_output(self.ready_marker)
            if self.print_ready_marker:
                print(self.ready_marker, flush=True)

    @on(Input.Submitted)
    async def _on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value
        event.input.clear()
        self.submit_text(value)

    def submit_text(self, text: str) -> None:
        self.submitted_lines.put_nowait(text)

    async def next_submitted_line(self) -> str | None:
        return await self.submitted_lines.get()

    def emit_eof(self) -> None:
        self.submitted_lines.put_nowait(None)

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._cancel_callback = cb

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._shutdown_callback = cb

    def action_cancel_turn(self) -> None:
        if self._cancel_callback is not None:
            self._cancel_callback()

    def action_request_shutdown(self) -> None:
        if self._shutdown_callback is not None:
            self._shutdown_callback()
        else:
            self.emit_eof()

    def append_output(self, payload: str) -> None:
        self.transcript_text += payload
        log = self.query("#transcript")
        if log:
            self.query_one("#transcript", RichLog).write(payload)

    def set_status(self, value: str) -> None:
        self.status_text = value
        status = self.query("#status")
        if status:
            self.query_one("#status", Static).update(value)

    def refresh_ui(self) -> None:
        try:
            self.refresh()
        except Exception:
            return

    def _initial_status(self) -> str:
        model = self.model or "model auto"
        session = self.session_id or "new session"
        return f"OpenSquilla Textual | {model} | {session}"
```

- [ ] **Step 3: Add the streaming context manager**

Create `src/opensquilla/cli/tui/textual/stream.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from opensquilla.cli.tui.textual.app import TextualChatApp


@asynccontextmanager
async def textual_stream_output(
    app: TextualChatApp,
) -> AsyncIterator[Callable[[str], None]]:
    chunks: list[str] = []

    def write(delta: str) -> None:
        chunks.append(delta)

    try:
        yield write
    finally:
        if chunks:
            app.append_output("".join(chunks))
```

- [ ] **Step 4: Add the surface and output handle**

Create `src/opensquilla/cli/tui/textual/surface.py`:

```python
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from opensquilla.cli.tui.textual.app import TextualChatApp
from opensquilla.cli.tui.textual.stream import textual_stream_output
from opensquilla.engine.commands import Surface


class TextualOutputHandle:
    """Typed output bridge over the live Textual chat app."""

    def __init__(self, app: TextualChatApp, *, approval_surface: Surface) -> None:
        self._app = app
        self.approval_surface = approval_surface
        self._toolbar: dict[str, object] = {}

    async def write_through(self, payload: str) -> None:
        self._app.append_output(payload)

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]:
        return textual_stream_output(self._app)

    def set_toolbar(self, key: str, value: object | None) -> None:
        if value is None:
            self._toolbar.pop(key, None)
        else:
            self._toolbar[key] = value
        hud = self._toolbar.get("router_hud")
        self._app.set_status(str(hud) if hud is not None else self._app._initial_status())

    def invalidate(self) -> None:
        self._app.refresh_ui()


class TextualSurface:
    """Adapter exposing `TextualChatApp` through `TuiSurface`."""

    def __init__(self, app: TextualChatApp, *, approval_surface: Surface) -> None:
        self._app = app
        self._approval_surface = approval_surface

    async def next_line(self) -> str | None:
        return await self._app.next_submitted_line()

    @property
    def output_handle(self) -> TextualOutputHandle:
        return TextualOutputHandle(self._app, approval_surface=self._approval_surface)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return self._app.refresh_ui

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        self._app.set_cancel_callback(cb)

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        self._app.set_shutdown_callback(cb)

    def emit_eof(self) -> None:
        self._app.emit_eof()

    async def write_through(self, payload: str) -> None:
        self._app.append_output(payload)


@asynccontextmanager
async def open_textual_surface(
    *,
    surface: Surface,
    model: str | None = None,
    session_id: str | None = None,
    ready_marker: str | None = "OPEN_SQUILLA_TUI_READY",
    print_ready_marker: bool = True,
) -> AsyncIterator[TextualSurface]:
    app = TextualChatApp(
        model=model,
        session_id=session_id,
        ready_marker=ready_marker,
        print_ready_marker=print_ready_marker,
    )
    app_task = app.run_async()
    try:
        yield TextualSurface(app, approval_surface=surface)
    finally:
        app.exit()
        with contextlib.suppress(Exception):
            await app_task
```

- [ ] **Step 5: Export the live package from `opensquilla.cli.tui`**

Modify `src/opensquilla/cli/tui/__init__.py` so `__all__` includes:

```python
    "textual",
```

- [ ] **Step 6: Run the unit tests**

Run:

```bash
uv run pytest tests/unit/cli/tui/test_textual_surface.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Run type and lint checks for the new package**

Run:

```bash
uv run ruff check src/opensquilla/cli/tui/textual tests/unit/cli/tui/test_textual_surface.py
uv run mypy src/opensquilla/cli/tui/textual tests/unit/cli/tui/test_textual_surface.py
```

Expected: both commands pass.

- [ ] **Step 8: Commit the live surface skeleton**

Run:

```bash
git add src/opensquilla/cli/tui/__init__.py src/opensquilla/cli/tui/textual tests/unit/cli/tui/test_textual_surface.py
git commit -m "Introduce a live Textual surface contract" \
  -m "Constraint: Textual must satisfy TuiSurface and TuiOutputHandle without replacing the existing terminal runtime." \
  -m "Rejected: Merge the live app with TextualReplayRenderer | replay remains a headless benchmark backend, not the production app." \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Directive: Keep chat turn semantics outside Textual widget event handlers." \
  -m "Tested: uv run pytest tests/unit/cli/tui/test_textual_surface.py -q; uv run ruff check src/opensquilla/cli/tui/textual tests/unit/cli/tui/test_textual_surface.py; uv run mypy src/opensquilla/cli/tui/textual tests/unit/cli/tui/test_textual_surface.py" \
  -m "Not-tested: Real-terminal Textual launch is wired in the next checkpoint."
```

---

### Task 4: Write Failing Tests for Textual Runtime Reuse

**Files:**
- Create: `tests/unit/cli/repl/test_textual_chat_adapter.py`
- Create later: `src/opensquilla/cli/tui/textual/runtime.py`

- [ ] **Step 1: Add runtime reuse tests**

Write `tests/unit/cli/repl/test_textual_chat_adapter.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from opensquilla.engine.commands import Surface


class _FakeOutputHandle:
    approval_surface = Surface.CLI_GATEWAY

    async def write_through(self, payload: str) -> None:
        return None

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


class _FakeTextualSurface:
    output_handle = _FakeOutputHandle()

    async def next_line(self) -> str | None:
        return None

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None:
        return None

    def emit_eof(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        return None

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return lambda: None


@pytest.mark.asyncio
async def test_textual_chat_runtime_exposes_tui_output_and_reuses_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.tui.textual import runtime as textual_runtime

    scope: dict[str, Any] = {"model": "model-a", "session_key": "session-a"}
    captured: dict[str, Any] = {}
    fake_surface = _FakeTextualSurface()

    @asynccontextmanager
    async def fake_open_textual_surface(**kwargs: Any):
        captured["surface_kwargs"] = kwargs
        yield fake_surface

    async def fake_run_tui_runtime(**kwargs: Any):
        captured["runtime_kwargs"] = kwargs
        hooks = kwargs["hooks"]
        hooks.expose_surface(fake_surface)
        assert textual_runtime.get_tui_output(scope) is not None
        hooks.clear_exposed_surface()
        return object()

    monkeypatch.setattr(textual_runtime, "open_textual_surface", fake_open_textual_surface)
    monkeypatch.setattr(textual_runtime, "run_tui_runtime", fake_run_tui_runtime)

    async def fake_dispatch(_value: str) -> bool:
        return True

    await textual_runtime.run_textual_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=fake_dispatch,
        queue_max_size=8,
    )

    assert captured["surface_kwargs"] == {
        "surface": Surface.CLI_GATEWAY,
        "model": "model-a",
        "session_id": "session-a",
    }
    assert captured["runtime_kwargs"]["surface_factory"] is not None
    assert textual_runtime.get_tui_output(scope) is None


def test_textual_notice_writes_to_active_output_handle() -> None:
    from opensquilla.cli.tui.textual.runtime import textual_notice

    writes: list[str] = []

    class Output:
        approval_surface = Surface.CLI_GATEWAY

        async def write_through(self, payload: str) -> None:
            writes.append(payload)

        def stream_output(self):
            raise AssertionError("stream_output should not be called")

    scope: dict[str, Any] = {"tui_output": Output()}
    textual_notice(scope, "[yellow]Hello[/yellow]")

    assert any("Hello" in payload for payload in writes)
```

- [ ] **Step 2: Run the tests to prove the runtime module is missing**

Run:

```bash
uv run pytest tests/unit/cli/repl/test_textual_chat_adapter.py -q
```

Expected: fail with import error for `opensquilla.cli.tui.textual.runtime`.

---

### Task 5: Implement Textual Runtime Adapter

**Files:**
- Create: `src/opensquilla/cli/tui/textual/runtime.py`
- Modify if needed: `tests/unit/cli/repl/test_textual_chat_adapter.py`

- [ ] **Step 1: Implement the runtime adapter**

Create `src/opensquilla/cli/tui/textual/runtime.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from opensquilla.cli.tui.adapters.terminal_chat_adapter import (
    ChatAbortTurn,
    ChatRuntimeScope,
    TuiPluginOutputHandle,
    classify_chat_input,
    clear_current_cancel,
    default_tui_plugin_manager,
    echo_queued_turn_start,
    echo_user_input,
    surface_task_name,
)
from opensquilla.cli.tui.backend.contracts import (
    TuiOutputHandle,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurface,
)
from opensquilla.cli.tui.backend.output_binding import TuiOutputBinding
from opensquilla.cli.tui.backend.plugins import TuiPluginManager
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.textual.surface import open_textual_surface
from opensquilla.engine.commands import Surface


async def _noop_abort_turn() -> None:
    return None


@dataclass
class TextualChatRuntimeContext:
    """Typed Textual-chat adapter state with a legacy scope mirror."""

    surface: Surface
    scope: ChatRuntimeScope
    plugin_manager: TuiPluginManager
    abort_active_turn: ChatAbortTurn | None = None

    @property
    def model(self) -> str | None:
        value = self.scope.get("model")
        return value if isinstance(value, str) else None

    @property
    def session_id(self) -> str | None:
        value = self.scope.get("session_key")
        return value if isinstance(value, str) else None

    def abort_turn(self) -> Awaitable[None]:
        if self.surface is not Surface.CLI_GATEWAY or self.abort_active_turn is None:
            return _noop_abort_turn()
        return self.abort_active_turn()

    def get_output(self) -> TuiOutputHandle | None:
        return TuiOutputBinding(self.scope).get()

    def expose_surface(self, tui_surface: TuiSurface) -> None:
        output_handle = getattr(tui_surface, "output_handle", None)
        if isinstance(output_handle, TuiOutputHandle):
            TuiOutputBinding(self.scope).expose(
                TuiPluginOutputHandle(
                    output_handle,
                    plugin_manager=self.plugin_manager,
                )
            )

    def clear_output(self) -> None:
        TuiOutputBinding(self.scope).clear()


def get_tui_output(scope: MutableMapping[str, Any]) -> TuiOutputHandle | None:
    return TuiOutputBinding(scope).get()


def textual_notice(scope: MutableMapping[str, Any], payload: str) -> None:
    output = get_tui_output(scope)
    if output is None:
        return

    async def _write() -> None:
        await output.write_through(payload)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_write())
    else:
        loop.create_task(_write())


async def run_textual_chat_runtime(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: ChatAbortTurn | None = None,
) -> None:
    """Compose the Textual chat adapter with the shared TUI backend runtime."""
    context = TextualChatRuntimeContext(
        surface=surface,
        scope=scope,
        plugin_manager=default_tui_plugin_manager(),
        abort_active_turn=abort_active_turn,
    )

    def _surface_factory():
        return open_textual_surface(
            surface=surface,
            model=context.model,
            session_id=context.session_id,
        )

    def _notice(payload: str) -> None:
        textual_notice(scope, payload)

    await run_tui_runtime(
        dispatch=dispatch,
        surface_factory=_surface_factory,
        config=TuiRuntimeConfig(
            task_name=surface_task_name(surface),
            queue_max_size=queue_max_size,
            classify_input=classify_chat_input,
        ),
        hooks=TuiRuntimeHooks(
            on_user_input_echo=echo_user_input,
            on_queued_turn_start=echo_queued_turn_start,
            clear_current_cancel=clear_current_cancel,
            notice=_notice,
            on_cancel_active_turn=context.abort_turn,
            expose_surface=context.expose_surface,
            clear_exposed_surface=context.clear_output,
        ),
    )
```

- [ ] **Step 2: Run the Textual runtime tests**

Run:

```bash
uv run pytest tests/unit/cli/repl/test_textual_chat_adapter.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run adjacent adapter tests**

Run:

```bash
uv run pytest tests/unit/cli/repl/test_terminal_chat_adapter.py tests/unit/cli/tui/test_runtime.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run lint/type checks for live Textual runtime**

Run:

```bash
uv run ruff check src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_textual_chat_adapter.py
uv run mypy src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_textual_chat_adapter.py
```

Expected: both commands pass.

- [ ] **Step 5: Commit runtime adapter**

Run:

```bash
git add src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_textual_chat_adapter.py
git commit -m "Reuse the shared TUI runtime for Textual chat" \
  -m "Constraint: Textual must not copy a second chat runtime." \
  -m "Rejected: Drive chat turns directly from Textual widget handlers | run_tui_runtime already owns queuing, exit, cancel, and dispatch lifecycle." \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Directive: Future Textual behavior changes should pass through TuiSurface and TuiOutputHandle." \
  -m "Tested: uv run pytest tests/unit/cli/repl/test_textual_chat_adapter.py -q; uv run pytest tests/unit/cli/repl/test_terminal_chat_adapter.py tests/unit/cli/tui/test_runtime.py -q; uv run ruff check src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_textual_chat_adapter.py; uv run mypy src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_textual_chat_adapter.py" \
  -m "Not-tested: Real-terminal Textual harness is wired in the next checkpoint."
```

---

### Task 6: Replace the Unavailable Harness Target with a Real Textual Fake App

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/test_targets.py`
- Modify: `tests/integration/cli/tui_real_terminal/targets.py`
- Create: `tests/integration/cli/tui_real_terminal/fake_textual_app.py`

- [ ] **Step 1: Replace the unavailable-target test with a failing real-target test**

Modify `tests/integration/cli/tui_real_terminal/test_targets.py` by replacing `test_textual_target_is_explicitly_unavailable` with:

```python
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
    assert target.command[:2] == [sys.executable, "-u"]
    assert target.command[2].endswith("fake_textual_app.py")
    assert target.env["OPENSQUILLA_TUI_FAKE_SCENARIO"] == "launch_input_loop"
    assert target.env["OPENSQUILLA_TUI_READY_MARKER"] == "OPEN_SQUILLA_TUI_READY"
    assert target.readiness_markers == ("OPEN_SQUILLA_TUI_READY",)
    assert target.log_paths == (tmp_path / "textual-app.log",)
    assert "live-textual-app" in target.capability_requirements
    assert "missing-live-app" not in target.capability_requirements
```

- [ ] **Step 2: Run the target test to prove it fails on the old skip**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
```

Expected: fail because the test now expects a populated live Textual target before
the implementation exists.

- [ ] **Step 3: Implement the Textual target command**

Modify `_textual_target()` in `tests/integration/cli/tui_real_terminal/targets.py`:

```python
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
        capability_requirements=("real-terminal", "fake-provider", "live-textual-app"),
    )
```

- [ ] **Step 4: Add the fake Textual app**

Create `tests/integration/cli/tui_real_terminal/fake_textual_app.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from opensquilla.cli.chat.turn import UsageSummary  # type: ignore[import-untyped]
from opensquilla.cli.tui.textual.runtime import (  # type: ignore[import-untyped]
    get_tui_output,
    run_textual_chat_runtime,
)
from opensquilla.cli.tui.terminal.stream import StreamingRenderer  # type: ignore[import-untyped]
from opensquilla.engine.commands import Surface  # type: ignore[import-untyped]


def _app_log_path() -> Path:
    return Path(os.environ["OPENSQUILLA_TUI_FAKE_APP_LOG"])


def _write_log(event: str, payload: dict[str, Any] | None = None) -> None:
    path = _app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, "payload": payload or {}}, sort_keys=True) + "\n")


async def _render_response(
    scope: dict[str, Any],
    user_input: str,
    scenario_id: str,
) -> bool:
    if user_input.strip() in {"/exit", "exit"}:
        _write_log("exit")
        return False

    output = get_tui_output(scope)
    if output is None:
        raise RuntimeError("textual output handle was not exposed")

    renderer = StreamingRenderer(title="squilla", output_handle=output)
    _write_log("dispatch", {"input": user_input, "scenario_id": scenario_id})
    if scenario_id == "long_streaming":
        for index in range(80):
            await renderer.aappend_text(f"stream-token-{index:03d} ")
            if index % 20 == 0:
                await asyncio.sleep(0)
    elif scenario_id == "complex_ui_state":
        _set_toolbar(output, "router_hud", "route standard -> fake-textual 99% save 42%")
        _set_toolbar(output, "router_hud_style", "normal")
        _invalidate(output)
        await renderer.astatus("router route standard -> fake-textual 99% save 42%")
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
    await renderer.afinalize(
        UsageSummary(model="fake-textual", input_tokens=1, output_tokens=2)
    )
    _write_log("turn_complete", {"input": user_input})
    return True


def _set_toolbar(output: Any, key: str, value: object | None) -> None:
    setter = getattr(output, "set_toolbar", None)
    if callable(setter):
        setter(key, value)


def _invalidate(output: Any) -> None:
    invalidate = getattr(output, "invalidate", None)
    if callable(invalidate):
        invalidate()


async def _run() -> None:
    scenario_id = os.environ.get("OPENSQUILLA_TUI_FAKE_SCENARIO", "launch_input_loop")
    scope: dict[str, Any] = {
        "model": "fake-textual",
        "session_key": f"fake:{scenario_id}",
    }
    _write_log("ready", {"scenario_id": scenario_id})
    await run_textual_chat_runtime(
        surface=Surface.CLI_GATEWAY,
        scope=scope,
        dispatch=lambda user_input: _render_response(scope, user_input, scenario_id),
        queue_max_size=4,
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run target and minimal launch scenario**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q --tui-backend textual
```

Expected: target tests pass and `test_launch_input_loop.py` passes under the Textual backend.

- [ ] **Step 6: Commit the harness target**

Run:

```bash
git add tests/integration/cli/tui_real_terminal/test_targets.py tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/fake_textual_app.py
git commit -m "Launch the real Textual app in the TUI harness" \
  -m "Constraint: The real-terminal Textual target must be a live textual.app.App command, not an unavailable skip." \
  -m "Rejected: Preserve the missing-live-app skip | deterministic Textual scenarios must now launch and fail visibly when broken." \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Directive: Harness fake apps may depend on production Textual modules, but production modules must not depend on harness fixtures." \
  -m "Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q; uv run pytest tests/integration/cli/tui_real_terminal/test_launch_input_loop.py -q --tui-backend textual" \
  -m "Not-tested: Full Textual real-terminal scenario suite is the next checkpoint."
```

---

### Task 7: Pass Full Textual Real-Terminal Scenario Parity

**Files:**
- Modify as needed: `src/opensquilla/cli/tui/textual/app.py`
- Modify as needed: `src/opensquilla/cli/tui/textual/surface.py`
- Modify as needed: `src/opensquilla/cli/tui/textual/stream.py`
- Modify as needed: `tests/integration/cli/tui_real_terminal/fake_textual_app.py`

- [ ] **Step 1: Run the full Textual scenario suite**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
```

Expected before fixes: failures identify the first missing live behavior, likely prompt readiness, input echo visibility, streaming chunk visibility, resize refresh, multiline paste submission, or Ctrl+C callback.

- [ ] **Step 2: Fix prompt readiness and input echo if needed**

If `assert_prompt_ready()` fails, update `TextualChatApp.compose()` and `set_status()` so the final screen always contains `you`, for example:

```python
yield Input(placeholder="you", id="input")
```

If input echo is missing, keep using `echo_user_input()` from `terminal_chat_adapter` through `run_textual_chat_runtime()` and ensure `TextualSurface.write_through()` appends the payload.

- [ ] **Step 3: Fix streaming visibility if needed**

If `stream-token-079` is missing, change `textual_stream_output()` to flush every chunk instead of only at context exit:

```python
def write(delta: str) -> None:
    chunks.append(delta)
    app.append_output(delta)
```

Then keep the `finally` block from duplicating already-flushed chunks by tracking a `flushed_live` boolean.

- [ ] **Step 4: Fix complex UI status visibility if needed**

If `route standard`, `fake_tool`, or `approval requested` is missing, keep `StreamingRenderer` on the fake app and ensure `TextualOutputHandle.set_toolbar()` writes the router HUD into both status and transcript:

```python
if key == "router_hud" and value is not None:
    text = str(value)
    self._app.set_status(text)
    self._app.append_output(text)
```

- [ ] **Step 5: Fix resize and Ctrl+C stability if needed**

If resize fails, keep `redraw_callback` as `TextualChatApp.refresh_ui` and avoid terminal-specific signal installation in `run_textual_chat_runtime()`.

If Ctrl+C exits the app instead of canceling the turn, keep `BINDINGS = [("ctrl+c", "cancel_turn", "Cancel")]` and ensure `action_cancel_turn()` does not call `exit()`.

- [ ] **Step 6: Re-run Textual and terminal scenario suites**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
```

Expected: both backend suites pass.

- [ ] **Step 7: Run the manual lab smoke**

Run:

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend textual
```

Expected: command launches the Textual fake app, records artifacts under `.artifacts/tui-real-terminal`, and exits without traceback after the scenario.

- [ ] **Step 8: Run targeted lint/type checks**

Run:

```bash
uv run ruff check src/opensquilla/cli/tui/textual tests/integration/cli/tui_real_terminal
uv run mypy src/opensquilla/cli/tui/textual tests/integration/cli/tui_real_terminal
```

Expected: both commands pass.

- [ ] **Step 9: Commit full harness parity**

Run:

```bash
git add src/opensquilla/cli/tui/textual tests/integration/cli/tui_real_terminal
git commit -m "Bring Textual real-terminal scenarios to parity" \
  -m "Constraint: Textual must pass the same deterministic scenario families as terminal before production selection is wired." \
  -m "Rejected: Narrow the scenario assertions for Textual | the backend is accepted through the shared real-terminal scenario contract." \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Directive: Keep terminal backend behavior green whenever Textual harness behavior changes." \
  -m "Tested: uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual; uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal; uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend textual; uv run ruff check src/opensquilla/cli/tui/textual tests/integration/cli/tui_real_terminal; uv run mypy src/opensquilla/cli/tui/textual tests/integration/cli/tui_real_terminal" \
  -m "Not-tested: Production explicit Textual bridge is the next checkpoint."
```

---

### Task 8: Wire Explicit Production Textual Selection

**Files:**
- Create: `src/opensquilla/cli/tui/adapters/textual_bridge.py`
- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Modify: `src/opensquilla/cli/tui/adapters/__init__.py`
- Modify: `src/opensquilla/cli/tui/__init__.py`
- Modify: `tests/unit/cli/repl/test_runtime_bridge.py`
- Modify: `tests/unit/cli/repl/test_launch_bridge.py`
- Modify if package-boundary tests require it: `tests/unit/cli/tui/test_contracts.py`

- [ ] **Step 1: Add failing production selection tests**

Add this test to `tests/unit/cli/repl/test_runtime_bridge.py`:

```python
@pytest.mark.asyncio
async def test_runtime_bridge_selects_textual_repl_when_backend_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import runtime_bridge

    calls: list[dict[str, Any]] = []

    async def fake_textual_repl(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(runtime_bridge._textual_bridge, "run_concurrent_repl", fake_textual_repl)

    await runtime_bridge.run_concurrent_repl(
        surface=Surface.CLI_GATEWAY,
        scope={},
        dispatch=lambda _value: asyncio.sleep(0, result=True),
        queue_max_size=8,
        env={"OPENSQUILLA_TUI_BACKEND": "textual"},
    )

    assert len(calls) == 1
    assert calls[0]["surface"] is Surface.CLI_GATEWAY
```

Add this test to `tests/unit/cli/repl/test_launch_bridge.py`:

```python
def test_launch_bridge_keeps_terminal_default_and_accepts_explicit_textual() -> None:
    from opensquilla.cli.repl import runtime_bridge

    assert runtime_bridge.validate_tui_backend_selection({}) == "terminal"
    assert (
        runtime_bridge.validate_tui_backend_selection({"OPENSQUILLA_TUI_BACKEND": "textual"})
        == "textual"
    )
```

- [ ] **Step 2: Run the production selection tests to prove they fail**

Run:

```bash
uv run pytest tests/unit/cli/repl/test_runtime_bridge.py::test_runtime_bridge_selects_textual_repl_when_backend_is_explicit tests/unit/cli/repl/test_launch_bridge.py::test_launch_bridge_keeps_terminal_default_and_accepts_explicit_textual -q
```

Expected: `test_runtime_bridge_selects_textual_repl_when_backend_is_explicit` fails until `textual_bridge` and bridge selection exist.

- [ ] **Step 3: Add the Textual bridge**

Create `src/opensquilla/cli/tui/adapters/textual_bridge.py`:

```python
"""Typed bridge from REPL runtimes to the live Textual TUI adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from opensquilla.cli.tui.textual.runtime import (
    ChatRuntimeScope,
    clear_current_cancel,
    get_tui_output,
    run_textual_chat_runtime,
)
from opensquilla.engine.commands import Surface


async def run_concurrent_repl(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Run live Textual chat without exposing concrete TUI adapters to chat_cmd."""
    await run_textual_chat_runtime(
        surface=surface,
        scope=scope,
        dispatch=dispatch,
        queue_max_size=queue_max_size,
        abort_active_turn=abort_active_turn,
    )


__all__ = [
    "ChatRuntimeScope",
    "clear_current_cancel",
    "get_tui_output",
    "run_concurrent_repl",
]
```

- [ ] **Step 4: Select the bridge in `runtime_bridge.py`**

Modify imports in `src/opensquilla/cli/tui/adapters/runtime_bridge.py`:

```python
import os

import opensquilla.cli.tui.adapters.terminal_bridge as _terminal_bridge
import opensquilla.cli.tui.adapters.textual_bridge as _textual_bridge
```

Change `validate_tui_backend_selection()` to keep the existing behavior and accept an explicit env mapping:

```python
def validate_tui_backend_selection(env: Mapping[str, str] | None = None) -> str:
    from opensquilla.cli.tui.renderers.selection import (
        select_renderer_backend_from_env,
    )

    return select_renderer_backend_from_env(env).backend_id
```

Add:

```python
def _selected_bridge(env: Mapping[str, str] | None = None) -> Any:
    backend_id = validate_tui_backend_selection(os.environ if env is None else env)
    if backend_id == "textual":
        return _textual_bridge
    return _terminal_bridge
```

Change `run_concurrent_repl()` signature and implementation:

```python
async def run_concurrent_repl(
    *,
    surface: Surface,
    scope: GatewayRuntimeScope | StandaloneRuntimeScope,
    dispatch: Callable[[str], Coroutine[Any, Any, bool]] | Callable[[str], Awaitable[bool]],
    abort_active_turn: Callable[[], Awaitable[None]] | None = None,
    queue_max_size: int | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    bridge = _selected_bridge(env)
    await bridge.run_concurrent_repl(
        surface=surface,
        scope=scope,
        dispatch=dispatch,
        queue_max_size=PENDING_QUEUE_MAX_SIZE
        if queue_max_size is None
        else queue_max_size,
        abort_active_turn=abort_active_turn,
    )
```

Keep `get_tui_output()` delegated to `_terminal_bridge.get_tui_output(scope)` only if both terminal and Textual write through the same `TuiOutputBinding`. If a test proves this is confusing, import `TuiOutputBinding` directly and implement:

```python
return TuiOutputBinding(scope).get()
```

- [ ] **Step 5: Export the bridge**

Add `"textual_bridge"` to `src/opensquilla/cli/tui/adapters/__init__.py` and `src/opensquilla/cli/tui/__init__.py`.

- [ ] **Step 6: Update package-boundary tests if needed**

If `tests/unit/cli/tui/test_contracts.py` fails because of a hard-coded module list, add `textual_bridge.py` to `TUI_TERMINAL_ADAPTER_MODULES` or rename the set in a minimal way that preserves the existing assertion intent:

```python
    "textual_bridge.py",
```

Do not add Textual modules to the backend core package list.

- [ ] **Step 7: Run production selection and adjacent tests**

Run:

```bash
uv run pytest tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py -q
uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/repl -q
```

Expected: all tests pass.

- [ ] **Step 8: Run lint/type checks for adapters**

Run:

```bash
uv run ruff check src/opensquilla/cli/tui/adapters src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py
uv run mypy src/opensquilla/cli/tui/adapters src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py
```

Expected: both commands pass.

- [ ] **Step 9: Commit production explicit selection**

Run:

```bash
git add src/opensquilla/cli/tui/adapters src/opensquilla/cli/tui/__init__.py tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py tests/unit/cli/tui/test_contracts.py
git commit -m "Select Textual chat only through explicit backend choice" \
  -m "Constraint: Textual must be production-launchable without becoming the default frontend." \
  -m "Rejected: Add a separate chat engine for Textual | gateway and standalone runtimes already depend on a frontend-neutral input loop." \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Directive: Keep terminal as the fallback when OPENSQUILLA_TUI_BACKEND is unset or empty." \
  -m "Tested: uv run pytest tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py -q; uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/repl -q; uv run ruff check src/opensquilla/cli/tui/adapters src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py; uv run mypy src/opensquilla/cli/tui/adapters src/opensquilla/cli/tui/textual tests/unit/cli/repl/test_runtime_bridge.py tests/unit/cli/repl/test_launch_bridge.py" \
  -m "Not-tested: Full acceptance matrix is the final checkpoint."
```

---

### Task 9: Final Acceptance Matrix and Review Fixes

**Files:**
- Modify only files needed by failures from the matrix.
- Do not broaden scope beyond live Textual TUI, harness parity, production explicit selection, docs, and cleanup.

- [ ] **Step 1: Scan for the removed skip text**

Run:

```bash
rg -n "live Textual TUI target is not implemented|missing-live-app|command=\\[\\]" tests/integration/cli/tui_real_terminal src/opensquilla/cli/tui
```

Expected: exit code `1` with no matches.

- [ ] **Step 2: Run the minimum acceptance matrix**

Run:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
uv run pytest tests/unit/cli/tui -q
uv run ruff check src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
uv run mypy src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
```

Expected: all commands pass.

- [ ] **Step 3: Run adjacent production chat/gateway tests because launch paths changed**

Run:

```bash
uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/repl -q
```

Expected: all tests pass.

- [ ] **Step 4: Run a read-only diff review**

Run:

```bash
git diff --check
git diff --stat HEAD
git diff -- src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal tests/unit/cli/repl tests/unit/cli/tui tests/test_cli/test_chat_cmd.py
```

Expected: `git diff --check` passes. Diff shows only planned live Textual, harness, production selection, and focused test changes.

- [ ] **Step 5: Request code review from a native subagent**

Dispatch a `code-reviewer` subagent with this scope:

```text
Review the live Textual TUI implementation on /workspace/opensquilla. Focus on: no second chat runtime, TextualReplayRenderer separation, terminal default preserved, harness skip removed, production Textual selected only explicitly, and acceptance matrix adequacy. Do not edit files. Return findings with file/line references.
```

Expected: reviewer returns no blocking findings, or returns concrete fixes.

- [ ] **Step 6: Fix review findings and rerun impacted checks**

For every blocking finding, make the smallest aligned change and rerun the specific failing or impacted command from Step 2 or Step 3.

Expected: no blocking findings remain.

- [ ] **Step 7: Commit final cleanup if there are remaining uncommitted fixes**

Run:

```bash
git add src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal tests/unit/cli/repl tests/unit/cli/tui tests/test_cli/test_chat_cmd.py
git commit -m "Finish live Textual TUI verification fixes" \
  -m "Constraint: Completion requires the requested real-terminal and production-selection matrix to be green." \
  -m "Rejected: Claim completion from narrow unit tests | live Textual acceptance depends on the real-terminal harness." \
  -m "Confidence: high" \
  -m "Scope-risk: moderate" \
  -m "Directive: Treat future Textual regressions as harness failures, not capability skips." \
  -m "Tested: uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q; uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal; uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual; uv run pytest tests/unit/cli/tui -q; uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/repl -q; uv run ruff check src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal; uv run mypy src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal" \
  -m "Not-tested: None for the requested acceptance matrix."
```

Expected: final implementation commit exists only if Step 6 changed files after the previous checkpoint.

---

## Final Verification Checklist

Run these commands after the last code commit:

```bash
uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py -q
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend terminal
uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend textual
uv run pytest tests/unit/cli/tui -q
uv run pytest tests/test_cli/test_chat_cmd.py tests/unit/cli/repl -q
uv run ruff check src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
uv run mypy src/opensquilla/cli/tui tests/integration/cli/tui_real_terminal
rg -n "live Textual TUI target is not implemented|missing-live-app|command=\\[\\]" tests/integration/cli/tui_real_terminal src/opensquilla/cli/tui
git status --short --branch
```

Expected:

- All pytest, ruff, and mypy commands pass.
- The skip-text scan has no matches and exits `1`.
- Git status is clean on the implementation branch after the final commit.

## Self-Review

### Spec Coverage

- Real live `textual.app.App`: Task 3 creates `TextualChatApp`; Task 6 launches it through the harness.
- Shared runtime, no second chat engine: Task 5 composes Textual with `run_tui_runtime()`.
- Textual surface adapter contracts: Tasks 2 and 3 test and implement `TuiSurface` and `TuiOutputHandle`.
- Headless replay separation: Tasks 3 and 5 create `src/opensquilla/cli/tui/textual/*` and do not modify `TextualReplayRenderer` into a live app.
- Harness unavailable skip removal: Task 6 replaces the `available=False` target and scans for the old skip text in Task 9.
- Deterministic scenario parity: Task 7 runs and fixes the full real-terminal Textual suite, then re-runs terminal parity.
- Production explicit selection: Task 8 routes `OPENSQUILLA_TUI_BACKEND=textual` to the Textual bridge and keeps terminal as default.
- Acceptance matrix: Task 9 names and runs every required command, plus adjacent chat tests because launch paths change.

### Placeholder Scan Result

The plan uses concrete file paths, command lines, expected outcomes, and code shapes for every implementation task. No deferred implementation markers or vague edge-action phrases remain in the task steps.

### Type And Interface Consistency

- `TextualSurface` implements the existing `TuiSurface` methods: `next_line()`, `set_cancel_callback()`, `set_shutdown_callback()`, `emit_eof()`, `write_through()`, and `redraw_callback`.
- `TextualOutputHandle` implements the existing `TuiOutputHandle` methods and adds optional `set_toolbar()` and `invalidate()` methods used by `TuiPluginOutputHandle`.
- `run_textual_chat_runtime()` mirrors `run_terminal_chat_runtime()` and accepts `surface`, `scope`, `dispatch`, `queue_max_size`, and optional `abort_active_turn`.
- Production bridge selection stays in `runtime_bridge.py`, so `chat_cmd.py`, `chat` Typer options, gateway runtime, and standalone runtime remain frontend-neutral.
