import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('..', import.meta.url).pathname
const srcRoot = join(root, 'src')
const allowedDesktopGlobal = new Set([
  'src/platform/capabilities.ts',
  'src/platform/desktop.ts',
  'src/vite-env.d.ts',
])
const bannedPatterns = [
  {
    pattern: 'window.opensquillaDesktop',
    allow: allowedDesktopGlobal,
    message: 'Electron preload access must stay behind src/platform/.',
  },
]
const stalePlatformPatterns = [
  'activeProfile',
  'cloudUrl',
  'getDesktopRpcConnection',
  'desktop:rpc-connection',
]

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue
    const path = join(dir, entry)
    const stat = statSync(path)
    if (stat.isDirectory()) walk(path, files)
    else if (/\.(ts|vue|d\.ts)$/.test(entry)) files.push(path)
  }
  return files
}

const failures = []
for (const file of walk(srcRoot)) {
  const rel = relative(root, file)
  const body = readFileSync(file, 'utf8')
  for (const rule of bannedPatterns) {
    if (body.includes(rule.pattern) && !rule.allow.has(rel)) {
      failures.push(`${rel}: ${rule.message} Found "${rule.pattern}".`)
    }
  }
  for (const pattern of stalePlatformPatterns) {
    if (body.includes(pattern)) {
      failures.push(`${rel}: stale desktop/cloud platform pattern found: "${pattern}".`)
    }
  }
}

if (failures.length > 0) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('Architecture guard passed.')
