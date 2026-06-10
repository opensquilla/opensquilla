import { nextTick, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatRenderedMessage,
  ChatStreamTimelineItem,
} from '@/types/chat'
import { copyTextWithFallback } from '@/utils/browser'

export interface UseChatMessageActionsOptions {
  messages: Ref<ChatMessage[]>
  inputText: Ref<string>
  isStreaming: Ref<boolean>
  sanitizeCopyText: (text: string) => string
  stripTimePrefix: (text: string) => string
  autoResizeTextarea: () => void
  sendCurrentInput: () => void
  focusComposer: () => void
}

export function useChatMessageActions(options: UseChatMessageActionsOptions) {
  function copyableMessageText(message: ChatRenderedMessage): string {
    // User bubbles render the raw text with only the time prefix stripped, so
    // copy must match: the markdown sanitizers would truncate or strip literal
    // text (e.g. "<details>") that is visible on screen.
    if ((message.displayRole || message.role) === 'user') {
      return options.stripTimePrefix(message.text || '').trim()
    }
    // Tool-bearing turns render text as separate timeline segments; the raw
    // message text concatenates them without separators, so rebuild from the
    // segments to keep paragraph boundaries in the copied markdown.
    const segmentTexts = (message.timelineItems || [])
      .filter((item): item is Extract<ChatStreamTimelineItem, { type: 'text' }> => item.type === 'text')
      .map(item => options.sanitizeCopyText(item.rawText || ''))
      .filter(Boolean)
    if (segmentTexts.length) return segmentTexts.join('\n\n')
    return options.sanitizeCopyText(message.text || '')
  }

  async function copyMessage(msg: ChatRenderedMessage): Promise<boolean> {
    try {
      await copyTextWithFallback(copyableMessageText(msg))
      return true
    } catch (err) {
      console.warn('Copy failed:', err instanceof Error ? err.message : String(err))
      return false
    }
  }

  function sourceMessageIndex(message: ChatRenderedMessage): number {
    if (typeof message.sourceIndex === 'number' && message.sourceIndex >= 0) {
      return message.sourceIndex
    }
    if (message.messageId) {
      return options.messages.value.findIndex(msg => msg.messageId === message.messageId)
    }
    return -1
  }

  function previousUserMessageIndex(beforeIndex: number): number {
    const startIndex = beforeIndex >= 0 ? beforeIndex - 1 : options.messages.value.length - 1
    for (let i = startIndex; i >= 0; i--) {
      if (options.messages.value[i]?.role === 'user') return i
    }
    return -1
  }

  function regenerateMessage(message: ChatRenderedMessage) {
    if (options.isStreaming.value) {
      console.warn('Wait for the current response to finish')
      return
    }
    const assistantIndex = sourceMessageIndex(message)
    const userMsgIndex = previousUserMessageIndex(assistantIndex)
    if (userMsgIndex < 0) {
      console.warn('No previous message to regenerate')
      return
    }

    const userText = options.messages.value[userMsgIndex]?.text || ''
    options.messages.value = options.messages.value.slice(0, userMsgIndex)
    options.inputText.value = userText
    options.autoResizeTextarea()
    nextTick(() => options.sendCurrentInput())
  }

  function editMessage(message: ChatRenderedMessage) {
    if (options.isStreaming.value) {
      console.warn('Wait for the current response to finish')
      return
    }
    const msgIndex = sourceMessageIndex(message)
    if (msgIndex < 0) return
    if (options.messages.value[msgIndex]?.role !== 'user') return
    const text = options.messages.value[msgIndex].text || ''
    options.messages.value = options.messages.value.slice(0, msgIndex)
    options.inputText.value = text
    options.autoResizeTextarea()
    options.focusComposer()
  }

  return {
    copyMessage,
    regenerateMessage,
    editMessage,
  }
}
