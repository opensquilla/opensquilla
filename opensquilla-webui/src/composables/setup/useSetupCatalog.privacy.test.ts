// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { useSetupCatalog } from './useSetupCatalog'

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
