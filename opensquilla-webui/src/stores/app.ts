import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

type FeatureWindow = Window & {
  OPENSQUILLA_FEATURES?: Record<string, boolean>
}

/** One pending approval, ordered oldest-first (closest to timeout). */
export interface PendingApproval {
  approvalId: string
  sessionKey: string
  tool: string
  command: string
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<ThemeMode>('system')
  const sidebarOpen = ref(true)
  const sidebarHovered = ref(false)
  // App-wide pending approvals, kept live by the gateway push events and a
  // reconnect seed fetch (App.vue). Ordered oldest-first. `approvalCount` is
  // derived from this list once it becomes the source, but `setApprovalCount`
  // still works for the Approvals page snapshot (back-compat).
  const pendingApprovals = ref<PendingApproval[]>([])
  const approvalCountRaw = ref(0)

  // True once App.vue has wired the live approval source (push events + seed
  // fetch). While live, `approvalCount` is derived from `pendingApprovals`;
  // before then it falls back to whatever `setApprovalCount` last wrote so the
  // Approvals page keeps working in isolation.
  const approvalsLive = ref(false)

  const approvalCount = computed(() =>
    approvalsLive.value ? pendingApprovals.value.length : approvalCountRaw.value)

  // The oldest pending approval with a routable session (closest to timeout).
  const oldestPendingWithSession = computed<PendingApproval | null>(() =>
    pendingApprovals.value.find(item => !!item.sessionKey) ?? null)

  const systemDark = ref<boolean>(
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )

  const resolvedTheme = computed<'light' | 'dark'>(() => {
    if (theme.value !== 'system') return theme.value
    return systemDark.value ? 'dark' : 'light'
  })

  let mq: MediaQueryList | null = null
  let mqHandler: ((e: MediaQueryListEvent) => void) | null = null
  let themeWatchStop: (() => void) | null = null

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', resolvedTheme.value)
  }

  function initTheme() {
    try {
      const saved = localStorage.getItem('opensquilla-theme') as ThemeMode | null
      if (saved && ['light', 'dark', 'system'].includes(saved)) {
        theme.value = saved
      }
    } catch {
      // ignore
    }

    if (!themeWatchStop) {
      themeWatchStop = watch(resolvedTheme, applyTheme, { immediate: true })
    } else {
      applyTheme()
    }

    if (mq) return // idempotent
    mq = window.matchMedia('(prefers-color-scheme: dark)')
    mqHandler = (e: MediaQueryListEvent) => {
      systemDark.value = e.matches
    }
    if (mq.addEventListener) mq.addEventListener('change', mqHandler)
    else if (mq.addListener) mq.addListener(mqHandler)
  }

  function destroyTheme() {
    if (mq && mqHandler) {
      if (mq.removeEventListener) mq.removeEventListener('change', mqHandler)
      else if (mq.removeListener) mq.removeListener(mqHandler)
    }
    mq = null
    mqHandler = null
    if (themeWatchStop) {
      themeWatchStop()
      themeWatchStop = null
    }
  }

  function setTheme(mode: ThemeMode) {
    theme.value = mode
    try { localStorage.setItem('opensquilla-theme', mode) } catch {}
  }

  function cycleTheme() {
    const order: ThemeMode[] = ['light', 'dark', 'system']
    const next = order[(order.indexOf(theme.value) + 1) % order.length]
    setTheme(next)
  }

  function setSidebarOpen(open: boolean) {
    sidebarOpen.value = open
    if (!open) sidebarHovered.value = false
  }

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
    sidebarHovered.value = false
  }

  function setSidebarHovered(hovered: boolean) {
    sidebarHovered.value = hovered
  }

  function setApprovalCount(count: number) {
    approvalCountRaw.value = count
  }

  // Replace the app-wide pending list and mark it the live source so
  // `approvalCount` derives from it. Called on the reconnect seed fetch.
  function setPendingApprovals(items: PendingApproval[]) {
    approvalsLive.value = true
    pendingApprovals.value = items
  }

  // `*.approval.requested` push: add or update by approvalId, preserving the
  // oldest-first order (new ids append to the tail).
  function upsertPendingApproval(item: PendingApproval) {
    approvalsLive.value = true
    const idx = pendingApprovals.value.findIndex(a => a.approvalId === item.approvalId)
    if (idx === -1) {
      pendingApprovals.value = [...pendingApprovals.value, item]
    } else {
      const next = pendingApprovals.value.slice()
      next[idx] = item
      pendingApprovals.value = next
    }
  }

  // `*.approval.resolved` push: drop by approvalId.
  function removePendingApproval(approvalId: string) {
    approvalsLive.value = true
    pendingApprovals.value = pendingApprovals.value.filter(a => a.approvalId !== approvalId)
  }

  const features = ref<Record<string, boolean>>({
    tokenViz: false,
    contractDebug: false,
    // MetaSkill run-history drawer + toolbar button: on by default so the run
    // history is reachable out of the box. Operators can disable it via
    // window.OPENSQUILLA_FEATURES. The preflight + ribbon cards are always-on
    // (driven by stream events) regardless of this flag.
    metaRuns: true,
    ...((window as FeatureWindow).OPENSQUILLA_FEATURES || {}),
  })

  return {
    theme,
    resolvedTheme,
    sidebarOpen,
    sidebarHovered,
    approvalCount,
    pendingApprovals,
    oldestPendingWithSession,
    features,
    initTheme,
    destroyTheme,
    setTheme,
    cycleTheme,
    setSidebarOpen,
    toggleSidebar,
    setSidebarHovered,
    setApprovalCount,
    setPendingApprovals,
    upsertPendingApproval,
    removePendingApproval,
  }
})
