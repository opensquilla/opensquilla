import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

// Every control-UI surface must use the semantic color tokens from
// src/assets/base.css so both themes render correctly. Raw hex / rgb() / hsl()
// color literals anywhere under src/ are violations — use a token, or
// color-mix(in srgb, var(--token) …).
//
// base.css is the token source, so it is scanned under a narrower rule: raw
// color literals are allowed only inside custom-property definitions
// (`--token: …`), comments, and neutral black/white rgba (the primitive the
// shadow/border tokens are themselves built from). An off-palette literal in a
// real base.css rule is still a violation — that is how theme-parity drift
// (e.g. a hardcoded near-black border that vanishes on dark) sneaks in.
const root = fileURLToPath(new URL('..', import.meta.url))
const srcDir = join(root, 'src')
const tokenSource = join(srcDir, 'assets', 'base.css')

// Negative lookbehind keeps HTML entities like &#8593; out of the hex match.
const colorLiteral = /(?<!&)#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/
// SVG fragment references such as url(#cg2) are ids, not colors.
const urlRef = /url\(#[\w-]+\)/g
// Neutral black/white — the primitive shadows/borders are built from; allowed
// in base.css rules. Matches rgba(0,0,0,…), rgba(255,255,255,…), #000(0), #fff(f).
const neutralColor =
  /\brgba?\(\s*(?:0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)\b[^)]*\)|#(?:000000|ffffff|000|fff)\b/gi
const customProp = /^\s*--[\w-]+\s*:/

function walk(path, files = []) {
  const stat = statSync(path)
  if (stat.isDirectory()) {
    for (const entry of readdirSync(path)) walk(join(path, entry), files)
  } else if (/\.(vue|css)$/.test(path)) {
    files.push(path)
  }
  return files
}

const files = walk(srcDir)

// ---------------------------------------------------------------------------
// Pass 1 — raw color literals
// ---------------------------------------------------------------------------
const failures = []
for (const file of files) {
  const rel = relative(root, file).replace(/\\/g, '/')
  const isBase = file === tokenSource
  const lines = readFileSync(file, 'utf8').split('\n')
  let inBlockComment = false
  lines.forEach((line, index) => {
    let code = line
    // Strip block comments (base.css is scanned, so its banner hex must not
    // trip the guard); track multi-line state.
    if (inBlockComment) {
      const end = code.indexOf('*/')
      if (end === -1) return
      code = code.slice(end + 2)
      inBlockComment = false
    }
    code = code.replace(/\/\*.*?\*\//g, '')
    const open = code.indexOf('/*')
    if (open !== -1) {
      inBlockComment = true
      code = code.slice(0, open)
    }
    code = code.replace(urlRef, '')
    if (isBase) {
      if (customProp.test(code)) return // a token definition — allowed
      code = code.replace(neutralColor, '') // neutral shadow/border primitive
    }
    if (colorLiteral.test(code)) {
      failures.push(
        `${rel}:${index + 1}: raw color literal; use a base.css token or color-mix(in srgb, var(--token) …). ${line.trim()}`,
      )
    }
  })
}

// ---------------------------------------------------------------------------
// Pass 2 — references to undefined tokens
// ---------------------------------------------------------------------------
// A bare `var(--token)` with no fallback that is never defined anywhere renders
// to nothing (e.g. a colorless status message). Fallback forms `var(--x, …)`
// are intentional and exempt — that is how runtime/host-set vars are consumed.
// Scoped to the semantic color/surface namespace: layout vars like
// `--router-left`/`--i`/`--composer-h` are legitimately set at runtime via
// :style bindings and are out of scope for a color guard.
const semanticToken = /^--(bg|surface|text|color|accent|ok|warn|danger|info|success|border|hairline|card|shadow|scrim|sidebar|syntax)/
const defined = new Set()
const bareUsages = [] // { token, rel, line }
const defRe = /(?:^|[\s;{])(--[\w-]+)\s*:/g
const bareVarRe = /var\(\s*(--[\w-]+)\s*\)/g
for (const file of files) {
  const rel = relative(root, file).replace(/\\/g, '/')
  const text = readFileSync(file, 'utf8')
  for (const m of text.matchAll(defRe)) defined.add(m[1])
  text.split('\n').forEach((line, index) => {
    for (const m of line.matchAll(bareVarRe)) {
      bareUsages.push({ token: m[1], rel, line: index + 1, text: line.trim() })
    }
  })
}
const undefinedTokens = bareUsages.filter(
  (u) => semanticToken.test(u.token) && !defined.has(u.token),
)

// ---------------------------------------------------------------------------
let failed = false
if (failures.length > 0) {
  failed = true
  console.error('Raw color literals found — use base.css design tokens:\n' + failures.join('\n'))
}
if (undefinedTokens.length > 0) {
  failed = true
  console.error(
    '\nReferences to undefined CSS tokens (use a defined token or add a fallback `var(--x, …)`):\n' +
      undefinedTokens.map((u) => `${u.rel}:${u.line}: ${u.token} is never defined. ${u.text}`).join('\n'),
  )
}
if (failed) process.exit(1)

console.log('WebUI color guard passed.')
