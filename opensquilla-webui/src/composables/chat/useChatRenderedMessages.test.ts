import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { useChatRenderedMessages } from './useChatRenderedMessages'
import type { ChatMessage, ChatRouterTierConfig } from '@/types/chat'

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
