import assert from 'node:assert/strict'

import { resolveLocaleFromTags } from '../dist/desktop-locale.js'

// --- preference order: first bundled match wins ---

// Regression: en-* is bundled and must match in place. Before the fix a Hong
// Kong system list [en-HK, zh-Hans-HK, zh-Hant-HK, fr-HK] resolved to 'fr' —
// the top two preferences both fell through and the fourth won.
assert.equal(resolveLocaleFromTags(['en-HK', 'zh-Hans-HK', 'zh-Hant-HK', 'fr-HK']), 'en')
assert.equal(resolveLocaleFromTags(['en', 'ja']), 'en')
assert.equal(resolveLocaleFromTags(['en_US']), 'en')
assert.equal(resolveLocaleFromTags(['ja-JP', 'en-US']), 'ja')

// --- Chinese: explicit script subtag wins over region ---

// Regression: zh-Hans with a Traditional-default region is still Simplified.
assert.equal(resolveLocaleFromTags(['zh-Hans-HK']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh-Hans-TW']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh-Hans-MO']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh-CN']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh-Hans-CN']), 'zh-Hans')
assert.equal(resolveLocaleFromTags(['zh_Hans_HK']), 'zh-Hans')

// Traditional variants (explicit Hant, or bare Traditional-default regions)
// resolve to zh-Hant — both Simplified and Traditional are bundled, so
// neither needs to fall through to a lower-preference tag or to English.
assert.equal(resolveLocaleFromTags(['zh-Hant']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-Hant-HK', 'ja-JP']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-TW']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-tw']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-HK', 'fr-FR']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-MO', 'de']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh_HK', 'fr-FR']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh_TW']), 'zh-Hant')
// A lower-preference zh-Hant is still reached once earlier tags are skipped.
assert.equal(resolveLocaleFromTags(['ko-KR', 'zh-TW']), 'zh-Hant')
// A top-preference Simplified tag still wins over a lower-preference
// Traditional one — first bundled match wins regardless of script.
assert.equal(resolveLocaleFromTags(['zh-CN', 'zh-TW']), 'zh-Hans')

// Script detection is structural, never a substring match against extensions
// or private-use subtags.
assert.equal(resolveLocaleFromTags(['zh-Hant-x-hans', 'ja-JP']), 'zh-Hant')
assert.equal(resolveLocaleFromTags(['zh-CN-x-hant', 'fr-FR']), 'zh-Hans')

// --- other bundled languages and fallback ---

assert.equal(resolveLocaleFromTags(['fr-CA']), 'fr')
assert.equal(resolveLocaleFromTags(['fr_CA']), 'fr')
assert.equal(resolveLocaleFromTags(['de-AT']), 'de')
assert.equal(resolveLocaleFromTags(['es-419']), 'es')
// Unsupported languages skip to the next preference; nothing matches → 'en'.
assert.equal(resolveLocaleFromTags(['ko-KR', 'es-ES']), 'es')
assert.equal(resolveLocaleFromTags(['ko-KR', 'th-TH']), 'en')
assert.equal(resolveLocaleFromTags([]), 'en')
// Malformed entries (Electron APIs can surface non-strings) are skipped.
assert.equal(resolveLocaleFromTags([undefined, null, 42, 'ja']), 'ja')
assert.equal(resolveLocaleFromTags(['en--US', 'ja']), 'ja')
assert.equal(resolveLocaleFromTags(['zh-Hans-Hant', 'fr']), 'fr')
assert.equal(resolveLocaleFromTags(['zha', 'ja']), 'ja')
assert.equal(resolveLocaleFromTags(['zh!', 'de']), 'de')

console.log('desktop-locale resolution tests passed')
