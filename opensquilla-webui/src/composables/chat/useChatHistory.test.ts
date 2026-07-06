import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

import { useChatHistory } from './useChatHistory'
import type { ChatMessage } from '@/types/chat'
import type { ChatHistoryResponse } from '@/types/rpc'

function makeHistory(autoScroll = true) {
  const response: ChatHistoryResponse = {
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
  const rpc = {
    waitForConnection: vi.fn().mockResolvedValue(undefined),
    call: vi.fn().mockResolvedValue(response),
  }
  const scrollToBottom = vi.fn()
  const api = useChatHistory({
    rpc,
    sessionKey: ref('agent:main:webchat:test'),
    messages: ref<ChatMessage[]>([]),
    lastHeaderRole: ref(''),
    lastHeaderDay: ref(''),
    autoScroll: ref(autoScroll),
    stripTimePrefix: text => text,
    scrollToBottom,
  })
  return { api, scrollToBottom }
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