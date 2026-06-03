# Frontend Review — 2026-06-03

Branch: `feature/frontend-vue` · Scope: `opensquilla-webui/`
Reviewers: code-reviewer · architect · designer (parallel)

栈：Vue 3.4 + Vite 5 + Pinia 2 + Vue Router 4 + TypeScript 5。WebSocket RPC ↔ Starlette gateway，构建产物挂在 `/control/`。

---

## 0. 总评

迁移完成度高：`lib/rpc.ts`（指数退避 / ping / 序列号 / tick watchdog）、CSS token 体系、`useSessions` 合约规范化都是优于平均水平的设计。问题集中在两点：

1. 一个 critical XSS 缺口与一个明显的暗色主题穿透 bug 必须立刻修。
2. 抽象层级没跟上功能密度——composable 写好了不被使用，`App.vue` 与 `ChatView.vue` 在膨胀。

无结构性失误，重构路径清晰。

---

## 1. P0 — 立刻修（高风险 / 低工作量）

### P0-1 🔴 XSS：DOMPurify 配置过宽
- **位置**：`opensquilla-webui/src/views/ChatView.vue:1592`
- **现象**：`ALLOWED_ATTR` 含 `class` 与 `src`，未限制 URI scheme。markdown 注入的 `javascript:` / `data:` URL 可绕过、`class` 可用于视觉欺骗。
- **修复**：
  ```ts
  DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [...],
    ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel'],   // 移除 'class'、'src'
    ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
    FORCE_BODY: true,
  })
  ```

### P0-2 🔴 暗色主题穿透
- **位置**：`opensquilla-webui/src/assets/base.css`
  - `L1038`: `background: #fff` → `var(--bg-surface)`
  - `L1007`: `background: #f5f5f5` → `var(--bg-elevated)`
  - `L942` / `L1058`: `color: #fff` → `var(--accent-foreground)`
- **现象**：dark 主题下普通 view 的 `.content` 区呈白色；topbar chat 模式 hover 出现亮色块。

### P0-3 🟠 `resolvedTheme` 计算属性失效 + 监听器永久泄漏
- **位置**：`opensquilla-webui/src/stores/app.ts:12-15` 与 `:28-33`
- **现象**：
  - `computed` 内直接读 `window.matchMedia(...).matches`，Vue 不追踪它，系统主题切换时 UI 不刷新。
  - `mq.addEventListener('change', handler)` 注册后无引用，永远无法移除；HMR/测试下会重复堆叠。
- **修复**：
  ```ts
  const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
  const resolvedTheme = computed(() =>
    theme.value !== 'system' ? theme.value : systemDark.value ? 'dark' : 'light'
  )
  // initTheme:
  const handler = (e: MediaQueryListEvent) => { systemDark.value = e.matches }
  mq.addEventListener('change', handler)
  // 暴露 destroyTheme(): mq.removeEventListener('change', handler)
  ```

### P0-4 🟠 `waitForConnection` 永不超时
- **位置**：`opensquilla-webui/src/lib/rpc.ts:96-104`
- **现象**：gateway 不可达时 promise 永远挂起，`useSessions.loadSessions`、`ChatView.subscribeSession`、`loadHistory` 等 await 链路全部静默 stall。
- **修复**：增加超时参数（默认 30s），到期 reject 并清理 `_state` listener。

### P0-5 🟠 `useRpc` composable 订阅泄漏
- **位置**：`opensquilla-webui/src/composables/useRpc.ts:13` 与 `:54`
- **现象**：`_state` 监听器返回的 unsub 没有在局部 `onUnmounted` 中调用；RPC 重连后旧订阅孤儿化。`useRpcCall` 同样未存 unsub。

---

## 2. P1 — 架构债

### P1-1 `App.vue` 职责过载（~670 行）
拆分目标：
- `composables/useSidebar.ts`：`sidebarConversations` / `conversationFamilies` / `localChatSessions` / 展开持久化（`App.vue:416-514`、`L293`、`L627-639`）
- `utils/sessions.ts`：`normalizeAgentId` / `webchatSessionKey` / `agentDisplayName` / `humanize` / `conversationMeta` / `sourceFamilyForSession`（`App.vue:314-381`）—— `ChatView.vue:1460-1465` 有同名重复
- `components/NewChatDialog.vue`：弹窗模板 + 焦点陷阱 + `loadAgents`（`App.vue:147-190`、`L544-595`）

目标：`App.vue` `<script setup>` 收敛到 ~150 行。

### P1-2 `useSessions` 不是单例
- **位置**：`App.vue:250` 与 `SessionsView.vue:293` 各调一次 `useSessions()`，各持独立 sessionsList，各发一次 `sessions.list`。
- **方案**：改为 `stores/sessions.ts` Pinia store。

### P1-3 `useRpcCall` / `useRpcEvent` 形同虚设
- **位置**：`opensquilla-webui/src/composables/useRpc.ts`
- **现象**：写好但 11 个 view 全部直接用 `rpcStore`，自己复写"连接就绪后调用"逻辑（`OverviewView.vue:354`、`AgentsView.vue:388` 等）。
- **决策**：要么强制切换并补齐缺失的能力，要么删除。

### P1-4 localStorage key 散落
集中到 `lib/storage.ts`：
- `opensquilla.wsUrl` —— `stores/rpc.ts:13-27` 与 `OverviewView.vue:511-531` 完整重复
- `opensquilla.elevatedMode`（`ELEVATED_MODE_KEY`）—— `ChatView.vue:650` 与 `ApprovalsView.vue:167` 各定义一份
- `opensquilla_active_session`（`ChatView.vue:3443`，且无 try/catch，私有模式抛 SecurityError 会中断 `onMounted`）
- `opensquilla_sidebar_conversation_groups`（`App.vue:629`）

### P1-5 路由 meta 与侧栏双维护
- **位置**：`router/index.ts:33-45` 声明的 `meta.group/icon` 未被消费；`App.vue:385-393` 硬编码了 `quickRoutes`。
- **方案**：从 `router.getRoutes()` 按 `meta.group` 过滤生成 `quickRoutes` / `bottomRoutes`。

### P1-6 巨型单文件组件
| 文件 | 行数 | 拆分建议 |
|------|------|---------|
| `views/ChatView.vue` | 5997 | `ChatMessage.vue` / `RouterFxStrip.vue` / `ChatComposer.vue` |
| `views/CronView.vue` | 2843 | 列表 / 表单 / cron 解析帮助 |
| `views/SetupView.vue` | 2207 | 步骤组件化 |
| `views/SkillsView.vue` | 1918 | 列表 / 详情 |

### P1-7 `agents.list` 类型重复定义
`App.vue:252-256` / `AgentsView.vue:253` / `OverviewView.vue` 各一份。集中到 `types/rpc.ts`。

### P1-8 `editMessage` 索引映射错位
- **位置**：`ChatView.vue:3119-3142`
- **现象**：`v-for` 在 `renderedMessages` 上、函数按 `messages` 数组重数 user 消息；`renderedMessages` 含 router-strip 合成项时映射偏移。
- **修复**：通过 `msg.messageId` 查找而非索引。

### P1-9 `editMessage` 之外的小 timer 泄漏
- **位置**：`ChatView.vue:2901-2904` `setTimeout(hideCompactStatus, options.dismissMs)` 返回的 id 被丢弃，`onUnmounted` 不清理。

---

## 3. P1 — UX / a11y

| ID | 问题 | 文件 | 修复 |
|----|------|------|------|
| UX-1 | 新建聊天弹窗无焦点陷阱、Tab 会逃出 | `App.vue:147-190`, `openNewChatPicker()` | `nextTick` + 初始 focus + Tab cycle |
| UX-2 | 侧栏折叠按钮无 `aria-label` | `App.vue:24` | 动态 `:aria-label="appStore.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'"` |
| UX-3 | 历史项 `:title` 暴露原始 session key | `App.vue:112` | `:title="item.title \|\| item.key"` |
| UX-4 | 移动端首次加载侧栏默认展开覆盖内容 | `stores/app.ts:8` | `sidebarOpen` 按 `window.innerWidth > 768` 初始化 |
| UX-5 | 4px hover trigger 触摸屏不可触发 | `base.css:359` | 移动端 media query 内隐藏 `.sidebar-hover-trigger` |
| UX-6 | 自定义 checkbox 失去焦点环 | `SessionsView.vue:133-143` | `.sess-check input:focus-visible + span { outline: 2px solid var(--accent); }` |
| UX-7 | LoadingSpinner reduced-motion 减速而非停止 | `LoadingSpinner.vue:26-28` | `animation: none` |
| UX-8 | Firefox 滚动条样式缺失 | `base.css:207-210` | 补 `scrollbar-width: thin; scrollbar-color: var(--border) transparent` |
| UX-9 | 新建聊天弹窗硬编码 `padding-left: 276px`，hover overlay 时错位 | `base.css:716-724` | `position: fixed` + `translate(-50%, -50%)` 或基于 `--sidebar-width` 变量 |
| UX-10 | "Approval required" 仅靠红底传达紧急 | `App.vue:215-219` | 加 `aria-live="polite"`，文本前置数量 |
| UX-11 | 中文硬编码 | `ChatView.vue:135` "次"、`L901` placeholder、`L661` `SQUILLA_VERBS` | 抽 i18n 或英文化（按产品定位决策） |
| UX-12 | 字体 `Inter` 未引入 | `base.css:10` | `@font-face` 引入或改用系统字体栈命名 |
| UX-13 | 空状态文案 / 视觉权重三处不一致 | sidebar / OverviewView / SessionsView | 统一文案与视觉框架 |

---

## 4. P3 — 清理

- `base.css:889-937` legacy `.nav-*` 死代码（48 行）
- `nav-item.is-active` vs `sidebar-fn-item.is-active` 两套 active 样式并存
- `sess-stage__title::after` 与 `ov-stage__title::after` 重复渐变下划线 → 抽 `.view-title-underline` utility
- `routerBurstStyle` / `routerSelectorStyle` 硬编码 px（`ChatView.vue:1211-1240`）

---

## 5. 测试基础设施

- ❌ 无 Vitest，0 单元测试。`useSessions.normalizeSessionItem` / `sessionRunStatus` / `groupSessions` 是最该测的纯函数。
- Playwright e2e 仅 1 个 spec（`e2e/chat.spec.ts`），且 `L9` `waitForSelector('.conn-pill')` 要求实际 WebSocket 连接，CI 离线无法执行。
- `package.json` 仅有 `test:e2e`，需新增 `test` 与 vitest 依赖。

---

## 6. 推荐落地顺序

### 第一周（低风险高收益）
1. P0-1 ~ P0-5（XSS、`#fff` 硬编码、`resolvedTheme` 监听器、`waitForConnection` 超时、`useRpc` unsub）
2. P1-4 `lib/storage.ts` 集中 localStorage key
3. P3 清理 `base.css` legacy 死代码
4. P1-2 `useSessions` → Pinia store

### 第二周（结构性）
5. P1-1 `App.vue` 抽 `useSidebar` + `utils/sessions.ts` + `NewChatDialog.vue`
6. P1-5 路由 meta 驱动侧栏
7. P1-3 RPC composable 决策（用 or 删）

### 长期
8. P1-6 ChatView 拆分
9. Vitest + WebSocket mock 让 e2e 离线可跑
10. P1-7 类型集中

---

## 附：关键文件 → 问题映射（grep 友好）

```
src/views/ChatView.vue:1592       P0-1  DOMPurify 配置
src/views/ChatView.vue:3119       P1-8  editMessage 索引错位
src/views/ChatView.vue:3443       P1-4  localStorage 无 try/catch
src/views/ChatView.vue:5997 行    P1-6  巨型组件
src/assets/base.css:1038          P0-2  background: #fff
src/assets/base.css:1007          P0-2  background: #f5f5f5
src/assets/base.css:942/1058      P0-2  color: #fff
src/assets/base.css:889-937       P3    legacy .nav-* 死代码
src/stores/app.ts:12-15           P0-3  resolvedTheme 计算失效
src/stores/app.ts:28-33           P0-3  matchMedia listener 泄漏
src/stores/app.ts:8               UX-4  sidebarOpen 移动端初值
src/lib/rpc.ts:96-104             P0-4  waitForConnection 无超时
src/composables/useRpc.ts:13/54   P0-5  unsub 泄漏
src/composables/useSessions.ts    P1-2  应改 Pinia store
src/App.vue:24                    UX-2  aria-label
src/App.vue:112                   UX-3  title 暴露 raw key
src/App.vue:147-190               UX-1  弹窗焦点陷阱
src/App.vue:215-219               UX-10 approval aria-live
src/App.vue:252-256               P1-7  AgentOption 类型重复
src/App.vue:293                   P1-1  localChatSessions 应迁移
src/App.vue:314-381               P1-1  工具函数应抽出
src/App.vue:385-393               P1-5  quickRoutes 硬编码
src/App.vue:416-514               P1-1  侧栏分组逻辑应抽出
src/router/index.ts:33-45         P1-5  meta 未消费
src/components/LoadingSpinner.vue:26  UX-7  reduced-motion
src/views/SessionsView.vue:133-143    UX-6  自定义 checkbox focus
src/views/OverviewView.vue:511-531    P1-4  连接设置重复
src/views/ApprovalsView.vue:167       P1-4  ELEVATED_MODE_KEY 重复
e2e/chat.spec.ts:9                测试  依赖实际 gateway
```
