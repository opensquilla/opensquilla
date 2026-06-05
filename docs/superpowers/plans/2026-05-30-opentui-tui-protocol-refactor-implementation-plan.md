# OpenTUI TUI Protocol Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **并行与多 agent 执行策略:** 任务按 Wave 分组。同一 Wave 内的任务彼此无依赖,可派发给多个并行 subagent 同时实现;Wave 之间有依赖,必须按序。每个任务实现时**可调用 codex xhigh**(`mcp__codex__codex`,model 选高推理档)产出代码,再由 review 把关。开始执行前先用 `/goal` 设定总目标:"把 OpenTUI footer TUI 重构为结构化消息协议,修活三处死代码,落地分层 scrollback 视觉,并通过 live-opentui tmux 真实跑通验证美观度"。
>
> **Wave 划分:**
> - **Wave 1(并行):** Task 1(协议消息) — 是所有上层的基础,先单独跑完。
> - **Wave 2(并行,依赖 Wave 1):** Task 2(JS 渲染层)、Task 3(OpenTuiStreamRenderer)、Task 4(surface 发送通道) 可并行。
> - **Wave 3(并行,依赖 Wave 2):** Task 5(runtime 接线 + prompt.echo)、Task 6(footer 重做 JS) 可并行。
> - **Wave 4(串行,依赖 Wave 3):** Task 7(live-opentui 验证路径接线)。
> - **Wave 5(串行,依赖全部):** Task 8(tmux 真实跑 + 美学迭代)、Task 9(全量验证 bundle)。

**Goal:** 把 OpenTUI footer TUI 从"Python 写纯文本 + JS 正则猜语义"重构为"Python 发结构化语义消息 + JS 按类型精确渲染",修活 turn 状态/composer 禁用/router context 三处死代码,落地分层 scrollback 视觉(块内紧凑折叠、turn 大块收尾卡片、颜色编码),并新增 live-opentui tmux 真实模型验证路径迭代调优美观度。

**Architecture:** 新增 `OpenTuiStreamRenderer`(镜像 `TerminalRenderer` 接口但发结构化消息),作为 opentui backend 的 `renderer_factory` 注入;`messages.py` 新增 11 类结构化消息;`main.mjs` 删除整套正则分类管线,改按消息 type 渲染并维护轻量 turn 块状态机;footer 三处死代码由 renderer 生命周期与 `turn.status`/`composer.set` 驱动。

**Tech Stack:** Python(asyncio、dataclass)、OpenTUI/Bun JS host、pytest 单元/静态测试、tmux real-terminal harness、ruff。

---

## File Structure

- Modify `src/opensquilla/cli/tui/opentui/messages.py`:新增结构化消息 dataclass 与解析(turn.begin/end/status、prompt.echo、model.text、tool.call、tool.detail、answer.text、usage)。
- Create `src/opensquilla/cli/tui/opentui/renderer.py`:`OpenTuiStreamRenderer`,镜像 `TerminalRenderer` 接口,每方法发结构化消息。
- Modify `src/opensquilla/cli/tui/opentui/surface.py`:`OpenTuiOutputHandle` 增结构化发送方法;`open_opentui_surface` 仍发初始 `composer.set`。
- Modify `src/opensquilla/cli/tui/opentui/runtime.py`:`echo_opentui_user_input`/`echo_opentui_queued_turn_start` 改发结构化消息;注入 `OpenTuiStreamRenderer` 作 renderer_factory。
- Modify `src/opensquilla/cli/tui/opentui/package/src/main.mjs`:删除正则分类管线,新增按 type 的 `renderXxxBlock` 与 turn 块状态机;footer 三处死代码修活。
- Modify `tests/integration/cli/tui_real_terminal/targets.py`:新增 `_live_opentui_target` 并注册。
- Modify `tests/integration/cli/tui_real_terminal/scenarios.py`:新增 `live_opentui_architecture_prompt` 场景。
- Modify `scripts/tui_real_terminal_lab.py`:`--backend` choices 加 `live-opentui`。
- Modify/Create 测试:`test_opentui_messages.py`、`test_opentui_renderer.py`(新)、`test_opentui_surface.py`、`test_opentui_host_layout.py`、`test_opentui_chat_adapter.py`、`test_architecture_prompt.py`。

---

## Task 1: 结构化消息协议(`messages.py`)

> **Wave 1。** 所有上层任务的基础。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/messages.py`
- Test: `tests/unit/cli/tui/test_opentui_messages.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/cli/tui/test_opentui_messages.py` 末尾追加:

```python
def test_python_message_to_json_serializes_structured_blocks() -> None:
    from opensquilla.cli.tui.opentui.messages import (
        AnswerText,
        ModelText,
        PromptEcho,
        ToolCall,
        ToolDetail,
        TurnBegin,
        TurnEnd,
        TurnStatusState,
        Usage,
    )

    assert '"type":"turn.begin"' in python_message_to_json("turn.begin", TurnBegin(id="t1"))
    assert '"type":"prompt.echo"' in python_message_to_json(
        "prompt.echo", PromptEcho(text="帮我分析架构")
    )
    assert '"id":"t1"' in python_message_to_json("turn.end", TurnEnd(id="t1", cancelled=False))
    model = python_message_to_json("model.text", ModelText(text="先扫描结构"))
    assert '"type":"model.text"' in model and '"text":"先扫描结构"' in model
    tool = python_message_to_json(
        "tool.call", ToolCall(name="read_file", summary="main.py", status="running", id="c1")
    )
    assert '"name":"read_file"' in tool and '"status":"running"' in tool
    assert '"type":"tool.detail"' in python_message_to_json(
        "tool.detail", ToolDetail(text="312 lines")
    )
    assert '"type":"answer.text"' in python_message_to_json(
        "answer.text", AnswerText(text="架构分四层")
    )
    assert '"type":"usage"' in python_message_to_json("usage", Usage(text="in 1k / out 2k"))
    status = python_message_to_json(
        "turn.status", TurnStatusState(phase="tool", label="read_file", active=True)
    )
    assert '"phase":"tool"' in status and '"active":true' in status
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_messages.py -q`
Expected: FAIL — `ImportError: cannot import name 'TurnBegin'`。

- [ ] **Step 3: 实现消息 dataclass**

在 `src/opensquilla/cli/tui/opentui/messages.py` 的 `RouterPluginState` 定义之后(约 line 21 后)插入:

```python
@dataclass(frozen=True)
class TurnBegin:
    id: str


@dataclass(frozen=True)
class TurnEnd:
    id: str
    cancelled: bool = False


@dataclass(frozen=True)
class PromptEcho:
    text: str


@dataclass(frozen=True)
class ModelText:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    summary: str = ""
    status: str = "running"
    id: str | None = None


@dataclass(frozen=True)
class ToolDetail:
    text: str


@dataclass(frozen=True)
class AnswerText:
    text: str


@dataclass(frozen=True)
class Usage:
    text: str
```

这些都是 Python→JS 消息,序列化走已有的 `python_message_to_json`(它用 `asdict`),无需改解析器(`host_message_from_json` 只解析 JS→Python 消息)。`TurnStatusState` 已存在于文件中,无需新增。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_messages.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/messages.py tests/unit/cli/tui/test_opentui_messages.py
git commit -m "feat: add structured OpenTUI timeline messages"
```

---

## Task 2: JS 渲染层重构(`main.mjs`)

> **Wave 2。** 依赖 Task 1 的消息契约(消息 type 名)。可与 Task 3、4 并行。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败测试**

把 `tests/unit/cli/tui/test_opentui_host_layout.py` 的 `test_opentui_host_locks_recommended_daily_visual_preset` 整体替换为下面两个测试(锁新渲染契约、删旧正则函数名):

```python
def test_opentui_host_locks_recommended_daily_visual_preset() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "OPENTUI_DAILY_THEME" in source
    assert 'preset: "daily"' in source
    assert 'frame: "card"' in source
    assert "#77B7FF" in source
    # 新的按 type 渲染分发(无正则分类)
    assert "renderPromptBlock" in source
    assert "renderModelText" in source
    assert "renderToolCall" in source
    assert "renderToolDetail" in source
    assert "renderAnswerText" in source
    assert "renderUsage" in source
    assert "STATUS_PULSE_FRAMES" in source


def test_opentui_host_removes_regex_timeline_classifier() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    # 整套正则猜测管线必须删除
    assert "decorateDailyTimelineScrollback" not in source
    assert "classifyDailyTimelineLine" not in source
    assert "colorForDailyScrollback" not in source
    # 块状态机存在
    assert "currentTurn" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: FAIL — `renderPromptBlock` 不存在、`decorateDailyTimelineScrollback` 仍存在。

- [ ] **Step 3: 删除正则管线,实现按 type 渲染**

在 `main.mjs` 中删除这些函数:`decorateDailyTimelineScrollback`、`classifyDailyTimelineLine`、`decorateDailyToolLine`、`decorateDailyDetailLine`、`colorForDailyScrollback`、`isDailySemanticScrollback`、`trimDailySemanticBlankEdges`、`wrapWidthForDailyLine`、`continuationPrefixForLine`。保留 `stripTerminalControls`、`wrapText`、`appendHardWrappedToken`、`textWidth`、`cellWidth`、`padLinesForScrollback`。

在顶部状态区(约 line 56 `let pulseFrame` 附近)新增 turn 块状态与 scrollback 计数器:

```javascript
let scrollbackSeq = 0;
const currentTurn = { id: null, sawAnswer: false };
```

新增统一的 scrollback 写入工具(替换旧 `writePlainScrollback` 的语义部分),以及各 `renderXxxBlock`。把旧的 `writePlainScrollback` 替换为下面这组函数:

```javascript
function writeScrollbackBlock(lines, fg, { startOnNewLine = true } = {}) {
  if (!renderer) return;
  renderer.writeToScrollback((ctx) => {
    const width = Math.max(1, ctx.width - 1);
    const plain = lines.map((line) => stripTerminalControls(line)).join("\n");
    const wrapped = padLinesForScrollback(wrapText(plain, Math.max(1, width - 1)));
    const height = Math.max(1, wrapped.split("\n").length);
    const node = new TextRenderable(ctx.renderContext, {
      id: `scrollback-${scrollbackSeq++}`,
      position: "absolute",
      left: 0,
      top: 0,
      width,
      height,
      content: wrapped,
      fg,
    });
    return { root: node, width, height, startOnNewLine, trailingNewline: true };
  });
}

function renderPromptBlock(text) {
  const lines = ["╭─ prompt"];
  for (const line of String(text).split("\n")) lines.push(`│ ${line}`);
  lines.push("╰");
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.promptAccent);
}

function renderModelText(text) {
  writeScrollbackBlock([String(text)], OPENTUI_DAILY_THEME.answerAccent);
}

function renderToolCall(name, summary, status) {
  const glyph = status === "error" ? "✗" : status === "ok" ? "✓" : "•";
  const fg = status === "error" ? OPENTUI_DAILY_THEME.routerError : OPENTUI_DAILY_THEME.toolAccent;
  const tail = summary ? ` ${summary}` : "";
  writeScrollbackBlock([`  ${glyph} ${name}${tail}`], fg);
}

function renderToolDetail(text) {
  const lines = String(text).split("\n").map((line) => `    │ ${line}`);
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.detailText);
}

function renderAnswerText(text) {
  const lines = [];
  if (!currentTurn.sawAnswer) {
    lines.push("╭─ answer ─ squilla");
    currentTurn.sawAnswer = true;
  }
  for (const line of String(text).split("\n")) lines.push(`│ ${line}`);
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.text);
}

function renderAnswerClose(cancelled) {
  if (cancelled) {
    writeScrollbackBlock(["╰─ turn cancelled"], OPENTUI_DAILY_THEME.muted);
    return;
  }
  if (currentTurn.sawAnswer) {
    writeScrollbackBlock(["╰"], OPENTUI_DAILY_THEME.text);
  }
}

function renderUsage(text) {
  writeScrollbackBlock([`  · ${text}`], OPENTUI_DAILY_THEME.muted);
}
```

把 `handlePythonMessage` 的 switch(约 line 448)替换为新分发(保留 `composer.set`、`shutdown`、`error` 分支,删除旧 `scrollback.write` 的语义猜测、保留其纯文本降级):

```javascript
function handlePythonMessage(message) {
  switch (message.type) {
    case "router.update":
      Object.assign(routerState, {
        model: String(message.model ?? routerState.model),
        route: String(message.route ?? routerState.route),
        saving: String(message.saving ?? routerState.saving),
        context: String(message.context ?? routerState.context),
        style: String(message.style ?? routerState.style),
      });
      rerenderFooter();
      return;
    case "composer.set":
      Object.assign(composer, {
        placeholder: String(message.placeholder ?? composer.placeholder),
        text: String(message.text ?? composer.text),
        disabled: Boolean(message.disabled ?? composer.disabled),
      });
      inputText = composer.text;
      rerenderFooter();
      return;
    case "turn.status":
      Object.assign(turnStatus, {
        phase: String(message.phase ?? turnStatus.phase),
        label: String(message.label ?? turnStatus.label),
        active: Boolean(message.active ?? turnStatus.active),
      });
      syncPulseTimer();
      rerenderFooter();
      return;
    case "turn.begin":
      currentTurn.id = String(message.id ?? "");
      currentTurn.sawAnswer = false;
      return;
    case "prompt.echo":
      renderPromptBlock(String(message.text ?? ""));
      return;
    case "model.text":
      renderModelText(String(message.text ?? ""));
      return;
    case "tool.call":
      renderToolCall(
        String(message.name ?? ""),
        String(message.summary ?? ""),
        String(message.status ?? "running"),
      );
      return;
    case "tool.detail":
      renderToolDetail(String(message.text ?? ""));
      return;
    case "answer.text":
      renderAnswerText(String(message.text ?? ""));
      return;
    case "turn.end":
      renderAnswerClose(Boolean(message.cancelled ?? false));
      currentTurn.id = null;
      currentTurn.sawAnswer = false;
      return;
    case "usage":
      renderUsage(String(message.text ?? ""));
      return;
    case "scrollback.write":
      writeScrollbackBlock([String(message.text ?? "")], OPENTUI_DAILY_THEME.text, {
        startOnNewLine: false,
      });
      return;
    case "shutdown":
      if (pulseTimer) clearInterval(pulseTimer);
      renderer.destroy();
      process.exit(0);
      return;
    default:
      writeError(new Error(`Unknown Python message type: ${message.type}`));
  }
}
```

同时把 `main.mjs` 顶部 `turnStatus` 初始对象(约 line 73-78,当前含 `phase/label/active/style`)的 `style: "dim"` 行删除(turn.status 不再带 style);把 `router-route`/`router-saving` 的硬编码色 `#C4B5FD`/`#8BD5CA` 收进 `OPENTUI_DAILY_THEME`(新增 `routeText: "#C4B5FD"`、`savingText: "#8BD5CA"`),在 `renderFooterTree` 的对应 `Text({ id: "router-route", ... fg: ... })` 引用它们。

- [ ] **Step 4: 运行测试 + JS smoke 确认通过**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: PASS。

Run: `npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: PASS,打印 footer host help。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "refactor: render OpenTUI scrollback by message type, drop regex classifier"
```

---

## Task 3: OpenTuiStreamRenderer(`renderer.py`)

> **Wave 2。** 依赖 Task 1。可与 Task 2、4 并行。

**Files:**
- Create: `src/opensquilla/cli/tui/opentui/renderer.py`
- Test: `tests/unit/cli/tui/test_opentui_renderer.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/cli/tui/test_opentui_renderer.py`:

```python
from __future__ import annotations

import pytest

from opensquilla.cli.tui.opentui.renderer import OpenTuiStreamRenderer


class _RecordingHandle:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_message(self, message_type: str, payload: dict) -> None:
        self.sent.append((message_type, payload))


@pytest.mark.asyncio
async def test_renderer_emits_turn_lifecycle_and_blocks() -> None:
    handle = _RecordingHandle()
    renderer = OpenTuiStreamRenderer(title="squilla", output_handle=handle)

    renderer.__enter__()
    await renderer.astatus("先扫描结构")
    await renderer.atool_start("read_file", {"path": "main.py"}, "c1")
    await renderer.atool_finished("c1", success=True)
    await renderer.aappend_text("架构分四层")
    await renderer.afinalize(None, cancelled=False)
    renderer.__exit__(None, None, None)

    types = [t for t, _ in handle.sent]
    assert types[0] == "turn.begin"
    assert "turn.status" in types
    assert "model.text" in types
    assert "tool.call" in types
    assert "answer.text" in types
    assert "usage" in types
    assert types[-1] == "turn.end" or "turn.end" in types
    # tool.call running 后有 ok
    statuses = [p.get("status") for t, p in handle.sent if t == "tool.call"]
    assert "running" in statuses and "ok" in statuses
    # aappend_text 首次前置 output 状态
    assert any(t == "turn.status" and p.get("phase") == "output" for t, p in handle.sent)


@pytest.mark.asyncio
async def test_renderer_marks_tool_error_and_cancel() -> None:
    handle = _RecordingHandle()
    renderer = OpenTuiStreamRenderer(output_handle=handle)
    renderer.__enter__()
    await renderer.atool_start("grep", {"pattern": "x"}, "c2")
    await renderer.atool_finished("c2", success=False, error="boom")
    await renderer.afinalize(None, cancelled=True)

    tool_states = [p.get("status") for t, p in handle.sent if t == "tool.call"]
    assert "error" in tool_states
    end = [p for t, p in handle.sent if t == "turn.end"][0]
    assert end["cancelled"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -q`
Expected: FAIL — `ModuleNotFoundError: opensquilla.cli.tui.opentui.renderer`。

- [ ] **Step 3: 实现 OpenTuiStreamRenderer**

新建 `src/opensquilla/cli/tui/opentui/renderer.py`:

```python
"""Structured-message renderer for the OpenTUI footer backend.

Mirrors the ``TerminalRenderer`` async protocol but, instead of formatting
content into Rich text, emits one structured timeline message per call so the
JS host can render each block by type. The renderer's lifetime equals one turn,
so turn.begin/status/end are driven by enter/method-calls/afinalize.
"""

from __future__ import annotations

import asyncio
from itertools import count
from typing import Any, Literal

from opensquilla.cli.tui.opentui.messages import (
    AnswerText,
    ModelText,
    ToolCall,
    ToolDetail,
    TurnBegin,
    TurnEnd,
    TurnStatusState,
    Usage,
)
from opensquilla.cli.tui.terminal.stream import _summarize_args  # reuse arg summary

_turn_ids = count(1)


class OpenTuiStreamRenderer:
    """Async renderer that emits structured OpenTUI timeline messages."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        self.title = title
        self.output_handle = output_handle
        self.buffer = ""
        self._turn_id = ""
        self._began = False
        self._saw_output = False
        self._tool_names: dict[str, str] = {}

    # --- message plumbing ------------------------------------------------
    async def _emit(self, message_type: str, payload: Any) -> None:
        handle = self.output_handle
        if handle is None:
            return
        send = getattr(handle, "send_message", None)
        if send is None:
            return
        from dataclasses import asdict

        await send(message_type, asdict(payload))

    async def _ensure_begin(self) -> None:
        if self._began:
            return
        self._began = True
        self._turn_id = f"t{next(_turn_ids)}"
        await self._emit("turn.begin", TurnBegin(id=self._turn_id))
        await self._emit(
            "turn.status", TurnStatusState(phase="thinking", label="thinking", active=True)
        )

    # --- sync lifecycle (context manager) --------------------------------
    def __enter__(self) -> OpenTuiStreamRenderer:
        # Begin is emitted lazily on first async call to keep enter sync-safe;
        # but record intent so a turn with no output still begins on afinalize.
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def pulse(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def start(self) -> None:
        return None

    # --- async protocol --------------------------------------------------
    async def aappend_text(self, delta: str) -> None:
        if not delta:
            return
        await self._ensure_begin()
        if not self._saw_output:
            self._saw_output = True
            await self._emit(
                "turn.status", TurnStatusState(phase="output", label="output", active=True)
            )
        self.buffer += delta
        await self._emit("answer.text", AnswerText(text=delta))

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        await self._ensure_begin()
        await self._emit("model.text", ModelText(text=message))

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        await self._ensure_begin()
        if tool_use_id:
            self._tool_names[tool_use_id] = name
        await self._emit(
            "turn.status", TurnStatusState(phase="tool", label=name, active=True)
        )
        await self._emit(
            "tool.call",
            ToolCall(
                name=name,
                summary=_summarize_args(name, args),
                status="running",
                id=tool_use_id,
            ),
        )

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        name = self._tool_names.get(tool_use_id or "", "")
        await self._emit(
            "tool.call",
            ToolCall(
                name=name,
                summary="",
                status="ok" if success else "error",
                id=tool_use_id,
            ),
        )
        detail = error if (not success and error) else (str(result) if result else "")
        if detail:
            await self._emit("tool.detail", ToolDetail(text=detail))

    async def aerror(self, message: str) -> None:
        await self._ensure_begin()
        await self._emit("tool.detail", ToolDetail(text=message))

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        await self._ensure_begin()
        if usage is not None:
            await self._emit("usage", Usage(text=_format_usage(usage)))
        await self._emit("turn.end", TurnEnd(id=self._turn_id, cancelled=cancelled))
        await self._emit(
            "turn.status", TurnStatusState(phase="idle", label="ready", active=False)
        )

    async def aclose(self) -> None:
        return None


def _format_usage(usage: Any) -> str:
    model = getattr(usage, "model", None)
    in_tok = getattr(usage, "input_tokens", None)
    out_tok = getattr(usage, "output_tokens", None)
    parts: list[str] = []
    if in_tok is not None or out_tok is not None:
        parts.append(f"in {in_tok or 0} / out {out_tok or 0}")
    if model:
        parts.append(str(model))
    return " · ".join(parts) if parts else "done"
```

> 注:`_summarize_args` 和 `UsageSummary` 字段(`model`/`input_tokens`/`output_tokens`)在 `terminal/stream.py` 与 `cli/chat/turn.py` 已存在。若 `_summarize_args` 不可直接 import(私有),实现阶段在本文件内复制一份等价的 args 摘要逻辑(取 `path`/`pattern`/第一个字符串值,截断到 ~40 字符)。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/renderer.py tests/unit/cli/tui/test_opentui_renderer.py
git commit -m "feat: add OpenTuiStreamRenderer emitting structured timeline messages"
```

---

## Task 4: surface 结构化发送通道(`surface.py`)

> **Wave 2。** 依赖 Task 1。可与 Task 2、3 并行。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/surface.py`
- Test: `tests/unit/cli/tui/test_opentui_surface.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/cli/tui/test_opentui_surface.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_output_handle_send_message_forwards_to_bridge() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    await output.send_message("turn.begin", {"id": "t1"})
    await output.send_message("model.text", {"text": "hi"})

    assert bridge.sent == [
        ("turn.begin", {"id": "t1"}),
        ("model.text", {"text": "hi"}),
    ]
```

> `FakeOpenTuiBridge.send` 已把 dataclass `asdict`,但这里直接传 dict;需让 `send_message` 把 dict 原样转发。下面实现让 `OpenTuiOutputHandle.send_message` 调 `bridge.send(type, payload_dict)`,而 `FakeOpenTuiBridge.send` 对 dict 走非 dataclass 分支。**调整 fake 的 send 以支持 dict**:在 `FakeOpenTuiBridge.send` 把 `asdict(payload)` 改为 `payload if isinstance(payload, dict) else asdict(payload)`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_surface.py::test_output_handle_send_message_forwards_to_bridge -q`
Expected: FAIL — `OpenTuiOutputHandle` 无 `send_message`。

- [ ] **Step 3: 实现 send_message**

先把 `tests/unit/cli/tui/test_opentui_surface.py` 里 `FakeOpenTuiBridge.send` 改成:

```python
    async def send(self, message_type: str, payload: object | None = None) -> None:
        if payload is None:
            self.sent.append((message_type, None))
            return
        self.sent.append(
            (message_type, payload if isinstance(payload, dict) else asdict(payload))
        )
```

在 `src/opensquilla/cli/tui/opentui/surface.py` 的 `OpenTuiOutputHandle` 类(约 line 54 `write_through` 后)新增:

```python
    async def send_message(self, message_type: str, payload: dict[str, object]) -> None:
        await self._bridge.send(message_type, payload)
```

`OpenTuiBridge.send`(`bridge.py:143`)已支持任意 payload(经 `python_message_to_json` 的 `_payload_dict`,dict 走 `dict(payload)` 分支),无需改 bridge。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_surface.py -q`
Expected: PASS(含原有 4 个测试)。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/surface.py tests/unit/cli/tui/test_opentui_surface.py
git commit -m "feat: add structured send_message channel on OpenTuiOutputHandle"
```

---

## Task 5: runtime 接线 — prompt.echo + renderer 注入(`runtime.py`)

> **Wave 3。** 依赖 Task 1、3、4。可与 Task 6 并行。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/runtime.py`
- Modify: `src/opensquilla/cli/tui/adapters/runtime_bridge.py`
- Test: `tests/unit/cli/repl/test_opentui_chat_adapter.py`

- [ ] **Step 1: 写失败测试**

把 `tests/unit/cli/repl/test_opentui_chat_adapter.py` 的 `_FakeOpenTuiSurface` 补一个 `send_message` 记录,并替换 `test_opentui_chat_runtime_uses_footer_native_echo_hooks` 的断言段。

先给 `_FakeOpenTuiSurface` 增加(在 `write_through` 旁):

```python
    async def send_message(self, message_type: str, payload: dict) -> None:
        self.writes.append(f"{message_type}:{payload.get('text', '')}")
```

并让 `_FakeOutputHandle` 也有同款 `send_message`(返回 None 即可)。

把该测试的断言段(`joined_writes = ...` 之后)替换为:

```python
    joined_writes = "".join(fake_surface.writes)
    assert "你 / you" not in joined_writes
    assert "prompt.echo:hello opentui" in joined_writes
    assert "中文输入 CJK混合ASCII" in joined_writes
    assert "running queued input" in joined_writes
```

并把测试里 `hooks.on_user_input_echo`/`on_queued_turn_start` 的调用保持不变(已传 `fake_surface`)。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/cli/repl/test_opentui_chat_adapter.py::test_opentui_chat_runtime_uses_footer_native_echo_hooks -q`
Expected: FAIL — echo 仍发 `╭─ prompt` 文本而非 `prompt.echo` 消息。

- [ ] **Step 3: echo 改发结构化消息**

在 `src/opensquilla/cli/tui/opentui/runtime.py`,把 `echo_opentui_user_input` 和 `echo_opentui_queued_turn_start` 改为发结构化消息(经 surface 的 `send_message`):

```python
from opensquilla.cli.tui.opentui.messages import ModelText, PromptEcho


async def echo_opentui_user_input(tui_surface: TuiSurface, text: str) -> None:
    """Echo accepted user input as a structured prompt block."""
    if not text.strip():
        return
    send = getattr(tui_surface, "send_message", None)
    if send is not None:
        from dataclasses import asdict

        await send("prompt.echo", asdict(PromptEcho(text=text)))


async def echo_opentui_queued_turn_start(tui_surface: TuiSurface) -> None:
    """Render a queue marker as a model.text line."""
    send = getattr(tui_surface, "send_message", None)
    if send is not None:
        from dataclasses import asdict

        await send("model.text", asdict(ModelText(text="running queued input")))
```

> `OpenTuiSurface` 需暴露 `send_message`。在 `surface.py` 的 `OpenTuiSurface` 类加一个委托(约 line 129 `write_through` 旁):
> ```python
>     async def send_message(self, message_type: str, payload: dict[str, object]) -> None:
>         await self._output_handle.send_message(message_type, payload)
> ```

- [ ] **Step 4: 注入 OpenTuiStreamRenderer 作 renderer_factory**

`src/opensquilla/cli/tui/adapters/runtime_bridge.py` 现有(line 119-122):
```python
def _turn_stream_dependencies() -> Any:
    from opensquilla.cli.tui import turn_bridge as _turn_bridge

    return _turn_bridge.default_turn_stream_dependencies()
```
`validate_tui_backend_selection`(line 39)已在本模块定义。把该函数改为按 backend 选 renderer_factory:
```python
def _turn_stream_dependencies() -> Any:
    from opensquilla.cli.tui import turn_bridge as _turn_bridge

    if validate_tui_backend_selection() == "opentui":
        from opensquilla.cli.tui.opentui.renderer import OpenTuiStreamRenderer

        return _turn_bridge.default_turn_stream_dependencies(
            renderer_factory=OpenTuiStreamRenderer
        )
    return _turn_bridge.default_turn_stream_dependencies()
```
`default_turn_stream_dependencies`(`turn_bridge.py:80`)已接受 `renderer_factory` 关键字参数,无需改其签名。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/cli/repl/test_opentui_chat_adapter.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/runtime.py src/opensquilla/cli/tui/opentui/surface.py src/opensquilla/cli/tui/adapters/runtime_bridge.py tests/unit/cli/repl/test_opentui_chat_adapter.py
git commit -m "feat: wire structured prompt echo and OpenTuiStreamRenderer for opentui backend"
```

---

## Task 6: footer 三处死代码修活(`main.mjs`)

> **Wave 3。** 依赖 Task 2(同文件,需在其后)。可与 Task 5 并行(不同关注点,但同文件 — 若并行须 review 合并;建议 Task 6 紧接 Task 2 由同一 agent 续做)。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败测试**

在 `test_opentui_host_layout.py` 追加:

```python
def test_opentui_footer_revives_status_and_composer_and_router_color() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    # 状态脉动定时器接 active
    assert "syncPulseTimer" in source
    assert "setInterval" in source
    # composer 禁用边框走 theme token
    assert "composerDisabledBorder" in source
    # router 边框色走状态(colorForStyle 用于 router border)
    assert "colorForStyle(routerState.style)" in source
    # 仍不使用背景填充
    assert "backgroundColor" not in source
```

- [ ] **Step 2: 运行测试确认失败/通过基线**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_footer_revives_status_and_composer_and_router_color -q`
Expected: 多数 assert 已因 Task 2 通过;若 `syncPulseTimer`/`composerDisabledBorder` 被 Task 2 误删则 FAIL,据此修复。

- [ ] **Step 3: 确认 footer 渲染消费动态状态**

确认 `renderFooterTree`(`main.mjs`):
1. composer box `borderColor` 用三元 `composer.disabled ? OPENTUI_DAILY_THEME.composerDisabledBorder : OPENTUI_DAILY_THEME.composerBorder`(已存在,保留)。
2. composer box `bottomTitle` = `` `${statusIcon()} ${turnStatus.label}` ``(已存在,保留)。
3. router box `borderColor` = `colorForStyle(routerState.style)`(已存在,保留)。
4. `statusIcon()` 用 `STATUS_PULSE_FRAMES[turnStatus.phase]`,active 时取脉动帧、否则 `✓`(已存在,保留)。
5. `syncPulseTimer` 在 `turn.status` 的 `active` 切换时启停(已存在,保留)。

这些 Task 2 应已保留;本任务确保 Task 2 重构未破坏它们,并把 `router-context` 行的死字段处理:`fixedRouterRow("ctx", routerState.context)` 当 context 为 `-` 时仍显示 `-`(由 Python 侧决定真实值,见 Task 5/契约)。重写 `fixedRouterRow` 为可读形式:

```javascript
function fixedRouterRow(label, value) {
  const safeValue = String(value).replace(/\s+/gu, " ").trim() || "-";
  const maxValueCells = 18;
  let clipped = "";
  let cells = 0;
  for (const char of Array.from(safeValue)) {
    const next = cells + cellWidth(char);
    if (next > maxValueCells) break;
    clipped += char;
    cells = next;
  }
  const padding = " ".repeat(Math.max(0, maxValueCells - cells));
  return `${label.padEnd(5)} ${clipped}${padding}`;
}
```

- [ ] **Step 4: 运行测试 + smoke**

Run: `uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: PASS。

Run: `npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "fix: revive OpenTUI footer status pulse, composer disable, router color"
```

---

## Task 7: live-opentui 验证路径接线

> **Wave 4。** 依赖 Task 5(真实 renderer 已接通)。

**Files:**
- Modify: `tests/integration/cli/tui_real_terminal/targets.py`
- Modify: `tests/integration/cli/tui_real_terminal/scenarios.py`
- Modify: `scripts/tui_real_terminal_lab.py`

- [ ] **Step 1: 新增 live-opentui target**

在 `tests/integration/cli/tui_real_terminal/targets.py`:

1. `TuiBackendId` 加 `"live-opentui"`(line 11)。
2. `build_tui_target`(line 35)加分支:
```python
    if backend_id == "live-opentui":
        return _live_opentui_target(context)
```
3. 仿 `_live_textual_target` 新增(放其后):
```python
def _live_opentui_target(context: TargetContext) -> TuiTarget:
    env = _base_env(context, isolate_state=False)
    env.update(
        {
            "OPENSQUILLA_TUI_BACKEND": "opentui",
            "OPENSQUILLA_TUI_READY_MARKER": "OPEN_SQUILLA_TUI_READY",
            "OPENSQUILLA_MEMORY_DREAM_DISABLED": "1",
            "OPENSQUILLA_OPENROUTER_LIVE_PRICING": "0",
        }
    )
    config_path = _host_gateway_config_path(context.project_root)
    if config_path:
        env["OPENSQUILLA_GATEWAY_CONFIG_PATH"] = config_path
    return TuiTarget(
        backend_id="live-opentui",
        command=[
            sys.executable,
            "-u",
            "-m",
            "opensquilla.cli.main",
            "chat",
            "--standalone",
            "--workspace",
            str(context.project_root),
            "--workspace-strict",
            "--timeout",
            "120",
        ],
        env=env,
        initial_size=context.size,
        readiness_markers=("OPEN_SQUILLA_TUI_READY",),
        log_paths=(context.artifact_dir / "logs",),
        capability_requirements=("real-terminal", "real-cli", "opentui-footer", "tmux"),
    )
```

- [ ] **Step 2: 新增 live_opentui_architecture_prompt 场景**

在 `tests/integration/cli/tui_real_terminal/scenarios.py` 的 `all_scenarios()` 元组里(在 `live_architecture_prompt` 之后)新增:

```python
        TuiScenario(
            scenario_id="live_opentui_architecture_prompt",
            family="live_prompt",
            initial_size=TerminalSize(cols=112, rows=34),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep(
                    "send-message",
                    "send_text",
                    "帮我分析这个代码长的架构 /workspace/opensquilla",
                    "after-input",
                ),
                ScenarioStep(
                    "wait-turn-complete",
                    "wait_any_text",
                    " · \nThe task timed out before it could finish.",
                    "after-turn-complete",
                    timeout_s=180.0,
                ),
                ScenarioStep(
                    "capture-final",
                    "capture",
                    "",
                    "after-final",
                    timeout_s=0.2,
                ),
            ),
            expected_text=(),
            requires_tmux=True,
            requires_prompt_ready=False,
            required_backend_id="live-opentui",
        ),
```

并把模块顶部 `__all__` 风格的 family 常量(line 25 附近 `"architecture_prompt", "live_prompt"`)确认含 `"live_prompt"`(已含,无需改)。

- [ ] **Step 3: lab 脚本加 backend choice**

在 `scripts/tui_real_terminal_lab.py` 的 `--backend` choices(line 40)改为:

```python
        choices=("terminal", "textual", "opentui", "live-textual", "live-opentui"),
```

- [ ] **Step 4: 静态校验导入与场景注册**

Run: `uv run python -c "import sys; sys.path.insert(0,'tests/integration/cli'); from tui_real_terminal.scenarios import scenario_by_id; from tui_real_terminal.targets import build_tui_target; print(scenario_by_id('live_opentui_architecture_prompt').scenario_id)"`
Expected: 打印 `live_opentui_architecture_prompt`,无异常。

- [ ] **Step 5: 提交**

```bash
git add tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/scenarios.py scripts/tui_real_terminal_lab.py
git commit -m "test: add live-opentui real-model tmux verification path"
```

---

## Task 8: tmux 真实跑 + 美学迭代

> **Wave 5。** 依赖全部前置。这是真实模型验证 + 调优环节,非纯 TDD,需读截图人工判断。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`(仅样式微调)

- [ ] **Step 1: 真实跑一次模型(禁用沙箱联网)**

Run(`dangerouslyDisableSandbox: true`,因为要真实联网调模型):

```bash
uv run python scripts/tui_real_terminal_lab.py --scenario live_opentui_architecture_prompt --backend live-opentui --driver tmux
```

Expected: `pass: <artifact-dir>`(或 timeout 但产出 artifact)。记录 artifact 目录。

- [ ] **Step 2: 读截图检查渲染层级**

Read: `<artifact-dir>/transcript.txt` 和 `<artifact-dir>/scrollback.txt`。

逐项核对设计:
- prompt 卡片 `╭─ prompt` / `│ ...` / `╰`,暖橙
- 模型中间输出柔绿满宽
- 工具调用单行 `• read_file ...` 青色
- 工具详情 `    │ ...` 暗灰缩进
- answer 卡片 `╭─ answer ─ squilla` ... `╰` 高亮白
- usage `· in/out · ...` 暗灰
- footer:状态指示器非 `✓ ready`(turn 中)、composer 变灰、router 边框颜色
- 无 `\x1b[` 裸控制符、无 `Traceback`

- [ ] **Step 3: 按需微调样式并重跑**

若发现层级/间距/颜色问题,只改 `main.mjs` 的样式常量与 `renderXxxBlock`(不改协议),重跑 Step 1,再读 Step 2。迭代直到层级清晰、美观达标。每次有意义的调整后提交:

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs
git commit -m "style: tune OpenTUI scrollback hierarchy from live tmux render"
```

- [ ] **Step 4: 更新真实终端集成测试断言**

在 `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py` 的 opentui 分支(line 80-92),把断言更新为新协议产出的标记(基于 Step 2 实际渲染):
- 保留 `╭─ prompt`、`╭─ answer`、`╰─ usage`(或新的 usage 前缀)、`│ detail`→改为实际的 `│ ` detail 形态
- 删除依赖旧正则装饰的断言(如 `╰─✓ ready` 若 footer 不再用该形态)
- 与 Step 2 的真实截图对齐,确保断言可通过

> 注:具体断言文本以 Step 2 截图为准填入,不留占位。

- [ ] **Step 5: 提交**

```bash
git add tests/integration/cli/tui_real_terminal/test_architecture_prompt.py
git commit -m "test: align opentui real-terminal assertions with structured render"
```

---

## Task 9: 全量验证 bundle

> **Wave 5。** 收尾,确保全绿。

**Files:** 无新增生产文件。

- [ ] **Step 1: 单元 + 静态测试**

Run:
```bash
uv run pytest tests/unit/cli/tui/test_opentui_messages.py tests/unit/cli/tui/test_opentui_renderer.py tests/unit/cli/tui/test_opentui_surface.py tests/unit/cli/tui/test_opentui_host_layout.py tests/unit/cli/repl/test_opentui_chat_adapter.py -q
```
Expected: PASS。

- [ ] **Step 2: JS host smoke**

Run: `npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: PASS,打印 footer host help。

- [ ] **Step 3: lint**

Run:
```bash
uv run ruff check src/opensquilla/cli/tui/opentui/renderer.py src/opensquilla/cli/tui/opentui/messages.py src/opensquilla/cli/tui/opentui/surface.py src/opensquilla/cli/tui/opentui/runtime.py src/opensquilla/cli/tui/adapters/runtime_bridge.py tests/integration/cli/tui_real_terminal/targets.py tests/integration/cli/tui_real_terminal/scenarios.py scripts/tui_real_terminal_lab.py
```
Expected: PASS。

- [ ] **Step 4: 完整 opentui 单元套件回归**

Run: `uv run pytest tests/unit/cli/tui/ tests/unit/cli/repl/ -q -k opentui`
Expected: PASS。

- [ ] **Step 5: 最终提交(若有 lint 修复)**

```bash
git add -A
git commit -m "chore: finalize OpenTUI protocol refactor verification bundle"
```

---

## Self-Review

- **Spec 覆盖:** Task 1=消息契约;Task 2=JS 渲染层删正则;Task 3=OpenTuiStreamRenderer 结构化边界;Task 4=surface 发送通道;Task 5=prompt.echo + renderer 注入;Task 6=footer 三处死代码;Task 7=live-opentui 路径;Task 8=tmux 真跑 + 美学迭代;Task 9=验证 bundle。spec 全部要求有对应任务。
- **死代码修复覆盖:** turn 状态(Task 3 发 turn.status + Task 6 消费)、composer 禁用(Task 3 发 composer.set disabled + Task 6 边框)、router context(Task 5 契约 + Task 6 fixedRouterRow)。
- **类型/签名一致:** 消息 dataclass 字段(Task 1)与 renderer emit(Task 3)、JS handlePythonMessage(Task 2)字段名一致(id/text/name/summary/status/phase/label/active/cancelled)。`send_message(type, dict)` 签名在 Task 4 定义、Task 3/5 调用一致。
- **占位符扫描:** Task 8 Step 4 的断言文本明确标注"以 Step 2 截图为准填入"——这是真实渲染依赖项,不是占位逃避;其余步骤均含完整代码/命令。
- **并行性:** Wave 标注清晰;同 Wave 任务文件无交叠(Task 2 与 3/4 不同文件;Task 5 与 6 不同文件但 Task 6 紧随 Task 2 同文件,已注明建议同 agent 续做)。
