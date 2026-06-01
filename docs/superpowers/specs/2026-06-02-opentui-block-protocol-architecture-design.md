# OpenTUI 信息架构重构:语义 Block 协议 + 声明式渲染

**日期**: 2026-06-02
**分支**: codex/tui-frontend
**状态**: 设计待评审

## Context（为什么重构）

OpenTUI 全屏 TUI 上线后,用户连续报告了十几个视觉/交互问题(answer 叠字、工具 detail 不归组、timeline 竖线断裂、中间输出闪青卡、detail 折行超出竖线、竖线颜色不统一……)。每修一个就冒出一个新的,陷入打地鼠循环。

根因不是单个 bug,而是**架构层面的四个病灶**:

1. **职责揉成一团**:JS 侧 `TurnView`(单类 ~700 行的 main.mjs 核心)同时负责消息接收、节点创建、缩进计算、配色、宽度截断、卡片升/降级、并行工具定位。方法之间通过 5-6 个 `this.answerXxx` 共享引用纠缠,手动同步增删节点,极易漏删/留悬空 → 叠字、残留、闪烁。
2. **"乐观渲染 + 事后修补"是脆弱模式**:answer 文本先乐观画成青卡,遇到工具调用再撤掉重画成紫色中间块(demote)。本质是 **host 在"猜"一段文本是中间输出还是最终回答**,因为消息协议没把语义讲清。每个边界情况都要单独打补丁。
3. **样式散落在字符串拼接里**:`│` / `✱` / `╭─` / 缩进 `TOOL_INDENT` / 颜色 / clip 宽度,全散在各方法的模板字符串中。改一个视觉细节要在多处同步改,漏改就不一致(竖线颜色不统一即源于此)。
4. **消息协议语义模糊**:`answer.text` / `answer.demote` / `model.text` / `tool.detail` 边界不清,是被需求逼出来的临时拼凑。

**一句话根因**:信息的「语义」(这是什么:prompt/工具/工具输出/中间思考/最终答案)与「呈现」(怎么画:颜色/缩进/竖线/卡片)没有分离。Python 知道语义但消息没讲清,host 不知道语义只能乐观猜测,再用一堆事后修补硬凑视觉。

**目标**:从架构上彻底分离语义与呈现,消灭乐观猜测和事后修补,让信息架构干净、解耦、可独立理解与测试。

## 架构总览

```
引擎事件 → Python OpenTuiStreamRenderer ──(语义 Block 协议, JSON lines)──> JS host
              [定义语义: 这是哪种 block]                    [定义呈现: 这种 block 怎么画]
```

三层职责严格分离:
- **Python 渲染层**:把引擎事件翻译成**语义明确的 block 生命周期消息**。它知道一段文本是中间思考(后面跟工具)还是最终回答(turn 收尾),并用不同 block kind 发出 —— 不让 host 猜。
- **协议层**(messages.py + 对应 JS 解析):6 种 block kind × 4 个生命周期动作。是两侧唯一的契约。
- **JS host 渲染层**:BlockRegistry 按 kind 路由到独立 Renderer;统一样式原语层提供 `│`/卡片/缩进/截断/配色;TurnView 退化为纯容器。

## 协议设计

### Block kind（6 种语义类型）

| kind | 语义 | 呈现(由 host Renderer 决定) |
|------|------|------|
| `prompt` | 用户输入 | 橙色卡片 `╭─ prompt ─/│ text/╰─` |
| `thinking` | 工具调用之间的中间模型输出 | 紫色 ✱ 块,timeline 缩进,上下 │ rail |
| `tool` | 一次工具调用(含其 output/detail) | 青色节点 `◑→✓/✗ name args` + 灰色 detail 归在内部,timeline 缩进 |
| `answer` | 最终回答 | 青色左边框卡片 `╭─ answer ─/│ markdown/╰─`,流式即青卡 |
| `usage` | token/模型统计 | 灰色单行 `· in/out · model` |
| `error` | turn 级错误 | 错误色块 |

**关键**:`thinking` 和 `answer` 是**两种不同 kind**,从 Python 源头区分(Python 知道文本段是被 tool_use_start 结束=thinking,还是 turn 收尾=answer)。host 不再猜测、不再 demote。`tool` 的 output 归在 tool block 内部,天然解决归组,不需要 toolId 跨节点关联。

### 生命周期动作（4 个）

每条消息形如 `{type: "block.<action>", id, kind?, ...}`:

- `block.begin {id, kind, meta?}` — 开一个块。`meta` 携带 kind 专属初始数据(prompt 的文本、tool 的 name/args、answer 无需)。
- `block.append {id, delta}` — 流式追加内容(thinking/answer 的 token delta;tool 追加一段 output)。
- `block.update {id, patch}` — 原地改状态(tool: running→done/error,带 status/elapsed)。
- `block.end {id}` — 块定稿(answer 收尾停止 streaming、tool 标记完成)。

turn 级仍保留:`turn.begin/end`、`turn.status`、`composer.set`、`router.update`、`usage`(可表示为 usage block 或保留独立,见下)。

**典型 turn 消息流**(用户问天气,模型先思考→搜索→思考→回答):
```
turn.begin
block.begin {id:b1, kind:prompt, meta:{text:"今天天气"}}  block.end b1
block.begin {id:b2, kind:thinking}  block.append b2 "Let me check..."  block.end b2   ← 被 tool 结束=thinking
block.begin {id:b3, kind:tool, meta:{name:web_search, args:"..."}}
block.append b3 "<output line>"  block.update b3 {status:ok}  block.end b3
block.begin {id:b4, kind:answer}  block.append b4 "根据..."(流式青卡)  ... block.end b4   ← turn 收尾=answer
usage / turn.end
```

## Python 渲染层（OpenTuiStreamRenderer 重写）

职责:维护"当前 turn 的 block 状态机",把引擎调用(aappend_text/atool_start/atool_finished/astatus/afinalize)翻译成 block 协议。

关键状态机逻辑(消灭乐观猜测的核心):
- 模型文本 delta 到来 → 若当前没有打开的文本 block,**先不决定 kind**,缓冲并开一个 pending 文本 block,流式 append。
- `atool_start` 到来 → 当前 pending 文本 block 被"封口"为 `thinking`(因为后面是工具),发它的 begin(kind=thinking)+ 已缓冲内容 + end;然后开 tool block。
- `afinalize`(turn 收尾)到来 → 当前 pending 文本 block 封口为 `answer`,发 begin(kind=answer)+ 内容 + end。

**取舍(诚实面对一个物理限制)**:第一个文本 token 到达时,Python 也**无法预知**这段后面是工具调用(→thinking)还是 turn 收尾(→answer)——除非引擎能预告。这是流式的固有限制,某种"先渲染、后改判"不可避免。本设计的改进**不是消灭改判,而是把它协议化、集中化、单次化**:

- 文本 block 流式时默认按 `answer` 发(begin kind=answer + append),host 流式即青卡 —— 满足"最终回答流式青卡"。
- 若随后 `atool_start` 到来,Python 发一次 `block.retype {id, kind:thinking}`,host 把该 block 从青卡重渲染为紫色 ✱ 块。
- **与现状(散落的 demote/promote 手动节点增删)的本质区别**:retype 是**协议层一个明确的语义信号**,逻辑集中在 Python 状态机一处;host 只需实现"按新 kind 重建一个 block 的渲染"这一个通用能力(Renderer.retype),不再有跨方法共享的 `this.answerXxx` 引用和手动 add/remove。改判从"脆弱的临时补丁"变成"协议的一等公民"。
- **备选(零闪烁,代价是最终回答不流式)**:若用户更看重 thinking 零闪烁,可改为文本 block 默认按 thinking 紫色流式,turn 收尾时 retype 成 answer 青卡——但这样最终回答要到收尾才变青卡(失去流式青卡)。当前设计选"最终回答流式青卡优先"(用户已明确)。
- **实现期 codex 重点**:这个状态机(pending 文本 block 的开启/封口/retype 时机)是重构的核心,需先想清再写。

## JS host 渲染层（拆成多模块）

bun 支持 ES module import。`package/src/` 下拆分:

- `theme.mjs` — 颜色常量(单一真相来源)。
- `primitives.mjs` — 样式/布局原语:`clipToCells`、`cellWidth`、`railLine(color)`、`card({title, bodyLines, accent})`、`timelineIndent()`、宽度计算。所有 Renderer 复用。**改一个视觉细节只改这里,全局一致。**
- `blocks/` — 每种 kind 一个 Renderer 模块(promptBlock.mjs / thinkingBlock.mjs / toolBlock.mjs / answerBlock.mjs / usageBlock.mjs / errorBlock.mjs)。每个 Renderer 接口统一:`begin(meta) / append(delta) / update(patch) / end() / retype(kind)`,内部用 primitives 画自己的节点,持有自己的 OpenTUI 节点引用。**新增/改一种 block 只动它自己的文件。**
- `blockRegistry.mjs` — `kind → Renderer 工厂` 映射。
- `turnView.mjs` — 纯容器:持有 block id → Renderer 实例,把 block.begin/append/update/end/retype 路由到对应 Renderer;管理 turn box 在 ScrollBox 里的挂载。不含任何具体渲染逻辑。
- `composer.mjs` — 输入区(光标/历史/键位/滚轮),从主文件抽出。
- `ipc.mjs` — fd 读写 + 消息解析分发。
- `main.mjs` — 瘦入口:createCliRenderer、buildLayout、wire 起 ipc→turnView,装键盘。

每个模块职责单一、可独立理解。文件大小受控,便于人和 agent 推理与修改。

## 数据流与错误处理

- 流式:block.append 增量更新对应 Renderer 的内容,Renderer 自行 requestRender。
- 原地更新:tool 的 running→done 走 block.update,Renderer 改自己节点的 glyph/color,不增删节点(消灭悬空)。
- 截断:thinking/tool detail 等纯文本行由 primitives.clipToCells 统一处理,绝不折行打断竖线;answer 用 MarkdownRenderable + 左边框 Box(OpenTUI 自身处理换行,不丢边框)。
- 未知 kind / 缺失 block id:host 记 error 消息回传 Python,不崩溃。

## 测试策略

- **协议层(Python 单测)**:断言每种引擎调用序列产出正确的 block 消息序列(尤其:文本+工具 → thinking;文本+turn 收尾 → answer;并行工具各自独立 block)。这是消灭乐观猜测的核心回归。
- **host 结构(现有 test_opentui_host_layout.py 风格)**:断言每个 Renderer 模块用了正确的 primitives(rail 颜色统一、卡片结构、clip),BlockRegistry 覆盖 6 种 kind。
- **真实终端帧(scripts/tui_real_terminal_lab.py)**:live + replay 双跑,确认 thinking 紫块/tool 归组缩进/answer 流式青卡/竖线连续不断/无折行。replay 装置已对齐真实 live 通路(走 atool_finished result→tool 协议)。
- **交互(用户目视)**:光标/滚轮/option回车/复制 —— 自动化抓不到的。

## 迁移与提交策略

- 当前工作区有未提交的"乐观+demote"改动(messages.py/renderer.py/main.mjs + 测试)。**先提交它们**锁定一个验证过的可用基线,重构从干净起点开始,便于回退。
- 重构分阶段(详见实现计划):① 协议层(messages + Python 状态机)② host 多模块拆分 + BlockRegistry + primitives ③ 各 block Renderer ④ 删除旧的 demote/promote/乐观逻辑 ⑤ 测试与真实跑验证。每阶段保持可运行、测试绿。

## 不做（YAGNI）

- 不引入前端框架/虚拟 DOM,继续用 OpenTUI 原生 Renderable + 手写 Renderer。
- 不改引擎层(opensquilla/engine);只在 Python 渲染层(cli/tui)和 JS host 重构。
- #5(运行中发新 prompt 注入)是独立功能需求,不在本次架构重构范围,后续单独做。
