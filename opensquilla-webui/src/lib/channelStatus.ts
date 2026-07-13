// Single source of truth for user-visible channel state. Both surfaces
// (Settings runtime list and the /channels monitor page) render channel state
// through statusPresentation(), so the vocabulary cannot drift between them.
//
// The gateway emits exactly six wire statuses (rpc_channels.py `_status_for`):
// connected | stopped | disabled | dead | exhausted | restarting. Anything
// else falls through to the translated `unknown` presentation — a raw enum
// must never reach the user unlabeled.

export type ChannelStatusTone = 'ok' | 'info' | 'muted' | 'danger'

export type ChannelStatusKey =
  | 'connected'
  | 'pendingRestart'
  | 'notRunning'
  | 'disabled'
  | 'restarting'
  | 'failed'
  | 'exhausted'
  | 'unknown'

export interface ChannelStatusInput {
  status?: string | null
  enabled?: boolean | null
  connected?: boolean | null
  /** Client-side overlay: a saved change for this channel awaits a gateway restart. */
  pendingRestart?: boolean | null
  /** `diagnostics.last_error.error_class` when present. */
  errorClass?: string | null
}

export interface ChannelStatusPresentation {
  key: ChannelStatusKey
  labelKey: string
  tone: ChannelStatusTone
  hintKey?: string
  causeKey?: string
  /** Unrecognized wire value, interpolated into the `unknown` label. */
  raw?: string
}

/** Severity order shared by row sorting and the summary chips. */
export const CHANNEL_STATUS_ORDER: readonly ChannelStatusKey[] = [
  'failed',
  'exhausted',
  'restarting',
  'pendingRestart',
  'connected',
  'notRunning',
  'disabled',
  'unknown',
]

/** Tone per presentation key — used where a chip is built from a key alone. */
export const CHANNEL_STATUS_TONES: Record<ChannelStatusKey, ChannelStatusTone> = {
  connected: 'ok',
  pendingRestart: 'info',
  notRunning: 'muted',
  disabled: 'muted',
  restarting: 'info',
  failed: 'danger',
  exhausted: 'danger',
  unknown: 'muted',
}

// The delivery-journal error taxonomy (channels/contract.py). Unknown classes
// simply get no cause line.
const ERROR_CLASSES = new Set([
  'auth_invalid',
  'payload_rejected',
  'target_missing',
  'contract_violation',
  'transport_transient',
  'rate_limited',
  'channel_degraded',
])

function causeKeyFor(errorClass?: string | null): string | undefined {
  return errorClass && ERROR_CLASSES.has(errorClass)
    ? `channelStatus.cause.${errorClass}`
    : undefined
}

export function statusPresentation(input: ChannelStatusInput): ChannelStatusPresentation {
  const causeKey = causeKeyFor(input.errorClass)
  if (input.pendingRestart) {
    return {
      key: 'pendingRestart',
      labelKey: 'channelStatus.pendingRestart',
      tone: 'info',
      hintKey: 'channelStatus.hint.pendingRestart',
    }
  }
  if (input.enabled === false || input.status === 'disabled') {
    // Deliberately switched off by the operator — never styled as a problem.
    return { key: 'disabled', labelKey: 'channelStatus.disabled', tone: 'muted' }
  }
  switch (input.status) {
    case 'connected':
      return { key: 'connected', labelKey: 'channelStatus.connected', tone: 'ok' }
    case 'restarting':
      return {
        key: 'restarting',
        labelKey: 'channelStatus.restarting',
        tone: 'info',
        hintKey: 'channelStatus.hint.restarting',
        causeKey,
      }
    case 'dead':
      return {
        key: 'failed',
        labelKey: 'channelStatus.failed',
        tone: 'danger',
        hintKey: 'channelStatus.hint.failed',
        causeKey,
      }
    case 'exhausted':
      return {
        key: 'exhausted',
        labelKey: 'channelStatus.exhausted',
        tone: 'danger',
        hintKey: 'channelStatus.hint.exhausted',
        causeKey,
      }
    case 'stopped':
      return {
        key: 'notRunning',
        labelKey: 'channelStatus.notRunning',
        tone: 'muted',
        hintKey: 'channelStatus.hint.notRunning',
      }
  }
  return {
    key: 'unknown',
    labelKey: 'channelStatus.unknown',
    tone: 'muted',
    raw: String(input.status ?? ''),
  }
}

/** Pull `last_error.error_class` out of a channel's diagnostics payload. */
export function lastErrorClass(diagnostics: unknown): string | undefined {
  if (!diagnostics || typeof diagnostics !== 'object') return undefined
  const lastError = (diagnostics as Record<string, unknown>).last_error
  if (!lastError || typeof lastError !== 'object') return undefined
  const errorClass = (lastError as Record<string, unknown>).error_class
  return typeof errorClass === 'string' && errorClass ? errorClass : undefined
}

/**
 * Whether the gateway process has actually loaded this channel's adapter.
 * `stopped` with no capability profile means the entry exists only in config —
 * restarting it can only fail until the gateway itself restarts.
 */
export function adapterLoaded(row: {
  status?: string | null
  capability_profile?: unknown
}): boolean {
  if (row.capability_profile != null) return true
  const status = String(row.status ?? '')
  return status === 'connected' || status === 'restarting' || status === 'dead' || status === 'exhausted'
}
