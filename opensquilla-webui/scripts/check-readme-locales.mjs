// README locale-parity guard — the docs analog of check-i18n.mjs.
//
// check-i18n.mjs keeps the webui translation CATALOGS in lockstep with the
// language list. This keeps the root README translations in lockstep with the
// SAME list, so the README's language coverage can never silently drift from
// the app's.
//
// The canonical language list (SUPPORTED_LOCALES) and the human endonyms
// (LOCALE_LABELS) are read from the real webui source — never duplicated here —
// so adding/removing a webui locale immediately changes what this check
// requires. For each locale it fails on:
//   - a missing README file (README.md for the default locale, README.<code>.md otherwise)
//   - a stale/extra translated README whose locale is not supported
//   - a wrong/missing language-switcher entry in any README (link, href, endonym, or active marker)
//   - a missing localized link in the docs/README.md footer
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const webuiSrc = resolve(here, '..', 'src')
const repoRoot = resolve(here, '..', '..')

// README.<x>.md files that are content variants, NOT language translations.
const NON_LOCALE_README = new Set(['product', 'release'])

const failures = []
const fail = (msg) => failures.push(msg)

// --- read canonical list + labels from the webui source (single source of truth) ---
function readSupportedLocales() {
  const src = readFileSync(resolve(webuiSrc, 'i18n', 'index.ts'), 'utf8')
  const m = src.match(/SUPPORTED_LOCALES\s*=\s*\[([^\]]+)\]\s*as const/)
  if (!m) throw new Error('could not parse SUPPORTED_LOCALES from src/i18n/index.ts')
  const codes = [...m[1].matchAll(/['"]([^'"]+)['"]/g)].map((x) => x[1])
  if (codes.length === 0) throw new Error('SUPPORTED_LOCALES parsed empty')
  const dm = src.match(/DEFAULT_LOCALE\s*=\s*'([^']+)'/)
  return { codes, defaultLocale: dm ? dm[1] : 'en' }
}

function readLocaleLabels() {
  const src = readFileSync(resolve(webuiSrc, 'components', 'LanguageSwitcher.vue'), 'utf8')
  const m = src.match(/LOCALE_LABELS[^{]*\{([\s\S]*?)\}/)
  if (!m) throw new Error('could not parse LOCALE_LABELS from src/components/LanguageSwitcher.vue')
  const labels = {}
  for (const mm of m[1].matchAll(/(?:'([^']+)'|"([^"]+)"|([A-Za-z][\w-]*))\s*:\s*(?:'([^']+)'|"([^"]+)")/g)) {
    labels[mm[1] ?? mm[2] ?? mm[3]] = mm[4] ?? mm[5]
  }
  if (Object.keys(labels).length === 0) throw new Error('LOCALE_LABELS parsed empty')
  return labels
}

const { codes, defaultLocale } = readSupportedLocales()
const labels = readLocaleLabels()

for (const code of codes) {
  if (!(code in labels)) fail(`LOCALE_LABELS is missing an endonym for "${code}"`)
}

const readmeFor = (code) => (code === defaultLocale ? 'README.md' : `README.${code}.md`)

// --- 1. every supported locale has a README file ---
for (const code of codes) {
  const file = readmeFor(code)
  if (!existsSync(resolve(repoRoot, file))) fail(`missing ${file} for locale "${code}"`)
}

// --- 2. no stale/extra translated README ---
for (const f of readdirSync(repoRoot).filter((f) => /^README\.[\w-]+\.md$/.test(f))) {
  const tag = f.slice('README.'.length, -'.md'.length)
  if (NON_LOCALE_README.has(tag)) continue
  if (!codes.includes(tag)) fail(`stale/extra translated README: ${f} (locale "${tag}" not in SUPPORTED_LOCALES)`)
}

// --- 3. switcher parity in every root README ---
function parseTokens(block) {
  const tokens = []
  const re = /<b>([^<]+)<\/b>|<a href="([^"]+)">([^<]+)<\/a>/g
  let mm
  while ((mm = re.exec(block))) {
    if (mm[1] !== undefined) tokens.push({ active: true, label: mm[1].trim() })
    else tokens.push({ active: false, href: mm[2].trim(), label: mm[3].trim() })
  }
  return tokens
}

function switcherTokens(text) {
  // The switcher is the centered block linking READMEs with the MOST language
  // tokens — picking by max tokens avoids being fooled by a decoy centered
  // block that happens to contain a single README link elsewhere in the doc.
  const candidates = [...text.matchAll(/<p align="center">([\s\S]*?)<\/p>/g)]
    .map((m) => m[1])
    .filter((b) => /href="README(?:\.[\w-]+)?\.md"/.test(b))
  if (!candidates.length) return null
  return candidates.map(parseTokens).reduce((best, t) => (t.length > best.length ? t : best), [])
}

for (const activeCode of codes) {
  const file = readmeFor(activeCode)
  const path = resolve(repoRoot, file)
  if (!existsSync(path)) continue // already reported as missing
  const tokens = switcherTokens(readFileSync(path, 'utf8'))
  if (!tokens) {
    fail(`${file}: no language-switcher block found`)
    continue
  }
  const expected = codes.map((code) =>
    code === activeCode
      ? { active: true, label: labels[code] }
      : { active: false, href: readmeFor(code), label: labels[code] },
  )
  if (tokens.length !== expected.length) {
    fail(`${file}: switcher has ${tokens.length} entries, expected ${expected.length} (${codes.join(', ')})`)
    continue
  }
  expected.forEach((exp, i) => {
    const got = tokens[i]
    if (got.label !== exp.label)
      fail(`${file}: switcher position ${i + 1} endonym "${got.label}" should be "${exp.label}"`)
    if (got.active !== exp.active)
      fail(`${file}: switcher position ${i + 1} (${exp.label}) active-marker mismatch (active should be ${exp.active})`)
    if (!exp.active && got.href !== exp.href)
      fail(`${file}: switcher link "${exp.label}" href "${got.href}" should be "${exp.href}"`)
  })
}

// --- 4. docs/README.md footer links every non-default locale (with ../ prefix) ---
const docsReadmePath = resolve(repoRoot, 'docs', 'README.md')
if (existsSync(docsReadmePath)) {
  const docs = readFileSync(docsReadmePath, 'utf8')
  for (const code of codes) {
    if (code === defaultLocale) continue
    const needle = `[${labels[code]}](../README.${code}.md)`
    if (!docs.includes(needle)) fail(`docs/README.md footer missing localized link: ${needle}`)
  }
} else {
  fail('docs/README.md not found')
}

// --- report ---
if (failures.length) {
  console.error('[check-readme-locales] FAILED:')
  for (const f of failures) console.error(`  - ${f}`)
  process.exit(1)
}
console.log(
  `[check-readme-locales] OK — ${codes.length} locales (${codes.join(', ')}); ` +
    'README files, switchers, and docs footer in sync with webui SUPPORTED_LOCALES',
)
