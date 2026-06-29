import { createI18n } from 'vue-i18n'
import en from '@/locales/en.json'

// Single i18n instance for the whole app. Composition mode (legacy:false) so
// `i18n.global.locale` is a writable ref and `t()` is reactive — calling it
// inside a computed (e.g. the nav builders) re-runs that computed on locale
// change. English is bundled eagerly as the fallback so the first paint is
// never untranslated and any missing key degrades to English; every other
// locale is a lazy dynamic-import chunk loaded on demand by loadLocaleMessages.

export const SUPPORTED_LOCALES = ['en', 'zh-Hans', 'ja', 'fr', 'de', 'es'] as const
export type LocaleCode = (typeof SUPPORTED_LOCALES)[number]
// Literal 'en' (not widened to LocaleCode) so Exclude<LocaleCode, …> below
// resolves to the non-en locales rather than never.
export const DEFAULT_LOCALE = 'en' satisfies LocaleCode

type MessageSchema = typeof en

const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  // Cast so vue-i18n infers the full locale union (en is the only EAGER bundle;
  // zh-Hans is registered later via setLocaleMessage). Without this it would
  // type the locale as just 'en' and reject setting it to 'zh-Hans'.
  messages: { en } as Record<LocaleCode, MessageSchema>,
})

export default i18n

// Non-setup modules (stores, the router guard, nav builders) import this `t`
// instead of useI18n(), which only works inside component setup.
export const t = i18n.global.t

// Static import map — one discrete chunk per non-en locale. A fully dynamic
// `import('@/locales/' + code)` would emit a broad glob and risk bundling en
// into the lazy chunk, so each locale gets an explicit specifier.
const loaders: Record<Exclude<LocaleCode, typeof DEFAULT_LOCALE>, () => Promise<{ default: MessageSchema }>> = {
  'zh-Hans': () => import('@/locales/zh-Hans.json'),
  ja: () => import('@/locales/ja.json'),
  fr: () => import('@/locales/fr.json'),
  de: () => import('@/locales/de.json'),
  es: () => import('@/locales/es.json'),
}

const loaded = new Set<LocaleCode>([DEFAULT_LOCALE])

export function isSupportedLocale(value: unknown): value is LocaleCode {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

/** Map an arbitrary BCP-47 tag to a supported locale, or null if unsupported. */
export function normalizeLocale(raw: string | null | undefined): LocaleCode | null {
  if (!raw) return null
  const lower = raw.toLowerCase()
  if (lower === 'en' || lower.startsWith('en-') || lower.startsWith('en_')) return 'en'
  if (lower.startsWith('zh')) return 'zh-Hans'
  if (lower.startsWith('ja')) return 'ja'
  if (lower.startsWith('fr')) return 'fr'
  if (lower.startsWith('de')) return 'de'
  if (lower.startsWith('es')) return 'es'
  return null
}

/** Load and register a locale's messages (idempotent). en is always present. */
export async function loadLocaleMessages(code: LocaleCode): Promise<void> {
  if (loaded.has(code)) return
  const loader = loaders[code as Exclude<LocaleCode, typeof DEFAULT_LOCALE>]
  if (!loader) return
  const mod = await loader()
  i18n.global.setLocaleMessage(code, mod.default)
  loaded.add(code)
}

/**
 * Resolve the initial locale, first match wins:
 *   1. saved preference (localStorage)
 *   2. host OS locale (Platform.getOsLocale, desktop) — passed in by the store
 *   3. server/desktop-injected #opensquilla-data data-locale
 *   4. <html lang> (set by the gateway template / pre-paint guard)
 *   5. navigator.languages
 *   6. DEFAULT_LOCALE
 * The OS locale precedes data-locale because the desktop gateway injects a
 * default-`en` data-locale; the actual OS preference must win over it.
 */
export function resolveInitialLocale(osLocale?: string | null): LocaleCode {
  try {
    const saved = localStorage.getItem('opensquilla-locale')
    if (isSupportedLocale(saved)) return saved
  } catch {
    // localStorage unavailable (private mode) — fall through
  }

  const os = normalizeLocale(osLocale)
  if (os) return os

  try {
    const data = document.getElementById('opensquilla-data')?.dataset.locale
    if (isSupportedLocale(data)) return data
  } catch {
    // ignore
  }

  const htmlLang = normalizeLocale(document.documentElement.lang)
  if (htmlLang) return htmlLang

  const navs = navigator.languages && navigator.languages.length
    ? navigator.languages
    : [navigator.language]
  for (const tag of navs) {
    const norm = normalizeLocale(tag)
    if (norm) return norm
  }

  return DEFAULT_LOCALE
}
