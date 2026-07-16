import type { ChatRenderedMessage } from '@/types/chat'

export function chatMessageKey(message: ChatRenderedMessage, index: number): string {
  return message.messageId || message.clientId || message.id || `${message.displayRole || message.role}-${message.sourceIndex ?? index}`
}

let clientMessageSequence = 0
let clientRequestSequence = 0

export function createClientMessageId(): string {
  clientMessageSequence += 1
  return `local-${Date.now().toString(36)}-${clientMessageSequence.toString(36)}`
}

export function createClientRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  clientRequestSequence += 1
  return `web-${Date.now().toString(36)}-${clientRequestSequence.toString(36)}`
}

export function isShareableChatMessage(message: ChatRenderedMessage): boolean {
  if (message.stopNotice) return false
  return message.displayRole === 'user' || message.displayRole === 'assistant'
}
