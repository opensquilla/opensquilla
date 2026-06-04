import type { Ref } from 'vue'
import type { Attachment, ChatMessage } from '@/types/chat'
import type {
  ChatSendParams,
  ChatSendResponse,
} from '@/types/rpc'
import type { ChatRpcStreamApi } from '@/composables/chat/useChatRpcEventHandlers'

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface UseChatSendOptions {
  rpc: RpcClient
  inputText: Ref<string>
  messages: Ref<ChatMessage[]>
  sessionKey: Ref<string>
  elevatedMode: Ref<string>
  pendingAttachments: Ref<Attachment[]>
  pendingSessionIntent: Ref<string | null>
  aborted: Ref<boolean>
  autoScroll: Ref<boolean>
  stream: ChatRpcStreamApi
  normalizeElevatedMode: (mode: string) => string
  persistSession: (key: string) => void
  isCompactInFlightForCurrentSession: () => boolean
  hasPendingAttachmentWork: () => boolean
  enqueuePendingInput: (text: string) => boolean
  popAllPendingIntoComposer: () => boolean
  executeSlashCommand: (text: string) => Promise<boolean>
  closeSlashMenu: () => void
  autoResizeTextarea: () => void
  scrollToBottom: () => void
}

export function useChatSend(options: UseChatSendOptions) {
  async function onSend() {
    let text = options.inputText.value.trim()
    let hasPayload = text || options.pendingAttachments.value.length > 0
    let isLiteralSlash = false

    if (options.hasPendingAttachmentWork()) {
      console.warn('Wait for file attachment processing to finish')
      return
    }

    if (text.startsWith('//')) {
      isLiteralSlash = true
      text = text.slice(1)
      hasPayload = text || options.pendingAttachments.value.length > 0
    }

    const compactInFlight = options.isCompactInFlightForCurrentSession()
    if (options.stream.isStreaming.value || compactInFlight) {
      if (!isLiteralSlash && text.startsWith('/')) {
        console.warn(`Wait for ${compactInFlight ? 'context compaction' : 'the current response'} before running ${text.split(/\s+/, 1)[0]}.`)
        return
      }
      if (!hasPayload) return
      options.enqueuePendingInput(text)
      return
    }

    if (!isLiteralSlash && text.startsWith('/')) {
      const handled = await options.executeSlashCommand(text)
      if (handled) return
    }

    if (!hasPayload || !options.sessionKey.value) return

    options.aborted.value = false
    options.closeSlashMenu()

    const now = new Date().toISOString()
    const userText = text
    options.messages.value.push({ role: 'user', text: userText, ts: now })
    options.autoScroll.value = true
    options.scrollToBottom()

    const params: ChatSendParams = { message: text || 'Describe these attachments', sessionKey: options.sessionKey.value }
    const elevated = options.normalizeElevatedMode(options.elevatedMode.value)
    if (elevated) params._source = { elevated }
    if (options.pendingSessionIntent.value) {
      params.intent = options.pendingSessionIntent.value
      options.pendingSessionIntent.value = null
    }
    if (options.pendingAttachments.value.length > 0) {
      params.displayText = userText
      params.attachments = options.pendingAttachments.value.map((a) => {
        if (a.kind === 'staged') return { type: a.mime, file_uuid: a.file_uuid, mime: a.mime, name: a.name }
        return { type: a.mime || 'image/png', data: a.data, mime: a.mime, name: a.name }
      })
    }

    options.inputText.value = ''
    options.autoResizeTextarea()
    options.pendingAttachments.value = []

    options.stream.startStreaming()
    options.stream.showThinkingIndicator()

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      if (res?.sessionKey && res.sessionKey !== options.sessionKey.value) options.persistSession(res.sessionKey)
    } catch (err: unknown) {
      options.stream.endStreaming()
      const message = err instanceof Error ? err.message : String(err)
      options.messages.value.push({ role: 'error', text: 'Send failed: ' + message, ts: new Date().toISOString() })
    }
  }

  function onStop() {
    if (!options.stream.isStreaming.value) return
    options.aborted.value = true
    options.rpc.call('chat.abort', { sessionKey: options.sessionKey.value }).catch(() => {})
    options.stream.endStreaming({ reason: 'aborted' })
    const recovered = options.popAllPendingIntoComposer()
    console.warn(recovered ? 'Stopped -- pending recovered to input' : 'Stopped')
  }

  return {
    onSend,
    onStop,
  }
}
