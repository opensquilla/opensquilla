import { describe, expect, it } from 'vitest'

import { buildChatMarkdown } from './useChatMarkdownExport'
import type { ChatRenderedMessage } from '@/types/chat'

describe('buildChatMarkdown', () => {
  it('exports subagent completion messages as readable summaries, not raw JSON', () => {
    const json = JSON.stringify({
      type: 'subagent_completion',
      parent_session_key: 'agent:main:webchat:wo01onmp',
      child_session_key: 'agent:main:subagent:4dd8059d',
      status: 'succeeded',
      terminal_reason: 'completed',
      result: {
        text: 'OK',
      },
    })

    const markdown = buildChatMarkdown({
      title: '烟火App创意设计',
      exportedAt: '2026-06-29T07:30:02.759Z',
      messages: [{
        displayRole: 'subagent',
        roleLabel: 'Sub-agent',
        text: json,
        timeStr: '3m ago',
      } as ChatRenderedMessage],
    })

    expect(markdown).toContain('## Sub-agent')
    expect(markdown).toContain('Subagent agent:main:subagent:4dd8059d completed with status succeeded')
    expect(markdown).toContain('Result:\nOK')
    expect(markdown).not.toContain('"type": "subagent_completion"')
    expect(markdown).not.toContain('"parent_session_key"')
  })
})
