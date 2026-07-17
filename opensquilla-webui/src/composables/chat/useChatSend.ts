import type { Ref } from 'vue'
import i18n from '@/i18n'
import { useToasts } from '@/composables/useToasts'
import type { RpcClientError } from '@/lib/rpc'
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
import { createClientMessageId, createClientRequestId } from '@/utils/chat/messageIdentity'
import {
  FINISHED_STREAM_TASK_ID,
  PENDING_STREAM_TASK_ID,
  STOPPED_STREAM_TASK_ID,
  taskTerminalMessage,
} from '@/utils/chat/streamEvents'

type RpcClient = {
  call: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

type PersistSessionOptions = { updateRoute?: boolean; source?: string }

interface SendAttempt {
  clientRequestId: string
  composerText: string
  requestSessionKey: string
  queueMode?: 'steer'
  text: string
  attachments: SendableAttachment[]
  intent: string | null
  forkBeforeMessageId: string | null
  params: ChatSendParams
}

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

function shouldRestoreSendAttempt(err: unknown): boolean {
  // Unknown acceptance (for example a lost response) is safe to retry because
  // the exact attempt keeps its durable clientRequestId. Only a positive
  // accepted signal proves that restoring the composer would be misleading.
  return (err as RpcClientError | null | undefined)?.accepted !== true
}

const TERMINAL_TASK_STATUSES = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'timeout',
  'abandoned',
])

function terminalResponseStatus(response: ChatSendResponse | null | undefined): string {
  const status = String(response?.task_status || response?.taskStatus || '').toLowerCase()
  return TERMINAL_TASK_STATUSES.has(status) ? status : ''
}

function terminalReplayMessage(response: ChatSendResponse, status: string): string {
  const supplied = response.terminal_message || response.terminalMessage ||
    response.terminal_reason || response.terminalReason || response.reason
  if (typeof supplied === 'string' && supplied.trim()) return supplied.trim()
  return taskTerminalMessage(status, {})
}

function terminalReplayErrorCode(response: ChatSendResponse, status: string): string {
  const reason = response.terminal_reason || response.terminalReason || response.reason
  const normalized = typeof reason === 'string' ? reason.trim().toLowerCase() : ''
  return /^[a-z][a-z0-9_.-]*$/.test(normalized) ? normalized : status
}

function sameSendableAttachments(
  attachments: SendableAttachment[],
  attempt: SendAttempt,
): boolean {
  if (attachments.length !== attempt.attachments.length) return false
  return attachments.every((attachment, index) => {
    const prior = attempt.attachments[index]
    return (
      prior?.local_id === attachment.local_id &&
      JSON.stringify(serializeSendableAttachment(prior)) ===
        JSON.stringify(serializeSendableAttachment(attachment))
    )
  })
}

function matchesRecoveredDraft(
  attempt: SendAttempt,
  input: {
    requestSessionKey: string
    text: string
    attachments: SendableAttachment[]
    intent: string | null
    forkBeforeMessageId: string | null
  },
): boolean {
  return (
    attempt.requestSessionKey === input.requestSessionKey &&
    attempt.text === input.text &&
    attempt.intent === input.intent &&
    attempt.forkBeforeMessageId === input.forkBeforeMessageId &&
    sameSendableAttachments(input.attachments, attempt)
  )
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
  pendingForkBeforeMessageId: Ref<string | null>
  aborted: Ref<boolean>
  // Task id rendered by the live stream; a fresh turn binds it from the
  // chat.send response so a prior task's late events can't leak in (issue #344).
  activeStreamTaskId: Ref<string>
  activeStreamSessionKey: Ref<string>
  autoScroll: Ref<boolean>
  stream: ChatRpcStreamApi
  normalizeElevatedMode: (mode: string) => string
  persistSession: (key: string, options?: PersistSessionOptions) => void
  scheduleHistorySync: () => void
  // Event frames can beat the chat.send response. The event handler owns the
  // pending-terminal buffer and consumes only the task id accepted here.
  bindActiveStreamTask?: (taskId: string) => void
  isCompactInFlightForCurrentSession: () => boolean
  hasPendingAttachmentWork: () => boolean
  prepareAttachmentsForSend?: (options?: { isCurrent?: () => boolean }) => Promise<boolean>
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
  let activeFreshSendToken: symbol | null = null
  let recoveredAttempt: SendAttempt | null = null

  function beginFreshStream(requestSessionKey: string): symbol {
    const token = Symbol('fresh-send')
    activeFreshSendToken = token
    options.activeStreamTaskId.value = PENDING_STREAM_TASK_ID
    options.activeStreamSessionKey.value = requestSessionKey
    options.stream.startStreaming()
    options.stream.showThinkingIndicator()
    return token
  }

  function freshSendStillOwnsStream(token: symbol | null, requestSessionKey: string): boolean {
    return (
      token !== null &&
      activeFreshSendToken === token &&
      options.sessionKey.value === requestSessionKey
    )
  }

  function acceptedTaskId(response: ChatSendResponse | null | undefined): string {
    return response?.task_id || response?.taskId || ''
  }

  function bindAcceptedTask(taskId: string) {
    if (options.bindActiveStreamTask) {
      options.bindActiveStreamTask(taskId)
      return
    }
    options.activeStreamTaskId.value = taskId
  }

  function handleTerminalResponse(
    response: ChatSendResponse,
    freshSendToken: symbol | null,
    optionsForResponse: { finishFreshStream: boolean },
  ): boolean {
    const status = terminalResponseStatus(response)
    if (!status) return false
    if (optionsForResponse.finishFreshStream) {
      if (activeFreshSendToken === freshSendToken) activeFreshSendToken = null
      options.activeStreamTaskId.value = FINISHED_STREAM_TASK_ID
      options.activeStreamSessionKey.value = ''
      options.stream.endStreaming(status === 'cancelled' ? { reason: 'aborted' } : undefined)
    }
    if (status !== 'succeeded') {
      options.messages.value.push({
        role: 'error',
        text: terminalReplayMessage(response, status),
        errorCode: terminalReplayErrorCode(response, status),
        terminalNotice: true,
        ts: new Date().toISOString(),
      })
    }
    options.scheduleHistorySync()
    return true
  }

  function abortStaleAcceptedTask(response: ChatSendResponse | null | undefined, requestSessionKey: string) {
    if (options.sessionKey.value !== requestSessionKey) return
    const taskId = acceptedTaskId(response)
    if (!taskId) return
    options.rpc.call('chat.abort', {
      sessionKey: requestSessionKey,
      taskId,
      source: 'webui_stale_send',
    }).catch(() => {})
  }

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

    // Retry an ambiguous prior send with its exact original queue semantics,
    // even if the ambient stream state changed while the error was visible.
    // Deriving steer/followup again here would create a new fingerprint and
    // could duplicate a turn that the gateway already accepted.
    if (
      recoveredAttempt &&
      matchesRecoveredDraft(recoveredAttempt, {
        requestSessionKey: options.sessionKey.value,
        text,
        attachments: sendableAttachments,
        intent: options.pendingSessionIntent.value,
        forkBeforeMessageId: options.pendingForkBeforeMessageId.value,
      })
    ) {
      await dispatchSend(text, {
        composerText: options.inputText.value,
        queueMode: recoveredAttempt.queueMode,
      })
      return
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
        await dispatchSend(text, {
          composerText: options.inputText.value,
          queueMode: 'steer',
        })
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

    await dispatchSend(text, { composerText: options.inputText.value })
  }

  async function dispatchSend(
    text: string,
    sendOpts?: { composerText?: string; queueMode?: 'steer' },
  ) {
    const requestSessionKey = options.sessionKey.value
    if (!requestSessionKey) return
    const initialSendableAttachments = options.pendingAttachments.value.filter(isSendableAttachment)
    const retryCandidate = recoveredAttempt
    const isRecoveredRetry = Boolean(
      retryCandidate &&
      matchesRecoveredDraft(retryCandidate, {
        requestSessionKey,
        text,
        attachments: initialSendableAttachments,
        intent: options.pendingSessionIntent.value,
        forkBeforeMessageId: options.pendingForkBeforeMessageId.value,
      }) &&
      retryCandidate.queueMode === sendOpts?.queueMode,
    )
    const retryAttempt = isRecoveredRetry ? retryCandidate : null
    const sendAttachmentIds = new Set(
      (retryAttempt?.attachments || initialSendableAttachments)
        .map(attachment => attachment.local_id),
    )
    // A recovered attempt must keep the exact serialized attachment tokens and
    // metadata that were fingerprinted with its idempotency key.
    if (!retryAttempt && options.prepareAttachmentsForSend) {
      const ready = await options.prepareAttachmentsForSend({
        isCurrent: () => options.sessionKey.value === requestSessionKey,
      })
      if (!ready) return
      if (options.sessionKey.value !== requestSessionKey) return
    }
    const attachmentsToSend = retryAttempt?.attachments || options.pendingAttachments.value.filter((a): a is SendableAttachment => sendAttachmentIds.has(a.local_id) && isSendableAttachment(a))
    const attachmentsToKeep = options.pendingAttachments.value.filter(a => !sendAttachmentIds.has(a.local_id) || !isSendableAttachment(a))
    if (!text && attachmentsToSend.length === 0) return

    options.aborted.value = false
    options.closeSlashMenu()
    recordSessionNavigationDiag('send.start', {
      requestSession: requestSessionKey,
      current: requestSessionKey,
    })

    const userText = text
    const intent = options.pendingSessionIntent.value
    const forkBeforeMessageId = options.pendingForkBeforeMessageId.value
    let attempt = retryAttempt
    if (!attempt) {
      const clientMessageId = createClientMessageId()
      const params: ChatSendParams = {
        clientRequestId: createClientRequestId(),
        message: text || 'Describe these attachments',
        sessionKey: requestSessionKey,
      }
      if (sendOpts?.queueMode) params.queueMode = sendOpts.queueMode
      params._source = chatSourceMetadata(options)
      if (intent) params.intent = intent
      if (forkBeforeMessageId) params.forkBeforeMessageId = forkBeforeMessageId
      if (attachmentsToSend.length > 0) {
        params.displayText = userText
        params.attachments = attachmentsToSend.map(serializeSendableAttachment)
      }
      attempt = {
        clientRequestId: params.clientRequestId!,
        composerText: sendOpts?.composerText ?? text,
        requestSessionKey,
        queueMode: sendOpts?.queueMode,
        text,
        attachments: attachmentsToSend.map(attachment => ({ ...attachment })),
        intent,
        forkBeforeMessageId,
        params,
      }
      const now = new Date().toISOString()
      const displayAttachments = attachmentsToSend.map(serializeDisplayAttachment)
      options.messages.value.push({
        role: 'user',
        text: userText,
        ts: now,
        clientId: clientMessageId,
        ...(displayAttachments.length > 0 ? { attachments: displayAttachments } : {}),
      })
      options.autoScroll.value = true
      options.scrollToBottom()
    }
    recoveredAttempt = null

    options.inputText.value = ''
    options.autoResizeTextarea()
    options.pendingAttachments.value = attachmentsToKeep
    if (options.pendingSessionIntent.value === intent) options.pendingSessionIntent.value = null
    if (options.pendingForkBeforeMessageId.value === forkBeforeMessageId) {
      options.pendingForkBeforeMessageId.value = null
    }

    // A steer send rides an already-active stream; restarting it would wipe
    // the partial output of the run being steered.
    const wasStreaming = options.stream.isStreaming.value
    const freshSendToken = wasStreaming ? null : beginFreshStream(requestSessionKey)

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', attempt.params)
      if (!wasStreaming && !freshSendStillOwnsStream(freshSendToken, requestSessionKey)) {
        abortStaleAcceptedTask(res, requestSessionKey)
        return
      }
      // Bind the live stream to this turn's task so a prior task's late events
      // can't bleed into it (issue #344). Only a fresh turn takes over rendering
      // — a steer/queue send rides the in-flight stream and must not rebind —
      // and only while this session is still the one on screen.
      const taskId = acceptedTaskId(res)
      const terminalStatus = terminalResponseStatus(res)
      const responseIsCurrent = options.sessionKey.value === requestSessionKey
      if (terminalStatus && responseIsCurrent) {
        handleTerminalResponse(res, freshSendToken, {
          finishFreshStream: !wasStreaming,
        })
        // A terminal task response (including first-attempt activation failure)
        // may have no future live event. Fresh turns close their spinner;
        // steer responses only surface the result without ending the older run.
      } else if (!terminalStatus && !wasStreaming && responseIsCurrent) {
        options.activeStreamSessionKey.value = res?.sessionKey || requestSessionKey
        if (taskId) bindAcceptedTask(taskId)
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
      if (!wasStreaming && !freshSendStillOwnsStream(freshSendToken, requestSessionKey)) {
        return
      }
      if (!wasStreaming) {
        if (activeFreshSendToken === freshSendToken) activeFreshSendToken = null
        options.activeStreamTaskId.value = ''
        options.activeStreamSessionKey.value = ''
        options.stream.endStreaming()
      }
      if (shouldRestoreSendAttempt(err)) restoreSendAttempt(attempt)
      const message = errorMessage(err)
      options.messages.value.push({ role: 'error', text: 'Send failed: ' + message, ts: new Date().toISOString() })
    }
  }

  function restoreSendAttempt(attempt: SendAttempt) {
    const currentText = options.inputText.value
    if (!currentText) {
      options.inputText.value = attempt.composerText
    } else if (currentText !== attempt.composerText) {
      options.inputText.value = [attempt.composerText, currentText].filter(Boolean).join('\n')
    }
    restoreSendableAttachments(attempt.attachments)
    if (!options.pendingSessionIntent.value) options.pendingSessionIntent.value = attempt.intent
    if (!options.pendingForkBeforeMessageId.value) {
      options.pendingForkBeforeMessageId.value = attempt.forkBeforeMessageId
    }
    recoveredAttempt = attempt
    options.autoResizeTextarea()
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
    const abortSessionKey = options.activeStreamSessionKey.value || options.sessionKey.value
    const abortTaskId = options.activeStreamTaskId.value
    activeFreshSendToken = null
    options.activeStreamTaskId.value = STOPPED_STREAM_TASK_ID
    // Be honest if the abort can't reach the gateway (e.g. the socket dropped):
    // we still tear the local stream down for responsiveness, but the user must
    // know the server-side run may keep going rather than trust a false "stopped".
    const abortParams: Record<string, string> = { sessionKey: abortSessionKey, source: 'webui_stop' }
    if (abortTaskId && !abortTaskId.startsWith('__opensquilla_')) abortParams.taskId = abortTaskId
    options.rpc.call('chat.abort', abortParams).catch(() => {
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

    const params: ChatSendParams = {
      clientRequestId: createClientRequestId(),
      message: providerText,
      sessionKey: requestSessionKey,
    }
    if (displayText && displayText !== providerText) params.displayText = displayText
    params._source = chatSourceMetadata(options)

    const wasStreaming = options.stream.isStreaming.value
    const freshSendToken = wasStreaming ? null : beginFreshStream(requestSessionKey)

    try {
      const res = await options.rpc.call<ChatSendResponse>('chat.send', params)
      if (!wasStreaming && !freshSendStillOwnsStream(freshSendToken, requestSessionKey)) {
        abortStaleAcceptedTask(res, requestSessionKey)
        return
      }
      // Bind the live stream to this turn's task so a prior task's late events
      // can't bleed into it (issue #344). Only a fresh turn takes over rendering
      // — a steer/queue send rides the in-flight stream and must not rebind —
      // and only while this session is still the one on screen.
      const taskId = acceptedTaskId(res)
      if (handleTerminalResponse(res, freshSendToken, { finishFreshStream: !wasStreaming })) {
        // See dispatchSend: a terminal response has no future lifecycle event.
      } else if (!wasStreaming && options.sessionKey.value === requestSessionKey) {
        options.activeStreamSessionKey.value = res?.sessionKey || requestSessionKey
        if (taskId) bindAcceptedTask(taskId)
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
      if (!wasStreaming && !freshSendStillOwnsStream(freshSendToken, requestSessionKey)) {
        return
      }
      if (!wasStreaming) {
        if (activeFreshSendToken === freshSendToken) activeFreshSendToken = null
        options.activeStreamTaskId.value = ''
        options.activeStreamSessionKey.value = ''
        options.stream.endStreaming()
      }
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
