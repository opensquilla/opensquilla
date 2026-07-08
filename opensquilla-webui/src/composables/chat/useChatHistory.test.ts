import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

import { useChatHistory } from './useChatHistory'
import type { ChatMessage } from '@/types/chat'
import type { ChatHistoryResponse } from '@/types/rpc'

function makeHistory(autoScroll = true, overrides: {
  response?: ChatHistoryResponse
  messages?: ChatMessage[]
  preserveLiveTail?: boolean
} = {}) {
  const response: ChatHistoryResponse = overrides.response || {
    messages: [
      {
        id: 'm1',
        message_id: 'm1',
        role: 'assistant',
        text: 'hello',
        timestamp: '2026-07-06T00:00:00Z',
      },
    ],
    has_more: false,
    oldest_cursor: null,
    newest_cursor: null,
    history_scope: 'session',
  }
  const messages = ref<ChatMessage[]>(overrides.messages || [])
  const rpc = {
    waitForConnection: vi.fn().mockResolvedValue(undefined),
    call: vi.fn().mockResolvedValue(response),
  }
  const scrollToBottom = vi.fn()
  const api = useChatHistory({
    rpc,
    sessionKey: ref('agent:main:webchat:test'),
    messages,
    lastHeaderRole: ref(''),
    lastHeaderDay: ref(''),
    preserveLiveTail: ref(overrides.preserveLiveTail ?? false),
    autoScroll: ref(autoScroll),
    stripTimePrefix: text => text,
    scrollToBottom,
  })
  return { api, scrollToBottom, messages }
}

describe('useChatHistory scroll anchoring', () => {
  it('does not force the thread to the latest message when the reader has scrolled up', async () => {
    const { api, scrollToBottom } = makeHistory(false)

    await api.loadHistory()
    await nextTick()

    expect(scrollToBottom).not.toHaveBeenCalled()
  })

  it('keeps the initial pinned load behavior when the thread is still at the bottom', async () => {
    const { api, scrollToBottom } = makeHistory(true)

    await api.loadHistory()
    await nextTick()

    expect(scrollToBottom).toHaveBeenCalledTimes(1)
  })
})

describe('useChatHistory optimistic local rows', () => {
  it('does not erase local user text when an immediate history sync is still empty', async () => {
    const localMessages: ChatMessage[] = [
      { role: 'user', text: '上下文相关SOTA论文', ts: '2026-07-07T10:00:00Z' },
    ]
    const { api, messages } = makeHistory(true, {
      messages: localMessages,
      response: {
        messages: [],
        has_more: false,
        oldest_cursor: null,
        newest_cursor: null,
        history_scope: 'session',
      },
    })

    await api.loadHistory()

    expect(messages.value).toEqual(localMessages)
  })

  it('keeps a local stopped-output notice when the settled server history only has the user turn', async () => {
    const { api, messages } = makeHistory(true, {
      messages: [
        { role: 'user', text: 'stop immediately', ts: '2026-07-07T10:00:00Z', messageId: 'user-1' },
        {
          role: 'assistant',
          text: 'Stopped after 1s',
          ts: '2026-07-07T10:00:01Z',
          messageId: 'client-stop-notice:task-1',
          stopNotice: true,
          interrupted: true,
        },
      ],
      response: {
        messages: [
          {
            id: 'user-1',
            message_id: 'user-1',
            role: 'user',
            text: 'stop immediately',
            timestamp: '2026-07-07T10:00:00Z',
          },
        ],
        has_more: false,
        oldest_cursor: null,
        newest_cursor: null,
        history_scope: 'session',
      },
    })

    await api.loadHistory()

    expect(messages.value.map(message => [message.role, message.text])).toEqual([
      ['user', 'stop immediately'],
      ['assistant', 'Stopped after 1s'],
    ])
    expect(messages.value[1]?.stopNotice).toBe(true)
  })

  it('keeps multiple local stopped-output notices when repeated user prompts reload with server ids', async () => {
    const prompt = '调研一下上下文相关的sota论文'
    const { api, messages } = makeHistory(true, {
      messages: [
        { role: 'user', text: prompt, ts: 'local-1' },
        {
          role: 'assistant',
          text: '输出被中断',
          ts: 'local-stop-1',
          messageId: 'client-stop-notice:task-1',
          stopNotice: true,
          interrupted: true,
        },
        { role: 'user', text: prompt, ts: 'local-2' },
        {
          role: 'assistant',
          text: '输出被中断',
          ts: 'local-stop-2',
          messageId: 'client-stop-notice:task-2',
          stopNotice: true,
          interrupted: true,
        },
        { role: 'user', text: prompt, ts: 'local-3' },
        {
          role: 'assistant',
          text: '输出被中断',
          ts: 'local-stop-3',
          messageId: 'client-stop-notice:task-3',
          stopNotice: true,
          interrupted: true,
        },
      ],
      response: {
        messages: [
          {
            id: 'server-user-1',
            message_id: 'server-user-1',
            role: 'user',
            text: prompt,
            timestamp: 'server-1',
          },
          {
            id: 'server-user-2',
            message_id: 'server-user-2',
            role: 'user',
            text: prompt,
            timestamp: 'server-2',
          },
          {
            id: 'server-user-3',
            message_id: 'server-user-3',
            role: 'user',
            text: prompt,
            timestamp: 'server-3',
          },
        ],
        has_more: false,
        oldest_cursor: null,
        newest_cursor: null,
        history_scope: 'session',
      },
    })

    await api.loadHistory()

    expect(messages.value.map(message => [message.role, message.text])).toEqual([
      ['user', prompt],
      ['assistant', '输出被中断'],
      ['user', prompt],
      ['assistant', '输出被中断'],
      ['user', prompt],
      ['assistant', '输出被中断'],
    ])
    expect(messages.value.filter(message => message.stopNotice)).toHaveLength(3)
  })
})
