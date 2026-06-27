import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { useChatRenderedMessages } from './useChatRenderedMessages'
import type { ChatMessage, ChatRouterTierConfig } from '@/types/chat'
import type { ChatPart, InterruptViewState } from '@/types/parts'

function renderedMessagesForRouterVisualMode(visualMode: 'real_candidates' | 'legacy_grid') {
  const configs: Record<string, ChatRouterTierConfig> = {
    fast: { model: 'openai/gpt-5.4-mini', supportsImage: false, imageOnly: false },
    balanced: { model: 'anthropic/claude-sonnet-4.6', supportsImage: false, imageOnly: false },
    strong: { model: 'openai/gpt-5.5', supportsImage: false, imageOnly: false },
  }
  return useChatRenderedMessages({
    messages: ref<ChatMessage[]>([]),
    sessionKey: ref('router-visual-test'),
    routerSlots: ref(['fast', 'balanced', 'strong']),
    routerModels: ref({}),
    routerTierConfigs: ref(configs),
    routerVisualEffectsEnabled: ref(true),
    routerVisualMode: ref(visualMode),
    renderMarkdown: text => text,
    stripGeneratedArtifactMarkers: text => text,
    stripTimePrefix: text => text,
    isSubagentCompletionMessage: () => false,
  })
}

function renderedMessagesFor(
  messages: ChatMessage[],
  interruptState = ref<ReadonlyMap<string, InterruptViewState>>(new Map()),
) {
  return useChatRenderedMessages({
    messages: ref<ChatMessage[]>(messages),
    interruptState,
    sessionKey: ref('agent:main:webchat:test'),
    routerSlots: ref([]),
    routerModels: ref({}),
    routerTierConfigs: ref({}),
    routerVisualEffectsEnabled: ref(false),
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
