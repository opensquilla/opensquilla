import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useChatSessionRuntime, type ChatUsageAccumulator } from './useChatSessionRuntime'
import type { ChatMessage } from '@/types/chat'

function emptyUsage(): ChatUsageAccumulator {
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

describe('useChatSessionRuntime', () => {
  it('does not load or hand control back until the new session subscription completes', async () => {
    const sessionKey = ref('agent:main:webchat:old')
    let finishSubscribe: (() => void) | undefined
    const subscribeSession = vi.fn(() => new Promise<void>((resolve) => {
      finishSubscribe = resolve
    }))
    const loadHistory = vi.fn()
    const persistSession = vi.fn((key: string) => {
      sessionKey.value = key
    })
    const runtime = useChatSessionRuntime({
      sessionKey,
      messages: ref<ChatMessage[]>([]),
      pendingSessionIntent: ref(null),
      routerDecisionPending: ref(null),
      currentEpoch: ref(0),
      lastStreamSeq: ref(0),
      activeTaskGroups: ref(new Set<string>()),
      aborted: ref(false),
      lastHeaderRole: ref(''),
      lastHeaderDay: ref(''),
      usageAccum: ref(emptyUsage()),
      usageModel: ref(''),
      createSessionKey: () => 'agent:main:webchat:draft',
      persistSession,
      unsubscribeSession: vi.fn(),
      subscribeSession,
      loadHistory,
      loadCurrentSessionUsage: vi.fn(),
      applySessionRunState: vi.fn(),
      setCompactInFlight: vi.fn(),
      hideCompactStatus: vi.fn(),
      clearPendingQueue: vi.fn(),
      resetSavingsPopupCooldown: vi.fn(),
      restoreWidgetState: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    const switched = runtime.switchToSession('agent:main:webchat:new')
    expect(sessionKey.value).toBe('agent:main:webchat:new')
    expect(subscribeSession).toHaveBeenCalledOnce()
    expect(loadHistory).not.toHaveBeenCalled()

    finishSubscribe?.()
    await expect(switched).resolves.toBe(true)
    expect(loadHistory).toHaveBeenCalledOnce()
  })

  it('does not report a completed switch when session subscription fails', async () => {
    const sessionKey = ref('agent:main:webchat:old')
    const loadHistory = vi.fn()
    const runtime = useChatSessionRuntime({
      sessionKey,
      messages: ref<ChatMessage[]>([]),
      pendingSessionIntent: ref(null),
      routerDecisionPending: ref(null),
      currentEpoch: ref(0),
      lastStreamSeq: ref(0),
      activeTaskGroups: ref(new Set<string>()),
      aborted: ref(false),
      lastHeaderRole: ref(''),
      lastHeaderDay: ref(''),
      usageAccum: ref(emptyUsage()),
      usageModel: ref(''),
      createSessionKey: () => 'agent:main:webchat:draft',
      persistSession: key => { sessionKey.value = key },
      unsubscribeSession: vi.fn(),
      subscribeSession: vi.fn(async () => false),
      loadHistory,
      loadCurrentSessionUsage: vi.fn(),
      applySessionRunState: vi.fn(),
      setCompactInFlight: vi.fn(),
      hideCompactStatus: vi.fn(),
      clearPendingQueue: vi.fn(),
      resetSavingsPopupCooldown: vi.fn(),
      restoreWidgetState: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    await expect(runtime.switchToSession('agent:main:webchat:new')).resolves.toBe(false)
    expect(loadHistory).not.toHaveBeenCalled()
  })
})
