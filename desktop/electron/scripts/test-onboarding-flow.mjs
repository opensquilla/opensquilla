import { strict as assert } from 'node:assert'
import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(scriptDir, '..')
const repoRoot = resolve(packageRoot, '../..')

async function waitFor(check, label, timeoutMs = 60_000) {
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
  const suffix = lastError ? ` Last error: ${lastError.message || lastError}` : ''
  throw new Error(`Timed out waiting for ${label}.${suffix}`)
}

async function setupWindow(app) {
  return await waitFor(async () => {
    for (const page of app.windows()) {
      if (page.isClosed()) continue
      await page.waitForLoadState('domcontentloaded', { timeout: 5_000 }).catch(() => {})
      const hasSetupForm = await page.locator('#setup-form').count().catch(() => 0)
      if (hasSetupForm > 0) return page
    }
    return null
  }, 'desktop onboarding window')
}

const userDataRoot = await mkdtemp(join(tmpdir(), 'opensquilla-electron-onboarding-test-'))
const userDataDir = join(userDataRoot, 'chromium-user-data')
const isolatedHome = join(userDataRoot, 'home')
await mkdir(isolatedHome, { recursive: true })
const app = await electron.launch({
  args: [
    '--use-mock-keychain',
    `--user-data-dir=${userDataDir}`,
    packageRoot,
  ],
  env: {
    ...process.env,
    HOME: isolatedHome,
    USERPROFILE: isolatedHome,
    OPENSQUILLA_DESKTOP_REPO_ROOT: repoRoot,
    OPENSQUILLA_DESKTOP_SECRET_STORAGE: 'plain',
    OPENSQUILLA_DESKTOP_GATEWAY_PORT: '18897',
    OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE: '1',
    OPENSQUILLA_DESKTOP_MOCK_UPDATE_VERSION: '',
    LANG: 'en_US.UTF-8',
    LC_ALL: 'en_US.UTF-8',
  },
})

try {
  const page = await setupWindow(app)

  await page.locator('#onboardingLocale').selectOption('zh-Hans')
  assert.equal(await page.evaluate(() => document.documentElement.lang), 'zh-Hans')
  assert.equal(await page.locator('[data-screen="0"] h2').innerText(), '选择设置深度')
  assert.equal(await page.title(), '设置 OpenSquilla')
  assert.doesNotMatch(await page.locator('[data-setup-mode="advanced"]').innerText(), /Smart Router mode/)
  await page.locator('[data-setup-mode="advanced"]').click()

  await page.locator('[data-screen="0"].active .next-button').click()
  await page.locator('[data-screen="1"].active').waitFor({ state: 'visible', timeout: 10_000 })
  assert.equal(await page.locator('[data-step-label="2"]').count(), 1, 'advanced setup should expose the routing-mode progress step')

  assert.equal(await page.locator('#provider').inputValue(), 'tokenrhythm')
  assert.equal(await page.locator('#baseUrl').inputValue(), 'https://tokenrhythm.studio/v1')
  assert.equal(await page.locator('#model').inputValue(), 'deepseek-v4-pro')
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'direct')
  assert.equal(await page.locator('#routerMode').inputValue(), 'disabled')

  const tokenRhythmFeature = page.locator('[data-provider-feature="tokenrhythm"]')
  assert.equal(await tokenRhythmFeature.count(), 1)
  assert.equal(await tokenRhythmFeature.locator('[data-tokenrhythm-title]').innerText(), '推荐使用 TokenRhythm')
  assert.equal(
    await tokenRhythmFeature.locator('[data-tokenrhythm-value]').innerText(),
    '一个 API Key，统一接入 DeepSeek、GLM、MiniMax、Kimi 等主流模型。',
  )
  assert.equal(
    await tokenRhythmFeature.locator('[data-tokenrhythm-registration]').innerText(),
    '免费注册，立即获取 API Key。',
  )
  const tokenRhythmCta = tokenRhythmFeature.locator('#tokenrhythmRegister')
  assert.equal(await tokenRhythmCta.innerText(), '免费获取 API Key')
  assert.equal(await tokenRhythmCta.getAttribute('href'), 'https://tokenrhythm.studio/register')
  assert.equal(await tokenRhythmCta.getAttribute('target'), '_blank')
  assert.equal(await tokenRhythmCta.getAttribute('rel'), 'noopener noreferrer')
  assert.equal(
    await tokenRhythmCta.getAttribute('aria-label'),
    '免费获取 TokenRhythm API Key（在外部浏览器中打开）',
  )
  assert.equal(await tokenRhythmFeature.locator('img, svg, canvas').count(), 0)
  assert.equal(await tokenRhythmFeature.locator('[data-provider="tokenrhythm"]').getAttribute('aria-pressed'), 'true')

  const providerMoreToggle = page.locator('#providerMoreToggle')
  const providerMorePanel = page.locator('#providerMorePanel')
  assert.equal(await providerMoreToggle.getAttribute('aria-expanded'), 'false')
  assert.equal(await providerMoreToggle.getAttribute('aria-controls'), 'providerMorePanel')
  assert.equal(await providerMorePanel.isHidden(), true)

  await page.locator('#onboardingLocale').selectOption('en')
  assert.equal(await page.evaluate(() => document.documentElement.lang), 'en')
  assert.equal(await page.locator('[data-screen="1"] h2').innerText(), 'Connect a provider')
  assert.equal(await page.locator('#provider').inputValue(), 'tokenrhythm', 'locale changes should preserve the selected provider')
  assert.equal(await tokenRhythmFeature.locator('[data-tokenrhythm-title]').innerText(), 'Recommended: TokenRhythm')
  assert.equal(
    await tokenRhythmFeature.locator('[data-tokenrhythm-value]').innerText(),
    'One API key connects DeepSeek, GLM, MiniMax, Kimi, and other leading models.',
  )
  assert.equal(
    await tokenRhythmFeature.locator('[data-tokenrhythm-registration]').innerText(),
    'Register free and get an API key.',
  )
  assert.equal(await tokenRhythmCta.innerText(), 'Get a free API key')
  assert.equal(
    await tokenRhythmCta.getAttribute('aria-label'),
    'Get a free TokenRhythm API key (opens in external browser)',
  )

  await providerMoreToggle.click()
  assert.equal(await providerMoreToggle.getAttribute('aria-expanded'), 'true')
  assert.equal(await providerMorePanel.isVisible(), true)
  const openRouterProvider = page.locator('#providerGrid [data-provider="openrouter"]')
  await openRouterProvider.click()
  assert.equal(await page.locator('#provider').inputValue(), 'openrouter')
  assert.equal(await openRouterProvider.getAttribute('aria-pressed'), 'true')
  assert.equal(await tokenRhythmFeature.locator('[data-provider="tokenrhythm"]').getAttribute('aria-pressed'), 'false')
  await page.locator('#onboardingLocale').selectOption('zh-Hans')
  assert.equal(await page.locator('#provider').inputValue(), 'openrouter', 'locale changes should preserve another provider selection')
  await page.locator('#onboardingLocale').selectOption('en')
  assert.equal(await page.locator('#provider').inputValue(), 'openrouter')
  await tokenRhythmFeature.locator('[data-provider="tokenrhythm"]').click()
  assert.equal(await page.locator('#provider').inputValue(), 'tokenrhythm', 'TokenRhythm should remain re-selectable')
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'direct')
  assert.equal(await tokenRhythmFeature.locator('[data-provider="tokenrhythm"]').getAttribute('aria-pressed'), 'true')
  await openRouterProvider.click()
  assert.equal(await page.locator('#provider').inputValue(), 'openrouter')
  const enProviderHint = await page.locator('#providerHint').innerText()
  assert.doesNotMatch(enProviderHint, /saved locally/)
  assert.doesNotMatch(enProviderHint, /OPENROUTER_API_KEY/)
  assert.doesNotMatch(enProviderHint, /supplied to the local runtime/)

  await page.locator('#apiKey').fill('test-openrouter-key')
  await page.locator('[data-screen="1"].active .next-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 10_000 })
  assert.equal(await page.locator('[data-screen="2"] h2').innerText(), 'Choose routing mode')
  assert.equal(await page.locator('[data-model-routing-mode="squilla_router"]').isEnabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="direct"]').isEnabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="llm_ensemble"]').isEnabled(), true)
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'squilla_router')
  await page.locator('[data-screen="2"].active .next-button').click()
  await page.locator('[data-screen="3"].active').waitFor({ state: 'visible', timeout: 10_000 })
  assert.equal(await page.locator('[data-screen="3"] h2').innerText(), 'Review tier models')
  await page.locator('[data-screen="3"].active .back-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('[data-model-routing-mode="llm_ensemble"]').click()
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'llm_ensemble')
  await page.locator('[data-screen="2"].active .next-button').click()
  await page.locator('[data-screen="4"].active').waitFor({ state: 'visible', timeout: 10_000 })
  await page.locator('[data-screen="4"].active .back-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('[data-screen="2"].active .back-button').click()
  await page.locator('[data-screen="1"].active').waitFor({ state: 'visible', timeout: 5_000 })

  await page.locator('#providerGrid [data-provider="ollama"]').click()
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'direct')
  assert.equal(await page.locator('#routerMode').inputValue(), 'disabled')
  assert.equal(await page.locator('#model').inputValue(), '', 'direct-only providers without a default model should not inherit the previous provider model')
  assert.equal(await page.locator('#endpointToggle').getAttribute('aria-expanded'), 'true', 'direct-only providers that need a model should open the endpoint panel')
  await page.locator('[data-screen="1"].active .next-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  assert.equal(await page.locator('[data-model-routing-mode="squilla_router"]').isDisabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="direct"]').isEnabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="llm_ensemble"]').isDisabled(), true)
  assert.equal(await page.locator('[data-step-label="3"]').isVisible(), false, 'route-excluded tier step should be hidden from the progress rail')
  await page.locator('[data-screen="2"].active .next-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  assert.match(await page.locator('#error').innerText(), /Direct model is required/)
  await page.locator('[data-screen="2"].active .back-button').click()
  await page.locator('[data-screen="1"].active').waitFor({ state: 'visible', timeout: 5_000 })

  await page.locator('#providerGrid [data-provider="openai"]').click()

  assert.equal(await page.locator('#provider').inputValue(), 'openai')
  assert.equal(await page.locator('#baseUrl').inputValue(), 'https://api.openai.com/v1')
  assert.equal(await page.locator('#model').inputValue(), 'gpt-5.4-mini')
  await page.locator('#providerGrid [data-provider="openai"].active').waitFor({ state: 'visible', timeout: 5_000 })
  const openAiHint = await page.locator('#providerHint').innerText()
  assert.match(openAiHint, /OpenAI-only tier profile/)
  assert.doesNotMatch(openAiHint, /OPENAI_API_KEY/)
  await page.locator('#apiKey').fill('test-openai-key')
  await page.locator('[data-screen="1"].active .next-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 10_000 })
  assert.equal(await page.locator('#modelRoutingMode').inputValue(), 'squilla_router')
  assert.equal(await page.locator('[data-model-routing-mode="squilla_router"]').isEnabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="direct"]').isEnabled(), true)
  assert.equal(await page.locator('[data-model-routing-mode="llm_ensemble"]').isDisabled(), true)
  await page.locator('[data-screen="2"].active .next-button').click()
  await page.locator('[data-screen="3"].active').waitFor({ state: 'visible', timeout: 10_000 })
  assert.match(await page.locator('[data-screen="3"] .eyebrow').innerText(), /step 04/i)
  assert.equal(await page.locator('[data-screen="3"] h2').innerText(), 'Review tier models')

  await page.locator('[data-screen="3"].active .back-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('[data-screen="2"].active .back-button').click()
  await page.locator('[data-screen="1"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('#providerGrid [data-provider="openrouter"]').click()
  await page.locator('#apiKey').fill('test-openrouter-key')
  await page.locator('[data-screen="1"].active .next-button').click()
  await page.locator('[data-screen="2"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('[data-model-routing-mode="llm_ensemble"]').click()
  await page.locator('[data-screen="2"].active .next-button').click()
  await page.locator('[data-screen="4"].active').waitFor({ state: 'visible', timeout: 5_000 })
  await page.locator('#finish').click()
  await waitFor(async () => {
    const credential = JSON.parse(await readFile(join(userDataDir, 'desktop-credential.json'), 'utf8'))
    return credential.modelRoutingMode === 'llm_ensemble' ? credential : null
  }, 'saved ensemble credential')
  const credential = JSON.parse(await readFile(join(userDataDir, 'desktop-credential.json'), 'utf8'))
  const config = await readFile(join(userDataDir, 'opensquilla', 'config.toml'), 'utf8')
  assert.equal(credential.provider, 'openrouter')
  assert.equal(credential.modelRoutingMode, 'llm_ensemble')
  assert.equal(credential.routerMode, 'recommended')
  assert.match(config, /\[squilla_router\]\nenabled = true/)
  assert.match(config, /\[llm_ensemble\]\nenabled = true\nselection_mode = "static_openrouter_b5"/)

  console.log(JSON.stringify({
    ok: true,
    provider: credential.provider,
    modelRoutingMode: credential.modelRoutingMode,
    routerMode: credential.routerMode,
    model: credential.model,
  }, null, 2))
} finally {
  await app.close().catch(() => {})
  await rm(userDataRoot, { recursive: true, force: true }).catch(() => {})
}
