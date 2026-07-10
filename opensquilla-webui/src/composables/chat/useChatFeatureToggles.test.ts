import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatFeatureToggles } from './useChatFeatureToggles'
import source from './useChatFeatureToggles.ts?raw'
import type { ModelRoutingMode } from '@/types/modelRouting'

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

describe('useChatFeatureToggles model routing mode', () => {
  it.each([
    [{}, 'off', false, false],
    [{ squilla_router: { enabled: true, rollout_phase: 'observe' } }, 'off', false, false],
    [{ squilla_router: { enabled: true, rollout_phase: 'full' } }, 'squilla_router', true, false],
    [{ squilla_router: { enabled: false }, llm_ensemble: { enabled: true } }, 'llm_ensemble', true, true],
    [{ squilla_router: { enabled: true, rollout_phase: 'full' }, llm_ensemble: { enabled: true } }, 'llm_ensemble', true, true],
  ])('maps backend config %j to mode %s', async (config, mode, routerActive, ensembleActive) => {
    const { api } = createHarness({
      configGetResults: [config],
    })

    await api.loadFeatureToggles()

    expect(api.modelRoutingMode.value).toBe(mode)
    expect(api.routerEnabled.value).toBe(routerActive)
    expect(api.llmEnsembleEnabled.value).toBe(ensembleActive)
  })

  const writeCases: Array<[
    ModelRoutingMode,
    Record<string, unknown>,
    Record<string, unknown>,
  ]> = [
    ['off', {}, {
      'llm_ensemble.enabled': false,
      'squilla_router.enabled': false,
      'squilla_router.rollout_phase': 'observe',
    }],
    ['squilla_router', {}, {
      'llm_ensemble.enabled': false,
      'squilla_router.enabled': true,
      'squilla_router.rollout_phase': 'full',
    }],
    // Static/custom ensemble persists router-disabled — the same
    // exclusive-strategy encoding the Settings "Model strategy" card writes.
    ['llm_ensemble', {
      llm_ensemble: { selection_mode: 'static_openrouter_b5' },
    }, {
      'llm_ensemble.enabled': true,
      'squilla_router.enabled': false,
      'squilla_router.rollout_phase': 'full',
    }],
  ]

  it.each(writeCases)('writes %s through one safe backend patch', async (mode, config, patches) => {
    const { api, rpc } = createHarness({
      configGetResults: [config, config],
    })

    await api.loadFeatureToggles()
    await api.setModelRoutingMode(mode)

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', { patches })
  })

  it.each([
    'static_openrouter_b5',
    'static_tokenrhythm_b5',
    'custom_b5',
  ])('disables the router for known independent ensemble mode %s', async (selectionMode) => {
    const config = {
      squilla_router: { enabled: true, rollout_phase: 'full' },
      llm_ensemble: { enabled: false, selection_mode: selectionMode },
    }
    const { api, rpc } = createHarness({
      configGetResults: [config, config],
    })

    await api.loadFeatureToggles()
    await api.setModelRoutingMode('llm_ensemble')

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: {
        'llm_ensemble.enabled': true,
        'squilla_router.enabled': false,
        'squilla_router.rollout_phase': 'full',
      },
    })
  })

  it('keeps the router enabled for a legacy router_dynamic ensemble', async () => {
    const dynamicConfig = {
      squilla_router: { enabled: true, rollout_phase: 'full' },
      llm_ensemble: { enabled: false, selection_mode: 'router_dynamic' },
    }
    const { api, rpc } = createHarness({
      configGetResults: [
        dynamicConfig,
        {
          ...dynamicConfig,
          llm_ensemble: { enabled: true, selection_mode: 'router_dynamic' },
        },
      ],
    })

    await api.loadFeatureToggles()
    await api.setModelRoutingMode('llm_ensemble')

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: {
        'llm_ensemble.enabled': true,
        'squilla_router.enabled': true,
        'squilla_router.rollout_phase': 'full',
      },
    })
    expect(api.modelRoutingMode.value).toBe('llm_ensemble')
  })

  it.each([
    ['a missing selection mode', undefined],
    ['an unknown selection mode', 'future_ensemble_mode'],
  ])('keeps the router enabled for %s', async (_label, selectionMode) => {
    const llmEnsemble = selectionMode
      ? { enabled: false, selection_mode: selectionMode }
      : { enabled: false }
    const config = {
      squilla_router: { enabled: true, rollout_phase: 'full' },
      llm_ensemble: llmEnsemble,
    }
    const { api, rpc } = createHarness({
      configGetResults: [config, config],
    })

    await api.loadFeatureToggles()
    await api.setModelRoutingMode('llm_ensemble')

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: {
        'llm_ensemble.enabled': true,
        'squilla_router.enabled': true,
        'squilla_router.rollout_phase': 'full',
      },
    })
  })

  it('keeps the three modes mutually exclusive when switching to Squilla Router', async () => {
    const { api, rpc } = createHarness({
      configGetResults: [{ squilla_router: { enabled: true, rollout_phase: 'full' } }],
    })

    await api.setModelRoutingMode('squilla_router')

    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: {
        'llm_ensemble.enabled': false,
        'squilla_router.enabled': true,
        'squilla_router.rollout_phase': 'full',
      },
    })
    expect(api.modelRoutingMode.value).toBe('squilla_router')
  })

  it('optimistically reflects the selected routing mode while a write is pending', async () => {
    const pendingPatch = deferred<void>()
    const { api } = createHarness({
      patchResults: [pendingPatch.promise],
      configGetResults: [{ squilla_router: { enabled: true, rollout_phase: 'full' }, llm_ensemble: { enabled: true } }],
    })

    const write = api.setModelRoutingMode('llm_ensemble')
    await Promise.resolve()

    expect(api.modelRoutingSettingsBusy.value).toBe(true)
    expect(api.modelRoutingMode.value).toBe('llm_ensemble')
    expect(api.routerEnabled.value).toBe(true)
    expect(api.llmEnsembleEnabled.value).toBe(true)

    pendingPatch.resolve(undefined)
    await write
    expect(api.modelRoutingMode.value).toBe('llm_ensemble')
  })

  it('rolls back model routing when the backend patch fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { api } = createHarness({
      configGetResults: [{ squilla_router: { enabled: true, rollout_phase: 'full' } }],
      patchResults: [new Error('patch failed')],
    })

    await api.loadFeatureToggles()
    await api.setModelRoutingMode('off')

    expect(api.modelRoutingMode.value).toBe('squilla_router')
    expect(warn).toHaveBeenCalledWith('Failed to update model routing:', 'patch failed')
  })

  it('uses the post-patch backend value as authoritative', async () => {
    const { api } = createHarness({
      configGetResults: [{ squilla_router: { enabled: false }, llm_ensemble: { enabled: false } }],
    })

    await api.setModelRoutingMode('llm_ensemble')

    expect(api.modelRoutingMode.value).toBe('off')
  })

  it('prevents overlapping model-routing writes while busy', async () => {
    const pendingPatch = deferred<void>()
    const { api, rpc } = createHarness({
      patchResults: [pendingPatch.promise],
      configGetResults: [{ squilla_router: { enabled: true, rollout_phase: 'full' }, llm_ensemble: { enabled: true } }],
    })

    const firstWrite = api.setModelRoutingMode('llm_ensemble')
    await api.setModelRoutingMode('off')
    await Promise.resolve()

    expect(patchCalls(rpc)).toHaveLength(1)
    expect(rpc.call).toHaveBeenCalledWith('config.patch.safe', {
      patches: {
        'llm_ensemble.enabled': true,
        'squilla_router.enabled': true,
        'squilla_router.rollout_phase': 'full',
      },
    })

    pendingPatch.resolve(undefined)
    await firstWrite
  })

  it('does not persist model routing through browser storage APIs', () => {
    const setterStart = source.indexOf('async function setModelRoutingMode')
    const setterEnd = source.indexOf('function bindFeatureRefresh', setterStart)
    const setterSource = source.slice(setterStart, setterEnd)

    expect(setterSource).toContain('llm_ensemble.enabled')
    expect(setterSource).toContain('squilla_router.enabled')
    expect(setterSource).not.toMatch(/localStorage|sessionStorage/)
  })
})
