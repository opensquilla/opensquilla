import { describe, expect, it } from 'vitest'

import { shouldShowAgentFilterBadge } from './sidebarConversations'

describe('sidebar conversation badges', () => {
  it('does not render a Main Agent filter badge for subagent task rows', () => {
    expect(shouldShowAgentFilterBadge('chats', {
      sessionKind: 'task',
      depth: 1,
    })).toBe(false)
  })

  it('keeps agent filter badges available for root non-task chat-family rows', () => {
    expect(shouldShowAgentFilterBadge('chats', {
      sessionKind: 'unknown',
      depth: 0,
    })).toBe(true)
  })
})
