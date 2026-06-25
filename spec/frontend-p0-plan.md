# P0 修复实施计划

来源：`spec/frontend-review-2026-06-03.md` §1
范围：5 个 P0 项，预计总工作量 60–90 分钟，可独立提交
分支建议：`fix/webui-p0-security-and-theme`（一次成 PR）或按 task 分 5 个 commit

---

## 全局约束

- 全部修改在 `opensquilla-webui/` 内
- 每个 task 完成后跑：`npm run typecheck` + `npm run build`
- 全部完成后跑：`cd opensquilla-webui && npm run build`，gateway 起在 `127.0.0.1:18790`，浏览器手测列表见末尾
- 不破坏现有 e2e（`e2e/chat.spec.ts`）
- 不引入新依赖
- 不修改后端、不动其他 P1/P3 项

---

## Task P0-1 — 收紧 DOMPurify 白名单

**风险等级**：🔴 Critical（XSS）
**文件**：`opensquilla-webui/src/views/ChatView.vue`
**位置**：`L1592` 附近 `DOMPurify.sanitize(...)` 调用

### 现状

```ts
ALLOWED_ATTR: [..., 'class', 'src', ...]   // class、src 暴露
// 无 ALLOWED_URI_REGEXP，javascript:/data: 可通过
```

### 实施步骤

1. 读 `ChatView.vue:1580-1620`，确认完整 sanitize 调用上下文（是否在 markdown 渲染或工具输出渲染中）
2. 改为：
   ```ts
   DOMPurify.sanitize(rawHtml, {
     ALLOWED_TAGS: [/* 保持现状 */],
     ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel'],
     ALLOWED_URI_REGEXP: /^(?:https?|mailto|#):/i,
     FORCE_BODY: true,
   })
   ```
3. 如果现有 markdown 输出依赖 `class`（例如 highlight.js 高亮 token），改为：
   - 方案 A：保留 `class`，但加 `ALLOWED_URI_REGEXP` 并移除 `src`，并在文档中标记为已知风险
   - 方案 B（首选）：渲染前用 marked 的 hooks 把 highlight 输出转换成 inline `style` 或在 sanitize 后由前端重新着色
4. 若现有渲染没有 `<img>` 需求，删除 `src` 与 `<img>` 标签即可
5. 决策：当前 chat 是否需要展示用户/工具消息中的图片？
   - 是：保留 `<img>` 与 `src`，但把 `ALLOWED_URI_REGEXP` 收紧到 `^(?:https?|data:image\/(png|jpeg|gif|webp);base64,):/i`
   - 否：从 `ALLOWED_TAGS` 移除 `img`、从 `ALLOWED_ATTR` 移除 `src`

### 验收

- [ ] 注入测试：在 chat 输入 `[click](javascript:alert(1))`，渲染后 `<a>` 不应有 href（或被剥离）
- [ ] 注入测试：在 chat 输入 `<img src=x onerror=alert(1)>`，渲染后无图也无脚本执行
- [ ] 现有 markdown（粗体、代码块、链接、列表）外观不变
- [ ] `npm run typecheck` 通过
- [ ] `npm run build` 通过

### 不做

- 不引入额外的 sanitizer（如 sanitize-html）
- 不重写 marked renderer
- 不动后端发送的 raw 字段

---

## Task P0-2 — 暗色主题硬编码颜色

**风险等级**：🔴（视觉破坏）
**文件**：`opensquilla-webui/src/assets/base.css`

### 现状

- `L1038`: `.content { background: #fff }` —— dark 主题下普通 view 内容区呈白色
- `L1007`: `.topbar--chat .btn--ghost:hover { background: #f5f5f5 }` —— hover 出现亮色块
- `L942`: 硬编码 `color: #fff`
- `L1058`: `.approval-inline { color: #fff }`

### 实施步骤

1. 读 `base.css:1-60` 确认现有 token：`--bg-surface` / `--bg-elevated` / `--bg-hover` / `--accent-foreground` 是否都已定义且在 light/dark 都有值
2. 替换：
   | 行 | 旧 | 新 |
   |----|----|----|
   | 1038 | `background: #fff` | `background: var(--bg-surface)` |
   | 1007 | `background: #f5f5f5` | `background: var(--bg-elevated)` |
   | 942 | `color: #fff` | `color: var(--accent-foreground)` |
   | 1058 | `color: #fff` | `color: var(--accent-foreground)` |
3. 如果 token 未定义对应的暗色值，先在 `:root` 与 `[data-theme="light"]` 各补一对
4. `grep -n "#fff\|#f5f5f5" src/assets/base.css` 检查是否还有遗漏

### 验收

- [ ] 切到 dark 主题，访问 `/overview`、`/sessions`、`/agents`、`/chat`，内容区背景跟随主题
- [ ] dark 主题下 `/chat` 页面 topbar 的 ghost 按钮 hover 不出现亮色块
- [ ] light 主题下 `.approval-inline` 文字仍可读（白底红字 OR 红底白字按现状）
- [ ] `grep -n "#fff\|#f5f5f5\|#ffffff" src/assets/base.css` 仅剩 token 定义本身或注释中的颜色

### 不做

- 不重构 token 体系
- 不改 `--accent` 等品牌色
- 不删除其他 legacy 样式（属于 P3）

---

## Task P0-3 — `resolvedTheme` 响应化 + listener 可清理

**风险等级**：🟠（功能 + 内存）
**文件**：`opensquilla-webui/src/stores/app.ts`
**位置**：`L12-15`、`L28-33`

### 现状

```ts
const resolvedTheme = computed(() => {
  if (theme.value !== 'system') return theme.value
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
})
// initTheme:
mq.addEventListener('change', () => applyTheme())   // handler 引用丢失
```

问题：
- `computed` 内读 `matchMedia` 不被 Vue 追踪 → 系统主题切换时 `resolvedTheme.value` 不更新
- handler 没有引用 → 永远无法 `removeEventListener`，HMR/测试下重复堆叠

### 实施步骤

1. 在 `defineStore` setup 中新增：
   ```ts
   const systemDark = ref(
     typeof window !== 'undefined'
       ? window.matchMedia('(prefers-color-scheme: dark)').matches
       : false
   )
   ```
2. 改 `resolvedTheme`：
   ```ts
   const resolvedTheme = computed(() =>
     theme.value !== 'system' ? theme.value : systemDark.value ? 'dark' : 'light'
   )
   ```
3. 改 `initTheme()`：
   ```ts
   let mq: MediaQueryList | null = null
   let mqHandler: ((e: MediaQueryListEvent) => void) | null = null

   function initTheme() {
     if (mq) return  // 幂等
     mq = window.matchMedia('(prefers-color-scheme: dark)')
     mqHandler = (e) => { systemDark.value = e.matches }
     mq.addEventListener('change', mqHandler)
     applyTheme()
   }

   function destroyTheme() {
     if (mq && mqHandler) mq.removeEventListener('change', mqHandler)
     mq = null
     mqHandler = null
   }
   ```
4. 导出 `destroyTheme`（Pinia store return 列表里加上）
5. `applyTheme()` 不再依赖手动调用，改为 `watch(resolvedTheme, applyTheme, { immediate: true })`
6. 检查 `main.ts` 是否调用了 `initTheme()`；保持原调用点

### 验收

- [ ] macOS 切换系统外观（dark↔light），`theme === 'system'` 时 UI 立即跟随（验证 `App.vue:301` 的 themeIconName 也跟着变）
- [ ] 多次调用 `initTheme()` 不堆叠 listener（`mq.addEventListener` 只调一次）
- [ ] 显式 `destroyTheme()` 后，`mq.dispatchEvent(...)` 不再触发 systemDark 变化
- [ ] `npm run typecheck` 通过
- [ ] e2e `chat.spec.ts` 中主题切换用例仍然通过

### 不做

- 不改主题切换 UI
- 不引入 VueUse `useMediaQuery`（保持零依赖）
- 不改 `cycleTheme` 行为

---

## Task P0-4 — `waitForConnection` 加超时

**风险等级**：🟠（静默 stall）
**文件**：`opensquilla-webui/src/lib/rpc.ts`
**位置**：`L96-104`

### 现状

```ts
waitForConnection(): Promise<void> {
  return new Promise((resolve) => {
    if (this._state === 'connected') return resolve()
    const off = this.on('_state', (s) => {
      if (s === 'connected') { off(); resolve() }
    })
  })
}
```

gateway 不可达时永挂；listener 永留。

### 实施步骤

1. 改签名：`waitForConnection(timeoutMs = 30000): Promise<void>`
2. 实现：
   ```ts
   waitForConnection(timeoutMs = 30000): Promise<void> {
     return new Promise((resolve, reject) => {
       if (this._state === 'connected') return resolve()
       let timer: ReturnType<typeof setTimeout> | null = null
       const off = this.on('_state', (s: string) => {
         if (s === 'connected') {
           if (timer) clearTimeout(timer)
           off()
           resolve()
         }
       })
       timer = setTimeout(() => {
         off()
         reject(new Error(`waitForConnection timed out after ${timeoutMs}ms`))
       }, timeoutMs)
     })
   }
   ```
3. 排查所有 `waitForConnection()` 调用点：
   - `useSessions.ts` `loadSessions`
   - `App.vue:548` `loadAgents`
   - `ChatView.vue` `subscribeSession` / `loadHistory` / `loadFeatureToggles`
   - `composables/useRpc.ts:54`
   - 各 view（OverviewView 等）
4. 调用方策略：
   - 业务调用保持 `await rpcStore.waitForConnection()` 不变（继承 30s 默认）
   - 加 try/catch 后将错误状态映射到现有 errorRef（`agentListError`、`sessionListError` 等已有），不要 throw 到 `onMounted` 顶层
5. `stores/rpc.ts` 把 `waitForConnection` 透传，签名同步

### 验收

- [ ] 关闭 gateway，刷新页面，30s 内 `agentListError`、`sessionListError` 等显示而非永远转圈
- [ ] gateway 可达时 reconnect/首连接行为不变（不会过早 timeout）
- [ ] 无未处理 promise rejection（DevTools console 检查）
- [ ] `npm run typecheck` 通过

### 不做

- 不改重连策略 / 退避算法
- 不在 `RpcClient.connect` 里加超时（属于另一层）
- 不改 ping keepalive 周期

---

## Task P0-5 — `useRpc` composable unsub 泄漏

**风险等级**：🟠（内存）
**文件**：`opensquilla-webui/src/composables/useRpc.ts`
**位置**：`L13`（`useRpcEvent`）、`L54`（`useRpcCall`）

### 现状

两个 composable 都对 `_state` 加 listener，但返回的 unsub 没存到能在 `onUnmounted` 调用的位置；RPC client 重连导致 `client.value` 替换时旧订阅孤儿化。

### 实施步骤

1. 读 `useRpc.ts` 全文，确认 `useRpcEvent(event, handler)` 与 `useRpcCall(method, params)` 签名
2. `useRpcEvent`：
   ```ts
   export function useRpcEvent<T>(event: string, handler: (data: T) => void) {
     const rpc = useRpcStore()
     let unsub: (() => void) | null = null
     onMounted(() => {
       unsub = rpc.on(event, handler)
     })
     onUnmounted(() => {
       unsub?.()
       unsub = null
     })
   }
   ```
3. `useRpcCall`：把内部的 `_state` listener 也存为 `unsub`，在 onUnmounted 与 connected 触发后都释放：
   ```ts
   let stateUnsub: (() => void) | null = null
   const execute = async () => { /* ... */ }
   onMounted(() => {
     if (rpc.state === 'connected') {
       execute()
     } else {
       stateUnsub = rpc.on('_state', (s: string) => {
         if (s === 'connected') {
           stateUnsub?.()
           stateUnsub = null
           execute()
         }
       })
     }
   })
   onUnmounted(() => {
     stateUnsub?.()
     stateUnsub = null
   })
   ```
4. 检查 `rpcStore.on` 是否在 client 重建后仍能正确转发（如果是直接挂在 client 上而非 store 自己的 emitter，需要先保证 store 层是 stable 的；如不稳定，作为本 task 第二步同时修补）
5. grep 项目内其它直接 `rpc.on('_state', ...)` 的写法，确认没有同类泄漏

### 验收

- [ ] 反复 mount/unmount 同一 view（路由切换 50 次）后 listener 数量不增长（DevTools Memory 或在 store 内加临时计数 console）
- [ ] RPC 断线重连后 useRpcCall 不会 double-fire `execute()`
- [ ] `npm run typecheck` 通过

### 不做

- 不重写 RpcClient 事件层
- 不强制 view 全部改用 `useRpcCall`/`useRpcEvent`（属于 P1-3 决策）

---

## 浏览器手测脚本（全部完成后跑一次）

```bash
cd opensquilla-webui && npm run build && cd ..
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18790/healthz \
  | grep -q 200 || (uv run opensquilla gateway run &)
sleep 3
open http://127.0.0.1:18790/control/
```

**逐项手测**

1. **P0-1**：在 chat 输入
   - `[x](javascript:alert(1))` → 渲染的 `<a>` 不应跳脚本
   - `<img src=x onerror=alert(1)>` → 不弹窗
   - 普通 markdown（**粗体**、`code`、列表、链接 https://example.com）渲染正常
2. **P0-2**：在 dark 主题下访问 `/overview`、`/sessions`、`/agents`、`/chat`，无白色矩形；切到 light 主题样式正常
3. **P0-3**：macOS 系统外观切换 dark↔light（`theme === 'system'` 时），UI 立即跟随；`themeIconName` 切换正确
4. **P0-4**：`kill <gateway-pid>` 后刷新，30s 内出现错误状态而非永久 loading；重启 gateway 后页面恢复
5. **P0-5**：DevTools → Memory → Heap snapshot 在路由切换 20 次前后比对，listener 计数无显著增长

---

## 提交策略

5 个 task 互相独立，可一次性提交也可拆 5 个 commit：

```
fix(webui): tighten DOMPurify allowlist (P0-1)
fix(webui): replace hardcoded #fff backgrounds with theme tokens (P0-2)
fix(webui): make resolvedTheme reactive and clean up matchMedia listener (P0-3)
feat(webui): add timeout to RpcClient.waitForConnection (P0-4)
fix(webui): release _state listeners in useRpc composables (P0-5)
```

PR 描述引用 `spec/frontend-review-2026-06-03.md` §1 与本文件。

---

## 完成定义（DoD）

- [ ] 5 个 task 验收清单全部勾选
- [ ] `npm run typecheck` + `npm run build` 通过
- [ ] `uv run pytest tests -q` 通过（gateway 静态资源测试）
- [ ] 手测脚本 1–5 通过
- [ ] `git diff --stat` 影响范围只在 `opensquilla-webui/src/views/ChatView.vue` / `opensquilla-webui/src/assets/base.css` / `opensquilla-webui/src/stores/app.ts` / `opensquilla-webui/src/lib/rpc.ts` / `opensquilla-webui/src/composables/useRpc.ts`（必要时含 `opensquilla-webui/src/stores/rpc.ts` 的签名透传）
