# OpenTUI TUI 协议级重构与视觉层级设计

> 状态:已批准设计,待写实现计划。
> 分支:`codex/tui-frontend`

## 目标

把 OpenTUI footer TUI 从"Python 写纯文本 scrollback、JS 用正则猜语义"的脆弱架构,重构为"Python 发结构化语义事件、JS 按类型精确渲染"的协议级架构。同时:

1. 修复三处死代码:turn 状态指示器(永远停在 `✓ ready`)、composer 禁用态(turn 中不变灰)、router context 字段(永远 `-`)。
2. 落地经确认的 scrollback 视觉层级:块内类 Claude Code 紧凑折叠,大调用块(一个 turn)收尾用边框卡片区分,颜色编码内容类型。
3. 通过真实调用一次模型的 tmux 渲染验证,迭代调优界面美观度。

## 背景与问题

当前实现(已审查)存在以下问题:

- **P0 — turn 状态指示器是死代码**:`main.mjs` 实现了完整的 `STATUS_PULSE_FRAMES` 脉动动画、`syncPulseTimer`、`statusIcon()` 动态取帧,但 Python 侧从不发送 `turn.status` 消息(全仓库无发送方),`TurnStatusState` dataclass 定义却无人使用。footer 底部永远显示 `✓ ready`。
- **P0 — composer 禁用态是死代码**:`composer.set` 只在 surface 启动时发一次(仅 placeholder),`disabled`/`text` 从不动态更新,turn 进行中输入框不变灰,`composerDisabledBorder` 是死颜色。
- **P1 — router context 永远 `-`**:`_router_plugin_state_from_toolbar` 三个返回分支全部硬编码 `context="-"`。
- **P1 — 多行 prompt 破坏装饰**:`echo_opentui_user_input` 写 `╭─ prompt\n│ {text}\n╰`,若 text 含换行,装饰器只保留以 `│` 开头的续行,多行第 2 行被误分类。
- **架构性脆弱 — 正则猜语义**:`decorateDailyTimelineScrollback`/`classifyDailyTimelineLine` 用一组正则去"装饰"Python 写过来的纯文本(如 `/(\bin\s*\/\s*\d+...|\$[0-9]|aggregate)/` 判定 usage 行),会误伤含 `$5` 或 "aggregate" 的正常答案。
- **细节问题**:`scrollback-${Date.now()}` 同毫秒 id 碰撞;`router-route`/`router-saving` 颜色硬编码未走 theme;`fixedRouterRow` padding 表达式难读;bun/node 术语混乱。

经确认,真实 CLI 渲染路径为:`OPENSQUILLA_TUI_BACKEND=opentui` → `runtime_bridge._runtime_bridge_for_selected_backend` → `opentui_bridge.run_concurrent_repl` → `run_opentui_chat_runtime` → footer host。`OpenTuiReplayRenderer` 仅用于 headless 评测,不在真实路径上。

## 设计决策(已确认)

| 决策点 | 选择 |
|---|---|
| 重构边界 | 协议级重构 |
| 结构化边界画在哪层 | 富消息协议(方案 A):每类内容独立消息类型,JS 不做文本分类 |
| scrollback 层级 | 类 Claude Code 折叠;大调用块(turn)收尾用边框卡片;颜色编码内容类型 |
| footer 布局 | A — composer 左 + router 右下角窄框,重做内容 |
| 颜色语义 | 两者结合:router 边框走状态色(绿/黄/红),框内字段走中性色 |
| tmux 验证 | lab 脚本截图迭代,且真实跑一次模型 |
| 真实调用 | 直接跑(用本机 `~/.opensquilla/config.toml`,禁用沙箱联网) |

## 架构

```
Python 侧                          IPC (fd 3/4, JSON lines)        JS/Bun 侧 (main.mjs)
─────────                          ──────────────────────         ───────────────────
OpenTuiStreamRenderer              turn.begin/status/end
  (renderer_factory 注入)          prompt.echo / model.text       renderXxxBlock(payload)
  ├─ __enter__   → turn.begin  ────────────────────────────────▶  按消息 type 精确渲染
  ├─ aappend_text → answer.text                                    (无正则分类)
  ├─ atool_start  → tool.call(running)                            轻量块状态机:
  ├─ atool_finished → tool.call(ok/error) + tool.detail            currentTurn={id,sawAnswer}
  ├─ astatus      → model.text                                    footer:
  ├─ afinalize    → usage + turn.end                                composer(disabled 切换)
  └─ (经 OpenTuiOutputHandle 发送)                                  状态脉动(turn.status 驱动)
OpenTuiOutputHandle                                                router HUD(边框状态色)
  └─ set_toolbar/invalidate → router.update
```

## 组件设计

### 1. 协议消息契约(`messages.py`)

新增结构化 Python→JS 消息,每种 scrollback 内容独立类型:

| 消息 type | 字段 | 语义 / 颜色 |
|---|---|---|
| `turn.begin` | `id` | 大调用块开始 |
| `prompt.echo` | `text` | 用户输入回显 → 暖橙 `#FFB86C` 边框卡片 |
| `model.text` | `text` | 模型中间输出 → 柔绿 `#9AD18B`、满宽、无边框 |
| `tool.call` | `name, summary, status(running/ok/error), id` | 工具调用 → 青 `#69D2E7` 单行 |
| `tool.detail` | `text` | 工具输出/思考 → 暗灰 `#667385`、缩进、`│` 前导 |
| `answer.text` | `text` | 最终回答 → 高亮白 `#F4F7FB`,包在 `╭─ answer` 卡片内 |
| `usage` | `text` | 用量 → 暗灰单行 |
| `turn.end` | `id, cancelled` | 块收尾,JS 据此闭合 answer 卡片底边 |
| `turn.status` | `phase(thinking/tool/output/idle), label, active` | footer 状态指示器 |
| `composer.set` | `placeholder, text, disabled` | footer 输入框 |
| `router.update` | `model, route, saving, context, style` | footer router HUD |

JS→Python(保留):`ready` / `input.submit` / `input.cancel` / `input.eof` / `resize` / `error`。

设计要点:
- 一个 turn = 一个大块,`turn.begin`/`turn.end` 框住整段(模型输出→工具×N→模型输出→工具×M→最终回答),answer 卡片在块尾画底边。
- 旧 `scrollback.write`(纯文本)保留但降级,仅用于 ready marker 等非语义文本。
- 保留并补全 `ScrollbackWrite`/`RouterPluginState`/`ComposerState`/`TurnStatusState` 的验证。

### 2. JS 渲染层(`main.mjs`)

删除整套正则猜测管线:`decorateDailyTimelineScrollback`、`classifyDailyTimelineLine`、`decorateDailyToolLine`、`decorateDailyDetailLine`、`colorForDailyScrollback`、`isDailySemanticScrollback`、`trimDailySemanticBlankEdges`、`wrapWidthForDailyLine`、`continuationPrefixForLine`。

保留:`stripTerminalControls`(防御控制符)、`wrapText`/`cellWidth`/CJK 宽字符处理。

新增按消息类型的渲染分发:

| 消息 | 渲染 |
|---|---|
| `prompt.echo` | `╭─ prompt` / `│ <每行>` / `╰` 卡片,暖橙;多行逐行 `│ ` 前导 |
| `model.text` | 满宽柔绿,无边框,wrap 后写入 |
| `tool.call` | `  • <name> <summary>` 青色单行;error 前导 `✗` 红 |
| `tool.detail` | `    │ <text>` 暗灰缩进 |
| `answer.text` | turn 内累积;首次画 `╭─ answer ─ squilla` 顶边,行 `│ ` 包裹高亮白 |
| `turn.end` | 本块出现过 answer 则画 `╰` 闭合;cancelled 画 `╰─ turn cancelled` |
| `usage` | `  · <text>` 暗灰单行 |

轻量块状态机:`currentTurn = { id, sawAnswer }`,由 Python begin/end 明确驱动。

细节修复:scrollback id 改单调计数器 `scrollback-${seq++}`;硬编码色收进 `OPENTUI_DAILY_THEME`。

### 3. Python 输出层(新增 `OpenTuiStreamRenderer` + `surface.py` + `runtime.py`)

**已确认的架构约束**:`StreamingRenderer`(`terminal/stream.py`)把工具调用、状态、答案、用量都在自己内部用 Rich 格式化成纯文本/ANSI payload,再通过 `output_handle.write_through`/`aappend_text` 发出 —— 这正是当前 JS 侧必须用正则反向猜语义的根源。真实 turn 路径通过 `stream_deps.renderer_factory(output_handle=tui_output)` 创建 renderer(`chat/turn_stream.py:663/967/1245`),默认工厂是 `TerminalRenderer`(`turn_stream_defaults.py:114`),注入点在 `runtime_bridge.py:122` 的 `default_turn_stream_dependencies()`。

**决策(已确认)**:结构化边界放在 renderer 层。新增 `OpenTuiStreamRenderer`(`opentui/renderer.py`),镜像 `TerminalRenderer` 的接口(`__init__(title, output_handle)`、`__enter__/__exit__`、`aappend_text`、`atool_start`、`atool_finished`、`astatus`、`aerror`、`afinalize`、`aclose`、`stream_output`),但每个方法**不格式化文本,而是通过 output_handle 发结构化消息**。当 backend 为 opentui 时,把它作为 `renderer_factory` 注入。`fake_opentui_app.py` 也改用它。

`OpenTuiStreamRenderer` 方法 → 消息映射:

| 方法 | 发送消息 |
|---|---|
| `__enter__` / 首次写入前 | `turn.begin(id)` + `turn.status(thinking, active=true)` + `composer.set(disabled=true)` |
| `astatus(msg, style)` | `model.text(msg)` |
| `aappend_text(delta)` | 首次置 `turn.status(output)`;`answer.text(delta)` |
| `atool_start(name, args, id)` | `turn.status(tool, label=name)` + `tool.call(name, summary, running, id)`,summary 由 `_summarize_args` 提炼 |
| `atool_finished(id, success, result, ...)` | `tool.call(... ok/error, id)`;若有 result 文本发 `tool.detail` |
| `aerror(msg)` | `tool.detail(msg)` 或 `model.text`,style=error |
| `afinalize(usage, cancelled)` | `usage(text)` + `turn.end(id, cancelled)` + `turn.status(idle, "ready", active=false)` + `composer.set(disabled=false)` |

`OpenTuiOutputHandle`(保留)负责底层消息发送通道:`set_toolbar`/`invalidate`→`router.update`(保留);`write_through`→降级 `scrollback.write`(ready marker);新增结构化发送方法(如 `send_turn_begin`/`send_tool_call` 等)供 renderer 调用,或 renderer 直接持有 bridge。turn id 由 renderer 内部单调计数器分配。

turn 生命周期由 `OpenTuiStreamRenderer` 的方法调用**自然驱动**(见上表),不靠新增 backend hook。

**已确认约束**:`TuiRuntimeHooks`(`backend/contracts.py`)只有 `on_user_input_echo`、`on_queued_turn_start`、`clear_current_cancel`、`notice`、`on_cancel_active_turn`、`expose_surface`、`clear_exposed_surface`,没有 turn/工具钩子。所以 prompt.echo 仍挂 `on_user_input_echo`,而 turn.begin/status/end 落在 renderer 的 `__enter__`/各 `aXxx`/`afinalize` 上 —— renderer 的生命周期恰好等于一个 turn,这比新增 backend hook 更内聚,且不触碰 textual/terminal 后端。

`echo_opentui_user_input` 改发 `prompt.echo` 结构化消息(不再拼 `╭─ prompt` 文本)。`router context` 接真实用量或显式 `-`。

### 4. footer 重做(布局 A)

composer(左):边框色随 `disabled` 切换(启用 `#77B7FF` / 禁用 `#354453`);底边标题 = `${statusIcon()} ${label}`;占位符/文本由 `composer.set` 动态更新。

状态指示器(嵌 composer 底边):空闲 `✓ ready`(静态);thinking `∙•●•`、tool `◌◔◑◕`+label、output `◇◆` 脉动;`syncPulseTimer` 180ms 仅 active 时运行。

router HUD(右下角窄框,颜色语义两者结合):边框色走状态(绿 `#73D0A7` 正常 / 黄 `#F6C177` fallback降级警告 / 红 `#FF7B8A` 错误);框内字段标签暗灰、值中性白;`ctx` 接真实用量或 `-`。

保留 `fixedRouterRow` CJK 截断,重写为可读形式(`padding = maxValueCells - cells`)。

布局示意:
```
  · in 12.4k / out 1.8k · $0.04
╭──────────────────────────────────╮ ╭─ router ───────────╮   边框绿/黄/红
│ 分析一下登录模块的安全性          │ │ model claude-opus-4 │
│ ▏                                  │ │ route standard 96%  │
╰─◑ read_file──────────────────────╯ │ save  42%           │   状态脉动
                                      ╰────────────────────╯
```

## 数据流

1. 用户在 footer 输入 → JS 发 `input.submit` → Python `next_line` 返回文本。
2. `on_user_input_echo` 触发 → `prompt.echo` → JS 画 prompt 卡片。
3. `renderer_factory(output_handle)` 创建 `OpenTuiStreamRenderer`,`__enter__` → `turn.begin` + `turn.status(thinking)` + `composer.set(disabled)`。
4. 模型流式 → `astatus`→`model.text` / `aappend_text`(首次置 `turn.status(output)`)→`answer.text`;工具 → `atool_start`(置 `turn.status(tool)`)/`atool_finished`→`tool.call`,输出→`tool.detail`;router 决策 → `set_toolbar`→`router.update`。
5. `afinalize` → `usage` + `turn.end` + `turn.status(idle)` + `composer.set(enabled)` → JS 闭合 answer 卡片。

## 错误处理

- JS 收到未知 type → 发 `error` 回 Python(保留现有 `writeError`)。
- Python 解析非法消息 → `HostToPythonMessageError`(保留)。
- 工具 error → `tool.call status=error`,前导 `✗` 红色。
- turn cancelled → `turn.end cancelled=true`,JS 画 `╰─ turn cancelled`。
- 控制符防御:`stripTerminalControls` 仍施加于所有写入文本。

## 测试策略

新增 live-opentui 真实模型验证路径:
- `targets.py` 新增 `_live_opentui_target`(仿 `_live_textual_target`,`OPENSQUILLA_TUI_BACKEND=opentui`、`isolate_state=False`、本机 config、`chat --standalone --workspace <root> --timeout 120`)。
- `build_tui_target` 注册 `live-opentui`;lab `--backend` choices 加 `live-opentui`。
- 新增 `live_opentui_architecture_prompt` 场景(`required_backend_id="live-opentui"`,`requires_tmux=True`)。

迭代验证循环(执行者):
1. `uv run python scripts/tui_real_terminal_lab.py --scenario live_opentui_architecture_prompt --backend live-opentui --driver tmux`(禁用沙箱联网,真实调一次模型)
2. 读 `.artifacts/.../transcript.txt` + `scrollback.txt`
3. 对照设计检查:prompt 卡片、工具单行、detail 缩进、answer 卡片收尾、footer 状态、颜色层级
4. 调 `main.mjs` 样式 → 重跑 → 再看,直到美观达标

单元/静态测试(TDD 先红后绿):
- `test_opentui_messages.py`:新消息类型序列化/解析往返
- `test_opentui_host_layout.py`:锁渲染函数名、theme tokens、`backgroundColor` 仍不存在、脉动帧表存在
- `test_opentui_chat_adapter.py`:`prompt.echo` 结构化、turn 生命周期发 `turn.status`/`composer.set(disabled)`、多行逐行 `│`
- `test_opentui_renderer.py`(新增):`OpenTuiStreamRenderer` 各 `aXxx`/`__enter__`/`afinalize` 发对应结构化消息(turn.begin/status/end、model.text、tool.call、answer.text、usage)
- `test_opentui_surface.py`:`OpenTuiOutputHandle` 的结构化发送方法与 `router.update`/降级 `scrollback.write`
- `test_architecture_prompt.py`:opentui 分支断言更新为新协议产出标记

JS host smoke:`npm run smoke` 仍通过。Lint:改动 Python 文件过 `ruff`。

## 验收标准

- 三处死代码修活:状态指示器随 turn 切换并脉动、composer turn 中变灰、router 边框随状态变色。
- 多行输入不破坏装饰;正则误判消失(无正则分类)。
- live-opentui tmux 真实跑通,截图显示完整层级(prompt/model/tool/detail/answer 卡片/usage/footer)。
- 全部单元/静态测试 + lint 绿;`npm run smoke` 通过。

## 范围外(YAGNI)

- 不改 textual/terminal 后端的渲染。
- 不引入新依赖。
- 不做 scrollback 区域的交互(选择、复制)——保持 shell 原生回滚。
- 不改 split-footer 模式与 fd-based IPC 机制。
