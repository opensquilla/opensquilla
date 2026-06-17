import { ref, type Ref } from 'vue'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface ChatUsageAccumulator {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  cost: number | null
  routedTurns: number
  sessionSaved: number
}

export interface UseChatUsageWidgetOptions {
  rpc: RpcClient
  sessionKey: Ref<string>
  tokenVizEnabled: () => boolean
}

interface PersistedUsageWidget {
  input?: number
  output?: number
  cost?: number | null
  model?: string
}

interface UsageStatusSession {
  session?: string
  sessionKey?: string
  key?: string
  input_tokens?: number
  inputTokens?: number
  output_tokens?: number
  outputTokens?: number
  cache_read_tokens?: number
  cacheReadTokens?: number
  cache_write_tokens?: number
  cacheWriteTokens?: number
  cost_usd?: number
  costUsd?: number
  model?: string
}

interface UsageStatusResponse {
  sessions?: UsageStatusSession[]
}

export function createEmptyUsageAccumulator(): ChatUsageAccumulator {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    cost: null,
    routedTurns: 0,
    sessionSaved: 0,
  }
}

export function useChatUsageWidget(options: UseChatUsageWidgetOptions) {
  const usageAccum = ref<ChatUsageAccumulator>(createEmptyUsageAccumulator())
  const usageModel = ref('')
  const savingsPopupLastTs = ref(0)
  const lastSavingsPopupIdentity = ref('')

  function resetSavingsPopupCooldown() {
    savingsPopupLastTs.value = 0
    lastSavingsPopupIdentity.value = ''
  }

  function saveWidgetState() {
    if (!options.tokenVizEnabled()) return
    if (!options.sessionKey.value) return
    try {
      localStorage.setItem('opensquilla-widget:' + options.sessionKey.value, JSON.stringify({
        input: usageAccum.value.input,
        output: usageAccum.value.output,
        cost: usageAccum.value.cost,
        model: usageModel.value,
      }))
    } catch {
      // Ignore storage failures in private or restricted contexts.
    }
  }

  function restoreWidgetState() {
    if (!options.tokenVizEnabled()) return
    if (!options.sessionKey.value) return
    try {
      const raw = localStorage.getItem('opensquilla-widget:' + options.sessionKey.value)
      if (raw) {
        const d = JSON.parse(raw) as PersistedUsageWidget
        usageAccum.value.input = d.input || 0
        usageAccum.value.output = d.output || 0
        usageAccum.value.cost = d.cost || null
        usageModel.value = d.model || ''
      }
    } catch {
      // Ignore malformed or unavailable persisted widget state.
    }
  }

  async function loadCurrentSessionUsage() {
    if (!options.sessionKey.value) return
    try {
      await options.rpc.waitForConnection()
      const usage = await options.rpc.call<UsageStatusResponse>('usage.status', { sessionKey: options.sessionKey.value })
      const sessions = usage?.sessions || []
      const current = sessions.find(s => (s.session || s.sessionKey || s.key) === options.sessionKey.value)
      if (current) {
        usageAccum.value.input = Number(current.input_tokens || current.inputTokens || 0)
        usageAccum.value.output = Number(current.output_tokens || current.outputTokens || 0)
        usageAccum.value.cacheRead = Number(current.cache_read_tokens || current.cacheReadTokens || 0)
        usageAccum.value.cacheWrite = Number(current.cache_write_tokens || current.cacheWriteTokens || 0)
        const costVal = Number(current.cost_usd || current.costUsd || 0)
        usageAccum.value.cost = costVal > 0 ? costVal : null
        usageModel.value = current.model || ''
        saveWidgetState()
      }
    } catch {
      // Usage endpoint may be unavailable in older gateways.
    }
  }

  return {
    usageAccum,
    usageModel,
    resetSavingsPopupCooldown,
    saveWidgetState,
    restoreWidgetState,
    loadCurrentSessionUsage,
  }
}
