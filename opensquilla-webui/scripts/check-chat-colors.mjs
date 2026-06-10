import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// Chat surfaces must use the semantic tokens from src/assets/base.css so both
// themes render correctly. Raw hex/rgb()/hsl() color literals are violations.
const root = new URL('..', import.meta.url).pathname
const targets = [join(root, 'src', 'styles', 'chat-view.css'), join(root, 'src', 'components', 'chat')]
// Negative lookbehind keeps HTML entities like &#8593; out of the hex match.
const colorLiteral = /(?<!&)#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/

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
for (const target of targets) {
  for (const file of walk(target)) {
    const rel = relative(root, file)
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, index) => {
      if (colorLiteral.test(line)) {
        failures.push(`${rel}:${index + 1}: raw color literal; use a base.css token instead. ${line.trim()}`)
      }
    })
  }
}

if (failures.length > 0) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('Chat color guard passed.')
