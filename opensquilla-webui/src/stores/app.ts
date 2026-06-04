import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

type FeatureWindow = Window & {
  OPENSQUILLA_FEATURES?: Record<string, boolean>
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<ThemeMode>('system')
  const sidebarOpen = ref(true)
  const sidebarHovered = ref(false)
  const approvalCount = ref(0)

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
    approvalCount.value = count
  }

  const features = ref<Record<string, boolean>>({
    tokenViz: false,
    ...((window as FeatureWindow).OPENSQUILLA_FEATURES || {}),
  })

  return {
    theme,
    resolvedTheme,
    sidebarOpen,
    sidebarHovered,
    approvalCount,
    features,
    initTheme,
    destroyTheme,
    setTheme,
    cycleTheme,
    setSidebarOpen,
    toggleSidebar,
    setSidebarHovered,
    setApprovalCount,
  }
})
