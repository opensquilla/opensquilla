// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from './app'

const THEME_KEY = 'opensquilla-theme'

function stubMatchMedia(matches = false) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

describe('app store — theme persistence + legacy id migration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    // Default OS preference to light so an unmigrated fallback would resolve to
    // 'light' (distinct from the renamed dark themes under test).
    stubMatchMedia(false)
  })

  it('migrates a persisted legacy id ("nord") to its renamed theme ("arctic")', () => {
    localStorage.setItem(THEME_KEY, 'nord')
    const store = useAppStore()
    store.initTheme()
    // Resolves to the renamed id — it does NOT fall back to system/default.
    expect(store.theme).toBe('arctic')
    expect(store.resolvedTheme).toBe('arctic')
    // The canonical id is written back, so the migration happens once and the
    // pre-paint anti-flash script stamps the right theme next cold load.
    expect(localStorage.getItem(THEME_KEY)).toBe('arctic')
    store.destroyTheme()
  })

  it('migrates a persisted legacy "phosphor" to "crt-green"', () => {
    localStorage.setItem(THEME_KEY, 'phosphor')
    const store = useAppStore()
    store.initTheme()
    expect(store.theme).toBe('crt-green')
    expect(localStorage.getItem(THEME_KEY)).toBe('crt-green')
    store.destroyTheme()
  })

  it('keeps a current custom theme id as-is', () => {
    localStorage.setItem(THEME_KEY, 'vapor')
    const store = useAppStore()
    store.initTheme()
    expect(store.theme).toBe('vapor')
    expect(localStorage.getItem(THEME_KEY)).toBe('vapor')
    store.destroyTheme()
  })

  it('drops a genuinely unknown persisted id and falls back to system', () => {
    localStorage.setItem(THEME_KEY, 'ferrari-red')
    const store = useAppStore()
    store.initTheme()
    expect(store.theme).toBe('system')
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
    store.destroyTheme()
  })
})
