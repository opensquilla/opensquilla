// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import SetupProviderPanel from './SetupProviderPanel.vue'
import type { ConnectionState, DiscoveredModel } from '@/composables/setup/useSetupProviderForm'

function connection(overrides: Partial<ConnectionState> = {}): ConnectionState {
  return {
    phase: 'unverified',
    failureKind: '',
    detail: '',
    latencyMs: null,
    models: [],
    modelSource: 'none',
    discoverError: '',
    ...overrides,
  }
}

const DISCOVERED: DiscoveredModel[] = [
  {
    id: 'test-vendor/alpha',
    name: 'Alpha',
    contextWindow: 262144,
    maxOutputTokens: 16384,
    capabilities: ['chat'],
    pricing: null,
    capabilitySource: 'provider',
  },
]

function panel(overrides: Record<string, unknown> = {}) {
  const base = {
    providerSummary: 'OpenAI',
    providerSelected: 'openai',
    runtimeProviders: [{ providerId: 'openai', label: 'OpenAI' }],
    routerSupportTone: 'is-ready',
    routerSupportText: 'SquillaRouter ready',
    canConfigureRouter: false,
    providerNeeds: [],
    providerCoreFields: [
      { name: 'model', label: 'Model' },
    ],
    providerAdvancedFields: [],
    credentialPanel: {
      providerLabel: 'OpenAI',
      providerSelected: true,
      available: true,
      source: 'explicit',
      envKey: 'OPENAI_API_KEY',
      masked: 'sk-••••1234',
      revealAllowed: true,
      revealed: '',
      revealError: '',
      replacing: false,
      apiKeyValue: '',
      apiKeyEnvValue: '',
      connection: connection(),
      onReveal: vi.fn(),
      onReplace: vi.fn(),
      onCancelReplace: vi.fn(),
    },
    providerAdvancedOpen: false,
    providerEnvMissing: false,
    providerEnvKey: '',
    providerEnvCommand: '',
    llmTimeoutSeconds: 120,
    contextWindowTokens: '',
    contextWindowGlobal: null,
    providerIsLocal: false,
    connection: connection(),
    providerFieldValue: () => '',
    ...overrides,
  }
  const credentialPanel = (base.credentialPanel as Record<string, unknown>) || {}
  return {
    ...base,
    credentialPanel: {
      ...credentialPanel,
      providerSelected: (overrides.providerSelected as string | undefined) !== undefined
        ? Boolean(overrides.providerSelected)
        : credentialPanel.providerSelected,
      connection: (overrides.connection as ConnectionState | undefined) || (credentialPanel.connection as ConnectionState) || base.connection,
    },
  }
}

async function mountPanel(props: Record<string, unknown> = {}, listeners: Record<string, unknown> = {}) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SetupProviderPanel, { panel: panel(props), ...listeners })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

function testButton(el: HTMLElement): HTMLButtonElement | null {
  return Array.from(el.querySelectorAll<HTMLButtonElement>('button.btn'))
    .find(btn => (btn.textContent || '').includes('Test connection') || (btn.textContent || '').includes('Testing')) || null
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  // The context-window keys land in the locale JSONs via the i18n merge step;
  // inject them here so assertions exercise interpolation, not raw key names.
  i18n.global.mergeLocaleMessage('en', {
    setup: {
      provider: {
        contextWindowLabel: 'Context window override (tokens)',
        contextWindowDesc: 'desc',
        contextWindowAuto: 'auto',
        contextWindowUnknown: 'unknown',
        contextWindowNone: 'none',
        contextWindowReadout: 'auto-detected {auto} · override {override} · effective {effective}',
        contextWindowLocalWarning: 'Effective context window is {tokens} tokens.',
      },
    },
  })
  document.body.innerHTML = ''
})

describe('SetupProviderPanel — test connection', () => {
  it('emits probeConnection when the Test connection button is clicked', async () => {
    const onProbeConnection = vi.fn()
    const { app, el } = await mountPanel({}, { onProbeConnection })
    const button = testButton(el)
    expect(button?.disabled).toBe(false)
    button?.click()
    expect(onProbeConnection).toHaveBeenCalledTimes(1)
    app.unmount()
  })

  it('disables the button with no provider selected and while probing', async () => {
    const noProvider = await mountPanel({ providerSelected: '' })
    expect(testButton(noProvider.el)?.disabled).toBe(true)
    noProvider.app.unmount()

    const probing = await mountPanel({ connection: connection({ phase: 'probing' }) })
    const button = testButton(probing.el)
    expect(button?.disabled).toBe(true)
    expect(button?.textContent).toContain('Testing connection')
    expect(probing.el.querySelector('.setup-connection__spinner')).toBeTruthy()
    probing.app.unmount()
  })

  it('shows the Connected pill when verified', async () => {
    const { app, el } = await mountPanel({ connection: connection({ phase: 'verified' }) })
    const pill = el.querySelector('.setup-connection__actions .control-pill.control-pill--ok')
    expect(pill?.textContent).toContain('✓ Connected')
    app.unmount()
  })

  it('shows a human sentence for key_invalid and keeps the raw kind in the tooltip only', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'key_invalid', failureKind: 'auth_invalid', detail: 'HTTP 401' }),
    })
    const pill = el.querySelector('.control-pill.control-pill--danger')
    expect(pill?.textContent).toContain('✗ Key rejected — The provider rejected this API key.')
    expect(pill?.textContent).not.toContain('auth_invalid')
    expect(pill?.getAttribute('title')).toContain('auth_invalid')
    app.unmount()
  })

  it('shows a couldn\'t-connect pill for unreachable failures', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'unreachable', failureKind: 'transport_transient', detail: 'timeout' }),
    })
    const pill = el.querySelector('.control-pill.control-pill--warn')
    expect(pill?.textContent).toContain("✗ Couldn't connect — Couldn't reach the endpoint.")
    app.unmount()
  })

  it('shows a discover hint when verified but model listing failed', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', discoverError: 'listing unsupported' }),
    })
    expect(el.querySelector('.setup-connection__hint')?.textContent)
      .toContain('Couldn\'t list models — type a model id.')
    app.unmount()
  })
})

describe('SetupProviderPanel — model field', () => {
  it('renders the plain text field when no models were discovered', async () => {
    const { app, el } = await mountPanel()
    expect(el.querySelector('.setup-model-combobox')).toBeNull()
    expect(el.querySelector('input[name="setup_provider_model"]')).toBeTruthy()
    app.unmount()
  })

  it('upgrades only the model field to the combobox when discovery returned models', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', models: DISCOVERED, modelSource: 'live' }),
    })
    const combobox = el.querySelector('.setup-model-combobox input[role="combobox"]')
    expect(combobox?.getAttribute('name')).toBe('setup_provider_model')
    expect(el.querySelector('input[name="setup_provider_api_key"]')).toBeNull()
    app.unmount()
  })

  it('does not render api_key or api_key_env as generic provider fields when the credential card is present', async () => {
    const { app, el } = await mountPanel({
      providerCoreFields: [
        { name: 'model', label: 'Model' },
      ],
      providerAdvancedFields: [
        { name: 'base_url', label: 'Base URL' },
      ],
    })

    expect(el.querySelector('[data-name="api_key"]')).toBeNull()
    expect(el.querySelector('[data-name="api_key_env"]')).toBeNull()
    expect(el.textContent).toContain('OpenAI credential')

    app.unmount()
  })
})

describe('SetupProviderPanel — context-window override', () => {
  function contextInput(el: HTMLElement): HTMLInputElement | null {
    return el.querySelector<HTMLInputElement>('input[name="setup_provider_context_window"]')
  }

  function readout(el: HTMLElement): string {
    return el.querySelector('.setup-context-window__readout')?.textContent || ''
  }

  const modelValue = (value: string) =>
    (field: { name: string }) => (field.name === 'model' ? value : '')

  it('shows the auto-detected window for the current model with no override', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', models: DISCOVERED, modelSource: 'live' }),
      providerFieldValue: modelValue('test-vendor/alpha'),
    })

    const input = contextInput(el)
    expect(input).toBeTruthy()
    expect(input?.disabled).toBe(false)
    expect(input?.placeholder).toBe('auto')
    expect(el.querySelector('.setup-context-window__readout')?.getAttribute('aria-live')).toBe('polite')
    expect(readout(el)).toContain('auto-detected 262144')
    expect(readout(el)).toContain('override none')
    expect(readout(el)).toContain('effective 262144')
    expect(el.querySelector('.setup-warning')).toBeNull()

    app.unmount()
  })

  it('reports unknown when the model has no discovery row', async () => {
    const { app, el } = await mountPanel({
      providerFieldValue: modelValue('unlisted-model'),
    })

    expect(readout(el)).toContain('auto-detected unknown')
    expect(readout(el)).toContain('effective unknown')

    app.unmount()
  })

  it('an override beats auto-detection and warns for small local windows', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', models: DISCOVERED, modelSource: 'live' }),
      providerFieldValue: modelValue('test-vendor/alpha'),
      contextWindowTokens: '4096',
      providerIsLocal: true,
    })

    expect(readout(el)).toContain('override 4096')
    expect(readout(el)).toContain('effective 4096')
    expect(el.querySelector('.setup-warning')?.textContent).toContain('4096 tokens')

    app.unmount()
  })

  it('does not warn for the same small window on a hosted provider', async () => {
    const { app, el } = await mountPanel({
      providerFieldValue: modelValue('test-vendor/alpha'),
      contextWindowTokens: '4096',
      providerIsLocal: false,
    })

    expect(el.querySelector('.setup-warning')).toBeNull()

    app.unmount()
  })

  it('falls back to the global llm.context_window_tokens layer when no override is set', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', models: DISCOVERED, modelSource: 'live' }),
      providerFieldValue: modelValue('test-vendor/alpha'),
      contextWindowTokens: '',
      contextWindowGlobal: 100000,
    })

    // No per-model override → effective takes the global config layer, not auto.
    expect(readout(el)).toContain('override none')
    expect(readout(el)).toContain('auto-detected 262144')
    expect(readout(el)).toContain('effective 100000')

    app.unmount()
  })

  it('a per-model override beats the global config layer', async () => {
    const { app, el } = await mountPanel({
      connection: connection({ phase: 'verified', models: DISCOVERED, modelSource: 'live' }),
      providerFieldValue: modelValue('test-vendor/alpha'),
      contextWindowTokens: '4096',
      contextWindowGlobal: 100000,
    })

    expect(readout(el)).toContain('override 4096')
    expect(readout(el)).toContain('effective 4096')

    app.unmount()
  })

  it('warns for a small global window on a local provider with no override', async () => {
    const { app, el } = await mountPanel({
      providerFieldValue: modelValue('test-vendor/alpha'),
      contextWindowTokens: '',
      contextWindowGlobal: 8192,
      providerIsLocal: true,
    })

    expect(el.querySelector('.setup-warning')?.textContent).toContain('8192 tokens')

    app.unmount()
  })

  it('disables the input while the model field is empty', async () => {
    const { app, el } = await mountPanel()

    expect(contextInput(el)?.disabled).toBe(true)

    app.unmount()
  })

  it('emits updateContextWindow with the raw input string', async () => {
    const onUpdateContextWindow = vi.fn()
    const { app, el } = await mountPanel(
      { providerFieldValue: modelValue('test-vendor/alpha') },
      { onUpdateContextWindow },
    )

    const input = contextInput(el)!
    input.value = '16384'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    expect(onUpdateContextWindow).toHaveBeenCalledWith('16384')

    app.unmount()
  })
})

describe('SetupProviderPanel — model strategy wayfinding', () => {
  it('shows exactly one compact Model Routing entry without SquillaRouter wording', async () => {
    const onGoToSection = vi.fn()
    const preset = {
      hasPreset: true,
      presetLabel: 'OpenAI balanced tiers',
      presetDescription: 'A curated tier split.',
      synthesized: false,
      tierRows: [],
      tierLabel: (tier: string) => tier,
      routerMode: 'custom',
      routerCustomized: true,
    }
    const { app, el } = await mountPanel({ canConfigureRouter: true }, { preset, onGoToSection })
    const routingLinks = Array.from(el.querySelectorAll<HTMLButtonElement>('button'))
      .filter(btn => /Model Routing/.test(btn.textContent || ''))

    expect(routingLinks).toHaveLength(1)
    expect(routingLinks[0]?.textContent).toContain('Open Model Routing')
    expect(el.textContent).not.toContain('SquillaRouter ready')
    expect(el.textContent).not.toContain('Routing template:')
    expect(el.textContent).not.toContain('Model Routing already uses')

    routingLinks[0]?.click()

    expect(onGoToSection).toHaveBeenCalledWith('modelStrategy')
    app.unmount()
  })
})
