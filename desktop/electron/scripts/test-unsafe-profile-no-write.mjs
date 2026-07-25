import { strict as assert } from 'node:assert'
import { spawnSync } from 'node:child_process'
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')
const recoveryId = '11234567-89ab-4cde-8fab-0123456789ab'
const sessionKey = 'agent:main:unsafe-recovery-regression'
const sessionSentinel = 'primary transcript must survive an unsafe recovery selection'

async function waitFor(check, label, timeoutMs = 90_000) {
  const startedAt = Date.now()
  let lastError
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const value = await check()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await delay(250)
  }
  throw new Error(`Timed out waiting for ${label}: ${lastError?.message || lastError || ''}`)
}

function runPython(source, args) {
  const result = spawnSync('uv', ['run', 'python', '-c', source, ...args], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  if (result.status !== 0) {
    throw new Error(`Python fixture command failed: ${result.stderr || result.stdout}`)
  }
  return result.stdout.trim()
}

async function freeLoopbackPort() {
  const server = createServer()
  await new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  assert(address && typeof address === 'object')
  const port = address.port
  await new Promise((resolveClose, rejectClose) => {
    server.close((error) => error ? rejectClose(error) : resolveClose())
  })
  return port
}

async function snapshotTree(root) {
  const snapshot = {}
  async function visit(path, relative = '') {
    const info = await lstat(path)
    assert.equal(info.isSymbolicLink(), false, `unsafe target fixture must be a plain tree: ${path}`)
    if (info.isDirectory()) {
      snapshot[`${relative || '.'}/`] = 'directory'
      for (const name of (await readdir(path)).sort()) {
        await visit(join(path, name), relative ? `${relative}/${name}` : name)
      }
      return
    }
    assert.equal(info.isFile(), true, `unsafe target fixture contains an unexpected node: ${path}`)
    snapshot[relative] = (await readFile(path)).toString('base64')
  }
  await visit(root)
  return snapshot
}

async function waitForNormalDesktop(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      if (await page.locator('#recoveryPanel.visible').count().catch(() => 0)) {
        return { kind: 'recovery', page }
      }
      let pathname = ''
      try {
        pathname = new URL(page.url()).pathname
      } catch {
        pathname = ''
      }
      if (
        (pathname === '/control/chat' || pathname === '/control/chat/new')
        && await page.locator('.chat-textarea').count().catch(() => 0)
      ) {
        return { kind: 'control', page }
      }
    }
    return null
  }, 'normal Desktop Control UI')
}

function isolatedLaunchEnvironment(isolatedHome, gatewayPort) {
  const inherited = { ...process.env }
  for (const name of Object.keys(inherited)) {
    if (name === 'DISPLAY' || name === 'XAUTHORITY') continue
    const upperName = name.toUpperCase()
    if (
      name.startsWith('OPENSQUILLA_')
      || ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'].includes(upperName)
      || /(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(name)
    ) {
      delete inherited[name]
    }
  }
  return {
    ...inherited,
    HOME: isolatedHome,
    USERPROFILE: isolatedHome,
    OPENSQUILLA_DESKTOP_REPO_ROOT: repoRoot,
    OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
    OPENSQUILLA_USER_STATE_DIR: join(isolatedHome, 'user-state'),
    OPENSQUILLA_TEST_PROFILE_LOCK_ROOT: '1',
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: String(gatewayPort),
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    HTTP_PROXY: 'http://127.0.0.1:1',
    HTTPS_PROXY: 'http://127.0.0.1:1',
    ALL_PROXY: 'http://127.0.0.1:1',
    NO_PROXY: '127.0.0.1,localhost',
    http_proxy: 'http://127.0.0.1:1',
    https_proxy: 'http://127.0.0.1:1',
    all_proxy: 'http://127.0.0.1:1',
    no_proxy: '127.0.0.1,localhost',
    LANG: 'en_US.UTF-8',
    LC_ALL: 'en_US.UTF-8',
  }
}

const root = await realpath(await mkdtemp(join(tmpdir(), 'opensquilla-unsafe-profile-test-')))
const userData = join(root, 'user-data')
const isolatedHome = join(root, 'home')
const primaryHome = join(userData, 'opensquilla')
const primaryWorkspace = join(primaryHome, 'workspace')
const primaryState = join(primaryHome, 'state')
const primaryDatabase = join(primaryState, 'sessions.db')
const outside = join(root, 'outside')
const recoveryRoot = join(userData, 'recovery-profiles')
const selectedRoot = join(recoveryRoot, recoveryId)
const gatewayPort = await freeLoopbackPort()

await mkdir(primaryWorkspace, { recursive: true })
await mkdir(primaryState, { recursive: true })
await mkdir(recoveryRoot, { recursive: true })
await mkdir(isolatedHome, { recursive: true })
await mkdir(join(outside, 'opensquilla', 'state'), { recursive: true })

for (const [name, text] of [
  ['USER.md', '# Synthetic primary user\n'],
  ['SOUL.md', '# Synthetic primary soul\n'],
  ['IDENTITY.md', '# Synthetic primary identity\n'],
  ['MEMORY.md', '# Synthetic primary memory\n'],
]) {
  await writeFile(join(primaryWorkspace, name), text, 'utf8')
}
await writeFile(
  join(primaryHome, 'config.toml'),
  [
    `workspace_dir = ${JSON.stringify(primaryWorkspace)}`,
    `state_dir = ${JSON.stringify(primaryState)}`,
    'search_provider = "duckduckgo"',
    'search_api_key_env = ""',
    '',
    '[llm]',
    'provider = "ollama"',
    'model = "synthetic-primary-model"',
    'base_url = "http://127.0.0.1:9/v1"',
    'api_key_env = ""',
    '',
    '[squilla_router]',
    'enabled = false',
    '',
    '[control_ui]',
    'enabled = true',
    'base_path = "/control"',
    '',
  ].join('\n'),
  'utf8',
)
const now = new Date().toISOString()
await writeFile(
  join(userData, 'desktop-credential.json'),
  JSON.stringify({
    provider: 'ollama',
    model: 'synthetic-primary-model',
    baseUrl: 'http://127.0.0.1:9/v1',
    apiKeyEnv: '',
    encryptedApiKey: '',
    modelRoutingMode: 'direct',
    routerMode: 'disabled',
    routerDefaultTier: 'c1',
    routerTiers: {},
    searchProvider: 'duckduckgo',
    searchApiKeyEnv: '',
    encryptedSearchApiKey: '',
    encryption: 'plain',
    disableNetworkObservability: true,
    createdAt: now,
    updatedAt: now,
  }, null, 2),
  { mode: 0o600 },
)
runPython(
  `
import asyncio
import sys
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage

async def seed() -> None:
    storage = SessionStorage(sys.argv[1])
    await storage.connect()
    manager = SessionManager(storage, inject_time_prefix=False)
    await manager.create(sys.argv[2])
    await manager.append_message(sys.argv[2], "user", sys.argv[3])
    await storage.close()

asyncio.run(seed())
`,
  [primaryDatabase, sessionKey, sessionSentinel],
)

const unsafeUpdateState = join(outside, 'opensquilla', 'state', 'desktop-update.json')
await writeFile(
  unsafeUpdateState,
  JSON.stringify({
    snoozedVersion: '0.0.1',
    snoozedUntil: '2099-01-01T00:00:00.000Z',
  }, null, 2),
  'utf8',
)
await writeFile(
  join(outside, 'opensquilla', 'state', 'sessions.db'),
  'unsafe recovery database sentinel; this is intentionally not SQLite\n',
  'utf8',
)
await writeFile(
  join(outside, 'desktop-credential.json'),
  'unsafe recovery credential sentinel\n',
  'utf8',
)
await symlink(outside, selectedRoot, process.platform === 'win32' ? 'junction' : 'dir')
await writeFile(
  join(userData, 'desktop-profile-context.json'),
  JSON.stringify({
    schema_version: 1,
    active_profile_kind: 'recovery',
    active_recovery_id: recoveryId,
    attention_acknowledgement: null,
    updated_at: '2026-07-11T00:00:00.000Z',
  }, null, 2),
  'utf8',
)

const outsideBefore = await snapshotTree(outside)
let app
try {
  app = await electron.launch({
    args: ['--use-mock-keychain', `--user-data-dir=${userData}`, packageRoot],
    env: isolatedLaunchEnvironment(isolatedHome, gatewayPort),
  })

  const destination = await waitForNormalDesktop(app)
  assert.equal(
    destination.kind,
    'control',
    'an unsafe persisted recovery selection must never show a blocking recovery interaction',
  )
  assert.match(new URL(destination.page.url()).pathname, /^\/control\/chat(?:\/new)?$/)
  assert.equal(await destination.page.locator('#recoveryPanel').count(), 0)

  const retainedContext = JSON.parse(
    await readFile(join(userData, 'desktop-profile-context.json'), 'utf8'),
  )
  assert.equal(
    retainedContext.active_profile_kind,
    'recovery',
    'an unsafe source selection must remain recorded for a later safe retry',
  )
  assert.equal(retainedContext.active_recovery_id, recoveryId)

  await delay(1_000)
  await app.close()
  app = null

  assert.deepEqual(
    await snapshotTree(outside),
    outsideBefore,
    'Desktop must not read through or write through the unsafe recovery selection',
  )
  assert.deepEqual(
    (await readdir(recoveryRoot)).sort(),
    [recoveryId],
    'Desktop must neither replace the unsafe recovery link nor create another recovery profile',
  )
  assert.equal((await lstat(selectedRoot)).isSymbolicLink(), true)
  assert.equal(await realpath(selectedRoot), outside)

  const persistedSession = JSON.parse(runPython(
    `
import json
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
session = connection.execute(
    "SELECT session_key FROM sessions WHERE session_key = ?",
    (sys.argv[2],),
).fetchone()
entries = connection.execute(
    "SELECT role, content FROM transcript_entries WHERE session_key = ? ORDER BY id",
    (sys.argv[2],),
).fetchall()
connection.close()
print(json.dumps({"session": session, "entries": entries}))
`,
    [primaryDatabase, sessionKey],
  ))
  assert.deepEqual(persistedSession.session, [sessionKey])
  assert(
    persistedSession.entries.some(
      ([role, content]) => role === 'user' && content === sessionSentinel,
    ),
    'the primary session transcript must remain available after startup',
  )

  console.log(JSON.stringify({
    ok: true,
    activeProfile: 'primary',
    primarySessionPreserved: true,
    unsafeRecoveryTreeUnchanged: true,
    recoveryProfilesCreated: 0,
  }))
} finally {
  await app?.close().catch(() => {})
  await rm(root, { recursive: true, force: true }).catch(() => {})
}
