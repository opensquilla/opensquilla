import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

// Every control-UI surface must round its corners with the radius token ladder
// defined in src/assets/base.css: the primitives --radius-none/xs/sm/md/lg/xl/
// 2xl/full and the semantic aliases --radius-control/card/panel/modal/pill. A
// raw length (6px, 0.375rem, 14px, …) inside a border-radius / border-*-radius
// declaration is a violation — route it through a token so the "Instrument"
// direction's corner tiers stay consistent and can be tuned in one place.
//
// Allowed raw values: 0, 0px, 50% (true circles — dots/avatars), inherit, and
// the fully-round pill literals 999px / 9999px, plus calc(...) expressions built
// from var(--radius-*). base.css is the token source, so its --radius-* token
// definitions (custom-property lines) are exempt. Any genuinely geometric one-off
// (hairline caret, progress/trace bar, scrollbar thumb) can opt out with a
// trailing `/* radius-allow: why */`.
const root = fileURLToPath(new URL('..', import.meta.url))
const srcDir = join(root, 'src')

const customProp = /^\s*--[\w-]+\s*:/
// A border-radius / border-<corner>-radius declaration, capturing just its VALUE
// (up to the next ; or }). Scanning only the value avoids false positives from
// other lengths on the same line (e.g. a `padding: 0.25rem` shorthand sitting
// beside a tokenized `border-radius: var(--radius-sm)`).
const radiusValue = /border(?:-[a-z]+)*-radius\s*:\s*([^;}]+)/gi
// A raw CSS length: number + px/rem/em unit.
const lengthLiteral = /\b\d*\.?\d+(?:px|rem|em)\b/g
// Raw length literals that are explicitly allowed even inside a radius decl.
const allowedLength = /^(?:0px|999px|9999px)$/

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

// In .vue files only <style> blocks carry CSS; template class strings can
// contain the word "radius" and must not be scanned.
function styleLineSet(text, isVue) {
  if (!isVue) return null
  const inStyle = new Set()
  let active = false
  text.split('\n').forEach((line, i) => {
    if (!active && /<style[\s>]/.test(line)) { active = true; return }
    if (active && /<\/style>/.test(line)) { active = false; return }
    if (active) inStyle.add(i)
  })
  return inStyle
}

const failures = []
for (const file of files) {
  const rel = relative(root, file).replace(/\\/g, '/')
  const text = readFileSync(file, 'utf8')
  const lines = text.split('\n')
  const styleLines = styleLineSet(text, file.endsWith('.vue'))
  let inBlockComment = false
  lines.forEach((line, index) => {
    if (styleLines && !styleLines.has(index)) return
    // Explicit, reviewed opt-out (e.g. a hairline caret / progress bar geometry).
    if (/radius-allow/.test(line)) return
    let code = line
    // Strip block comments (base.css is scanned, so its banner text must not
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
    // The --radius-* token definitions in base.css are the source of the ladder —
    // allowed to hold raw lengths.
    if (customProp.test(code)) return
    // Check ONLY the value of each border-radius declaration on the line.
    let offending = false
    for (const decl of code.matchAll(radiusValue)) {
      // Strip calc(...) so var(--radius-*)-based expressions don't trip on the
      // literals inside them.
      const value = decl[1].replace(/calc\([^()]*\)/g, '')
      const literals = [...value.matchAll(lengthLiteral)]
        .map((m) => m[0])
        .filter((v) => !allowedLength.test(v))
      if (literals.length > 0) offending = true
    }
    if (offending) {
      failures.push(
        `${rel}:${index + 1}: hardcoded border-radius; use a --radius-* token. ${line.trim()}`,
      )
    }
  })
}

if (failures.length > 0) {
  console.error(
    `WebUI radius guard: ${failures.length} hardcoded border-radius value(s) — use a base.css --radius-* token:\n` +
      failures.join('\n'),
  )
  process.exit(1)
}

console.log('WebUI radius guard passed.')
