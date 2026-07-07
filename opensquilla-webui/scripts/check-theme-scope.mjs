import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { walkFiles } from './lib/fs-walk.mjs'
import { stripCssComments } from './lib/css-utils.mjs'

// Scope-leak / boundary guard for the Axis-B expressive-skin layer.
//   1. Every selector in a theme's skin.css must descend from that theme's
//      `[data-skin="<id>"]` scope — a skin can never restyle the base app.
//   2. A skin must not reach operational L2 surfaces even when scoped.
//   3. L2 (components / views / base.css) must not read a skin-private
//      `--x-*` token — those belong only inside the skin.
const root = fileURLToPath(new URL('..', import.meta.url))
const srcDir = join(root, 'src')
const themesDir = join(srcDir, 'themes')
const rel = (p) => relative(root, p).replace(/\\/g, '/')

// Operational L2 surfaces a skin must never target (belt-and-suspenders: the
// skin is already scoped to its route's content area, but this blocks a skin
// from ever reaching console chrome or data surfaces).
const FORBIDDEN = [
  '.control-stage', '.control-stat', '.control-panel', '.control-card',
  '.data-table', '.approval', '.chat-', '.composer', '.sidebar', '.topbar',
  '.mobile-tab', '[role="alert"]',
]

// Split a selector header into its comma-separated arms, respecting commas
// nested inside (), [] and quotes (`:is(a, b)`, `[attr="x,y"]`). Each arm must
// be validated INDEPENDENTLY — otherwise `[data-skin="x"] .a, body .b {}` passes
// as one blob because the scoped-prefix substring is present, while `body .b`
// silently restyles the whole app (the exact leak this guard exists to stop).
function splitSelectorList(sel) {
  const out = []
  let depth = 0
  let quote = null
  let buf = ''
  for (const ch of sel) {
    if (quote) {
      buf += ch
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; buf += ch; continue }
    if (ch === '(' || ch === '[') { depth++; buf += ch; continue }
    if (ch === ')' || ch === ']') { depth = Math.max(0, depth - 1); buf += ch; continue }
    if (ch === ',' && depth === 0) { out.push(buf); buf = ''; continue }
    buf += ch
  }
  if (buf.trim()) out.push(buf)
  return out
}

// Brace-aware walk: invoke cb(selectorText, depth) for each rule header.
function eachSelector(css, cb) {
  let depth = 0
  let buf = ''
  for (const ch of css) {
    if (ch === '{') {
      const sel = buf.trim()
      if (sel) cb(sel, depth)
      buf = ''
      depth++
    } else if (ch === '}') {
      buf = ''
      depth = Math.max(0, depth - 1)
    } else if (ch === ';' && depth === 0) {
      buf = '' // top-level statement (@import/@charset) — not a selector
    } else {
      buf += ch
    }
  }
}

const failures = []

// --- (1)+(2) skin.css scoping -----------------------------------------------
if (existsSync(themesDir)) {
  for (const entry of readdirSync(themesDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const skinPath = join(themesDir, entry.name, 'skin.css')
    if (!existsSync(skinPath)) continue
    const id = entry.name
    const scoped = (sel) =>
      sel.includes(`[data-skin="${id}"]`) || sel.includes(`[data-skin=${id}]`)
    const css = stripCssComments(readFileSync(skinPath, 'utf8'))
    eachSelector(css, (sel) => {
      if (sel.startsWith('@')) return // @media/@supports/@keyframes/@font-face
      if (/^(from|to|\d+%)(\s*,\s*(from|to|\d+%))*$/.test(sel)) return // keyframe steps
      for (const raw of splitSelectorList(sel)) {
        const arm = raw.trim()
        if (!arm) continue
        if (!scoped(arm)) {
          failures.push(`${rel(skinPath)}: selector not scoped to [data-skin="${id}"]: "${arm}"${arm === sel ? '' : ` (arm of "${sel}")`}`)
          continue
        }
        for (const f of FORBIDDEN) {
          if (arm.includes(f)) {
            failures.push(`${rel(skinPath)}: skin reaches operational surface "${f}": "${arm}"`)
            break
          }
        }
      }
    })
  }

  // world.css (a value theme's global "world" layer) may restyle the whole app
  // (operational L2 included) -- that is the point -- but every selector must
  // still be scoped to [data-theme="<id>"] so it can't leak to other themes.
  for (const entry of readdirSync(themesDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const worldPath = join(themesDir, entry.name, 'world.css')
    if (!existsSync(worldPath)) continue
    const id = entry.name
    const scoped = (sel) =>
      sel.includes(`[data-theme="${id}"]`) || sel.includes(`[data-theme=${id}]`)
    const css = stripCssComments(readFileSync(worldPath, 'utf8'))
    eachSelector(css, (sel) => {
      if (sel.startsWith('@')) return
      if (/^(from|to|\d+%)(\s*,\s*(from|to|\d+%))*$/.test(sel)) return
      for (const raw of splitSelectorList(sel)) {
        const arm = raw.trim()
        if (!arm) continue
        if (!scoped(arm)) {
          failures.push(`${rel(worldPath)}: world selector not scoped to [data-theme="${id}"]: "${arm}"${arm === sel ? '' : ` (arm of "${sel}")`}`)
        }
      }
    })
  }
}

// --- (3) L2 must not read skin-private --x-* tokens --------------------------
const styleFiles = /\.(vue|css)$/
const l2Files = [
  ...walkFiles(join(srcDir, 'components'), styleFiles),
  ...walkFiles(join(srcDir, 'views'), styleFiles),
  // Global stylesheets (control-visual-system, chat-*, route-fx, …) are L2
  // surfaces too — imported app-wide from main.ts.
  ...walkFiles(join(srcDir, 'styles'), styleFiles),
  join(srcDir, 'assets', 'base.css'),
  join(srcDir, 'assets', 'foundation.css'),
]
const xLeak = /var\(\s*--x-[\w-]+/
for (const f of l2Files) {
  if (!existsSync(f)) continue
  readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
    if (xLeak.test(line)) {
      failures.push(`${rel(f)}:${i + 1}: L2 must not read skin-private --x-* token: ${line.trim()}`)
    }
  })
}

if (failures.length) {
  console.error('Theme scope guard failed:\n' + failures.join('\n'))
  process.exit(1)
}
console.log('Theme scope guard passed.')
