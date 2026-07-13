import { strict as assert } from 'node:assert'
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
const RECOVERY_ID = '21234567-89ab-4cde-8fab-0123456789ab'
const observedRendererPages = new WeakSet()
const rendererDiagnostics = []

const LOCALES = {
  en: {
    title: 'Starting OpenSquilla',
    bootAria: 'OpenSquilla startup',
    recoveryTitle: 'Your primary profile needs recovery',
    continueRecovery: 'Continue recovery profile',
    createRecovery: 'Create recovery profile',
    retryPrimary: 'Retry primary profile',
  },
  'zh-Hans': {
    title: '正在启动 OpenSquilla',
    bootAria: 'OpenSquilla 启动',
    recoveryTitle: '主配置需要恢复',
    continueRecovery: '继续恢复配置',
    createRecovery: '创建恢复配置',
    retryPrimary: '重试主配置',
  },
  ja: {
    title: 'OpenSquilla を起動しています',
    bootAria: 'OpenSquilla の起動',
    recoveryTitle: 'プライマリプロファイルの復旧が必要です',
    continueRecovery: '復旧プロファイルを続行',
    createRecovery: '復旧プロファイルを作成',
    retryPrimary: 'プライマリを再試行',
  },
  fr: {
    title: "Démarrage d'OpenSquilla",
    bootAria: "Démarrage d'OpenSquilla",
    recoveryTitle: 'Le profil principal doit être récupéré',
    continueRecovery: 'Continuer ce profil',
    createRecovery: 'Créer un profil de récupération',
    retryPrimary: 'Réessayer le profil principal',
  },
  de: {
    title: 'OpenSquilla wird gestartet',
    bootAria: 'OpenSquilla-Start',
    recoveryTitle: 'Das Hauptprofil muss wiederhergestellt werden',
    continueRecovery: 'Profil fortsetzen',
    createRecovery: 'Wiederherstellungsprofil erstellen',
    retryPrimary: 'Hauptprofil erneut prüfen',
  },
  es: {
    title: 'Iniciando OpenSquilla',
    bootAria: 'Inicio de OpenSquilla',
    recoveryTitle: 'El perfil principal necesita recuperación',
    continueRecovery: 'Continuar perfil de recuperación',
    createRecovery: 'Crear perfil de recuperación',
    retryPrimary: 'Reintentar perfil principal',
  },
}

const BLOCKING_CASES = {
  en: { fixture: 'missing-workspace', stableCode: 'effective_workspace_missing' },
  'zh-Hans': { fixture: 'corrupt-config', stableCode: 'config_invalid' },
  ja: { fixture: 'future-config', stableCode: 'config_schema_too_new' },
  fr: {
    fixture: 'future-context',
    stableCode: 'desktop_profile_context_schema_too_new',
  },
  de: { fixture: 'unfinished-transaction', stableCode: 'transaction_incomplete' },
  es: { fixture: 'unsafe-database', stableCode: 'state_database_invalid' },
}

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

function launchEnvironment(isolatedHome) {
  const inherited = { ...process.env }
  for (const name of Object.keys(inherited)) {
    if (name === 'DISPLAY' || name === 'XAUTHORITY') continue
    const upperName = name.toUpperCase()
    if (
      upperName.startsWith('OPENSQUILLA_')
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
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: '18897',
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_OPENROUTER_LIVE_PRICING: '0',
    OPENSQUILLA_GATEWAY_WORKSPACE_DIR: '',
    OPENSQUILLA_WORKSPACE_DIR: '',
    OPENSQUILLA_GATEWAY_STATE_DIR: '',
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

async function createFixture(locale, blockingCase) {
  const root = await realpath(await mkdtemp(join(tmpdir(), `opensquilla-recovery-a11y-${locale}-`)))
  const userData = join(root, 'user-data')
  const isolatedHome = join(root, 'home')
  const primaryHome = join(userData, 'opensquilla')
  const primaryWorkspace = join(primaryHome, 'workspace')
  const primaryState = join(primaryHome, 'state')
  const missingWorkspace = join(root, 'missing-external-workspace')
  const recoveryHome = join(userData, 'recovery-profiles', RECOVERY_ID, 'opensquilla')

  await mkdir(primaryWorkspace, { recursive: true })
  await mkdir(primaryState, { recursive: true })
  await mkdir(recoveryHome, { recursive: true })
  await mkdir(isolatedHome, { recursive: true })
  for (const [name, text] of [
    ['USER.md', 'synthetic accessibility user\n'],
    ['SOUL.md', 'synthetic accessibility soul\n'],
    ['IDENTITY.md', 'synthetic accessibility identity\n'],
    ['MEMORY.md', 'synthetic accessibility memory\n'],
  ]) {
    await writeFile(join(primaryWorkspace, name), text, 'utf8')
  }
  await writeFile(join(primaryState, 'primary-must-not-change.txt'), 'unchanged\n', 'utf8')
  const validConfig = [
    `state_dir = ${JSON.stringify(primaryState)}`,
    '',
  ].join('\n')
  let config = validConfig
  if (blockingCase.fixture === 'missing-workspace') {
    config = [
      `state_dir = ${JSON.stringify(primaryState)}`,
      `workspace_dir = ${JSON.stringify(missingWorkspace)}`,
      '',
    ].join('\n')
  } else if (blockingCase.fixture === 'corrupt-config') {
    config = 'workspace_dir = "unterminated\n'
  } else if (blockingCase.fixture === 'future-config') {
    config = 'config_version = 999\n'
  }
  await writeFile(join(primaryHome, 'config.toml'), config, 'utf8')
  if (blockingCase.fixture === 'unsafe-database') {
    await writeFile(join(primaryState, 'sessions.db'), 'not a sqlite database', 'utf8')
  }
  let journalPath = null
  let journalBytes = null
  if (blockingCase.fixture === 'unfinished-transaction') {
    journalPath = join(userData, '.opensquilla.profile-replace.json')
    journalBytes = '{"schema_version":1,"phase":"prepared"}\n'
    await writeFile(journalPath, journalBytes, 'utf8')
  }
  await writeFile(join(userData, 'desktop-locale'), locale, 'utf8')
  await writeFile(
    join(userData, 'desktop-profile-context.json'),
    `${JSON.stringify({
      schema_version: blockingCase.fixture === 'future-context' ? 999 : 1,
      active_profile_kind: 'primary',
      active_recovery_id: null,
      attention_acknowledgement: null,
      updated_at: '2026-07-11T00:00:00.000Z',
    }, null, 2)}\n`,
    'utf8',
  )

  return {
    root,
    userData,
    isolatedHome,
    primaryHome,
    recoveryHome,
    journalPath,
    journalBytes,
    primaryBefore: await snapshotTree(primaryHome),
  }
}

async function launchFixture(fixture) {
  return await electron.launch({
    args: ['--use-mock-keychain', `--user-data-dir=${fixture.userData}`, packageRoot],
    env: launchEnvironment(fixture.isolatedHome),
  })
}

async function recoveryPage(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      if (await page.locator('#recoveryPanel.visible').count().catch(() => 0)) return page
    }
    return null
  }, 'localized recovery page')
}

function observeRenderer(page) {
  if (observedRendererPages.has(page)) return
  observedRendererPages.add(page)
  page.on('console', (message) => {
    rendererDiagnostics.push({
      type: `console:${message.type()}`,
      text: message.text().slice(0, 1_000),
    })
  })
  page.on('pageerror', (error) => {
    rendererDiagnostics.push({
      type: 'pageerror',
      text: String(error?.message || error).slice(0, 1_000),
    })
  })
}

async function onboardingPage(app) {
  try {
    return await waitFor(async () => {
      for (const page of app.windows()) {
        if (page.isClosed()) continue
        observeRenderer(page)
        await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
        if (await page.locator('#setup-form').count().catch(() => 0)) return page
      }
      return null
    }, 'selected recovery profile onboarding')
  } catch (error) {
    const windows = await Promise.all(app.windows().map(async (page) => ({
      url: page.url(),
      title: await page.title().catch(() => ''),
      body: await page.locator('body').innerText().catch(() => '').then((value) => (
        value.slice(0, 1_500)
      )),
    })))
    throw new Error(
      `${error.message}; windows=${JSON.stringify(windows)}; `
      + `renderer=${JSON.stringify(rendererDiagnostics.slice(-30))}`,
    )
  }
}

async function tabTo(page, targetId, maximumTabs = 30) {
  for (let index = 0; index <= maximumTabs; index += 1) {
    const activeId = await page.evaluate(() => document.activeElement?.id || '')
    if (activeId === targetId) return
    await page.keyboard.press('Tab')
  }
  throw new Error(`Keyboard focus did not reach #${targetId}`)
}

function durationSeconds(value) {
  if (value.endsWith('ms')) return Number.parseFloat(value) / 1_000
  if (value.endsWith('s')) return Number.parseFloat(value)
  return Number.NaN
}

async function assertReducedMotion(page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const result = await page.evaluate(() => {
    const bodyWasErrored = document.body.classList.contains('errored')
    const blockedStyle = getComputedStyle(
      document.querySelector('.status-line'),
      '::before',
    )
    const blockedAnimationName = blockedStyle.animationName
    document.body.classList.remove('errored')
    const reducedStyle = getComputedStyle(
      document.querySelector('.status-line'),
      '::before',
    )
    const snapshot = {
      mediaMatches: matchMedia('(prefers-reduced-motion: reduce)').matches,
      blockedAnimationName,
      animationName: reducedStyle.animationName,
      animationDuration: reducedStyle.animationDuration,
      animationIterationCount: reducedStyle.animationIterationCount,
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    }
    if (bodyWasErrored) document.body.classList.add('errored')
    return snapshot
  })
  assert.equal(result.mediaMatches, true)
  assert.equal(result.blockedAnimationName, 'none')
  assert.equal(result.animationName, 'progress')
  assert(durationSeconds(result.animationDuration) <= 0.00001, result.animationDuration)
  assert.equal(result.animationIterationCount, '1')
  assert.equal(result.scrollBehavior, 'auto')
}

async function assertLocalizedRecovery(page, locale, expected) {
  await waitFor(
    async () => await page.locator('html').getAttribute('lang') === locale,
    `${locale} locale application`,
  )
  assert.equal(await page.title(), expected.title)
  assert.equal(await page.locator('main.boot').getAttribute('aria-label'), expected.bootAria)
  assert.equal(await page.locator('#recoveryTitle').innerText(), expected.recoveryTitle)
  assert.equal(await page.locator('#continueRecovery').innerText(), expected.continueRecovery)
  assert.equal(await page.locator('#createRecovery').innerText(), expected.createRecovery)
  assert.equal(await page.locator('#retryPrimary').innerText(), expected.retryPrimary)
  assert.equal(await page.locator('#recoveryPanel').getAttribute('role'), 'region')
  assert.equal(await page.locator('#recoveryPanel').getAttribute('aria-labelledby'), 'recoveryTitle')
  assert.equal(
    await page.getByRole('region', { name: expected.recoveryTitle }).count(),
    1,
  )
  assert.equal(await page.locator('#recoveryStatus').getAttribute('role'), 'status')
  assert.equal(await page.locator('#recoveryStatus').getAttribute('aria-live'), 'polite')
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'recoveryTitle')
}

const completedLocales = []
const completedBlockingCodes = []
for (const [locale, expected] of Object.entries(LOCALES)) {
  const blockingCase = BLOCKING_CASES[locale]
  assert(blockingCase, `missing blocking fixture for ${locale}`)
  const fixture = await createFixture(locale, blockingCase)
  let app
  try {
    app = await launchFixture(fixture)
    const page = await recoveryPage(app)
    assert.deepEqual(
      await readdir(fixture.recoveryHome),
      [],
      'read-only recovery inspection must not seed a third blank workspace',
    )
    assert.equal(await page.locator('#recoveryCode').innerText(), blockingCase.stableCode)
    await assertLocalizedRecovery(page, locale, expected)

    if (locale === 'en') await assertReducedMotion(page)

    const existingProfiles = await page.locator('#recoveryProfiles option').evaluateAll((options) => (
      options.map((option) => ({ value: option.value, label: option.textContent || '' }))
    ))
    assert(existingProfiles.some((option) => (
      option.value === RECOVERY_ID && option.label.includes(fixture.recoveryHome)
    )))
    const gatewayBeforeChoice = await page.evaluate(() => (
      window.opensquillaDesktop.getGatewayStatus()
    ))
    assert.equal(gatewayBeforeChoice.status, 'stopped')
    assert.equal(gatewayBeforeChoice.owned, false)

    // The entire fallback selection is keyboard-only. Starting from the
    // programmatically focused recovery heading, Tab reaches the existing
    // profile selector, then Enter activates Continue without a pointer click.
    await tabTo(page, 'recoveryProfiles')
    assert.equal(await page.locator('#recoveryProfiles').inputValue(), RECOVERY_ID)
    await page.keyboard.press('Home')
    assert.equal(await page.locator('#recoveryProfiles').inputValue(), RECOVERY_ID)
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'continueRecovery')
    await page.keyboard.press('Enter')

    const onboarding = await onboardingPage(app)
    const gatewayAfterChoice = await onboarding.evaluate(() => (
      window.opensquillaDesktop.getGatewayStatus()
    ))
    assert.equal(gatewayAfterChoice.status, 'stopped')
    assert.equal(gatewayAfterChoice.owned, false)
    const context = JSON.parse(
      await readFile(join(fixture.userData, 'desktop-profile-context.json'), 'utf8'),
    )
    assert.equal(context.active_profile_kind, 'recovery')
    assert.equal(context.active_recovery_id, RECOVERY_ID)
    assert.deepEqual(await snapshotTree(fixture.primaryHome), fixture.primaryBefore)
    if (fixture.journalPath) {
      assert.equal(await readFile(fixture.journalPath, 'utf8'), fixture.journalBytes)
    }
    completedLocales.push(locale)
    completedBlockingCodes.push(blockingCase.stableCode)
  } finally {
    await app?.close().catch(() => {})
    await rm(fixture.root, { recursive: true, force: true }).catch(() => {})
  }
}

assert.deepEqual(completedLocales, Object.keys(LOCALES))
assert.deepEqual(
  completedBlockingCodes,
  Object.values(BLOCKING_CASES).map((item) => item.stableCode),
)
console.log(JSON.stringify({
  ok: true,
  locales: completedLocales,
  blockingCodes: completedBlockingCodes,
  keyboardContinueVerified: true,
  primaryBytesUnchanged: true,
  reducedMotionVerified: true,
}))
