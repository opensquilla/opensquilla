import { ref, type Ref } from 'vue'
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
  hasActiveInterrupt: Ref<boolean>
  activeStreamTaskId: Ref<string>
  activeTaskGroups: Ref<Set<string>>
  sessionRunStatus: (source: ChatRunStatusSource | null | undefined) => ChatRunStatus
  startStreaming: () => void
  loadHistory: () => void | Promise<void>
  resetStreamIdleTimer: () => void
  resetStreamLiveTurnState: () => void
}

const LIVE_RUN_STATES = ['queued', 'running', 'approval_pending']

export function useChatSessionSubscription(options: UseChatSessionSubscriptionOptions) {
  const isHydrating = ref(false)
  let subscriptionAttempt = 0

  async function subscribeSession() {
    if (!options.sessionKey.value) return
    const key = options.sessionKey.value
    const sinceStreamSeq = options.lastStreamSeq.value
    const attempt = ++subscriptionAttempt
    if (sinceStreamSeq === 0) isHydrating.value = true
    try {
      await options.rpc.waitForConnection()
      if (key !== options.sessionKey.value) return
      const params: SessionMessagesSubscribeParams = { key, since_stream_seq: sinceStreamSeq }
      const res = await options.rpc.call<SessionMessagesSubscribeResponse>('sessions.messages.subscribe', params)
      if (key !== options.sessionKey.value) return
      if (res && res.subscribed === false) throw new Error('No subscription manager available')
      applySessionRunState(res)
      // A pending inline interrupt is newer, stronger evidence than an idle
      // subscription snapshot that raced with the approval request.
      if (
        options.hasActiveInterrupt.value
        && !LIVE_RUN_STATES.includes(options.runStatus.value.status)
      ) {
        options.runStatus.value = options.sessionRunStatus({
          run_status: 'approval_pending',
          active_task: options.runStatus.value.task,
        })
      }
      const liveTaskSnapshot = LIVE_RUN_STATES.includes(options.runStatus.value.status)
      reconcileActiveTaskGroups(res)
      if (liveTaskSnapshot && !options.isStreaming.value) {
        options.startStreaming()
      }
      if (liveTaskSnapshot) {
        const activeTask = (res.active_task || res.activeTask) as {
          task_id?: string
          taskId?: string
        } | null | undefined
        const taskId = activeTask?.task_id || activeTask?.taskId
        if (taskId) options.activeStreamTaskId.value = taskId
      }
      // Replayed events arrive before this response and can rebuild a live
      // bubble for a run that already ended (a stopped run leaves no terminal
      // event in the replay buffer), duplicating the partial reply that
      // chat.history already persists. When the subscribe snapshot says
      // nothing is live, drop that stale bubble without emitting a message.
      if (
        options.isStreaming.value
        && !options.hasActiveInterrupt.value
        && !liveTaskSnapshot
      ) {
        options.resetStreamLiveTurnState()
      }
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
    } finally {
      if (attempt === subscriptionAttempt) isHydrating.value = false
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

  function reconcileActiveTaskGroups(res: SessionMessagesSubscribeResponse) {
    const snapshot = res.active_task_group_ids || res.activeTaskGroupIds
    if (!Array.isArray(snapshot)) return
    options.activeTaskGroups.value = new Set(
      snapshot.filter((groupId): groupId is string => typeof groupId === 'string' && Boolean(groupId)),
    )
    if (options.activeTaskGroups.value.size === 0) return
    applySessionRunState({
      run_status: 'running',
      active_task: {
        status: 'running',
        task_group_count: options.activeTaskGroups.value.size,
      },
    })
  }

  return {
    isHydrating,
    subscribeSession,
    unsubscribeSession,
    applySessionRunState,
  }
}
