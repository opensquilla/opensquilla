import type { Ref } from 'vue'
import i18n from '@/i18n'
import { useToasts } from '@/composables/useToasts'
import type { Attachment, ChatMessage } from '@/types/chat'
import type { SandboxRunMode } from '@/types/sandbox'
import { normalizeSandboxRunMode } from '@/types/sandbox'
import type {
  ChatSendParams,
  ChatSendResponse,
} from '@/types/rpc'
import type { ChatRpcStreamApi } from '@/composables/chat/useChatRpcEventHandlers'
import type { BusySendMode } from '@/composables/chat/useChatPendingQueue'
import { recordSessionNavigationDiag } from '@/utils/chat/sessionNavigationDiag'
import { isSendableAttachment, serializeDisplayAttachment, serializeSendableAttachment, type SendableAttachment } from '@/utils/chat/attachments'

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

type PersistSessionOptions = { updateRoute?: boolean; source?: string }

export type SendResponseSessionDecision =
  | { action: 'ignore'; reason: 'missing_response_session' | 'current_session_changed' | 'same_session' }
  | { action: 'persist'; responseSessionKey: string }

export function decideSendResponseSession(input: {
  requestSessionKey: string
  currentSessionKey: string
  responseSessionKey?: string | null
}): SendResponseSessionDecision {
  const responseSessionKey = input.responseSessionKey || ''
  if (!responseSessionKey) return { action: 'ignore', reason: 'missing_response_session' }
  if (input.currentSessionKey !== input.requestSessionKey) {
    return { action: 'ignore', reason: 'current_session_changed' }
  }
  if (responseSessionKey === input.currentSessionKey) {
    return { action: 'ignore', reason: 'same_session' }
  }
  return { action: 'persist', responseSessionKey }
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function chatSourceMetadata(options: UseChatSendOptions): ChatSendParams['_source'] {
  const elevated = options.normalizeElevatedMode(options.elevatedMode.value)
  return {
    ...(elevated ? { elevated } : {}),
    runMode: normalizeSandboxRunMode(options.runMode.value),
  }
}

export interface UseChatSendOptions {
  rpc: RpcClient
  inputText: Ref<string>
  messages: Ref<ChatMessage[]>
  sessionKey: Ref<string>
  busySendMode: Ref<BusySendMode>
  elevatedMode: Ref<string>
  runMode: Ref<SandboxRunMode>
  pendingAttachments: Ref<Attachment[]>
  pendingSessionIntent: Ref<string | null>
  aborted: Ref<boolean>
  // Task id rendered by the live stream; a fresh turn binds it from the
  // chat.send response so a prior task's late events can't leak in (issue #344).
  activeStreamTaskId: Ref<string>
  autoScroll: Ref<boolean>
  stream: ChatRpcStreamApi
  normalizeElevatedMode: (mode: string) => string
  persistSession: (key: string, options?: PersistSessionOptions) => void
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
    let sendableAttachments = options.pendingAttachments.value.filter(isSendableAttachment)
    let hasPayload = text || sendableAttachments.length > 0
    let isLiteralSlash = false

    if (options.hasPendingAttachmentWork()) {
      pushToast(i18n.global.t('chat.toast.waitAttachments'), { tone: 'info' })
      return
    }

    if (text.startsWith('//')) {
      isLiteralSlash = true
      text = text.slice(1)
      sendableAttachments = options.pendingAttachments.value.filter(isSendableAttachment)
      hasPayload = text || sendableAttachments.length > 0
    }

    const compactInFlight = options.isCompactInFlightForCurrentSession()
    if (options.stream.isStreaming.value || compactInFlight) {
      if (!isLiteralSlash && text.startsWith('/')) {
        pushToast(i18n.global.t(
          compactInFlight ? 'chat.toast.waitCompactionBeforeCommand' : 'chat.toast.waitResponseBeforeCommand',
          { command: text.split(/\s+/, 1)[0] },
        ), { tone: 'info' })
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
        pushToast(i18n.global.t('chat.toast.queueFull'), { tone: 'info' })
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
    const requestSessionKey = options.sessionKey.value
    if (!requestSessionKey) return
    const attachmentsToSend = options.pendingAttachments.value.filter(isSendableAttachment)
    const attachmentsToKeep = options.pendingAttachments.value.filter(a => !isSendableAttachment(a))

    options.aborted.value = false
    options.closeSlashMenu()
    recordSessionNavigationDiag('send.start', {
      requestSession: requestSessionKey,
      current: requestSessionKey,
    })

    const now = new Date().toISOString()
    const userText = text
    const displayAttachments = attachmentsToSend.map(serializeDisplayAttachment)
    options.messages.value.push({
      role: 'user',
      text: userText,
      ts: now,
      ...(displayAttachments.length > 0 ? { attachments: displayAttachments } : {}),
    })
    options.autoScroll.value = true
    options.scrollToBottom()

    const params: ChatSendParams = { message: text || 'Describe these attachments', sessionKey: requestSessionKey }
    if (sendOpts?.queueMode) params.queueMode = sendOpts.queueMode
    params._source = chatSourceMetadata(options)
    if (options.pendingSessionIntent.value) {
      params.intent = options.pendingSessionIntent.value
      options.pendingSessionIntent.value = null
    }
    if (attachmentsToSend.length > 0) {
      params.displayText = userText
      params.attachments = attachmentsToSend.map(serializeSendableAttachment)
    }

    options.inputText.value = ''
    options.autoResizeTextarea()
    options.pendingAttachments.value = attachmentsToKeep

    // A steer send rides an already-active stream; restarting it would wipe
    // the partial output of the run being steered.
    const wasStreaming = options.stream.isStreaming.value
    if (!wasStreaming) {
      options.stream.startStreaming()
      options.stream.showThinkingIndicator()
    }

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      // Bind the live stream to this turn's task so a prior task's late events
      // can't bleed into it (issue #344). Only a fresh turn takes over rendering
      // — a steer/queue send rides the in-flight stream and must not rebind —
      // and only while this session is still the one on screen.
      const acceptedTaskId = res?.task_id || res?.taskId || ''
      if (!wasStreaming && acceptedTaskId && options.sessionKey.value === requestSessionKey) {
        options.activeStreamTaskId.value = acceptedTaskId
      }
      const decision = decideSendResponseSession({
        requestSessionKey,
        currentSessionKey: options.sessionKey.value,
        responseSessionKey: res?.sessionKey,
      })
      if (decision.action === 'persist') {
        recordSessionNavigationDiag('send.response.persist', {
          requestSession: requestSessionKey,
          responseSession: decision.responseSessionKey,
          current: options.sessionKey.value,
        })
        options.persistSession(decision.responseSessionKey, { source: 'send.response' })
      } else if (decision.reason === 'current_session_changed') {
        recordSessionNavigationDiag('send.response.stale', {
          requestSession: requestSessionKey,
          responseSession: res?.sessionKey,
          current: options.sessionKey.value,
          reason: decision.reason,
        })
      }
    } catch (err: unknown) {
      if (options.sessionKey.value !== requestSessionKey) {
        recordSessionNavigationDiag('send.error.stale', {
          requestSession: requestSessionKey,
          current: options.sessionKey.value,
          reason: errorMessage(err),
        })
        return
      }
      if (!wasStreaming) options.stream.endStreaming()
      restoreSendableAttachments(attachmentsToSend)
      const message = errorMessage(err)
      options.messages.value.push({ role: 'error', text: 'Send failed: ' + message, ts: new Date().toISOString() })
    }
  }

  function restoreSendableAttachments(attachments: SendableAttachment[]) {
    if (attachments.length === 0) return
    const currentLocalIds = new Set(options.pendingAttachments.value.map(attachment => attachment.local_id))
    const missing = attachments.filter(attachment => !currentLocalIds.has(attachment.local_id))
    if (missing.length > 0) {
      options.pendingAttachments.value = [...missing, ...options.pendingAttachments.value]
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
    const requestSessionKey = options.sessionKey.value
    if (!requestSessionKey || !providerText) return
    const compactInFlight = options.isCompactInFlightForCurrentSession()
    if (options.stream.isStreaming.value || compactInFlight) {
      options.enqueueHiddenControl?.({ text: providerText, displayText })
      return
    }

    options.aborted.value = false
    recordSessionNavigationDiag('hiddenSend.start', {
      requestSession: requestSessionKey,
      current: requestSessionKey,
    })
    // Show the visible confirmation as a user bubble (NOT the marker text).
    const now = new Date().toISOString()
    if (displayText) {
      options.messages.value.push({ role: 'user', text: displayText, ts: now })
      options.autoScroll.value = true
      options.scrollToBottom()
    }

    const params: ChatSendParams = { message: providerText, sessionKey: requestSessionKey }
    if (displayText && displayText !== providerText) params.displayText = displayText
    params._source = chatSourceMetadata(options)

    const wasStreaming = options.stream.isStreaming.value
    if (!wasStreaming) {
      options.stream.startStreaming()
      options.stream.showThinkingIndicator()
    }

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      // Bind the live stream to this turn's task so a prior task's late events
      // can't bleed into it (issue #344). Only a fresh turn takes over rendering
      // — a steer/queue send rides the in-flight stream and must not rebind —
      // and only while this session is still the one on screen.
      const acceptedTaskId = res?.task_id || res?.taskId || ''
      if (!wasStreaming && acceptedTaskId && options.sessionKey.value === requestSessionKey) {
        options.activeStreamTaskId.value = acceptedTaskId
      }
      const decision = decideSendResponseSession({
        requestSessionKey,
        currentSessionKey: options.sessionKey.value,
        responseSessionKey: res?.sessionKey,
      })
      if (decision.action === 'persist') {
        recordSessionNavigationDiag('hiddenSend.response.persist', {
          requestSession: requestSessionKey,
          responseSession: decision.responseSessionKey,
          current: options.sessionKey.value,
        })
        options.persistSession(decision.responseSessionKey, { source: 'hiddenSend.response' })
      } else if (decision.reason === 'current_session_changed') {
        recordSessionNavigationDiag('hiddenSend.response.stale', {
          requestSession: requestSessionKey,
          responseSession: res?.sessionKey,
          current: options.sessionKey.value,
          reason: decision.reason,
        })
      }
    } catch (err: unknown) {
      if (options.sessionKey.value !== requestSessionKey) {
        recordSessionNavigationDiag('hiddenSend.error.stale', {
          requestSession: requestSessionKey,
          current: options.sessionKey.value,
          reason: errorMessage(err),
        })
        return
      }
      if (!wasStreaming) options.stream.endStreaming()
      const message = errorMessage(err)
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
