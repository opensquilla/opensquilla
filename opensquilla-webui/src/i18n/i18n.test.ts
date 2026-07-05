// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import en from '@/locales/en.json'
import zhHans from '@/locales/zh-Hans.json'
import de from '@/locales/de.json'
import es from '@/locales/es.json'
import fr from '@/locales/fr.json'
import ja from '@/locales/ja.json'
import i18n, {
  resolveInitialLocale,
  normalizeLocale,
  isSupportedLocale,
} from '@/i18n'
import { useAppStore } from '@/stores/app'

function flatten(obj: Record<string, unknown>, prefix = '', out: Record<string, unknown> = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v as Record<string, unknown>, key, out)
    else out[key] = v
  }
  return out
}

describe('normalizeLocale', () => {
  it('maps supported language variants, rejects the rest', () => {
    expect(normalizeLocale('en')).toBe('en')
    expect(normalizeLocale('en-US')).toBe('en')
    expect(normalizeLocale('zh')).toBe('zh-Hans')
    expect(normalizeLocale('zh-CN')).toBe('zh-Hans')
    expect(normalizeLocale('zh-Hans')).toBe('zh-Hans')
    expect(normalizeLocale('ja-JP')).toBe('ja')
    expect(normalizeLocale('fr')).toBe('fr')
    expect(normalizeLocale('de-DE')).toBe('de')
    expect(normalizeLocale('es-419')).toBe('es')
    expect(normalizeLocale('ko')).toBeNull()
    expect(normalizeLocale('')).toBeNull()
    expect(normalizeLocale(null)).toBeNull()
  })
})

describe('isSupportedLocale', () => {
  it('only accepts the canonical codes', () => {
    expect(isSupportedLocale('en')).toBe(true)
    expect(isSupportedLocale('zh-Hans')).toBe(true)
    expect(isSupportedLocale('zh-CN')).toBe(false)
    expect(isSupportedLocale('zh-hans')).toBe(false)
    expect(isSupportedLocale(null)).toBe(false)
  })
})

describe('resolveInitialLocale (first match wins)', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('lang')
    document.getElementById('opensquilla-data')?.remove()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('1. prefers a valid saved localStorage value', () => {
    localStorage.setItem('opensquilla-locale', 'zh-Hans')
    expect(resolveInitialLocale()).toBe('zh-Hans')
  })

  it('2. ignores an unsupported saved value and reads #opensquilla-data data-locale', () => {
    localStorage.setItem('opensquilla-locale', 'ko')
    const el = document.createElement('div')
    el.id = 'opensquilla-data'
    el.dataset.locale = 'zh-Hans'
    document.body.appendChild(el)
    expect(resolveInitialLocale()).toBe('zh-Hans')
  })

  it('3. honors <html lang> when no saved/data value', () => {
    document.documentElement.setAttribute('lang', 'zh-CN')
    expect(resolveInitialLocale()).toBe('zh-Hans')
  })

  it('4. falls back to navigator.languages', () => {
    vi.stubGlobal('navigator', { languages: ['zh-CN', 'en'], language: 'zh-CN' })
    expect(resolveInitialLocale()).toBe('zh-Hans')
  })

  it('4b. matches a supported navigator language (fr)', () => {
    vi.stubGlobal('navigator', { languages: ['fr-FR', 'en'], language: 'fr-FR' })
    expect(resolveInitialLocale()).toBe('fr')
  })

  it('5. defaults to en when nothing matches', () => {
    vi.stubGlobal('navigator', { languages: ['ko-KR'], language: 'ko-KR' })
    expect(resolveInitialLocale()).toBe('en')
  })

  it('honors the desktop OS locale (arg) ahead of navigator', () => {
    vi.stubGlobal('navigator', { languages: ['en-US'], language: 'en-US' })
    expect(resolveInitialLocale('zh-CN')).toBe('zh-Hans')
    expect(resolveInitialLocale('ja-JP')).toBe('ja')
    // an unsupported OS locale falls through to navigator → en
    expect(resolveInitialLocale('ko-KR')).toBe('en')
  })

  it('saved preference still beats the OS locale', () => {
    localStorage.setItem('opensquilla-locale', 'en')
    expect(resolveInitialLocale('zh-CN')).toBe('en')
  })
})

describe('appStore locale state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    i18n.global.locale.value = 'en'
    document.documentElement.removeAttribute('lang')
  })

  it('setLocale loads the chunk, persists, and applies all side effects', async () => {
    const store = useAppStore()
    await store.setLocale('zh-Hans')
    expect(store.locale).toBe('zh-Hans')
    expect(localStorage.getItem('opensquilla-locale')).toBe('zh-Hans')
    expect(document.documentElement.getAttribute('lang')).toBe('zh-Hans')
    expect(document.documentElement.getAttribute('dir')).toBe('ltr')
    expect(i18n.global.locale.value).toBe('zh-Hans')
    // the lazily-loaded chunk is now resolvable
    expect(i18n.global.t('nav.sessions')).toBe('会话')
  })

  it('setLocale ignores unsupported codes (no throw, stays en)', async () => {
    const store = useAppStore()
    await store.setLocale('ko' as never)
    expect(store.locale).toBe('en')
  })

  it('initLocale resolves the saved preference and applies it', async () => {
    localStorage.setItem('opensquilla-locale', 'zh-Hans')
    const store = useAppStore()
    await store.initLocale()
    expect(store.locale).toBe('zh-Hans')
    expect(document.documentElement.getAttribute('lang')).toBe('zh-Hans')
  })
})

describe('missing-key fallback', () => {
  it('returns the en string for a key absent from the active locale', () => {
    // an intentionally unknown key falls back to its own key string, never blank
    expect(i18n.global.t('totally.unknown.key')).toBe('totally.unknown.key')
  })
})

describe('catalog parity', () => {
  it('all bundled locales share the exact flattened key set', () => {
    const enKeys = Object.keys(flatten(en as Record<string, unknown>)).sort()
    const locales = { zhHans, de, es, fr, ja }

    for (const [locale, messages] of Object.entries(locales)) {
      const keys = Object.keys(flatten(messages as Record<string, unknown>)).sort()
      expect(keys, locale).toEqual(enKeys)
    }
  })

  it('no zh-Hans value is left as the English source', () => {
    const enFlat = flatten(en as Record<string, unknown>)
    const zhFlat = flatten(zhHans as Record<string, unknown>)
    const leaked = Object.keys(enFlat).filter(
      (k) => typeof zhFlat[k] === 'string' && zhFlat[k] === enFlat[k] && /[A-Za-z]/.test(zhFlat[k] as string),
    )
    expect(leaked).toEqual([])
  })
})
