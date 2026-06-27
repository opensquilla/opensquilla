import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
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

// live-turn fold fence: the append-only turn log and its pure reducer are an internal
// live-turn detail. Keep their imports inside the chat composables (where the
// legacy live refs live) plus ChatView, so the new path cannot leak into other
// layers before it is ever authoritative.
function isUnderChatComposables(rel) {
  const normalized = rel.split('\\').join('/')
  return normalized.startsWith('src/composables/chat/')
}
function isChatView(rel) {
  return rel.split('\\').join('/') === 'src/views/ChatView.vue'
}
const turnLogModulePatterns = [
  '@/composables/chat/useChatTurnLog',
  '@/composables/chat/turnParity',
  '@/utils/chat/foldTurn',
]

// Test files exercise the fenced modules directly (that is their job) and are
// not a runtime layer, so they are exempt from the import fence below.
function isTestFile(entry) {
  return /\.(test|spec)\.(ts|tsx)$/.test(entry)
}

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue
    const path = join(dir, entry)
    const stat = statSync(path)
    if (stat.isDirectory()) walk(path, files)
    else if (/\.(ts|vue|d\.ts)$/.test(entry) && !isTestFile(entry)) files.push(path)
  }
  return files
}

const failures = []
for (const file of walk(srcRoot)) {
  const rel = relative(root, file).replace(/\\/g, '/')
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
  if (!isUnderChatComposables(rel) && !isChatView(rel)) {
    for (const moduleId of turnLogModulePatterns) {
      if (body.includes(moduleId)) {
        failures.push(`${rel}: live-turn log "${moduleId}" must stay within src/composables/chat/ or views/ChatView.vue.`)
      }
    }
  }
}

if (failures.length > 0) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('Architecture guard passed.')
