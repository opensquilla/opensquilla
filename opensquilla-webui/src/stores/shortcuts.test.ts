import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useShortcutsStore } from './shortcuts'

// The store reads/writes localStorage, which the `node` test env lacks. Back it
// with an in-memory Map so hydrate/persist exercise the real code paths.
class MemoryStorage {
  private map = new Map<string, string>()
  getItem(k: string): string | null {
    return this.map.has(k) ? this.map.get(k)! : null
  }
  setItem(k: string, v: string): void {
    this.map.set(k, v)
  }
  removeItem(k: string): void {
    this.map.delete(k)
  }
  clear(): void {
    this.map.clear()
  }
}

function installStorage(seed?: Record<string, unknown>) {
  const store = new MemoryStorage()
  if (seed) store.setItem('opensquilla.shortcuts', JSON.stringify(seed))
  ;(globalThis as unknown as { localStorage: unknown }).localStorage = store
  return store
}

afterEach(() => {
  delete (globalThis as unknown as { localStorage?: unknown }).localStorage
})

describe('useShortcutsStore defaults', () => {
  beforeEach(() => {
    installStorage()
    setActivePinia(createPinia())
  })

  it('seeds the command palette enabled and new-chat disabled', () => {
    const s = useShortcutsStore()
    expect(s.states['command-palette'].enabled).toBe(true)
    expect(s.states['new-chat'].enabled).toBe(false)
    expect(s.effectiveBinding('command-palette')).toEqual({ primary: true, key: 'k' })
    // Disabled → no effective binding even though a default chord is stored.
    expect(s.effectiveBinding('new-chat')).toBeNull()
    expect(s.states['new-chat'].binding).toEqual({ primary: true, shift: true, key: 'k' })
  })
})

describe('useShortcutsStore hydration + mutation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('hydrates a saved override over the defaults', () => {
    installStorage({ 'new-chat': { enabled: true, binding: { primary: true, shift: true, key: 'n' } } })
    setActivePinia(createPinia())
    const s = useShortcutsStore()
    expect(s.effectiveBinding('new-chat')).toEqual({ primary: true, shift: true, key: 'n' })
    // Unspecified shortcut keeps its default.
    expect(s.states['command-palette'].enabled).toBe(true)
  })

  it('setEnabled flips the effective binding and persists', () => {
    const ls = installStorage()
    setActivePinia(createPinia())
    const s = useShortcutsStore()
    s.setEnabled('new-chat', true)
    expect(s.effectiveBinding('new-chat')).toEqual({ primary: true, shift: true, key: 'k' })
    expect(JSON.parse(ls.getItem('opensquilla.shortcuts')!)['new-chat'].enabled).toBe(true)
  })

  it('setBinding then resetBinding restores the default chord', () => {
    installStorage()
    setActivePinia(createPinia())
    const s = useShortcutsStore()
    s.setBinding('command-palette', { primary: true, shift: true, key: 'p' })
    expect(s.effectiveBinding('command-palette')).toEqual({ primary: true, shift: true, key: 'p' })
    s.resetBinding('command-palette')
    expect(s.effectiveBinding('command-palette')).toEqual({ primary: true, key: 'k' })
  })

  it('findConflict reports a chord already taken by another enabled shortcut', () => {
    installStorage()
    setActivePinia(createPinia())
    const s = useShortcutsStore()
    // The palette owns Ctrl/⌘+K; binding new-chat to the same chord conflicts.
    expect(s.findConflict({ primary: true, key: 'k' }, 'new-chat')).toBe('command-palette')
    // A free chord has no conflict.
    expect(s.findConflict({ primary: true, alt: true, key: 'k' }, 'new-chat')).toBeNull()
  })
})
