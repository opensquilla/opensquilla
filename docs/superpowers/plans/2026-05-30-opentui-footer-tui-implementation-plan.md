# OpenTUI Footer TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a selectable OpenTUI footer backend that keeps transcript output in terminal scrollback and renders a clean composer plus compact lower-right Router plugin.

**Architecture:** Python remains the chat/runtime owner. A Node/OpenTUI host owns only the split-footer safe area and communicates with Python over typed JSON lines using extra file descriptors so OpenTUI can keep stdin/stdout attached to the terminal. Transcript payloads are sent to the host as scrollback writes so the footer and transcript have one terminal owner.

**Tech Stack:** Python 3.12, asyncio, pytest, OpenTUI `@opentui/core@0.3.0`, Node ESM, tmux real-terminal harness.

---

## File Structure

- Create `src/opensquilla/cli/tui/opentui/messages.py`: typed Python message builders/parsers for Python-to-host and host-to-Python JSON lines.
- Create `src/opensquilla/cli/tui/opentui/bridge.py`: OpenTUI host process resolver, subprocess lifecycle, fd-based IPC reader/writer, and startup availability errors.
- Create `src/opensquilla/cli/tui/opentui/surface.py`: `TuiSurface` and `TuiOutputHandle` adapters backed by the bridge.
- Create `src/opensquilla/cli/tui/opentui/runtime.py`: shared-runtime adapter matching the terminal/textual runtime shape.
- Create `src/opensquilla/cli/tui/opentui/package/package.json`: local OpenTUI host package metadata and npm scripts.
- Create `src/opensquilla/cli/tui/opentui/package/src/main.mjs`: OpenTUI split-footer host.
- Create `src/opensquilla/cli/tui/adapters/opentui_bridge.py`: chat command bridge wrapper.
- Modify `src/opensquilla/cli/tui/adapters/runtime_bridge.py`: route `OPENSQUILLA_TUI_BACKEND=opentui`.
- Modify `src/opensquilla/cli/tui/renderers/selection.py`: register backend id `opentui`.
- Modify `tests/integration/cli/tui_real_terminal/targets.py`: add `opentui` fake target.
- Modify `tests/integration/cli/tui_real_terminal/conftest.py`: accept `--tui-backend=opentui`.
- Create `tests/integration/cli/tui_real_terminal/fake_opentui_app.py`: deterministic fake runtime launcher.
- Create `tests/unit/cli/tui/test_opentui_messages.py`: message contract tests.
- Create `tests/unit/cli/tui/test_opentui_bridge.py`: bridge lifecycle and clear missing-dependency tests.
- Create `tests/unit/cli/tui/test_opentui_surface.py`: surface/output-handle tests with a fake bridge.
- Modify `tests/unit/cli/tui/test_renderer_backend_contract.py`: backend registry tests.
- Modify `tests/integration/cli/tui_real_terminal/test_targets.py`: OpenTUI target construction tests.

## Task 1: Message Contracts

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/messages.py`
- Create: `src/opensquilla/cli/tui/opentui/__init__.py`
- Test: `tests/unit/cli/tui/test_opentui_messages.py`

- [ ] **Step 1: Write failing tests**

```python
from opensquilla.cli.tui.opentui.messages import (
    HostInputSubmit,
    HostReady,
    HostToPythonMessageError,
    RouterPluginState,
    host_message_from_json,
    python_message_to_json,
)


def test_python_message_to_json_serializes_router_update() -> None:
    payload = python_message_to_json(
        "router.update",
        RouterPluginState(
            model="gpt-5.5",
            route="T3 · 91%",
            saving="42% · -$0.021",
            context="128k · 37%",
            style="normal",
        ),
    )
    assert payload.endswith("\n")
    assert '"type":"router.update"' in payload
    assert '"model":"gpt-5.5"' in payload


def test_host_message_from_json_parses_ready_and_submit() -> None:
    assert host_message_from_json('{"type":"ready"}') == HostReady()
    assert host_message_from_json(
        '{"type":"input.submit","text":"中文 prompt"}'
    ) == HostInputSubmit(text="中文 prompt")


def test_host_message_rejects_malformed_control_payloads() -> None:
    try:
        host_message_from_json('{"type":"input.submit"}')
    except HostToPythonMessageError as exc:
        assert "input.submit.text" in str(exc)
    else:
        raise AssertionError("expected HostToPythonMessageError")
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_messages.py -q`
Expected: FAIL because `opensquilla.cli.tui.opentui.messages` does not exist.

- [ ] **Step 3: Implement message contracts**

Implement dataclasses for `RouterPluginState`, `ComposerState`, `TurnStatusState`, `HostReady`, `HostInputSubmit`, `HostInputCancel`, `HostInputEof`, `HostResize`, `HostError`, plus `python_message_to_json()` and `host_message_from_json()`.

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_messages.py -q`
Expected: PASS.

## Task 2: Backend Registry And Availability

**Files:**
- Modify: `src/opensquilla/cli/tui/renderers/selection.py`
- Create: `src/opensquilla/cli/tui/opentui/bridge.py`
- Test: `tests/unit/cli/tui/test_renderer_backend_contract.py`
- Test: `tests/unit/cli/tui/test_opentui_bridge.py`

- [ ] **Step 1: Write failing tests**

Add assertions that `get_renderer_backend("opentui")` returns a backend with `backend_id == "opentui"`, `supports_structured_ui is True`, and `supports_streaming_fast_path is True`. Add a bridge test that missing `node_modules/@opentui/core` reports a clear install command.

- [ ] **Step 2: Run targeted tests and verify they fail**

Run: `uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py tests/unit/cli/tui/test_opentui_bridge.py -q`
Expected: FAIL because `opentui` is not registered.

- [ ] **Step 3: Implement backend registration**

Add `OpenTuiRendererBackend` that checks for `node` plus the local package dependency directory. Register it in `renderer_backends()` without importing OpenTUI at module import time.

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py tests/unit/cli/tui/test_opentui_bridge.py -q`
Expected: PASS.

## Task 3: OpenTUI Host Package

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/package.json`
- Create: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_bridge.py`

- [ ] **Step 1: Write host package metadata**

Create a local package with `"type": "module"`, script `"start": "node src/main.mjs"`, and dependencies on `@opentui/core@0.3.0`.

- [ ] **Step 2: Write host smoke behavior**

Implement `main.mjs` so it:

- reads IPC from fd 3 and writes IPC to fd 4;
- creates `createCliRenderer({ screenMode: "split-footer", footerHeight: 5, externalOutputMode: "passthrough", exitOnCtrlC: false })`;
- renders a bordered composer and compact lower-right Router card;
- emits `{"type":"ready"}`;
- emits `input.submit`, `input.cancel`, and `input.eof` messages for Enter, Ctrl+C, and Ctrl+D;
- handles `router.update`, `composer.set`, `turn.status`, `scrollback.write`, and `shutdown` messages;
- calls `renderer.writeToScrollback()` for transcript payloads.

- [ ] **Step 3: Install local host dependencies**

Run: `npm install --prefix src/opensquilla/cli/tui/opentui/package`
Expected: package dependencies install successfully and `package-lock.json` is created.

- [ ] **Step 4: Run a non-interactive host smoke**

Run: `node src/opensquilla/cli/tui/opentui/package/src/main.mjs --help`
Expected: exits 0 and prints a short usage line without touching terminal modes.

## Task 4: Python Bridge And Surface

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/bridge.py`
- Create: `src/opensquilla/cli/tui/opentui/surface.py`
- Test: `tests/unit/cli/tui/test_opentui_bridge.py`
- Test: `tests/unit/cli/tui/test_opentui_surface.py`

- [ ] **Step 1: Write failing bridge/surface tests**

Use a fake bridge object with async queues. Assert `OpenTuiSurface.next_line()` returns submitted text, EOF returns `None`, `OpenTuiOutputHandle.write_through()` sends `scrollback.write`, and `set_toolbar("router_hud", "...")` sends a compact `router.update`.

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_bridge.py tests/unit/cli/tui/test_opentui_surface.py -q`
Expected: FAIL because bridge/surface do not exist.

- [ ] **Step 3: Implement bridge and surface**

Implement `OpenTuiBridge.start()`, `OpenTuiBridge.send()`, `OpenTuiBridge.next_message()`, `OpenTuiBridge.close()`, `OpenTuiSurface`, `OpenTuiOutputHandle`, and `open_opentui_surface()`.

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_bridge.py tests/unit/cli/tui/test_opentui_surface.py -q`
Expected: PASS.

## Task 5: Runtime Adapter And Fake Target

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/runtime.py`
- Create: `src/opensquilla/cli/tui/adapters/opentui_bridge.py`
- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Create: `tests/integration/cli/tui_real_terminal/fake_opentui_app.py`
- Modify: `tests/integration/cli/tui_real_terminal/targets.py`
- Modify: `tests/integration/cli/tui_real_terminal/conftest.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_targets.py`

- [ ] **Step 1: Write failing target and runtime-selection tests**

Assert `build_tui_target("opentui", context)` returns a command ending in `fake_opentui_app.py`, env `OPENSQUILLA_TUI_BACKEND=opentui`, log `opentui-app.log`, and capability `opentui-footer`.

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py tests/test_cli/test_chat_cmd.py::TestChatCommand::test_chat_rejects_unknown_tui_backend_before_launch -q`
Expected: FAIL because target and backend are unknown.

- [ ] **Step 3: Implement runtime adapter**

Mirror `textual/runtime.py` and `adapters/textual_bridge.py`, but use `open_opentui_surface()` and route notices through the OpenTUI output handle.

- [ ] **Step 4: Implement fake target**

Mirror `fake_textual_app.py` and call `run_opentui_chat_runtime()`. Keep the same deterministic scenarios.

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/integration/cli/tui_real_terminal/test_targets.py tests/test_cli/test_chat_cmd.py::TestChatCommand::test_chat_rejects_unknown_tui_backend_before_launch -q`
Expected: PASS.

## Task 6: Real-Terminal Evidence And Stream Polish

**Files:**
- Modify: `src/opensquilla/cli/tui/terminal/stream.py`
- Modify: `tests/test_cli/test_tool_call_strip.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_complex_ui_state.py`
- Modify: `tests/integration/cli/tui_real_terminal/test_terminal_changes.py`

- [ ] **Step 1: Add assertions for compact tool spacing and final contrast**

Update existing tests so tool call rows do not contain repeated blank-line gaps and final output is not classified/rendered as dim detail.

- [ ] **Step 2: Run tests and verify current failures**

Run: `uv run pytest tests/test_cli/test_tool_call_strip.py tests/integration/cli/tui_real_terminal/test_complex_ui_state.py -q --tui-backend opentui`
Expected: FAIL until OpenTUI target and stream polish are complete.

- [ ] **Step 3: Tighten stream spacing**

Remove redundant fresh-line insertion where tool start/finish already begins on a clean line. Keep one readable boundary before a new tool run.

- [ ] **Step 4: Run real-terminal OpenTUI target**

Run: `uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend opentui`
Expected: PASS or a single documented OpenTUI dependency/setup blocker. Captured scrollback must include submitted prompt, tool output text, final answer text, and no transcript viewport artifacts.

## Final Verification

- [ ] Run: `uv run pytest tests/unit/cli/tui/test_opentui_messages.py tests/unit/cli/tui/test_opentui_bridge.py tests/unit/cli/tui/test_opentui_surface.py -q`
- [ ] Run: `uv run pytest tests/unit/cli/tui/test_renderer_backend_contract.py tests/integration/cli/tui_real_terminal/test_targets.py -q`
- [ ] Run: `uv run pytest tests/integration/cli/tui_real_terminal -q --tui-backend opentui`
- [ ] Run: `uv run ruff check src/opensquilla/cli/tui tests/unit/cli/tui tests/integration/cli/tui_real_terminal`
- [ ] Run: `uv run mypy src/opensquilla/cli/tui --show-error-codes`

## Self Review

- Spec coverage: all visual, architecture, IPC, error handling, replay, and real-terminal gates map to tasks.
- Placeholder scan: no TBD/TODO placeholders are present.
- Type consistency: Python message names match the spec and host message names.
- Scope risk: first implementation proves OpenTUI footer reservation before changing the default backend.
