# OpenSquilla 沙箱设计：远程更新后的新旧对比

日期：2026-06-01

## 结论

原设计的核心判断仍然成立，而且当前代码进一步证明这件事必须做：

- `bypass` 仍然和 host execution 混在一起。
- Chat 前端已经把旧的 `Bypass Off` 文案改成了 `Execution mode`，但底层行为仍然是 `/elevated bypass`。
- Approvals 页新增了 `Effective execution mode` 摘要，这说明产品上已经开始感知“审批策略”和“执行模式”是两回事。
- 侧边栏结构仍然适合新增 `Control -> Sandbox`，但新的 topbar/chat 布局要求原 spec 的前端落点更精确。

所以原 spec 不需要推翻，但需要做一次 v2 修订。修订重点不是后端大方向，而是：

1. 明确当前 `topbar-center` 和 composer gear 的职责边界。
2. 明确现有 `Visual effects` 不属于沙箱控制，不要被 sandbox spec 误删。
3. 明确 Approvals 页和全局 approval modal 都要从旧 `Bypass Approvals` 迁移。
4. 明确 Squilla Router 可以继续保留现有配置路径，不必强绑进 sandbox Run Context。
5. 明确 Allowed Domains 不能破坏现有 `network.http` / `web_fetch` 测试语义。

## 当前代码状态

### 1. 主导航已经有标准视图包装

当前 `app.js` 用 `_renderStandardView()` 包装除 Chat 外的大多数页面。这个包装会先清空 `topbar-center`，再渲染页面，见 `src/opensquilla/gateway/static/js/app.js:31` 到 `src/opensquilla/gateway/static/js/app.js:52`。

这对 Sandbox 页有直接影响：新增 `/sandbox` route 时应该走 `_renderStandardView(SandboxView, ...)`，这样从 Chat 切到 Sandbox 时，Chat 专属的 session chip、run status、context warning 不会残留。

当前侧边栏仍然是：

- Chat
- Control: Overview, Health, Channels, Skills, Sessions, Agents, Usage, Cron
- Settings: Config, Logs, Approvals

代码位置见 `src/opensquilla/gateway/static/js/app.js:70` 到 `src/opensquilla/gateway/static/js/app.js:87`。

原 spec 说把 Sandbox 放在 `Control -> Health` 后面仍然合适。需要补充的是：当前代码还没有 `/sandbox` route，也没有 Sandbox nav item；实现时要同时加 route、nav item、icon 和 view registration。

### 2. Chat 顶部结构已经变了

旧分析时，Chat session chip、run status、context warning 都在 Chat 页面自己的 header 里。现在它们被移到了全局 topbar 的 center slot：

- `App.getTopbarCenter()` 暴露 topbar center。
- Chat 渲染时把 session chip、copy、run status、context warning 放进去。
- 标准页面渲染时会清掉这个 slot。

代码见 `src/opensquilla/gateway/static/js/app.js:216` 到 `src/opensquilla/gateway/static/js/app.js:224`，以及 `src/opensquilla/gateway/static/js/views/chat.js:1182` 到 `src/opensquilla/gateway/static/js/views/chat.js:1195`。

这意味着原 spec 里“聊天输入框功能键只放 Run Mode / Workspace / Squilla Router / Open Sandbox...”的方向仍然可用，但需要更精确：

- `topbar-center` 是会话身份和运行状态区，不建议塞复杂设置。
- composer gear 是“下一次执行前的快捷设置”区，仍然适合放 Run Mode、Workspace、Router。
- 如果未来想让 Run Mode 更显眼，可以在 topbar-center 只显示一个只读状态 chip，但编辑入口仍然放在 composer gear 或 Sandbox 页。

### 3. Composer gear 现在已经不是纯 sandbox 控制

当前 composer gear 里有三行：

- `Execution mode`
- `Squilla Router`
- `Visual effects`

代码见 `src/opensquilla/gateway/static/js/views/chat.js:1213` 到 `src/opensquilla/gateway/static/js/views/chat.js:1244`。

这和原 spec 的一句话有冲突：原 spec 写得像是 composer gear 只能放 `Run Mode / Workspace / Squilla Router / Open Sandbox...`。现在应该改成：

> composer gear 可以继续承载当前已有的轻量会话设置；其中 sandbox 相关控制只新增 Run Mode、Workspace 和 Open Sandbox，不把 Mounts、Domains、Doctor、Rules 塞进去。现有 Visual effects 是非沙箱的外观设置，保留但需要视觉上弱化或分组，避免用户误以为它影响安全边界。

推荐的新 composer gear 内容：

- Run Mode
- Workspace
- Squilla Router
- Visual effects
- Open Sandbox...

其中前两项属于 sandbox run context；Router 保留现有产品行为；Visual effects 是纯前端偏好；Open Sandbox 是跳转入口。

### 4. `Execution mode` 名字已经接近新设计，但行为还是旧设计

Chat 里现在的按钮文案是 `Execution mode`，默认显示 `Approval prompts`，但点击后仍然弹出：

> This allows host execution without approval prompts in this browser session. This maps to /elevated bypass.

代码见 `src/opensquilla/gateway/static/js/views/chat.js:1321` 到 `src/opensquilla/gateway/static/js/views/chat.js:1343`。

这说明 UI 已经从 “Bypass Off” 迈向 “Execution mode”，但它仍然把 bypass 和 host execution 绑在一起。原 spec 的三档 Run Mode 设计仍然是正确方向，但需要把当前 UI 迁移点写得更具体：

- 把 `Execution mode` 行改成 `Run Mode`。
- 当前按钮不再是一个 bypass toggle，而是三档选择器。
- `Standard-Sandbox` 和 `Trusted-Sandbox` 都不能调用旧 `/api/elevated-mode` 去启用 host。
- 切到 `Full Host Access` 时才进入 host execution。
- 旧 localStorage key `opensquilla.elevatedMode` 只能作为迁移读取，不应继续作为新状态源。

### 5. Approvals 页新增了执行模式摘要

当前 Approvals 页已经并列展示：

- pending 数量
- approval strategy
- effective execution mode

代码见 `src/opensquilla/gateway/static/js/views/approvals.js:69` 到 `src/opensquilla/gateway/static/js/views/approvals.js:105`。

这是好变化，说明产品已经承认两层含义：

- approval strategy：怎么处理审批请求
- execution mode：命令在哪里、以什么姿态执行

但现在 `effective execution mode` 仍然从旧 localStorage/global config 的 elevated mode 推导，见 `src/opensquilla/gateway/static/js/views/approvals.js:176` 到 `src/opensquilla/gateway/static/js/views/approvals.js:245`。

原 spec 需要补一条：

> Approvals 页的 `Effective execution mode` 应该改为读取新的 Run Context，而不是读旧 elevated/localStorage/default_mode。这个摘要可以保留，因为它是新设计的天然展示位。

### 6. Approvals 页面和全局 modal 仍有 `Bypass Approvals`

当前 Approvals 列表每条 pending request 有：

- Approve once
- Always allow this type
- Bypass approvals
- Deny

代码见 `src/opensquilla/gateway/static/js/views/approvals.js:274` 到 `src/opensquilla/gateway/static/js/views/approvals.js:278`。

全局 approval modal 也有 `Bypass Approvals`，代码见 `src/opensquilla/gateway/static/js/approval_monitor.js:154` 到 `src/opensquilla/gateway/static/js/approval_monitor.js:178`。

原 spec 已经说普通审批不应该出现 Host Once，也说 bypass 不等于 host execution。但现在需要更明确地覆盖这两个具体前端入口：

- `Bypass Approvals` 不能继续传 `elevatedMode: "bypass"`。
- 普通审批卡片推荐只保留 Approve Once / Always Allow This Type / Deny / Deny This Type。
- 如果产品仍想提供“少问我”入口，它应该是“Switch to Trusted-Sandbox”，并且必须说明仍在沙箱内执行。
- 这个入口最好不在每条 approval 的主按钮里，否则会鼓励用户在压力下扩大权限。

### 7. Router 当前是全局 config patch，不是 session Run Context

当前 Chat gear 的 Squilla Router toggle 调用的是 `config.patch.safe`，修改：

- `squilla_router.enabled`
- `squilla_router.rollout_phase`

代码见 `src/opensquilla/gateway/static/js/views/chat.js:1352` 到 `src/opensquilla/gateway/static/js/views/chat.js:1365`。

原 spec 把 `Squilla Router state` 放进 session Run Context。远程更新后，这一点建议修订：

- Sandbox Run Context 不应该强行接管 Router。
- composer gear 仍然显示 Router，因为它是现有主界面控制。
- 但 Router 可以继续走现有 `config.patch.safe` 路径，除非后续另开“Router session scope”设计。
- Sandbox 的 P0/P1 不应该因为 Router session 化而变重。

换句话说，新 spec 里应该把 “Run Context 包含 Squilla Router state” 改成：

> composer gear 同屏展示 Squilla Router，但 sandbox Run Context 只负责 execution/mount/domain/grant；Router 继续使用现有配置机制，除非另一个需求明确要 session-level router。

### 8. Config 文案仍然是旧权限模型

当前 Config help 仍然写着：

- `sandbox.sandbox`: use `opensquilla sandbox on|bypass|full`
- `permissions.default_mode`: `bypass` is out-of-box local posture, `on` uses host execution, `full` bypasses sensitive paths

代码见 `src/opensquilla/gateway/static/js/views/config.js:69` 到 `src/opensquilla/gateway/static/js/views/config.js:74`。

原 spec 应该补充：迁移不仅是 Chat 和 Approvals，还包括 Config help 文案、slash command help 文案和 tool context 注释。否则用户会在不同界面看到两套冲突语义。

### 9. `/permissions` 和 `/elevated` 已经统一到 slash-command registry

当前 `/permissions` 的 choices 仍然是旧模型：

- `on`: Host exec, approvals required
- `bypass`: Host exec, approvals auto-granted
- `full`: Host exec, approvals skipped

代码见 `src/opensquilla/engine/commands.py:334` 到 `src/opensquilla/engine/commands.py:347`。

原 spec 有“legacy wording should be mapped at the boundary”，但现在需要更具体：

- `/permissions` 应该成为 `/run-mode` 或保留 `/permissions` 但显示三档 Run Mode。
- `/elevated` alias 可以保留兼容，但不应该继续作为新帮助里的主要词。
- 旧 `on` 不应作为新模式暴露。
- 旧 `bypass` 应迁移成 `Trusted-Sandbox`。
- 旧 `full` 应迁移成 `Full Host Access`。

### 10. 后端仍然把 approval 和 host execution 绑在一起

当前 shell 工具的注释和逻辑非常明确：

- `_elevate_current_call` 表示“本次调用允许 host execution”，见 `src/opensquilla/tools/builtin/shell.py:118` 到 `src/opensquilla/tools/builtin/shell.py:125`。
- `/elevated on|bypass|full` 会绕过 sandbox backend，见 `src/opensquilla/tools/builtin/shell.py:663` 到 `src/opensquilla/tools/builtin/shell.py:670`。
- `bypass` 会跳过审批并设置 `_elevate_current_call`，见 `src/opensquilla/tools/builtin/shell.py:1335` 到 `src/opensquilla/tools/builtin/shell.py:1345`。
- 普通 approval 通过后也会设置 `_elevate_current_call`，见 `src/opensquilla/tools/builtin/shell.py:1481` 到 `src/opensquilla/tools/builtin/shell.py:1485`。

这正是原 spec 要解决的核心问题。原 spec 不需要改方向，但应该在“迁移目标”里点名这些现有入口：

- `ToolContext.elevated`
- approval queue session elevated mode
- `/api/elevated-mode`
- `_elevate_current_call`
- approval resolve 的 `elevatedMode`
- Chat localStorage `opensquilla.elevatedMode`

否则 implementation plan 容易只改前端文案，而没有真正拆开执行目标和审批行为。

### 11. `LevelHints` 仍然很浅，原 hints 设计仍然需要

当前 `LevelHints` 有字段：

- `trusted_source`
- `needs_network`
- `writes_outside_workspace`
- `crosses_trust_boundary`
- `high_impact`

代码见 `src/opensquilla/sandbox/policy.py:43` 到 `src/opensquilla/sandbox/policy.py:57`。

但规则主要仍按 action tag 走，`needs_network` 没有直接参与网络策略。当前 `_resolve_network()` 是：

- `DISABLED` -> `HOST`
- `network.*` 且 `STANDARD` -> `HOST`
- 其他 -> `NONE`

见 `src/opensquilla/sandbox/policy.py:148` 到 `src/opensquilla/sandbox/policy.py:155`。

原 spec 说 hints 应该进入 Operation Profile，这一点仍然成立。

### 12. 网络设计要避开现有测试语义

当前测试明确要求：

- `network.http` 在 STANDARD 下保留 `NetworkMode.HOST`
- `shell.exec` / `code.exec` 在 STANDARD 下 `NetworkMode.NONE`

见 `tests/test_sandbox/test_policy_network.py`。

这和原 spec 的 “Allowed Domains” 不一定冲突，但原 spec 表述偏宽，容易让实现误伤现有测试。建议修订为：

> P1 的 Allowed Domains / package bundle 首先约束 sandboxed shell/code/package-manager egress。现有显式网络工具如 `web_fetch`、`http_request` 的 `network.http -> HOST` 语义不在 P0 改动范围内；如果未来要统一给网络工具也加域名审批，需要另开迁移并新增测试，而不是改松现有 `tests/test_sandbox`。

这样可以同时满足用户要求：可以补 sandbox 测试，但不要改原有测试。

## 原 spec 逐项判断

| 原 spec 部分 | 是否仍有效 | 是否建议修改 | 说明 |
| --- | --- | --- | --- |
| Goal | 有效 | 小改 | 可以补一句“当前 UI 已经出现 Execution mode 摘要，但仍基于旧 elevated”。 |
| Non-Goals | 有效 | 小改 | 增加“不把 Router session 化作为本阶段目标”。 |
| User-Facing Modes | 有效 | 不改核心 | 三档命名和语义仍然正确。 |
| Frontend Placement | 部分有效 | 必改 | 当前有 topbar-center 和 Visual effects，需要更新 composer gear 描述。 |
| Sandbox Page | 有效 | 小改 | 新增 route 应走 `_renderStandardView`，位置仍在 Health 后。 |
| Run Context | 部分有效 | 必改 | Router 不建议放进 sandbox Run Context。 |
| Tool Execution Flow | 有效 | 小改 | 加一句当前 approval grant 不能再隐式 host。 |
| Operation Profile And Hints | 有效 | 不改核心 | 当前 LevelHints 状态证明这块仍然必要。 |
| Approval Matrix | 有效 | 小改 | 明确覆盖 Approvals 页和 ApprovalMonitor modal。 |
| Host Once | 有效 | 不改核心 | 当前 `escalate_backend_denial` 类路径说明这块有落点。 |
| External Path Access | 有效 | 不改核心 | 当前没有 UI 支持，仍然是新能力。 |
| Cross-Platform Path Validation | 有效 | 不改核心 | 用户强调后仍应保留。 |
| Allowed Domains | 部分有效 | 必改 | 要避免破坏 `network.http -> HOST` 的既有测试。 |
| Doctor And Explain | 有效 | 小改 | Health 页已经有 doctor.status，Sandbox 页应复用。 |
| Testing Strategy | 有效 | 小改 | 明确只新增测试，不改现有 test expectations。 |
| ROI | 基本有效 | 小改 | Router session 化不进 ROI；UI migration 优先级上升。 |

## 建议写入原 spec 的修订

### 修订 1：Frontend Placement

旧表达：

> The chat composer gear remains the quick control ... only show Run Mode, Workspace, Squilla Router, Open Sandbox...

建议改成：

> The current app has a global topbar center slot used by Chat for session identity and run status. Sandbox editing controls should stay in the composer gear, while topbar center may show read-only state only. The composer gear already contains non-sandbox controls such as Visual effects; sandbox-related additions must stay limited to Run Mode, Workspace, and Open Sandbox, preserving existing Router and Visual effects rows without turning the popover into a full security console.

### 修订 2：Sandbox route

补充：

> `Control -> Sandbox` should be registered as a standard view, using the same `_renderStandardView` pattern as Overview, Health, Config, and Approvals, so Chat-specific topbar content is cleared when navigating away from Chat.

### 修订 3：Run Context

旧表达包含：

> Squilla Router state

建议改成：

> Sandbox Run Context owns run mode, workspace, mounts, allowed domains, package bundles, temporary grants, and doctor/explain summary. Squilla Router remains visible in the same composer popover for convenience, but continues to use its existing router configuration path unless a separate router-session design is approved.

原因：当前 Router toggle 写的是 `config.patch.safe`，把它强行并入 sandbox Run Context 会扩大本需求范围。

### 修订 4：Approval UI migration

补充：

> Both `ApprovalsView` and `ApprovalMonitor` must migrate away from `Bypass Approvals -> elevatedMode=bypass`. Ordinary approvals should not offer a host-like bypass action. If a shortcut remains, it must be framed as switching the session to `Trusted-Sandbox`, and it must keep execution sandboxed.

### 修订 5：Config and slash command wording

补充：

> Migration must update all user-facing copies of the old model: Config help, `/permissions` and `/elevated` command descriptions, Chat localStorage state, Approvals summaries, and API errors from `/api/elevated-mode`.

### 修订 6：Allowed Domains scope

补充：

> Allowed Domains are first applied to sandboxed shell/code/package-manager egress and package install bundles. Existing explicit network tools that currently resolve to `NetworkMode.HOST` are not changed in the first implementation slice, because current sandbox tests depend on that behavior.

### 修订 7：Testing

补充：

> Additive tests should include current frontend migration surfaces where practical: Chat no longer sends `elevatedMode=bypass` for `Trusted-Sandbox`, Approvals/ApprovalMonitor no longer use bypass to imply host execution, and explicit network-tool tests keep their existing expectations.

## 新旧设计对比

### 旧版设计

旧版设计假设前端仍接近这个形态：

- Chat 页面内部有自己的 header。
- composer gear 主要只有 Approvals / Router。
- Approvals 页只是审批策略和 pending list。
- Router 与 sandbox 快捷设置可以一起进入 session Run Context。

在这个假设下，把 `Run Mode / Workspace / Squilla Router / Open Sandbox...` 都塞进 composer gear 是合理的。

### 当前代码后的新版设计

当前代码更像这样：

- App 有全局 topbar。
- Chat 独占 topbar center，用于 session chip、run status、context warning。
- composer gear 已经成为轻量设置 popover，包含 Execution mode、Router、Visual effects。
- Approvals 页已经有 execution mode 摘要。
- Approvals modal 和 page 仍然提供 Bypass Approvals。

所以新版设计应变成：

- topbar-center：只读会话状态，不作为 sandbox 配置主入口。
- composer gear：轻量快捷配置，包含 Run Mode、Workspace、Router、Visual effects、Open Sandbox。
- Sandbox page：完整沙箱管理，仍在 Control 组 Health 后。
- Approvals page：显示审批策略和 Run Mode 摘要，但不负责切换到 host。
- Approval modal：只处理当前请求，不鼓励全局 bypass。

## 实现风险更新

### 风险 1：只改文案，不改执行语义

当前 Chat 已经把按钮叫 `Execution mode`，但点击后仍然是 host execution bypass。实现时如果只把文案换成 `Trusted-Sandbox`，安全问题不会解决。

必须同时拆开：

- 是否问用户
- 是否进 sandbox
- 是否允许 host fallback

### 风险 2：Approvals 页会继续把 bypass 传播回 Chat

Approvals 页和 ApprovalMonitor 都会写 localStorage 并触发 `opensquilla:elevated-mode` 事件。即使 Chat gear 改了，如果这两个入口没改，用户仍可从审批弹窗把 session 推回旧 host bypass。

### 风险 3：Router 被误纳入 sandbox P0

Router 当前是全局 config toggle。强行 session 化会扩大需求，拖慢 sandbox 核心目标。推荐保持现状，只在 UI 上同处一个 popover。

### 风险 4：Allowed Domains 误伤 web_fetch/http_request

当前测试保留 `network.http -> HOST`。如果实现者把所有 network action 都改成 allowlist，会违反“不动原有 tests_sandbox”的要求。第一阶段只新增 shell/code/package-manager 相关域名控制。

### 风险 5：topbar-center 残留

新增 Sandbox 页如果不走标准 view wrapper，从 Chat 切过去可能残留 Chat session controls。实现 route 时要复用 `_renderStandardView`。

## 建议的新版 ROI

### P0

1. 拆开 `Run Mode` 和旧 `elevated`：`Trusted-Sandbox` 不能 host exec。
2. 新增 session sandbox Run Context：Run Mode、Workspace、Mounts、Domains、Grants 实时生效。
3. 改 Chat composer gear：`Execution mode` -> `Run Mode`，新增 Workspace，保留 Router / Visual effects，添加 `Open Sandbox...`。
4. 改 ApprovalsView 和 ApprovalMonitor：移除旧 `Bypass Approvals -> elevatedMode=bypass` 语义。
5. 外部路径先走 Path Access Request，不直接 host fallback。

### P1

6. 新增 `Control -> Sandbox` 标准页面，放在 Health 后。
7. Operation Profile + hints 接入策略。
8. Allowed Domains + package install bundles，但第一阶段不改变现有 explicit network tool 测试语义。
9. doctor/explain 复用 Health 的 doctor.status，并在 Sandbox 页展示更完整细节。

### P2

10. 后端硬隔离增强。
11. worktree/session 隔离。

### P3

12. Claude 式复杂 auto classifier 继续延后。

## 是否需要修改原 spec

需要，但不是重写。

建议对 `2026-05-29-sandbox-run-mode-design.md` 做 v2 patch，重点改这些小节：

- `Frontend Placement`
- `Run Context`
- `Approval Matrix`
- `Allowed Domains`
- `Testing Strategy`
- `ROI`
- 新增 `Current UI Migration Targets`

不建议改动这些核心结论：

- 三档 Run Mode。
- bypass 不等于 host exec。
- Host Once 只在沙箱失败后出现。
- hints 进入 Operation Profile，不直接授权。
- 外部路径优先问是否挂载。
- Cross-platform path validation 必须全面。
