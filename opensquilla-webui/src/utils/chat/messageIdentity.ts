import type { ChatRenderedMessage } from '@/types/chat'

export function chatMessageKey(message: ChatRenderedMessage, index: number): string {
  return message.messageId || message.id || `${message.displayRole || message.role}-${message.sourceIndex ?? index}`
}

export function isShareableChatMessage(message: ChatRenderedMessage): boolean {
  if (message.stopNotice) return false
  return message.displayRole === 'user' || message.displayRole === 'assistant'
}
