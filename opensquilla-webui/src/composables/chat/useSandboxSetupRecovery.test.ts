import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useSandboxSetupRecovery } from './useSandboxSetupRecovery'

afterEach(() => {
  vi.useRealTimers()
})

function payload(state: string, platform = 'win32') {
  return { state, platform, message: state, requiresAdmin: false }
}

describe('useSandboxSetupRecovery', () => {
  it('hides ready status and never changes the selected run mode', async () => {
    const runMode = ref<'standard' | 'trusted' | 'full'>('trusted')
    const rpc = { call: vi.fn(async () => payload('ready')) }
    const scope = effectScope()
    const recovery = scope.run(() => useSandboxSetupRecovery({
      rpc,
      connectionState: ref('connected'),
      runMode,
    }))!

    await vi.waitFor(() => expect(rpc.call).toHaveBeenCalledWith('sandbox.setup.status'))
    expect(recovery.status.value?.state).toBe('ready')
    expect(recovery.visible.value).toBe(false)
    expect(runMode.value).toBe('trusted')
    scope.stop()
  })

  it('short-polls setting_up until the setup becomes ready', async () => {
    vi.useFakeTimers()
    const rpc = {
      call: vi.fn()
        .mockResolvedValueOnce(payload('setting_up'))
        .mockResolvedValueOnce(payload('ready')),
    }
    const scope = effectScope()
    const recovery = scope.run(() => useSandboxSetupRecovery({
      rpc,
      connectionState: ref('connected'),
      runMode: ref('standard'),
    }))!
    await vi.runAllTicks()
    await Promise.resolve()
    expect(recovery.status.value?.state).toBe('setting_up')
    expect(recovery.visible.value).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    expect(recovery.status.value?.state).toBe('ready')
    expect(recovery.visible.value).toBe(false)
    scope.stop()
  })

  it('offers owner setup only for Windows not_setup/failed states', async () => {
    const rpc = {
      call: vi.fn(async (method: string) =>
        method === 'sandbox.setup.ensure' ? payload('ready') : payload('not_setup')),
    }
    const scope = effectScope()
    const recovery = scope.run(() => useSandboxSetupRecovery({
      rpc,
      connectionState: ref('connected'),
      runMode: ref('standard'),
    }))!
    await vi.waitFor(() => expect(recovery.canSetup.value).toBe(true))

    await recovery.ensureSetup()
    expect(rpc.call).toHaveBeenCalledWith('sandbox.setup.ensure')
    expect(recovery.status.value?.state).toBe('ready')
    expect(recovery.visible.value).toBe(false)
    scope.stop()
  })

  it('shows unavailable as explanation-only and resets dismissal on state/mode change', async () => {
    const runMode = ref<'standard' | 'trusted' | 'full'>('trusted')
    const connectionState = ref('connected')
    const rpc = { call: vi.fn(async () => payload('unavailable', 'darwin')) }
    const scope = effectScope()
    const recovery = scope.run(() => useSandboxSetupRecovery({ rpc, connectionState, runMode }))!
    await vi.waitFor(() => expect(recovery.visible.value).toBe(true))
    expect(recovery.canSetup.value).toBe(false)

    recovery.dismiss()
    expect(recovery.visible.value).toBe(false)
    runMode.value = 'standard'
    await vi.waitFor(() => expect(recovery.visible.value).toBe(true))
    expect(runMode.value).toBe('standard')
    scope.stop()
  })
})
