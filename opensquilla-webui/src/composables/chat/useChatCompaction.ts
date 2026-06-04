import { ref, type Ref } from 'vue'

export type ChatCompactStatusTone = 'info' | 'ok' | 'warn' | 'err' | string

export interface ChatCompactStatus {
  visible: boolean
  message: string
  detail: string
  tone: ChatCompactStatusTone
  isBusy: boolean
}

export interface ShowCompactStatusOptions {
  tone?: ChatCompactStatusTone
  detail?: string
  dismissMs?: number
}

export interface UseChatCompactionOptions {
  sessionKey: Ref<string>
  schedulePendingDrainAfterTerminal: () => void
  popAllPendingIntoComposer: () => boolean
}

interface ChatCompactPayload extends Record<string, unknown> {
  key?: string
  status?: string
  compacted?: boolean
  source?: string
  refused?: boolean
  safe_to_send?: boolean
  safeToSend?: boolean
  reason?: string
  error_reason?: string
  errorClass?: string
  error_class?: string
  error?: { reason?: string; code?: string }
}

interface SettleCompactOptions {
  preservePending?: boolean
  recoverPending?: boolean
}

interface ChatCompactMeta {
  replayed?: boolean
}

const EMPTY_COMPACT_STATUS: ChatCompactStatus = {
  visible: false,
  message: '',
  detail: '',
  tone: 'info',
  isBusy: false,
}

function createEmptyCompactStatus(): ChatCompactStatus {
  return { ...EMPTY_COMPACT_STATUS }
}

export function useChatCompaction(options: UseChatCompactionOptions) {
  const compactInFlight = ref(false)
  const compactInFlightKey = ref('')
  const compactStatus = ref<ChatCompactStatus>(createEmptyCompactStatus())
  let dismissTimer: ReturnType<typeof setTimeout> | null = null

  function clearDismissTimer() {
    if (!dismissTimer) return
    clearTimeout(dismissTimer)
    dismissTimer = null
  }

  function isCompactInFlightForCurrentSession(): boolean {
    if (!compactInFlight.value) return false
    return !compactInFlightKey.value || compactInFlightKey.value === options.sessionKey.value
  }

  function setCompactInFlight(active: boolean, key = options.sessionKey.value) {
    compactInFlight.value = active
    compactInFlightKey.value = active ? String(key || options.sessionKey.value || '') : ''
  }

  function hideCompactStatus() {
    clearDismissTimer()
    compactStatus.value = createEmptyCompactStatus()
  }

  function showCompactStatus(status: string, message: string, statusOptions: ShowCompactStatusOptions = {}) {
    clearDismissTimer()
    compactStatus.value = {
      visible: true,
      message,
      detail: statusOptions.detail || '',
      tone: statusOptions.tone || 'info',
      isBusy: status === 'started',
    }
    if (statusOptions.dismissMs && statusOptions.dismissMs > 0) {
      dismissTimer = setTimeout(() => {
        dismissTimer = null
        hideCompactStatus()
      }, statusOptions.dismissMs)
    }
  }

  function compactFailureBlocksPending(payload: ChatCompactPayload): boolean {
    if (!payload) return false
    if (payload.refused === true || payload.safe_to_send === false || payload.safeToSend === false) return true
    const reason = String(payload.reason || payload.error_reason || payload.errorClass || payload.error_class || payload.error?.reason || payload.error?.code || '').toLowerCase()
    return ['compaction_insufficient', 'compaction_flush_failed', 'context_overflow', 'unsafe_flush_receipt'].includes(reason)
  }

  function settleCompactInFlight(payload: ChatCompactPayload = {}, settleOptions: SettleCompactOptions = {}) {
    const key = String(payload.key || compactInFlightKey.value || options.sessionKey.value || '')
    if (!compactInFlight.value || (compactInFlightKey.value && key && key !== compactInFlightKey.value)) return false
    setCompactInFlight(false)
    const status = String(payload.status || '').toLowerCase()
    const compactedFlag = Object.prototype.hasOwnProperty.call(payload, 'compacted') ? !!payload.compacted : null
    if (status === 'completed' || status === 'skipped' || (status === '' && compactedFlag !== null)) {
      options.schedulePendingDrainAfterTerminal()
    } else if (settleOptions.preservePending) {
      // Pending queue remains blocked until the user acts.
    } else if (settleOptions.recoverPending) {
      options.popAllPendingIntoComposer()
    }
    return true
  }

  function showCompactionToast(payload: ChatCompactPayload, meta: ChatCompactMeta = {}) {
    if (meta.replayed) return
    let status = String(payload.status || '').toLowerCase()
    if (!status && Object.prototype.hasOwnProperty.call(payload, 'compacted')) {
      status = payload.compacted ? 'completed' : 'skipped'
    }
    const source = String(payload.source || '').toLowerCase()

    if (status === 'started') {
      if (source === 'manual') setCompactInFlight(true, payload.key || options.sessionKey.value)
      showCompactStatus('started', 'Compacting context...', { tone: 'info' })
      return
    }
    if (status === 'skipped') {
      settleCompactInFlight(payload || {})
      showCompactStatus('skipped', 'Already within context budget; no compact was applied.', { tone: 'info', dismissMs: 5000 })
      return
    }
    if (status === 'failed' || status === 'error') {
      const preservePending = compactFailureBlocksPending(payload || {})
      settleCompactInFlight(payload || {}, { preservePending })
      showCompactStatus('failed', 'Compact failed', { tone: 'err', dismissMs: 10000 })
      return
    }
    if (status === 'cancelled') {
      settleCompactInFlight(payload || {}, { recoverPending: true })
      showCompactStatus('cancelled', 'Compact cancelled', { tone: 'warn', dismissMs: 8000 })
      return
    }
    if (status === 'completed') {
      settleCompactInFlight(payload || {})
      showCompactStatus('completed', 'Context compacted', { tone: 'ok', dismissMs: 5000 })
    }
  }

  function cleanup() {
    clearDismissTimer()
  }

  return {
    compactStatus,
    isCompactInFlightForCurrentSession,
    setCompactInFlight,
    hideCompactStatus,
    showCompactStatus,
    showCompactionToast,
    cleanup,
  }
}
