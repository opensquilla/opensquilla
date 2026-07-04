import { describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useChatRpcEventHandlers, type ChatRpcStreamApi } from './useChatRpcEventHandlers'
import type { ChatMessage } from '@/types/chat'

function createHarness(options: {
  messages?: ChatMessage[]
  endStreaming?: (messages: ChatMessage[]) => void
} = {}) {
  const messages = ref<ChatMessage[]>(options.messages ?? [])
  const stream: ChatRpcStreamApi = {
    isStreaming: ref(true),
    streamBubble: ref(true),
    streamHasVisibleOutput: ref(false),
    startStreaming: vi.fn(),
    endStreaming: vi.fn(() => options.endStreaming?.(messages.value)),
    appendDelta: vi.fn(),
    scheduleRender: vi.fn(),
    appendToolCall: vi.fn(),
    appendToolDelta: vi.fn(),
    appendToolResult: vi.fn(),
    appendArtifact: vi.fn(),
    reconcileFinalText: vi.fn(),
    resetStreamIdleTimer: vi.fn(),
    clearStreamIdleTimer: vi.fn(),
    setStreamActivity: vi.fn(),
    showThinkingIndicator: vi.fn(),
    hideThinkingIndicator: vi.fn(),
    appendFrame: vi.fn(),
    useReducer: ref(false),
  }
  const scope = effectScope()
  const api = scope.run(() => useChatRpcEventHandlers({
    sessionKey: ref('agent:main:test'),
    currentEpoch: ref(0),
    lastStreamSeq: ref(0),
    activeTaskGroups: ref(new Set<string>()),
    activeStreamTaskId: ref(''),
    aborted: ref(false),
    messages,
    pendingQueue: ref([]),
    usageAccum: ref({
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      cost: null,
      routedTurns: 0,
      sessionSaved: 0,
    }),
    usageModel: ref(''),
    stream,
    normalizeRunStatus: (status: string) => status,
    sessionRunStatus: () => ({ status: 'idle', label: 'Idle', task: null }),
    applySessionRunState: vi.fn(),
    queueRouterDecision: vi.fn(),
    appendEnsembleProgress: vi.fn(),
    flushPendingRouterDecision: vi.fn(),
    clearPendingRouterDecision: vi.fn(),
    handleRouterControlReplay: vi.fn(),
    showCompactionToast: vi.fn(),
    scheduleHistorySync: vi.fn(),
    schedulePendingDrainAfterTerminal: vi.fn(),
    popAllPendingIntoComposer: vi.fn(() => false),
    saveWidgetState: vi.fn(),
    subscribeSession: vi.fn(),
    loadHistory: vi.fn(),
    loadCurrentSessionUsage: vi.fn(),
  }))!
  return { api, messages, stream, stop: () => scope.stop() }
}

describe('useChatRpcEventHandlers done usage attachment', () => {
  it('does not attach done usage to the previous assistant when no new bubble was pushed', () => {
    const previous: ChatMessage = { role: 'assistant', text: 'previous', ts: 'before' }
    const { api, messages, stop } = createHarness({ messages: [previous] })

    try {
      api.handlers.onAny('session.event.done', {
        session_key: 'agent:main:test',
        stream_seq: 1,
        text: 'NO_REPLY',
        input_tokens: 10,
        output_tokens: 1,
        model: 'ensemble/default',
        model_usage_breakdown: [{ model: 'z-ai/glm-5.2', role: 'aggregator' }],
        ensemble_trace: { profile: 'default', llm_request_count: 5 },
      })

      expect(messages.value).toHaveLength(1)
      expect(messages.value[0]).toEqual(previous)
      expect(messages.value[0].usage).toBeUndefined()
    } finally {
      stop()
    }
  })

  it('attaches done usage to the assistant message pushed by endStreaming', () => {
    const previous: ChatMessage = { role: 'assistant', text: 'previous', ts: 'before' }
    const { api, messages, stop } = createHarness({
      messages: [previous],
      endStreaming(list) {
        list.push({ role: 'assistant', text: 'current', ts: 'now' })
      },
    })

    try {
      api.handlers.onAny('session.event.done', {
        session_key: 'agent:main:test',
        stream_seq: 1,
        text: 'current',
        input_tokens: 10,
        output_tokens: 1,
        model: 'z-ai/glm-5.2',
        model_usage_breakdown: [{ model: 'z-ai/glm-5.2', role: 'aggregator' }],
        ensemble_trace: { profile: 'default', llm_request_count: 5 },
      })

      expect(messages.value[0].usage).toBeUndefined()
      expect(messages.value[1].usage?.ensemble_trace).toEqual({
        profile: 'default',
        llm_request_count: 5,
      })
      expect(messages.value[1].model).toBe('z-ai/glm-5.2')
      expect(messages.value[1].input_tokens).toBe(10)
      expect(messages.value[1].output_tokens).toBe(1)
    } finally {
      stop()
    }
  })
})
