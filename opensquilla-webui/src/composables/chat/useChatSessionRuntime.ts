import type { Ref } from 'vue'
import type {
  ChatMessage,
  ChatRunStatusSource,
} from '@/types/chat'
import type { PersistSessionOptions } from '@/composables/chat/useChatSessionRoute'
import type { SessionSubscriptionOutcome } from '@/composables/chat/useChatSessionSubscription'

export interface ChatUsageAccumulator {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  cost: number | null
  routedTurns: number
  sessionSaved: number
}

export interface ResponseSessionAdoptionResult {
  authoritativeIdle: boolean
  backgroundOnly: boolean
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
  createSessionKey: (agentId?: string) => string
  persistSession: (key: string, options?: PersistSessionOptions) => void
  unsubscribeSession: () => void | Promise<void>
  subscribeSession: () =>
    | boolean
    | void
    | SessionSubscriptionOutcome
    | Promise<boolean | void | SessionSubscriptionOutcome>
  loadHistory: () => void | Promise<void>
  loadCurrentSessionUsage: () => void | Promise<void>
  applySessionRunState: (source: ChatRunStatusSource | null | undefined) => void
  setCompactInFlight: (active: boolean, key?: string) => void
  hideCompactStatus: () => void
  clearPendingQueue: () => void
  switchPendingQueue?: (targetSessionKey: string) => void
  adoptPendingQueue?: (targetSessionKey: string, ownerRequestId: string) => void
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

  function resetCompactState() {
    options.setCompactInFlight(false)
    options.hideCompactStatus()
  }

  function resetCurrentSessionAfterSlash() {
    resetSessionRuntimeState()
    resetCompactState()
    options.clearPendingQueue()
    resetSessionViewState()
  }

  function switchSession(
    key: string,
    pendingQueuePolicy: { kind: 'navigate' },
  ): Promise<boolean>
  function switchSession(
    key: string,
    pendingQueuePolicy: { kind: 'response_handoff'; ownerRequestId: string },
  ): Promise<ResponseSessionAdoptionResult | undefined>
  async function switchSession(
    key: string,
    pendingQueuePolicy:
      | { kind: 'navigate' }
      | { kind: 'response_handoff'; ownerRequestId: string },
  ): Promise<boolean | ResponseSessionAdoptionResult | undefined> {
    if (!key || key === options.sessionKey.value) {
      return pendingQueuePolicy.kind === 'navigate' ? false : undefined
    }

    options.unsubscribeSession()
    resetCompactState()
    if (pendingQueuePolicy.kind === 'response_handoff') {
      options.adoptPendingQueue?.(key, pendingQueuePolicy.ownerRequestId)
    } else {
      if (options.switchPendingQueue) options.switchPendingQueue(key)
      else options.clearPendingQueue()
    }
    options.persistSession(key, { source: 'runtime.switchToSession' })
    resetSessionRuntimeState()
    options.pendingSessionIntent.value = null
    options.applySessionRunState({ run_status: 'idle' })
    resetSessionViewState()
    options.restoreWidgetState()
    options.loadCurrentSessionUsage()
    if (pendingQueuePolicy.kind === 'navigate') {
      const subscriptionOutcome = await options.subscribeSession()
      if (subscriptionOutcome === false || !isAuthoritativeSubscription(subscriptionOutcome)) {
        return false
      }
      if (options.sessionKey.value !== key) return false
      await options.loadHistory()
      return true
    }

    const [subscriptionOutcome] = await Promise.all([
      options.subscribeSession(),
      options.loadHistory(),
    ])
    return {
      authoritativeIdle: isSubscriptionOutcome(subscriptionOutcome)
        && subscriptionOutcome.authoritative === true
        && subscriptionOutcome.live === false,
      backgroundOnly: isSubscriptionOutcome(subscriptionOutcome)
        && subscriptionOutcome.authoritative === true
        && subscriptionOutcome.backgroundOnly === true,
    }
  }

  function switchToSession(key: string) {
    return switchSession(key, { kind: 'navigate' })
  }

  function adoptResponseSession(key: string, ownerRequestId: string) {
    return switchSession(key, { kind: 'response_handoff', ownerRequestId })
  }

  // Drafts keep their provisional key out of the URL and local storage; it
  // only persists once the first message actually goes out.
  function startDraftSession(agentId?: string) {
    options.unsubscribeSession()
    const key = options.createSessionKey(agentId)
    resetCompactState()
    if (options.switchPendingQueue) options.switchPendingQueue(key)
    else options.clearPendingQueue()
    options.sessionKey.value = key
    resetSessionRuntimeState()
    options.pendingSessionIntent.value = 'new_chat'
    resetSessionViewState()
    options.subscribeSession()
  }

  return {
    resetCurrentSessionAfterSlash,
    startDraftSession,
    switchToSession,
    adoptResponseSession,
  }
}

function isSubscriptionOutcome(
  value: boolean | void | SessionSubscriptionOutcome,
): value is SessionSubscriptionOutcome {
  return typeof value === 'object' && value !== null
}

function isAuthoritativeSubscription(
  value: boolean | void | SessionSubscriptionOutcome,
): boolean {
  return !isSubscriptionOutcome(value) || value.authoritative
}
