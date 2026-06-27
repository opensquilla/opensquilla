import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatFeatureToggles } from './useChatFeatureToggles'
import source from './useChatFeatureToggles.ts?raw'

type RpcResult = Record<string, unknown> | Error | Promise<unknown>

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function createHarness(options: {
  configGetResults?: RpcResult[]
  patchResults?: RpcResult[]
} = {}) {
  const configGetResults = [...(options.configGetResults ?? [{}])]
  const patchResults = [...(options.patchResults ?? [])]
  const waitForConnection = vi.fn(async () => {})
  const setGlobalElevatedMode = vi.fn()
  const loadCurrentSessionUsage = vi.fn()
  const call = vi.fn(async (method: string, _params?: Record<string, unknown>): Promise<unknown> => {
    if (method === 'config.get') {
      const result = configGetResults.shift() ?? {}
      if (result instanceof Error) throw result
      return await Promise.resolve(result)
    }
    if (method === 'config.patch.safe') {
      const result = patchResults.shift()
      if (result instanceof Error) throw result
      await Promise.resolve(result)
      return { ok: true }
    }
    throw new Error(`Unexpected RPC method: ${method}`)
  })
  const rpc = {
    waitForConnection,
    call: call as <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>,
  }
  const api = useChatFeatureToggles({
    rpc,
    setGlobalElevatedMode,
    loadCurrentSessionUsage,
  })
  return { api, rpc: { waitForConnection, call }, setGlobalElevatedMode, loadCurrentSessionUsage }
}

function patchCalls(rpc: ReturnType<typeof createHarness>['rpc']) {
  return rpc.call.mock.calls.filter(([method]) => method === 'config.patch.safe')
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useChatFeatureToggles coding mode', () => {
  it('reads enabled coding mode from backend config', async () => {
    const { api } = createHarness({
      configGetResults: [{ skills: { coding_mode: true } }],
    })

    await api.loadFeatureToggles()

    expect(api.codingModeEnabled.value).toBe(true)
  })

  it.each([
    {},
    { skills: {} },
  ])('defaults missing coding mode to off for %j', async (config) => {
    const { api } = createHarness({
      configGetResults: [config],
    })

    await api.loadFeatureToggles()

    expect(api.codingModeEnabled.value).toBe(false)
  })

  it('writes coding mode on with the safe backend patch path', async () => {
    const { api, rpc } = createHarness({
      configGetResults: [{ skills: { coding_mode: true } }],
    })

    await api.setCodingModeEnabled(true)

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: { 'skills.coding_mode': true },
    })
  })

  it('writes coding mode off with the safe backend patch path', async () => {
    const { api, rpc } = createHarness({
      configGetResults: [{ skills: { coding_mode: false } }],
    })

    await api.setCodingModeEnabled(false)

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: { 'skills.coding_mode': false },
    })
  })

  it('strictly reloads backend config after a successful write', async () => {
    const { api, rpc } = createHarness({
      configGetResults: [{ skills: { coding_mode: true } }],
    })

    await api.setCodingModeEnabled(true)

    const calls = rpc.call.mock.calls
    const patchIndex = calls.findIndex(([method]) => method === 'config.patch.safe')
    const getIndex = calls.findIndex(([method], index) => index > patchIndex && method === 'config.get')
    expect(patchIndex).toBeGreaterThanOrEqual(0)
    expect(getIndex).toBeGreaterThan(patchIndex)
    expect(api.codingModeEnabled.value).toBe(true)
  })

  it('applies the strict post-patch config through the shared feature mapping', async () => {
    const { api, setGlobalElevatedMode } = createHarness({
      configGetResults: [{
        skills: { coding_mode: true },
        squilla_router: { enabled: true, rollout_phase: 'full' },
        permissions: { default_mode: 'bypass' },
      }],
    })

    await api.setCodingModeEnabled(true)

    expect(api.codingModeEnabled.value).toBe(true)
    expect(api.routerEnabled.value).toBe(true)
    expect(setGlobalElevatedMode).toHaveBeenCalledWith('bypass')
  })

  it('keeps coding mode backend-confirmed while a write is pending', async () => {
    const pendingPatch = deferred<void>()
    const { api } = createHarness({
      patchResults: [pendingPatch.promise],
      configGetResults: [{ skills: { coding_mode: true } }],
    })

    const write = api.setCodingModeEnabled(true)
    await Promise.resolve()

    expect(api.codingModeSettingsBusy.value).toBe(true)
    expect(api.codingModeEnabled.value).toBe(false)

    pendingPatch.resolve(undefined)
    await write
    expect(api.codingModeEnabled.value).toBe(true)
  })

  it('rolls back when the backend patch fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { api } = createHarness({
      patchResults: [new Error('patch failed')],
    })

    await api.setCodingModeEnabled(true)

    expect(api.codingModeEnabled.value).toBe(false)
    expect(warn).toHaveBeenCalledWith('Failed to update Coding mode:', 'patch failed')
  })

  it('rolls back when post-patch config reload fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { api } = createHarness({
      configGetResults: [new Error('reload failed')],
    })

    await api.setCodingModeEnabled(true)

    expect(api.codingModeEnabled.value).toBe(false)
    expect(warn).toHaveBeenCalledWith('Failed to update Coding mode:', 'reload failed')
  })

  it('uses the post-patch backend value as authoritative', async () => {
    const { api } = createHarness({
      configGetResults: [{ skills: { coding_mode: false } }],
    })

    await api.setCodingModeEnabled(true)

    expect(api.codingModeEnabled.value).toBe(false)
  })

  it('prevents overlapping coding mode writes while busy', async () => {
    const pendingPatch = deferred<void>()
    const { api, rpc } = createHarness({
      patchResults: [pendingPatch.promise],
      configGetResults: [{ skills: { coding_mode: true } }],
    })

    const firstWrite = api.setCodingModeEnabled(true)
    await api.setCodingModeEnabled(false)
    await Promise.resolve()

    expect(patchCalls(rpc)).toHaveLength(1)
    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: { 'skills.coding_mode': true },
    })

    pendingPatch.resolve(undefined)
    await firstWrite
  })

  it('does not persist coding mode through browser storage APIs', () => {
    const setterStart = source.indexOf('async function setCodingModeEnabled')
    const setterEnd = source.indexOf('function bindFeatureRefresh', setterStart)
    const setterSource = source.slice(setterStart, setterEnd)

    expect(setterSource).toContain('skills.coding_mode')
    expect(setterSource).not.toMatch(/localStorage|sessionStorage/)
  })
})
