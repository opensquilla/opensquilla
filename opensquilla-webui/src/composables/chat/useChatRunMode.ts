import { computed, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { HelloAuthInfo, RunMode, RunModePolicyInfo } from '@/types/rpc'

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
  waitForConnection?: () => Promise<void>
}

type SandboxSetupStatus = {
  state?: string
  message?: string
  detail?: string
  [key: string]: unknown
} | null

export interface UseChatRunModeOptions {
  rpc: RpcClient
  auth?: Readonly<Ref<HelloAuthInfo | null>>
  pushToast?: (message: string, options?: { tone?: 'info' | 'danger'; duration?: number }) => void
}

const RUN_MODES: RunMode[] = ['standard', 'trusted', 'full']

export function normalizeRunMode(mode: unknown, fallback: RunMode = 'trusted'): RunMode {
  const value = String(mode || '').trim().toLowerCase().replace(/_/g, '-')
  if (value === 'standard' || value === 'standard-sandbox') return 'standard'
  if (value === 'trusted' || value === 'trust' || value === 'trusted-sandbox') return 'trusted'
  if (value === 'full' || value === 'full-host-access' || value === 'host') return 'full'
  return fallback
}

export function useChatRunMode(options: UseChatRunModeOptions) {
  const runModePolicy = computed<RunModePolicyInfo | null>(() => {
    return options.auth?.value?.runModePolicy || null
  })
  const allowedRunModes = computed<RunMode[]>(() => {
    const policyAllowed = runModePolicy.value?.allowedRunModes
    if (!policyAllowed) return [...RUN_MODES]
    const allowed = policyAllowed
      .map(mode => normalizeRunMode(mode))
      .filter((mode, index, modes) => RUN_MODES.includes(mode) && modes.indexOf(mode) === index)
    return allowed.length ? allowed : [...RUN_MODES]
  })
  const defaultRunMode = computed<RunMode>(() => {
    const allowed = allowedRunModes.value
    const policyDefault = runModePolicy.value?.defaultRunMode
    if (policyDefault) {
      const normalized = normalizeRunMode(policyDefault)
      if (allowed.includes(normalized)) return normalized
    }
    if (allowed.includes('full')) return 'full'
    if (allowed.includes('trusted')) return 'trusted'
    return allowed[0] || 'trusted'
  })
  const fullHostAccessDisabledReason = computed(() => {
    return runModePolicy.value?.fullHostAccessDisabledReason || null
  })
  const runMode = ref<RunMode>(defaultRunMode.value)
  const sandboxSetupStatus = ref<SandboxSetupStatus>(null)
  const sandboxSetupBusy = ref(false)
  const sandboxSetupPromptDismissed = ref(false)
  const pendingSandboxSetupMode = ref<RunMode | ''>('')
  let sandboxSetupRequestSeq = 0

  function modeAllowed(mode: RunMode): boolean {
    return allowedRunModes.value.includes(mode)
  }

  function clampRunMode(mode: unknown): RunMode {
    const normalized = normalizeRunMode(mode, defaultRunMode.value)
    return modeAllowed(normalized) ? normalized : defaultRunMode.value
  }

  watch([allowedRunModes, defaultRunMode], () => {
    runMode.value = clampRunMode(runMode.value)
    if (pendingSandboxSetupMode.value && !modeAllowed(pendingSandboxSetupMode.value)) {
      pendingSandboxSetupMode.value = ''
    }
  }, { immediate: true })

  function isSandboxSetupReadyPayload(payload: SandboxSetupStatus): boolean {
    return String(payload?.state || '').toLowerCase() === 'ready'
  }

  function sandboxSetupReadyForMode(mode: RunMode): boolean {
    if (mode === 'full') return true
    return isSandboxSetupReadyPayload(sandboxSetupStatus.value)
  }

  function sandboxSetupMessage(payload: SandboxSetupStatus): string {
    if (!payload || typeof payload !== 'object') return ''
    if (payload.state === 'failed' && payload.message && payload.detail) {
      return `${payload.message}: ${payload.detail}`
    }
    return String(payload.message || payload.detail || '')
  }

  const sandboxSetupVisible = computed(() => {
    const setupKnown = sandboxSetupStatus.value !== null
    const setupReady = isSandboxSetupReadyPayload(sandboxSetupStatus.value)
    const pendingPrompt = !!pendingSandboxSetupMode.value
    const optionalPrompt = setupKnown && !sandboxSetupPromptDismissed.value
    return !setupReady && (pendingPrompt || optionalPrompt)
  })

  const sandboxSetupDetail = computed(() => {
    return sandboxSetupMessage(sandboxSetupStatus.value)
  })

  async function loadSandboxSetupStatus(optionsArg: { mode?: RunMode; showPrompt?: boolean } = {}) {
    const mode = clampRunMode(optionsArg.mode || runMode.value)
    if (optionsArg.showPrompt) sandboxSetupPromptDismissed.value = false
    const requestSeq = ++sandboxSetupRequestSeq
    try {
      await options.rpc.waitForConnection?.()
      const payload = await options.rpc.call<SandboxSetupStatus>('sandbox.setup.status', {})
      if (requestSeq !== sandboxSetupRequestSeq) return sandboxSetupStatus.value
      sandboxSetupStatus.value = payload || null
      if (isSandboxSetupReadyPayload(sandboxSetupStatus.value) && pendingSandboxSetupMode.value) {
        const pending = pendingSandboxSetupMode.value
        pendingSandboxSetupMode.value = ''
        runMode.value = clampRunMode(pending)
      } else if (mode === 'full') {
        runMode.value = clampRunMode('full')
      }
      return sandboxSetupStatus.value
    } catch {
      return sandboxSetupStatus.value
    }
  }

  async function ensureSandboxSetupOnly(): Promise<boolean> {
    if (sandboxSetupReadyForMode('standard')) return true
    sandboxSetupBusy.value = true
    try {
      await options.rpc.waitForConnection?.()
      const payload = await options.rpc.call<SandboxSetupStatus>('sandbox.setup.ensure', {})
      sandboxSetupStatus.value = payload || null
      const ready = isSandboxSetupReadyPayload(sandboxSetupStatus.value)
      if (ready && pendingSandboxSetupMode.value) {
        const pendingMode = pendingSandboxSetupMode.value
        pendingSandboxSetupMode.value = ''
        runMode.value = clampRunMode(pendingMode)
      }
      options.pushToast?.(ready ? 'Sandbox established' : 'Sandbox setup is not ready', {
        tone: ready ? undefined : 'info',
        duration: 2200,
      })
      return ready
    } catch (err: unknown) {
      const details = err && typeof err === 'object' && 'details' in err
        ? (err as { details?: SandboxSetupStatus }).details
        : null
      if (details) sandboxSetupStatus.value = details
      const message = err instanceof Error ? err.message : 'unknown error'
      options.pushToast?.('Sandbox setup failed: ' + message, { tone: 'danger', duration: 3500 })
      return false
    } finally {
      sandboxSetupBusy.value = false
    }
  }

  async function requestSandboxSetupForMode(mode: RunMode): Promise<boolean> {
    mode = normalizeRunMode(mode)
    if (mode === 'full') return true
    if (sandboxSetupReadyForMode(mode)) return true
    sandboxSetupPromptDismissed.value = false
    const status = await loadSandboxSetupStatus({ mode })
    if (isSandboxSetupReadyPayload(status)) return true
    pendingSandboxSetupMode.value = mode
    options.pushToast?.('Sandbox setup is required before switching modes.', { tone: 'info', duration: 2400 })
    return false
  }

  async function setRunMode(mode: RunMode, toast = true) {
    const normalized = normalizeRunMode(mode)
    if (!modeAllowed(normalized)) {
      runMode.value = defaultRunMode.value
      options.pushToast?.('Full Host Access requires owner permission.', { tone: 'info', duration: 2400 })
      return false
    }
    if (!(await requestSandboxSetupForMode(normalized))) return false
    runMode.value = normalized
    if (toast) {
      const labels: Record<RunMode, string> = {
        standard: 'Standard-Sandbox',
        trusted: 'Trusted-Sandbox',
        full: 'Full Host Access',
      }
      options.pushToast?.(`Run Mode: ${labels[normalized]}`, {
        tone: normalized === 'full' ? 'info' : undefined,
        duration: 1800,
      })
    }
    return true
  }

  function dismissSandboxSetupPrompt() {
    sandboxSetupPromptDismissed.value = true
    pendingSandboxSetupMode.value = ''
    runMode.value = defaultRunMode.value
  }

  return {
    allowedRunModes,
    defaultRunMode,
    fullHostAccessDisabledReason,
    runMode,
    runModePolicy,
    sandboxSetupBusy,
    sandboxSetupDetail,
    sandboxSetupPromptDismissed,
    sandboxSetupVisible,
    dismissSandboxSetupPrompt,
    ensureSandboxSetupOnly,
    isSandboxSetupReadyPayload,
    loadSandboxSetupStatus,
    modeAllowed,
    normalizeRunMode,
    requestSandboxSetupForMode,
    sandboxSetupReadyForMode,
    setRunMode,
  }
}
