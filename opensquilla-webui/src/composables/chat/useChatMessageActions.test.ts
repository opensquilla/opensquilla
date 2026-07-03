import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

import { useChatMessageActions, type UseChatMessageActionsOptions } from './useChatMessageActions'
import type { ChatMessage, ChatRenderedMessage } from '@/types/chat'

function renderedMessage(overrides: Partial<ChatRenderedMessage>): ChatRenderedMessage {
  return {
    role: 'user',
    displayRole: 'user',
    roleLabel: 'User',
    text: '',
    timeStr: '',
    showHeader: false,
    ...overrides,
  }
}

function makeOptions(messages: ChatMessage[]) {
  const pendingForkBeforeMessageId = ref<string | null>(null)
  const options: UseChatMessageActionsOptions = {
    messages: ref(messages),
    inputText: ref(''),
    isStreaming: ref(false),
    sanitizeCopyText: text => text,
    stripTimePrefix: text => text,
    autoResizeTextarea: vi.fn(),
    sendCurrentInput: vi.fn(),
    focusComposer: vi.fn(),
    pendingForkBeforeMessageId,
  }
  return { api: useChatMessageActions(options), options, pendingForkBeforeMessageId }
}

describe('useChatMessageActions branching edits', () => {
  it('records the edited user message id before trimming local history', () => {
    const { api, options, pendingForkBeforeMessageId } = makeOptions([
      { role: 'user', text: 'A', ts: null, messageId: 'msg-A' },
      { role: 'assistant', text: 'ack A', ts: null, messageId: 'msg-a1' },
      { role: 'user', text: 'B', ts: null, messageId: 'msg-B' },
      { role: 'assistant', text: 'ack B', ts: null, messageId: 'msg-b1' },
    ])

    api.editMessage(renderedMessage({
      role: 'user',
      displayRole: 'user',
      sourceIndex: 2,
      messageId: 'msg-B',
      text: 'B',
    }))

    expect(pendingForkBeforeMessageId.value).toBe('msg-B')
    expect(options.messages.value.map(message => message.text)).toEqual(['A', 'ack A'])
    expect(options.inputText.value).toBe('B')
    expect(options.focusComposer).toHaveBeenCalledOnce()
  })

  it('records the previous user message id before regenerating', async () => {
    const { api, options, pendingForkBeforeMessageId } = makeOptions([
      { role: 'user', text: 'A', ts: null, messageId: 'msg-A' },
      { role: 'assistant', text: 'ack A', ts: null, messageId: 'msg-a1' },
      { role: 'user', text: 'B', ts: null, messageId: 'msg-B' },
      { role: 'assistant', text: 'ack B', ts: null, messageId: 'msg-b1' },
      { role: 'user', text: 'C', ts: null, messageId: 'msg-C' },
    ])

    api.regenerateMessage(renderedMessage({
      role: 'assistant',
      displayRole: 'assistant',
      sourceIndex: 3,
      messageId: 'msg-b1',
      text: 'ack B',
    }))
    await nextTick()

    expect(pendingForkBeforeMessageId.value).toBe('msg-B')
    expect(options.messages.value.map(message => message.text)).toEqual(['A', 'ack A'])
    expect(options.inputText.value).toBe('B')
    expect(options.sendCurrentInput).toHaveBeenCalledOnce()
  })
})
