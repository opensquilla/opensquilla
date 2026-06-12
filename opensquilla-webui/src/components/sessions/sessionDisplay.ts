import type { IconName } from '@/utils/icons'
import type { SessionItem } from '@/composables/useSessions'

export interface SessionStatusBadge {
  label: string
  cls: string
}

export function sessionSurfaceIcon(item: SessionItem): IconName {
  if (item.sessionKind === 'cron') return 'cron'
  if (item.sessionKind === 'channel') return 'channels'
  if (item.sessionKind === 'task' || item.surface === 'subagent') return 'agents'
  if (item.sessionKind === 'chat') return 'chat'
  return 'sessions'
}

export function sessionStatusBadge(item: SessionItem, needsInput = false): SessionStatusBadge | null {
  if (needsInput) {
    return { label: 'Needs input', cls: 'is-needs-input' }
  }
  const map: Record<string, SessionStatusBadge> = {
    running: { label: 'Running', cls: 'is-running' },
    queued: { label: 'Queued', cls: 'is-queued' },
    failed: { label: 'Failed', cls: 'is-failed' },
    timeout: { label: 'Timed out', cls: 'is-failed' },
    interrupted: { label: 'Interrupted', cls: 'is-queued' },
    cancelled: { label: 'Cancelled', cls: 'is-off' },
  }
  return map[item.runStatus] || null
}

/**
 * Shared relative-time formatter for every session ledger row (and any other
 * surface that lists sessions). Renders "just now" / "Ns ago" / "Nm ago" /
 * "Nh ago" / "Nd ago" up to ~7 days, then falls back to an absolute date.
 */
export function formatRelativeTime(timestamp: number | null | undefined): string {
  if (!timestamp) return '—'
  const d = new Date(timestamp)
  if (isNaN(d.getTime())) return '—'

  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString()
}

/** Back-compat alias; prefer {@link formatRelativeTime} for new call sites. */
export const sessionRelTime = formatRelativeTime

/**
 * Ledger title for a subagent row: "↳ Subagent · {parent title}" when the
 * parent title is known, otherwise a plain "↳ Subagent" so we never surface a
 * raw key. The arrow + label conveys lineage without rendering UUIDs.
 */
export function subagentRowTitle(parentTitle: string | null | undefined): string {
  const parent = (parentTitle || '').trim()
  return parent ? `↳ Subagent · ${parent}` : '↳ Subagent'
}
