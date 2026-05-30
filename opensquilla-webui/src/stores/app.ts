import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

export const useAppStore = defineStore('app', () => {
  const theme = ref<ThemeMode>('system')
  const sidebarOpen = ref(false)
  const approvalCount = ref(0)

  const resolvedTheme = computed<'light' | 'dark'>(() => {
    if (theme.value !== 'system') return theme.value
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  function initTheme() {
    try {
      const saved = localStorage.getItem('opensquilla-theme') as ThemeMode | null
      if (saved && ['light', 'dark', 'system'].includes(saved)) {
        theme.value = saved
      }
    } catch {
      // ignore
    }
    applyTheme()

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (theme.value === 'system') applyTheme()
    }
    if (mq.addEventListener) mq.addEventListener('change', handler)
    else if ((mq as any).addListener) (mq as any).addListener(handler)
  }

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', resolvedTheme.value)
  }

  function setTheme(mode: ThemeMode) {
    theme.value = mode
    try { localStorage.setItem('opensquilla-theme', mode) } catch {}
    applyTheme()
  }

  function cycleTheme() {
    const order: ThemeMode[] = ['light', 'dark', 'system']
    const next = order[(order.indexOf(theme.value) + 1) % order.length]
    setTheme(next)
  }

  function setSidebarOpen(open: boolean) {
    sidebarOpen.value = open
  }

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
  }

  function setApprovalCount(count: number) {
    approvalCount.value = count
  }

  const features = ref<Record<string, boolean>>({
    tokenViz: false,
    ...((window as any).OPENSQUILLA_FEATURES || {}),
  })

  return {
    theme,
    resolvedTheme,
    sidebarOpen,
    approvalCount,
    features,
    initTheme,
    setTheme,
    cycleTheme,
    setSidebarOpen,
    toggleSidebar,
    setApprovalCount,
  }
})
