import { nextTick, ref, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatTimelineSegment,
  ChatUsagePayload,
  RawToolCallPayload,
} from '@/types/chat'
import type { ChatHistoryMessage, ChatHistoryResponse } from '@/types/rpc'

type RpcClient = {
  waitForConnection: () => Promise<void>
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

function recordArray<T extends Record<string, unknown>>(value: unknown): T[] {
  return Array.isArray(value)
    ? value.filter((item): item is T => !!item && typeof item === 'object' && !Array.isArray(item))
    : []
}

function usagePayload(value: unknown): ChatUsagePayload | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as ChatUsagePayload
}

export interface UseChatHistoryOptions {
  rpc: RpcClient
  sessionKey: Ref<string>
  messages: Ref<ChatMessage[]>
  threadRef?: Ref<HTMLElement | null>
  lastHeaderRole: Ref<string>
  lastHeaderDay: Ref<string>
  stripTimePrefix: (text: string) => string
  scrollToBottom: () => void
}

export interface ChatHistoryState {
  hasMore: boolean
  oldestCursor: string | number | null
  newestCursor: string | number | null
  historyScope: string
  loading: boolean
}

export function useChatHistory(options: UseChatHistoryOptions) {
  let historySyncTimer: ReturnType<typeof setTimeout> | null = null
  let historyRequestSeq = 0
  let historySyncPending = false
  let loadingHistoryKey = ''
  const historyState = ref<ChatHistoryState>({
    hasMore: false,
    oldestCursor: null,
    newestCursor: null,
    historyScope: '',
    loading: false,
  })

  function scheduleHistorySync() {
    if (historySyncTimer) clearTimeout(historySyncTimer)
    historySyncTimer = setTimeout(() => {
      historySyncTimer = null
      if (historyState.value.loading) {
        historySyncPending = true
        return
      }
      void loadHistory()
    }, 50)
  }

  function flushPendingHistorySync() {
    if (!historySyncPending || historyState.value.loading) return
    historySyncPending = false
    scheduleHistorySync()
  }

  function mapHistoryMessage(msg: ChatHistoryMessage): ChatMessage {
    // History rows carry the turn's reasoning text but not the measured
    // thinking duration; live turn records re-fill seconds after sync.
    const reasoningText = typeof msg.reasoning_content === 'string' ? msg.reasoning_content.trim() : ''
    return {
      role: msg.role || 'assistant',
      text: msg.role === 'user' ? options.stripTimePrefix(msg.text || '') : msg.text || '',
      ts: msg.timestamp || msg.ts || null,
      reasoning: reasoningText ? { text: reasoningText, seconds: 0 } : undefined,
      routerDecision: msg.router_decision || msg.routerDecision || null,
      artifacts: msg.artifacts || [],
      tool_calls: recordArray<RawToolCallPayload>(msg.tool_calls),
      timeline: recordArray<ChatTimelineSegment>(msg.timeline),
      attachments: msg.attachments || [],
      provenanceKind: msg.provenance_kind || '',
      provenanceSourceSessionKey: msg.provenance_source_session_key || '',
      provenanceSourceTool: msg.provenance_source_tool || '',
      usage: usagePayload(msg.usage) || usagePayload(msg.turn_usage),
      model: msg.model || undefined,
      input: msg.input || msg.input_tokens || undefined,
      output: msg.output || msg.output_tokens || undefined,
      messageId: msg.message_id || msg.id || '',
      restoredFromHistory: true,
    }
  }

  function messageKey(msg: ChatMessage): string {
    return msg.messageId || `${msg.role}:${msg.ts || ''}:${msg.text || ''}`
  }

  function updateHistoryState(data: ChatHistoryResponse) {
    historyState.value = {
      hasMore: Boolean(data.has_more ?? data.hasMore),
      oldestCursor: data.oldest_cursor ?? data.oldestCursor ?? null,
      newestCursor: data.newest_cursor ?? data.newestCursor ?? null,
      historyScope: data.history_scope ?? data.historyScope ?? '',
      loading: false,
    }
  }

  async function loadHistory(params: { before?: string | number | null, prepend?: boolean } = {}) {
    if (!options.sessionKey.value) return
    const key = options.sessionKey.value
    if (historyState.value.loading && loadingHistoryKey === key) {
      if (!params.prepend) historySyncPending = true
      return
    }
    const requestSeq = ++historyRequestSeq
    const previousHeight = params.prepend ? options.threadRef?.value?.scrollHeight || 0 : 0
    loadingHistoryKey = key
    historyState.value = { ...historyState.value, loading: true }
    const isCurrentRequest = () => key === options.sessionKey.value && requestSeq === historyRequestSeq
    try {
      await options.rpc.waitForConnection()
      if (!isCurrentRequest()) {
        if (requestSeq === historyRequestSeq) {
          loadingHistoryKey = ''
          historyState.value = { ...historyState.value, loading: false }
          flushPendingHistorySync()
        }
        return
      }
      const request: Record<string, unknown> = {
        sessionKey: key,
        limit: !params.prepend && options.messages.value.length > 50
          ? Math.min(200, options.messages.value.length)
          : 50,
        includeCanonical: false,
        includeSummaries: true,
      }
      if (params.before) request.before = params.before
      const data = await options.rpc.call<ChatHistoryResponse>('chat.history', request)
      if (!isCurrentRequest()) return
      const msgs = data.messages || []
      updateHistoryState(data)
      loadingHistoryKey = ''

      if (msgs.length === 0 && !params.prepend) {
        options.messages.value = []
        options.lastHeaderRole.value = ''
        options.lastHeaderDay.value = ''
        flushPendingHistorySync()
        return
      }

      const mapped = msgs.map(mapHistoryMessage)
      if (params.prepend) {
        const existing = new Set(options.messages.value.map(messageKey))
        options.messages.value = [
          ...mapped.filter(msg => !existing.has(messageKey(msg))),
          ...options.messages.value,
        ]
      } else {
        options.messages.value = mapped
      }

      options.lastHeaderRole.value = ''
      options.lastHeaderDay.value = ''

      nextTick(() => {
        if (params.prepend && options.threadRef?.value) {
          const nextHeight = options.threadRef.value.scrollHeight
          options.threadRef.value.scrollTop += Math.max(0, nextHeight - previousHeight)
          return
        }
        options.scrollToBottom()
      })
      flushPendingHistorySync()
    } catch {
      // History endpoint may not exist yet.
      if (isCurrentRequest()) {
        loadingHistoryKey = ''
        historyState.value = { ...historyState.value, loading: false }
        flushPendingHistorySync()
      }
    }
  }

  function loadEarlierHistory() {
    if (!historyState.value.hasMore || historyState.value.loading) return
    return loadHistory({ before: historyState.value.oldestCursor, prepend: true })
  }

  function cleanup() {
    if (historySyncTimer) {
      clearTimeout(historySyncTimer)
      historySyncTimer = null
    }
    historySyncPending = false
  }

  return {
    historyState,
    loadHistory,
    loadEarlierHistory,
    scheduleHistorySync,
    cleanup,
  }
}
