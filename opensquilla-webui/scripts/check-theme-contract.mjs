import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseTokenDefinitions } from './lib/css-utils.mjs'

// Contract completeness: every value theme (a folder under src/themes/ that
// ships a tokens.css) must define every required L1 role from contract.json.
// Expressive skins (no tokens.css, or a sparse one) are exempt — they inherit
// the ground's tokens. This is what lets a new/stranger theme drop in without
// silently leaving a role undefined (which renders as an invisible element).
const root = fileURLToPath(new URL('..', import.meta.url))
const themesDir = join(root, 'src', 'themes')

const contract = JSON.parse(readFileSync(join(themesDir, 'contract.json'), 'utf8'))
const required = contract.required ?? []

const failures = []
let checked = 0

for (const entry of readdirSync(themesDir, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue
  const tokensPath = join(themesDir, entry.name, 'tokens.css')
  if (!existsSync(tokensPath)) {
    // Only expressive skins may omit tokens.css. Cross-check the manifest: a
    // kind:'value' folder without one would still register, appear in the
    // picker, and silently render the :root fallback when selected — the
    // "phantom theme" this guard exists to catch (e.g. a token.css typo).
    const manifestPath = join(themesDir, entry.name, 'manifest.ts')
    if (existsSync(manifestPath)) {
      const manifest = readFileSync(manifestPath, 'utf8')
      if (/kind\s*:\s*['"]value['"]/.test(manifest)) {
        failures.push(
          `theme "${entry.name}" declares kind:'value' in its manifest but has no tokens.css — it would ship as a selectable theme whose palette never applies`,
        )
      }
    }
    continue // expressive skin — inherits the ground's tokens, exempt
  }
  const css = readFileSync(tokensPath, 'utf8')
  const defined = new Set(parseTokenDefinitions(css).keys())
  const missing = required.filter((role) => !defined.has(role))
  if (missing.length) {
    failures.push(
      `theme "${entry.name}" (src/themes/${entry.name}/tokens.css) is missing required L1 role(s): ${missing.join(', ')}`,
    )
  }
  checked++
}

if (checked === 0) {
  failures.push('no value-theme token files found (src/themes/*/tokens.css)')
}

if (failures.length) {
  console.error('Theme contract check failed:\n' + failures.join('\n'))
  process.exit(1)
}

console.log(
  `Theme contract check passed (${checked} value theme(s) satisfy ${required.length} required roles).`,
)
