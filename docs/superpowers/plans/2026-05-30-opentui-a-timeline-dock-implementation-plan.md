# OpenTUI A Timeline Dock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved `daily` OpenTUI A Timeline Dock visual baseline in the production terminal UI.

**Architecture:** Keep OpenTUI in split-footer mode so terminal scrollback remains shell-native. Apply the approved visual system in the JS footer host: compact composer on the left, compact router plugin on the lower right, and append-only semantic timeline decoration for prompt, router status, tool call, tool detail, assistant answer, and usage lines. Use borders, rails, and line structure for separation; do not use background fills.

**Tech Stack:** Python runtime hooks, OpenTUI/Bun JS host, pytest unit/static tests, tmux real-terminal harness.

---

### File Structure

- Modify `src/opensquilla/cli/tui/opentui/package/src/main.mjs`: add the approved daily theme tokens, semantic scrollback decoration, tuned composer/router chrome, and active/done status glyphs.
- Modify `src/opensquilla/cli/tui/opentui/runtime.py`: make user echo and queued-turn markers match the A timeline prompt card language.
- Modify `tests/unit/cli/tui/test_opentui_host_layout.py`: lock the daily preset tokens and timeline classifier contract.
- Modify `tests/unit/cli/repl/test_opentui_chat_adapter.py`: lock footer-native prompt echo without `你 / you`.
- Modify `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py`: require tmux-rendered OpenTUI output to show distinct prompt/tool/detail/final markers.

### Task 1: Lock The Approved Daily Visual Contract

**Files:**
- Modify: `tests/unit/cli/tui/test_opentui_host_layout.py`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: Write the failing test**

Add assertions that `main.mjs` exposes:

```python
assert "OPENTUI_DAILY_THEME" in source
assert 'preset: "daily"' in source
assert 'frame: "card"' in source
assert 'detailMode: "inline"' in source
assert 'answerMode: "panel"' in source
assert "#77B7FF" in source
assert "decorateDailyTimelineScrollback" in source
assert "classifyDailyTimelineLine" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`

Expected: FAIL because `OPENTUI_DAILY_THEME` and daily timeline helpers are not implemented yet.

- [ ] **Step 3: Implement the daily theme and footer chrome**

Add the theme object and switch composer/router colors to its tokens. Keep `screenMode: "split-footer"` and `shouldFill: false`; do not set `backgroundColor` on any OpenTUI node.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`

Expected: PASS.

### Task 2: Lock Prompt Echo As A Timeline Card

**Files:**
- Modify: `tests/unit/cli/repl/test_opentui_chat_adapter.py`
- Modify: `src/opensquilla/cli/tui/opentui/runtime.py`

- [ ] **Step 1: Write the failing test**

Extend `test_opentui_chat_runtime_uses_footer_native_echo_hooks`:

```python
assert "╭─ prompt" in joined_writes
assert "╭─ squilla" in joined_writes
assert "│ hello opentui" in joined_writes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cli/repl/test_opentui_chat_adapter.py::test_opentui_chat_runtime_uses_footer_native_echo_hooks -q`

Expected: FAIL because prompt echo currently writes a bare `›` marker.

- [ ] **Step 3: Implement prompt and queue cards**

Change `echo_opentui_user_input()` to write `╭─ prompt`, `│ <text>`, `╰`, and change queued-turn echo to `╭─ squilla`, `│ running queued input`, `╰`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/cli/repl/test_opentui_chat_adapter.py::test_opentui_chat_runtime_uses_footer_native_echo_hooks -q`

Expected: PASS.

### Task 3: Lock tmux Rendering For Tool/Detail/Final Separation

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py`
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`

- [ ] **Step 1: Write the failing test**

Inside the OpenTUI branch, assert the rendered tmux transcript includes distinct timeline markers:

```python
assert "╭─ prompt" in rendered_output
assert "╭─ tool" in rendered_output
assert "│ detail" in rendered_output
assert "╭─ answer" in rendered_output
assert "╰─ usage" in rendered_output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/cli/tui_real_terminal/test_architecture_prompt.py::test_architecture_prompt_renders_tools_and_chinese_output --tui-backend=opentui --tui-driver=tmux -q`

Expected: FAIL because OpenTUI currently writes plain scrollback text without semantic timeline decoration.

- [ ] **Step 3: Implement semantic scrollback decoration**

Decorate stripped scrollback lines before wrapping:

```javascript
function classifyDailyTimelineLine(line) {
  if (/^╭─ prompt|^│ .*|^╰$/u.test(line)) return "prompt";
  if (/^▸ |^✓ |^✗ /u.test(line)) return "tool";
  if (/^tool_output\b|^│\s*(stdout|stderr|omitted|router\.)/u.test(line)) return "detail";
  if (/^◢ /u.test(line)) return "answer";
  if (/^· .*tokens|^turn cancelled/u.test(line)) return "usage";
  return "body";
}
```

Keep raw detail visible but lower contrast by prefixing with `│ detail`, while tool title/result and final answer get their own `╭─ tool` / `╭─ answer` boundaries.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/cli/tui_real_terminal/test_architecture_prompt.py::test_architecture_prompt_renders_tools_and_chinese_output --tui-backend=opentui --tui-driver=tmux -q`

Expected: PASS with artifact files under `.artifacts/tui-real-terminal/runs`.

### Task 4: Verification Bundle

**Files:**
- No additional production files.

- [ ] **Step 1: Run unit and static layout checks**

Run:

```bash
uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py tests/unit/cli/repl/test_opentui_chat_adapter.py tests/unit/cli/tui/test_opentui_surface.py tests/unit/cli/tui/test_opentui_messages.py -q
```

Expected: PASS.

- [ ] **Step 2: Run JS host smoke**

Run:

```bash
npm run --prefix src/opensquilla/cli/tui/opentui/package smoke
```

Expected: PASS and prints the OpenTUI footer host help.

- [ ] **Step 3: Run tmux render-only lab**

Run:

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario architecture_prompt --backend opentui --driver tmux
```

Expected: `pass: <artifact-dir>`.

- [ ] **Step 4: Run lint on changed Python files**

Run:

```bash
uv run ruff check src/opensquilla/cli/tui/opentui/runtime.py tests/unit/cli/repl/test_opentui_chat_adapter.py tests/unit/cli/tui/test_opentui_host_layout.py tests/integration/cli/tui_real_terminal/test_architecture_prompt.py
```

Expected: PASS.

### Self-Review

- Spec coverage: daily recommended default, shell-native scrollback, rounded composer/router plugin, tool/detail/final separation, compact router plugin, tmux/cache validation.
- Visual constraint coverage: all separation is through frames, rails, line prefixes, and text/border colors; no background-color fills are used.
- Placeholder scan: no TBD/TODO/placeholders.
- Type consistency: only string payload and static JS contract changes; no protocol message schema change.
