# P0-1 MetaSkill Run Progress (Step Ribbon) 设计稿

- 日期：2026-06-04
- 状态：草案，本地（`docs/proposals/`），等团队 review
- 上游：`docs/proposals/specs/2026-06-04-meta-skill-ux-roadmap-design.md` P0-1
- 实施跟踪：本 spec 通过后由 writing-plans 拆 plan

## 1. 目标与非目标

### 目标（in scope）

1. MetaSkill 跑的过程中用户能**一眼看到**：这次跑共几步、当前在第几步、当前步在干什么
2. 每个 step chip 可点击 → 滚动到对应 tool-card
3. 失败 step 显红色 chip + 下方挂动作行（重试 / 切换 meta-skill / 错误详情）
4. 跳过 step（被 `route`/`when` 排除）显淡灰 chip
5. 并行 step 同时高亮
6. 新事件**附加**到现有事件流，不破坏 CLI/MCP 兼容
7. 断线重连后 ribbon 能从 replay buffer 重建

### 非目标（不在 P0-1）

- 错误→安装提示的动态 hint mapping（属 P0-5）
- "微调一个字段重跑"（属 P0-5）
- step 内 LLM trace 展开（属 P1-1）
- 跨 run 历史 ribbon（属 P1-1）
- 进度百分比预测（步内时长不可估）
- ribbon telemetry（属 P1）
- i18n 多语言切换（按当前 WebUI 默认中文硬编码）

## 2. UX 视觉契约

```
┌─ ▼ meta-document-to-decision · 3/7 ────────────────────────┐
│  [✓ intake] [✓ classify] [⚙ search ●] [○ draft] [○ audit]  │
│                            正在检索 2026 年日本 eSIM …      │
└─────────────────────────────────────────────────────────────┘
   ↓ 现有 tool-call cards 按 step 顺序往下展开（不变）
```

**状态符号集**：

| 符号 | 含义 |
|---|---|
| `○` | pending（待执行） |
| `⚙` + 旋灯 + 高亮 | running（进行中） |
| `✓` | succeeded |
| `✗`（红色） | failed |
| `↷`（灰色） | skipped（route/when 排除） |
| `⇄` | substituted（on_failure 的替代 step） |

**ribbon 行为**：

- 单次 run 一条 ribbon，绑 run_id
- 默认展开；用户可折叠（chevron 切换），折叠后只剩"3/7 检索中…"
- chip 数 > 8 横向滚动，当前 chip sticky 可见
- 当前 step 下方的短状态文本来自 step `status_text`，缺失回退到"运行中"
- 并行 step：相邻 chip 同时显示 `⚙`，不强制视觉分组

## 3. 后端事件模型

**原则**：附加（additive），不改 `ToolUseStartEvent` / `ToolResultEvent`，CLI/MCP 继续可用。

### 3.1 新增事件

| 事件名 | 触发点 | payload |
|---|---|---|
| `session.event.meta_run_announced` | plan 编译完成、第一个 step 派发前 | `{ run_id, meta_skill_name, steps: [{id, label, kind, depends_on}], total }` |
| `session.event.meta_step_state` | 每次 step 状态变化 | `{ run_id, step_id, state, status_text?, error?, substitute_for? }` |
| `session.event.meta_run_completed` | 所有 step 结束 | `{ run_id, outcome, completed_steps, failed_steps, skipped_steps }` |

### 3.2 `state` 取值集

`pending` / `running` / `succeeded` / `failed` / `skipped` / `substituted`（与 §2 视觉契约一一对应）。

### 3.3 `status_text` 来源

| step kind | 默认 status_text | 进度更新来源 |
|---|---|---|
| `llm_chat` | "起草中…" | 无 |
| `llm_classify` | "分类中…" | 无 |
| `agent` | "调用 <skill> 中…" | 子 turn 每个 `ToolUseStartEvent.tool_name` 回填 |
| `skill_exec` | "执行 <skill> 中…" | 子进程 stdout `progress:` 前缀行；缺失保留默认 |
| `tool_call` | "调用 <tool>…" | 无 |
| `user_input` | "等待你回复表单" | 无 |

### 3.4 节流

- `meta_step_state(running, status_text=…)` 每 step 每 500ms 最多 1 次
- 同 state 重复事件去重（前端按 `(run_id, step_id, state)` 去重）

### 3.5 事件发布位置

- `meta_run_announced`：`scheduler.iter_events()` 主循环入口，紧随 plan 编译之后
- `meta_step_state(running)`：现有 `ToolUseStartEvent(meta-step:…)` 旁并发
- `meta_step_state(succeeded/failed)`：现有 `ToolResultEvent(meta-step:…)` 旁并发
- `meta_step_state(skipped)`：scheduler 在 `route`/`when` 排除时单独发
- `meta_step_state(substituted)`：在 `_FailoverTriggered` 处理处发
- `meta_run_completed`：scheduler 末尾发，不论结果

### 3.6 Replay 兼容

`session_streams.SessionStreamRegistry`：

- 三个新事件均**不**进 `_is_replay_lossy` 名单
- replay buffer 500 events/session 上限对预期 step 数（< 20 / meta-skill）有足够裕量

## 4. Plan 宣告与状态机一致性

### 4.1 静态宣告

`meta_run_announced` 发的是**`composition.steps` 全集**（按拓扑顺序）。原则：宁可宣告完整集，运行时用 state 推进，也不动态修改 plan。

### 4.2 状态推进规则

- `route` 命中 A 分支 → A step 状态推进，B step 收 `skipped`
- `when=False` → 该 step 收 `skipped`
- `on_failure` 触发 → 失败 step `failed`，替代 step `substituted`
- 用户取消（Escape / abort）→ scheduler cleanup 段给所有 `pending`/`running` 发 `skipped`，再发 `meta_run_completed`

### 4.3 Label 来源

- 优先：`SKILL.md` 里 step 新增可选 `label:`
- 回退：前端 humanize step `id`（`intake` → `Intake`）
- i18n：MVP 不做；作者写中文则中文显示

## 5. SKILL.md schema 扩展

```yaml
composition:
  steps:
    - id: intake
      kind: llm_chat
      label: 意图提取                # 新增，可选
      with: { ... }
    - id: search
      kind: agent
      skill: web-research
      label: 检索证据
      progress_emits: true           # 新增，可选；agent/skill_exec 默认 true
      with: { ... }
```

**字段语义**：

- `label`：人类可读名，作 chip 文本。缺失走 humanize 回退。
- `progress_emits`：是否允许子执行器回填 `status_text`。`tool_call` 默认 `false`；`agent`/`skill_exec` 默认 `true`；`llm_chat`/`llm_classify` 不读。

**Parser**：`skills/meta/parser.py` 接受这两个字段，未知字段保持现有 strict 行为。

## 6. 失败 chip 的动作行

**MVP 三段式**：

```
✗ search 失败 · web-research 第 2 次工具调用超时
[ 重试整个 run ]  [ 切换 meta-skill… ]  [ 查看错误详情 ]
```

**按钮行为**：

1. **重试整个 run**：触发 `meta_invoke` 重发，沿用本次 run 的 `inputs.user_message`。MVP 不实现"重试单步"（属 P0-5）。
2. **切换 meta-skill…**：MVP 用简版下拉列其他 meta-skill 名 + 一句话描述；P0-2 落地后统一替换为 confirm card。
3. **查看错误详情**：展开下方失败 step 的 `ToolResultEvent.result`（已有错误文本）。

**安装提示不接**：即使知道是 ffmpeg 缺失也不在 P0-1 加 "Install" 按钮；动态 hint mapping 留 P0-5。

## 7. 兼容与节流

### 7.1 对外兼容

- CLI / MCP / 第三方 client：继续收 `ToolUseStartEvent(meta-step:…)` 和 `ToolResultEvent(meta-step:…)`，不改不删
- 新事件只有 WebUI 解析；未识别 client 默认忽略
- WebSocket 协议版本不升

### 7.2 断线重连

- `meta_run_announced` 必保留——ribbon 重建 anchor
- `meta_step_state` 全量保留——按 stream_seq 顺序应用状态机，最终一致
- `meta_run_completed` 必保留

### 7.3 多 meta-skill 嵌套

- 当前不允许 meta 调 meta；agent step 调子 skill 不构成嵌套 ribbon
- 防御性：`meta_run_announced` 带 `parent_run_id?` 保留位（MVP 总为 null）

## 8. 前端集成方案

### 8.1 文件切分

```
src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js     新增
src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css   新增
```

`chat.js` 只做**接线**：import handler、注册到 dispatcher、决定 ribbon DOM 插入容器节点。**禁止把 ribbon 业务逻辑写在 chat.js 里**（chat.js 已 9528 行，再扩会失控）。

### 8.2 模块职责

`meta-ribbon.js` 暴露：

- `createRibbon(announce) → ribbonState`
- `updateStep(ribbonState, stepStateEvent) → ribbonState`
- `completeRun(ribbonState, completedEvent) → ribbonState`
- `renderRibbon(rootEl, ribbonState)`（纯渲染）

模块内部维护 `run_id → ribbonState` 的本地 map。

### 8.3 DOM 结构

```html
<section class="meta-ribbon" data-run-id="...">
  <header class="meta-ribbon-head">
    <button class="meta-ribbon-toggle">▼</button>
    <span class="meta-ribbon-title">meta-document-to-decision</span>
    <span class="meta-ribbon-counter">3/7</span>
  </header>
  <ol class="meta-ribbon-chips">
    <li class="chip succeeded" data-step-id="intake">✓ 意图提取</li>
    <li class="chip running" data-step-id="search">⚙ 检索证据</li>
    ...
  </ol>
  <div class="meta-ribbon-status">正在检索 2026 年日本 eSIM 市场…</div>
  <div class="meta-ribbon-actions" hidden>...</div>
</section>
```

### 8.4 Chip 点击跳转

ribbon `data-step-id` 与 tool-card `data-tool-use-id="meta-step:<step_id>"` 一一对应：

```js
document.querySelector(`[data-tool-use-id="meta-step:${stepId}"]`)
        .scrollIntoView({block:'center'});
```

## 9. 测试策略

### 9.1 Python 单元/集成测试

| 测试文件 | 验什么 |
|---|---|
| `tests/test_meta_skill_step_events.py` | scheduler 在派发/完成/失败/跳过时分别发出 `meta_step_state`，state 序列符合拓扑 |
| `tests/test_meta_skill_run_announce.py` | `meta_run_announced` 在第一个 step 派发前发出；含全部声明 step 的 id、label、depends_on |
| `tests/test_session_streams_meta_events.py` | 新事件不被 `_is_replay_lossy` 丢弃；断线重连补齐 |
| `tests/test_meta_skill_route_skipped.py` | `route` 排除的 step 收 `skipped`；`when=False` 同上 |
| `tests/test_meta_skill_failover_substituted.py` | `on_failure` 触发时原 step `failed`、替代 `substituted` |
| `tests/test_meta_skill_status_text_throttle.py` | 500ms 节流生效；重复 state 去重 |

### 9.2 前端静态测试

| 测试文件 | 验什么 |
|---|---|
| `tests/test_gateway/test_chat_meta_ribbon_static.py` | announce 后 chip 列正确；state 推进切换 class；折叠后只剩 status |
| `tests/test_gateway/test_chat_meta_ribbon_failure.py` | 失败动作行显示；点"详情"展开对应 tool-card |
| `tests/test_gateway_static_chat_view.py`（已存在） | 回归：ribbon 不影响现有工具卡片 |

### 9.3 E2E browser 测试

- `tests/functional/test_webui_browser_chat_e2e.py` 加一例：跑 stub meta-skill，断言 ribbon 出现、chip 推进、失败动作行可点
- 沿用 `OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1` gate

### 9.4 回归

- `uv run pytest tests` 全量绿
- `uv run ruff check src tests`
- `uv run mypy src/opensquilla`

### 9.5 手工验证清单（PR 描述列出）

- `meta-document-to-decision`：ribbon 显 5 chip → 逐一推进
- `meta-paper-write`（缺 xelatex）：失败 chip + 动作行 → "重试"可点
- 断线重连：第 3 步刷浏览器 → ribbon 恢复到第 3 chip running
- 折叠 / 展开切换
- 移动端窄屏（chip 横向滚动）

## 10. 风险与开放问题

### 10.1 风险

| # | 风险 | 缓解 |
|---|---|---|
| R-1 | agent 子 turn 回填 `status_text` 与 `subagent_announce.py` 现有路径冲突 | 实施前先读 subagent_announce，复用事件总线 |
| R-2 | meta-skill 嵌套未来若放开，ribbon 需要嵌套渲染 | `parent_run_id?` 保留位已加 |
| R-3 | replay buffer 500 events/session 上限 | step 数 < 20，远低于阈值 |
| R-4 | 9 个内置 meta-skill 都要补 `label:` | 分 PR：先引擎 + ribbon（label 缺失走 humanize），再补 label |
| R-5 | 失败动作行"切换"在 P0-2 未就绪时走简版，可能 UI 不一致 | 简版用纯下拉；P0-2 落地后替换为 confirm card |
| R-6 | chat.js 注册新 handler 可能漏分支 | 静态测试 + e2e；模块 ES module 边界 |
| R-7 | 移动端窄屏 chip 太多 | CSS 横向滚动 + sticky 当前 chip |

### 10.2 开放问题

| # | 问题 | 默认建议 |
|---|---|---|
| Q-1 | ribbon 在 user_input 暂停时显不显示 | 显示，当前 chip 状态写"等待你回复" |
| Q-2 | 折叠后新 run 默认展开还是延续 | 每次新 run 默认展开 |
| Q-3 | telemetry 记 chip 操作 | MVP 不接，列入 P1 |
| Q-4 | 默认 status_text 中文还是 i18n | MVP 中文硬编码 |
| Q-5 | a11y screen reader 播报 | `aria-label="step 3 of 7: 检索证据 进行中"` + `aria-live="polite"` |
| Q-6 | 极快 run（< 1s）ribbon 闪过 | 不加 min-display；`meta_run_completed` 后保留 5s |
| Q-7 | 0 step 退化 meta-skill | scheduler 入口校验：空数组直接 `MetaResult(ok=True)`，不发事件 |
| Q-8 | announce 与第一个 tool-card 的顺序 | scheduler 强制先 yield announce 再 yield tool-card；测试覆盖 |

## 11. 实施步骤（writing-plans 种子）

1. **后端 types/事件类**——`engine/types.py` 或新 `engine/meta_events.py` 加 3 个事件类
2. **后端 scheduler 发布点**——`skills/meta/scheduler.py` 主循环 6 个位置插入 yield（announce / running / succeeded / failed / skipped / completed）
3. **后端 replay buffer**——`session_streams.py` 确认新事件不被丢；加测试
4. **后端节流**——`status_text` 500ms 节流 helper
5. **后端 schema 扩展**——`skills/meta/parser.py` 接受 `label:` / `progress_emits:`
6. **后端单元 + 集成测试**——按 §9.1 矩阵
7. **前端 `chat/meta-ribbon.js` 新模块**——纯函数 + 渲染
8. **前端 CSS** ——独立文件 `chat-meta-ribbon.css`
9. **前端 `chat.js` 接线**——3 个 handler 注册
10. **前端静态测试**——按 §9.2 矩阵
11. **E2E browser 测试**——按 §9.3
12. **9 个内置 meta-skill 补 label**——独立 PR
13. **文档**——`docs/authoring/meta-skills.md` 加新字段说明

每步原子提交、可独立 review。

## 12. 决策记录（待填）

- [ ] 团队确认事件名 / state 取值集 / payload schema
- [ ] 团队确认 SKILL.md 加 `label:` / `progress_emits:` 字段
- [ ] 是否同意"先 9 个内置 meta-skill 中只补 3 个高频（research / decision / brief）的 label，其余 PR2 处理"
- [ ] M0 季度内是否能投入完成步骤 1-11

## 13. 下一步

本 spec 通过后：

- 由 superpowers:writing-plans 拆 implementation plan，落到 `docs/proposals/plans/2026-06-04-meta-skill-run-progress-plan.md`（本地）
- plan 按"原子可 review 提交"切，每步对应一个 PR 或单提交

---

[路线图](2026-06-04-meta-skill-ux-roadmap-design.md) · [MetaSkill 用户指南](../../features/meta-skill-user-guide.md) · [作者指南](../../authoring/meta-skills.md)
