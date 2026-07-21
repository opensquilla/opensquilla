import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useChatSessionSubscription } from './useChatSessionSubscription'
import type { ChatRunStatus, ChatRunStatusState } from '@/types/chat'

function createSubscription(hasActiveInterrupt = false) {
  const resetStreamLiveTurnState = vi.fn()
  const runStatus = ref({ status: 'idle' as const, label: 'Idle', task: null })
  const rpc = {
    waitForConnection: vi.fn().mockResolvedValue(undefined),
    call: vi.fn().mockResolvedValue({
      subscribed: true,
      status: 'idle',
      current_stream_seq: 0,
      replay_complete: true,
    }),
  }
  const api = useChatSessionSubscription({
    rpc,
    sessionKey: ref('agent:main:webchat:e2eapproval'),
    lastStreamSeq: ref(0),
    runStatus,
    isStreaming: ref(true),
    hasActiveInterrupt: ref(hasActiveInterrupt),
    activeStreamTaskId: ref(''),
    activeTaskGroups: ref(new Set<string>()),
    sessionRunStatus: source => {
      const status = source?.run_status === 'approval_pending' ? 'approval_pending' : 'idle'
      return { status, label: status === 'approval_pending' ? 'Approval pending' : 'Idle', task: null }
    },
    startStreaming: vi.fn(),
    loadHistory: vi.fn(),
    resetStreamIdleTimer: vi.fn(),
    resetStreamLiveTurnState,
  })
  return { api, resetStreamLiveTurnState, runStatus }
}

describe('useChatSessionSubscription', () => {
  it('preserves an interrupt bubble when a late idle subscription snapshot arrives', async () => {
    const { api, resetStreamLiveTurnState, runStatus } = createSubscription(true)

    await api.subscribeSession()

    expect(resetStreamLiveTurnState).not.toHaveBeenCalled()
    expect(runStatus.value.status).toBe('approval_pending')
  })

  it('still clears a stale replay bubble when no interrupt is active', async () => {
    const { api, resetStreamLiveTurnState } = createSubscription(false)

    await api.subscribeSession()

    expect(resetStreamLiveTurnState).toHaveBeenCalledOnce()
  })
})

describe('useChatSessionSubscription', () => {
  it('marks an initial session subscription as hydrating until its snapshot arrives', async () => {
    let resolveSnapshot: ((value: unknown) => void) | undefined
    const snapshot = new Promise(resolve => { resolveSnapshot = resolve })
    const rpc = {
      waitForConnection: vi.fn(async () => {}),
      call: <T = unknown>() => snapshot as Promise<T>,
    }
    const subscription = useChatSessionSubscription({
      rpc,
      sessionKey: ref('agent:main:webchat:test'),
      lastStreamSeq: ref(0),
      runStatus: ref<ChatRunStatus>({ status: 'idle', label: '', task: null }),
      isStreaming: ref(false),
      hasActiveInterrupt: ref(false),
      activeStreamTaskId: ref(''),
      activeTaskGroups: ref(new Set<string>()),
      sessionRunStatus: source => ({
        status: String(source?.run_status || 'idle') as ChatRunStatusState,
        label: '',
        task: source?.active_task || null,
      }),
      startStreaming: vi.fn(),
      loadHistory: vi.fn(),
      resetStreamIdleTimer: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    const pending = subscription.subscribeSession()
    await Promise.resolve()

    expect(subscription.isHydrating.value).toBe(true)

    resolveSnapshot?.({
      subscribed: true,
      run_status: 'cancelled',
      active_task_group_ids: [],
      current_stream_seq: 20,
    })
    await pending

    expect(subscription.isHydrating.value).toBe(false)
  })

  it('hydrates a live backend task into the local streaming state', async () => {
    const isStreaming = ref(false)
    const runStatus = ref<ChatRunStatus>({ status: 'idle', label: '', task: null })
    const activeStreamTaskId = ref('')
    const startStreaming = vi.fn(() => { isStreaming.value = true })
    const rpc = {
      waitForConnection: vi.fn(async () => {}),
      call: async <T = unknown>() => ({
          subscribed: true,
          run_status: 'running',
          active_task: { task_id: 'task-live', status: 'running' },
          current_stream_seq: 12,
        }) as T,
    }

    const subscription = useChatSessionSubscription({
      rpc,
      sessionKey: ref('agent:main:webchat:test'),
      lastStreamSeq: ref(0),
      runStatus,
      isStreaming,
      hasActiveInterrupt: ref(false),
      activeStreamTaskId,
      activeTaskGroups: ref(new Set<string>()),
      sessionRunStatus: source => ({
        status: String(
          source?.run_status || source?.active_task?.status || 'idle',
        ) as ChatRunStatusState,
        label: '',
        task: source?.active_task || null,
      }),
      startStreaming,
      loadHistory: vi.fn(),
      resetStreamIdleTimer: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    await subscription.subscribeSession()

    expect(runStatus.value.status).toBe('running')
    expect(startStreaming).toHaveBeenCalledOnce()
    expect(activeStreamTaskId.value).toBe('task-live')
  })

  it('reconciles stale replayed task groups with an empty authoritative snapshot', async () => {
    const activeTaskGroups = ref(new Set(['stale-group']))
    const runStatus = ref<ChatRunStatus>({ status: 'running', label: '', task: null })
    const rpc = {
      waitForConnection: vi.fn(async () => {}),
      call: async <T = unknown>() => ({
        subscribed: true,
        run_status: 'cancelled',
        active_task: null,
        active_task_group_ids: [],
        current_stream_seq: 18,
      }) as T,
    }

    const subscription = useChatSessionSubscription({
      rpc,
      sessionKey: ref('agent:main:webchat:test'),
      lastStreamSeq: ref(0),
      runStatus,
      isStreaming: ref(false),
      hasActiveInterrupt: ref(false),
      activeStreamTaskId: ref(''),
      activeTaskGroups,
      sessionRunStatus: source => ({
        status: String(source?.run_status || 'idle') as ChatRunStatusState,
        label: '',
        task: source?.active_task || null,
      }),
      startStreaming: vi.fn(),
      loadHistory: vi.fn(),
      resetStreamIdleTimer: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    await subscription.subscribeSession()

    expect(activeTaskGroups.value.size).toBe(0)
    expect(runStatus.value.status).toBe('cancelled')
  })

  it('hydrates active background groups even when the latest parent task is terminal', async () => {
    const activeTaskGroups = ref(new Set<string>())
    const runStatus = ref<ChatRunStatus>({ status: 'idle', label: '', task: null })
    const rpc = {
      waitForConnection: vi.fn(async () => {}),
      call: async <T = unknown>() => ({
        subscribed: true,
        run_status: 'idle',
        active_task: null,
        active_task_group_ids: ['group-live'],
        current_stream_seq: 19,
      }) as T,
    }

    const subscription = useChatSessionSubscription({
      rpc,
      sessionKey: ref('agent:main:webchat:test'),
      lastStreamSeq: ref(0),
      runStatus,
      isStreaming: ref(false),
      hasActiveInterrupt: ref(false),
      activeStreamTaskId: ref(''),
      activeTaskGroups,
      sessionRunStatus: source => ({
        status: String(source?.run_status || 'idle') as ChatRunStatusState,
        label: '',
        task: source?.active_task || null,
      }),
      startStreaming: vi.fn(),
      loadHistory: vi.fn(),
      resetStreamIdleTimer: vi.fn(),
      resetStreamLiveTurnState: vi.fn(),
    })

    await subscription.subscribeSession()

    expect([...activeTaskGroups.value]).toEqual(['group-live'])
    expect(runStatus.value.status).toBe('running')
  })
})
