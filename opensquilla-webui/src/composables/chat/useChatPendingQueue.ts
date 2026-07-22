import { computed, nextTick, ref, watch, type Ref } from 'vue'
import type {
  Attachment,
  ChatPendingItem,
  HiddenControlDispatchResult,
} from '@/types/chat'

const MAX_PENDING = 5

export type BusySendMode = 'queue' | 'steer'

export interface PendingQueueOwner {
  ownerRequestId?: string
}

export interface PendingQueueOwnerContext {
  sessionKey: string
  ownerRequestId: string
}

export interface UseChatPendingQueueOptions {
  sessionKey?: Ref<string>
  ownerContext?: Readonly<Ref<PendingQueueOwnerContext | null>>
  inputText: Ref<string>
  pendingAttachments: Ref<Attachment[]>
  pendingSessionIntent: Ref<string | null>
  isStreaming: Ref<boolean>
  isBlocked: () => boolean
  autoResizeTextarea: () => void
  sendCurrentInput: () => void
  resetInputHistory: () => void
  hasComposer: () => boolean
  // Drain a queued hidden-control send (e.g. meta-preflight confirmation)
  // directly through the dedicated hidden-send path instead of the composer.
  dispatchHiddenControl?: (
    providerText: string,
    displayText: string,
    clientRequestId?: string,
  ) => void | HiddenControlDispatchResult | Promise<void | HiddenControlDispatchResult>
  // Returning false for an explicit discard keeps the chip queued. This lets
  // the caller fail closed when it cannot persist the cancellation tombstone.
  onHiddenControlDispatchResult?: (result: HiddenControlDispatchResult) => void | boolean
}

export function useChatPendingQueue(options: UseChatPendingQueueOptions) {
  const pendingQueue = ref<ChatPendingItem[]>([])
  const parkedQueues = new Map<string, ChatPendingItem[]>()
  let pendingDrainTimer: ReturnType<typeof setTimeout> | null = null
  let deferredDrainRequested = false

  const canQueueMore = computed(() => pendingQueue.value.length < MAX_PENDING)

  // Busy-composer delivery mode: 'queue' holds the message until the turn
  // ends (pending queue), 'steer' sends it immediately into the active run.
  // The choice only applies while a run is active, so it snaps back to the
  // safe default whenever streaming stops.
  const busySendMode = ref<BusySendMode>('queue')
  watch(options.isStreaming, (streaming) => {
    if (!streaming) {
      busySendMode.value = 'queue'
      flushDeferredPendingDrain()
    }
  })

  function resolveOwnerRequestId(owner?: PendingQueueOwner): string | undefined {
    if (owner?.ownerRequestId) return owner.ownerRequestId
    const context = options.ownerContext?.value
    return context && context.sessionKey === options.sessionKey?.value
      ? context.ownerRequestId
      : undefined
  }

  function currentSessionKey(): string {
    return options.sessionKey?.value || ''
  }

  function enqueuePendingInput(text: string, owner?: PendingQueueOwner) {
    if (pendingQueue.value.length >= MAX_PENDING) {
      console.warn(`Pending queue full (${MAX_PENDING})`)
      return false
    }
    const ownerRequestId = resolveOwnerRequestId(owner)
    pendingQueue.value.push({
      text,
      attachments: options.pendingAttachments.value.map(a => ({ ...a })),
      intent: options.pendingSessionIntent.value,
      ...(currentSessionKey() ? { ownerSessionKey: currentSessionKey() } : {}),
      ...(ownerRequestId ? { ownerRequestId } : {}),
    })
    options.inputText.value = ''
    options.pendingAttachments.value = []
    options.pendingSessionIntent.value = null
    options.autoResizeTextarea()
    flushDeferredPendingDrain()
    return true
  }

  function enqueueRecoveredInput(text: string, owner?: PendingQueueOwner) {
    const recovered = String(text || '').trim()
    if (!recovered) return true
    if (pendingQueue.value.some(item => !item.hiddenControl && item.text === recovered)) {
      return true
    }
    if (pendingQueue.value.length >= MAX_PENDING) {
      console.warn(`Pending queue full (${MAX_PENDING})`)
      return false
    }
    const ownerRequestId = resolveOwnerRequestId(owner)
    pendingQueue.value.push({
      text: recovered,
      attachments: [],
      intent: null,
      ...(currentSessionKey() ? { ownerSessionKey: currentSessionKey() } : {}),
      ...(ownerRequestId ? { ownerRequestId } : {}),
    })
    return true
  }

  function enqueueHiddenControl(
    item: {
      text: string
      displayText: string
      clientRequestId?: string
      sessionKey?: string
    },
    owner?: PendingQueueOwner,
  ) {
    const stableRequestId = String(item.clientRequestId || '').trim()
    const hiddenControlSessionKey = item.sessionKey || currentSessionKey()
    if (
      stableRequestId
      && pendingQueue.value.some(candidate => (
        candidate.hiddenControl
        && candidate.clientRequestId === stableRequestId
        && candidate.hiddenControlSessionKey === hiddenControlSessionKey
      ))
    ) {
      return true
    }
    if (pendingQueue.value.length >= MAX_PENDING) {
      console.warn(`Pending queue full (${MAX_PENDING})`)
      return false
    }
    // A hidden-control send does NOT consume the composer draft/attachments.
    const ownerRequestId = resolveOwnerRequestId(owner)
    pendingQueue.value.push({
      text: item.text,
      attachments: [],
      intent: null,
      ...(currentSessionKey() ? { ownerSessionKey: currentSessionKey() } : {}),
      ...(ownerRequestId ? { ownerRequestId } : {}),
      hiddenControl: true,
      displayTextOverride: item.displayText,
      clientRequestId: item.clientRequestId,
      hiddenControlSessionKey,
    })
    flushDeferredPendingDrain()
    return true
  }

  function removePendingChip(index: number) {
    const item = pendingQueue.value[index]
    if (!notifyDiscardedHiddenControl(item)) return
    pendingQueue.value.splice(index, 1)
  }

  function clearPendingQueue() {
    clearPendingDrainAfterTerminalTimer()
    pendingQueue.value = pendingQueue.value.filter(item => !notifyDiscardedHiddenControl(item))
  }

  function notifyDiscardedHiddenControl(item?: ChatPendingItem): boolean {
    if (!item?.hiddenControl || !item.clientRequestId) return true
    const result = options.onHiddenControlDispatchResult?.({
      status: 'rejected',
      reason: 'discarded',
      clientRequestId: item.clientRequestId,
      sessionKey: item.hiddenControlSessionKey || '',
    })
    return result !== false
  }

  function switchPendingQueue(targetSessionKey: string) {
    clearPendingDrainAfterTerminalTimer()
    const sourceSessionKey = currentSessionKey()
    const sourceHidden = pendingQueue.value.filter(item => item.hiddenControl)
    if (sourceSessionKey && sourceHidden.length > 0) {
      const existing = parkedQueues.get(sourceSessionKey) || []
      parkedQueues.set(sourceSessionKey, [...existing, ...sourceHidden])
    }
    const parked = parkedQueues.get(targetSessionKey) || []
    parkedQueues.delete(targetSessionKey)
    // Explicit navigation keeps its historical behavior of discarding the
    // active session's ordinary queue. Machine controls remain bound to their
    // source session and are parked without emitting an explicit-discard event;
    // returning to that session resumes the same durable request identity.
    pendingQueue.value = parked
  }

  function adoptPendingQueue(targetSessionKey: string, ownerRequestId: string) {
    clearPendingDrainAfterTerminalTimer()
    const sourceSessionKey = currentSessionKey()
    const carried: ChatPendingItem[] = []
    const stayingVisible: ChatPendingItem[] = []
    const stayingHidden: ChatPendingItem[] = []
    for (const item of pendingQueue.value) {
      if (item.hiddenControl) {
        // Hidden MetaSkill controls are authorized against the exact session
        // where meta.run staged them. A response handoff may adopt ordinary
        // follow-up drafts, but must not re-parent that machine control into a
        // child session. Its durable outbox copy remains scoped to the source
        // and can be restored only if that source session becomes active again.
        stayingHidden.push(item)
        continue
      }
      if (
        ownerRequestId
        && item.ownerSessionKey === sourceSessionKey
        && item.ownerRequestId === ownerRequestId
      ) {
        carried.push({
          ...item,
          ownerSessionKey: targetSessionKey,
          ownerRequestId: undefined,
        })
      } else {
        // Keep unrelated visible drafts parked under their source session;
        // only drafts owned by the response being handed off move to the
        // accepted child session.
        stayingVisible.push(item)
      }
    }
    if (stayingVisible.length > 0 || stayingHidden.length > 0) {
      parkedQueues.set(sourceSessionKey, [
        ...(parkedQueues.get(sourceSessionKey) || []),
        ...stayingVisible,
        ...stayingHidden,
      ])
    }
    const parkedTargetItems = parkedQueues.get(targetSessionKey) || []
    parkedQueues.delete(targetSessionKey)
    pendingQueue.value = [...parkedTargetItems, ...carried]
  }

  function popPendingTail() {
    // Skip hidden-control sends: they never belong in the composer.
    let tailIndex = pendingQueue.value.length - 1
    while (tailIndex >= 0 && pendingQueue.value[tailIndex]?.hiddenControl) tailIndex--
    if (tailIndex < 0) return false
    const [tail] = pendingQueue.value.splice(tailIndex, 1)
    options.inputText.value = tail?.text || ''
    options.pendingAttachments.value = tail?.attachments || []
    options.pendingSessionIntent.value = tail?.intent || null
    options.autoResizeTextarea()
    return true
  }

  function popAllPendingIntoComposer(): boolean {
    clearPendingDrainAfterTerminalTimer()
    if (!options.hasComposer() || pendingQueue.value.length === 0) return false
    // Hidden-control sends stay queued (they bypass the composer); only the
    // visible drafts are pulled back in.
    const visible = pendingQueue.value.filter(p => !p.hiddenControl)
    const hidden = pendingQueue.value.filter(p => p.hiddenControl)
    if (visible.length === 0) return false
    const queuedTexts = visible.map(p => p.text).filter(Boolean)
    const queuedAttachments = visible.flatMap(p => p.attachments || [])
    const headIntent = visible[0]?.intent
    const current = options.inputText.value || ''
    const joined = [current, ...queuedTexts].filter(Boolean).join('\n')
    pendingQueue.value = hidden
    options.inputText.value = joined
    options.pendingAttachments.value = [...options.pendingAttachments.value, ...queuedAttachments]
    options.pendingSessionIntent.value = options.pendingSessionIntent.value || headIntent || null
    options.autoResizeTextarea()
    options.resetInputHistory()
    return true
  }

  function drainQueueHead() {
    clearPendingDrainAfterTerminalTimer()
    if (pendingQueue.value.length === 0) return
    const head = pendingQueue.value.shift()
    if (head?.hiddenControl) {
      // Hidden-control sends bypass the composer entirely.
      const providerText = head.text || ''
      const displayText = head.displayTextOverride || ''
      void nextTick(async () => {
        try {
          const result = await options.dispatchHiddenControl?.(
            providerText,
            displayText,
            head.clientRequestId,
          )
          if (result) options.onHiddenControlDispatchResult?.(result)
        } catch {
          if (!head.clientRequestId) return
          options.onHiddenControlDispatchResult?.({
            status: 'unknown',
            reason: 'response_unknown',
            clientRequestId: head.clientRequestId,
            sessionKey: head.hiddenControlSessionKey || '',
          })
        }
      })
      return
    }
    options.inputText.value = head?.text || ''
    options.pendingAttachments.value = head?.attachments || []
    options.pendingSessionIntent.value = head?.intent || null
    nextTick(() => options.sendCurrentInput())
  }

  function schedulePendingDrainAfterTerminal() {
    if (pendingQueue.value.length === 0) {
      // A terminal subscription replay can arrive while response handoff is
      // still hydrating, before the matching follow-up reaches the queue.
      // Preserve that terminal signal until the blocker releases.
      deferredDrainRequested = options.isBlocked()
      return
    }
    deferredDrainRequested = true
    armPendingDrainTimer()
  }

  function armPendingDrainTimer() {
    cancelPendingDrainTimer()
    pendingDrainTimer = setTimeout(() => {
      pendingDrainTimer = null
      if (pendingQueue.value.length === 0) {
        deferredDrainRequested = false
        return
      }
      if (options.isStreaming.value || options.isBlocked()) return
      deferredDrainRequested = false
      drainQueueHead()
    }, 50)
  }

  function flushDeferredPendingDrain() {
    if (!deferredDrainRequested || pendingQueue.value.length === 0) return
    armPendingDrainTimer()
  }

  function cancelPendingDrainTimer() {
    if (pendingDrainTimer) {
      clearTimeout(pendingDrainTimer)
      pendingDrainTimer = null
    }
  }

  function clearPendingDrainAfterTerminalTimer() {
    cancelPendingDrainTimer()
    deferredDrainRequested = false
  }

  function cleanup() {
    clearPendingDrainAfterTerminalTimer()
    parkedQueues.clear()
  }

  return {
    pendingQueue,
    canQueueMore,
    busySendMode,
    maxPending: MAX_PENDING,
    enqueuePendingInput,
    enqueueRecoveredInput,
    enqueueHiddenControl,
    removePendingChip,
    clearPendingQueue,
    switchPendingQueue,
    adoptPendingQueue,
    popPendingTail,
    popAllPendingIntoComposer,
    schedulePendingDrainAfterTerminal,
    flushDeferredPendingDrain,
    clearPendingDrainAfterTerminalTimer,
    cleanup,
  }
}
