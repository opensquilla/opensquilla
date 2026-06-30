import { describe, expect, it } from 'vitest'
import { toSources } from './toSources'
import type { ChatRenderedMessage, ChatToolCall } from '@/types/chat'

function baseCall(overrides: Partial<ChatToolCall>): ChatToolCall {
  return {
    toolId: 'tool-1',
    name: 'web_search',
    displayName: 'Web search',
    inputPreview: '',
    isRunning: false,
    status: 'success',
    isError: false,
    result: '',
    resultPreview: '',
    isOpen: false,
    ...overrides,
  }
}

function message(toolCalls: ChatToolCall[]): ChatRenderedMessage {
  return {
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: '',
    timeStr: '',
    showHeader: false,
    toolCalls,
  }
}

describe('toSources', () => {
  it('preserves source trust metadata and merges duplicate URLs', () => {
    const sources = toSources(message([
      baseCall({
        sources: [
          {
            url: 'https://example.com/a',
            canonical_url: 'https://example.com/a',
            provider: 'duckduckgo',
            fetched: false,
            fetch_status: 'not_requested',
          },
          {
            url: 'https://example.com/a#section',
            title: 'Example result',
            provider: 'duckduckgo',
            fetched: true,
            fetch_status: 'ok',
          },
        ],
      }),
    ]))

    expect(sources).toEqual([
      {
        sourceId: 1,
        url: 'https://example.com/a',
        title: 'Example result',
        domain: 'example.com',
        canonicalUrl: 'https://example.com/a',
        provider: 'duckduckgo',
        fetched: true,
        fetchStatus: 'ok',
      },
    ])
  })

  it('upgrades duplicate source metadata when a later entry is verified', () => {
    const sources = toSources(message([
      baseCall({
        sources: [
          {
            url: 'https://example.com/a',
            title: 'Initial result',
            provider: 'duckduckgo',
            fetched: false,
            fetch_status: 'fetch_failed',
          },
          {
            url: 'https://example.com/a',
            provider: 'duckduckgo',
            fetched: true,
            fetch_status: 'ok',
          },
        ],
      }),
    ]))

    expect(sources[0]).toMatchObject({
      url: 'https://example.com/a',
      title: 'Initial result',
      fetched: true,
      fetchStatus: 'ok',
    })
  })
})
