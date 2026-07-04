export const LOCAL_SESSIONS_DELETED_EVENT = 'opensquilla:sessions-deleted'

export interface LocalSessionsDeletedDetail {
  keys: string[]
  source?: string
}

export function normalizeSessionKeys(keys: Iterable<string>): string[] {
  return [...new Set([...keys].map(key => key.trim()).filter(Boolean))]
}

export function dispatchLocalSessionsDeleted(keys: Iterable<string>, source?: string) {
  if (typeof window === 'undefined') return
  const normalized = normalizeSessionKeys(keys)
  if (normalized.length === 0) return
  window.dispatchEvent(new CustomEvent<LocalSessionsDeletedDetail>(
    LOCAL_SESSIONS_DELETED_EVENT,
    { detail: { keys: normalized, source } },
  ))
}

export function localSessionsDeletedDetail(event: Event): LocalSessionsDeletedDetail | null {
  if (!(event instanceof CustomEvent)) return null
  const detail = event.detail as Partial<LocalSessionsDeletedDetail> | null
  if (!detail || !Array.isArray(detail.keys)) return null
  const keys = normalizeSessionKeys(detail.keys)
  return keys.length > 0 ? { keys, source: detail.source } : null
}
