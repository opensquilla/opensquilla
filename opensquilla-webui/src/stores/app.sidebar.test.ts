// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from './app'
import {
  SIDEBAR_WIDTH_PRESETS,
  SIDEBAR_WIDTH_STORAGE_KEY,
} from '@/utils/sidebarLayout'

function stubMatchMedia() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

describe('app store — sidebar width preference', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    stubMatchMedia()
  })

  it('hydrates the default synchronously when storage is absent', () => {
    const store = useAppStore()
    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.default)
  })

  it('hydrates and normalizes the versioned storage payload', () => {
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, JSON.stringify({
      version: 1,
      width: 350,
      source: 'custom',
    }))

    const store = useAppStore()
    expect(store.sidebarWidthPreference).toEqual({ version: 1, width: 350, source: 'custom' })
  })

  it('persists a normalized complete preference', () => {
    const store = useAppStore()
    store.setSidebarWidthPreference({ version: 1, width: 333, source: 'compact' })

    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.compact)
    expect(JSON.parse(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)!)).toEqual(
      SIDEBAR_WIDTH_PRESETS.compact,
    )

    setActivePinia(createPinia())
    expect(useAppStore().sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.compact)
  })

  it('resets in memory and removes the persisted override', () => {
    const store = useAppStore()
    store.setSidebarWidthPreference({ version: 1, width: 380, source: 'custom' })
    store.resetSidebarWidthPreference()

    expect(store.sidebarWidthPreference).toEqual(SIDEBAR_WIDTH_PRESETS.default)
    expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBeNull()
  })
})
