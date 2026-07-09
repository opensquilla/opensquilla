import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useChatSessionSubscription } from './useChatSessionSubscription'

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
    sessionRunStatus: source => {
      const status = source?.run_status === 'approval_pending' ? 'approval_pending' : 'idle'
      return { status, label: status === 'approval_pending' ? 'Approval pending' : 'Idle', task: null }
    },
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
