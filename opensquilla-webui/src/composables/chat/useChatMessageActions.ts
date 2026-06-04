import { nextTick, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatRenderedMessage,
} from '@/types/chat'
import { copyTextWithFallback } from '@/utils/browser'

export interface UseChatMessageActionsOptions {
  messages: Ref<ChatMessage[]>
  inputText: Ref<string>
  isStreaming: Ref<boolean>
  autoResizeTextarea: () => void
  sendCurrentInput: () => void
  focusComposer: () => void
}

export function useChatMessageActions(options: UseChatMessageActionsOptions) {
  function copyMessage(msg: ChatRenderedMessage) {
    copyTextWithFallback(msg.text || '').catch(() => {})
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
