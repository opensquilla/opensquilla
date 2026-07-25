#!/usr/bin/env node

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdir, readFile, readdir, realpath, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

import { _electron as electron } from '../../desktop/electron/node_modules/playwright/index.mjs'

class BlockingSurfaceError extends Error {}

function option(name, fallback = '') {
  const index = process.argv.indexOf(name)
  if (index < 0) return fallback
  const value = process.argv[index + 1]
  if (!value) throw new Error(`Missing value for ${name}`)
  return value
}

async function waitFor(check, label, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const value = await check()
      if (value) return value
    } catch (error) {
      if (error instanceof BlockingSurfaceError) throw error
      lastError = error
    }
    await delay(250)
  }
  const detail = lastError ? ` Last error: ${lastError.message || lastError}` : ''
  throw new Error(`Timed out waiting for ${label}.${detail}`)
}

function labelPort(label) {
  let hash = 0
  for (const character of label) hash = ((hash * 33) + character.charCodeAt(0)) >>> 0
  return 19000 + (hash % 1000)
}

function safeLaunchEnvironment(
  userData,
  label,
  useDefaultUserData,
  forceInspectFailure,
) {
  const inherited = { ...process.env }
  for (const name of Object.keys(inherited)) {
    const upper = name.toUpperCase()
    if (
      name.startsWith('OPENSQUILLA_')
      || ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'].includes(upper)
      || /(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(name)
    ) {
      delete inherited[name]
    }
  }
  const inheritedDefaultHome = process.platform === 'win32'
    ? process.env.USERPROFILE || process.env.HOME
    : process.env.HOME || process.env.USERPROFILE
  const isolatedHome = useDefaultUserData
    ? resolve(inheritedDefaultHome || dirname(userData))
    : resolve(dirname(userData), `${label}-isolated-home`)
  const isolatedAppData = useDefaultUserData
    ? resolve(process.env.APPDATA || dirname(userData))
    : resolve(dirname(userData), `${label}-local-app-data`)
  const isolatedLocalData = useDefaultUserData
    ? resolve(process.env.LOCALAPPDATA || isolatedAppData)
    : isolatedAppData
  return {
    ...inherited,
    HOME: isolatedHome,
    USERPROFILE: isolatedHome,
    ...(process.platform === 'darwin'
      ? { CFFIXED_USER_HOME: isolatedHome }
      : {}),
    APPDATA: isolatedAppData,
    LOCALAPPDATA: isolatedLocalData,
    OPENSQUILLA_TEST_PROFILE_LOCK_ROOT: '1',
    OPENSQUILLA_USER_STATE_DIR: isolatedLocalData,
    OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: String(labelPort(label)),
    ...(forceInspectFailure
      ? {
          OPENSQUILLA_DESKTOP_RELEASE_GATE: '1',
          OPENSQUILLA_DESKTOP_TEST_FORCE_INSPECT_FAILURE: '1',
        }
      : {}),
    OPENSQUILLA_RECOVERY_OFFLINE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    OPENSQUILLA_PRIVACY_DISABLE_NETWORK_OBSERVABILITY: '1',
    CI: forceInspectFailure ? 'true' : (inherited.CI || 'false'),
    GITHUB_ACTIONS: forceInspectFailure ? 'true' : '0',
    HTTP_PROXY: 'http://127.0.0.1:1',
    HTTPS_PROXY: 'http://127.0.0.1:1',
    ALL_PROXY: 'http://127.0.0.1:1',
    NO_PROXY: '127.0.0.1,localhost',
    http_proxy: 'http://127.0.0.1:1',
    https_proxy: 'http://127.0.0.1:1',
    all_proxy: 'http://127.0.0.1:1',
    no_proxy: '127.0.0.1,localhost',
    LANG: 'en_US.UTF-8',
  }
}

async function writeCredential(userData) {
  const now = new Date().toISOString()
  await mkdir(userData, { recursive: true })
  await writeFile(
    join(userData, 'desktop-credential.json'),
    JSON.stringify({
      provider: 'minimax_openai',
      model: 'synthetic-release-model',
      baseUrl: 'http://127.0.0.1:18993/v1',
      apiKeyEnv: '',
      encryptedApiKey: Buffer.from('synthetic-release-key', 'utf8').toString('base64'),
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
}

async function desktopEvents(userData) {
  let raw = ''
  try {
    raw = await readFile(join(userData, 'logs', 'desktop.log'), 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return []
    throw error
  }
  return raw
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line) } catch { return null }
    })
    .filter((record) => record && typeof record === 'object')
}

function desktopEventCount(records, event, stableCode = '') {
  return records.filter((record) => (
    record.event === event
    && (!stableCode || record.stableCode === stableCode)
  )).length
}

function assertInspectFailureEventIncrease(before, after, launchLabel) {
  assert.ok(
    desktopEventCount(after, 'recovery_inspect_forced_failure_for_test')
      >= desktopEventCount(before, 'recovery_inspect_forced_failure_for_test') + 1,
    `${launchLabel} packaged launch must execute the forced inspector-failure branch`,
  )
  assert.ok(
    desktopEventCount(
      after,
      'desktop_profile_inspection_advisory',
      'desktop_recovery_inspect_failed',
    ) >= desktopEventCount(
      before,
      'desktop_profile_inspection_advisory',
      'desktop_recovery_inspect_failed',
    ) + 1,
    `${launchLabel} packaged launch must treat desktop_recovery_inspect_failed as advisory`,
  )
}

async function directoryTreeDigest(root) {
  const entries = []
  async function walk(directory, relativeDirectory = '') {
    const children = await readdir(directory, { withFileTypes: true })
    children.sort((left, right) => (
      left.name < right.name ? -1 : left.name > right.name ? 1 : 0
    ))
    for (const child of children) {
      const relativePath = relativeDirectory
        ? `${relativeDirectory}/${child.name}`
        : child.name
      const absolutePath = join(directory, child.name)
      if (child.isSymbolicLink()) {
        throw new Error(`Legacy recovery source contains an unexpected symlink: ${relativePath}`)
      }
      if (child.isDirectory()) {
        entries.push(`directory\t${relativePath}`)
        await walk(absolutePath, relativePath)
        continue
      }
      if (!child.isFile()) {
        throw new Error(`Legacy recovery source contains an unsafe entry: ${relativePath}`)
      }
      const digest = createHash('sha256').update(await readFile(absolutePath)).digest('hex')
      entries.push(`file\t${relativePath}\t${digest}`)
    }
  }
  await walk(root)
  return createHash('sha256').update(`${entries.join('\n')}\n`).digest('hex')
}

async function canonicalExistingPath(path) {
  try {
    return await realpath(path)
  } catch {
    return resolve(path)
  }
}

async function seedLegacyRecoveryScenario(probe, userData, label) {
  const recoveryId = '00000000-0000-4000-8000-000000000001'
  const recoveryLabel = `${label.slice(0, 56)}-recovery`
  const recoveryRoot = join(userData, 'recovery-profiles', recoveryId)
  const recoveryHome = join(recoveryRoot, 'opensquilla')
  const recoveryMarker = `synthetic retained chat (${recoveryLabel})`
  const sentinelPath = join(recoveryRoot, 'release-gate-sentinel.txt')
  const sentinel = `legacy recovery source ${label}\n`
  const seeded = spawnSync(
    'python',
    [
      probe,
      'seed',
      '--home',
      recoveryHome,
      '--label',
      recoveryLabel,
      '--layout',
      'modern',
      '--source-tag',
      'v0.5.0',
    ],
    { encoding: 'utf8' },
  )
  if (seeded.status !== 0) {
    throw new Error(
      `Legacy recovery seed failed: ${
        seeded.error?.message || seeded.stderr || seeded.stdout || `exit ${seeded.status}`
      }`,
    )
  }
  await Promise.all([
    writeFile(sentinelPath, sentinel, 'utf8'),
    writeFile(
      join(userData, 'desktop-profile-context.json'),
      JSON.stringify({
        schema_version: 1,
        active_profile_kind: 'recovery',
        active_recovery_id: recoveryId,
        attention_acknowledgement: null,
        updated_at: new Date().toISOString(),
      }, null, 2),
      'utf8',
    ),
  ])
  const sourceBefore = profileSnapshot(
    probe,
    recoveryHome,
    recoveryLabel,
    recoveryMarker,
    true,
    false,
  )
  assert.equal(sourceBefore.new_marker_count, 1)
  assert.equal(sourceBefore.new_marker_session_keys.length, 1)
  const sourceTreeBefore = await directoryTreeDigest(recoveryRoot)
  return {
    recoveryRoot,
    recoveryHome,
    recoveryLabel,
    recoveryMarker,
    sentinel,
    sentinelPath,
    sourceBefore,
    sourceTreeBefore,
  }
}

async function startProvider() {
  const requests = []
  const server = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const raw = Buffer.concat(chunks).toString('utf8')
    let payload = {}
    try { payload = raw ? JSON.parse(raw) : {} } catch { payload = {} }
    requests.push({ method: request.method, url: request.url, stream: payload.stream })

    if (request.method === 'GET' && request.url?.endsWith('/models')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({
        object: 'list',
        data: [{ id: 'synthetic-release-model' }],
      }))
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
        id: 'chatcmpl-release-title',
        object: 'chat.completion',
        model: 'synthetic-release-model',
        choices: [{
          index: 0,
          message: { role: 'assistant', content: 'Synthetic release session' },
          finish_reason: 'stop',
        }],
        usage: { prompt_tokens: 4, completion_tokens: 3, total_tokens: 7 },
      }))
      return
    }
    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'close',
    })
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-release-client',
      object: 'chat.completion.chunk',
      model: 'synthetic-release-model',
      choices: [{
        index: 0,
        delta: { role: 'assistant', content: 'PACKAGED_CLIENT_REPLY' },
        finish_reason: null,
      }],
    })}\n\n`)
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-release-client',
      object: 'chat.completion.chunk',
      model: 'synthetic-release-model',
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
      usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 },
    })}\n\n`)
    response.end('data: [DONE]\n\n')
  })
  server.listen(18993, '127.0.0.1')
  await once(server, 'listening')
  return {
    requests,
    close: () => new Promise((resolveClose, rejectClose) => {
      server.close((error) => error ? rejectClose(error) : resolveClose())
    }),
  }
}

async function launchCandidate(
  executable,
  userData,
  label,
  useDefaultUserData,
  forceInspectFailure,
) {
  if (!useDefaultUserData) {
    await Promise.all([
      mkdir(resolve(dirname(userData), `${label}-isolated-home`), { recursive: true }),
      mkdir(resolve(dirname(userData), `${label}-local-app-data`), { recursive: true }),
    ])
  }
  return await electron.launch({
    executablePath: executable,
    args: [
      '--use-mock-keychain',
      ...(useDefaultUserData ? [] : [`--user-data-dir=${userData}`]),
    ],
    env: safeLaunchEnvironment(
      userData,
      label,
      useDefaultUserData,
      forceInspectFailure,
    ),
  })
}

async function assertNoBlockingSurfaces(app, allowOnboarding) {
  for (const page of app.windows()) {
    if (page.isClosed()) continue
    if (await page.locator('#recoveryPanel').count().catch(() => 0)) {
      throw new BlockingSurfaceError(
        `packaged client exposed a blocking recovery surface at ${page.url()}`,
      )
    }
    if (await page.locator('#errorPanel.visible').count().catch(() => 0)) {
      throw new BlockingSurfaceError(
        `packaged client exposed a blocking startup error at ${page.url()}`,
      )
    }
    if (!allowOnboarding) {
      if (await page.locator('#setup-form').count().catch(() => 0)) {
        throw new BlockingSurfaceError(
          `packaged upgrade exposed onboarding at ${page.url()}`,
        )
      }
    }
  }
}

async function onboardingClosed(app) {
  for (const page of app.windows()) {
    if (page.isClosed()) continue
    if (await page.locator('#setup-form').count().catch(() => 0)) return false
  }
  return true
}

async function controlPage(app, allowOnboarding = false) {
  try {
    const page = await waitFor(async () => {
      await assertNoBlockingSurfaces(app, allowOnboarding)
      for (const candidate of app.windows()) {
        if (candidate.isClosed()) continue
        let pathname = ''
        try { pathname = new URL(candidate.url()).pathname } catch { pathname = '' }
        if (!['/control/chat', '/control/chat/new'].includes(pathname)) continue
        if (await candidate.locator('.chat-textarea').count().catch(() => 0)) return candidate
      }
      return null
    }, 'packaged Control UI')
    assert.equal(await page.locator('#setup-form').count().catch(() => 0), 0)
    return page
  } catch (error) {
    const windows = await Promise.all(app.windows().map(async (page) => ({
      url: page.url(),
      title: await page.title().catch(() => ''),
      body: await page.locator('body').innerText().catch(() => '').then(
        (value) => value.slice(0, 1500),
      ),
    })))
    throw new Error(`${error.message}; windows=${JSON.stringify(windows)}`)
  }
}

async function onboardingPage(app) {
  return await waitFor(async () => {
    await assertNoBlockingSurfaces(app, true)
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {})
      if (await page.locator('#setup-form').count().catch(() => 0)) return page
    }
    return null
  }, 'packaged onboarding')
}

async function completeCleanOnboarding(app) {
  const page = await onboardingPage(app)
  await page.locator('[data-setup-mode="simple"]').click()
  await page.locator('[data-screen="0"].active .next-button').click()
  await page.locator('[data-screen="1"].active').waitFor({ state: 'visible', timeout: 10_000 })
  const more = page.locator('#providerMoreToggle')
  if (await more.getAttribute('aria-expanded') !== 'true') await more.click()
  await page.locator('#providerGrid [data-provider="minimax_openai"]').click()
  await page.locator('#apiKey').fill('synthetic-release-key')
  await page.locator('#baseUrl').fill('http://127.0.0.1:18993/v1')
  await page.locator('#model').fill('synthetic-release-model')
  await page.locator('[data-screen="1"].active .next-button').click()
  await page.locator('[data-screen="4"].active').waitFor({ state: 'visible', timeout: 10_000 })
  await page.locator('#finish').click()
}

function routedSessionKey(page) {
  try {
    return new URL(page.url()).searchParams.get('session') || ''
  } catch {
    return ''
  }
}

async function resetSidebarSessionDiscovery(page) {
  const newSession = page.locator('.sidebar-new-session')
  await newSession.waitFor({ state: 'visible', timeout: 30_000 })
  await newSession.click()
  await waitFor(() => {
    try {
      return new URL(page.url()).pathname === '/control/chat/new'
    } catch {
      return false
    }
  }, 'new-chat route before sidebar session discovery', 30_000)
}

async function openListedPersistedSession(page, sessionKey, expectedUserText) {
  await resetSidebarSessionDiscovery(page)
  const historyItems = page.locator('.sidebar-history-item')
  let previousCount = -1
  let stableCountPolls = 0
  const itemCount = await waitFor(async () => {
    if (await page.locator('.sidebar-refresh-btn.spinning').count()) return 0
    const count = await historyItems.count()
    stableCountPolls = count === previousCount ? stableCountPolls + 1 : 0
    previousCount = count
    return count > 0 && stableCountPolls >= 2 ? count : 0
  }, 'sidebar history items', 60_000)
  const examined = []

  for (let index = 0; index < itemCount; index += 1) {
    const item = page.locator('.sidebar-history-item').nth(index)
    examined.push((await item.innerText().catch(() => '')).trim() || `item-${index + 1}`)
    await item.click()
    const clickedSessionKey = await waitFor(
      () => routedSessionKey(page),
      `sidebar history item ${index + 1} route`,
      30_000,
    )
    if (clickedSessionKey === sessionKey) {
      await page.locator('.msg-user').filter({ hasText: expectedUserText }).waitFor({
        state: 'visible',
        timeout: 60_000,
      })
      return
    }
    await resetSidebarSessionDiscovery(page)
  }

  throw new Error(
    `Persisted session ${sessionKey} was not discoverable from the sidebar; `
      + `examined=${JSON.stringify(examined)}`,
  )
}

async function newChat(page, marker) {
  await page.locator('.sidebar-new-session').click()
  await waitFor(() => {
    try { return new URL(page.url()).pathname === '/control/chat/new' } catch { return false }
  }, 'new-chat route', 30_000)
  const textarea = page.locator('.chat-textarea')
  await textarea.waitFor({ state: 'visible', timeout: 30_000 })
  await waitFor(async () => {
    await textarea.fill(marker)
    return await page.locator('.chat-send-btn.is-ready').count()
  }, 'ready packaged chat composer', 30_000)
  await textarea.press('Enter')
  await page.locator('.msg-ai').filter({
    hasText: 'PACKAGED_CLIENT_REPLY',
  }).last().waitFor({ state: 'visible', timeout: 60_000 })
  await waitFor(async () => (
    await page.locator('.chat-thread').getAttribute('aria-busy') === 'false'
  ), 'completed packaged chat turn', 60_000)
  return await waitFor(() => {
    try {
      return new URL(page.url()).searchParams.get('session') || ''
    } catch {
      return ''
    }
  }, 'durable new-session route', 30_000)
}

function profileSnapshot(probe, profileHome, label, marker, retained, allowConfigChange) {
  const args = [
    probe,
    'snapshot',
    '--home',
    profileHome,
    '--label',
    label,
    '--new-marker',
    marker,
  ]
  if (!retained) args.push('--skip-retained-verification')
  if (allowConfigChange) args.push('--allow-config-change')
  const result = spawnSync('python', args, { encoding: 'utf8' })
  if (result.status !== 0) {
    throw new Error(
      `Profile snapshot failed: ${
        result.error?.message || result.stderr || result.stdout || `exit ${result.status}`
      }`,
    )
  }
  return JSON.parse(result.stdout)
}

const executable = resolve(option('--executable'))
const userData = resolve(option('--user-data-dir'))
const profileHome = resolve(option('--profile-home', join(userData, 'opensquilla')))
const probe = resolve(option('--probe'))
const label = option('--label')
const mode = option('--mode')
const allowConfigChange = process.argv.includes('--allow-config-change')
const useDefaultUserData = process.argv.includes('--use-default-user-data')
const forceInspectFailure = process.argv.includes('--force-inspect-failure')
assert.match(label, /^[A-Za-z0-9._-]{1,80}$/)
assert.ok(['upgrade', 'clean'].includes(mode), `unsupported mode: ${mode}`)

const retainedMarker = option('--retained-marker', `synthetic retained chat (${label})`)
const marker = mode === 'upgrade'
  ? `NEW_RELEASE_SESSION_${label}${forceInspectFailure ? '_INSPECT_FAILURE' : ''}`
  : `CLEAN_INSTALL_SESSION_${label}`
const provider = await startProvider()
let app

try {
  const forcedEventsBefore = forceInspectFailure
    ? await desktopEvents(userData)
    : []
  if (forceInspectFailure) {
    await assert.rejects(
      readFile(join(userData, 'desktop-session-authority.json'), 'utf8'),
      (error) => error?.code === 'ENOENT',
      'forced packaged scenario must be the candidate first launch without a current anchor',
    )
  }
  const legacyRecovery = forceInspectFailure
    ? await seedLegacyRecoveryScenario(probe, userData, label)
    : null
  let forcedEventsCheckpoint = forcedEventsBefore
  const retainedBefore = mode === 'upgrade'
    ? profileSnapshot(
      probe,
      profileHome,
      label,
      retainedMarker,
      false,
      allowConfigChange,
    )
    : null
  if (retainedBefore) {
    assert.equal(
      retainedBefore.new_marker_count,
      1,
      'upgrade source must contain exactly one retained runtime session',
    )
    assert.equal(
      retainedBefore.new_marker_session_keys.length,
      1,
      'retained marker must identify exactly one durable session',
    )
  }
  if (mode === 'upgrade') await writeCredential(userData)
  app = await launchCandidate(
    executable,
    userData,
    label,
    useDefaultUserData,
    forceInspectFailure,
  )
  if (mode === 'clean') await completeCleanOnboarding(app)
  let page = await controlPage(app, mode === 'clean')
  if (mode === 'clean') {
    await waitFor(() => onboardingClosed(app), 'onboarding window to close', 30_000)
  }
  if (retainedBefore) {
    await openListedPersistedSession(
      page,
      retainedBefore.new_marker_session_keys[0],
      retainedMarker,
    )
  }
  if (legacyRecovery && retainedBefore) {
    const mergedRecovery = profileSnapshot(
      probe,
      profileHome,
      label,
      legacyRecovery.recoveryMarker,
      false,
      allowConfigChange,
    )
    assert.equal(
      mergedRecovery.sessions,
      retainedBefore.sessions + 1,
      'first packaged inspector-failure launch must merge one legacy recovery session',
    )
    assert.equal(
      mergedRecovery.new_marker_count,
      1,
      'legacy recovery transcript must be present once in the primary database',
    )
    assert.equal(mergedRecovery.new_marker_session_keys.length, 1)
    const authority = JSON.parse(
      await readFile(join(userData, 'desktop-session-authority.json'), 'utf8'),
    )
    assert.equal(authority.schema_version, 1)
    assert.equal(
      await canonicalExistingPath(authority.state_dir),
      await canonicalExistingPath(resolve(profileHome, 'state')),
      'inspector failure must pin the primary session database before entering chat',
    )
    await openListedPersistedSession(
      page,
      mergedRecovery.new_marker_session_keys[0],
      legacyRecovery.recoveryMarker,
    )
  }
  const databaseBefore = profileSnapshot(
    probe,
    profileHome,
    label,
    marker,
    false,
    allowConfigChange,
  )
  assert.equal(databaseBefore.new_marker_count, 0)
  const sentSessionKey = await newChat(page, marker)
  await app.close()
  app = null
  if (forceInspectFailure) {
    const eventsAfterFirstLaunch = await desktopEvents(userData)
    assertInspectFailureEventIncrease(
      forcedEventsCheckpoint,
      eventsAfterFirstLaunch,
      'first',
    )
    forcedEventsCheckpoint = eventsAfterFirstLaunch
  }

  const first = profileSnapshot(
    probe,
    profileHome,
    label,
    marker,
    false,
    allowConfigChange,
  )
  assert.equal(first.new_marker_count, 1, 'new session must be stored exactly once')
  assert.equal(
    first.new_marker_session_keys.length,
    1,
    'new marker must identify exactly one durable session',
  )
  assert.equal(
    first.sessions,
    databaseBefore.sessions + 1,
    'new-chat flow must create exactly one new durable session',
  )
  assert.ok(
    first.transcripts > databaseBefore.transcripts,
    'new-chat flow must append durable transcript entries',
  )
  assert.equal(
    first.new_marker_session_keys[0],
    sentSessionKey,
    'the routed Control UI session must match the database session receiving the marker',
  )
  if (retainedBefore) {
    assert.notEqual(
      first.new_marker_session_keys[0],
      retainedBefore.new_marker_session_keys[0],
      'new-chat flow must not append the marker to the retained historical session',
    )
  }
  const retainedAfterFirst = mode === 'upgrade'
    ? profileSnapshot(
      probe,
      profileHome,
      label,
      retainedMarker,
      false,
      allowConfigChange,
    )
    : null
  if (retainedBefore && retainedAfterFirst) {
    assert.deepEqual(
      retainedAfterFirst.new_marker_session_keys,
      retainedBefore.new_marker_session_keys,
      'candidate launch must retain the original release-runtime session',
    )
    assert.equal(retainedAfterFirst.new_marker_count, 1)
  }

  app = await launchCandidate(
    executable,
    userData,
    label,
    useDefaultUserData,
    forceInspectFailure,
  )
  page = await controlPage(app)
  if (retainedBefore) {
    await openListedPersistedSession(
      page,
      retainedBefore.new_marker_session_keys[0],
      retainedMarker,
    )
  }
  if (legacyRecovery) {
    const mergedRecovery = profileSnapshot(
      probe,
      profileHome,
      label,
      legacyRecovery.recoveryMarker,
      false,
      allowConfigChange,
    )
    assert.equal(mergedRecovery.new_marker_count, 1)
    assert.equal(mergedRecovery.new_marker_session_keys.length, 1)
    await openListedPersistedSession(
      page,
      mergedRecovery.new_marker_session_keys[0],
      legacyRecovery.recoveryMarker,
    )
  }
  await openListedPersistedSession(page, first.new_marker_session_keys[0], marker)
  const second = profileSnapshot(
    probe,
    profileHome,
    label,
    marker,
    false,
    allowConfigChange,
  )
  assert.deepEqual(
    {
      sessions: second.sessions,
      transcripts: second.transcripts,
      marker: second.new_marker_count,
    },
    {
      sessions: first.sessions,
      transcripts: first.transcripts,
      marker: first.new_marker_count,
    },
    'relaunch must not duplicate, discard, or switch the session database',
  )
  if (legacyRecovery) {
    const sourceAfter = profileSnapshot(
      probe,
      legacyRecovery.recoveryHome,
      legacyRecovery.recoveryLabel,
      legacyRecovery.recoveryMarker,
      true,
      false,
    )
    assert.deepEqual(
      {
        sessions: sourceAfter.sessions,
        transcripts: sourceAfter.transcripts,
        marker: sourceAfter.new_marker_count,
        markerKeys: sourceAfter.new_marker_session_keys,
      },
      {
        sessions: legacyRecovery.sourceBefore.sessions,
        transcripts: legacyRecovery.sourceBefore.transcripts,
        marker: legacyRecovery.sourceBefore.new_marker_count,
        markerKeys: legacyRecovery.sourceBefore.new_marker_session_keys,
      },
      'packaged inspector-failure recovery must leave the legacy source database unchanged',
    )
    assert.equal(
      await directoryTreeDigest(legacyRecovery.recoveryRoot),
      legacyRecovery.sourceTreeBefore,
      'packaged inspector-failure recovery must leave every legacy source file unchanged',
    )
    assert.equal(
      await readFile(legacyRecovery.sentinelPath, 'utf8'),
      legacyRecovery.sentinel,
      'packaged inspector-failure recovery must leave the legacy source tree unchanged',
    )
  }
  if (forceInspectFailure) {
    const eventsAfter = await desktopEvents(userData)
    assertInspectFailureEventIncrease(
      forcedEventsCheckpoint,
      eventsAfter,
      'second',
    )
  }

  console.log(JSON.stringify({
    ok: true,
    mode,
    label,
    executable,
    database: first.database,
    retainedSessionVisible: mode === 'upgrade',
    newSessionStored: true,
    relaunchIdempotent: true,
    forcedInspectFailure: forceInspectFailure,
    legacyRecoverySessionMerged: Boolean(legacyRecovery),
    legacyRecoverySourceUnchanged: Boolean(legacyRecovery),
    providerRequests: provider.requests.length,
    defaultUserData: useDefaultUserData,
  }, null, 2))
} finally {
  await app?.close().catch(() => {})
  await provider.close().catch(() => {})
}
