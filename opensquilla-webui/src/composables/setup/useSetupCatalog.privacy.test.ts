// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { useSetupCatalog } from './useSetupCatalog'
import { PROVIDER_CREDENTIAL_REVEAL_TIMEOUT_MS } from './useSetupProviderForm'

const rpcCall = vi.hoisted(() => vi.fn())
const waitForConnection = vi.hoisted(() => vi.fn(async () => {}))
const pushToast = vi.hoisted(() => vi.fn())

vi.mock('@/stores/rpc', () => ({
  useRpcStore: () => ({
    isConnected: true,
    isConnecting: false,
    waitForConnection,
    call: rpcCall,
  }),
}))

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ pushToast }),
}))

async function mountCatalog() {
  let api!: ReturnType<typeof useSetupCatalog>
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    setup() {
      api = useSetupCatalog()
      return () => null
    },
  })
  app.mount(el)
  await nextTick()
  await Promise.resolve()
  await nextTick()
  return { api, app }
}

function mockConfigSequence(configs: Array<Record<string, unknown>>) {
  const queue = [...configs]
  rpcCall.mockImplementation(async (method: string) => {
    if (method === 'onboarding.catalog') return {}
    if (method === 'onboarding.status') return {}
    if (method === 'channels.status') return { channels: [] }
    if (method === 'config.get') return queue.shift() ?? configs[configs.length - 1] ?? {}
    if (method === 'config.patch.safe') return { restartRequired: false }
    throw new Error(`Unexpected RPC method: ${method}`)
  })
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  rpcCall.mockReset()
  waitForConnection.mockClear()
  pushToast.mockClear()
  document.body.innerHTML = ''
})

describe('useSetupCatalog privacy settings', () => {
  it('saves disable_network_observability through the safe gateway config patch', async () => {
    mockConfigSequence([
      { privacy: { disable_network_observability: false } },
      { privacy: { disable_network_observability: true } },
    ])
    const { api, app } = await mountCatalog()

    api.setDisableNetworkObservability(true)
    expect(api.sectionDirty('privacy')).toBe(true)

    await api.savePrivacy()

    expect(rpcCall).toHaveBeenCalledWith('config.patch.safe', {
      patches: { 'privacy.disable_network_observability': true },
    })
    expect(api.sectionDirty('privacy')).toBe(false)
    expect(pushToast).toHaveBeenCalledWith('Privacy saved.')
    app.unmount()
  })

  it('keeps the privacy intent visible when dirty-bar privacy save fails alongside another section', async () => {
    const configQueue = [
      { privacy: { disable_network_observability: false }, naming: { enabled: false } },
      { privacy: { disable_network_observability: false }, naming: { enabled: true } },
    ]
    rpcCall.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') return {}
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return configQueue.shift() ?? configQueue[configQueue.length - 1] ?? {}
      if (method === 'config.patch.safe') {
        const patches = params?.patches as Record<string, unknown> | undefined
        if (patches && 'privacy.disable_network_observability' in patches) {
          throw new Error('privacy patch failed')
        }
        return { restartRequired: false }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setDisableNetworkObservability(true)
    api.setAutoSessionTitles(true)
    expect(api.sectionDirty('privacy')).toBe(true)
    expect(api.sectionDirty('behavior')).toBe(true)

    await api.saveDirtySections()

    expect(rpcCall).toHaveBeenCalledWith('config.patch.safe', {
      patches: { 'privacy.disable_network_observability': true },
    })
    expect(api.privacyPanel.value.disableNetworkObservability).toBe(true)
    expect(api.sectionDirty('privacy')).toBe(true)
    app.unmount()
  })

  it('shows the effective disabled state when legacy environment variables disable observability', async () => {
    mockConfigSequence([
      {
        privacy: {
          disable_network_observability: false,
          network_observability_disabled_effective: true,
        },
      },
    ])
    const { api, app } = await mountCatalog()

    expect(api.privacyPanel.value.disableNetworkObservability).toBe(false)
    expect(api.privacyPanel.value.statusText).toBe('Network observability is disabled by environment.')
    expect(api.sectionDirty('privacy')).toBe(false)
    app.unmount()
  })

  it('does not label an unsaved config toggle as environment-disabled', async () => {
    mockConfigSequence([
      {
        privacy: {
          disable_network_observability: true,
          network_observability_disabled_effective: true,
        },
      },
    ])
    const { api, app } = await mountCatalog()

    api.setDisableNetworkObservability(false)

    expect(api.privacyPanel.value.statusText).toBe('Network observability is enabled.')
    expect(api.sectionDirty('privacy')).toBe(true)
    app.unmount()
  })
})

describe('useSetupCatalog model strategy IA', () => {
  it('exposes the Model Strategy facade panel cards', async () => {
    mockConfigSequence([
      {
        llm: { provider: 'openrouter', model: 'openrouter/auto' },
        squilla_router: { enabled: true },
        llm_ensemble: { enabled: true },
      },
    ])
    const { api, app } = await mountCatalog()

    expect(api.modelStrategyPanel.value.cards.map(card => card.id)).toEqual(['router', 'ensemble', 'single'])
    expect(api.modelStrategyPanel.value.providerLabel).toBe('openrouter')
    app.unmount()
  })

  it('marks Model Strategy dirty when selecting the single-model strategy', async () => {
    mockConfigSequence([
      {
        llm: { provider: 'openrouter', model: 'openrouter/auto' },
        squilla_router: { enabled: true },
        llm_ensemble: { enabled: true },
      },
    ])
    const { api, app } = await mountCatalog()

    api.setModelStrategy('single')

    expect(api.modelStrategyPanel.value.activeStrategy).toBe('single')
    expect(api.sectionDirty('modelStrategy')).toBe(true)
    expect(api.dirtySections.value.map(s => s.id)).toContain('modelStrategy')
    app.unmount()
  })

  it('routes router readiness actions and status through Model Strategy', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          sectionDetails: {
            router: {
              status: 'missing',
              blocking: true,
              label: 'Router',
            },
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'openrouter', model: 'openrouter/auto' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    expect(api.actionItems.value).toContainEqual({ label: 'Router setup needed', section: 'modelStrategy' })
    expect(api.sectionStatus('modelStrategy')).toEqual({ label: 'Needs action', tone: 'is-warn' })
    app.unmount()
  })

  it('routes ensemble readiness actions through Model Strategy', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          sectionDetails: {
            ensemble: {
              status: 'degraded',
              actionRequired: true,
              label: 'Ensemble',
            },
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'openrouter', model: 'openrouter/auto' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    expect(api.actionItems.value).toContainEqual({ label: 'Ensemble setup needed', section: 'modelStrategy' })
    expect(api.actionItems.value).not.toContainEqual({ label: 'Ensemble setup needed', section: 'provider' })
    app.unmount()
  })

  it('auto-selects Model Strategy when ensemble readiness needs action', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          sectionDetails: {
            router: { status: 'ok', label: 'Router' },
            ensemble: {
              status: 'degraded',
              actionRequired: true,
              label: 'Ensemble',
            },
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'openrouter', model: 'openrouter/auto' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.selectInitialSection('auto')

    expect(api.section.value).toBe('modelStrategy')
    app.unmount()
  })

  it('reports Model Strategy needs action when ensemble detail needs action', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          sectionDetails: {
            router: { status: 'ok', label: 'Router' },
            ensemble: {
              status: 'degraded',
              actionRequired: true,
              label: 'Ensemble',
            },
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'openrouter', model: 'openrouter/auto' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    expect(api.sectionStatus('modelStrategy')).toEqual({ label: 'Needs action', tone: 'is-warn' })
    app.unmount()
  })

  it('aggregates router and ensemble dirty state under Model Strategy', async () => {
    mockConfigSequence([
      {
        llm: { provider: 'openrouter', model: 'openrouter/auto' },
        squilla_router: { enabled: true },
        llm_ensemble: { enabled: true },
      },
    ])
    const { api, app } = await mountCatalog()

    api.setModelStrategy('single')
    expect(api.sectionDirty('modelStrategy')).toBe(true)

    await api.discardChanges()
    expect(api.sectionDirty('modelStrategy')).toBe(false)

    api.setEnsembleEnabled(false)
    expect(api.sectionDirty('modelStrategy')).toBe(true)
    expect(api.dirtySections.value.map(s => s.id)).toContain('modelStrategy')
    app.unmount()
  })

  it('saves dirty router and ensemble edits through the Model Strategy save path', async () => {
    let routerSaved = false
    let ensembleSaved = false
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return {}
      if (method === 'onboarding.status') return {}
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return {
          llm: { provider: 'openrouter', model: 'openrouter/auto' },
          squilla_router: { enabled: !routerSaved, default_tier: 'balanced' },
          llm_ensemble: { enabled: ensembleSaved },
        }
      }
      if (method === 'onboarding.router.configure') {
        routerSaved = true
        return {}
      }
      if (method === 'onboarding.ensemble.configure') {
        ensembleSaved = true
        return {}
      }
      if (method === 'config.patch.safe') return { restartRequired: false }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setModelStrategy('single')
    api.setEnsembleEnabled(true)
    await api.saveDirtySections()

    expect(rpcCall).toHaveBeenCalledWith('onboarding.router.configure', expect.any(Object))
    expect(rpcCall).toHaveBeenCalledWith('onboarding.ensemble.configure', { enabled: true })
    app.unmount()
  })

  it('represents router and ensemble dirty state under Model Strategy', async () => {
    mockConfigSequence([
      {
        llm: { provider: 'openrouter', model: 'openrouter/auto' },
        squilla_router: { enabled: true },
        llm_ensemble: { enabled: false },
      },
    ])
    const { api, app } = await mountCatalog()

    api.setRouterMode('disabled')
    expect(api.sectionDirty('modelStrategy')).toBe(true)
    expect(api.dirtySections.value.map(s => s.id)).toContain('modelStrategy')

    await api.discardChanges()
    expect(api.sectionDirty('modelStrategy')).toBe(false)

    api.setEnsembleEnabled(true)
    expect(api.sectionDirty('modelStrategy')).toBe(true)
    expect(api.dirtySections.value.map(s => s.id)).toContain('modelStrategy')
    app.unmount()
  })
})

describe('useSetupCatalog provider credential reveal', () => {
  it('reveals the saved provider key through the dedicated RPC', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'deepseek',
              label: 'DeepSeek',
              runtimeSupported: true,
              requiresApiKey: true,
              envKey: 'DEEPSEEK_API_KEY',
              fields: [{ name: 'model', label: 'Model' }],
            },
          ],
        }
      }
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          llmConfigured: true,
          llmSource: 'explicit',
          llmCredentialStatus: {
            provider: 'deepseek',
            available: true,
            source: 'explicit',
            envKey: 'DEEPSEEK_API_KEY',
            masked: 'sk-••••1234',
            revealAllowed: true,
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'deepseek', model: 'deepseek-chat' } }
      if (method === 'onboarding.provider.credential.reveal') return { ok: true, apiKey: 'sk-real-value' }
      throw new Error(`Unexpected RPC method: ${method}`)
    })

    const { api, app } = await mountCatalog()

    vi.useFakeTimers()
    await api.revealProviderCredential()

    expect(rpcCall).toHaveBeenCalledWith('onboarding.provider.credential.reveal', { providerId: 'deepseek' })
    const credentialPanel = api.providerPanel.value.credentialPanel as { masked: string; revealed: string }
    expect(credentialPanel.revealed).toBe('sk-real-value')

    vi.advanceTimersByTime(PROVIDER_CREDENTIAL_REVEAL_TIMEOUT_MS)
    await nextTick()

    const expiredCredentialPanel = api.providerPanel.value.credentialPanel as { masked: string; revealed: string }
    expect(expiredCredentialPanel.masked).toBe('sk-••••1234')
    expect(expiredCredentialPanel.revealed).toBe('')
    app.unmount()
  })
})
