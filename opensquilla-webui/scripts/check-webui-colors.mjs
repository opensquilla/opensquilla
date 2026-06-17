import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// Every control-UI surface must use the semantic color tokens from
// src/assets/base.css so both themes render correctly. Raw hex / rgb() / hsl()
// color literals anywhere under src/ (outside the token definitions in
// base.css) are violations — use a token, or color-mix(in srgb, var(--token) …).
const root = new URL('..', import.meta.url).pathname
const srcDir = join(root, 'src')
const tokenSource = join(srcDir, 'assets', 'base.css')

// Negative lookbehind keeps HTML entities like &#8593; out of the hex match.
const colorLiteral = /(?<!&)#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/
// SVG fragment references such as url(#cg2) are ids, not colors.
const urlRef = /url\(#[\w-]+\)/g

function walk(path, files = []) {
  const stat = statSync(path)
  if (stat.isDirectory()) {
    for (const entry of readdirSync(path)) walk(join(path, entry), files)
  } else if (/\.(vue|css)$/.test(path)) {
    files.push(path)
  }
  return files
}

const failures = []
for (const file of walk(srcDir)) {
  if (file === tokenSource) continue
  const rel = relative(root, file)
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, index) => {
    if (colorLiteral.test(line.replace(urlRef, ''))) {
      failures.push(
        `${rel}:${index + 1}: raw color literal; use a base.css token or color-mix(in srgb, var(--token) …). ${line.trim()}`,
      )
    }
  })
}

if (failures.length > 0) {
  console.error('Raw color literals found — use base.css design tokens:\n' + failures.join('\n'))
  process.exit(1)
}

console.log('WebUI color guard passed.')
