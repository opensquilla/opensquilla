import type { Ref } from 'vue'
import type {
  ChatRunStatus,
  ChatRunStatusSource,
} from '@/types/chat'
import type {
  SessionMessagesSubscribeParams,
  SessionMessagesSubscribeResponse,
} from '@/types/rpc'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface UseChatSessionSubscriptionOptions {
  rpc: RpcClient
  sessionKey: Ref<string>
  lastStreamSeq: Ref<number>
  runStatus: Ref<ChatRunStatus>
  isStreaming: Ref<boolean>
  sessionRunStatus: (source: ChatRunStatusSource | null | undefined) => ChatRunStatus
  loadHistory: () => void | Promise<void>
  resetStreamIdleTimer: () => void
}

export function useChatSessionSubscription(options: UseChatSessionSubscriptionOptions) {
  async function subscribeSession() {
    if (!options.sessionKey.value) return
    const key = options.sessionKey.value
    const sinceStreamSeq = options.lastStreamSeq.value
    try {
      await options.rpc.waitForConnection()
      if (key !== options.sessionKey.value) return
      const params: SessionMessagesSubscribeParams = { key, since_stream_seq: sinceStreamSeq }
      const res = await options.rpc.call<SessionMessagesSubscribeResponse>('sessions.messages.subscribe', params)
      if (key !== options.sessionKey.value) return
      if (res && res.subscribed === false) throw new Error('No subscription manager available')
      applySessionRunState(res)
      if (res && res.replay_complete === false) {
        options.lastStreamSeq.value = typeof res.current_stream_seq === 'number'
          ? Math.max(options.lastStreamSeq.value, res.current_stream_seq)
          : options.lastStreamSeq.value
        options.loadHistory()
      } else if (res && typeof res.current_stream_seq === 'number') {
        options.lastStreamSeq.value = Math.max(options.lastStreamSeq.value, res.current_stream_seq)
      }
      if (options.isStreaming.value) options.resetStreamIdleTimer()
    } catch (err: unknown) {
      console.warn('Session stream subscription failed:', err instanceof Error ? err.message : err)
    }
  }

  async function unsubscribeSession() {
    if (!options.sessionKey.value) return
    try {
      await options.rpc.call('sessions.messages.unsubscribe', { key: options.sessionKey.value })
    } catch {
      // Unsubscribe is best-effort during route changes and unmount.
    }
  }

  function applySessionRunState(source: ChatRunStatusSource | null | undefined) {
    options.runStatus.value = options.sessionRunStatus(source)
  }

  return {
    subscribeSession,
    unsubscribeSession,
    applySessionRunState,
  }
}
