import { strict as assert } from 'node:assert'
import { spawnSync } from 'node:child_process'
import { lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')
const SOURCE_IDENTITY = '# Synthetic imported identity\n'
const TARGET_IDENTITY = '# Synthetic previous Desktop identity\n'
const SOURCE_CHAT = 'synthetic imported chat survives whole-profile transfer'
// A replace import performs two independently bounded receipt-verifier CLI
// calls (60 seconds each) around the mutating import. Windows CI cold starts
// can legitimately approach both bounds, so the E2E timeout must cover the
// product's advertised "few minutes" operation without becoming unbounded.
const PROFILE_IMPORT_APPLY_TIMEOUT_MS = 180_000

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
    env: { ...process.env, UV_CACHE_DIR: join(tmpdir(), 'opensquilla-profile-import-uv-cache') },
  })
  if (result.status !== 0) {
    throw new Error(`Python fixture command failed: ${result.stderr || result.stdout}`)
  }
  return result.stdout.trim()
}

function seedProfile(home, identity, chat) {
  runPython(`
import json, sqlite3, sys
from pathlib import Path
home = Path(sys.argv[1]).resolve()
identity = sys.argv[2]
chat = sys.argv[3]
workspace = home / "workspace"
state = home / "state"
workspace.mkdir(parents=True, exist_ok=True)
state.mkdir(parents=True, exist_ok=True)
for name, value in {
    "IDENTITY.md": identity,
    "USER.md": "# Synthetic user\\n",
    "SOUL.md": "# Synthetic soul\\n",
    "MEMORY.md": "# Synthetic memory\\n",
}.items():
    (workspace / name).write_text(value, encoding="utf-8", newline="")
(home / "config.toml").write_text(
    "workspace_dir = " + json.dumps(str(workspace)) + "\\n"
    + "state_dir = " + json.dumps(str(state)) + "\\n"
    + "[llm]\\nprovider = \\"ollama\\"\\nmodel = \\"synthetic-import-model\\"\\n"
    + "base_url = \\"http://127.0.0.1:11434/v1\\"\\napi_key_env = \\"\\"\\n",
    encoding="utf-8",
    newline="",
)
with sqlite3.connect(state / "sessions.db") as connection:
    connection.execute("CREATE TABLE synthetic_import_chat (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    connection.execute("INSERT INTO synthetic_import_chat VALUES (?, ?)", ("session-1", chat))
    assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
`, [home, identity, chat])
}

async function writeProviderProfileConfig(home, settings) {
  const workspace = join(home, 'workspace')
  const state = join(home, 'state')
  const lines = [
    `workspace_dir = ${JSON.stringify(workspace)}`,
    `state_dir = ${JSON.stringify(state)}`,
    `search_provider = ${JSON.stringify(settings.searchProvider || 'duckduckgo')}`,
    `search_api_key_env = ${JSON.stringify(settings.searchApiKeyEnv || '')}`,
    '',
    '[llm]',
    `provider = ${JSON.stringify(settings.provider)}`,
    `model = ${JSON.stringify(settings.model)}`,
    `base_url = ${JSON.stringify(settings.baseUrl)}`,
    `api_key_env = ${JSON.stringify(settings.apiKeyEnv || '')}`,
    '',
    '[squilla_router]',
    `enabled = ${settings.routerEnabled === true ? 'true' : 'false'}`,
    'default_tier = "c2"',
    'confidence_threshold = 0.77',
    '',
    '[squilla_router.tiers.c0]',
    `provider = ${JSON.stringify(settings.provider)}`,
    'model = "synthetic-source-tier-model"',
    '',
    '[llm_ensemble]',
    'enabled = false',
    'selection_mode = "static_openrouter_b5"',
    '',
    '[privacy]',
    `disable_network_observability = ${settings.disableNetworkObservability ? 'true' : 'false'}`,
    '',
    '[control_ui]',
    'enabled = true',
    'base_path = "/control"',
    '',
  ]
  await writeFile(join(home, 'config.toml'), lines.join('\n'), 'utf8')
}

async function seedDesktopCredential(userData, settings) {
  await mkdir(userData, { recursive: true })
  const now = '2026-07-12T00:00:00.000Z'
  const credential = {
    provider: settings.provider,
    model: settings.model,
    baseUrl: settings.baseUrl,
    apiKeyEnv: settings.apiKeyEnv || '',
    encryptedApiKey: settings.apiKey
      ? Buffer.from(settings.apiKey, 'utf8').toString('base64')
      : '',
    encryption: 'plain',
    configAuthority: 'generated',
    importTransactionId: '',
    createdAt: now,
    updatedAt: now,
  }
  const raw = `${JSON.stringify(credential, null, 2)}\n`
  await writeFile(join(userData, 'desktop-credential.json'), raw, { mode: 0o600 })
  return raw
}

async function snapshotTree(root) {
  const result = {}
  async function visit(path, relative = '') {
    const info = await lstat(path)
    assert.equal(info.isSymbolicLink(), false, `fixture cannot contain symlinks: ${path}`)
    if (info.isDirectory()) {
      result[`${relative || '.'}/`] = { type: 'directory', mode: info.mode }
      for (const name of (await readdir(path)).sort()) {
        await visit(join(path, name), relative ? `${relative}/${name}` : name)
      }
      return
    }
    assert.equal(info.isFile(), true)
    result[relative] = {
      type: 'file',
      mode: info.mode,
      bytes: (await readFile(path)).toString('base64'),
    }
  }
  await visit(root)
  return result
}

function launchEnvironment(isolatedHome, port) {
  const inherited = { ...process.env }
  for (const name of Object.keys(inherited)) {
    if (name === 'DISPLAY' || name === 'XAUTHORITY') continue
    const upperName = name.toUpperCase()
    if (
      name.startsWith('OPENSQUILLA_')
      || ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'].includes(upperName)
      || /(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(name)
      || /^(?:AWS|AZURE|GOOGLE|ANTHROPIC|OPENAI|OPENROUTER|MINIMAX|DEEPSEEK|GROQ|MISTRAL|COHERE|GEMINI|OLLAMA|XAI|MOONSHOT|DASHSCOPE|SILICONFLOW|ZHIPU|BAIDU|VOLCENGINE|TENCENT|ALIYUN|HF|HUGGINGFACE)_/i.test(name)
    ) delete inherited[name]
  }
  return {
    ...inherited,
    HOME: isolatedHome,
    USERPROFILE: isolatedHome,
    OPENSQUILLA_DESKTOP_REPO_ROOT: repoRoot,
    OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
    OPENSQUILLA_USER_STATE_DIR: join(isolatedHome, 'user-state'),
    OPENSQUILLA_TEST_PROFILE_LOCK_ROOT: '1',
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: String(port),
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    UV_CACHE_DIR: join(isolatedHome, '.uv-cache'),
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

async function launchDesktop(userData, isolatedHome, port) {
  return await electron.launch({
    args: ['--use-mock-keychain', `--user-data-dir=${userData}`, packageRoot],
    env: launchEnvironment(isolatedHome, port),
  })
}

async function onboardingPage(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      if (await page.locator('#setup-form').count().catch(() => 0)) return page
    }
    return null
  }, 'Desktop onboarding')
}

async function recoveryPage(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      if (await page.locator('#recoveryPanel.visible').count().catch(() => 0)) return page
    }
    return null
  }, 'recovery profile confirmation page')
}

async function controlPage(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      let pathname = ''
      try { pathname = new URL(page.url()).pathname } catch { pathname = '' }
      if (!['/control/chat', '/control/chat/new'].includes(pathname)) continue
      if (await page.locator('.chat-textarea').count().catch(() => 0)) return page
    }
    return null
  }, 'Desktop Control UI', 120_000)
}

const root = await realpath(await mkdtemp(join(tmpdir(), 'opensquilla-profile-import-e2e-')))
let app = null
try {
  // A single detected CLI profile remains unselected, and skipping performs no import.
  const skipHome = join(root, 'skip-home')
  const skipSource = join(skipHome, '.opensquilla')
  const skipDesktopSource = join(root, 'skip-desktop-source')
  const skipUserData = join(root, 'skip-user-data')
  seedProfile(skipSource, SOURCE_IDENTITY, SOURCE_CHAT)
  seedProfile(skipDesktopSource, '# Synthetic alternate Desktop identity\n', 'alternate chat')
  const skipSourceBefore = await snapshotTree(skipSource)
  const skipDesktopSourceBefore = await snapshotTree(skipDesktopSource)
  app = await launchDesktop(skipUserData, skipHome, 18921)
  let page = await onboardingPage(app)
  await page.locator('[data-screen="5"].active').waitFor({ state: 'visible' })
  assert.equal(await page.locator('#migrationSource').inputValue(), '')
  assert.equal(await page.locator('#migrationSource option').count(), 2)
  assert.equal(await page.locator('#migrationPreview').isDisabled(), true)
  await app.evaluate(({ dialog }, selectedPath) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [selectedPath] })
  }, skipDesktopSource)
  await page.locator('#migrationSourceKind').selectOption('desktop-home')
  await page.locator('#migrationBrowse').click()
  await waitFor(async () => (
    await page.locator('#migrationSource option').count() === 3
  ), 'second explicitly browsed candidate')
  assert.equal(await page.locator('#migrationSource').inputValue(), skipDesktopSource)
  await page.locator('#migrationSource').selectOption('')
  assert.equal(await page.locator('#migrationPreview').isDisabled(), true)
  await page.locator('#migrationSkip').click()
  await page.locator('[data-screen="0"].active').waitFor({ state: 'visible' })
  assert.deepEqual(await snapshotTree(skipSource), skipSourceBefore)
  assert.deepEqual(await snapshotTree(skipDesktopSource), skipDesktopSourceBefore)
  assert.notEqual(
    await readFile(join(skipUserData, 'opensquilla', 'workspace', 'IDENTITY.md'), 'utf8').catch(() => ''),
    SOURCE_IDENTITY,
  )
  await app.close()
  app = null

  // A non-empty Desktop target is backed up and replaced as one profile; source stays read-only.
  const importHome = join(root, 'import-home')
  const source = join(importHome, '.opensquilla')
  const userData = join(root, 'import-user-data')
  const target = join(userData, 'opensquilla')
  seedProfile(source, SOURCE_IDENTITY, SOURCE_CHAT)
  seedProfile(target, TARGET_IDENTITY, 'synthetic previous Desktop chat')
  const sourceBefore = await snapshotTree(source)
  app = await launchDesktop(userData, importHome, 18922)
  page = await onboardingPage(app)
  await page.locator('[data-screen="5"].active').waitFor({ state: 'visible' })
  assert.equal(await page.locator('#migrationSource').inputValue(), '')
  await page.locator('#migrationSource').selectOption(source)
  await waitFor(async () => !(await page.locator('#migrationPreview').isDisabled()), 'explicit source selection')
  await page.locator('#migrationPreview').click()
  try {
    await waitFor(async () => !(await page.locator('#migrationImport').isDisabled()), 'whole-replace preview')
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      error: document.getElementById('error')?.textContent || '',
      summary: document.getElementById('migrationSummary')?.textContent || '',
      source: document.getElementById('migrationSource')?.value || '',
    }))
    throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`)
  }
  await app.evaluate(({ dialog }) => {
    dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
  })
  await page.locator('#migrationImport').click()
  try {
    await page.locator('#migrationDoneNote').waitFor({
      state: 'visible',
      timeout: PROFILE_IMPORT_APPLY_TIMEOUT_MS,
    })
  } catch (error) {
    const renderer = await page.evaluate(() => ({
      error: document.getElementById('error')?.textContent || '',
      statusVisible: !document.getElementById('migrationStatus')?.hidden,
      summaryVisible: !document.getElementById('migrationSummary')?.hidden,
    })).catch(() => ({ error: '', statusVisible: false, summaryVisible: false }))
    const pendingPhase = await readFile(
      join(userData, 'migration-provider-setup.json'),
      'utf8',
    ).then((raw) => JSON.parse(raw)?.phase || '').catch(() => '')
    const receiptCount = await readdir(join(target, 'migration', 'opensquilla'))
      .then((entries) => entries.length)
      .catch(() => 0)
    const backupCount = await readdir(userData)
      .then((entries) => entries.filter((name) => name.startsWith('opensquilla.backup.')).length)
      .catch(() => 0)
    const migrationResult = await readFile(
      join(userData, 'migration-last-result.json'),
      'utf8',
    ).then((raw) => {
      const value = JSON.parse(raw)
      return {
        ok: value?.ok === true,
        migrationApplied: value?.migrationApplied === true,
        restartOk: value?.restartOk === true,
        requiresProviderSetup: value?.requiresProviderSetup === true,
        detail: typeof value?.detail === 'string' ? value.detail : '',
      }
    }).catch(() => null)
    const diagnostics = {
      renderer,
      pendingPhase,
      receiptCount,
      backupCount,
      migrationResult,
      importedIdentityPresent: await readFile(
        join(target, 'workspace', 'IDENTITY.md'),
        'utf8',
      ).then((value) => value === SOURCE_IDENTITY).catch(() => false),
    }
    const reportDir = process.env.CI_REPORT_DIR
    if (reportDir) {
      await mkdir(reportDir, { recursive: true })
      await writeFile(
        join(reportDir, 'profile-import-timeout.json'),
        `${JSON.stringify(diagnostics, null, 2)}\n`,
        'utf8',
      )
    }
    throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`)
  }
  assert.match(await page.locator('#migrationDoneNote').innerText(), /Import complete/i)

  assert.deepEqual(await snapshotTree(source), sourceBefore, 'source bytes and permissions changed')
  assert.equal(await readFile(join(source, '.opensquilla-imported.json'), 'utf8').catch(() => null), null)
  assert.equal(await readFile(join(target, 'workspace', 'IDENTITY.md'), 'utf8'), SOURCE_IDENTITY)
  const importedChat = runPython(`
import sqlite3, sys
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as connection:
    print(connection.execute('SELECT body FROM synthetic_import_chat WHERE id = ?', ('session-1',)).fetchone()[0])
`, [join(target, 'state', 'sessions.db')])
  assert.equal(importedChat, SOURCE_CHAT)
  const backups = (await readdir(userData)).filter((name) => name.startsWith('opensquilla.backup.'))
  assert.equal(backups.length, 1)
  assert.equal(
    await readFile(join(userData, backups[0], 'workspace', 'IDENTITY.md'), 'utf8'),
    TARGET_IDENTITY,
  )
  await app.close()
  app = null

  // Settings import with a required key must release exclusive admission before
  // onboarding, preserve source config bytes, and retain the previous credential.
  const settingsHome = join(root, 'settings-home')
  const settingsSource = join(settingsHome, '.opensquilla')
  const settingsUserData = join(root, 'settings-user-data')
  const settingsTarget = join(settingsUserData, 'opensquilla')
  seedProfile(settingsSource, SOURCE_IDENTITY, SOURCE_CHAT)
  seedProfile(settingsTarget, TARGET_IDENTITY, 'synthetic previous settings chat')
  await writeProviderProfileConfig(settingsSource, {
    provider: 'openai',
    model: 'gpt-5.4-mini',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyEnv: 'OPENAI_API_KEY',
    searchProvider: 'brave',
    searchApiKeyEnv: 'BRAVE_API_KEY',
    routerEnabled: false,
    disableNetworkObservability: true,
  })
  const importedEnvBytes = Buffer.from(
    'OPENAI_API_KEY="synthetic-source-env-key"\r\nTRAILING_VALUE=keep\r\n\r\n',
  )
  await writeFile(join(settingsSource, '.env'), importedEnvBytes)
  await writeProviderProfileConfig(settingsTarget, {
    provider: 'openai',
    model: 'synthetic-old-target-model',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyEnv: 'OPENAI_API_KEY',
    routerEnabled: true,
    disableNetworkObservability: false,
  })
  const oldCredential = await seedDesktopCredential(settingsUserData, {
    provider: 'openai',
    model: 'synthetic-old-target-model',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyEnv: 'OPENAI_API_KEY',
    apiKey: 'synthetic-old-target-key',
  })
  app = await launchDesktop(settingsUserData, settingsHome, 18924)
  const settingsControl = await controlPage(app)
  const settingsPreview = await settingsControl.evaluate(async (sourcePath) => (
    await window.opensquillaDesktop.migrationSummary({ source: sourcePath })
  ), settingsSource)
  assert.equal(settingsPreview.ok, false, JSON.stringify(settingsPreview))
  assert.equal(typeof settingsPreview.previewId, 'string')
  assert.equal(
    settingsPreview.report.items.filter((item) => item.status === 'error').at(0)?.kind,
    'preflight/target',
  )
  await app.evaluate(({ dialog }) => {
    dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
  })
  await settingsControl.evaluate(({ previewId }) => {
    void window.opensquillaDesktop.migrationRun({ previewId, overwrite: true })
    return true
  }, { previewId: settingsPreview.previewId })

  const requiredKeyOnboarding = await onboardingPage(app)
  await requiredKeyOnboarding.locator('[data-screen="0"].active').waitFor({
    state: 'visible',
    timeout: 90_000,
  })
  await requiredKeyOnboarding.locator('[data-screen="0"].active .next-button').click()
  await requiredKeyOnboarding.locator('[data-screen="1"].active').waitFor({
    state: 'visible',
    timeout: 90_000,
  })
  assert.equal(await requiredKeyOnboarding.locator('#provider').inputValue(), 'openai')
  assert.equal(await requiredKeyOnboarding.locator('#model').inputValue(), 'gpt-5.4-mini')
  const importedConfigBeforeCredential = await readFile(join(settingsTarget, 'config.toml'))
  assert.match(importedConfigBeforeCredential.toString('utf8'), /search_provider = "brave"/)
  assert.match(importedConfigBeforeCredential.toString('utf8'), /confidence_threshold = 0\.77/)
  assert.match(
    importedConfigBeforeCredential.toString('utf8'),
    /disable_network_observability = true/,
  )
  await requiredKeyOnboarding.locator('#apiKey').fill('synthetic-new-imported-key')
  await requiredKeyOnboarding.locator('[data-screen="1"].active .next-button').click()
  await requiredKeyOnboarding.locator('[data-screen="4"].active').waitFor({ state: 'visible' })
  await requiredKeyOnboarding.locator('#finish').click()

  const adopted = await waitFor(async () => {
    const pending = await readFile(
      join(settingsUserData, 'migration-provider-setup.json'),
      'utf8',
    ).catch(() => null)
    if (pending !== null) return null
    const raw = await readFile(join(settingsUserData, 'desktop-credential.json'), 'utf8')
    const credential = JSON.parse(raw)
    return credential.configAuthority === 'profile' ? credential : null
  }, 'required-key imported credential adoption')
  assert.match(adopted.importTransactionId, /^[0-9a-f-]{36}$/i)
  assert.equal(adopted.model, 'gpt-5.4-mini')
  assert.equal(
    Buffer.from(adopted.encryptedApiKey, 'base64').toString('utf8'),
    'synthetic-new-imported-key',
  )
  assert.deepEqual(
    await readFile(join(settingsTarget, 'config.toml')),
    importedConfigBeforeCredential,
    'provider adoption rewrote imported config.toml',
  )
  assert.deepEqual(
    await readFile(join(settingsTarget, '.env')),
    importedEnvBytes,
    'provider adoption rewrote imported .env bytes',
  )
  const credentialBackup = join(
    settingsUserData,
    `desktop-credential.import-backup.${adopted.importTransactionId}.json`,
  )
  assert.equal(await readFile(credentialBackup, 'utf8'), oldCredential)
  if (process.platform !== 'win32') {
    assert.equal((await lstat(credentialBackup)).mode & 0o777, 0o600)
  }
  await app.close()
  app = null

  // A selected recovery H can use the app, but it cannot import another profile.
  const recoveryHome = join(root, 'recovery-home')
  const recoveryUserData = join(root, 'recovery-user-data')
  const recoveryId = '12345678-1234-4234-8234-123456789abc'
  await mkdir(join(recoveryUserData, 'recovery-profiles', recoveryId, 'opensquilla'), { recursive: true })
  await writeFile(join(recoveryUserData, 'desktop-profile-context.json'), JSON.stringify({
    schema_version: 1,
    active_profile_kind: 'recovery',
    active_recovery_id: recoveryId,
    attention_acknowledgement: null,
    updated_at: new Date().toISOString(),
  }, null, 2))
  app = await launchDesktop(recoveryUserData, recoveryHome, 18923)
  page = await recoveryPage(app)
  const rejected = await page.evaluate(() => window.opensquillaDesktop.migrationSummary())
  assert.equal(rejected.ok, false)
  assert.match(rejected.raw, /primary profile/i)

  console.log(JSON.stringify({
    explicitSelectionAndSkip: true,
    multipleCandidates: true,
    wholeReplacement: true,
    sourceUnchanged: true,
    identityAndChatImported: true,
    settingsRequiredKeyCompleted: true,
    importedConfigPreserved: true,
    previousCredentialBackedUp: true,
    recoveryProfileRejected: true,
  }, null, 2))
} finally {
  if (app) await app.close().catch(() => {})
  await rm(root, { recursive: true, force: true })
}
