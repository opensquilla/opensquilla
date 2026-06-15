# MetaSkill UX Roadmap — Handoff to Next Contributor

- 日期：2026-06-04
- 当前分支：`feature/meta-skill-run-progress`（已推到 `nice/feature/meta-skill-run-progress`）
- 当前 HEAD：`1f17331`（21 个 commit 累计于 `bad0086`）
- 上一位贡献者：Claude Opus 4.7
- 接手者：Codex（或任何后续 contributor）

本文档让接手者在不读全部 21 个 commit 与 3000+ 行设计文档的前提下，理解**已完成什么、剩什么、为何如此、下一步应从哪起手**。

---

## 1. 整体路线图所在位置

完整路线图、所有主题分级、依赖耦合：

- `docs/proposals/specs/2026-06-04-meta-skill-ux-roadmap-design.md`

P0-1 当前主题的设计稿与实施 plan：

- `docs/proposals/specs/2026-06-04-meta-skill-run-progress-design.md`
- `docs/proposals/plans/2026-06-04-meta-skill-run-progress-plan.md`

---

## 2. 已完成 — P0-1 MetaSkill Run Progress Ribbon (20 task)

### 后端（commits 1-11，依拓扑顺序）

| Commit | Subject |
|---|---|
| `8c3df16` | Introduce meta-skill run progress event types |
| `bc7e0c4` | Tighten meta-skill event types and extend AgentEvent union |
| `1a09716` | Route meta-skill progress events through gateway bridge |
| `b728aa3` | Lock meta-skill events as replay-safe in session streams |
| `4ab4975` | Add label and progress_emits fields to MetaStep |
| `c4ea0ad` | Parse label and progress_emits on meta-skill steps |
| `59581ad` | Add progress-event throttle and state dedupe helper |
| `ce938c8` | Announce meta-skill composition before run dispatch |
| `d0ad547` | Emit running and succeeded states for meta-skill steps |
| `0f16d15` | Emit skipped state when meta-step when-condition is false |
| `cdf6efe` | Emit failed and substituted states for meta-skill failover |
| `74d584b` | Yield meta-run completion event at scheduler end |

### 前端（commits 12-17）

| Commit | Subject |
|---|---|
| `82dd512` | Style meta-skill run progress ribbon |
| `5a851db` | Render meta-skill run progress ribbon |
| `b6bd43e` | Wire meta-skill ribbon events into chat dispatcher |
| `c1f1d3a` | Lock meta-ribbon DOM and dispatcher contract |
| `246a83f` | Lock failure action row contract on meta-ribbon |
| `8c049b5` | Verify meta-skill ribbon end-to-end in real browser |

### 收尾（commits 18-21）

| Commit | Subject |
|---|---|
| `9d2a089` | Label high-frequency meta-skill steps for ribbon display |
| `e4552dc` | Document step labels and run progress ribbon |
| `1f17331` | Publish meta-skill UX roadmap, design, and implementation plan |

**测试**：117 个 meta 测试 + 9 个前端静态测试全 PASS，ruff 干净。E2E 测试已写、等 chromium gate。

---

## 3. 必须先做：P0-1 review 找到的 5 个 Critical/Important bug

P0-1 推进时偷工后留下的债，**接手者第一件事先收掉这些**，否则后续主题会被坑放大：

### 🔴 Critical（推 PR 前阻塞）

#### C1. Ribbon DOM 位置错

**症状**：ribbon 显示在工具卡片**之后**而非之前；视觉与 spec §2 图反。

**位置**：`src/opensquilla/gateway/static/js/views/chat.js`，`session.event.meta_run_announced` handler。当前是 `host.appendChild(el)`，应找到当前 turn 的容器节点再 `prepend`，或用 CSS `order: -1`。

**LOC**：~10。

#### C2. `_run_id` 跨进程不稳定

**症状**：scheduler 用 `id(match)` 做兜底，断线重连后视为新 run，ribbon 重新出空白。

**位置**：`src/opensquilla/skills/meta/scheduler.py` `run_dag()` 入口处：

```python
_run_id = getattr(match, "run_id", "") or f"{match.plan.name}:{id(match)}"
```

**修法**：

1. `MetaMatch` 加真正的 `run_id: str` 字段，由 orchestrator 调用方注入
2. 或派生自 `session_key + plan.name + monotonic_counter`

涉及 `skills/meta/types.py`、`scheduler.py` 以及 orchestrator facade。**约 ~50 LOC，半天**。

#### C3. Substituted glyph 被 succeeded 覆盖

**症状**：on_failure 触发后 substitute step 跑成功 → 视觉上是普通成功 `✓` 而非替代 `⇄`。失败救援的故事丢了。

**位置**：`src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js` `renderRibbon` 中 chip 渲染：

```js
${STATE_GLYPH[s.state] || '○'}   // 用 state 决定 glyph
```

应改成：

```js
${s.substituteFor ? '⇄' : (STATE_GLYPH[s.state] || '○')}
```

**LOC**：~5。

### 🟡 Important

#### I4. outcome="failed" 在替代成功时仍触发

**症状**：on_failure 救回成功 → 但 `_failed_step_ids` 仍含原 step → outcome="failed" → 前端动作行误报。

**位置**：`scheduler.py` 末尾 `_yield_completion("failed" if _failed_step_ids else "ok")`。

**修法**：判定改成"`_failed_step_ids` 中**未被** substitute 成功的"，或前端 `shouldShowActions` 加 outcome 守门。

**LOC**：~20，含 1 个新测试。

#### I5. retry-run 按钮只 focus 输入框

**症状**：按钮像是动作但什么都不做，UX 等同于没按钮。

**位置**：`chat.js` action handler：

```js
if (action === 'retry-run') {
  if (_textarea && typeof _textarea.focus === 'function') _textarea.focus();
}
```

**修法**：从 `_thread` 找到最近一条 `[data-role="user"]` 消息的原文，写回 `_textarea.value` 再触发 send 路径（找 chat.js 现有 send 函数复用）。

**LOC**：~40。

### 完成所有 5 项预估

**~185 LOC / ~1.5 天**。建议作为接手者**第一个 PR**，标题：「Fix critical issues from P0-1 meta-skill ribbon review」。

---

## 4. 剩余 Minor（M1-M6）

低优先级累积修，不阻塞推进：

| # | 内容 | LOC |
|---|---|---|
| M1 | 测试 fixtures 抽 `tests/_meta_fixtures.py` 或 conftest 去重 | ~30 |
| M2 | `asyncio.run + break` 留尾 task → 显式 `aclose()` | ~5 |
| M3 | parser 默认 `progress_emits` 走 tool_call 路径无测试 → 加 1 个 case | ~10 |
| M4 | `cancelled` outcome 路径无测试 → 加 paused 场景 1 case | ~30 |
| M5 | PR 描述里注明 `tests/test_gateway/test_ws_writer_queue.py` 等预存失败 | 文档 |
| M6 | CSS `:hover` 在触屏退化 → 加 `@media (hover: hover)` 包裹 | ~5 |

---

## 5. 路线图剩余主题（按推荐顺序）

### P0 剩 4 项 — 用户体感层关键

**做完 P0 = 用户日常 meta-skill 体验基本到位**。预计 3-4 周。

#### P0-2 调用前确认 + 请求脚手架（5-7 天）

**目标**：软触发命中时先弹"我准备用 X meta-skill；缺这些字段"卡片，让用户填补或一键跑默认。

**关键改动**：

- 每个 meta-skill 在 frontmatter 加 `request_template:` 字段
- Orchestrator 加 pre-confirm 阶段（启动前 yield 一种新事件）
- 新前端组件：confirm card
- "已熟悉就 skip"开关 / per-user 偏好

**为什么排第二**：是 P0-3 输出契约的**输入端**，必须在 P0-3 之前；不做 P0-3 的 audit 只能挂红灯（垃圾输入仍产生垃圾输出）。

#### P0-3 输出契约强化（7-10 天）

**目标**：每个 meta-skill 必出"事实 / 假设 / 风险 / 下一步"等结构化 section；末端 audit step 自动校验。

**关键改动**：

- meta-skill frontmatter 加 `output_contract:` schema
- Orchestrator 末端追加 audit step（llm_classify + llm_chat）
- 9 个内置 meta-skill 各写一版 contract（建议先做 3 个高频）
- 最终 final_text 后追加固定汇总块（✅ / ⚠ / ❌ / 📎）

**为什么重**：是 meta-skill 区别于普通 skill 的**核心承诺**；这一项不做，整套系统的可信度上不去。

#### P0-4 Artifact 真实性 + Card UI（3-5 天）

**目标**：聊天里 artifact 是 card 而非文字路径；末端 verify 校验"声称生成 / 实际生成"一致。

**关键改动**：

- 前端 artifact card 组件（复用 `attachment_refs` 基础设施）
- Orchestrator 末端加 verify-artifact step（存在性 + size > 0 + checksum）
- 失败时把"生成失败"写进 final answer 而非吞掉

**为什么轻**：infra 大部分已在 `artifact_refs.py`，主要工作量在前端 + verify hook。

#### P0-5 失败救援与降级（5-7 天）

**目标**：失败动作行真做事（动态 hint mapping、单步重跑、部分产出保留）。

**关键改动**：

- failure→install/retry 提示的 mapping 表
- 单步重跑实现（state 隔离 + scheduler 注入 prior outputs）
- partial output 保留与展示（scheduler 在异常分支不丢前 N-1 步 outputs）
- 替换 P0-1 的 retry-run / switch-skill 简版为完整实现（I5 的真实修法落在这里）

**为什么排末**：依赖 P0-2 confirm card 和 P0-4 verify 才能形成完整闭环。

### P1（5 项 ~22-30 天）— 高级用户 / 作者 / 质量基线

按代价从小到大：

1. **P1-5 成本可视化**（2-3 天，杠杆低成本先吃）
2. **P1-1 WebUI run 历史面板**（7-10 天，依赖 P0-1 已铺的事件粒度）
3. **P1-2 Clarify 对话化**（3-5 天）
4. **P1-4 效果回归基线**（5-7 天，可与 P0-3 output_contract 复用 rubric）
5. **P1-3 作者轻量入口**（5-7 天，生态侧）

### P2（5 项 ~21-31 天）— 长期累积

按客户/用量浮动，不阻塞。详见路线图 §8。

---

## 6. 工作量总账

| 阶段 | LOC | 工时 | 优先级 |
|---|---|---|---|
| P0-1 review 漏修（C1/C2/C3/I4/I5） | ~185 | ~1.5 天 | 🔴 第一件事 |
| 6 个剩余 meta-skill 补 label | ~60 | 半天 | 🟡 跟在收尾后 |
| P0-2 ~ P0-5 | ~5300 | 20-30 天 | 🟠 完成"用户体感到位" |
| P1（5 项） | ~4700 | 22-30 天 | 🟡 高级用户拉齐 |
| P2（5 项） | ~4200 | 21-31 天 | ⚪ 机会窗口 |
| **TOTAL（含本次已完成的 ~1500）** | **~14400** | **~65-90 天** | — |

**当前完成率：~10% LOC / ~3-5% 工时 / 1.85 个路线图主题（共 15）**。

---

## 7. 给接手者的关键提示

### 7.1 工作风格与节奏

- **每 Task 一个原子 commit**，subject imperative + Co-Authored-By trailer（match 本仓现有风格）
- 测试先行（TDD），新功能必须先写失败测试再写实现
- 改 SKILL.md 或 scheduler 时，**先跑 `tests/test_meta_skill_openclaw_*` 对比测试**确认没破回归
- `docs/proposals/` 是公开的 design / plan 区，落地后留作 review 凭据；`docs/superpowers/` 是本地草稿区（`.gitignore` 内）

### 7.2 已知陷阱

1. **scheduler.py `_run_one` 是 `run_dag` 内嵌函数**，闭包捕获 `_run_id` / `_failed_step_ids` 等；新增 emission 时不要把这些变量泄到全局。
2. **`tests/test_session/`、`tests/test_mcp/`、`tests/test_gateway/test_ws_writer_queue.py` 等预存失败与本工作无关**（baseline 在 `bad0086` 就坏的）。跑回归时显式列出测试文件，不要 `uv run pytest tests/` 全量。
3. **`chat.js` 是 classic IIFE**（9594 行），不支持 ES module `import`；新组件用经典 `<script>` + `window.NAMESPACE` 注册（参考 `chat/meta-ribbon.js`）。
4. **`MetaStep` 字段顺序敏感**：新字段加到 dataclass 末尾，否则下游有些位置参数构造会错位。
5. **`MetaPlan.steps` 是 tuple 而非 list**——某些 fixture 容易写错。
6. **mypy 在本 worktree 的 venv 没装**——本次 session 所有 "mypy clean" 实际未跑；接手者请先 `uv pip install mypy` 再依赖类型检查。

### 7.3 推 PR 前 checklist

- [ ] C1/C2/C3/I4/I5 全修
- [ ] `uv run pytest <列出的所有 meta 文件>` 全绿
- [ ] `uv run ruff check <列出的所有改动文件>` clean
- [ ] `uv run mypy src/opensquilla/skills/meta/ src/opensquilla/engine/types.py src/opensquilla/gateway/event_bridge.py` clean
- [ ] `OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run pytest tests/functional/test_webui_browser_chat_e2e.py::test_meta_skill_ribbon_renders_and_progresses_in_real_browser` 本地跑过
- [ ] PR 描述基于 `docs/superpowers/plans/2026-06-04-meta-skill-run-progress-pr-draft.md`（本地）

---

## 8. 推荐第一周节奏

```
Day 1   收 review 漏修（C1+C3）+ 补 label 6 个 → 1 PR
Day 2   C2（_run_id 稳定） → 1 PR（接 C1 的 PR）
Day 3   I4 + I5（retry-run 真做事 + outcome 修正） → 1 PR
Day 4-5 P0-2 spec + plan（brainstorming → writing-plans → 起手 backend）
后续    P0-2 实施 → P0-3 → P0-4 → P0-5（每周一主题节奏）
```

---

[Roadmap](specs/2026-06-04-meta-skill-ux-roadmap-design.md) · [P0-1 Design](specs/2026-06-04-meta-skill-run-progress-design.md) · [P0-1 Plan](plans/2026-06-04-meta-skill-run-progress-plan.md)
