import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { useChatRenderedMessages } from './useChatRenderedMessages'
import type { ChatMessage, ChatRouterTierConfig } from '@/types/chat'
import type { ModelRoutingMode } from '@/types/modelRouting'
import type { ChatPart, InterruptViewState } from '@/types/parts'

function renderedMessagesForRouterVisualMode(
  visualMode: 'real_candidates' | 'legacy_grid',
  modelRoutingMode: ModelRoutingMode = 'squilla_router',
) {
  const configs: Record<string, ChatRouterTierConfig> = {
    fast: { model: 'openai/gpt-5.4-mini', supportsImage: false, imageOnly: false },
    balanced: { model: 'anthropic/claude-sonnet-4.6', supportsImage: false, imageOnly: false },
    strong: { model: 'openai/gpt-5.5', supportsImage: false, imageOnly: false },
  }
  const options = {
    messages: ref<ChatMessage[]>([]),
    sessionKey: ref('router-visual-test'),
    routerSlots: ref(['fast', 'balanced', 'strong']),
    routerModels: ref({}),
    routerTierConfigs: ref(configs),
    routerVisualEffectsEnabled: ref(true),
    routerVisualMode: ref(visualMode),
    renderMarkdown: (text: string) => text,
    stripGeneratedArtifactMarkers: (text: string) => text,
    stripTimePrefix: (text: string) => text,
    isSubagentCompletionMessage: () => false,
    modelRoutingMode: ref(modelRoutingMode),
  }
  return useChatRenderedMessages(options)
}

function renderedMessagesFor(
  messages: ChatMessage[],
  interruptState = ref<ReadonlyMap<string, InterruptViewState>>(new Map()),
  routerVisualEffectsEnabled = false,
) {
  return useChatRenderedMessages({
    messages: ref<ChatMessage[]>(messages),
    interruptState,
    sessionKey: ref('agent:main:webchat:test'),
    routerSlots: ref([]),
    routerModels: ref({}),
    routerTierConfigs: ref({}),
    routerVisualEffectsEnabled: ref(routerVisualEffectsEnabled),
    routerVisualMode: ref('real_candidates'),
    renderMarkdown: text => text,
    stripGeneratedArtifactMarkers: text => text,
    stripTimePrefix: text => text,
    isSubagentCompletionMessage: () => false,
  })
}

describe('useChatRenderedMessages router visual mode', () => {
  it('keeps real-candidates mode limited to callable router tiers', () => {
    const api = renderedMessagesForRouterVisualMode('real_candidates')

    const cells = api.routerDecisionCells({
      tier: 'balanced',
      model: 'anthropic/claude-sonnet-4.6',
    })

    expect(cells).toHaveLength(3)
    expect(cells.every(cell => cell.kind === 'real')).toBe(true)
  })

  it('renders legacy-grid mode as a 15-cell visual panel without moving the real winner', () => {
    const api = renderedMessagesForRouterVisualMode('legacy_grid')

    const cells = api.routerDecisionCells({
      tier: 'balanced',
      model: 'anthropic/claude-sonnet-4.6',
    })
    const winnerIdx = api.routerWinnerCellIndex(cells, 'balanced')

    expect(cells).toHaveLength(15)
    expect(cells.some(cell => cell.kind === 'decoy')).toBe(true)
    expect(cells.filter(cell => cell.kind === 'real')).toHaveLength(3)
    expect(cells.map(cell => cell.displayName)).toEqual(
      expect.arrayContaining([
        'gpt-5.5',
        'gemini-3.5-flash',
        'qwen3-coder-plus',
        'grok-4.3',
        'gpt-5.4-mini',
        'kimi-k2.6',
      ]),
    )
    expect(cells.map(cell => cell.displayName)).not.toEqual(
      expect.arrayContaining([
        'gpt-4.1-mini',
        'gpt-4o-mini',
        'o4-mini',
        'deepseek-chat',
        'mistral-medium',
        'grok-code-fast',
        'qwen3-coder',
      ]),
    )
    expect(winnerIdx).toBeGreaterThanOrEqual(0)
    expect(cells[winnerIdx].kind).toBe('real')
    expect(cells[winnerIdx].tiers).toContain('balanced')
  })

  it('uses the ensemble strip instead of normal router cells while LLM ensemble mode is active', () => {
    const withMessages = useChatRenderedMessages({
      messages: ref<ChatMessage[]>([
        { role: 'user', text: 'hard question', ts: 0 },
        {
          role: 'router',
          text: '',
          ts: 1,
          provenanceKind: 'router_decision',
          routerDecision: {
            tier: 'balanced',
            model: 'anthropic/claude-sonnet-4.6',
            source: 'squilla_router',
          },
        },
      ]),
      sessionKey: ref('router-ensemble-active-test'),
      routerSlots: ref(['fast', 'balanced', 'strong']),
      routerModels: ref({}),
      routerTierConfigs: ref({
        fast: { model: 'openai/gpt-5.4-mini', supportsImage: false, imageOnly: false },
        balanced: { model: 'anthropic/claude-sonnet-4.6', supportsImage: false, imageOnly: false },
        strong: { model: 'openai/gpt-5.5', supportsImage: false, imageOnly: false },
      }),
      routerVisualEffectsEnabled: ref(true),
      routerVisualMode: ref('real_candidates'),
      renderMarkdown: text => text,
      stripGeneratedArtifactMarkers: text => text,
      stripTimePrefix: text => text,
      isSubagentCompletionMessage: () => false,
      modelRoutingMode: ref('llm_ensemble'),
    })

    const strip = withMessages.renderedMessages.value.find(message => message.isRouterStrip)
    expect(strip?.routerPanel).toBe('llm-ensemble')
    expect(strip?.gridCells || []).toHaveLength(0)
  })

  it('removes the pending ensemble strip once the assistant answer carries the completed trace', () => {
    const api = useChatRenderedMessages({
      messages: ref<ChatMessage[]>([
        { role: 'user', text: 'hello', ts: 0 },
        {
          role: 'router',
          text: '',
          ts: 1,
          provenanceKind: 'router_decision',
          routerDecision: {
            tier: 'balanced',
            model: 'anthropic/claude-sonnet-4.6',
            source: 'llm_ensemble',
          },
        },
        {
          role: 'assistant',
          text: 'Hi there.',
          ts: 2,
          messageId: 'assistant-ensemble',
          usage: {
            model: 'z-ai/glm-5.2',
            model_usage_breakdown: [
              { role: 'anchor', provider: 'openrouter', model: 'qwen/qwen3.7-plus' },
              { role: 'critic', provider: 'openrouter', model: 'z-ai/glm-5.2' },
            ],
            ensemble_trace: {
              profile: 'default',
              mode: 'router_dynamic',
              llm_request_count: 2,
              total_candidates: 3,
              fallback_used: false,
            },
          },
        },
      ]),
      sessionKey: ref('router-ensemble-completed-test'),
      routerSlots: ref(['fast', 'balanced', 'strong']),
      routerModels: ref({}),
      routerTierConfigs: ref({
        fast: { model: 'openai/gpt-5.4-mini', supportsImage: false, imageOnly: false },
        balanced: { model: 'anthropic/claude-sonnet-4.6', supportsImage: false, imageOnly: false },
        strong: { model: 'openai/gpt-5.5', supportsImage: false, imageOnly: false },
      }),
      routerVisualEffectsEnabled: ref(true),
      routerVisualMode: ref('real_candidates'),
      renderMarkdown: text => text,
      stripGeneratedArtifactMarkers: text => text,
      stripTimePrefix: text => text,
      isSubagentCompletionMessage: () => false,
      modelRoutingMode: ref('llm_ensemble'),
    })

    const rendered = api.renderedMessages.value
    const assistantIndex = rendered.findIndex(message => message.displayRole === 'assistant')
    const stripIndex = rendered.findIndex(message => message.isRouterStrip)

    expect(assistantIndex).toBeGreaterThan(-1)
    expect(stripIndex).toBe(-1)
    expect(rendered[assistantIndex]?.meta?.ensemble?.modelCount).toBe(2)
  })
})

describe('useChatRenderedMessages clarify history recovery', () => {
  it('restores a clarify interrupt from persisted meta-step tool input', () => {
    const api = renderedMessagesFor([
      {
        role: 'assistant',
        text: 'Please reply with these fields.',
        ts: 0,
        messageId: 'm-clarify',
        tool_calls: [
          {
            type: 'tool_use',
            tool_use_id: 'meta_step_project_clarify',
            name: 'meta-step:project_clarify',
            input: {
              kind: 'user_input',
              paused: true,
              step: 'project_clarify',
              run_id: 'run-1',
              clarify_schema: {
                mode: 'form',
                intro: 'A few details.',
                fields: [
                  {
                    name: 'topic',
                    type: 'string',
                    required: true,
                    prompt: 'Project topic',
                  },
                  {
                    name: 'age_band',
                    type: 'enum',
                    required: true,
                    prompt: 'Child age band',
                    choices: ['PRE_K', 'EARLY_GRADE'],
                  },
                ],
              },
            },
          },
          {
            type: 'tool_result',
            tool_use_id: 'meta_step_project_clarify',
            name: 'meta-step:project_clarify',
            result: "paused: awaiting user input (step 'project_clarify')",
          },
        ],
      },
    ])

    const [message] = api.renderedMessages.value
    const clarify = message.parts?.find((part): part is ChatPart & {
      type: 'interrupt'
      interruptKind: 'clarify'
    } => part.type === 'interrupt' && part.interruptKind === 'clarify')

    expect(clarify).toBeTruthy()
    expect(clarify?.key).toBe('m-clarify:interrupt:run-1|project_clarify')
    expect(clarify?.clarify?.intro).toBe('A few details.')
    expect(clarify?.clarify?.fields.map(field => field.name)).toEqual([
      'topic',
      'age_band',
    ])
    expect(clarify?.clarify?.fields[1].choices).toEqual(['PRE_K', 'EARLY_GRADE'])
  })

  it('applies clarify submit state to recovered historical interrupt cards', () => {
    const interruptState = ref<ReadonlyMap<string, InterruptViewState>>(new Map([
      ['run-1|project_clarify', {
        resolution: 'replied',
        busy: true,
        error: '',
      }],
    ]))
    const api = renderedMessagesFor([
      {
        role: 'assistant',
        text: 'Please reply with these fields.',
        ts: 0,
        messageId: 'm-clarify',
        tool_calls: [
          {
            type: 'tool_use',
            tool_use_id: 'meta_step_project_clarify',
            name: 'meta-step:project_clarify',
            input: {
              kind: 'user_input',
              paused: true,
              step: 'project_clarify',
              run_id: 'run-1',
              clarify_schema: {
                mode: 'form',
                fields: [
                  {
                    name: 'topic',
                    type: 'string',
                    required: true,
                  },
                ],
              },
            },
          },
        ],
      },
    ], interruptState)

    const [message] = api.renderedMessages.value
    const clarify = message.parts?.find((part): part is ChatPart & {
      type: 'interrupt'
      interruptKind: 'clarify'
    } => part.type === 'interrupt' && part.interruptKind === 'clarify')

    expect(clarify?.resolution).toBe('replied')
    expect(clarify?.busy).toBe(true)
  })
})

describe('useChatRenderedMessages ensemble metadata', () => {
  it('keeps completed ensemble trace on the assistant meta without rendering a router strip', () => {
    const api = renderedMessagesFor([
      {
        role: 'user',
        text: 'Compare multiple recent AI policy updates.',
        ts: 0,
      },
      {
        role: 'assistant',
        text: 'fused answer',
        ts: 1,
        messageId: 'm-ensemble-strip',
        usage: {
          model_usage_breakdown: [
            { role: 'anchor', provider: 'openrouter', model: 'qwen/qwen3.7-plus' },
            { role: 'research', provider: 'openrouter', model: 'moonshotai/kimi-k2.6' },
            { role: 'critic', provider: 'openrouter', model: 'z-ai/glm-5.2' },
          ],
          ensemble_trace: {
            profile: 'default',
            llm_request_count: 3,
            total_candidates: 8,
            fallback_used: false,
          },
        },
      },
    ], undefined, true)

    const strip = api.renderedMessages.value.find(message => message.isRouterStrip)
    const assistant = api.renderedMessages.value.find(message => message.displayRole === 'assistant')

    expect(strip).toBeUndefined()
    expect(assistant?.meta?.ensemble?.modelCount).toBe(3)
    expect(assistant?.meta?.ensemble?.models.map(model => model.modelShort)).toEqual([
      'qwen3.7-plus',
      'kimi-k2.6',
      'glm-5.2',
    ])
  })

  it('normalizes ensemble model breakdown, cost, and savings into assistant meta', () => {
    const api = renderedMessagesFor([
      {
        role: 'assistant',
        text: 'fused answer',
        ts: 0,
        messageId: 'm-ensemble',
        usage: {
          model: 'z-ai/glm-5.2',
          cost_usd: 0.123456,
          total_savings_usd: 0.045,
          total_savings_pct: 26,
          model_usage_breakdown: [
            {
              role: 'proposer',
              label: 'Proposer 1',
              provider: 'openrouter',
              model: 'deepseek/deepseek-v4-pro',
              input_tokens: 10,
              output_tokens: 2,
              billed_cost: 0.01,
            },
            {
              role: 'aggregator',
              label: 'aggregator',
              provider: 'openrouter',
              model: 'z-ai/glm-5.2',
              input_tokens: 20,
              output_tokens: 8,
              billed_cost: 0.02,
            },
          ],
          ensemble_trace: {
            profile: 'default',
            llm_request_count: 2,
            fallback_used: false,
          },
        },
      },
    ])

    const [message] = api.renderedMessages.value
    expect(message.meta?.ensemble).toMatchObject({
      profile: 'default',
      modelCount: 2,
      requestCount: 2,
      costUsd: 0.123456,
      savedUsd: 0.045,
      savedPct: 26,
      fallbackUsed: false,
    })
    expect(message.meta?.ensemble?.models.map(model => model.model)).toEqual([
      'deepseek/deepseek-v4-pro',
      'z-ai/glm-5.2',
    ])
  })

  it('does not undercount requests when a turn has multiple ensemble breakdown rows', () => {
    const api = renderedMessagesFor([
      {
        role: 'assistant',
        text: 'fused answer',
        ts: 0,
        usage: {
          model_usage_breakdown: [
            { role: 'proposer', provider: 'openrouter', model: 'p1' },
            { role: 'aggregator', provider: 'openrouter', model: 'a1' },
            { role: 'proposer', provider: 'openrouter', model: 'p2' },
            { role: 'aggregator', provider: 'openrouter', model: 'a2' },
          ],
          ensemble_trace: {
            profile: 'default',
            llm_request_count: 2,
          },
        },
      },
    ])

    expect(api.renderedMessages.value[0].meta?.ensemble?.requestCount).toBe(4)
  })
})
