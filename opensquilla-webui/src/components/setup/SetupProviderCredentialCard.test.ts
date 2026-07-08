// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupProviderCredentialCard from './SetupProviderCredentialCard.vue'

function panel(overrides: Record<string, unknown> = {}) {
  return {
    providerLabel: 'DeepSeek',
    providerSelected: true,
    available: true,
    source: 'env',
    envKey: 'DEEPSEEK_API_KEY',
    masked: 'sk-••••7890',
    revealAllowed: true,
    revealed: '',
    revealError: '',
    replacing: false,
    apiKeyValue: '',
    apiKeyEnvValue: 'DEEPSEEK_API_KEY',
    connection: { phase: 'unverified' },
    ...overrides,
  }
}

async function mountCard(props: Record<string, unknown> = {}, listeners: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupProviderCredentialCard, { panel: panel(props), ...listeners })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  // The verdict keys land in the locale JSONs via the i18n merge step; inject
  // them here so assertions exercise interpolation instead of raw key names.
  i18n.global.mergeLocaleMessage('en', {
    setup: { provider: { verdictModels: '{count} models · e.g. {samples}', verdictSampleJoiner: ', ' } },
  })
  i18n.global.mergeLocaleMessage('zh-Hans', {
    setup: { provider: { verdictModels: '{count} 个模型 · 例如 {samples}', verdictSampleJoiner: '、' } },
  })
  document.body.innerHTML = ''
})

function discoveredModel(id: string) {
  return {
    id,
    name: id,
    contextWindow: 128000,
    maxOutputTokens: 8192,
    capabilities: ['chat'],
    pricing: null,
    capabilitySource: 'provider',
  }
}

function verifiedConnection(overrides: Record<string, unknown> = {}) {
  return {
    phase: 'verified',
    failureKind: '',
    detail: '',
    latencyMs: 412,
    models: [
      discoveredModel('test-vendor/alpha'),
      discoveredModel('test-vendor/beta'),
      discoveredModel('test-vendor/gamma'),
      discoveredModel('test-vendor/delta'),
    ],
    modelSource: 'live',
    discoverError: '',
    ...overrides,
  }
}

describe('SetupProviderCredentialCard', () => {
  it('keeps credential controls in tablet layout until phone widths', () => {
    const source = readFileSync('src/components/setup/SetupProviderCredentialCard.vue', 'utf8')

    expect(source).toContain('@media (max-width: 520px)')
    expect(source).not.toContain('@media (max-width: 720px)')
    expect(source).toContain('flex-wrap: wrap;')
    expect(source).toContain('width: auto;')
  })

  it('shows env-connected state without rendering env input while advanced details are closed', async () => {
    const { app, el } = await mountCard()

    expect(el.textContent).toContain('DeepSeek credential')
    expect(el.textContent).toContain('Connected')
    expect(el.textContent).toContain('Current source: environment variable DEEPSEEK_API_KEY')
    expect(el.querySelector('input[name="setup_provider_api_key_env"]')).toBeNull()

    app.unmount()
  })

  it('shows the reveal button only when reveal is allowed and a masked credential exists', async () => {
    const visible = await mountCard()
    expect(visible.el.querySelector('.setup-provider-credential__input-action[aria-label="View"]')).toBeTruthy()
    expect(Array.from(visible.el.querySelectorAll('button')).some(btn => (btn.textContent || '').includes('View'))).toBe(false)
    visible.app.unmount()

    const hidden = await mountCard({ revealAllowed: false })
    expect(hidden.el.querySelector('.setup-provider-credential__input-action[aria-label="View"]')).toBeNull()
    hidden.app.unmount()
  })

  it('shows the public-session hint when a masked credential exists but reveal is not allowed', async () => {
    const { app, el } = await mountCard({ revealAllowed: false })

    expect(el.textContent).toContain('Current session can replace this credential but cannot view its secret.')

    app.unmount()
  })

  it('does not show the reveal button when no masked credential exists', async () => {
    const { app, el } = await mountCard({ masked: '', revealAllowed: true })

    expect(el.querySelector('.setup-provider-credential__input-action[aria-label="View"]')).toBeNull()

    app.unmount()
  })

  it('keeps reveal and replace controls attached to the API key input', async () => {
    const { app, el } = await mountCard()

    const fieldRow = el.querySelector('.setup-provider-credential__field-row')
    const inputShell = fieldRow?.querySelector('.setup-provider-credential__input-shell')
    expect(inputShell?.querySelector('input[name="setup_provider_api_key_display"]')).toBeTruthy()
    expect(inputShell?.querySelector('.setup-provider-credential__input-action[aria-label="View"]')).toBeTruthy()
    expect(fieldRow?.querySelector('.setup-provider-credential__replace')?.textContent).toContain('Replace key')
    expect(el.querySelector('.setup-provider-credential__actions')).toBeNull()

    app.unmount()
  })

  it('emits updateField while replacing and toggles the local password visibility control', async () => {
    const onUpdateField = vi.fn()
    const { app, el } = await mountCard({ replacing: true, apiKeyValue: 'sk-new' }, { onUpdateField })

    const input = el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')
    expect(input?.type).toBe('password')

    input!.value = 'sk-next'
    input!.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    expect(onUpdateField).toHaveBeenCalledWith('api_key', 'sk-next')

    const toggle = Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
      .find(btn => btn.getAttribute('aria-label') === 'Show API key')
    toggle?.click()
    await nextTick()

    expect(el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')?.type).toBe('text')

    app.unmount()
  })

  it('renders the advanced env input on demand and emits api_key_env updates', async () => {
    const onUpdateField = vi.fn()
    const { app, el } = await mountCard({}, { onUpdateField })

    const summary = Array.from(el.querySelectorAll('summary'))
      .find(node => (node.textContent || '').includes('Advanced'))
    ;(summary as HTMLElement | undefined)?.click()
    await nextTick()

    const envInput = el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key_env"]')
    expect(envInput).toBeTruthy()

    envInput!.value = 'ALT_DEEPSEEK_KEY'
    envInput!.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    expect(onUpdateField).toHaveBeenCalledWith('api_key_env', 'ALT_DEEPSEEK_KEY')

    app.unmount()
  })
})

describe('SetupProviderCredentialCard — connection verdict line', () => {
  it('shows latency, live model count, and up to 3 sample ids when verified', async () => {
    const { app, el } = await mountCard({ connection: verifiedConnection() })

    const verdict = el.querySelector('.setup-connection__verdict')
    expect(verdict).toBeTruthy()
    expect(verdict?.getAttribute('aria-live')).toBe('polite')
    expect(verdict?.textContent).toContain('412ms')
    expect(verdict?.textContent).toContain('4 models')
    expect(verdict?.textContent).toContain('e.g. test-vendor/alpha, test-vendor/beta, test-vendor/gamma')
    expect(verdict?.textContent).not.toContain('test-vendor/delta')

    app.unmount()
  })

  it('joins sample ids with 、 for Chinese locales', async () => {
    i18n.global.locale.value = 'zh-Hans'
    const { app, el } = await mountCard({ connection: verifiedConnection() })

    expect(el.querySelector('.setup-connection__verdict')?.textContent)
      .toContain('test-vendor/alpha、test-vendor/beta、test-vendor/gamma')

    app.unmount()
  })

  it('omits the model summary when discovery returned nothing live', async () => {
    const { app, el } = await mountCard({
      connection: verifiedConnection({ models: [], modelSource: 'none' }),
    })

    const verdict = el.querySelector('.setup-connection__verdict')
    expect(verdict?.textContent).toContain('412ms')
    expect(verdict?.textContent).not.toContain('models')

    app.unmount()
  })

  it('keeps the verdict line empty when latency is unknown and nothing was discovered', async () => {
    const { app, el } = await mountCard({
      connection: verifiedConnection({ latencyMs: null, models: [], modelSource: 'none' }),
    })

    expect(el.querySelector('.setup-connection__verdict')?.textContent?.trim()).toBe('')
    expect(el.querySelector('.setup-connection__latency')).toBeNull()

    app.unmount()
  })

  it('appends a muted latency span to failure pills when a round trip completed', async () => {
    const { app, el } = await mountCard({
      connection: {
        phase: 'key_invalid',
        failureKind: 'auth_invalid',
        detail: 'HTTP 401',
        latencyMs: 87,
        models: [],
        modelSource: 'none',
        discoverError: '',
      },
    })

    const actions = el.querySelector('.setup-connection__actions')
    expect(actions?.querySelector('.setup-connection__latency')?.textContent).toContain('87ms')

    app.unmount()
  })

  it('does not append latency to failure pills when no round trip completed', async () => {
    const { app, el } = await mountCard({
      connection: {
        phase: 'unreachable',
        failureKind: 'transport_transient',
        detail: 'timeout',
        latencyMs: null,
        models: [],
        modelSource: 'none',
        discoverError: '',
      },
    })

    expect(el.querySelector('.setup-connection__actions .setup-connection__latency')).toBeNull()

    app.unmount()
  })
})
