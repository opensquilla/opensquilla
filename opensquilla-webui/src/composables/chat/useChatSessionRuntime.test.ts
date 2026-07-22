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
  it('starts history immediately but does not hand control back until subscription completes', async () => {
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
    expect(loadHistory).toHaveBeenCalledOnce()

    finishSubscribe?.()
    await expect(switched).resolves.toBe(true)
    expect(loadHistory).toHaveBeenCalledOnce()
  })

  it('loads history and reports non-authoritative when subscription rejects', async () => {
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
      subscribeSession: vi.fn(async () => { throw new Error('offline') }),
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
    expect(loadHistory).toHaveBeenCalledOnce()
  })

  it('loads persisted history but rejects a structured non-authoritative switch', async () => {
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
      subscribeSession: vi.fn(async () => ({
        authoritative: false,
        live: false,
        backgroundOnly: false,
      })),
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
    expect(loadHistory).toHaveBeenCalledOnce()
  })

  it('rechecks draft ownership after unsubscribe before rebinding without persistence', async () => {
    const sessionKey = ref('agent:main:webchat:local-draft')
    const pendingSessionIntent = ref<string | null>('new_chat')
    let pristine = true
    let finishUnsubscribe: (() => void) | undefined
    const firstUnsubscribe = new Promise<void>((resolve) => { finishUnsubscribe = resolve })
    const unsubscribeSession = vi.fn()
      .mockImplementationOnce(() => firstUnsubscribe)
      .mockResolvedValueOnce(undefined)
    const subscribeSession = vi.fn(async () => ({
      authoritative: true,
      live: false,
      backgroundOnly: false,
    }))
    const switchPendingQueue = vi.fn()
    const persistSession = vi.fn()
    const runtime = useChatSessionRuntime({
      sessionKey,
      messages: ref<ChatMessage[]>([]),
      pendingSessionIntent,
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
      unsubscribeSession,
      subscribeSession,
      loadHistory: vi.fn(),
      loadCurrentSessionUsage: vi.fn(),
      applySessionRunState: vi.fn(),
      setCompactInFlight: vi.fn(),
      hideCompactStatus: vi.fn(),
      clearPendingQueue: vi.fn(),
      switchPendingQueue,
      resetSavingsPopupCooldown: vi.fn(),
      restoreWidgetState: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    const staleRebind = runtime.rebindDraftSession(
      'agent:main:webchat:server-draft',
      () => pristine,
    )
    pristine = false
    finishUnsubscribe?.()
    await expect(staleRebind).resolves.toBe(false)
    expect(sessionKey.value).toBe('agent:main:webchat:local-draft')
    expect(subscribeSession).toHaveBeenCalledOnce()

    pristine = true
    await expect(runtime.rebindDraftSession(
      'agent:main:webchat:server-draft',
      () => pristine,
    )).resolves.toEqual({ authoritative: true, live: false, backgroundOnly: false })
    expect(sessionKey.value).toBe('agent:main:webchat:server-draft')
    expect(pendingSessionIntent.value).toBe('new_chat')
    expect(switchPendingQueue).toHaveBeenCalledWith('agent:main:webchat:server-draft')
    expect(persistSession).not.toHaveBeenCalled()
    expect(subscribeSession).toHaveBeenCalledTimes(2)
  })
})
