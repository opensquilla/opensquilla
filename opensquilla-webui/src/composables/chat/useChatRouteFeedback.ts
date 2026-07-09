import { reactive } from 'vue'
import i18n from '@/i18n'
import { useToasts } from '@/composables/useToasts'
import { useRpcStore } from '@/stores/rpc'

export type RouteFeedbackRating = 'up' | 'down'

interface FeedbackSubmitResponse {
  accepted?: boolean
  recorded?: string
  reason?: string
}

// Per-decision selected state for the whole view. Keyed by decisionId (not
// message index) so history reloads and regenerates keep ratings attached to
// the routing decision they judged. Optimistic: the sidecar is last-write-wins
// server-side, so replaying a click after a failed call is always safe.
const selected = reactive(new Map<string, RouteFeedbackRating>())
const inFlight = reactive(new Set<string>())

export function useChatRouteFeedback() {
  const { pushToast } = useToasts()

  function ratingFor(decisionId: string | undefined): RouteFeedbackRating | undefined {
    return decisionId ? selected.get(decisionId) : undefined
  }

  function busy(decisionId: string | undefined): boolean {
    return !!decisionId && inFlight.has(decisionId)
  }

  /** Clicking the active thumb again revokes (neutral); clicking the other revises. */
  async function submit(decisionId: string, rating: RouteFeedbackRating): Promise<void> {
    if (inFlight.has(decisionId)) return
    const previous = selected.get(decisionId)
    const effective = previous === rating ? 'neutral' : rating

    // Optimistic flip; rolled back below if the gateway refuses.
    if (effective === 'neutral') selected.delete(decisionId)
    else selected.set(decisionId, rating)

    inFlight.add(decisionId)
    try {
      // Resolved lazily: message components mount in Pinia-free contexts
      // (share view, unit fixtures) where no rating can ever be cast.
      const rpc = useRpcStore()
      const res = await rpc.call<FeedbackSubmitResponse>('router.feedback.submit', {
        decisionId,
        rating: effective,
      })
      if (!res?.accepted) {
        rollback(decisionId, previous)
        pushToast(
          res?.reason === 'decision_not_found'
            ? i18n.global.t('chat.routeFeedback.expired')
            : i18n.global.t('chat.routeFeedback.failed'),
          { tone: 'danger' },
        )
      }
    } catch {
      rollback(decisionId, previous)
      pushToast(i18n.global.t('chat.routeFeedback.failed'), { tone: 'danger' })
    } finally {
      inFlight.delete(decisionId)
    }
  }

  function rollback(decisionId: string, previous: RouteFeedbackRating | undefined) {
    if (previous === undefined) selected.delete(decisionId)
    else selected.set(decisionId, previous)
  }

  return { ratingFor, busy, submit }
}
