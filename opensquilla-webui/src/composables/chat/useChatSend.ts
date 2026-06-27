import type { Ref } from 'vue'
import { useToasts } from '@/composables/useToasts'
import type { Attachment, ChatMessage } from '@/types/chat'
import type {
  ChatSendParams,
  ChatSendResponse,
} from '@/types/rpc'
import type { ChatRpcStreamApi } from '@/composables/chat/useChatRpcEventHandlers'
import type { BusySendMode } from '@/composables/chat/useChatPendingQueue'

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export interface UseChatSendOptions {
  rpc: RpcClient
  inputText: Ref<string>
  messages: Ref<ChatMessage[]>
  sessionKey: Ref<string>
  busySendMode: Ref<BusySendMode>
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
  enqueueHiddenControl?: (item: { text: string; displayText: string }) => boolean
  popAllPendingIntoComposer: () => boolean
  executeSlashCommand: (text: string) => Promise<boolean>
  closeSlashMenu: () => void
  autoResizeTextarea: () => void
  scrollToBottom: () => void
}

export function useChatSend(options: UseChatSendOptions) {
  const { pushToast } = useToasts()

  async function onSend() {
    let text = options.inputText.value.trim()
    let hasPayload = text || options.pendingAttachments.value.length > 0
    let isLiteralSlash = false

    if (options.hasPendingAttachmentWork()) {
      pushToast('Wait for file attachment processing to finish', { tone: 'info' })
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
        pushToast(`Wait for ${compactInFlight ? 'context compaction' : 'the current response'} before running ${text.split(/\s+/, 1)[0]}.`, { tone: 'info' })
        return
      }
      if (!hasPayload) return
      // Steer injects into the active run right away; compaction cannot be
      // steered, so those sends still queue until it finishes.
      if (options.busySendMode.value === 'steer' && !compactInFlight) {
        await dispatchSend(text, { queueMode: 'steer' })
        return
      }
      // Surface a full queue instead of silently dropping the send: the draft is
      // preserved (enqueue returns false before clearing the composer).
      if (!options.enqueuePendingInput(text)) {
        pushToast('Queue is full — wait for the current response to finish.', { tone: 'info' })
      }
      return
    }

    if (!isLiteralSlash && text.startsWith('/')) {
      const handled = await options.executeSlashCommand(text)
      if (handled) return
    }

    if (!hasPayload || !options.sessionKey.value) return

    await dispatchSend(text)
  }

  async function dispatchSend(text: string, sendOpts?: { queueMode?: 'steer' }) {
    if (!options.sessionKey.value) return

    options.aborted.value = false
    options.closeSlashMenu()

    const now = new Date().toISOString()
    const userText = text
    options.messages.value.push({ role: 'user', text: userText, ts: now })
    options.autoScroll.value = true
    options.scrollToBottom()

    const params: ChatSendParams = { message: text || 'Describe these attachments', sessionKey: options.sessionKey.value }
    if (sendOpts?.queueMode) params.queueMode = sendOpts.queueMode
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

    // A steer send rides an already-active stream; restarting it would wipe
    // the partial output of the run being steered.
    const wasStreaming = options.stream.isStreaming.value
    if (!wasStreaming) {
      options.stream.startStreaming()
      options.stream.showThinkingIndicator()
    }

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      if (res?.sessionKey && res.sessionKey !== options.sessionKey.value) options.persistSession(res.sessionKey)
    } catch (err: unknown) {
      if (!wasStreaming) options.stream.endStreaming()
      const message = err instanceof Error ? err.message : String(err)
      options.messages.value.push({ role: 'error', text: 'Send failed: ' + message, ts: new Date().toISOString() })
    }
  }

  function onStop() {
    if (!options.stream.isStreaming.value) return
    options.aborted.value = true
    // Be honest if the abort can't reach the gateway (e.g. the socket dropped):
    // we still tear the local stream down for responsiveness, but the user must
    // know the server-side run may keep going rather than trust a false "stopped".
    options.rpc.call('chat.abort', { sessionKey: options.sessionKey.value }).catch(() => {
      options.messages.value.push({
        role: 'system',
        text: 'Stop could not reach the server — the run may still be finishing.',
        ts: new Date().toISOString(),
      })
    })
    options.stream.endStreaming({ reason: 'aborted' })
    options.popAllPendingIntoComposer()
  }

  /**
   * Hidden control send: dispatches chat.send with provider text that carries
   * the meta_preflight markers, optionally with a visible displayText bubble.
   * Unlike dispatchSend it does NOT push the provider text as a user bubble,
   * does NOT consume composer text/attachments/intent, and does NOT clear the
   * composer — the operator's draft is preserved. When the turn is streaming or
   * compaction is in flight, it is queued (carrying provider + display text and
   * a hiddenControl flag) so the drain restores both.
   */
  async function dispatchHiddenSend(providerText: string, displayText: string) {
    if (!options.sessionKey.value || !providerText) return
    const compactInFlight = options.isCompactInFlightForCurrentSession()
    if (options.stream.isStreaming.value || compactInFlight) {
      options.enqueueHiddenControl?.({ text: providerText, displayText })
      return
    }

    options.aborted.value = false
    // Show the visible confirmation as a user bubble (NOT the marker text).
    const now = new Date().toISOString()
    if (displayText) {
      options.messages.value.push({ role: 'user', text: displayText, ts: now })
      options.autoScroll.value = true
      options.scrollToBottom()
    }

    const params: ChatSendParams = { message: providerText, sessionKey: options.sessionKey.value }
    if (displayText && displayText !== providerText) params.displayText = displayText
    const elevated = options.normalizeElevatedMode(options.elevatedMode.value)
    if (elevated) params._source = { elevated }

    const wasStreaming = options.stream.isStreaming.value
    if (!wasStreaming) {
      options.stream.startStreaming()
      options.stream.showThinkingIndicator()
    }

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      if (res?.sessionKey && res.sessionKey !== options.sessionKey.value) options.persistSession(res.sessionKey)
    } catch (err: unknown) {
      if (!wasStreaming) options.stream.endStreaming()
      const message = err instanceof Error ? err.message : String(err)
      options.messages.value.push({ role: 'error', text: 'Send failed: ' + message, ts: new Date().toISOString() })
    }
  }

  /**
   * Build and dispatch the hidden meta-preflight confirmation. The
   * server-authored confirmed.message is preferred (it carries the base64url
   * meta_preflight_fields marker); the JS fallback embeds the two required
   * HTML-comment markers keyed by the Python preflight protocol parser.
   */
  function sendHiddenMetaPreflightConfirmation(
    confirmed: { message?: string } | null,
    detail: { runId: string; metaSkillName: string; interpretedRequest: string; language: string },
  ) {
    const interpreted = (detail.interpretedRequest || '').trim()
    const fallback =
      `${interpreted}\n\n<!-- opensquilla:meta_preflight_confirmed=1 -->` +
      (detail.runId ? `\n<!-- opensquilla:meta_preflight_run_id=${detail.runId} -->` : '')
    const providerText = confirmed?.message || fallback
    const zhFallback = detail.language === 'zh' ? '已确认，开始运行。' : 'Confirmed — starting the run.'
    const visibleText = interpreted || zhFallback
    void dispatchHiddenSend(providerText, visibleText)
  }

  return {
    onSend,
    onStop,
    dispatchHiddenSend,
    sendHiddenMetaPreflightConfirmation,
  }
}
