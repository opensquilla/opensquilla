# OpenTUI 全屏对话视图重构设计

> 状态:已批准设计,待写实现计划。
> 分支:`codex/tui-frontend`

## 目标

把 OpenTUI TUI 从"split-footer + 终端原生 scrollback(append-only)"重构为"alternate-screen 全屏 + OpenTUI ScrollBox 单视口",从根本上解决一批共性问题,并新增 answer 卡片的 markdown 可视化渲染。

具体解决:
1. **工具调用打印两行**(append-only 无法把 running→done 合并到一行)→ 全屏下节点可原地从闪烁 `◑` 变 `✓`/`✗`。
2. **工具块与 answer 块没分开** → 工具做成连接 prompt 和 answer 的 timeline 竖线,节点是工具状态符号本身。
3. **续行缩进错位、横线太短、resize 空行/右框错位** → 全屏下宽度稳定 + Box 布局自适应,统一由组件处理。
4. **answer 是 markdown 但显示为纯文本** → 用 OpenTUI 内置 `MarkdownRenderable` 流式渲染全部 markdown 元素。
5. **不能自由滚动(卡在底部)** → ScrollBox 自管虚拟滚动(滚轮/翻页键),`stickyStart:"bottom"` 贴底但上滚保持。

## 背景:为什么转向全屏

调研了 Claude Code 的实现:它**不依赖终端原生 scrollback**,而是 alt-screen 全屏接管 + 自己实现虚拟滚动(VirtualMessageList + 双缓冲 cell diff),所以任意 cell 可原地更新、流式 60fps、自由滚动。

OpenTUI(同为 react-reconciler 风格的终端 UI 框架,带 Yoga 布局、cell 缓冲)提供了同类能力的现成组件:
- `screenMode: "alternate-screen"` 全屏模式。
- `ScrollBoxRenderable`:`stickyStart`、`scrollBy/scrollTo`、滚动条、`viewportCulling`(虚拟滚动)、鼠标滚轮 + 键盘。
- `MarkdownRenderable`:`content` setter + `streaming` 模式、`conceal` 隐藏标记符、`syntaxStyle` 代码高亮、内置标题/列表/引用/代码块/表格(TextTable, grid|columns)/水平线/链接。
- `Input`/`Textarea`、`Box`/`Text`。

当前 split-footer + `writeToScrollback` 受 append-only 约束(行写入不可改),是上述问题的共同根因。全屏 + ScrollBox 让"当前 turn 任意行可原地重绘"天然成立。

**代价(已接受)**:退出后终端不保留对话历史(alt-screen 固有,与 Claude Code 一致);放弃终端原生 scrollback,滚动改为 app 内 ScrollBox。

## 设计决策(已确认)

| 决策点 | 选择 |
|---|---|
| 屏幕模型 | alternate-screen 全屏,单 ScrollBox 视口 |
| 活动 turn 渲染 | 当前 turn 在 ScrollBox 内,节点/answer 可原地重绘;完成后留在 ScrollBox 成为历史(无需 commit) |
| 工具表现 | timeline 竖线 + 节点;节点 = 工具状态符号本身(运行 `◑` 脉动 → `✓`/`✗`),原地变化 |
| markdown | OpenTUI MarkdownRenderable,streaming + conceal + daily SyntaxStyle,全元素(标题/加粗/斜体/行内码/列表/引用/水平线/代码块/表格/链接) |
| 卡片边界 | **保留左侧导轨风格**(`╭─ title ─` 顶 + `│` 左导轨 + `╰─` 底,无右框)。横线长度由 Box 宽度自适应 |
| 滚动 | ScrollBox `stickyStart:"bottom"` + viewportCulling;滚轮/翻页键滚动 |
| 键盘 | 上下键 = composer 历史导航;翻页键/滚轮 = ScrollBox 滚动;composer 持键盘焦点 |
| 配色 | 沿用现有 OPENTUI_DAILY_THEME |

## 架构

```
┌─ alt-screen (OpenTUI 全屏) ───────────────┐
│ ScrollBox (stickyStart:"bottom", viewportCulling) │
│   TurnView (turn N-1, 历史)                │
│   TurnView (turn N, 当前 — 可原地重绘)      │
│     ╭─ prompt ─────                        │
│     │ <text>                               │
│     ╰─────                                 │
│     │  (timeline 主干)                     │
│     ◑ list_dir  src/   ← 运行,脉动          │
│     │   src/ · tests/ · ... 14 more         │
│     ✓ read_file  protocol.py                │
│     │                                      │
│     ╭─ answer ─ squilla ─────              │
│     │ (MarkdownRenderable, streaming)       │
│     ╰─────                                 │
│     · in/out · $...                         │
│ ──────────────────────────────────────── │
│ composer + router (固定底部 Box)           │
└────────────────────────────────────────────┘
```

## 组件设计

### ConversationView (JS)
持有 ScrollBox(`stickyStart:"bottom"`, `viewportCulling:true`)。管理 TurnView 列表。`turn.begin` 新建 TurnView 加入 ScrollBox;持有当前 TurnView 引用供后续消息更新。

### TurnView (JS class)
持有一个 turn 的渲染子树(Box, column)与 model:
- `setPrompt(text)`:渲染 prompt 卡片(左导轨,title `prompt`)。
- `addTool(id, name, summary)`:在 timeline 加节点 Text,内容 `◑ name summary`(running)。记录 id→节点。
- `finishTool(id, status, summary)`:**原地**改该节点为 `✓/✗ name summary`,触发重绘。
- `addToolDetail(id, text)`:节点下挂 detail 行 `│   <text>`(暗灰,最多 3 行)。
- `appendAnswer(delta)`:累积到 answer 的 MarkdownRenderable `content`(streaming)。
- `finishAnswer()`:MarkdownRenderable `streaming=false` 定稿,画 answer 卡片底边。
- `setUsage(text)`:usage 行。

### TimelineNode 渲染
主干 `│`(muted)。节点行行首是状态符号:运行 `◑`(脉动青,统一脉动定时器驱动所有运行节点同步)、成功 `✓`(绿)、失败 `✗`(红)。detail 行 `│   <预览>`(缩进由 Box padding 处理,不靠正则)。

### answer markdown (MarkdownRenderable)
`new MarkdownRenderable(ctx, { content:"", streaming:true, conceal:true, syntaxStyle:<daily>, fg:theme.text, tableOptions:{style:"columns"} })`。流式期间 `content +=` 增量;`turn.end` 后 `streaming=false`。配一个 daily 主题的 SyntaxStyle(代码高亮配色)。

### 输入区 (composer + router)
ScrollBox 下方固定 Box。沿用现有:composer 左(光标闪烁 `▏`、上下键历史栈、禁用态变灰)、router HUD 右下(边框状态色、model/route/save/ctx)。

## 数据流与协议

Python `OpenTuiStreamRenderer` 仍发结构化消息(协议基本复用):

| 消息 | JS 处理 |
|---|---|
| `turn.begin{id}` | ConversationView 新建 TurnView |
| `prompt.echo{text}` | TurnView.setPrompt |
| `tool.call{name,summary,status,id}` | running→addTool;ok/error→finishTool(**同 id 原地更新**) |
| `tool.detail{text,id?}` | TurnView.addToolDetail |
| `answer.text{text}` | TurnView.appendAnswer(累积喂 MarkdownRenderable) |
| `turn.end{id,cancelled}` | TurnView.finishAnswer + timeline 收尾 |
| `usage{text}` | TurnView.setUsage |
| `turn.status{phase,label,active}` | footer 状态指示器(脉动) |
| `composer.set` / `router.update` | footer |
| `resize{width,height}` | 视口/ScrollBox 重算 |

**Python 侧微调**:
- `atool_start` 恢复发 `tool.call(status="running", id=...)`(之前为避免 append-only 双行删掉了;全屏下用同 id 原地更新,需要 running 节点)。
- `aappend_text` 去掉行缓冲(行缓冲是 append-only 产物),直接发原始 delta;markdown 文本在 JS 侧累积喂给 MarkdownRenderable。

## 实现阶段

1. **骨架切换**:`alternate-screen` + ScrollBox + 底部输入 Box;空对话能起、能输入、能滚动。
2. **TurnView**:prompt 卡片 + timeline 节点(原地 running→✓/✗)+ usage;answer 先用纯文本 Text。
3. **MarkdownRenderable 接入**:answer 改用 MarkdownRenderable + streaming + daily SyntaxStyle。
4. **输入区迁移**:composer 光标/历史 + router HUD 移入新布局。
5. **协议微调**:Python `atool_start` 恢复 running、`aappend_text` 去行缓冲。

## 测试策略

- **静态/单元**:`test_opentui_host_layout.py` 锁新结构(`alternate-screen`、`ScrollBox`、`MarkdownRenderable`、TurnView 关键标识符;split-footer/writeToScrollback 不再是主路径)。renderer 单元测试调整(tool.call running 恢复、answer 不行缓冲)。
- **真实 tmux**:live-opentui 场景跑真实模型,读截图验证三卡片、timeline 节点状态、markdown 渲染、滚动。**早期验证 alt-screen + tmux capture-pane 兼容性**(passthrough 曾崩,alt-screen 需确认 capture 可工作)。
- **JS smoke**:`--help` 仍通过。
- **lint**:ruff 改动的 Python 文件。

## 风险

- **alt-screen + tmux capture 兼容性**:阶段 1 必须先验证 capture-pane 能抓到 alt-screen 内容,否则 lab 验证链断。
- **ScrollBox + 流式 MarkdownRenderable 性能**:viewportCulling 缓解;长对话 + 高频流式需观察。
- **键盘焦点路由**:composer 打字 vs ScrollBox 滚动键的分发,上下键归历史、翻页键归滚动。
- **退出无历史**:alt-screen 固有,已接受。

## 范围外 (YAGNI)

- 不改 textual/terminal 后端。
- 不引入新依赖(marked / OpenTUI 组件均为现成)。
- 不实现 IME 拼音中间态(OpenTUI keyInput 无 composition 事件,已知受限)。
- 不做对话历史持久化(退出即清,同 Claude Code)。
