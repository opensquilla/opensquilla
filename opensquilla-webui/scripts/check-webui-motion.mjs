import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

// Every control-UI surface must move with the shared motion vocabulary defined in
// src/assets/base.css: durations --dur-fast/base/enter/pulse and easings
// --ease-standard/out/in/spring. Raw millisecond/second literals and the bare
// `ease`/`ease-in`/`ease-out`/`ease-in-out` keywords inside transition/animation
// declarations are violations — route them through the tokens so timing and feel
// stay consistent (and so "exits one tier faster" can be enforced in one place).
//
// Allowed: var(--token), cubic-bezier(...)/steps(...) custom curves, `linear`
// and `infinite` continuous loops (spinners/pulses keep their own cadence), the
// zero value (0s/0ms), and the token definitions in base.css. Any genuinely
// intentional one-off can opt out with a trailing `/* motion-allow: why */`.
const root = fileURLToPath(new URL('..', import.meta.url))
const srcDir = join(root, 'src')

const customProp = /^\s*--[\w-]+\s*:/
const easingKeyword = /\b(?:ease-in-out|ease-in|ease-out|ease)\b/
// A time value; we exclude the literal zero (0s / 0ms / 0.0s) separately.
const durationLiteral = /\b\d*\.?\d+m?s\b/g
const isZero = (v) => /^0(?:\.0+)?m?s$/.test(v)

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
const failures = []

// In .vue files only <style> blocks carry CSS; script/template lines (timer
// durations, "1s tick" comments) must not be scanned as motion.
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

for (const file of files) {
  const rel = relative(root, file).replace(/\\/g, '/')
  const text = readFileSync(file, 'utf8')
  const lines = text.split('\n')
  const styleLines = styleLineSet(text, file.endsWith('.vue'))
  let inBlockComment = false
  lines.forEach((line, index) => {
    if (styleLines && !styleLines.has(index)) return
    // Explicit, reviewed opt-out (e.g. a spinner whose cadence is intentional).
    if (/motion-allow/.test(line)) return
    let code = line
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
    // Token definitions are the source of the vocabulary — allowed to hold raw
    // values and bare curves.
    if (customProp.test(code)) return
    // Stagger delays are layout math (per-item offsets), not the motion-quality
    // vocabulary — `animation-delay`/`transition-delay` are out of scope.
    if (/(?:animation|transition)-delay\s*:/.test(code)) return
    // Strip the allowed forms so only raw literals can remain to be flagged.
    code = code
      .replace(/var\([^()]*\)/g, '')
      .replace(/cubic-bezier\([^()]*\)/g, '')
      .replace(/steps\([^()]*\)/g, '')
    // Continuous loops (linear/infinite spinners, breathes, shimmers) keep their
    // own cadence and symmetric curve, which sit outside the UI-transition
    // vocabulary — exempt the whole line (both duration and easing).
    if (/\b(?:infinite|linear)\b/.test(code)) return

    const durations = [...code.matchAll(durationLiteral)]
      .map((m) => m[0])
      .filter((v) => !isZero(v))
    if (durations.length > 0) {
      failures.push(
        `${rel}:${index + 1}: raw duration ${durations.join(', ')}; use var(--dur-fast|base|enter|pulse). ${line.trim()}`,
      )
    }
    if (easingKeyword.test(code)) {
      failures.push(
        `${rel}:${index + 1}: bare easing keyword; use var(--ease-standard|out|in|spring). ${line.trim()}`,
      )
    }
  })
}

if (failures.length > 0) {
  console.error(
    `WebUI motion guard: ${failures.length} raw motion literal(s) — route through base.css motion tokens:\n` +
      failures.join('\n'),
  )
  process.exit(1)
}

console.log('WebUI motion guard passed.')
