import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { ChatMessage } from '@/types/chat'
import { useChatRouterDecisionRuntime } from '@/composables/chat/useChatRouterDecisionRuntime'

function makeRuntime(messages: ChatMessage[] = [], isStreaming = true) {
  const messagesRef = ref<ChatMessage[]>(messages)
  const runtime = useChatRouterDecisionRuntime({
    messages: messagesRef,
    sessionKey: ref('sess'),
    isStreaming: ref(isStreaming),
    streamBubble: ref(true),
    streamHasVisibleOutput: ref(false),
    startStreaming: vi.fn(),
    resetStreamForRouterReplay: vi.fn(),
    resetStreamIdleTimer: vi.fn(),
    setStreamActivity: vi.fn(),
    scrollToBottom: vi.fn(),
  })
  return { runtime, messagesRef }
}

describe('appendEnsembleProgress', () => {
  it('synthesizes a router message and reveals members with running → done status', () => {
    const { runtime, messagesRef } = makeRuntime([{ role: 'user', text: 'q', ts: 0 }])

    runtime.appendEnsembleProgress({
      event_type: 'proposer_start',
      proposer_label: 'anchor',
      proposer_provider: 'openrouter',
      proposer_model: 'qwen/qwen3.7-plus',
    })

    const router = messagesRef.value.find(m => m.role === 'router')
    expect(router).toBeTruthy()
    expect(router?.provenanceKind).toBe('router_decision')
    expect(router?.routerDecision?.source).toBe('llm_ensemble')
    expect(router?.ensemble?.models).toHaveLength(1)
    expect(router?.ensemble?.models[0].modelShort).toBe('qwen3.7-plus')
    expect(router?.ensemble?.models[0].status).toBe('running')
    expect(router?.ensemble?.modelCount).toBe(1)

    // The finish delta upserts the SAME row (no duplicate) and flips to done.
    runtime.appendEnsembleProgress({
      event_type: 'proposer_finish',
      proposer_label: 'anchor',
      proposer_provider: 'openrouter',
      proposer_model: 'qwen/qwen3.7-plus',
      input_tokens: 100,
      output_tokens: 20,
    })
    expect(router?.ensemble?.models).toHaveLength(1)
    expect(router?.ensemble?.models[0].status).toBe('done')
    expect(router?.ensemble?.models[0].input).toBe(100)

    // A second proposer grows the revealed count.
    runtime.appendEnsembleProgress({
      event_type: 'proposer_start',
      proposer_label: 'critic',
      proposer_provider: 'openrouter',
      proposer_model: 'z-ai/glm-5.2',
    })
    expect(router?.ensemble?.models).toHaveLength(2)
    expect(router?.ensemble?.modelCount).toBe(2)
  })

  it('attaches members to the existing live router message instead of duplicating it', () => {
    const existing: ChatMessage = {
      role: 'router',
      text: '',
      ts: 1,
      provenanceKind: 'router_decision',
      routerDecision: { tier: 'c1', model: 'x', source: 'squilla_router' },
    }
    const { runtime, messagesRef } = makeRuntime([{ role: 'user', text: 'q', ts: 0 }, existing])

    runtime.appendEnsembleProgress({
      event_type: 'proposer_finish',
      proposer_label: 'anchor',
      proposer_provider: 'openrouter',
      proposer_model: 'qwen/qwen3.7-plus',
    })

    const routers = messagesRef.value.filter(m => m.role === 'router')
    expect(routers).toHaveLength(1)
    expect(routers[0].ensemble?.models).toHaveLength(1)
    // The strip is upgraded onto the ensemble branch.
    expect(routers[0].routerDecision?.source).toBe('llm_ensemble')
  })

  it('ignores deltas with no model and no aggregator role', () => {
    const { runtime, messagesRef } = makeRuntime([{ role: 'user', text: 'q', ts: 0 }])
    runtime.appendEnsembleProgress({ event_type: 'proposer_start', proposer_model: '' })
    expect(messagesRef.value.some(m => m.role === 'router')).toBe(false)
  })
})
