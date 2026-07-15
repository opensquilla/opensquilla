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
  it('discovers the active provider model catalog when Model Strategy opens', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'tokenrhythm',
              label: 'TokenRhythm',
              runtimeSupported: true,
              fields: [{ name: 'model', label: 'Model' }],
            },
          ],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return { llm: { provider: 'tokenrhythm', model: 'deepseek-v4-pro' } }
      }
      if (method === 'onboarding.models.discover') {
        return {
          ok: true,
          source: 'live',
          models: [
            {
              id: 'deepseek-v4-flash',
              name: 'DeepSeek V4 Flash',
              contextWindow: 128000,
              maxOutputTokens: 16384,
              capabilities: ['chat', 'tools'],
              pricing: null,
              capabilitySource: 'provider',
            },
          ],
        }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setSection('modelStrategy')
    await nextTick()
    await Promise.resolve()
    await nextTick()

    expect(rpcCall).toHaveBeenCalledWith('onboarding.models.discover', {
      providerId: 'tokenrhythm',
      model: 'deepseek-v4-pro',
    })
    expect(api.routerPanel.value.discoveredModelsByProvider.tokenrhythm?.models).toHaveLength(1)
    expect(api.routerPanel.value.discoveredModelsByProvider.tokenrhythm?.models[0]?.id).toBe('deepseek-v4-flash')
    app.unmount()
  })

  it('rediscovers models when config reloads while Model Strategy stays open', async () => {
    let discoverCalls = 0
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'tokenrhythm',
              label: 'TokenRhythm',
              runtimeSupported: true,
              fields: [{ name: 'model', label: 'Model' }],
            },
          ],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return { llm: { provider: 'tokenrhythm', model: 'deepseek-v4-pro' } }
      }
      if (method === 'onboarding.models.discover') {
        discoverCalls += 1
        return {
          ok: true,
          source: 'live',
          models: [
            {
              id: 'deepseek-v4-flash',
              name: 'DeepSeek V4 Flash',
              contextWindow: 128000,
              maxOutputTokens: 16384,
              capabilities: ['chat', 'tools'],
              pricing: null,
              capabilitySource: 'provider',
            },
          ],
        }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setSection('modelStrategy')
    await nextTick()
    await Promise.resolve()
    await nextTick()
    expect(discoverCalls).toBe(1)

    await api.loadData()

    expect(discoverCalls).toBe(2)
    expect(api.routerPanel.value.discoveredModelsByProvider.tokenrhythm?.models[0]?.id).toBe('deepseek-v4-flash')
    app.unmount()
  })

  it('does not wait for model discovery before a Model Strategy config reload completes', async () => {
    let discoverCalls = 0
    let releaseReloadDiscovery!: () => void
    const reloadDiscovery = new Promise<void>((resolve) => { releaseReloadDiscovery = resolve })
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [{ providerId: 'tokenrhythm', label: 'TokenRhythm', runtimeSupported: true }],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return { llm: { provider: 'tokenrhythm', model: 'deepseek-v4-pro' } }
      }
      if (method === 'onboarding.models.discover') {
        discoverCalls += 1
        if (discoverCalls === 2) await reloadDiscovery
        return { ok: true, source: 'live', models: [] }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setSection('modelStrategy')
    await vi.waitFor(() => expect(discoverCalls).toBe(1))

    let reloadCompleted = false
    const reload = api.loadData().then(() => { reloadCompleted = true })
    await vi.waitFor(() => expect(discoverCalls).toBe(2))
    await Promise.resolve()

    expect(reloadCompleted).toBe(true)
    releaseReloadDiscovery()
    await reload
    app.unmount()
  })

  it('discovers and isolates catalogs for every provider used by mixed router tiers', async () => {
    const requests: Array<Record<string, unknown>> = []
    rpcCall.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'tokenrhythm',
              label: 'TokenRhythm',
              runtimeSupported: true,
              fields: [
                { name: 'model', label: 'Model' },
                { name: 'api_key', label: 'API key', secret: true },
              ],
            },
            { providerId: 'openrouter', label: 'OpenRouter', runtimeSupported: true },
            { providerId: 'anthropic', label: 'Anthropic', runtimeSupported: true },
          ],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return {
          llm: { provider: 'tokenrhythm', model: 'deepseek-v4-pro' },
          squilla_router: {
            enabled: true,
            tiers: {
              c0: { provider: ' TokenRhythm ', model: 'deepseek-v4-flash' },
              c1: { provider: 'OPENROUTER', model: 'deepseek/deepseek-v4-pro' },
              c2: { provider: 'anthropic', model: 'claude-sonnet-4' },
            },
          },
        }
      }
      if (method === 'onboarding.models.discover') {
        requests.push(params || {})
        const providerId = String(params?.providerId || '').toLowerCase()
        if (providerId === 'anthropic') return { ok: true, source: 'none', models: [] }
        return {
          ok: true,
          source: 'live',
          models: [{
            id: providerId === 'openrouter' ? 'deepseek/deepseek-v4-pro' : 'deepseek-v4-flash',
            name: 'Model',
            contextWindow: null,
            maxOutputTokens: null,
            capabilities: [],
            pricing: null,
            capabilitySource: 'provider',
          }],
        }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.updateProviderField('api_key', 'unsaved-selected-provider-key')
    api.setSection('modelStrategy')
    await vi.waitFor(() => expect(requests).toHaveLength(3))

    expect(requests).toContainEqual({
      providerId: 'tokenrhythm',
      apiKey: 'unsaved-selected-provider-key',
      model: 'deepseek-v4-pro',
    })
    expect(requests).toContainEqual({ providerId: 'openrouter' })
    expect(requests).toContainEqual({ providerId: 'anthropic' })
    expect(requests.filter(request => request.apiKey !== undefined)).toHaveLength(1)

    const byProvider = api.routerPanel.value.discoveredModelsByProvider
    expect(Object.keys(byProvider).sort()).toEqual(['anthropic', 'openrouter', 'tokenrhythm'])
    expect(byProvider.tokenrhythm?.models[0]?.id).toBe('deepseek-v4-flash')
    expect(byProvider.openrouter?.models[0]?.id).toBe('deepseek/deepseek-v4-pro')
    expect(byProvider.anthropic).toEqual({ models: [], source: 'none' })
    app.unmount()
  })

  it('deduplicates provider-scoped discovery when Model Strategy is reopened mid-request', async () => {
    const requests: string[] = []
    let releaseDiscoveries!: () => void
    const blocked = new Promise<void>((resolve) => { releaseDiscoveries = resolve })
    rpcCall.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            { providerId: 'tokenrhythm', label: 'TokenRhythm', runtimeSupported: true },
            { providerId: 'openrouter', label: 'OpenRouter', runtimeSupported: true },
          ],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return {
          llm: { provider: 'tokenrhythm', model: 'deepseek-v4-pro' },
          squilla_router: {
            enabled: true,
            tiers: {
              c0: { provider: 'tokenrhythm', model: 'deepseek-v4-flash' },
              c1: { provider: 'openrouter', model: 'deepseek/deepseek-v4-pro' },
            },
          },
        }
      }
      if (method === 'onboarding.models.discover') {
        requests.push(String(params?.providerId || ''))
        await blocked
        return { ok: true, source: 'none', models: [] }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.setSection('modelStrategy')
    await vi.waitFor(() => expect(requests).toHaveLength(2))
    api.setSection('provider')
    await nextTick()
    api.setSection('modelStrategy')
    await nextTick()

    expect(requests.sort()).toEqual(['openrouter', 'tokenrhythm'])
    releaseDiscoveries()
    app.unmount()
  })

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

describe('useSetupCatalog optional provider credentials', () => {
  function mockSavedProviderForSave(options: {
    providerId?: string
    acceptsApiKey?: boolean
    requiresApiKey?: boolean
    additionalProviderId?: string
    baseUrl?: string
  } = {}) {
    const providerId = options.providerId || 'custom'
    const acceptsApiKey = options.acceptsApiKey ?? true
    const requiresApiKey = options.requiresApiKey ?? false
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId,
              label: providerId === 'custom' ? 'Custom OpenAI-compatible endpoint' : 'Test provider',
              runtimeSupported: true,
              acceptsApiKey,
              requiresApiKey,
              envKey: `${providerId.toUpperCase()}_API_KEY`,
              fields: [
                { name: 'model', label: 'Model', required: true },
                { name: 'api_key', label: 'API key', secret: true },
                { name: 'api_key_env', label: 'API key environment variable' },
                ...(options.baseUrl
                  ? [{ name: 'base_url', label: 'Base URL', required: true }]
                  : []),
              ],
            },
            ...(options.additionalProviderId
              ? [{
                  providerId: options.additionalProviderId,
                  label: 'Other optional provider',
                  runtimeSupported: true,
                  acceptsApiKey: true,
                  requiresApiKey: false,
                  envKey: `${options.additionalProviderId.toUpperCase()}_API_KEY`,
                  fields: [{ name: 'model', label: 'Model', required: true }],
                }]
              : []),
          ],
        }
      }
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          llmConfigured: true,
          llmSource: 'explicit',
          llmCredentialStatus: {
            provider: providerId,
            available: true,
            source: 'explicit',
            envKey: `${providerId.toUpperCase()}_API_KEY`,
            masked: 'sk-••••1234',
            revealAllowed: true,
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') {
        return {
          llm: {
            provider: providerId,
            model: 'test-model',
            ...(options.baseUrl ? { base_url: options.baseUrl } : {}),
          },
        }
      }
      if (method === 'onboarding.provider.configure') return {}
      throw new Error(`Unexpected RPC method: ${method}`)
    })
  }

  it('exposes an optional custom key and blocks probes until required fields exist', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'custom',
              label: 'Custom OpenAI-compatible endpoint',
              runtimeSupported: true,
              acceptsApiKey: true,
              requiresApiKey: false,
              envKey: 'CUSTOM_LLM_API_KEY',
              fields: [
                { name: 'model', label: 'Model id', required: true, default: '' },
                { name: 'api_key', label: 'API key', required: false, secret: true },
                { name: 'base_url', label: 'Base URL', required: true, default: '' },
              ],
            },
          ],
        }
      }
      if (method === 'onboarding.status') {
        return { hasConfig: false, llmConfigured: false, llmCredentialStatus: {} }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return {}
      if (method === 'onboarding.provider.probe') {
        return { ok: false, failureKind: 'transport_transient', message: 'offline' }
      }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    api.selectProvider('custom')
    api.onProviderChange()

    let credential = api.providerPanel.value.credentialPanel
    expect(credential).toMatchObject({
      acceptsApiKey: true,
      requiresApiKey: false,
      source: 'not_required',
      probeReady: false,
    })
    expect(credential?.probeDisabledReason).toBe(
      'Complete required fields before testing: Model, Base URL.',
    )

    api.probeProviderConnection()
    expect(rpcCall.mock.calls.some(call => call[0] === 'onboarding.provider.probe')).toBe(false)

    api.updateProviderField('model', 'test-model')
    api.updateProviderField('base_url', 'https://custom.example.test/v1')
    credential = api.providerPanel.value.credentialPanel
    expect(credential?.probeReady).toBe(true)
    expect(credential?.probeDisabledReason).toBe('')

    api.probeProviderConnection()
    await Promise.resolve()
    expect(rpcCall).toHaveBeenCalledWith('onboarding.provider.probe', {
      providerId: 'custom',
      baseUrl: 'https://custom.example.test/v1',
      model: 'test-model',
    })
    app.unmount()
  })

  it('falls back conservatively to requiresApiKey when an older gateway omits acceptsApiKey', async () => {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId: 'custom',
              label: 'Custom endpoint',
              runtimeSupported: true,
              requiresApiKey: false,
              fields: [{ name: 'model', label: 'Model' }],
            },
            {
              providerId: 'openrouter',
              label: 'OpenRouter',
              runtimeSupported: true,
              requiresApiKey: true,
              fields: [{ name: 'model', label: 'Model' }],
            },
          ],
        }
      }
      if (method === 'onboarding.status') {
        return {
          hasConfig: true,
          llmConfigured: true,
          llmSource: 'not_required',
          llmCredentialStatus: {
            provider: 'custom',
            available: true,
            source: 'not_required',
          },
        }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: 'custom', model: 'test-model' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
    const { api, app } = await mountCatalog()

    expect(api.providerPanel.value.credentialPanel).toMatchObject({
      acceptsApiKey: false,
      requiresApiKey: false,
    })

    api.selectProvider('openrouter')
    api.onProviderChange()
    expect(api.providerPanel.value.credentialPanel).toMatchObject({
      acceptsApiKey: true,
      requiresApiKey: true,
    })
    app.unmount()
  })

  it('sends preserveApiKey only for the active saved explicit optional credential', async () => {
    mockSavedProviderForSave()
    const { api, app } = await mountCatalog()

    await api.saveProvider()

    expect(rpcCall).toHaveBeenCalledWith('onboarding.provider.configure', {
      providerId: 'custom',
      model: 'test-model',
      preserveApiKey: true,
    })
    app.unmount()
  })

  it('reuses the same preservation intent when applying a provider preset', async () => {
    mockSavedProviderForSave()
    const { api, app } = await mountCatalog()

    await api.applyProviderPreset()

    expect(rpcCall).toHaveBeenCalledWith('onboarding.provider.configure', {
      providerId: 'custom',
      model: 'test-model',
      preserveApiKey: true,
      presetId: 'custom',
    })
    app.unmount()
  })

  it('preserves an optional key for a same-origin endpoint path change', async () => {
    mockSavedProviderForSave({ baseUrl: 'https://llm.example.test/v1' })
    const { api, app } = await mountCatalog()

    api.updateProviderField('base_url', 'https://llm.example.test/openai/v1')
    await api.saveProvider()

    const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
    expect(configureCall?.[1]).toMatchObject({
      baseUrl: 'https://llm.example.test/openai/v1',
      preserveApiKey: true,
    })
    app.unmount()
  })

  it('does not preserve an optional key across endpoint origins', async () => {
    mockSavedProviderForSave({ baseUrl: 'https://llm-a.example.test/v1' })
    const { api, app } = await mountCatalog()

    api.updateProviderField('base_url', 'https://llm-b.example.test/v1')
    await api.saveProvider()

    const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
    const payload = configureCall?.[1] as Record<string, unknown>
    expect(payload).toMatchObject({ baseUrl: 'https://llm-b.example.test/v1' })
    expect(payload).not.toHaveProperty('preserveApiKey')
    app.unmount()
  })

  it.each([
    ['api_key', 'sk-replacement', 'apiKey'],
    ['api_key_env', 'CUSTOM_REPLACEMENT_KEY', 'apiKeyEnv'],
  ])('does not send preserveApiKey with an explicit %s replacement', async (field, value, wireField) => {
    mockSavedProviderForSave()
    const { api, app } = await mountCatalog()

    api.updateProviderField(field, value)
    await api.saveProvider()

    const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
    const payload = configureCall?.[1] as Record<string, unknown>
    expect(payload).toMatchObject({ providerId: 'custom', model: 'test-model', [wireField]: value })
    expect(payload).not.toHaveProperty('preserveApiKey')
    app.unmount()
  })

  it.each(['api_key', 'api_key_env'])(
    'treats whitespace-only %s input as unchanged when preserving an optional key',
    async field => {
      mockSavedProviderForSave()
      const { api, app } = await mountCatalog()

      api.updateProviderField(field, '   ')
      await api.saveProvider()

      const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
      expect(configureCall?.[1]).toEqual({
        providerId: 'custom',
        model: 'test-model',
        preserveApiKey: true,
      })
      app.unmount()
    },
  )

  it('does not send preserveApiKey for a provider whose key is required', async () => {
    mockSavedProviderForSave({ providerId: 'deepseek', requiresApiKey: true })
    const { api, app } = await mountCatalog()

    await api.saveProvider()

    const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
    const payload = configureCall?.[1] as Record<string, unknown>
    expect(payload).toMatchObject({ providerId: 'deepseek', model: 'test-model' })
    expect(payload).not.toHaveProperty('preserveApiKey')
    app.unmount()
  })

  it('does not carry preserveApiKey across a provider switch', async () => {
    mockSavedProviderForSave({ additionalProviderId: 'custom-alt' })
    const { api, app } = await mountCatalog()

    api.selectProvider('custom-alt')
    api.onProviderChange()
    api.updateProviderField('model', 'other-model')
    await api.saveProvider()

    const configureCall = rpcCall.mock.calls.find(call => call[0] === 'onboarding.provider.configure')
    const payload = configureCall?.[1] as Record<string, unknown>
    expect(payload).toMatchObject({ providerId: 'custom-alt', model: 'other-model' })
    expect(payload).not.toHaveProperty('preserveApiKey')
    app.unmount()
  })
})

describe('useSetupCatalog context-window override', () => {
  const CATALOG = {
    providers: [
      {
        providerId: 'ollama',
        label: 'Ollama',
        runtimeSupported: true,
        requiresApiKey: false,
        deployment: 'local',
        fields: [{ name: 'model', label: 'Model' }],
      },
      {
        providerId: 'vllm',
        label: 'vLLM',
        runtimeSupported: true,
        requiresApiKey: false,
        deployment: 'local',
        fields: [{ name: 'model', label: 'Model' }],
      },
    ],
  }

  function mockCatalog(config: Record<string, unknown>) {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') return CATALOG
      if (method === 'onboarding.status') {
        return { hasConfig: true, llmConfigured: true, llmSource: 'explicit' }
      }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return config
      if (method === 'onboarding.provider.configure') return {}
      if (method === 'config.patch') return { restartRequired: false }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
  }

  it('reseeds the context-window field from the saved override when the provider switches', async () => {
    mockCatalog({
      llm: { provider: 'ollama', model: 'qwen3:8b' },
      models: {
        ollama: { 'qwen3:8b': { context_window: 16384 } },
        vllm: { 'meta/llama-4': { context_window: 65536 } },
      },
    })
    const { api, app } = await mountCatalog()

    expect(api.providerPanel.value.contextWindowTokens).toBe('16384')

    // Switch provider (select + change, mirroring the panel's @change handler).
    api.selectProvider('vllm')
    api.onProviderChange()

    // resetForProvider clears the model field, so the new provider has no saved
    // override for an empty model → field reseeds to blank, not the stale 16384.
    expect(api.providerPanel.value.contextWindowTokens).toBe('')
    app.unmount()
  })

  it('reseeds from the per-model override when the model field changes', async () => {
    mockCatalog({
      llm: { provider: 'ollama', model: 'qwen3:8b' },
      models: {
        ollama: {
          'qwen3:8b': { context_window: 16384 },
          'qwen3:32b': { context_window: 40960 },
        },
      },
    })
    const { api, app } = await mountCatalog()

    expect(api.providerPanel.value.contextWindowTokens).toBe('16384')

    api.updateProviderField('model', 'qwen3:32b')
    expect(api.providerPanel.value.contextWindowTokens).toBe('40960')

    api.updateProviderField('model', 'qwen3:unlisted')
    expect(api.providerPanel.value.contextWindowTokens).toBe('')
    app.unmount()
  })

  it('saves the context-window patch under the currently-selected provider and form model', async () => {
    mockCatalog({ llm: { provider: 'ollama', model: 'qwen3:8b' } })
    const { api, app } = await mountCatalog()

    api.updateContextWindow('32768')
    await api.saveProvider()

    expect(rpcCall).toHaveBeenCalledWith('config.patch', {
      patch: { models: { ollama: { 'qwen3:8b': { context_window: 32768 } } } },
    })
    app.unmount()
  })

  it('skips the context-window patch when the form model is empty', async () => {
    mockCatalog({ llm: { provider: 'ollama', model: '' } })
    const { api, app } = await mountCatalog()

    api.updateContextWindow('32768')
    await api.saveProvider()

    const deepPatchCalls = rpcCall.mock.calls.filter(
      (call: unknown[]) => call[0] === 'config.patch' && 'patch' in ((call[1] as Record<string, unknown>) || {}),
    )
    expect(deepPatchCalls).toHaveLength(0)
    app.unmount()
  })
})

describe('useSetupCatalog providerIsLocal', () => {
  function mockLocalCatalog(providerId: string, deployment: string) {
    rpcCall.mockImplementation(async (method: string) => {
      if (method === 'onboarding.catalog') {
        return {
          providers: [
            {
              providerId,
              label: providerId,
              runtimeSupported: true,
              requiresApiKey: false,
              deployment,
              fields: [{ name: 'model', label: 'Model' }],
            },
          ],
        }
      }
      if (method === 'onboarding.status') return { hasConfig: true, llmConfigured: true, llmSource: 'explicit' }
      if (method === 'channels.status') return { channels: [] }
      if (method === 'config.get') return { llm: { provider: providerId, model: 'm' } }
      throw new Error(`Unexpected RPC method: ${method}`)
    })
  }

  it('treats a custom-deployment provider as local (mirrors backend LOCAL_RUNTIME_PROVIDERS)', async () => {
    // 'custom' is budgeted at the 8192 local default backend-side, so the panel's
    // small-window warning must fire — a non-'local' deployment tag must not
    // suppress the known-local-id match.
    mockLocalCatalog('custom', 'custom')
    const { api, app } = await mountCatalog()

    expect(api.providerPanel.value.providerIsLocal).toBe(true)
    app.unmount()
  })

  it('treats a hosted provider as non-local', async () => {
    mockLocalCatalog('openai', 'hosted')
    const { api, app } = await mountCatalog()

    expect(api.providerPanel.value.providerIsLocal).toBe(false)
    app.unmount()
  })
})
