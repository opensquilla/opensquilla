import type { Ref } from 'vue'
import type {
  ChatMessage,
  ChatRunStatusSource,
} from '@/types/chat'

export interface ChatUsageAccumulator {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  cost: number | null
  routedTurns: number
  sessionSaved: number
}

export interface UseChatSessionRuntimeOptions {
  sessionKey: Ref<string>
  messages: Ref<ChatMessage[]>
  pendingSessionIntent: Ref<string | null>
  routerDecisionPending: Ref<unknown | null>
  currentEpoch: Ref<number>
  lastStreamSeq: Ref<number>
  activeTaskGroups: Ref<Set<string>>
  aborted: Ref<boolean>
  lastHeaderRole: Ref<string>
  lastHeaderDay: Ref<string>
  usageAccum: Ref<ChatUsageAccumulator>
  usageModel: Ref<string>
  createSessionKey: () => string
  persistSession: (key: string, options?: { updateRoute?: boolean }) => void
  unsubscribeSession: () => void | Promise<void>
  subscribeSession: () => void | Promise<void>
  loadHistory: () => void | Promise<void>
  loadCurrentSessionUsage: () => void | Promise<void>
  applySessionRunState: (source: ChatRunStatusSource | null | undefined) => void
  setCompactInFlight: (active: boolean, key?: string) => void
  hideCompactStatus: () => void
  clearPendingQueue: () => void
  resetSavingsPopupCooldown: () => void
  restoreWidgetState: () => void
  resetStreamLiveTurnState: () => void
}

const EMPTY_USAGE: ChatUsageAccumulator = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  cost: null,
  routedTurns: 0,
  sessionSaved: 0,
}

function createEmptyUsage(): ChatUsageAccumulator {
  return { ...EMPTY_USAGE }
}

export function useChatSessionRuntime(options: UseChatSessionRuntimeOptions) {
  function resetLiveTurnState() {
    options.resetStreamLiveTurnState()
    options.aborted.value = false
    options.routerDecisionPending.value = null
  }

  function resetSessionRuntimeState() {
    options.currentEpoch.value = 0
    options.lastStreamSeq.value = 0
    options.activeTaskGroups.value.clear()
    resetLiveTurnState()
  }

  function resetSessionViewState() {
    options.messages.value = []
    options.lastHeaderRole.value = ''
    options.lastHeaderDay.value = ''
    options.usageAccum.value = createEmptyUsage()
    options.usageModel.value = ''
    options.resetSavingsPopupCooldown()
  }

  function resetCompactAndQueueState() {
    options.setCompactInFlight(false)
    options.hideCompactStatus()
    options.clearPendingQueue()
  }

  function resetCurrentSessionAfterSlash() {
    resetSessionRuntimeState()
    resetCompactAndQueueState()
    resetSessionViewState()
  }

  function switchToSession(key: string) {
    if (!key || key === options.sessionKey.value) return

    options.unsubscribeSession()
    options.persistSession(key)
    resetSessionRuntimeState()
    options.pendingSessionIntent.value = null
    resetCompactAndQueueState()
    options.applySessionRunState({ run_status: 'idle' })
    resetSessionViewState()
    options.restoreWidgetState()
    options.loadCurrentSessionUsage()
    options.subscribeSession()
    options.loadHistory()
  }

  function newSession() {
    options.unsubscribeSession()
    const key = options.createSessionKey()
    options.sessionKey.value = key
    options.persistSession(key)
    resetSessionRuntimeState()
    resetCompactAndQueueState()
    options.pendingSessionIntent.value = 'new_chat'
    resetSessionViewState()
    options.subscribeSession()
    console.info('New chat session:', key)
  }

  function consumeNewChatRouteSignal() {
    newSession()
  }

  return {
    consumeNewChatRouteSignal,
    resetCurrentSessionAfterSlash,
    switchToSession,
    newSession,
  }
}
