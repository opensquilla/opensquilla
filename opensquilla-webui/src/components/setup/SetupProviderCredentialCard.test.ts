// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createApp, nextTick, reactive } from 'vue'
import i18n from '@/i18n'
import SetupProviderCredentialCard from './SetupProviderCredentialCard.vue'

function panel(overrides: Record<string, unknown> = {}) {
  return {
    providerLabel: 'DeepSeek',
    providerSelected: true,
    acceptsApiKey: true,
    requiresApiKey: true,
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
    probeReady: true,
    probeDisabledReason: '',
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

// The real card stays mounted across saves and provider switches, so these
// tests need a panel whose fields mutate in place after mount.
async function mountReactiveCard(props: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const livePanel = reactive(panel(props))
  const app = createApp(SetupProviderCredentialCard, { panel: livePanel })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el, livePanel }
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

  it('separates credential readiness from the unverified connection state', async () => {
    const { app, el } = await mountCard()

    expect(el.textContent).toContain('DeepSeek authentication')
    expect(el.textContent).toContain('Credential ready')
    expect(el.textContent).toContain('Not tested')
    expect(el.textContent).not.toContain('✓ Connected')
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

  it('renders a directly editable input when no key was ever saved', async () => {
    const onUpdateField = vi.fn()
    const { app, el } = await mountCard(
      { masked: '', source: 'none', available: false },
      { onUpdateField },
    )

    // First-run setup: no saved secret to guard, so no readonly display, no
    // "Replace key" detour, and nothing to cancel back to.
    expect(el.querySelector('input[name="setup_provider_api_key_display"]')).toBeNull()
    expect(Array.from(el.querySelectorAll('button')).some(btn => (btn.textContent || '').includes('Replace key'))).toBe(false)
    expect(Array.from(el.querySelectorAll('button')).some(btn => (btn.textContent || '').includes('Cancel'))).toBe(false)

    const input = el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')
    expect(input).toBeTruthy()
    expect(input?.placeholder).toBe('Paste your API key')

    input!.value = 'sk-first'
    input!.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    expect(onUpdateField).toHaveBeenCalledWith('api_key', 'sk-first')

    app.unmount()
  })

  it('keeps the editable input directly available when a declared env var is not visible', async () => {
    const { app, el } = await mountCard({ masked: '', source: 'missing_env', available: false })

    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeTruthy()
    expect(el.querySelector('input[name="setup_provider_api_key_display"]')).toBeNull()

    app.unmount()
  })

  it('keeps an optional key directly editable when the provider accepts one', async () => {
    const { app, el } = await mountCard({
      masked: '',
      source: 'not_required',
      requiresApiKey: false,
    })

    expect(el.textContent).toContain('API key optional')
    expect(el.textContent).toContain('Current source: no API key configured (optional)')
    expect(el.textContent).toContain('API key (optional)')
    expect(el.textContent).toContain(
      'Enter a key only if this endpoint requires authentication; otherwise leave it blank.',
    )
    expect(el.textContent).not.toContain('Credential ready')
    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeTruthy()
    expect(el.querySelector('input[name="setup_provider_api_key_display"]')).toBeNull()

    app.unmount()
  })

  it('does not render an API key control for an OAuth provider', async () => {
    const { app, el } = await mountCard({
      providerLabel: 'OpenAI Codex',
      acceptsApiKey: false,
      requiresApiKey: false,
      masked: '',
      source: 'not_required',
    })

    expect(el.textContent).toContain('No key required')
    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeNull()
    expect(el.querySelector('details.setup-provider-credential__details')).toBeNull()

    app.unmount()
  })

  it('disables probing with a localized missing-field reason', async () => {
    const reason = '请先填写必填项：模型、基础 URL。'
    const { app, el } = await mountCard({ probeReady: false, probeDisabledReason: reason })

    const button = Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
      .find(candidate => candidate.textContent?.includes('Test connection'))
    expect(button?.disabled).toBe(true)
    expect(button?.title).toBe(reason)
    expect(el.textContent).toContain(reason)

    app.unmount()
  })

  it('keeps the masked display and Replace key guard while a saved key exists', async () => {
    const { app, el } = await mountCard({ masked: 'sk-••••7890', source: 'explicit' })

    expect(el.querySelector('input[name="setup_provider_api_key_display"]')).toBeTruthy()
    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeNull()
    expect(Array.from(el.querySelectorAll('button')).some(btn => (btn.textContent || '').includes('Replace key'))).toBe(true)

    app.unmount()
  })

  it('re-hides the secret input when first-run editing ends in a saved key', async () => {
    const { app, el, livePanel } = await mountReactiveCard({ masked: '', source: 'none', available: false })

    // First-run: user toggles the key to plaintext while typing it.
    const toggle = () => Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
      .find(btn => /^(Show|Hide) API key$/.test(btn.getAttribute('aria-label') || ''))
    toggle()!.click()
    await nextTick()
    expect(el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')?.type).toBe('text')

    // Save lands: the masked display takes over without replacing ever flipping.
    livePanel.masked = 'sk-••••1234'
    livePanel.source = 'explicit'
    await nextTick()
    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeNull()

    // A later Replace must start hidden again, not inherit the old toggle.
    livePanel.replacing = true
    await nextTick()
    expect(el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')?.type).toBe('password')

    app.unmount()
  })

  it('re-hides the secret input when the card switches to another provider mid-edit', async () => {
    const { app, el, livePanel } = await mountReactiveCard({ masked: '', source: 'none', available: false })

    const toggle = Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
      .find(btn => btn.getAttribute('aria-label') === 'Show API key')
    toggle!.click()
    await nextTick()
    expect(el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')?.type).toBe('text')

    livePanel.providerLabel = 'OpenRouter'
    livePanel.envKey = 'OPENROUTER_API_KEY'
    await nextTick()

    expect(el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')?.type).toBe('password')

    app.unmount()
  })

  it('shows the replacement placeholder and Cancel when replacing a saved key', async () => {
    const { app, el } = await mountCard({ replacing: true })

    const input = el.querySelector<HTMLInputElement>('input[name="setup_provider_api_key"]')
    expect(input?.placeholder).toBe('Paste a replacement API key')
    expect(Array.from(el.querySelectorAll('button')).some(btn => (btn.textContent || '').includes('Cancel'))).toBe(true)

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
