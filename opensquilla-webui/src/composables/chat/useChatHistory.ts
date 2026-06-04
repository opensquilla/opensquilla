import { nextTick, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatTimelineSegment,
  ChatUsagePayload,
  RawToolCallPayload,
} from '@/types/chat'
import type { ChatHistoryResponse } from '@/types/rpc'

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
  lastHeaderRole: Ref<string>
  lastHeaderDay: Ref<string>
  stripTimePrefix: (text: string) => string
  scrollToBottom: () => void
}

export function useChatHistory(options: UseChatHistoryOptions) {
  let historySyncTimer: ReturnType<typeof setTimeout> | null = null

  function scheduleHistorySync() {
    if (historySyncTimer) clearTimeout(historySyncTimer)
    historySyncTimer = setTimeout(() => {
      historySyncTimer = null
      loadHistory()
    }, 50)
  }

  async function loadHistory() {
    if (!options.sessionKey.value) return
    const key = options.sessionKey.value
    try {
      await options.rpc.waitForConnection()
      if (key !== options.sessionKey.value) return
      const data = await options.rpc.call<ChatHistoryResponse>('chat.history', { sessionKey: key })
      if (key !== options.sessionKey.value) return
      const msgs = data.messages || []

      if (msgs.length === 0) {
        options.messages.value = []
        options.lastHeaderRole.value = ''
        options.lastHeaderDay.value = ''
        return
      }

      options.messages.value = msgs.map(msg => ({
        role: msg.role || 'assistant',
        text: msg.role === 'user' ? options.stripTimePrefix(msg.text || '') : msg.text || '',
        ts: msg.timestamp || msg.ts || null,
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
      }))

      options.lastHeaderRole.value = ''
      options.lastHeaderDay.value = ''

      nextTick(() => options.scrollToBottom())
    } catch {
      // History endpoint may not exist yet.
    }
  }

  function cleanup() {
    if (historySyncTimer) {
      clearTimeout(historySyncTimer)
      historySyncTimer = null
    }
  }

  return {
    loadHistory,
    scheduleHistorySync,
    cleanup,
  }
}
