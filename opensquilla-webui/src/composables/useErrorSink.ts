import { useToasts } from '@/composables/useToasts'

/**
 * Centralized, de-duplicated error reporting.
 *
 * Dual poll+subscribe surfaces and periodic pollers can raise the same failure
 * many times in quick succession; without de-duping that becomes a wall of
 * identical toasts. `reportError` collapses repeats of the same `key` (or the
 * message itself) within a short window into a single toast.
 */
const recent = new Map<string, number>()
const DEDUPE_MS = 2000

export function useErrorSink() {
  const { pushToast } = useToasts()

  function reportError(message: string, key?: string): void {
    const text = message.trim()
    if (!text) return
    const now = Date.now()
    // Opportunistically prune stale keys so the map can't grow unbounded.
    for (const [k, ts] of recent) {
      if (now - ts > DEDUPE_MS) recent.delete(k)
    }
    const dedupeKey = key || text
    const last = recent.get(dedupeKey)
    if (last !== undefined && now - last < DEDUPE_MS) return
    recent.set(dedupeKey, now)
    pushToast(text, { tone: 'danger' })
  }

  return { reportError }
}
