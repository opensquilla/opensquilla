import { describe, expect, it } from 'vitest'
import { sessionStatusBadge } from './sessionDisplay'
import type { SessionItem } from '@/composables/useSessions'

function sessionItem(overrides: Partial<SessionItem>): SessionItem {
  return {
    key: 'agent:main:webchat:test',
    title: 'Test chat',
    subtitle: '',
    groupLabel: 'main',
    effectiveAgentId: 'main',
    sessionKind: 'chat',
    surface: 'webchat',
    conversationKind: 'direct',
    threadLabel: '',
    channelContext: null,
    status: 'killed',
    visualStatus: 'killed',
    runStatus: 'cancelled',
    runLabel: 'Stopped after 1s',
    messageCount: 1,
    updatedAt: 1000,
    interactive: true,
    forkedFromParent: false,
    contractGaps: [],
    raw: { key: 'agent:main:webchat:test' },
    ...overrides,
  }
}

describe('sessionStatusBadge', () => {
  it('shows the normalized stop label for cancelled sessions', () => {
    const badge = sessionStatusBadge(sessionItem({ runStatus: 'cancelled', runLabel: 'Stopped after 1s' }))

    expect(badge?.label).toBe('Stopped after 1s')
  })

  it('shows the normalized stop label for interrupted sessions', () => {
    const badge = sessionStatusBadge(sessionItem({
      runStatus: 'interrupted',
      runLabel: 'Output interrupted',
    }))

    expect(badge?.label).toBe('Output interrupted')
  })
})
