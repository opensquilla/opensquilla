import { strict as assert } from 'node:assert'
import { spawnSync } from 'node:child_process'
import { createServer } from 'node:http'
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')
const screenshotPath = String(process.env.OPENSQUILLA_DESKTOP_RECOVERY_SCREENSHOT || '').trim()
const LEGACY_RECOVERY_ID = '5a8f9b8c-7d6e-4f10-9a2b-3c4d5e6f7081'
const PRESERVED_SESSION_KEY = 'agent:main:webchat:preserved-primary-session'
const PRESERVED_SESSION_ID = 'preserved-primary-session-id'
const PRESERVED_TRANSCRIPT = 'primary transcript must survive desktop startup'
const RECOVERY_SESSION_KEY = 'agent:main:webchat:preserved-recovery-session'
const RECOVERY_SESSION_ID = 'preserved-recovery-session-id'
const RECOVERY_TRANSCRIPT = 'recovery transcript must be merged into the primary session store'
const RECOVERY_ATTACHMENT = 'recovery attachment bytes must survive the profile merge'
const RECOVERY_ARTIFACT = 'recovery artifact bytes must survive the profile merge'
const RECOVERY_SENTINEL = 'legacy recovery profile must remain byte-for-byte untouched'
const SYNTHETIC_API_KEY = 'synthetic-loopback-only-primary-key'
const PROMPT = 'PRIMARY_SESSION_PRESERVATION_E2E_PROMPT'
const REPLY = 'PRIMARY_SESSION_PRESERVATION_E2E_REPLY'
const observedRendererPages = new WeakSet()
const rendererDiagnostics = []
let observedRecoverySurface = false
let observedOnboardingSurface = false

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

async function snapshotTree(root) {
  const result = {}
  async function visit(path, relative = '') {
    const info = await lstat(path)
    assert.equal(info.isSymbolicLink(), false, `fixture must not contain symlinks: ${path}`)
    if (info.isDirectory()) {
      result[`${relative || '.'}/`] = 'directory'
      for (const name of (await readdir(path)).sort()) {
        await visit(join(path, name), relative ? `${relative}/${name}` : name)
      }
      return
    }
    assert.equal(info.isFile(), true, `fixture must contain only files/directories: ${path}`)
    result[relative] = (await readFile(path)).toString('base64')
  }
  await visit(root)
  return result
}

async function inspectForbiddenSurfaces(page) {
  if (page.isClosed()) return
  await page.waitForLoadState('domcontentloaded', { timeout: 2_000 }).catch(() => {})
  observedRecoverySurface ||= await page.locator('#recoveryPanel').count().catch(() => 0) > 0
  observedOnboardingSurface ||= await page.locator('#setup-form').count().catch(() => 0) > 0
}

function observeRenderer(page) {
  if (observedRendererPages.has(page)) return
  observedRendererPages.add(page)
  page.on('console', (message) => {
    rendererDiagnostics.push({ type: `console:${message.type()}`, text: message.text().slice(0, 1_000) })
  })
  page.on('pageerror', (error) => {
    rendererDiagnostics.push({ type: 'pageerror', text: String(error?.message || error).slice(0, 1_000) })
  })
  page.on('domcontentloaded', () => {
    void inspectForbiddenSurfaces(page)
  })
}

async function controlPage(app) {
  try {
    const page = await waitFor(async () => {
      for (const candidate of app.windows()) {
        if (candidate.isClosed()) continue
        observeRenderer(candidate)
        await inspectForbiddenSurfaces(candidate)
        let pathname = ''
        try { pathname = new URL(candidate.url()).pathname } catch { pathname = '' }
        if (pathname !== '/control/chat' && pathname !== '/control/chat/new') continue
        if (await candidate.locator('.chat-textarea').count().catch(() => 0)) return candidate
      }
      return null
    }, 'primary-profile Control UI', 120_000)

    let pathname = ''
    try { pathname = new URL(page.url()).pathname } catch { pathname = '' }
    if (pathname !== '/control/chat/new') {
      await page.locator('.sidebar-new-session').click()
      await waitFor(() => {
        try { return new URL(page.url()).pathname === '/control/chat/new' } catch { return false }
      }, 'new-chat draft route', 30_000)
    }
    return page
  } catch (error) {
    const windows = await Promise.all(app.windows().map(async (page) => ({
      url: page.url(),
      title: await page.title().catch(() => ''),
      body: await page.locator('body').innerText().catch(() => '').then((value) => value.slice(0, 1_500)),
    })))
    throw new Error(
      `${error.message}; windows=${JSON.stringify(windows)}; renderer=${JSON.stringify(rendererDiagnostics.slice(-30))}`,
    )
  }
}

async function sendChat(page, prompt) {
  const textarea = page.locator('.chat-textarea')
  await textarea.waitFor({ state: 'visible', timeout: 30_000 })
  try {
    await waitFor(async () => {
      if (await textarea.inputValue().catch(() => '') !== prompt) {
        await textarea.fill(prompt)
      }
      return await page.locator('.chat-send-btn.is-ready').count().catch(() => 0)
    }, 'ready primary chat composer', 10_000)
  } catch (error) {
    const state = await page.evaluate(() => ({
      href: window.location.href,
      sessionKey: document.querySelector('.chat-label')?.getAttribute('title') || '',
      textareaValue: document.querySelector('.chat-textarea')?.value || '',
      sendButtonClass: document.querySelector('.chat-send-btn')?.className || '',
      bodyText: document.body.innerText.slice(0, 1_000),
    })).catch(() => ({ unavailable: true }))
    throw new Error(`${error.message}; composer=${JSON.stringify(state)}`)
  }
  await textarea.press('Enter')
  await page.locator('.msg-ai').filter({ hasText: REPLY }).last().waitFor({
    state: 'visible',
    timeout: 60_000,
  })
  await waitFor(async () => (
    await page.locator('.chat-thread').getAttribute('aria-busy') === 'false'
  ), 'completed primary chat turn', 60_000)
}

function launchEnvironment(isolatedHome, providerPort, sourceEnvironment = process.env) {
  const inherited = { ...sourceEnvironment }
  for (const name of Object.keys(inherited)) {
    if (name === 'DISPLAY' || name === 'XAUTHORITY') continue
    const upperName = name.toUpperCase()
    if (
      name.startsWith('OPENSQUILLA_')
      || ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'].includes(upperName)
      || /(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(name)
      || /^(?:AWS|AZURE|GOOGLE|ANTHROPIC|OPENAI|OPENROUTER|MINIMAX|DEEPSEEK|GROQ|MISTRAL|COHERE|GEMINI|OLLAMA|XAI|MOONSHOT|DASHSCOPE|SILICONFLOW|ZHIPU|BAIDU|VOLCENGINE|TENCENT|ALIYUN|HF|HUGGINGFACE)_/i.test(name)
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
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: '18898',
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    OPENSQUILLA_GATEWAY_WORKSPACE_DIR: '',
    OPENSQUILLA_WORKSPACE_DIR: '',
    OPENSQUILLA_GATEWAY_STATE_DIR: '',
    OPENSQUILLA_E2E_PROVIDER_PORT: String(providerPort),
    PYTHONFAULTHANDLER: '1',
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

async function launchDesktop(
  userData,
  isolatedHome,
  providerPort,
  forceInspectFailure = false,
) {
  return await electron.launch({
    args: ['--use-mock-keychain', `--user-data-dir=${userData}`, packageRoot],
    env: {
      ...launchEnvironment(isolatedHome, providerPort),
      ...(forceInspectFailure
        ? { OPENSQUILLA_DESKTOP_TEST_FORCE_INSPECT_FAILURE: '1' }
        : {}),
    },
  })
}

async function startFakeProvider() {
  const requests = []
  const server = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const raw = Buffer.concat(chunks).toString('utf8')
    let payload = {}
    try { payload = raw ? JSON.parse(raw) : {} } catch { payload = {} }
    requests.push({ method: request.method, url: request.url, payload })

    if (request.method === 'GET' && request.url?.endsWith('/models')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ object: 'list', data: [{ id: 'synthetic-primary-model' }] }))
      return
    }
    if (request.method === 'GET' && request.url?.endsWith('/api/tags')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ models: [{ name: 'synthetic-primary-model' }] }))
      return
    }
    if (request.method !== 'POST' || !request.url?.endsWith('/chat/completions')) {
      response.writeHead(404, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ error: { message: 'synthetic endpoint not found' } }))
      return
    }
    if (payload.stream === false) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({
        id: 'chatcmpl-primary-title',
        object: 'chat.completion',
        model: 'synthetic-primary-model',
        choices: [{
          index: 0,
          message: { role: 'assistant', content: 'Primary chat' },
          finish_reason: 'stop',
        }],
        usage: { prompt_tokens: 8, completion_tokens: 2, total_tokens: 10 },
      }))
      return
    }
    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'close',
    })
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-primary-e2e',
      object: 'chat.completion.chunk',
      model: 'synthetic-primary-model',
      choices: [{ index: 0, delta: { role: 'assistant', content: REPLY }, finish_reason: null }],
    })}\n\n`)
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-primary-e2e',
      object: 'chat.completion.chunk',
      model: 'synthetic-primary-model',
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
      usage: { prompt_tokens: 12, completion_tokens: 3, total_tokens: 15 },
    })}\n\n`)
    response.end('data: [DONE]\n\n')
  })
  await new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  assert(address && typeof address === 'object')
  return {
    port: address.port,
    requests,
    close: () => new Promise((resolveClose, rejectClose) => {
      server.close((error) => error ? rejectClose(error) : resolveClose())
    }),
  }
}

const root = await realpath(await mkdtemp(join(tmpdir(), 'opensquilla-electron-primary-test-')))
const userData = join(root, 'user-data')
const isolatedHome = join(root, 'home')
const primaryHome = join(userData, 'opensquilla')
const primaryWorkspace = join(primaryHome, 'workspace')
const configuredPrimaryState = join(primaryHome, 'state')
const primaryState = join(root, 'primary-dotenv-state')
const primaryMedia = join(root, 'primary-dotenv-media')
const primaryDatabase = join(primaryState, 'sessions.db')
const primaryCredential = join(userData, 'desktop-credential.json')
const recoveryRoot = join(userData, 'recovery-profiles', LEGACY_RECOVERY_ID)
const recoveryHome = join(recoveryRoot, 'opensquilla')
const recoveryWorkspace = join(recoveryHome, 'workspace')
const configuredRecoveryState = join(recoveryHome, 'state')
const recoveryState = join(recoveryRoot, 'recovery-dotenv-state')
const recoveryMedia = join(recoveryRoot, 'recovery-dotenv-media')

await mkdir(primaryWorkspace, { recursive: true })
await mkdir(configuredPrimaryState, { recursive: true })
await mkdir(primaryState, { recursive: true })
await mkdir(recoveryWorkspace, { recursive: true })
await mkdir(configuredRecoveryState, { recursive: true })
await mkdir(recoveryState, { recursive: true })
await mkdir(isolatedHome, { recursive: true })
for (const [name, text] of [
  ['USER.md', 'synthetic primary user\n'],
  ['SOUL.md', 'synthetic primary soul\n'],
  ['IDENTITY.md', 'synthetic primary identity\n'],
  ['MEMORY.md', 'synthetic primary memory\n'],
]) {
  await writeFile(join(primaryWorkspace, name), text, 'utf8')
}
await writeFile(join(recoveryState, 'legacy-recovery-sentinel.txt'), RECOVERY_SENTINEL, 'utf8')
await writeFile(
  join(recoveryHome, '.env'),
  [
    'OPENSQUILLA_GATEWAY_STATE_DIR=../recovery-dotenv-state',
    `OPENSQUILLA_ATTACHMENTS_MEDIA_ROOT=${JSON.stringify(recoveryMedia)}`,
    '',
  ].join('\n'),
  'utf8',
)
await writeFile(
  join(recoveryHome, 'config.toml'),
  [
    `state_dir = ${JSON.stringify(configuredRecoveryState)}`,
    `workspace_dir = ${JSON.stringify(recoveryWorkspace)}`,
    '',
  ].join('\n'),
  'utf8',
)
await writeFile(
  join(recoveryRoot, 'desktop-credential.json'),
  JSON.stringify({ sentinel: RECOVERY_SENTINEL }, null, 2),
  'utf8',
)
await writeFile(
  join(userData, 'desktop-profile-context.json'),
  JSON.stringify({
    schema_version: 1,
    active_profile_kind: 'recovery',
    active_recovery_id: LEGACY_RECOVERY_ID,
    attention_acknowledgement: null,
    updated_at: '2026-07-25T00:00:00.000Z',
  }, null, 2),
  'utf8',
)

const fakeProvider = await startFakeProvider()
await writeFile(
  join(primaryHome, '.env'),
  [
    'OPENSQUILLA_GATEWAY_STATE_DIR=../../primary-dotenv-state',
    `OPENSQUILLA_ATTACHMENTS_MEDIA_ROOT=${JSON.stringify(primaryMedia)}`,
    '',
  ].join('\n'),
  'utf8',
)
await writeFile(
  join(primaryHome, 'config.toml'),
  [
    `state_dir = ${JSON.stringify(configuredPrimaryState)}`,
    `workspace_dir = ${JSON.stringify(primaryWorkspace)}`,
    '',
    '[llm]',
    'provider = "minimax_openai"',
    'model = "synthetic-primary-model"',
    `base_url = ${JSON.stringify(`http://127.0.0.1:${fakeProvider.port}/v1`)}`,
    '',
  ].join('\n'),
  'utf8',
)
await writeFile(
  primaryCredential,
  JSON.stringify({
    provider: 'minimax_openai',
    model: 'synthetic-primary-model',
    baseUrl: `http://127.0.0.1:${fakeProvider.port}/v1`,
    encryptedApiKey: Buffer.from(SYNTHETIC_API_KEY, 'utf8').toString('base64'),
    modelRoutingMode: 'direct',
    routerMode: 'disabled',
    searchProvider: 'duckduckgo',
    encryption: 'plain',
    createdAt: '2026-07-25T00:00:00.000Z',
    updatedAt: '2026-07-25T00:00:00.000Z',
  }, null, 2),
  'utf8',
)
runPython(
  'import asyncio,sys\n'
  + 'from opensquilla.session.models import SessionNode, TranscriptEntry\n'
  + 'from opensquilla.session.storage import SessionStorage\n'
  + 'async def main():\n'
  + ' s=await SessionStorage.open(sys.argv[1])\n'
  + ' try:\n'
  + '  await s.upsert_session(SessionNode(session_key=sys.argv[2], session_id=sys.argv[3], '
  + 'display_name="Preserved primary chat", status="done"))\n'
  + '  await s.append_transcript_entry(TranscriptEntry(session_id=sys.argv[3], '
  + 'session_key=sys.argv[2], role="user", content=sys.argv[4]))\n'
  + ' finally:\n'
  + '  await s.close()\n'
  + 'asyncio.run(main())',
  [primaryDatabase, PRESERVED_SESSION_KEY, PRESERVED_SESSION_ID, PRESERVED_TRANSCRIPT],
)
const recoveryMaterial = JSON.parse(runPython(
  'import asyncio,json,sys\n'
  + 'from opensquilla.artifacts import ArtifactStore\n'
  + 'from opensquilla.attachment_refs import write_transcript_material\n'
  + 'from opensquilla.session.models import SessionNode, TranscriptEntry\n'
  + 'from opensquilla.session.storage import SessionStorage\n'
  + 'async def main():\n'
  + ' sha,_,_=write_transcript_material(media_root=__import__("pathlib").Path(sys.argv[5]), '
  + 'session_id=sys.argv[3], payload=sys.argv[6].encode())\n'
  + ' artifact=ArtifactStore(sys.argv[5]).publish_bytes(sys.argv[7].encode(), '
  + 'session_id=sys.argv[3], session_key=sys.argv[2], name="recovery-report.txt", '
  + 'mime="text/plain", source="publish_artifact")\n'
  + ' s=await SessionStorage.open(sys.argv[1])\n'
  + ' try:\n'
  + '  await s.upsert_session(SessionNode(session_key=sys.argv[2], session_id=sys.argv[3], '
  + 'display_name="Preserved recovery chat", status="done"))\n'
  + '  await s.append_transcript_entry(TranscriptEntry(session_id=sys.argv[3], '
  + 'session_key=sys.argv[2], role="user", content=json.dumps({"text":sys.argv[4],'
  + '"attachments":[{"sha256_ref":sha,"name":"evidence.txt","mime":"text/plain",'
  + '"size":len(sys.argv[6].encode())}]})))\n'
  + ' finally:\n'
  + '  await s.close()\n'
  + ' print(json.dumps({"sha":sha,"artifact_id":artifact.id}))\n'
  + 'asyncio.run(main())',
  [
    join(recoveryState, 'sessions.db'),
    RECOVERY_SESSION_KEY,
    RECOVERY_SESSION_ID,
    RECOVERY_TRANSCRIPT,
    recoveryMedia,
    RECOVERY_ATTACHMENT,
    RECOVERY_ARTIFACT,
  ],
))

const recoveryBefore = await snapshotTree(recoveryRoot)
const fakeProviderRequestsBeforeLaunch = fakeProvider.requests.length
const scrubbedEnvironmentProbe = launchEnvironment(isolatedHome, fakeProvider.port, {
  ...process.env,
  DISPLAY: ':synthetic-display',
  XAUTHORITY: '/synthetic/xauthority',
  OPENAI_API_KEY: 'synthetic-real-provider-key-must-not-leak',
  AWS_PROFILE: 'synthetic-real-provider-profile-must-not-leak',
  OPENSQUILLA_STATE_DIR: '/synthetic/external/state/must-not-leak',
})
assert.equal(scrubbedEnvironmentProbe.DISPLAY, ':synthetic-display')
assert.equal(scrubbedEnvironmentProbe.XAUTHORITY, '/synthetic/xauthority')
assert.equal(scrubbedEnvironmentProbe.OPENAI_API_KEY, undefined)
assert.equal(scrubbedEnvironmentProbe.AWS_PROFILE, undefined)
assert.equal(scrubbedEnvironmentProbe.OPENSQUILLA_STATE_DIR, undefined)
assert.equal(scrubbedEnvironmentProbe.HTTP_PROXY, 'http://127.0.0.1:1')
assert.equal(scrubbedEnvironmentProbe.NO_PROXY, '127.0.0.1,localhost')

let app
try {
  app = await launchDesktop(userData, isolatedHome, fakeProvider.port, true)
  const control = await controlPage(app)
  assert.equal(observedRecoverySurface, false, 'desktop must not render a recovery interaction')
  assert.equal(observedOnboardingSurface, false, 'saved credentials must not trigger onboarding')

  const recoveryHistory = control.locator(
    '.sidebar-history-item[title="Preserved recovery chat"]',
  )
  await recoveryHistory.waitFor({ state: 'visible', timeout: 30_000 })
  await recoveryHistory.click()
  await control.locator('.msg-user').filter({ hasText: RECOVERY_TRANSCRIPT }).waitFor({
    state: 'visible',
    timeout: 30_000,
  })
  const primaryHistory = control.locator(
    '.sidebar-history-item[title="Preserved primary chat"]',
  )
  await primaryHistory.waitFor({ state: 'visible', timeout: 30_000 })
  await primaryHistory.click()
  await control.locator('.msg-user').filter({ hasText: PRESERVED_TRANSCRIPT }).waitFor({
    state: 'visible',
    timeout: 30_000,
  })
  await control.locator('.sidebar-new-session').click()
  await waitFor(() => {
    try { return new URL(control.url()).pathname === '/control/chat/new' } catch { return false }
  }, 'new primary chat route after preserved-session checks', 30_000)

  if (screenshotPath) {
    await mkdir(dirname(screenshotPath), { recursive: true })
    await control.screenshot({ path: screenshotPath })
  }
  await sendChat(control, PROMPT)
  await waitFor(
    () => fakeProvider.requests.some((item) => JSON.stringify(item.payload).includes(PROMPT)),
    'primary prompt at local fake provider',
  )
  const newSessionKey = await waitFor(() => {
    try { return new URL(control.url()).searchParams.get('session') } catch { return '' }
  }, 'new primary chat route')
  assert.notEqual(newSessionKey, PRESERVED_SESSION_KEY)

  await app.close()
  app = null

  const sessions = JSON.parse(runPython(
    'import json,sqlite3,sys; c=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); '
    + 'rows=c.execute("SELECT session_key,session_id,display_name,status FROM sessions '
    + 'ORDER BY session_key").fetchall(); c.close(); print(json.dumps(rows))',
    [primaryDatabase],
  ))
  const preserved = sessions.find(([sessionKey]) => sessionKey === PRESERVED_SESSION_KEY)
  assert.deepEqual(
    preserved,
    [PRESERVED_SESSION_KEY, PRESERVED_SESSION_ID, 'Preserved primary chat', 'done'],
    JSON.stringify(sessions),
  )
  const recovered = sessions.filter(([sessionKey]) => sessionKey === RECOVERY_SESSION_KEY)
  assert.deepEqual(
    recovered,
    [[RECOVERY_SESSION_KEY, RECOVERY_SESSION_ID, 'Preserved recovery chat', 'done']],
    JSON.stringify(sessions),
  )
  assert(sessions.some(([sessionKey]) => sessionKey === newSessionKey), JSON.stringify(sessions))
  assert.equal(
    await lstat(join(configuredPrimaryState, 'sessions.db')).then(() => true).catch(() => false),
    false,
    'configured fallback state must not replace the profile-dotenv session authority',
  )

  const transcripts = JSON.parse(runPython(
    'import json,sqlite3,sys; c=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); '
    + 'rows=c.execute("SELECT session_key,role,content FROM transcript_entries '
    + 'ORDER BY id").fetchall(); c.close(); print(json.dumps(rows))',
    [primaryDatabase],
  ))
  assert(transcripts.some(([sessionKey, role, content]) => (
    sessionKey === PRESERVED_SESSION_KEY
    && role === 'user'
    && content === PRESERVED_TRANSCRIPT
  )), JSON.stringify(transcripts))
  assert(transcripts.some(([sessionKey, role, content]) => (
    sessionKey === RECOVERY_SESSION_KEY
    && role === 'user'
    && String(content).includes(RECOVERY_TRANSCRIPT)
  )), JSON.stringify(transcripts))
  assert(transcripts.some(([sessionKey, role, content]) => (
    sessionKey === newSessionKey
    && role === 'user'
    && String(content).includes(PROMPT)
  )), JSON.stringify(transcripts))
  assert(transcripts.some(([sessionKey, role, content]) => (
    sessionKey === newSessionKey
    && role === 'assistant'
    && String(content).includes(REPLY)
  )), JSON.stringify(transcripts))
  assert.equal(
    await readFile(
      join(
        primaryMedia,
        'transcripts',
        RECOVERY_SESSION_ID,
        recoveryMaterial.sha,
      ),
      'utf8',
    ),
    RECOVERY_ATTACHMENT,
  )
  assert.equal(
    runPython(
      'import sys; from opensquilla.artifacts import ArtifactStore; '
      + '_,p=ArtifactStore(sys.argv[1]).resolve_for_download('
      + 'sys.argv[2],session_id=sys.argv[3]); print(p.read_text())',
      [primaryMedia, recoveryMaterial.artifact_id, RECOVERY_SESSION_ID],
    ),
    RECOVERY_ARTIFACT,
  )

  assert.deepEqual(
    await snapshotTree(recoveryRoot),
    recoveryBefore,
    'legacy recovery profile must remain byte-for-byte untouched',
  )
  assert.deepEqual(
    (await readdir(join(userData, 'recovery-profiles'))).sort(),
    [LEGACY_RECOVERY_ID],
    'startup must not create another recovery profile',
  )
  assert.deepEqual(
    JSON.parse(await readFile(join(userData, 'desktop-session-authority.json'), 'utf8')),
    {
      schema_version: 1,
      state_dir: primaryState,
      media_root: primaryMedia,
    },
  )
  const persistedContext = JSON.parse(
    await readFile(join(userData, 'desktop-profile-context.json'), 'utf8'),
  )
  assert.equal(
    persistedContext.active_profile_kind,
    'recovery',
    'failed inspection must retain the old context for a safe retry',
  )
  assert.equal(persistedContext.active_recovery_id, LEGACY_RECOVERY_ID)

  app = await launchDesktop(userData, isolatedHome, fakeProvider.port)
  const relaunchedControl = await controlPage(app)
  const relaunchedRecoveryHistory = relaunchedControl.locator(
    '.sidebar-history-item[title="Preserved recovery chat"]',
  )
  await relaunchedRecoveryHistory.waitFor({ state: 'visible', timeout: 30_000 })
  assert.equal(
    await relaunchedRecoveryHistory.count(),
    1,
    'relaunch must not duplicate an already merged recovery conversation',
  )
  await relaunchedRecoveryHistory.click()
  await relaunchedControl.locator('.msg-user').filter({ hasText: RECOVERY_TRANSCRIPT }).waitFor({
    state: 'visible',
    timeout: 30_000,
  })
  await app.close()
  app = null

  const normalizedContext = JSON.parse(
    await readFile(join(userData, 'desktop-profile-context.json'), 'utf8'),
  )
  assert.equal(normalizedContext.active_profile_kind, 'primary')
  assert.equal(normalizedContext.active_recovery_id, null)

  const relaunchedRecoveryCount = Number(runPython(
    'import sqlite3,sys; c=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); '
    + 'value=c.execute("SELECT COUNT(*) FROM sessions WHERE session_key = ?", '
    + '(sys.argv[2],)).fetchone()[0]; c.close(); print(value)',
    [primaryDatabase, RECOVERY_SESSION_KEY],
  ))
  assert.equal(relaunchedRecoveryCount, 1)
  assert.deepEqual(
    await snapshotTree(recoveryRoot),
    recoveryBefore,
    'idempotent relaunch must leave the legacy recovery profile untouched',
  )

  console.log(JSON.stringify({
    ok: true,
    originalSessionPreserved: true,
    recoverySessionMerged: true,
    recoveryMaterialsMerged: true,
    recoveryMergeIdempotent: true,
    newSessionStoredInPrimaryDatabase: true,
    recoveryInteractionRemoved: true,
    onboardingSkipped: true,
    legacyRecoveryProfileUntouched: true,
    sessionAuthorityPinned: true,
    profileDotenvAuthorityPreserved: true,
    inspectorFailureStillEnteredClient: true,
    providerRequests: fakeProvider.requests.length - fakeProviderRequestsBeforeLaunch,
  }, null, 2))
} catch (error) {
  const requestSummary = fakeProvider.requests.map((item) => ({
    method: item.method,
    url: item.url,
    stream: item.payload?.stream,
  }))
  const desktopLog = await readFile(join(userData, 'logs', 'desktop.log'), 'utf8').catch(() => '')
  const gatewayLog = await readFile(join(userData, 'logs', 'gateway.log'), 'utf8').catch(() => '')
  console.error(JSON.stringify({
    requestSummary,
    observedRecoverySurface,
    observedOnboardingSurface,
    desktopLogTail: desktopLog.slice(-8_000),
    gatewayLogTail: gatewayLog.slice(-8_000),
    rendererDiagnostics: rendererDiagnostics.slice(-40),
  }, null, 2))
  throw error
} finally {
  await app?.close().catch(() => {})
  await fakeProvider.close().catch(() => {})
  await rm(root, { recursive: true, force: true }).catch(() => {})
}
