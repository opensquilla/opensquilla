# MetaSkill UX Roadmap (设计稿)

- 日期：2026-06-04
- 状态：草案，待团队 review
- 范围：OpenSquilla MetaSkill 的端到端用户体验优化方向
- 受众：产品 / 工程 / 文档 / DX

## 1. 摘要

MetaSkill 是 OpenSquilla 的任务-协议层（task-protocol layer），把多步、可审计、可复跑的高价值工作沉淀为可复用工作流。本文件对当前 MetaSkill 用户体验做一次系统扫描，覆盖**外围流程 UX**与**输出/交付质量**两大类，按四人群（终端用户 / 高级用户 / 作者 / 管理员）整理痛点，按四轴（影响 × 成本 × 风险消解 × 杠杆）评估，给出 P0 / P1 / P2 分级路线图与推荐打法顺序。

文档目的不是一次性大改造，而是为后续若干迭代提供**评估共识**与**优先级共识**，每个 P0 主题会另起 spec + plan 推进。

## 2. 范围与边界

**包含**：

- MetaSkill 调用前（发现、触发、契约确认）
- 调用中（多步执行、可观察、澄清、中断）
- 调用后（输出、artifact、复跑、修正）
- 输出/交付质量（决策可用度、证据强度、结构稳定性、约束尊重）
- 作者产能（创建、验证、迭代、提案审核）
- 运营可观察（历史、复跑、失败、成本、合规）

**不包含**：

- 单个具体 MetaSkill 的内容质量改造（属各自 skill 的迭代）
- 普通 skill / tool 层改动（除非影响 MetaSkill UX）
- 模型供应商切换 / 路由细节（已由 router_tiers 等独立工作流推进）
- 安装/部署体验（除非阻断 MetaSkill 使用）

## 3. 现状速览

- 9 个内置 MetaSkill：`meta-competitive-intel` / `meta-daily-operator-brief` / `meta-document-to-decision` / `meta-job-search-pipeline` / `meta-kid-project-planner` / `meta-paper-write` / `meta-short-drama` / `meta-skill-creator` / `meta-web-research-to-report`
- 激活方式：软触发（自然语言） + 显式 `Use meta-skill <name>`
- 步骤类型：`agent` / `llm_chat` / `llm_classify` / `user_input` / `tool_call` / `skill_exec`
- 近期落地：依赖就绪 WebUI 暴露（68358fa）、澄清恢复稳定化（bad0086）、流式状态可审查（7f9228）、未知 slash 文本回退到聊天输入（83d0377）

## 4. 问题清单

按"流程外围 (A-D)"+"效果质量 (E-R)"两大块共 18 类、约 45+ 痛点。

### 4.1 流程外围

#### A. 终端用户

| # | 维度 | 痛点 |
|---|---|---|
| D-1 | 发现 | 9 个 meta-skill 名记不住，软触发可能误命中 |
| D-2 | 发现 | 没遇到过的 meta-skill 永远不会被试用 |
| I-1 | 调用 | 用户写不出"outcome/context/standard"高质量模板 |
| I-2 | 调用 | 没有"我即将运行 X meta-skill，你确认吗"的承诺前预览 |
| C-1 | 澄清 | user_input 表单像是离开对话 |
| C-2 | 澄清 | 用户在 chat 里答了字段时是否被识别不显眼 |
| E-1 | 执行 | 多步 DAG 在跑哪一步、还剩几步——用户看不见 |
| E-2 | 执行 | 长步骤（搜索、渲染）无进度反馈 |
| O-1 | 输出 | 答案没分"事实/假设/未验证"，用户难判断可信度 |
| O-2 | 输出 | 生成的 artifact 藏在文字里 |
| F-1 | 恢复 | 跑错 meta-skill 要打一段 stop+restart 提示 |
| F-2 | 恢复 | 微调重跑要重打整段请求 |
| F-3 | 恢复 | 依赖缺失的错误未必接到"如何安装"引导 |

#### B. 高级用户/运营

| # | 维度 | 痛点 |
|---|---|---|
| R-1 | 历史 | `runs list/show` 只在 CLI |
| R-2 | 历史 | 同 skill 不同 run 的 diff 看不了 |
| R-3 | 复跑 | replay 只能 dry-run，带改参的 live replay UI 缺失 |
| R-4 | 诊断 | step 级 LLM trace/prompt/tool args 在 WebUI 不展开 |
| R-5 | 失败 | 跨多个 run 的失败模式聚类无 |
| R-6 | 成本 | 每个 run/step 的 token 成本与聚合视图无 |

#### C. 作者/贡献者

| # | 维度 | 痛点 |
|---|---|---|
| A-1 | 入门 | `meta-skill-creator` 重，普通用户不会用 |
| A-2 | 入门 | "把这段对话变 meta-skill"轻量化路径无 |
| A-3 | 设计 | triggers/description 难写，无评分助手 |
| A-4 | 设计 | 多 meta-skill 间 trigger 冲突在 design time 不报 |
| A-5 | 设计 | risk/capabilities 字段写不准 |
| A-6 | 验证 | E2E 软触发脚本是 CLI |
| A-7 | 审核 | proposal 缺"变了什么/风险增量" |
| A-8 | 迭代 | 编辑后无热重载 + DAG 模拟器 |

#### D. 管理员/运维

| # | 维度 | 痛点 |
|---|---|---|
| M-1 | 部署 | 凭据/API key 就绪缺整合视图 |
| M-2 | 策略 | "禁止 high-risk auto-enable" 等组织级策略无 |
| M-3 | 健康 | 单 meta-skill 故障率聚合视图无 |
| M-4 | 合规 | 谁写了文件系统/调了网络的审计报表无 |

### 4.2 效果质量

> 类别字母刻意跳过 `Q`，因为 4.2 节内所有痛点编号统一以 `Q-` 起头，避免视觉冲突。

#### E. 决策可用度

| # | 痛点 |
|---|---|
| Q-1 | 输出降级成"客观综述"，无明确推荐/结论 |
| Q-2 | 给了结论但缺"为什么不是另一种"的对比论证 |
| Q-3 | "下一步行动"写得像建议而不是可执行项 |
| Q-4 | 用户写了"决策标准"但 meta-skill 没拿来评分 |

#### F. 证据强度 / 幻觉控制

| # | 痛点 |
|---|---|
| Q-5 | 事实/假设/未验证三栏分离非强约束 |
| Q-6 | citation 给了链接但点开不对 |
| Q-7 | 数字/日期在没源时被填"看着合理"的值 |
| Q-8 | 多 source 间矛盾被静默 merge |

#### G. 粒度匹配

| # | 痛点 |
|---|---|
| Q-9 | 简单问题被 meta-skill 过度包装 |
| Q-10 | 复杂请求被 `final_text_mode: auto` 压缩到失真 |
| Q-11 | 用户说"compact first"但仍走全量 |
| Q-12 | artifact 和聊天 summary 重复，没分工 |

#### H. 结构稳定性

| # | 痛点 |
|---|---|
| Q-13 | 同一 meta-skill 两次 run，section 顺序/标题变化 |
| Q-14 | 输出格式（表/文/列表）随机切 |
| Q-15 | 关键 section（如"风险"）有时全缺，无"必出"契约 |

#### I. 个性化 / 上下文延续

| # | 痛点 |
|---|---|
| Q-16 | 跨 session 偏好（语气、长度、禁用项）每次重说 |
| Q-17 | `meta-competitive-intel` baseline 不累积 |
| Q-18 | 上次 run 学到的"用户不要 X"未被继承 |

#### J. Artifact 真实性

| # | 痛点 |
|---|---|
| Q-19 | 声称生成了 PDF 实际未生成 |
| Q-20 | 文件存在但内容与聊天回复不一致 |
| Q-21 | 路径写在文字里没法直接打开 |
| Q-22 | docx/xlsx 在多轮修改后未 regen，artifact 落后 |

#### K. 约束尊重度（do-not）

| # | 痛点 |
|---|---|
| Q-23 | "do not invent missing dates" 仍编造 |
| Q-24 | "do not auto-apply/sign/send" 但中风险步骤照跑 |
| Q-25 | 用户源限制被搜索 step 覆盖 |
| Q-26 | 末端无 self-check 把 "do not" 与输出比对 |

#### L. 迭代收敛

| # | 痛点 |
|---|---|
| Q-27 | "redo as decision-ready" 只换措辞没换结构 |
| Q-28 | 多轮 refine 后整体一致性下降 |
| Q-29 | 失败原因没显式注入下一轮，重复同样错 |

#### M. 多模态质量

| # | 痛点 |
|---|---|
| Q-30 | `meta-short-drama` 字幕错位 / 角色一致性差 |
| Q-31 | `meta-paper-write` 图表占位与正文脱节 |
| Q-32 | LaTeX 编译过但排版坏 |

#### N. 失败优雅度

| # | 痛点 |
|---|---|
| Q-33 | 第 N 步挂了，前 N-1 步的产出被一并丢弃 |
| Q-34 | `on_failure` 只能 1 个替代步 |
| Q-35 | 失败原因暴露的是"step 失败"而不是"你能怎么救" |

#### O. 性价比 / 效率

| # | 痛点 |
|---|---|
| Q-36 | classify 该用 small 跑了 large；llm_chat 反之 |
| Q-37 | 并行机会未利用（depends_on 保守） |
| Q-38 | 同类信息在多步里被重复检索 |
| Q-39 | 模板里 `truncate(2000)` 等参数无回归 |

#### P. 可学习性 / 跨 run 复盘

| # | 痛点 |
|---|---|
| Q-40 | 用户跑 10 次相似 task 看不出"哪类输入做不好" |
| Q-41 | 版本演进时质量 drift 无 eval baseline |
| Q-42 | judge rubric 是文档建议但没自动跑 |

#### S. 语气 / 受众适配

| # | 痛点 |
|---|---|
| Q-43 | "自己看" vs "转发老板" 没分模式 |
| Q-44 | 中/英输出质量不齐 |
| Q-45 | 文化语境默认西方化 |

## 5. 评估方法

四轴：

- **影响**：多少用户被命中、感知强度（H/M/L）
- **成本**：当前架构下实现复杂度（H/M/L）
- **风险消解**：是否预防严重失败模式（H/M/L）
- **杠杆**：是否解锁其他改进（H/M/L）

把 45+ 痛点归为 15 个主题：

| Theme | 影响 | 成本 | 风险消解 | 杠杆 | 分级 |
|---|---|---|---|---|---|
| T1 中途可见性 | H | M | M | H | **P0** |
| T2 调用前确认 + 脚手架 | H | M | M | H | **P0** |
| T3 输出契约强化 | H | H | H | H | **P0** |
| T4 WebUI 历史/复跑面板 | H | H | L | M | **P1** |
| T5 Clarify 对话化 | M | M | L | M | **P1** |
| T6 Artifact 真实性 + Card | H | M | H | M | **P0** |
| T7 跨会话偏好/记忆 | M | H | L | H | **P2** |
| T8 失败救援与降级 | H | M | H | M | **P0** |
| T9 作者轻量入口 | M | M | L | H | **P1** |
| T10 验证 WebUI 化 | M | M | L | M | **P2** |
| T11 效果回归基线 | H | M | H | H | **P1** |
| T12 成本可视 | M | L | L | L | **P1** |
| T13 组织级策略 | L | M | H | L | **P2** |
| T14 个性化/受众/语种 | M | M | L | M | **P2** |
| T15 多模态质量 | M | M | L | L | **P2** |

## 6. P0 详述（5 项）

### P0-1 中途可见性（Run progress surfacing）

- **命中**：E-1, E-2, E-3, F-3, R-4, Q-19, Q-33
- **现状**：7f9228 已开窗看到流式状态，但多步 DAG 的"第 X / N 步、正在做什么、剩多久"对终端用户仍是黑盒
- **解法骨架**：
  - 聊天侧渲染 step ribbon（横向 chip：classify→search→draft→audit，当前 step 高亮 + 旋灯）
  - 每步发布短状态行（"正在检索 2026 年日本 eSIM 市场..."）
  - 失败 step 挂"安装提示 / 重试 / 切到 X meta-skill"行动按钮
- **改动表面**：`gateway/session_streams.py`、`gateway/static/js/views/chat.js`、`engine/` 里 meta orchestrator 的 progress event 发布点
- **成本**：中（事件骨架已有，主要工作在前端 chip 组件 + 更细粒度事件）
- **风险**：噪声过多会盖住主回答；需要折叠/留底机制

### P0-2 调用前确认 + 请求脚手架（Pre-flight contract）

- **命中**：D-2, I-1, I-2, Q-1..Q-4
- **现状**：软触发直接跑；用户写不出"outcome/context/standard/constraints"模板
- **解法骨架**：
  - 软触发命中时先弹一条"我准备用 `meta-document-to-decision`；缺这些字段：决策标准 / 时间窗 / 限制条件——填一下，或我用默认值跑"
  - 每个 meta-skill 在 frontmatter 加 `request_template:`，后端组装这条预览
  - 用户回"就这样跑"或填补；填补可自由文本（走 nl_extract）也可点 chip 选项
  - "已熟悉就 skip"开关
- **改动表面**：`skills/meta/` 下 metadata、`engine/` orchestrator 启动前注入 confirm step、`gateway/static/js/views/chat.js` 渲染 confirm card
- **成本**：中-高（多 meta-skill 都要补 template；orchestrator 要支持 pre-confirm 阶段）
- **风险**：加一步会让快用户觉得啰嗦
- **杠杆**：直接拉升 P0-3 输出契约的命中率

### P0-3 输出契约强化（Output contract enforcement）

- **命中**：Q-1..Q-4（决策可用）、Q-5..Q-8（证据）、Q-13..Q-15（结构稳定）、Q-23..Q-26（do-not 尊重）
- **现状**：输出契约靠 prompt + 文档约束，meta-skill 自觉度参差；末端无 self-check
- **解法骨架**：
  - 每个 meta-skill 在 frontmatter 加 `output_contract:` schema（必出 section、证据三栏、do-not 列表）
  - orchestrator 末端自动追加 `audit` step：用 `llm_classify` + `llm_chat` 检查输出是否满足 contract，不满足回写"再补 X / 删 Y"
  - 最终 final answer 后追加固定块「✅ 已覆盖 / ⚠ 假设 / ❌ 未验证 / 📎 生成的 artifact」
- **改动表面**：meta-skill `SKILL.md` 字段扩展、`engine/` 末端自动 audit、最终 final_text 模板
- **成本**：高（每个 meta-skill 单独编写 contract；audit step 增加 LLM 成本）
- **风险**：contract 太死会让生成贫乏；要分等级（必出 / 建议出）
- **杠杆**：是 meta-skill 区别于普通 skill 的**核心承诺兑现**，持续抬交付质量

### P0-4 Artifact 真实性 + Card UI

- **命中**：O-2, Q-19, Q-20, Q-21, Q-22
- **现状**：已有 `artifact_refs.py`、`artifacts.py`，聊天里 artifact 仍是文字路径，"声称生成实际未生成"难自检
- **解法骨架**：
  - artifact 在聊天里渲染为 card（文件名 / 大小 / 类型图标 / 打开 / 下载 / 重生成）
  - orchestrator 末端 verify-artifact step：所有 `skill_exec` 声明产出的文件做存在性 + size > 0 + content checksum 校验
  - 失败时把"生成失败"显式写进 final answer 而非被吞
- **改动表面**：`artifact_refs.py`、`gateway/static/js/views/chat.js`、orchestrator 末端 hook
- **成本**：中（artifact infra 多数在，主要在前端 + verify hook）
- **风险**：大文件预览/下载链路安全（已有 attachment_refs 框架可复用）

### P0-5 失败救援与降级（Failure rescue）

- **命中**：F-1, F-2, Q-29, Q-33, Q-34, Q-35
- **现状**：`on_failure` 只支持 1 个替代 step；错触发要打长 prompt 纠正；重跑改一字段要重打整段
- **解法骨架**：
  - 任一 run 末端固定挂三个 chip：「重跑这条 / 切到 X meta-skill / 微调一个字段重跑」
  - 错触发场景：用户下一条若以 "不对 / wrong / 应该用 ..." 起头，自动给"切到哪个"二选一
  - 部分失败时保留前面 step 的 output，final answer 写"以下基于成功的 4 步；第 5 步（PDF 渲染）失败，原因 X，可以 [安装 X / 重试 / 仅文字]"
  - 重跑时把上一轮失败原因 + 成功部分作为 prior context 显式注入
- **改动表面**：orchestrator partial-output 保留逻辑、聊天底栏 action chips、failure→hint mapping 表
- **成本**：中
- **风险**：partial output 可信度与中间链泄露

## 7. P1 概要（5 项）

| 主题 | 命中 | 一句话解 | 成本 |
|---|---|---|---|
| **P1-1 WebUI run 历史面板** | R-1..R-5, F-2 | 把 CLI `runs list/show/replay/failures` 整体搬到 WebUI 侧边栏 + run 详情页 | 高 |
| **P1-2 Clarify 对话化** | C-1, C-2, C-3 | 表单转 chat 卡片；nl_extract 显式 echo "已从你的话里抽出：topic=X, depth=Y"，可纠错 | 中 |
| **P1-3 作者轻量入口** | A-1, A-2, A-3, A-4 | run 详情页"把这次对话变 meta-skill 草案"按钮；自动起 triggers/description/steps 草稿；trigger 冲突当场检测 | 中 |
| **P1-4 效果回归基线** | Q-40, Q-41, Q-42 | 每 meta-skill 配 `eval_prompts:` + judge rubric；CI / cron 跑分；版本演进时报 drift | 中 |
| **P1-5 成本可视化** | R-6, Q-36..Q-39 | run 详情显示每 step token + 成本；按 meta-skill 聚合周/月报表；命中"该用 small 用了 large"打标 | 低-中 |

## 8. P2 列表（5 项）

| 主题 | 命中 | 暂不紧迫的原因 |
|---|---|---|
| P2-1 跨会话偏好/记忆 | Q-16, Q-17, Q-18 | 收益大但跨 memory 子系统改造大，P0/P1 稳后再动 |
| P2-2 验证 WebUI 化 | A-5, A-6, A-8 | 受众小（作者），CLI 已能用 |
| P2-3 组织级策略 | M-1..M-4 | 自部署用户才需，大客户出现前不阻塞 |
| P2-4 个性化/受众/语种 | Q-43, Q-44, Q-45 | 可在 P1-2 clarify 顺手开 audience 字段先苟住 |
| P2-5 多模态质量 | Q-30, Q-31, Q-32 | 只命中两个 meta-skill，优先级随使用量浮动 |

## 9. 推荐打法顺序

```
M0 (本季度) ───────────────────────────────────────────────
  P0-1 中途可见性  ───┐
  P0-4 Artifact card ─┼─ 表面 UX，前端 + 事件层为主，可并行
                      │
  P0-2 调用前确认 + 脚手架 ──┐
  P0-3 输出契约强化     ─────┼─ 串行：先立"输入"，再立"输出"
  P0-5 失败救援         ─────┘   最后兜底失败链路

M1 (下季度) ───────────────────────────────────────────────
  P1-5 成本可视（小成本先吃）
  P1-1 WebUI run 历史   ─┐
  P1-2 Clarify 对话化   ─┼─ 高级/普通用户体验拉齐
  P1-4 效果回归基线     ─┘   防住质量 drift
  P1-3 作者轻量入口（生态侧）

M2+ (机会窗口) ────────────────────────────────────────────
  P2 全部，按客户/用量浮动
```

## 10. 关键耦合

1. **P0-2 → P0-3 是输入输出契约的双链**：P0-2 不做，P0-3 的 audit 只能挂红灯（垃圾输入仍产生垃圾输出）。
2. **P0-1 是 P1-1 的数据源**：P0-1 把事件粒度补齐，P1-1 几乎只是"展示"。
3. **P0-3 与 P1-4 同源**：output_contract 的字段可直接作为 eval rubric 的判分维度，节省重复设计。
4. **P0-4 与 P0-5 共享 verify 链路**：artifact 校验失败应进入 P0-5 的失败救援流程，不应两套路径。

## 11. 风险与开放问题

- **R-1 prompt token 预算**：P0-3 末端 audit step 给每次 run 增加一次 LLM 调用；需评估对延迟与成本的影响，考虑按风险分级跳过。
- **R-2 contract 维护成本**：9 个 meta-skill 都补 `output_contract` 与 `request_template` 是一次性大投入；建议先做 3 个高频 skill（research / decision / brief）样板。
- **R-3 前端组件耦合**：step ribbon / confirm card / artifact card / action chips 都落在 `chat.js`，建议先抽 chat 内组件层再叠新组件，避免一锅粥。
- **R-4 partial output 安全**：P0-5 的"部分成功也返回"可能泄露未脱敏中间产物，需评审。
- **R-5 metric 缺位**：本路线图未指定衡量"用户体验改善"的具体指标。开放问题：用哪些线上信号（误触发率 / 重跑率 / artifact 缺失率 / 完成率 / 投诉数）来跟踪 P0 完工后的实际提升？

## 12. 决策记录（待填）

- [ ] 团队是否认可 P0 / P1 / P2 分级
- [ ] 是否同意"先 3 个高频 skill 样板出 `output_contract`"
- [ ] M0 季度内能投入多少人力
- [ ] 每个 P0 主题是否各起独立 spec + plan

## 13. 下一步

- 本路线图通过后，每个 P0 主题各起一个 spec：
  - `docs/proposals/specs/<date>-meta-skill-run-progress-design.md` (P0-1)
  - `docs/proposals/specs/<date>-meta-skill-pre-flight-contract-design.md` (P0-2)
  - `docs/proposals/specs/<date>-meta-skill-output-contract-design.md` (P0-3)
  - `docs/proposals/specs/<date>-meta-skill-artifact-card-design.md` (P0-4)
  - `docs/proposals/specs/<date>-meta-skill-failure-rescue-design.md` (P0-5)
- 每个 spec 跟一个 implementation plan，按 superpowers:writing-plans 流程

---

[Docs index](../../README.md) · [MetaSkill 用户指南](../../features/meta-skill-user-guide.md) · [作者指南](../../authoring/meta-skills.md)
