# OpenTUI Fullscreen Conversation View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **并行与多 agent 执行策略:** 这是一次较串行的大重构(渲染层重写)。任务按 Wave 分组:同 Wave 内无依赖、可派发并行 subagent;Wave 间有依赖必须按序。实现可调用 codex mcp(model `gpt-5.5`,`model_reasoning_effort: "xhigh"`,sandbox `workspace-write`)。**注意:codex 自带的 commit hook 会强加 Lore 正文 + `Co-authored-by: OmX` trailer;每次 codex 提交后在主会话用 `git commit --amend -m "<原消息>"` 修正。** uv 测试需 `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache` 且 Bash `dangerouslyDisableSandbox: true`。
>
> **Wave 划分:**
> - **Wave 1(串行,基础):** Task 1 骨架切换(alt-screen + ScrollBox + 输入 Box)。后续全部依赖它。
> - **Wave 2(串行,依赖 W1):** Task 2 TurnView + timeline 节点原地更新。
> - **Wave 3(并行,依赖 W2):** Task 3 MarkdownRenderable 接入 answer、Task 5 Python 协议微调 —— 不同文件,可并行。
> - **Wave 4(依赖 W2):** Task 4 输入区迁移(composer 光标/历史 + router HUD)。可与 Wave 3 并行(不同关注点,但同改 main.mjs,建议紧接 Task 2 由同一 agent 续做以免冲突)。
> - **Wave 5(串行,依赖全部):** Task 6 真实 tmux 验证 + 视觉调优、Task 7 全量验证 bundle。

**Goal:** 把 OpenTUI TUI 重构为 alternate-screen 全屏 + 单 ScrollBox 视口架构,当前 turn 在 ScrollBox 内可原地重绘(工具节点 `◑`→`✓`/`✗`、answer 流式 markdown),用 OpenTUI 内置 ScrollBox/MarkdownRenderable,实现自由滚动 + 实时更新 + markdown 可视化。

**Architecture:** `screenMode:"alternate-screen"`;一个 ScrollBox(`stickyStart:"bottom"`, `viewportCulling`)装所有 turn,下方固定输入 Box;每个 turn 是 ScrollBox 里的 TurnView(prompt 卡片 + timeline 节点 + answer MarkdownRenderable + usage),节点/answer 原地重绘;Python 侧 OpenTuiStreamRenderer 协议复用(微调 tool.call running + 去 answer 行缓冲)。

**Tech Stack:** OpenTUI/Bun(BoxRenderable / TextRenderable / ScrollBoxRenderable / MarkdownRenderable / SyntaxStyle)、Python asyncio、pytest、tmux real-terminal harness、ruff。

**已验证前提(probe 通过):** alt-screen 模式下 tmux `capture-pane -p` 能抓到内容;完整 Box 边框渲染正确;`new BoxRenderable(renderer,{...})` + `renderer.root.add(...)` 用法成立。`SyntaxStyle.create()` 无参工厂可用。

---

## File Structure

- Modify `src/opensquilla/cli/tui/opentui/package/src/main.mjs`:重写渲染层 —— alt-screen 启动、ScrollBox 容器、TurnView、timeline 节点、answer MarkdownRenderable、输入区迁移。保留 `OPENTUI_DAILY_THEME`、`stripTerminalControls`、`cellWidth`、键盘/IPC 框架、footer 的 composer/router 渲染逻辑(移入新布局)。
- Modify `src/opensquilla/cli/tui/opentui/renderer.py`:`atool_start` 恢复发 `tool.call(running)`;`aappend_text` 去行缓冲。
- Modify `tests/unit/cli/tui/test_opentui_host_layout.py`:锁新结构标识符。
- Modify `tests/unit/cli/tui/test_opentui_renderer.py`:tool.call running 恢复、answer 不行缓冲。
- Modify `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py`:opentui 断言对齐新渲染(Task 6,据真实截图)。

---

## Task 1: 骨架切换 — alt-screen + ScrollBox + 输入 Box

> **Wave 1。** 基础,后续全部依赖。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败的静态测试**

把 `tests/unit/cli/tui/test_opentui_host_layout.py` 的 `test_opentui_footer_uses_reference_plugin_layout_contract` 替换为新结构契约:

```python
def test_opentui_host_uses_fullscreen_scrollbox_layout() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert 'screenMode: "alternate-screen"' in source
    assert "ScrollBoxRenderable" in source
    assert 'stickyStart: "bottom"' in source
    assert "viewportCulling" in source
    assert 'id: "composer-box"' in source
    assert 'id: "router-plugin"' in source
    # split-footer / writeToScrollback 不再是主路径
    assert 'screenMode: "split-footer"' not in source
    assert "writeToScrollback" not in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_host_uses_fullscreen_scrollbox_layout -q`
Expected: FAIL — 仍是 split-footer。

- [ ] **Step 3: 重写 main() 与布局骨架**

在 `main.mjs`:

(A) 顶部 import 增加 ScrollBox:
```javascript
let ScrollBoxRenderable;
```
并在 `main()` 的动态 import 改为:
```javascript
  ({ Box, Text, TextRenderable, ScrollBoxRenderable, createCliRenderer } = await import("@opentui/core"));
```
(`Box`/`Text` 是 JSX 风格工厂,保留;新增 `ScrollBoxRenderable` 类。)

(B) `createCliRenderer` 配置改为:
```javascript
  renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
  });
```

(C) 新增模块级布局引用:
```javascript
let conversationBox;   // ScrollBoxRenderable, 装所有 turn
let inputBox;          // 底部固定输入区 (composer + router)
```

(D) 新增 `buildLayout()`,创建 ScrollBox + 输入区,挂到 `renderer.root`:
```javascript
function buildLayout() {
  const height = renderer.terminalHeight ?? 24;
  const inputHeight = FOOTER_HEIGHT; // 6

  conversationBox = new ScrollBoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: Math.max(1, height - inputHeight),
    stickyScroll: true,
    stickyStart: "bottom",
    scrollY: true,
    scrollX: false,
    viewportCulling: true,
    rootOptions: { backgroundColor: undefined },
  });
  renderer.root.add(conversationBox);

  inputBox = new BoxRenderable(renderer, {
    id: "input-region",
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: inputHeight,
  });
  renderer.root.add(inputBox);

  rerenderInputRegion();
}
```

> 注:`Box`/`Text` 在旧代码是工厂函数(返回 vnode)。新架构用 `BoxRenderable`/`TextRenderable` 类实例(`new BoxRenderable(renderer, {...})`),与 probe 验证一致。把动态 import 同时取出工厂和类:`Box, Text`(工厂,footer 树仍可用)和 `BoxRenderable, TextRenderable, ScrollBoxRenderable`(类)。实际实现统一用类实例 + `.add()`,移除对工厂 `Box()/Text()` 的依赖。修正动态 import:
> ```javascript
> ({ BoxRenderable, TextRenderable, ScrollBoxRenderable, createCliRenderer } = await import("@opentui/core"));
> ```
> 并把模块级 `let Box, Text;` 改为 `let BoxRenderable, TextRenderable, ScrollBoxRenderable;`。

(E) `rerenderInputRegion()`:把现有 `renderFooterTree` 的 composer + router 渲染逻辑迁移为在 `inputBox` 内创建 composer/router 子 Box(用 BoxRenderable/TextRenderable 类)。**本任务先放一个最小占位**(composer 输入行 + router 框),完整迁移在 Task 4:
```javascript
function rerenderInputRegion() {
  if (!inputBox) return;
  for (const child of inputBox.getChildren?.() ?? []) inputBox.remove?.(child.id);
  const cursor = !composer.disabled && cursorVisible ? "▏" : " ";
  const composerLine = inputText || composer.text;
  const text = composerLine ? `${composerLine}${cursor}` : `${cursor}${composer.placeholder}`;
  const composerNode = new BoxRenderable(renderer, {
    id: "composer-box", position: "absolute", left: 1, right: 34, bottom: 1, height: 4,
    borderStyle: "rounded",
    borderColor: composer.disabled ? OPENTUI_DAILY_THEME.composerDisabledBorder : OPENTUI_DAILY_THEME.composerBorder,
    bottomTitle: `${statusIcon()} ${turnStatus.label}`, bottomTitleAlignment: "left",
    paddingLeft: 1, paddingRight: 1, flexDirection: "column", justifyContent: "center",
  });
  composerNode.add(new TextRenderable(renderer, {
    id: "composer-text", content: text,
    fg: composerLine ? OPENTUI_DAILY_THEME.text : OPENTUI_DAILY_THEME.muted,
  }));
  inputBox.add(composerNode);

  const routerNode = new BoxRenderable(renderer, {
    id: "router-plugin", position: "absolute", right: 1, bottom: 0, width: 31, height: FOOTER_HEIGHT,
    borderStyle: "rounded", borderColor: colorForStyle(routerState.style),
    title: " router ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexDirection: "column",
  });
  routerNode.add(new TextRenderable(renderer, { id: "router-model", content: fixedRouterRow("model", routerState.model), fg: OPENTUI_DAILY_THEME.text }));
  routerNode.add(new TextRenderable(renderer, { id: "router-route", content: fixedRouterRow("route", routerState.route), fg: OPENTUI_DAILY_THEME.routeText }));
  routerNode.add(new TextRenderable(renderer, { id: "router-saving", content: fixedRouterRow("save", routerState.saving), fg: OPENTUI_DAILY_THEME.savingText }));
  routerNode.add(new TextRenderable(renderer, { id: "router-context", content: fixedRouterRow("ctx", routerState.context), fg: OPENTUI_DAILY_THEME.routerWarning }));
  inputBox.add(routerNode);
  renderer.requestRender?.();
}
```
把旧 `renderFooterTree`/`rerenderFooter` 的调用点全部替换为 `rerenderInputRegion`。删除 `renderFooterTree`、旧 `rerenderFooter`、`writeToScrollback`/`writeScrollbackBlock`/`renderPromptBlock`/`renderModelText`/`renderToolCall`/`renderToolDetail`/`renderAnswerText`/`renderAnswerClose`/`renderUsage`/`cardTopRule`/`cardBottomRule`/`padLinesForScrollback`/`continuationPrefixForLine`/`wrapText`/`appendHardWrappedToken`(scrollback 时代的产物;TurnView 在 Task 2 用 Renderable 树替代)。**保留** `OPENTUI_DAILY_THEME`、`STATUS_PULSE_FRAMES`、`statusIcon`、`syncPulseTimer`、`startCursorBlink`、`wakeCursor`、`colorForStyle`、`fixedRouterRow`、`cellWidth`、`textWidth`、`stripTerminalControls`、键盘处理、IPC、`handlePythonMessage` 框架。

(F) `main()` 里把 `rerenderFooter()` 改为 `buildLayout()`;resize 监听改为重算 `conversationBox`/`inputBox` 高度后 `rerenderInputRegion()`:
```javascript
  renderer.on?.("resize", () => {
    const h = renderer.terminalHeight ?? 24;
    if (conversationBox) conversationBox.height = Math.max(1, h - FOOTER_HEIGHT);
    rerenderInputRegion();
    const width = renderer.terminalWidth ?? 0;
    if (width && h) sendHostMessage({ type: "resize", width, height: h });
  });
```

(G) `handlePythonMessage` 里 scrollback/turn 相关分支**先改成占位 no-op 或最小文本**(Task 2 实现 TurnView 后接通)。`scrollback.write` 分支:把文本作为一个临时 Text 加进 conversationBox:
```javascript
    case "scrollback.write": {
      const node = new TextRenderable(renderer, { id: `sb-${scrollbackSeq++}`, content: stripTerminalControls(String(message.text ?? "")), fg: OPENTUI_DAILY_THEME.muted });
      conversationBox.add(node);
      renderer.requestRender?.();
      return;
    }
```
`prompt.echo`/`model.text`/`tool.call`/`tool.detail`/`answer.text`/`turn.begin`/`turn.end`/`usage` 分支暂时各自加一个临时 Text 到 conversationBox(占位,Task 2 替换为 TurnView)。

- [ ] **Step 4: 运行静态测试 + JS 校验 + alt-screen probe**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_host_uses_fullscreen_scrollbox_layout -q`
Expected: PASS。

Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs`
Expected: 无输出(语法正确)。

Run(smoke): `npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: PASS(`--help` 在 import @opentui/core 前退出,仍工作)。

- [ ] **Step 5: tmux 起一次确认能渲染(冒烟)**

用 lab 的 fake opentui 跑 launch 场景,确认 alt-screen 能起、ready marker 出现:
Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run python scripts/tui_real_terminal_lab.py --scenario launch_input_loop --backend opentui --driver tmux`
Expected: `pass:` 或至少 artifact 里 ready marker 出现。若 capture 失败,检查 alt-screen 起动(probe 已证明 capture 可行)。

- [ ] **Step 6: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "refactor: switch OpenTUI host to alternate-screen ScrollBox layout"
```

---

## Task 2: TurnView + timeline 节点原地更新

> **Wave 2。** 依赖 Task 1 的 ScrollBox 骨架。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败的静态测试**

追加:
```python
def test_opentui_host_has_turnview_with_inplace_tool_nodes() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "class TurnView" in source
    assert "addTool" in source
    assert "finishTool" in source
    assert "appendAnswer" in source
    assert "setUsage" in source
    # 工具节点状态符号
    assert "STATUS_PULSE_FRAMES" in source
    assert "✓" in source and "✗" in source
```

- [ ] **Step 2: 运行确认失败**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_host_has_turnview_with_inplace_tool_nodes -q`
Expected: FAIL — 无 `class TurnView`。

- [ ] **Step 3: 实现 TurnView 类**

在 `main.mjs` 增加(模块级):
```javascript
let activeTurn = null;          // 当前 TurnView
const toolPulseNodes = new Set(); // 运行中的工具节点,统一脉动

class TurnView {
  constructor(id) {
    this.id = id;
    this.toolNodes = new Map();   // tool id -> TextRenderable
    this.sawAnswer = false;
    this.box = new BoxRenderable(renderer, {
      id: `turn-${id}`, flexDirection: "column", paddingLeft: 1, paddingRight: 1,
    });
    conversationBox.add(this.box);
  }

  _line(id, content, fg) {
    const node = new TextRenderable(renderer, { id: `turn-${this.id}-${id}`, content, fg });
    this.box.add(node);
    return node;
  }

  setPrompt(text) {
    this._line("p-top", "╭─ prompt ─────", OPENTUI_DAILY_THEME.promptAccent);
    for (const [i, ln] of String(text).split("\n").entries()) {
      this._line(`p-${i}`, `│ ${ln}`, OPENTUI_DAILY_THEME.promptAccent);
    }
    this._line("p-bot", "╰─────", OPENTUI_DAILY_THEME.promptAccent);
    this._line("rail-top", "│", OPENTUI_DAILY_THEME.faint);
    renderer.requestRender?.();
  }

  addTool(toolId, name, summary) {
    const tail = summary ? ` ${summary}` : "";
    const node = this._line(`tool-${toolId}`, `${statusIcon()} ${name}${tail}`, OPENTUI_DAILY_THEME.toolAccent);
    node._toolName = name;
    node._toolTail = tail;
    this.toolNodes.set(toolId, node);
    toolPulseNodes.add(node);
    renderer.requestRender?.();
  }

  refreshToolPulse() {
    const frames = STATUS_PULSE_FRAMES.tool;
    const glyph = frames[pulseFrame % frames.length];
    for (const node of toolPulseNodes) {
      node.content = `${glyph} ${node._toolName}${node._toolTail}`;
    }
  }

  finishTool(toolId, status, name, summary) {
    const node = this.toolNodes.get(toolId);
    const glyph = status === "error" ? "✗" : "✓";
    const fg = status === "error" ? OPENTUI_DAILY_THEME.routerError : OPENTUI_DAILY_THEME.answerAccent;
    const tail = summary ? ` ${summary}` : (node?._toolTail ?? "");
    const finalName = name || node?._toolName || "";
    if (node) {
      node.content = `${glyph} ${finalName}${tail}`;
      node.fg = fg;
      toolPulseNodes.delete(node);
    } else {
      this._line(`tool-${toolId}`, `${glyph} ${finalName}${tail}`, fg);
    }
    renderer.requestRender?.();
  }

  addToolDetail(text) {
    const all = String(text).split("\n");
    const max = 3;
    all.slice(0, max).forEach((ln, i) => this._line(`detail-${this._detailSeq = (this._detailSeq ?? 0) + 1}-${i}`, `│   ${ln}`, OPENTUI_DAILY_THEME.detailText));
    if (all.length > max) this._line(`detail-more-${this._detailSeq}`, `│   … ${all.length - max} more lines`, OPENTUI_DAILY_THEME.detailText);
    renderer.requestRender?.();
  }

  appendAnswer(delta) {
    if (!this.sawAnswer) {
      this.sawAnswer = true;
      this._line("a-top", "╭─ answer ─ squilla ─────", OPENTUI_DAILY_THEME.frame ?? OPENTUI_DAILY_THEME.muted);
      this.answerNode = this._line("a-body", "", OPENTUI_DAILY_THEME.text);
      this._answerText = "";
    }
    this._answerText += delta;
    // 阶段 2:纯文本累积(Task 3 换 MarkdownRenderable)
    this.answerNode.content = this._answerText.split("\n").map((l) => `│ ${l}`).join("\n");
    renderer.requestRender?.();
  }

  finishAnswer(cancelled) {
    if (cancelled) {
      this._line("a-cancel", "│ turn cancelled", OPENTUI_DAILY_THEME.muted);
    }
    if (this.sawAnswer) this._line("a-bot", "╰─────", OPENTUI_DAILY_THEME.frame ?? OPENTUI_DAILY_THEME.muted);
    renderer.requestRender?.();
  }

  setUsage(text) {
    this._line("usage", `  · ${text}`, OPENTUI_DAILY_THEME.muted);
    renderer.requestRender?.();
  }
}
```

> `OPENTUI_DAILY_THEME` 若无 `faint`/`frame` 键,新增 `faint: "#3E4A57"`(已有)、`frame: "#5a6b7a"`。

(B) 把 Task 1 占位的 `handlePythonMessage` turn 分支接到 TurnView:
```javascript
    case "turn.begin":
      activeTurn = new TurnView(String(message.id ?? scrollbackSeq++));
      return;
    case "prompt.echo":
      activeTurn?.setPrompt(String(message.text ?? ""));
      return;
    case "model.text":
      activeTurn?._line(`model-${scrollbackSeq++}`, String(message.text ?? ""), OPENTUI_DAILY_THEME.answerAccent);
      return;
    case "tool.call": {
      const id = String(message.id ?? "");
      const status = String(message.status ?? "running");
      if (status === "running") activeTurn?.addTool(id, String(message.name ?? ""), String(message.summary ?? ""));
      else activeTurn?.finishTool(id, status, String(message.name ?? ""), String(message.summary ?? ""));
      return;
    }
    case "tool.detail":
      activeTurn?.addToolDetail(String(message.text ?? ""));
      return;
    case "answer.text":
      activeTurn?.appendAnswer(String(message.text ?? ""));
      return;
    case "turn.end":
      activeTurn?.finishAnswer(Boolean(message.cancelled ?? false));
      return;
    case "usage":
      activeTurn?.setUsage(String(message.text ?? ""));
      return;
```

(C) 工具脉动:`syncPulseTimer` 的 interval 回调里,除了 footer 状态,也刷新工具节点。在 `syncPulseTimer` 的 `setInterval` 回调中加 `activeTurn?.refreshToolPulse();`。同时确保 `syncPulseTimer` 在有运行中工具时也启动(不只 turnStatus.active)——简化:turn.status active 时脉动已开,工具运行期间 turnStatus 通常是 active(tool phase),复用即可。

- [ ] **Step 4: 运行测试 + JS 校验**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: PASS。
Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs`
Expected: 无输出。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "feat: render turns as TurnView with in-place timeline tool nodes"
```

---

## Task 3: answer 接入 MarkdownRenderable

> **Wave 3。** 依赖 Task 2。可与 Task 5 并行(不同文件)。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败的静态测试**

追加:
```python
def test_opentui_answer_uses_markdown_renderable() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "MarkdownRenderable" in source
    assert "SyntaxStyle" in source
    assert "streaming" in source
```

- [ ] **Step 2: 运行确认失败**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_answer_uses_markdown_renderable -q`
Expected: FAIL。

- [ ] **Step 3: answer 改用 MarkdownRenderable**

(A) 动态 import 增加:
```javascript
  ({ BoxRenderable, TextRenderable, ScrollBoxRenderable, MarkdownRenderable, SyntaxStyle, createCliRenderer } = await import("@opentui/core"));
```
模块级声明 `let MarkdownRenderable, SyntaxStyle, syntaxStyle;`。`main()` 里构造一次共享样式:`syntaxStyle = SyntaxStyle.create();`

(B) TurnView.appendAnswer 改为喂 MarkdownRenderable:
```javascript
  appendAnswer(delta) {
    if (!this.sawAnswer) {
      this.sawAnswer = true;
      this._line("a-top", "╭─ answer ─ squilla ─────", OPENTUI_DAILY_THEME.frame);
      this.answerMd = new MarkdownRenderable(renderer, {
        id: `turn-${this.id}-md`,
        content: "",
        streaming: true,
        conceal: true,
        syntaxStyle,
        fg: OPENTUI_DAILY_THEME.text,
        tableOptions: { style: "columns" },
        paddingLeft: 1,
      });
      this.box.add(this.answerMd);
      this._answerText = "";
    }
    this._answerText += delta;
    this.answerMd.content = this._answerText;
    renderer.requestRender?.();
  }

  finishAnswer(cancelled) {
    if (cancelled) this._line("a-cancel", "│ turn cancelled", OPENTUI_DAILY_THEME.muted);
    if (this.answerMd) this.answerMd.streaming = false;  // 定稿
    if (this.sawAnswer) this._line("a-bot", "╰─────", OPENTUI_DAILY_THEME.frame);
    renderer.requestRender?.();
  }
```

> markdown 内容不再手动加 `│ ` 前缀(MarkdownRenderable 自己排版);左导轨视觉由 answer 卡片的 `╭─`/`╰─` 头尾 + MarkdownRenderable 的 `paddingLeft` 体现。若需要左竖线,给 answerMd 包一个 `BoxRenderable({ borderStyle:"rounded", border:["left"] ... })`——实现时按真实渲染效果定(Task 6 调优)。

- [ ] **Step 4: 测试 + 校验**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: PASS。
Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs`
Expected: 无输出。

- [ ] **Step 5: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "feat: render answer as streaming markdown via MarkdownRenderable"
```

---

## Task 4: 输入区完整迁移 + 键盘/滚动路由

> **Wave 4。** 依赖 Task 1(同改 main.mjs,建议紧接 Task 2/3 由同一 agent 续做)。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`
- Test: `tests/unit/cli/tui/test_opentui_host_layout.py`

- [ ] **Step 1: 写失败的静态测试**

追加:
```python
def test_opentui_input_region_and_scroll_routing() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    # composer 光标 + 历史保留
    assert "inputHistory" in source
    assert "cursorVisible" in source
    # 滚动路由: 翻页键 -> ScrollBox
    assert "scrollBy" in source or "scrollTo" in source
    assert 'name === "pageup"' in source or 'name === "pagedown"' in source
```

- [ ] **Step 2: 运行确认失败**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py::test_opentui_input_region_and_scroll_routing -q`
Expected: FAIL — 无 scrollBy/pageup 路由。

- [ ] **Step 3: 键盘路由加滚动键**

在 `installKeyboardHandlers` 的 keypress 回调里,在历史(up/down)分支之后、printable 之前,加翻页滚动:
```javascript
    if (key.name === "pageup") {
      conversationBox?.scrollBy({ x: 0, y: -10 });
      renderer.requestRender?.();
      return;
    }
    if (key.name === "pagedown") {
      conversationBox?.scrollBy({ x: 0, y: 10 });
      renderer.requestRender?.();
      return;
    }
```
(上下键保持历史导航不变;翻页键给 ScrollBox 滚动。鼠标滚轮由 ScrollBox 的 onMouseEvent 内置处理,无需手动接线——但 `useMouse` 默认开启时生效,alt-screen 下保留默认 mouse 处理。)

- [ ] **Step 4: 确认输入区渲染完整**

确认 `rerenderInputRegion`(Task 1 已迁移 composer + router)显示:composer 光标闪烁(`▏`)、占位/输入文本、禁用态边框、状态指示器 bottomTitle、router HUD 四行 + 状态边框色。这些 Task 1 已搬入;本任务确保未遗漏,并确认 `startCursorBlink`/`syncPulseTimer` 的 rerender 回调指向 `rerenderInputRegion`(不是已删的 `rerenderFooter`)。全局替换残留的 `rerenderFooter()` 调用为 `rerenderInputRegion()`。

- [ ] **Step 5: 测试 + 校验**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_host_layout.py -q`
Expected: PASS。
Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs`
Expected: 无输出。

- [ ] **Step 6: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs tests/unit/cli/tui/test_opentui_host_layout.py
git commit -m "feat: migrate input region and route page keys to ScrollBox scroll"
```

---

## Task 5: Python 协议微调 — tool.call running + 去 answer 行缓冲

> **Wave 3。** 依赖 Task 2 的契约(JS 用同 id 原地更新)。可与 Task 3 并行(不同文件)。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/renderer.py`
- Test: `tests/unit/cli/tui/test_opentui_renderer.py`

- [ ] **Step 1: 改失败的测试**

`tests/unit/cli/tui/test_opentui_renderer.py` 的 `test_renderer_emits_turn_lifecycle_and_blocks`:把 tool.call 断言改回含 running:
```python
    tool_calls = [p for t, p in handle.sent if t == "tool.call"]
    assert [p.get("status") for p in tool_calls] == ["running", "ok"]
    assert all(p.get("id") == "c1" for p in tool_calls)  # 同 id 原地更新
```
并新增 answer 不行缓冲的断言(单次 aappend_text 不含换行也立即发):
```python
    answer_texts = [p.get("text") for t, p in handle.sent if t == "answer.text"]
    assert "架构分四层" in "".join(answer_texts)
```

- [ ] **Step 2: 运行确认失败**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -q`
Expected: FAIL — 当前 running 不发、answer 行缓冲。

- [ ] **Step 3: 恢复 tool.call running**

`src/opensquilla/cli/tui/opentui/renderer.py` 的 `atool_start`,在记录后发 running 的 tool.call:
```python
    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        await self._ensure_begin()
        summary = _summarize_args(name, args)
        if tool_use_id:
            self._tool_calls[tool_use_id] = (name, summary)
        await self._emit(
            "turn.status", TurnStatusState(phase="tool", label=name, active=True)
        )
        await self._emit(
            "tool.call",
            ToolCall(name=name, summary=summary, status="running", id=tool_use_id),
        )
```
`atool_finished` 不变(已发 ok/error + 同 id + summary)。

- [ ] **Step 4: 去 answer 行缓冲**

`aappend_text` 改为直接发原始 delta(markdown 文本在 JS 累积):
```python
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
```
删除 `_answer_buf` 字段、`_flush_answer` 方法,以及 `afinalize` 里的 `await self._flush_answer()` 调用。

- [ ] **Step 5: 测试 + lint**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/test_opentui_renderer.py -q`
Expected: PASS。
Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run ruff check src/opensquilla/cli/tui/opentui/renderer.py`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/opensquilla/cli/tui/opentui/renderer.py tests/unit/cli/tui/test_opentui_renderer.py
git commit -m "feat: emit running tool.call and unbuffered answer deltas for fullscreen host"
```

---

## Task 6: 真实 tmux 验证 + 视觉调优

> **Wave 5。** 依赖全部前置。真实模型验证 + 调优,读截图人工判断。

**Files:**
- Modify: `src/opensquilla/cli/tui/opentui/package/src/main.mjs`(仅样式微调)
- Modify: `tests/integration/cli/tui_real_terminal/test_architecture_prompt.py`

- [ ] **Step 1: 真实跑(禁用沙箱联网)**

Run(`dangerouslyDisableSandbox: true`):
```bash
UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run python scripts/tui_real_terminal_lab.py --scenario live_opentui_architecture_prompt --backend live-opentui --driver tmux
```
Expected: `pass: <artifact-dir>`。记录目录。

- [ ] **Step 2: 读截图核对**

Read `<artifact-dir>/transcript.txt`(alt-screen 内容)。逐项核对:
- prompt 卡片(左导轨)
- timeline 节点:工具行 `✓/✗ name summary`(完成态;运行态在过渡帧可能是 `◑`)
- tool detail `│   ...` 缩进对齐、最多 3 行
- answer markdown 渲染:标题/列表/代码块/表格可见且有样式(不是裸 markdown 符号)
- answer 卡片头尾 `╭─ answer`/`╰─`
- usage 在卡片外
- 无 `Traceback`

- [ ] **Step 3: 按需微调样式重跑**

发现层级/间距/颜色/markdown 渲染问题,只改 `main.mjs` 样式/TurnView(不改协议),重跑 Step 1 再读。迭代到美观达标。每次有意义调整后提交:
```bash
git add src/opensquilla/cli/tui/opentui/package/src/main.mjs
git commit -m "style: tune fullscreen conversation rendering from live tmux"
```

- [ ] **Step 4: 更新真实终端集成断言**

`tests/integration/cli/tui_real_terminal/test_architecture_prompt.py` 的 opentui 分支(及/或新增 live-opentui 分支),据 Step 2 真实截图更新断言:保留 `╭─ prompt`、`╭─ answer`、工具 `✓ ` 标记、markdown 渲染特征(如标题文字、`──` 表格列等真实出现的内容)。删除不再出现的旧标记。以真实截图为准填入,不留占位。

- [ ] **Step 5: 提交**

```bash
git add tests/integration/cli/tui_real_terminal/test_architecture_prompt.py
git commit -m "test: align real-terminal assertions with fullscreen conversation render"
```

---

## Task 7: 全量验证 bundle

> **Wave 5。** 收尾。

**Files:** 无新增生产文件。

- [ ] **Step 1: opentui 单元/静态套件**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run pytest tests/unit/cli/tui/ tests/unit/cli/repl/ -q -k opentui`
Expected: PASS。

- [ ] **Step 2: JS smoke + 语法**

Run: `npm run --prefix src/opensquilla/cli/tui/opentui/package smoke`
Expected: PASS。
Run: `node --check src/opensquilla/cli/tui/opentui/package/src/main.mjs`
Expected: 无输出。

- [ ] **Step 3: lint**

Run: `UV_CACHE_DIR=/private/tmp/opensquilla-uv-cache uv run ruff check src/opensquilla/cli/tui/opentui/renderer.py src/opensquilla/cli/tui/opentui/surface.py src/opensquilla/cli/tui/opentui/runtime.py`
Expected: PASS。

- [ ] **Step 4: 最终提交(若有 lint 修复)**

```bash
git add -A
git commit -m "chore: finalize fullscreen conversation verification bundle"
```

---

## Self-Review

- **Spec 覆盖:** Task 1=alt-screen+ScrollBox 骨架(spec 架构);Task 2=TurnView+timeline 节点原地(工具表现/原地更新);Task 3=MarkdownRenderable(markdown 全元素);Task 4=输入区+滚动路由(滚动/键盘);Task 5=Python 协议微调(tool.call running/去行缓冲);Task 6=真实验证+调优(测试策略/风险);Task 7=验证 bundle。spec 各节有对应任务。
- **占位符扫描:** Task 6 Step 4 断言"据真实截图填入"是真实渲染依赖,非占位逃避;其余步骤均含完整代码/命令。Task 3 的"左竖线包 Box 实现时按效果定"标注为 Task 6 调优——这是视觉微调,不是逻辑占位。
- **类型/签名一致:** TurnView 方法名(setPrompt/addTool/finishTool/addToolDetail/appendAnswer/finishAnswer/setUsage)跨 Task 2/3 一致;tool.call 字段(name/summary/status/id)跨 JS(Task 2)和 Python(Task 5)一致;`conversationBox`/`inputBox`/`activeTurn`/`rerenderInputRegion`/`syntaxStyle` 命名跨任务一致。
- **并行性:** Wave 1→2 串行(骨架→TurnView);Wave 3 的 Task 3(main.mjs)与 Task 5(renderer.py)不同文件可并行;Task 4 同改 main.mjs,注明紧接 Task 2/3 同 agent 续做避免冲突。
- **风险:** alt-screen+tmux capture 已 probe 验证通过(写入头部前提)。
