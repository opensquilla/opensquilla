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
  return {
    providerSummary: 'OpenAI',
    providerSelected: 'openai',
    runtimeProviders: [{ providerId: 'openai', label: 'OpenAI' }],
    routerSupportTone: 'is-ready',
    routerSupportText: 'SquillaRouter ready',
    canConfigureRouter: false,
    providerNeeds: [],
    providerCoreFields: [
      { name: 'api_key', label: 'API key', secret: true },
      { name: 'model', label: 'Model' },
    ],
    providerAdvancedFields: [],
    providerAdvancedOpen: false,
    providerEnvMissing: false,
    providerEnvKey: '',
    providerEnvCommand: '',
    llmTimeoutSeconds: 120,
    connection: connection(),
    providerFieldValue: () => '',
    ...overrides,
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
    const pill = el.querySelector('.control-pill.control-pill--ok')
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
    // the api_key field is untouched
    expect(el.querySelector('input[name="setup_provider_api_key"]')?.getAttribute('role')).toBeNull()
    app.unmount()
  })
})
