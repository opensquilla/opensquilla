import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Cross-surface brand-accent guard.
//
// The product ships several independently-authored surfaces (the Vue console,
// the Electron splash, the Electron onboarding window). Issue #403 found the
// brand accent had fragmented into six different oranges across them. The Vue
// console is already token-guarded by check-webui-colors.mjs; this guard keeps
// the DESKTOP launch sequence (splash + onboarding) locked to the one canonical
// "strike" accent so it can't drift off again.
//
// Scope: only a SATURATED ORANGE (a brand-accent candidate) is checked — a hue
// in the orange band with real saturation. Danger-reds, greens, warm neutrals
// and paper whites are ignored, so the guard is about brand identity, not every
// colour. Backgrounds are intentionally out of scope (too many valid neutral
// shades to allowlist without false positives).
//
// The legacy gateway frontend (src/opensquilla/gateway/static/css) is NOT scanned
// here — its status (resync vs. freeze) is a separate, still-open decision.
const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

// The canonical "strike" family — the Instrument accent and its documented
// hover / deep / secondary / light-theme siblings. Stored as normalized
// "r,g,b" so hex and rgb()/rgba() forms compare equal.
const CANONICAL = new Set([
  '242,106,27', // #F26A1B  accent (dark)
  '255,122,46', // #FF7A2E  accent-hover (dark)
  '217,90,17', //  #D95A11  accent-deep (dark) / onboarding hover
  '255,138,76', // #FF8A4C  accent-secondary
  '218,90,18', //  #DA5A12  accent (light)
  '194,78,14', //  #C24E0E  accent-hover (light)
  '163,67,9', //   #A34309  accent-deep (light)
])

// Files that make up the desktop launch sequence.
const targets = [
  'desktop/electron/src/boot.html',
  'desktop/electron/src/main.ts',
]

function hexToRgb(hex) {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}

// Is this rgb a saturated orange — i.e. a brand-accent candidate?
function isBrandOrange([r, g, b]) {
  const rn = r / 255, gn = g / 255, bn = b / 255
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return false
  const s = d / (1 - Math.abs(2 * l - 1))
  let hue
  if (max === rn) hue = ((gn - bn) / d) % 6
  else if (max === gn) hue = (bn - rn) / d + 2
  else hue = (rn - gn) / d + 4
  hue = ((hue * 60) + 360) % 360
  // Orange band, well saturated, mid lightness — excludes red danger (<16),
  // yellow (>46), and low-saturation warm taupes/papers.
  return hue >= 16 && hue <= 46 && s >= 0.4 && l >= 0.18 && l <= 0.72
}

// Strip HTML/JS/CSS comments so hexes named in comments don't trip the guard.
function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1') // // line comments, but not the // in http://
}

const hexRe = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g
const rgbRe = /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/g

const failures = []
for (const rel of targets) {
  let text
  try {
    text = readFileSync(repoRoot + rel, 'utf8')
  } catch {
    console.warn(`[cross-surface] skipped (not found): ${rel}`)
    continue
  }
  const lines = stripComments(text).split('\n')
  lines.forEach((line, i) => {
    const found = []
    for (const m of line.matchAll(hexRe)) found.push({ raw: m[0], rgb: hexToRgb(m[0]) })
    for (const m of line.matchAll(rgbRe)) found.push({ raw: m[0], rgb: [+m[1], +m[2], +m[3]] })
    for (const { raw, rgb } of found) {
      if (!isBrandOrange(rgb)) continue
      if (CANONICAL.has(rgb.join(','))) continue
      failures.push(
        `${rel}:${i + 1}: off-canonical brand orange ${raw} (rgb ${rgb.join(',')}); use the strike accent (#F26A1B family).`,
      )
    }
  })
}

if (failures.length > 0) {
  console.error(
    `Cross-surface accent guard: ${failures.length} off-canonical brand orange(s) — the desktop launch sequence must use the strike accent:\n` +
      failures.join('\n'),
  )
  process.exit(1)
}

console.log('Cross-surface accent guard passed.')
