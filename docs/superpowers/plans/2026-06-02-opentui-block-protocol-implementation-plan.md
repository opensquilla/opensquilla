# OpenTUI Semantic Block Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the OpenTUI TUI's optimistic-render + ad-hoc-patch model with a semantic Block protocol (Python defines meaning) and a declarative, modular host renderer (host defines presentation), so visual/grouping/streaming bugs are designed out rather than patched.

**Architecture:** Python `OpenTuiStreamRenderer` emits `block.begin/append/update/end/retype` messages carrying a semantic `kind` (prompt/thinking/tool/answer/usage/error). The JS host routes each block by `kind` to an isolated Renderer module; all Renderers draw through one shared style/primitives layer; `TurnView` is a pure container. See spec: `docs/superpowers/specs/2026-06-02-opentui-block-protocol-architecture-design.md`.

**Tech Stack:** Python 3.12 (dataclasses, asyncio), Bun + @opentui/core (ES modules), pytest, node --check.

**Conventions (project-specific, do NOT skip):**
- All `uv`/pytest commands MUST be prefixed `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache` (the `~/.cache/uv` path fails under sandbox). When a command is blocked by sandbox, the executor reruns it with sandbox disabled — do not stop to ask.
- Real-terminal runs need network; rerun with sandbox disabled.
- Commit messages: plain conventional-commit single line, NO co-author/Lore trailers.
- Host JS lives at `src/opensquilla/cli/tui/opentui/package/src/`. Python lives at `src/opensquilla/cli/tui/opentui/`.

**Migration note:** Baseline (optimistic+demote) committed at `50a197af`. This plan replaces that model. Old messages (`answer.text`/`answer.demote`/`model.text`/`tool.call`/`tool.detail`) are removed once the block protocol is wired end-to-end (Task 12). Keep tests green at every task.

---

## File Structure

**Python (protocol + state machine):**
- `src/opensquilla/cli/tui/opentui/messages.py` — add block dataclasses + JSON helpers (modify).
- `src/opensquilla/cli/tui/opentui/renderer.py` — rewrite `OpenTuiStreamRenderer` as a block state machine (modify).

**JS host (split monolithic main.mjs into focused modules under `package/src/`):**
- `theme.mjs` — colour constants (single source of truth).
- `primitives.mjs` — `cellWidth`, `textWidth`, `clipToCells`, `stripTerminalControls`, `railLine`, `cardTop`, `cardBottom`, `timelineAvailCells`, `TOOL_INDENT`, `CARD_RULE_LONG/SHORT`.
- `blocks/promptBlock.mjs`, `thinkingBlock.mjs`, `toolBlock.mjs`, `answerBlock.mjs`, `usageBlock.mjs`, `errorBlock.mjs` — one Renderer per kind. Uniform interface.
- `blockRegistry.mjs` — `kind → Renderer factory` map.
- `turnView.mjs` — pure container: holds `Map<blockId, Renderer>`, routes begin/append/update/end/retype; owns the turn's OpenTUI box in the ScrollBox.
- `composer.mjs` — input region (caret/history/keys/wheel), extracted.
- `ipc.mjs` — fd read/write + message parse/dispatch.
- `main.mjs` — thin entry: createCliRenderer, buildLayout, wire ipc→turnView, install keyboard.

**Tests:**
- `tests/unit/cli/tui/test_opentui_messages.py` — block message serialization (modify).
- `tests/unit/cli/tui/test_opentui_renderer.py` — state-machine → block message sequences (rewrite).
- `tests/unit/cli/tui/test_opentui_host_layout.py` — host module structure assertions (rewrite for modules).
- Host module smoke: a bun test driving real OpenTUI testing renderer is OUT (markdown headless unreliable, established earlier). Host verification is via `node --check`, structure asserts, and real-terminal frames.

---

## Block Protocol Reference (authoritative for all tasks)

Message envelope: `{"type": "block.<action>", ...fields}` one JSON object per line.

| action | fields | meaning |
|--------|--------|---------|
| `block.begin` | `id: str`, `kind: str`, `meta: dict` | open a block. meta is kind-specific (below). |
| `block.append` | `id: str`, `delta: str` | stream text into the block (thinking/answer) or add an output line (tool). |
| `block.update` | `id: str`, `patch: dict` | in-place state change (tool: `{status, summary}`). |
| `block.retype` | `id: str`, `kind: str` | reclassify an open block (answer→thinking when a tool starts). |
| `block.end` | `id: str` | finalize (answer: stop streaming + bottom border; tool: mark done). |

`meta` by kind:
- `prompt`: `{text: str}` (full text, emitted in begin; no append).
- `thinking`: `{}` (content via append).
- `tool`: `{name: str, args: str}`.
- `answer`: `{}` (content via append).
- `usage`: `{text: str}` (full, in begin).
- `error`: `{text: str}`.

Retained turn-level messages (unchanged): `turn.begin {id}`, `turn.end {id, cancelled}`, `turn.status {phase,label,active}`, `composer.set {...}`, `router.update {...}`.

Python state machine rules (the core of the design):
- A text segment opens lazily on first `aappend_text` as an `answer` block (`block.begin kind=answer` + `block.append`). Host renders cyan card streaming.
- On `atool_start`, if a text segment is open: emit `block.retype {id, kind:thinking}` then `block.end {id}` for it (now a purple ✱ block), then open the tool block.
- On `afinalize`, if a text segment is open: emit `block.end {id}` (it stays `answer`, the cyan card).
- Tool: `atool_start` → `block.begin kind=tool` + (status running via meta); `atool_finished` → `block.append` for each detail line + `block.update {status}` + `block.end`.
- `astatus` (router/status text) → currently `model.text`; map to a `thinking` block OR keep as a transient status line. DECISION: emit as its own short-lived `thinking` block is wrong (it's not model output). Keep `astatus` mapping to `turn.status` label only (no content block) to avoid noise — it already drives the status pill. If astatus carries router reasoning that must show in timeline, emit a `thinking` block; default: no content block (matches current model.text being minor).
- `aerror` → `block.begin kind=error` + end.

---

## Task 1: Block message dataclasses

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/messages.py`
- Test: `tests/unit/cli/tui/test_opentui_messages.py`

- [ ] **Step 1: Write failing test** — append to `test_opentui_messages.py`:

```python
def test_block_messages_serialize_with_kind_and_fields() -> None:
    from opensquilla.cli.tui.opentui.messages import (
        BlockBegin, BlockAppend, BlockUpdate, BlockRetype, BlockEnd,
        python_message_to_json,
    )
    begin = python_message_to_json("block.begin", BlockBegin(id="b1", kind="tool", meta={"name": "ls", "args": "src"}))
    assert '"type":"block.begin"' in begin
    assert '"kind":"tool"' in begin
    assert '"name":"ls"' in begin
    append = python_message_to_json("block.append", BlockAppend(id="b1", delta="line"))
    assert '"delta":"line"' in append
    update = python_message_to_json("block.update", BlockUpdate(id="b1", patch={"status": "ok"}))
    assert '"status":"ok"' in update
    retype = python_message_to_json("block.retype", BlockRetype(id="b1", kind="thinking"))
    assert '"kind":"thinking"' in retype
    end = python_message_to_json("block.end", BlockEnd(id="b1"))
    assert '"type":"block.end"' in end
```

- [ ] **Step 2: Run, verify fail**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_messages.py::test_block_messages_serialize_with_kind_and_fields -v`
Expected: FAIL ImportError (BlockBegin not defined).

- [ ] **Step 3: Add dataclasses** in `messages.py` after the `ToolDetail` dataclass:

```python
@dataclass(frozen=True)
class BlockBegin:
    id: str
    kind: str
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class BlockAppend:
    id: str
    delta: str


@dataclass(frozen=True)
class BlockUpdate:
    id: str
    patch: dict[str, Any]


@dataclass(frozen=True)
class BlockRetype:
    id: str
    kind: str


@dataclass(frozen=True)
class BlockEnd:
    id: str
```

- [ ] **Step 4: Run, verify pass**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_messages.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/messages.py tests/unit/cli/tui/test_opentui_messages.py
git commit -m "feat: add block protocol message dataclasses"
```

---

## Task 2: Python renderer emits block protocol (state machine rewrite)

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/renderer.py`
- Test: `tests/unit/cli/tui/test_opentui_renderer.py` (rewrite assertions for block messages)

This is the design's core. The renderer keeps a per-turn block-id counter and tracks one optional open text segment.

- [ ] **Step 1: Write failing tests** — replace the two lifecycle tests in `test_opentui_renderer.py` with block-protocol assertions:

```python
@pytest.mark.asyncio
async def test_text_then_tool_becomes_thinking_block() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("Let me check")
    await r.atool_start("web_search", {"query": "x"}, "c1")
    await r.atool_finished("c1", success=True, result="result line")
    await r.aappend_text("Final answer")
    await r.afinalize(None)
    # The first text segment retyped to thinking when the tool started:
    retypes = [p for t, p in handle.sent if t == "block.retype"]
    assert retypes and retypes[0]["kind"] == "thinking"
    # A tool block exists:
    tool_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "tool"]
    assert tool_begins and tool_begins[0]["meta"]["name"] == "web_search"
    # The final text segment stays an answer block (no retype after it):
    answer_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"]
    assert len(answer_begins) >= 1
    ends = [t for t, _ in handle.sent if t == "block.end"]
    assert ends  # everything closed


@pytest.mark.asyncio
async def test_answer_only_turn_has_no_retype() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("Direct answer")
    await r.afinalize(None)
    assert not [t for t, _ in handle.sent if t == "block.retype"]
    answer_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"]
    assert len(answer_begins) == 1
```

- [ ] **Step 2: Run, verify fail**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -k "thinking or retype" -v`
Expected: FAIL (renderer still emits answer.text/answer.demote).

- [ ] **Step 3: Rewrite renderer.py** — replace the text/tool/error methods. Full new bodies:

```python
# add to imports
from opensquilla.cli.tui.opentui.messages import (
    BlockBegin, BlockAppend, BlockUpdate, BlockRetype, BlockEnd,
    TurnBegin, TurnEnd, TurnStatusState, Usage,
)
# remove AnswerText, AnswerDemote, ModelText, ToolCall, ToolDetail imports

# in __init__ replace _answer_segment_open / _tool_calls block tracking:
        self._block_seq = 0
        self._open_text_id: str | None = None  # current answer-candidate text block

    def _next_block_id(self) -> str:
        self._block_seq += 1
        return f"{self._turn_id}-b{self._block_seq}"

    async def aappend_text(self, delta: str) -> None:
        if not delta:
            return
        await self._ensure_begin()
        if not self._saw_output:
            self._saw_output = True
            await self._emit("turn.status", TurnStatusState(phase="output", label="output", active=True))
        if self._open_text_id is None:
            self._open_text_id = self._next_block_id()
            await self._emit("block.begin", BlockBegin(id=self._open_text_id, kind="answer", meta={}))
        await self._emit("block.append", BlockAppend(id=self._open_text_id, delta=delta))

    async def _close_text_as(self, kind: str) -> None:
        if self._open_text_id is None:
            return
        block_id = self._open_text_id
        self._open_text_id = None
        if kind == "thinking":
            await self._emit("block.retype", BlockRetype(id=block_id, kind="thinking"))
        await self._emit("block.end", BlockEnd(id=block_id))

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        await self._ensure_begin()
        # Router/status text drives the status pill; not a timeline content block.
        return None

    async def atool_start(self, name, args=None, tool_use_id=None) -> None:
        await self._ensure_begin()
        await self._close_text_as("thinking")
        summary = _summarize_args(name, args)
        block_id = tool_use_id or self._next_block_id()
        self._tool_block_ids[tool_use_id or ""] = block_id
        await self._emit("turn.status", TurnStatusState(phase="tool", label=name, active=True))
        await self._emit("block.begin", BlockBegin(id=block_id, kind="tool", meta={"name": name, "args": summary}))

    async def atool_finished(self, tool_use_id, *, success, elapsed=None, error=None, result=None) -> None:
        block_id = self._tool_block_ids.get(tool_use_id or "")
        if block_id is None:
            block_id = self._next_block_id()
            await self._emit("block.begin", BlockBegin(id=block_id, kind="tool", meta={"name": "", "args": ""}))
        detail = _summarize_result(error) if (not success and error) else _summarize_result(result)
        if detail:
            for line in detail.split("\n"):
                await self._emit("block.append", BlockAppend(id=block_id, delta=line))
        await self._emit("block.update", BlockUpdate(id=block_id, patch={"status": "ok" if success else "error"}))
        await self._emit("block.end", BlockEnd(id=block_id))

    async def aerror(self, message: str) -> None:
        await self._ensure_begin()
        block_id = self._next_block_id()
        await self._emit("block.begin", BlockBegin(id=block_id, kind="error", meta={"text": message}))
        await self._emit("block.end", BlockEnd(id=block_id))

    async def afinalize(self, usage=None, *, cancelled=False) -> None:
        await self._ensure_begin()
        await self._close_text_as("answer")  # stays answer card
        await self._emit("turn.end", TurnEnd(id=self._turn_id, cancelled=cancelled))
        block_id = self._next_block_id()
        await self._emit("block.begin", BlockBegin(id=block_id, kind="usage", meta={"text": _format_usage(usage)}))
        await self._emit("block.end", BlockEnd(id=block_id))
        await self._emit("turn.status", TurnStatusState(phase="idle", label="ready", active=False))
        await self._emit_raw("composer.set", {"disabled": False})
```

Also add `self._tool_block_ids: dict[str, str] = {}` in `__init__`, and remove the old `_demote_answer_segment`, `buffer`/`_answer_segment_open` usages no longer needed (keep `self.buffer` accumulation if other code reads it; grep first).

- [ ] **Step 4: Run, verify pass**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -v`
Expected: PASS. Fix any other tests in that file referencing old messages by updating them to block assertions.

- [ ] **Step 5: ruff + commit**

```bash
UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run ruff check src/opensquilla/cli/tui/opentui/ tests/
git add src/opensquilla/cli/tui/opentui/renderer.py tests/unit/cli/tui/test_opentui_renderer.py
git commit -m "feat: rewrite opentui renderer as block protocol state machine"
```

---

## Task 3: Host theme + primitives modules

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/theme.mjs`
- Create: `src/opensquilla/cli/tui/opentui/package/src/primitives.mjs`

- [ ] **Step 1: Create theme.mjs** — move the OPENTUI_DAILY_THEME object out of main.mjs verbatim and export it:

```javascript
export const THEME = Object.freeze({
  preset: "daily", frameStyle: "card", detailMode: "inline", answerMode: "panel", motion: "pulse",
  text: "#F4F7FB", muted: "#667385", faint: "#3E4A57", frame: "#5a6b7a",
  composerBorder: "#77B7FF", composerDisabledBorder: "#354453",
  routerNormal: "#73D0A7", routerWarning: "#F6C177", routerError: "#FF7B8A",
  toolAccent: "#69D2E7", detailText: "#8A96A6", answerAccent: "#9AD18B",
  modelText: "#C4B5FD", promptAccent: "#FFB86C", routeText: "#C4B5FD", savingText: "#8BD5CA",
});
export const STATUS_PULSE_FRAMES = Object.freeze({
  thinking: ["∙", "•", "●", "•"], tool: ["◌", "◔", "◑", "◕"], output: ["◇", "◆", "◇", "◆"],
});
```

- [ ] **Step 2: Create primitives.mjs** — move cellWidth/textWidth/clipToCells/stripTerminalControls/timelineAvailCells + layout constants out of main.mjs verbatim and export each. Add `TOOL_INDENT`, `CARD_RULE_LONG`, `CARD_RULE_SHORT`, `TIMELINE_WRAP_GUARD_CELLS`. Signatures (bodies copied verbatim from current main.mjs):

```javascript
export const TOOL_INDENT = " ";
export const CARD_RULE_LONG = "─".repeat(48);
export const CARD_RULE_SHORT = "─".repeat(8);
export const TIMELINE_WRAP_GUARD_CELLS = 6;
export function cellWidth(char) { /* verbatim from main.mjs */ }
export function textWidth(text) { /* verbatim */ }
export function clipToCells(text, cells) { /* verbatim */ }
export function stripTerminalControls(text) { /* verbatim */ }
export function timelineAvailCells(prefix, terminalWidth) {
  return Math.max(8, (terminalWidth ?? 80) - textWidth(prefix) - TIMELINE_WRAP_GUARD_CELLS);
}
export function railLine(TextRenderable, renderer, id, color) {
  return new TextRenderable(renderer, { id, content: `${TOOL_INDENT}│`, fg: color });
}
```

(Note: `timelineAvailCells` now takes `terminalWidth` explicitly instead of reading global `renderer` — modules should not reach a global. Callers pass `renderer.terminalWidth`.)

- [ ] **Step 3: Verify** — `node --check` both files:

Run: `node --check src/opensquilla/cli/tui/opentui/package/src/theme.mjs && node --check src/opensquilla/cli/tui/opentui/package/src/primitives.mjs`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/theme.mjs src/opensquilla/cli/tui/opentui/package/src/primitives.mjs
git commit -m "refactor: extract opentui host theme and primitives modules"
```

---

## Task 4: Block Renderer interface + promptBlock + usageBlock + errorBlock (simple kinds first)

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/blocks/promptBlock.mjs`
- Create: `.../blocks/usageBlock.mjs`
- Create: `.../blocks/errorBlock.mjs`

Renderer interface (every block module exports a factory `create(ctx)` returning an object):
```
{ begin(meta), append(delta), update(patch), retype(kind), end() }
```
`ctx = { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box, idPrefix }` where `box` is the turn's container, `idPrefix` is unique per block.

- [ ] **Step 1: Create promptBlock.mjs**:

```javascript
import { THEME } from "../theme.mjs";
import { CARD_RULE_LONG, CARD_RULE_SHORT, stripTerminalControls } from "../primitives.mjs";

export function createPromptBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  const add = (suffix, content) => {
    const n = new TextRenderable(renderer, { id: `${idPrefix}-${suffix}`, content, fg: THEME.promptAccent });
    box.add(n); return n;
  };
  return {
    begin(meta) {
      add("top", `╭─ prompt ${CARD_RULE_LONG}`);
      stripTerminalControls(String(meta?.text ?? "")).split("\n").forEach((line, i) => add(`l${i}`, `│ ${line}`));
      add("bot", `╰${CARD_RULE_SHORT}`);
      renderer.requestRender?.();
    },
    append() {}, update() {}, retype() {}, end() {},
  };
}
```

- [ ] **Step 2: Create usageBlock.mjs**:

```javascript
import { THEME } from "../theme.mjs";
import { stripTerminalControls } from "../primitives.mjs";

export function createUsageBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  return {
    begin(meta) {
      const n = new TextRenderable(renderer, {
        id: `${idPrefix}-usage`, content: `  · ${stripTerminalControls(String(meta?.text ?? ""))}`, fg: THEME.muted,
      });
      box.add(n); renderer.requestRender?.();
    },
    append() {}, update() {}, retype() {}, end() {},
  };
}
```

- [ ] **Step 3: Create errorBlock.mjs**:

```javascript
import { THEME } from "../theme.mjs";
import { TOOL_INDENT, stripTerminalControls } from "../primitives.mjs";

export function createErrorBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  return {
    begin(meta) {
      const n = new TextRenderable(renderer, {
        id: `${idPrefix}-err`, content: `${TOOL_INDENT}✗ ${stripTerminalControls(String(meta?.text ?? ""))}`, fg: THEME.routerError,
      });
      box.add(n); renderer.requestRender?.();
    },
    append() {}, update() {}, retype() {}, end() {},
  };
}
```

- [ ] **Step 4: Verify** — `node --check` all three.

Run: `for f in prompt usage error; do node --check src/opensquilla/cli/tui/opentui/package/src/blocks/${f}Block.mjs; done`
Expected: exit 0 each.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/blocks/
git commit -m "feat: add prompt/usage/error block renderers"
```

---

## Task 5: toolBlock renderer (node + grouped detail + pulse + status)

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/blocks/toolBlock.mjs`
- Modify: `primitives.mjs` (export a shared `toolPulseRegistry` Set + glyph helper) — OR keep pulse in turnView. DECISION: pulse registry lives in turnView (Task 9), toolBlock exposes `node` + `setGlyph`. toolBlock keeps its own running state.

- [ ] **Step 1: Create toolBlock.mjs**:

```javascript
import { THEME, STATUS_PULSE_FRAMES } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

export function createToolBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let node = null;
  let railNode = null;
  let name = "";
  let tail = "";
  let detailCount = 0;
  const detailPrefix = `${TOOL_INDENT}│   `;

  function setGlyph(glyph) {
    if (node) node.content = `${TOOL_INDENT}${glyph} ${name}${tail}`;
  }

  return {
    get node() { return node; },
    get isRunning() { return node !== null && railNode !== null && !node._done; },
    setGlyph,
    begin(meta) {
      name = stripTerminalControls(String(meta?.name ?? ""));
      const summary = stripTerminalControls(String(meta?.args ?? ""));
      tail = summary ? ` ${summary}` : "";
      railNode = new TextRenderable(renderer, { id: `${idPrefix}-rail`, content: `${TOOL_INDENT}│`, fg: THEME.detailText });
      box.add(railNode);
      node = new TextRenderable(renderer, { id: `${idPrefix}-node`, content: `${TOOL_INDENT}${STATUS_PULSE_FRAMES.tool[0]} ${name}${tail}`, fg: THEME.toolAccent });
      box.add(node);
      renderer.requestRender?.();
    },
    append(delta) {
      if (detailCount >= 3) return;
      const avail = timelineAvailCells(detailPrefix, renderer.terminalWidth);
      const content = `${detailPrefix}${clipToCells(stripTerminalControls(String(delta)), avail)}`;
      const d = new TextRenderable(renderer, { id: `${idPrefix}-d${detailCount}`, content, fg: THEME.detailText });
      box.add(d);
      detailCount += 1;
      renderer.requestRender?.();
    },
    update(patch) {
      const status = patch?.status;
      if (status === "ok" || status === "error") {
        const glyph = status === "error" ? "✗" : "✓";
        if (node) { node.content = `${TOOL_INDENT}${glyph} ${name}${tail}`; node.fg = status === "error" ? THEME.routerError : THEME.answerAccent; node._done = true; }
      }
      renderer.requestRender?.();
    },
    retype() {},
    end() { if (node) node._done = true; },
  };
}
```

- [ ] **Step 2: Verify** — `node --check src/opensquilla/cli/tui/opentui/package/src/blocks/toolBlock.mjs`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/blocks/toolBlock.mjs
git commit -m "feat: add tool block renderer with grouped detail"
```

---

## Task 6: answerBlock + thinkingBlock (the retype pair)

**Files:**
- Create: `.../blocks/answerBlock.mjs`
- Create: `.../blocks/thinkingBlock.mjs`

answerBlock streams as the cyan left-bordered markdown card. retype("thinking") tears it down and hands content to a thinking rendering (handled by turnView swapping the renderer — see Task 9). For isolation, answerBlock exposes its accumulated text so turnView can pass it to a fresh thinkingBlock on retype.

- [ ] **Step 1: Create answerBlock.mjs**:

```javascript
import { THEME } from "../theme.mjs";
import { CARD_RULE_LONG, CARD_RULE_SHORT, stripTerminalControls } from "../primitives.mjs";

export function createAnswerBlock(ctx) {
  const { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box, idPrefix } = ctx;
  let gap = null, top = null, body = null, md = null, bot = null;
  let text = "";
  return {
    get text() { return text; },
    begin() {
      gap = new TextRenderable(renderer, { id: `${idPrefix}-gap`, content: "│", fg: THEME.detailText }); box.add(gap);
      top = new TextRenderable(renderer, { id: `${idPrefix}-top`, content: `╭─ answer ─ squilla ${CARD_RULE_LONG}`, fg: THEME.toolAccent }); box.add(top);
      body = new BoxRenderable(renderer, { id: `${idPrefix}-body`, width: "100%", flexDirection: "column", border: ["left"], borderColor: THEME.toolAccent, paddingLeft: 1, flexShrink: 0 });
      md = new MarkdownRenderable(renderer, { id: `${idPrefix}-md`, content: "", streaming: true, conceal: true, syntaxStyle, fg: THEME.text, tableOptions: { style: "columns" }, internalBlockMode: "top-level", width: "100%" });
      body.add(md); box.add(body);
      renderer.requestRender?.();
    },
    append(delta) { text += String(delta); if (md) md.content = stripTerminalControls(text); renderer.requestRender?.(); },
    update() {},
    retype() {},  // turnView handles teardown; expose teardown:
    teardown() { [gap, top, body, bot].forEach((n) => { if (n) box.remove?.(n.id); }); },
    end() {
      if (md) md.streaming = false;
      bot = new TextRenderable(renderer, { id: `${idPrefix}-bot`, content: `╰${CARD_RULE_SHORT}`, fg: THEME.toolAccent }); box.add(bot);
      renderer.requestRender?.();
    },
  };
}
```

- [ ] **Step 2: Create thinkingBlock.mjs**:

```javascript
import { THEME } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let text = "";
  let rendered = false;
  function flush() {
    const trimmed = stripTerminalControls(text).replace(/^\n+|\n+$/g, "");
    if (!trimmed) return;
    const gt = new TextRenderable(renderer, { id: `${idPrefix}-gt`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }); box.add(gt);
    trimmed.split("\n").forEach((line, i) => {
      const prefix = i === 0 ? `${TOOL_INDENT}✱ ` : `${TOOL_INDENT}  `;
      const avail = timelineAvailCells(prefix, renderer.terminalWidth);
      const n = new TextRenderable(renderer, { id: `${idPrefix}-l${i}`, content: `${prefix}${clipToCells(line, avail)}`, fg: THEME.modelText }); box.add(n);
    });
    const gb = new TextRenderable(renderer, { id: `${idPrefix}-gb`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }); box.add(gb);
    rendered = true;
    renderer.requestRender?.();
  }
  return {
    seedText(t) { text = t; },  // turnView passes answer's accumulated text on retype
    begin() {},
    append(delta) { text += String(delta); },
    update() {}, retype() {},
    end() { if (!rendered) flush(); },
  };
}
```

- [ ] **Step 3: Verify** — `node --check` both.

Run: `node --check src/opensquilla/cli/tui/opentui/package/src/blocks/answerBlock.mjs && node --check src/opensquilla/cli/tui/opentui/package/src/blocks/thinkingBlock.mjs`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/blocks/answerBlock.mjs src/opensquilla/cli/tui/opentui/package/src/blocks/thinkingBlock.mjs
git commit -m "feat: add answer and thinking block renderers"
```

---

## Task 7: blockRegistry

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/blockRegistry.mjs`

- [ ] **Step 1: Create blockRegistry.mjs**:

```javascript
import { createPromptBlock } from "./blocks/promptBlock.mjs";
import { createThinkingBlock } from "./blocks/thinkingBlock.mjs";
import { createToolBlock } from "./blocks/toolBlock.mjs";
import { createAnswerBlock } from "./blocks/answerBlock.mjs";
import { createUsageBlock } from "./blocks/usageBlock.mjs";
import { createErrorBlock } from "./blocks/errorBlock.mjs";

const FACTORIES = {
  prompt: createPromptBlock,
  thinking: createThinkingBlock,
  tool: createToolBlock,
  answer: createAnswerBlock,
  usage: createUsageBlock,
  error: createErrorBlock,
};

export function createBlock(kind, ctx) {
  const factory = FACTORIES[kind];
  if (!factory) throw new Error(`Unknown block kind: ${kind}`);
  return factory(ctx);
}
```

- [ ] **Step 2: Verify** — `node --check src/opensquilla/cli/tui/opentui/package/src/blockRegistry.mjs`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/blockRegistry.mjs
git commit -m "feat: add block registry mapping kind to renderer"
```

---

## Task 8: turnView container (routing + retype handling)

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/turnView.mjs`

turnView owns the turn box, a `Map<blockId, {kind, renderer}>`, and the tool pulse set (running tool nodes that animate). It routes block messages and handles `retype` by tearing down the answer block and creating a thinking block seeded with the answer's accumulated text.

- [ ] **Step 1: Create turnView.mjs**:

```javascript
import { createBlock } from "./blockRegistry.mjs";
import { STATUS_PULSE_FRAMES } from "./theme.mjs";

export function createTurnView(deps, id) {
  const { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox } = deps;
  const box = new BoxRenderable(renderer, { id: `turn-${id}`, flexDirection: "column", paddingLeft: 1, paddingRight: 1 });
  conversationBox.add(box);
  const blocks = new Map();      // blockId -> { kind, r }
  const runningTools = new Set(); // toolBlock renderers animating

  function ctxFor(blockId) {
    return { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box, idPrefix: `turn-${id}-${blockId}` };
  }

  return {
    box,
    ended: false,
    begin(blockId, kind, meta) {
      const r = createBlock(kind, ctxFor(blockId));
      blocks.set(blockId, { kind, r });
      r.begin(meta ?? {});
      if (kind === "tool") runningTools.add(r);
    },
    append(blockId, delta) { blocks.get(blockId)?.r.append(delta); },
    update(blockId, patch) {
      const entry = blocks.get(blockId);
      if (!entry) return;
      entry.r.update(patch);
      if (entry.kind === "tool" && (patch?.status === "ok" || patch?.status === "error")) runningTools.delete(entry.r);
    },
    retype(blockId, kind) {
      const entry = blocks.get(blockId);
      if (!entry) return;
      if (entry.kind === "answer" && kind === "thinking") {
        const text = entry.r.text;
        entry.r.teardown();
        const t = createBlock("thinking", ctxFor(blockId));
        t.seedText(text);
        blocks.set(blockId, { kind: "thinking", r: t });
      }
    },
    end(blockId) {
      const entry = blocks.get(blockId);
      if (!entry) return;
      entry.r.end();
      if (entry.kind === "tool") runningTools.delete(entry.r);
    },
    refreshPulse(frame) {
      const glyph = STATUS_PULSE_FRAMES.tool[frame % STATUS_PULSE_FRAMES.tool.length];
      for (const r of runningTools) r.setGlyph(glyph);
    },
  };
}
```

- [ ] **Step 2: Verify** — `node --check src/opensquilla/cli/tui/opentui/package/src/turnView.mjs`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/turnView.mjs
git commit -m "feat: add turnView container routing block messages"
```

---

## Task 9: composer module (extract input region)

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/composer.mjs`

Move the composer state, caret model (cursorPos/caretGlyph/composerLines/caretLineCol/lineColToPos/moveCaret*/insertAtCursor/deleteBeforeCursor/setInput), history (inputHistory/recallHistory), rerenderInputRegion, blink, and keyboard handler (installKeyboardHandlers including esc/ctrl+C/option-enter/wheel) out of main.mjs into composer.mjs. Export `createComposer({renderer, BoxRenderable, TextRenderable, conversationBox, sendHostMessage})` returning `{ rerender, setComposerState, setRouterState, setTurnStatus, syncPulseTimer, install, onResize }`.

- [ ] **Step 1: Create composer.mjs** — move verbatim the relevant functions/state from current main.mjs (lines ~85-260 for state/render, ~530-760 for keyboard/history), parameterizing the global `renderer`/`conversationBox`/`sendHostMessage` as closure args. Keep behavior identical (this is extraction, not change).

(Executor: copy the existing function bodies; replace global references with the closure-provided deps; export the factory. This is mechanical extraction — preserve every behavior: caret editing, history at boundary chars, esc→cancel, ctrl+C clear/eof, option+enter newline, wheel→scroll via useMouse, blink.)

- [ ] **Step 2: Verify** — `node --check src/opensquilla/cli/tui/opentui/package/src/composer.mjs`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/composer.mjs
git commit -m "refactor: extract composer/input module from main.mjs"
```

---

## Task 10: ipc module (parse + dispatch)

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/package/src/ipc.mjs`

- [ ] **Step 1: Create ipc.mjs** — fd read/write + dispatch table mapping message type → handler:

```javascript
import fs from "node:fs";
import readline from "node:readline";

export function createIpc({ fromFd, toFd }) {
  function send(message) { fs.writeSync(toFd, `${JSON.stringify(message)}\n`, "utf8"); }
  function start(onMessage, onClose) {
    const input = fs.createReadStream(null, { fd: fromFd, encoding: "utf8", autoClose: false });
    const lines = readline.createInterface({ input, crlfDelay: Infinity });
    lines.on("line", (line) => { if (line.trim()) { try { onMessage(JSON.parse(line)); } catch (e) { send({ type: "error", message: e instanceof Error ? e.message : String(e) }); } } });
    lines.on("close", onClose);
  }
  return { send, start };
}

// Build a dispatcher that routes block.* + turn.* + composer/router to handlers.
export function createDispatcher(h) {
  return (m) => {
    switch (m.type) {
      case "turn.begin": return h.turnBegin(m);
      case "turn.end": return h.turnEnd(m);
      case "turn.status": return h.turnStatus(m);
      case "composer.set": return h.composerSet(m);
      case "router.update": return h.routerUpdate(m);
      case "block.begin": return h.blockBegin(m);
      case "block.append": return h.blockAppend(m);
      case "block.update": return h.blockUpdate(m);
      case "block.retype": return h.blockRetype(m);
      case "block.end": return h.blockEnd(m);
      case "scrollback.write": return h.scrollback?.(m);
      case "shutdown": return h.shutdown(m);
      default: return h.unknown(m);
    }
  };
}
```

- [ ] **Step 2: Verify** — `node --check src/opensquilla/cli/tui/opentui/package/src/ipc.mjs`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/ipc.mjs
git commit -m "feat: add ipc module with message dispatcher"
```

---

## Task 11: Rewrite main.mjs as thin entry wiring modules

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs` (replace nearly all of it)

main.mjs now only: parses --help, reads fds, creates renderer (useMouse:true, alt-screen), builds layout (conversationBox + inputBox), creates composer, wires ipc dispatcher to turnView + composer, manages activeTurn lifecycle + pulse timer.

- [ ] **Step 1: Rewrite main.mjs**:

```javascript
#!/usr/bin/env node
import process from "node:process";
import { THEME } from "./theme.mjs";
import { createComposer } from "./composer.mjs";
import { createTurnView } from "./turnView.mjs";
import { createIpc, createDispatcher } from "./ipc.mjs";

const HELP = `OpenSquilla OpenTUI footer host\n\nUsage:\n  bun src/main.mjs\n\nIPC:\n  reads Python JSON lines from fd 3 and writes host JSON lines to fd 4.\n`;
if (process.argv.includes("--help") || process.argv.includes("-h")) { process.stdout.write(HELP); process.exit(0); }

const FROM = Number(process.env.OPENSQUILLA_OPENTUI_FROM_PYTHON_FD ?? "3");
const TO = Number(process.env.OPENSQUILLA_OPENTUI_TO_PYTHON_FD ?? "4");
const FOOTER_HEIGHT = 6;

async function main() {
  const { BoxRenderable, TextRenderable, ScrollBoxRenderable, MarkdownRenderable, SyntaxStyle, createCliRenderer } = await import("@opentui/core");
  const renderer = await createCliRenderer({ screenMode: "alternate-screen", exitOnCtrlC: false, useMouse: true });
  const syntaxStyle = SyntaxStyle.create();

  const conversationBox = new ScrollBoxRenderable(renderer, { id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: Math.max(1, (renderer.terminalHeight ?? 24) - FOOTER_HEIGHT), stickyScroll: true, stickyStart: "bottom", scrollY: true, scrollX: false, viewportCulling: true });
  renderer.root.add(conversationBox);
  const inputBox = new BoxRenderable(renderer, { id: "input-region", position: "absolute", left: 0, right: 0, bottom: 0, height: FOOTER_HEIGHT });
  renderer.root.add(inputBox);

  const ipc = createIpc({ fromFd: FROM, toFd: TO });
  const composer = createComposer({ renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, footerHeight: FOOTER_HEIGHT, sendHostMessage: ipc.send });
  composer.install();

  let activeTurn = null;
  let scrollbackSeq = 0;
  const turnDeps = { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox };
  const ensureTurn = (id) => { if (!activeTurn || activeTurn.ended) activeTurn = createTurnView(turnDeps, id ?? scrollbackSeq++); return activeTurn; };

  const dispatch = createDispatcher({
    turnBegin: (m) => ensureTurn(m.id),
    turnEnd: () => { if (activeTurn) activeTurn.ended = true; },
    turnStatus: (m) => { composer.setTurnStatus(m); },
    composerSet: (m) => composer.setComposerState(m),
    routerUpdate: (m) => composer.setRouterState(m),
    blockBegin: (m) => ensureTurn().begin(m.id, m.kind, m.meta),
    blockAppend: (m) => activeTurn?.append(m.id, m.delta),
    blockUpdate: (m) => activeTurn?.update(m.id, m.patch),
    blockRetype: (m) => activeTurn?.retype(m.id, m.kind),
    blockEnd: (m) => activeTurn?.end(m.id),
    shutdown: () => { renderer.destroy(); process.exit(0); },
    unknown: (m) => ipc.send({ type: "error", message: `Unknown message type: ${m.type}` }),
  });

  renderer.on?.("resize", () => { const h = renderer.terminalHeight ?? 24; conversationBox.height = Math.max(1, h - FOOTER_HEIGHT); composer.onResize(); const w = renderer.terminalWidth ?? 0; if (w && h) ipc.send({ type: "resize", width: w, height: h }); });

  // pulse timer drives running tool glyph animation + composer status pill
  let pulseFrame = 0;
  setInterval(() => { pulseFrame += 1; activeTurn?.refreshPulse(pulseFrame); composer.tickPulse(pulseFrame); renderer.requestRender?.(); }, 180).unref?.();

  ipc.send({ type: "ready" });
  ipc.start((m) => { try { dispatch(m); } catch (e) { ipc.send({ type: "error", message: e instanceof Error ? e.message : String(e) }); } }, () => { renderer.destroy(); process.exit(0); });
}
main().catch((e) => { process.stderr.write(`${e?.message ?? e}\n`); process.exit(1); });
```

(Executor: the composer factory must expose `setTurnStatus/setComposerState/setRouterState/onResize/tickPulse/install`. Reconcile composer.mjs's exports with these calls; adjust composer.mjs if names differ. The pulse timer here replaces the old syncPulseTimer; composer's blink stays internal.)

- [ ] **Step 2: Verify** — `node --check` + smoke:

Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs && npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: NODE ok + smoke prints help.

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs
git commit -m "refactor: rewrite main.mjs as thin entry wiring block modules"
```

---

## Task 12: Update host structure tests + remove dead old-message handling

**Files:**
- Modify: `tests/unit/cli/tui/test_opentui_host_layout.py` (rewrite for module structure)
- Modify: `tests/unit/cli/tui/test_opentui_messages.py` if it still asserts removed messages
- Modify: `tests/integration/cli/tui_real_terminal/*` if they assert old message types

- [ ] **Step 1: Rewrite test_opentui_host_layout.py** to assert the new module structure instead of main.mjs internals. New assertions (file reads each module):

```python
from pathlib import Path
SRC = Path(__file__).resolve().parents[4] / "src/opensquilla/cli/tui/opentui/package/src"

def test_host_split_into_block_modules() -> None:
    for f in ["theme.mjs","primitives.mjs","blockRegistry.mjs","turnView.mjs","composer.mjs","ipc.mjs",
              "blocks/promptBlock.mjs","blocks/thinkingBlock.mjs","blocks/toolBlock.mjs",
              "blocks/answerBlock.mjs","blocks/usageBlock.mjs","blocks/errorBlock.mjs"]:
        assert (SRC / f).exists(), f"missing {f}"

def test_registry_covers_six_kinds() -> None:
    reg = (SRC / "blockRegistry.mjs").read_text(encoding="utf-8")
    for kind in ["prompt","thinking","tool","answer","usage","error"]:
        assert f"{kind}:" in reg

def test_rails_share_one_colour() -> None:
    # detailText is the single rail colour across tool + thinking + answer-gap
    tool = (SRC / "blocks/toolBlock.mjs").read_text(encoding="utf-8")
    thinking = (SRC / "blocks/thinkingBlock.mjs").read_text(encoding="utf-8")
    answer = (SRC / "blocks/answerBlock.mjs").read_text(encoding="utf-8")
    assert "THEME.detailText" in tool and "│" in tool
    assert "THEME.detailText" in thinking
    assert "THEME.detailText" in answer

def test_answer_card_uses_left_border_markdown() -> None:
    answer = (SRC / "blocks/answerBlock.mjs").read_text(encoding="utf-8")
    assert 'border: ["left"]' in answer
    assert "borderColor: THEME.toolAccent" in answer
    assert "MarkdownRenderable" in answer

def test_main_uses_mouse_and_alt_screen() -> None:
    main = (SRC / "main.mjs").read_text(encoding="utf-8")
    assert 'screenMode: "alternate-screen"' in main
    assert "useMouse: true" in main
```

- [ ] **Step 2: Run all unit tests, fix stragglers**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/ -q`
Expected: PASS. Update any test still referencing `answer.text`/`answer.demote`/`model.text`/`tool.call`/`tool.detail` to block-protocol equivalents.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/cli/tui/
git commit -m "test: assert block-module host structure and protocol"
```

---

## Task 13: Update replay + integration tests for block protocol

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py` (assert block-protocol rendered output)
- Modify: `tests/integration/cli/tui_real_terminal/test_complex_ui_state.py` if it asserts old messages
- Modify: `tests/integration/cli/tui_real_terminal/fake_opentui_app.py` only if it bypasses renderer (it drives OpenTuiStreamRenderer, so the new protocol flows automatically — verify)

- [ ] **Step 1: Run integration suite, see failures**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/integration/cli/tui_real_terminal/ -q`
Expected: some FAIL where assertions reference old frame text.

- [ ] **Step 2: Update assertions** to match block-protocol frames (tool `✓ name`, thinking `✱`, answer `╭─ answer ─ squilla`, usage `· in/out`). Use actual frame output to write assertions (run the lab once, read transcript).

- [ ] **Step 3: Run, verify pass**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/integration/cli/tui_real_terminal/ -q`
Expected: PASS (tmux-dependent tests may skip; non-tmux logic passes).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/cli/tui_real_terminal/
git commit -m "test: align integration assertions with block protocol"
```

---

## Task 14: End-to-end real-terminal verification

- [ ] **Step 1: Full unit + integration**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/ tests/unit/cli/repl/ tests/integration/cli/tui_real_terminal/ -q`
Expected: all pass / expected skips.

- [ ] **Step 2: ruff + node check + smoke**

```bash
UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run ruff check src/opensquilla/cli/tui/ tests/
node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs
npm run --prefix src/opensquilla/cli/tui/opentui/package smoke
```
Expected: all clean.

- [ ] **Step 3: Real live run** (network; rerun with sandbox disabled if blocked)

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run python scripts/tui_real_terminal_lab.py --scenario live_opentui_architecture_prompt --backend live-opentui --driver tmux`
Read latest `.artifacts/tui-real-terminal/runs/<ts>/transcript.txt`. Confirm:
- thinking = purple ✱ block (between tools), no cyan-card flash
- tool nodes indented one cell, detail grouped under with `│   `, single rail colour, no wrap past rail
- final answer = cyan left-border card, streamed as card
- timeline rail continuous

- [ ] **Step 4: Replay run for final answer card** (deterministic)

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run python scripts/tui_real_terminal_lab.py --scenario architecture_prompt --backend opentui --driver tmux`
Confirm final answer card + grouped tool detail in transcript.

- [ ] **Step 5: Commit any assertion fixups, then report**

```bash
git add -A
git commit -m "test: finalize block-protocol real-terminal verification"
```

Report to user: structural before/after, test counts, and that interaction items (caret/wheel/option-enter/copy) still need their manual terminal eyeball.

---

## Self-Review Notes (addressed)

- **Spec coverage:** 6 kinds → Tasks 4,5,6; protocol → Tasks 1,2; primitives/theme → Task 3; registry → 7; turnView → 8; composer/ipc → 9,10; main wiring → 11; tests → 12,13,14. All spec sections mapped.
- **Retype pair:** answerBlock.teardown() + thinkingBlock.seedText() + turnView.retype() wired consistently (Tasks 6,8).
- **Single rail colour:** THEME.detailText used in tool/thinking/answer rails (Task 12 asserts).
- **No global reach:** primitives.timelineAvailCells takes terminalWidth param; modules receive renderer via ctx/deps.
- **Known risk:** composer.mjs extraction (Task 9) is mechanical but large; executor must preserve every interaction behavior. If composer/main method names drift, reconcile at Task 11 Step 1.
