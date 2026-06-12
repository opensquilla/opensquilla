import { computed, ref, type Ref } from 'vue'

export type ChatCompactStatusTone = 'info' | 'ok' | 'warn' | 'err' | string

export interface ChatCompactStatus {
  visible: boolean
  message: string
  detail: string
  tone: ChatCompactStatusTone
  isBusy: boolean
  status: string
  /** Real context occupancy percent (0-100) from the event payload; null = unknown. */
  occupancyPercent: number | null
  /** Compact label for the context window size (e.g. "200k"); '' = unknown. */
  contextWindowLabel: string
}

export interface ShowCompactStatusOptions {
  tone?: ChatCompactStatusTone
  detail?: string
  dismissMs?: number
  occupancyPercent?: number | null
  contextWindowLabel?: string
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
  context_window_tokens?: unknown
  contextWindowTokens?: unknown
  tokens_before?: unknown
  tokensBefore?: unknown
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
  status: '',
  occupancyPercent: null,
  contextWindowLabel: '',
}

function createEmptyCompactStatus(): ChatCompactStatus {
  return { ...EMPTY_COMPACT_STATUS }
}

function toFiniteNumber(value: unknown): number | null {
  const num = typeof value === 'number'
    ? value
    : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN
  return Number.isFinite(num) ? num : null
}

function formatTokensCompact(tokens: number): string {
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k`
  return `${Math.round(tokens)}`
}

// Real occupancy needs both the window size and the current token count
// (automatic preflight compaction sends tokens_before; manual and tier-upgrade
// paths send only context_window_tokens). Anything less renders indeterminate.
function parseContextOccupancy(payload: ChatCompactPayload): { percent: number; windowLabel: string } | null {
  const windowTokens = toFiniteNumber(payload.context_window_tokens ?? payload.contextWindowTokens)
  const usedTokens = toFiniteNumber(payload.tokens_before ?? payload.tokensBefore)
  if (windowTokens === null || windowTokens <= 0 || usedTokens === null || usedTokens < 0) return null
  return {
    percent: Math.min(100, Math.max(0, Math.round((usedTokens / windowTokens) * 100))),
    windowLabel: formatTokensCompact(windowTokens),
  }
}

export function useChatCompaction(options: UseChatCompactionOptions) {
  const compactInFlight = ref(false)
  const compactInFlightKey = ref('')
  const compactStatus = ref<ChatCompactStatus>(createEmptyCompactStatus())
  let dismissTimer: ReturnType<typeof setTimeout> | null = null

  const compactTick = ref(0)
  const compactStartedAtMs = ref(0)
  const compactEndedAtMs = ref(0)
  let elapsedTimer: ReturnType<typeof setInterval> | null = null

  // Live elapsed seconds for the maintenance card. Empty until a real
  // 'started' has been observed in this view, so terminal events arriving
  // on their own (or replayed history) never show a fabricated duration.
  const compactElapsed = computed(() => {
    compactTick.value
    if (!compactStartedAtMs.value) return ''
    const end = compactEndedAtMs.value || Date.now()
    const seconds = Math.max(0, Math.floor((end - compactStartedAtMs.value) / 1000))
    return `${seconds}s`
  })

  function stopElapsedTimer() {
    if (!elapsedTimer) return
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }

  function startElapsedTicker() {
    // A repeated 'started' (optimistic slash call followed by the gateway
    // event) keeps the running clock instead of resetting it.
    if (!compactStartedAtMs.value || compactEndedAtMs.value) {
      compactStartedAtMs.value = Date.now()
      compactEndedAtMs.value = 0
    }
    compactTick.value++
    if (!elapsedTimer) {
      elapsedTimer = setInterval(() => {
        compactTick.value++
      }, 1000)
    }
  }

  function freezeElapsedTicker() {
    stopElapsedTimer()
    if (compactStartedAtMs.value && !compactEndedAtMs.value) {
      compactEndedAtMs.value = Date.now()
    }
    compactTick.value++
  }

  function resetElapsedTicker() {
    stopElapsedTimer()
    compactStartedAtMs.value = 0
    compactEndedAtMs.value = 0
    compactTick.value++
  }

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
    resetElapsedTicker()
    compactStatus.value = createEmptyCompactStatus()
  }

  function showCompactStatus(status: string, message: string, statusOptions: ShowCompactStatusOptions = {}) {
    clearDismissTimer()
    const previous = compactStatus.value
    const isBusy = status === 'started'
    // Terminal events settle the gauge in place: keep the occupancy seen at
    // start unless the caller supplies fresh values.
    const carryGauge = previous.visible && !isBusy
    compactStatus.value = {
      visible: true,
      message,
      detail: statusOptions.detail || '',
      tone: statusOptions.tone || 'info',
      isBusy,
      status,
      occupancyPercent: statusOptions.occupancyPercent !== undefined
        ? statusOptions.occupancyPercent
        : carryGauge ? previous.occupancyPercent : null,
      contextWindowLabel: statusOptions.contextWindowLabel !== undefined
        ? statusOptions.contextWindowLabel
        : carryGauge ? previous.contextWindowLabel : '',
    }
    if (isBusy) startElapsedTicker()
    else freezeElapsedTicker()
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
      const occupancy = parseContextOccupancy(payload)
      showCompactStatus('started', 'Compacting context', {
        tone: 'info',
        occupancyPercent: occupancy ? occupancy.percent : null,
        contextWindowLabel: occupancy ? occupancy.windowLabel : '',
      })
      return
    }
    if (status === 'skipped') {
      settleCompactInFlight(payload || {})
      showCompactStatus('skipped', 'Context within budget.', { tone: 'info', dismissMs: 5000 })
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
    resetElapsedTicker()
  }

  return {
    compactStatus,
    compactElapsed,
    isCompactInFlightForCurrentSession,
    setCompactInFlight,
    hideCompactStatus,
    showCompactStatus,
    showCompactionToast,
    cleanup,
  }
}
