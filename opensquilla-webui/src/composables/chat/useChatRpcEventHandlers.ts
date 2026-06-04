import type { Ref } from 'vue'
import type {
  ChatMessage,
  ChatPendingItem,
  ChatRunStatus,
  ChatRunStatusSource,
} from '@/types/chat'
import type {
  ArtifactPayload,
  CompactionPayload,
  RouterDecisionPayload,
  SessionEventPayload,
  TextDeltaPayload,
  ToolDeltaPayload,
  ToolResultPayload,
  ToolUsePayload,
} from '@/types/rpc'
import type { ChatRpcSubscriptionHandlers } from '@/composables/chat/useChatRpcSubscriptions'
import {
  acceptStreamSeq as decideStreamSeq,
  activeTaskGroupRunState as buildActiveTaskGroupRunState,
  isCurrentSessionPayload as payloadIsCurrentSession,
  isStaleEpoch as payloadIsStaleEpoch,
  sessionChangeIsTerminal as payloadSessionChangeIsTerminal,
  sessionErrorMessage as eventSessionErrorMessage,
  taskGroupId as eventTaskGroupId,
  taskTerminalAsSessionEvent as normalizeTaskTerminalEvent,
  taskTerminalStatus as eventTaskTerminalStatus,
} from '@/utils/chat/streamEvents'

export interface ChatUsageAccumulator {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  cost: number | null
  routedTurns: number
  sessionSaved: number
}

export interface ChatRpcStreamApi {
  isStreaming: Ref<boolean>
  streamBubble: Ref<boolean>
  streamHasVisibleOutput: Ref<boolean>
  startStreaming: () => void
  endStreaming: (opts?: { reason?: string }) => void
  appendDelta: (text: string) => void
  appendToolCall: (payload: ToolUsePayload) => void
  appendToolDelta: (payload: ToolDeltaPayload) => void
  appendToolResult: (payload: ToolResultPayload) => void
  appendArtifact: (payload: ArtifactPayload) => void
  reconcileFinalText: (finalText: string) => void
  resetStreamIdleTimer: () => void
  clearStreamIdleTimer: () => void
  setStreamActivity: (label: string) => void
  showThinkingIndicator: () => void
  hideThinkingIndicator: () => void
}

export interface UseChatRpcEventHandlersOptions {
  sessionKey: Ref<string>
  currentEpoch: Ref<number>
  lastStreamSeq: Ref<number>
  activeTaskGroups: Ref<Set<string>>
  aborted: Ref<boolean>
  messages: Ref<ChatMessage[]>
  pendingQueue: Ref<ChatPendingItem[]>
  usageAccum: Ref<ChatUsageAccumulator>
  usageModel: Ref<string>
  stream: ChatRpcStreamApi
  normalizeRunStatus: (status: string) => string
  sessionRunStatus: (source: ChatRunStatusSource | null | undefined) => ChatRunStatus
  applySessionRunState: (source: ChatRunStatusSource | null | undefined) => void
  queueRouterDecision: (payload: RouterDecisionPayload) => void
  flushPendingRouterDecision: () => void
  clearPendingRouterDecision: () => void
  handleRouterControlReplay: () => void
  showCompactionToast: (payload: CompactionPayload, meta?: Record<string, unknown>) => void
  scheduleHistorySync: () => void
  schedulePendingDrainAfterTerminal: () => void
  popAllPendingIntoComposer: () => boolean
  saveWidgetState: () => void
  subscribeSession: () => void
  loadHistory: () => void
  loadCurrentSessionUsage: () => void
}

type ChatDoneUsageFields = {
  input_tokens?: number
  output_tokens?: number
  cached_tokens?: number
  cache_write?: number
  cost_usd?: number
  model?: string
  text?: string
}

type ChatDoneUsagePayload = SessionEventPayload & ChatDoneUsageFields & {
  usage?: ChatDoneUsageFields
}

export function useChatRpcEventHandlers(options: UseChatRpcEventHandlersOptions) {
  const {
    sessionKey,
    currentEpoch,
    lastStreamSeq,
    activeTaskGroups,
    aborted,
    messages,
    pendingQueue,
    usageAccum,
    usageModel,
    stream,
  } = options

  function isStaleEpoch(payload: SessionEventPayload): boolean {
    return payloadIsStaleEpoch(payload, currentEpoch.value)
  }

  function isCurrentSessionPayload(payload: SessionEventPayload): boolean {
    return payloadIsCurrentSession(payload, sessionKey.value)
  }

  function acceptStreamSeq(payload: SessionEventPayload): boolean {
    const decision = decideStreamSeq(payload, sessionKey.value, lastStreamSeq.value)
    if (decision.accepted) lastStreamSeq.value = decision.nextStreamSeq
    return decision.accepted
  }

  function activeTaskGroupRunState(payload: SessionEventPayload = {}) {
    return buildActiveTaskGroupRunState(payload, activeTaskGroups.value.size)
  }

  function noteTaskGroupActive(payload: SessionEventPayload) {
    const gid = eventTaskGroupId(payload)
    if (gid) activeTaskGroups.value.add(gid)
    options.applySessionRunState(activeTaskGroupRunState(payload))
  }

  function noteTaskGroupTerminal(payload: SessionEventPayload, terminalStatus: string) {
    const gid = eventTaskGroupId(payload)
    if (gid) activeTaskGroups.value.delete(gid)
    if (activeTaskGroups.value.size > 0) {
      options.applySessionRunState(activeTaskGroupRunState(payload))
      return
    }
    options.applySessionRunState({
      run_status: terminalStatus === 'failed' ? 'failed' : 'idle',
      last_task: { ...(payload || {}), status: terminalStatus },
    })
  }

  function sessionChangeIsTerminal(payload: SessionEventPayload): boolean {
    return payloadSessionChangeIsTerminal(payload, options.normalizeRunStatus)
  }

  function syncTerminalSessionChange(payload: SessionEventPayload = {}) {
    if (!isCurrentSessionPayload(payload)) return false
    activeTaskGroups.value.clear()
    const state = options.sessionRunStatus(payload)
    const interrupted = state.status === 'cancelled' || state.status === 'interrupted'
    if (stream.isStreaming.value) stream.endStreaming(interrupted ? { reason: 'aborted' } : undefined)
    options.applySessionRunState(payload)
    options.scheduleHistorySync()
    if (interrupted) {
      options.popAllPendingIntoComposer()
    } else {
      options.schedulePendingDrainAfterTerminal()
    }
    return true
  }

  function handleRpcTextDelta(payload: TextDeltaPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    stream.appendDelta(payload.text || '')
  }

  function handleRpcToolUseStart(payload: ToolUsePayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    stream.appendToolCall(payload)
  }

  function handleRpcToolUseDelta(payload: ToolDeltaPayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    stream.appendToolDelta(payload)
  }

  function handleRpcToolResult(payload: ToolResultPayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    stream.appendToolResult(payload)
  }

  function handleRpcArtifact(payload: ArtifactPayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    stream.appendArtifact(payload)
  }

  function handleRpcStateChange(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!payload || aborted.value) return
    if (!acceptStreamSeq(payload)) return
    stream.resetStreamIdleTimer()
    const to = payload.to_state || payload.toState || ''
    const activeState = ['thinking', 'streaming', 'tool_calling', 'tool_use', 'running'].includes(String(to))
    if (!stream.isStreaming.value && activeState) stream.startStreaming()
    if (!stream.isStreaming.value) return
    if (to === 'thinking') {
      if (stream.streamBubble.value && !stream.streamHasVisibleOutput.value) {
        stream.setStreamActivity('正在组织下一步')
      } else if (!stream.streamBubble.value) {
        stream.showThinkingIndicator()
      }
    } else if (to === 'streaming' && stream.streamBubble.value && !stream.streamHasVisibleOutput.value) {
      stream.setStreamActivity('模型正在生成')
    } else if ((to === 'tool_calling' || to === 'tool_use') && stream.streamBubble.value && !stream.streamHasVisibleOutput.value) {
      stream.setStreamActivity('正在准备工具调用')
    } else if (to && stream.streamBubble.value && !stream.streamHasVisibleOutput.value) {
      stream.setStreamActivity('仍在运行')
    }
  }

  function handleRpcRunHeartbeat(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    if (!stream.isStreaming.value) stream.startStreaming()
    stream.resetStreamIdleTimer()
    if (stream.streamBubble.value && !stream.streamHasVisibleOutput.value) {
      stream.setStreamActivity('正在组织下一步')
    } else if (!stream.streamBubble.value) {
      stream.showThinkingIndicator()
    }
  }

  function handleRpcCompaction(payload: CompactionPayload, meta: unknown) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    const safeMeta = (meta && typeof meta === 'object' ? meta : {}) as Record<string, unknown>
    options.showCompactionToast(payload || {}, safeMeta)
  }

  function handleRpcWarning(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    console.warn((payload && payload.message) || 'Assistant warning')
  }

  function handleRpcEpochChanged(payload: SessionEventPayload) {
    const ep = payload?.epoch
    if (typeof ep === 'number' && Number.isFinite(ep) && ep > currentEpoch.value) {
      activeTaskGroups.value.clear()
      currentEpoch.value = ep
    }
  }

  function handleRpcSessionsChanged(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!isCurrentSessionPayload(payload)) return
    if (sessionChangeIsTerminal(payload)) {
      syncTerminalSessionChange(payload)
      return
    }
    options.applySessionRunState(payload)
  }

  function handleRpcTaskQueued(payload: SessionEventPayload) {
    if (!isCurrentSessionPayload(payload)) return
    options.applySessionRunState({ run_status: 'queued', active_task: { ...(payload || {}), status: 'queued' } })
  }

  function handleRpcTaskRunning(payload: SessionEventPayload) {
    if (!isCurrentSessionPayload(payload)) return
    options.applySessionRunState({ run_status: 'running', active_task: { ...(payload || {}), status: 'running' } })
  }

  function handleRpcTaskGroupWaiting(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }

  function handleRpcTaskGroupSynthesizing(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }

  function handleRpcTaskGroupDone(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'succeeded')
  }

  function handleRpcTaskGroupFailed(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'failed')
  }

  function handleRpcRouterDecision(payload: RouterDecisionPayload) {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    options.queueRouterDecision(payload)
  }

  function handleRpcRouterControlReplay(payload: SessionEventPayload) {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    options.handleRouterControlReplay()
  }

  function handleRpcAny(rawEvent: string, rawPayload: unknown) {
    const payloadObj = (rawPayload && typeof rawPayload === 'object' ? rawPayload : {}) as SessionEventPayload
    const terminalStatus = eventTaskTerminalStatus(rawEvent)
    if (terminalStatus) {
      if (!isCurrentSessionPayload(payloadObj)) return
      const terminalRunStatus = terminalStatus === 'succeeded' ? 'idle' : terminalStatus === 'abandoned' ? 'interrupted' : terminalStatus
      if (activeTaskGroups.value.size > 0) {
        options.applySessionRunState(activeTaskGroupRunState(payloadObj))
      } else {
        options.applySessionRunState({ run_status: terminalRunStatus, last_task: { ...(payloadObj || {}), status: terminalStatus } })
      }
    }

    const normalized = normalizeTaskTerminalEvent(rawEvent, payloadObj)
    if (normalized && isStaleEpoch(payloadObj)) return
    if (normalized && !stream.isStreaming.value) return

    const event = normalized ? normalized.event : rawEvent
    const payload = normalized ? normalized.payload : payloadObj

    if (typeof event !== 'string') return
    if (event.startsWith('session.event.') && isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    if (event.startsWith('session.event.task_group.')) return
    if (event === 'sessions.changed') return

    if (event.endsWith('.done') || event === 'chat.done') {
      const donePayload = payload as ChatDoneUsagePayload
      const u = donePayload.usage || donePayload || {}
      if (u.input_tokens || u.output_tokens) {
        usageAccum.value.input += u.input_tokens || 0
        usageAccum.value.output += u.output_tokens || 0
        usageAccum.value.cacheRead += u.cached_tokens || 0
        usageAccum.value.cacheWrite += u.cache_write || 0
        if (u.cost_usd != null) usageAccum.value.cost = (usageAccum.value.cost || 0) + u.cost_usd
      }
      if (u.model) usageModel.value = u.model
      options.saveWidgetState()

      const finalText = typeof u.text === 'string' ? u.text : ''
      stream.reconcileFinalText(finalText)

      if (payload?.reason === 'aborted') {
        options.clearPendingRouterDecision()
      } else {
        options.flushPendingRouterDecision()
      }
      stream.endStreaming()
      options.scheduleHistorySync()

      if (payload?.reason === 'aborted') {
        options.popAllPendingIntoComposer()
        options.applySessionRunState({ run_status: 'cancelled', last_task: { ...(payload || {}), status: 'cancelled' } })
      } else if (activeTaskGroups.value.size > 0) {
        options.applySessionRunState(activeTaskGroupRunState({ reason: 'task_group_active' }))
      } else {
        options.applySessionRunState({ run_status: 'idle', last_task: { status: 'succeeded' } })
      }

      if (pendingQueue.value.length > 0 && payload?.reason !== 'aborted') {
        options.schedulePendingDrainAfterTerminal()
      }
    } else if (event.endsWith('.error')) {
      options.clearPendingRouterDecision()
      stream.endStreaming()
      messages.value.push({ role: 'error', text: eventSessionErrorMessage(payload), ts: new Date().toISOString() })
      options.scheduleHistorySync()
      if (activeTaskGroups.value.size > 0) {
        options.applySessionRunState(activeTaskGroupRunState(payload))
      } else {
        options.applySessionRunState({ run_status: 'failed', last_task: { ...(payload || {}), status: 'failed' } })
      }
    }
  }

  function handleRpcConnectionState(state: string) {
    if (state === 'connected' && sessionKey.value) {
      stream.hideThinkingIndicator()
      options.subscribeSession()
      options.loadCurrentSessionUsage()
      options.loadHistory()
    }
    if (state === 'disconnected' && stream.isStreaming.value) {
      stream.clearStreamIdleTimer()
      stream.showThinkingIndicator()
    }
  }

  const handlers: ChatRpcSubscriptionHandlers = {
    onTextDelta: handleRpcTextDelta,
    onToolUseStart: handleRpcToolUseStart,
    onToolUseDelta: handleRpcToolUseDelta,
    onToolResult: handleRpcToolResult,
    onArtifact: handleRpcArtifact,
    onStateChange: handleRpcStateChange,
    onRunHeartbeat: handleRpcRunHeartbeat,
    onCompaction: handleRpcCompaction,
    onWarning: handleRpcWarning,
    onEpochChanged: handleRpcEpochChanged,
    onSessionsChanged: handleRpcSessionsChanged,
    onTaskQueued: handleRpcTaskQueued,
    onTaskRunning: handleRpcTaskRunning,
    onTaskGroupWaiting: handleRpcTaskGroupWaiting,
    onTaskGroupSynthesizing: handleRpcTaskGroupSynthesizing,
    onTaskGroupDone: handleRpcTaskGroupDone,
    onTaskGroupFailed: handleRpcTaskGroupFailed,
    onRouterDecision: handleRpcRouterDecision,
    onRouterControlReplay: handleRpcRouterControlReplay,
    onAny: handleRpcAny,
    onConnectionState: handleRpcConnectionState,
  }

  return {
    handlers,
  }
}
