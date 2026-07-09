// Pure OS-language → bundled-locale resolution, split out of main.ts so it can
// be unit-tested without pulling in Electron (same pattern as
// update-feed-resolver.ts). main.ts feeds it
// [...app.getPreferredSystemLanguages(), app.getLocale()] in preference order.

export type DesktopLocale = 'en' | 'zh-Hans' | 'ja' | 'fr' | 'de' | 'es'

export const DESKTOP_LOCALES: DesktopLocale[] = ['en', 'zh-Hans', 'ja', 'fr', 'de', 'es']

/**
 * Map the user's ordered BCP-47 language tags to the first bundled locale.
 * First match wins, so a top-preference tag can never lose to a
 * lower-preference one (e.g. en-HK above fr-HK must yield 'en', not 'fr').
 */
export function resolveLocaleFromTags(tags: readonly unknown[]): DesktopLocale {
  for (const raw of tags) {
    if (typeof raw !== 'string') continue
    const t = raw.toLowerCase()
    // English is a bundled locale and must match here: without this branch a
    // top-preference en-* tag falls through and a LOWER-preference language
    // (e.g. fr-HK behind en-HK on a Hong Kong system) wins the loop.
    if (t === 'en' || t.startsWith('en-') || t.startsWith('en_')) return 'en'
    if (t.startsWith('zh')) {
      // Only Simplified Chinese is bundled. An explicit script subtag wins
      // over region: zh-Hans-HK/TW/MO is Simplified wherever the reader
      // lives. Only then route Traditional variants — explicit zh-Hant, or
      // bare region tags that default to Traditional (zh-TW / zh-HK /
      // zh-MO) — to the English fallback rather than forcing Simplified
      // text a Traditional reader may not want.
      if (t.includes('hans')) return 'zh-Hans'
      if (t.includes('hant') || /-(tw|hk|mo)\b/.test(t)) continue
      return 'zh-Hans'
    }
    for (const code of ['ja', 'fr', 'de', 'es'] as const) {
      if (t === code || t.startsWith(code + '-')) return code
    }
  }
  return 'en'
}
