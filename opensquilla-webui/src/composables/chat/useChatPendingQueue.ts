import { computed, nextTick, ref, watch, type Ref } from 'vue'
import type { Attachment, ChatPendingItem } from '@/types/chat'

const MAX_PENDING = 5

export type BusySendMode = 'queue' | 'steer'

export interface UseChatPendingQueueOptions {
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
  dispatchHiddenControl?: (providerText: string, displayText: string) => void
}

export function useChatPendingQueue(options: UseChatPendingQueueOptions) {
  const pendingQueue = ref<ChatPendingItem[]>([])
  let pendingDrainTimer: ReturnType<typeof setTimeout> | null = null

  const canQueueMore = computed(() => pendingQueue.value.length < MAX_PENDING)

  // Busy-composer delivery mode: 'queue' holds the message until the turn
  // ends (pending queue), 'steer' sends it immediately into the active run.
  // The choice only applies while a run is active, so it snaps back to the
  // safe default whenever streaming stops.
  const busySendMode = ref<BusySendMode>('queue')
  watch(options.isStreaming, (streaming) => {
    if (!streaming) busySendMode.value = 'queue'
  })

  function enqueuePendingInput(text: string) {
    if (pendingQueue.value.length >= MAX_PENDING) {
      console.warn(`Pending queue full (${MAX_PENDING})`)
      return false
    }
    pendingQueue.value.push({
      text,
      attachments: options.pendingAttachments.value.map(a => ({ ...a })),
      intent: options.pendingSessionIntent.value,
    })
    options.inputText.value = ''
    options.pendingAttachments.value = []
    options.pendingSessionIntent.value = null
    options.autoResizeTextarea()
    return true
  }

  function enqueueHiddenControl(item: { text: string; displayText: string }) {
    if (pendingQueue.value.length >= MAX_PENDING) {
      console.warn(`Pending queue full (${MAX_PENDING})`)
      return false
    }
    // A hidden-control send does NOT consume the composer draft/attachments.
    pendingQueue.value.push({
      text: item.text,
      attachments: [],
      intent: null,
      hiddenControl: true,
      displayTextOverride: item.displayText,
    })
    return true
  }

  function removePendingChip(index: number) {
    pendingQueue.value.splice(index, 1)
  }

  function clearPendingQueue() {
    clearPendingDrainAfterTerminalTimer()
    pendingQueue.value = []
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
      nextTick(() => options.dispatchHiddenControl?.(providerText, displayText))
      return
    }
    options.inputText.value = head?.text || ''
    options.pendingAttachments.value = head?.attachments || []
    options.pendingSessionIntent.value = head?.intent || null
    nextTick(() => options.sendCurrentInput())
  }

  function schedulePendingDrainAfterTerminal() {
    if (pendingQueue.value.length === 0) return
    clearPendingDrainAfterTerminalTimer()
    pendingDrainTimer = setTimeout(() => {
      pendingDrainTimer = null
      if (options.isStreaming.value || options.isBlocked() || pendingQueue.value.length === 0) return
      drainQueueHead()
    }, 50)
  }

  function clearPendingDrainAfterTerminalTimer() {
    if (pendingDrainTimer) {
      clearTimeout(pendingDrainTimer)
      pendingDrainTimer = null
    }
  }

  function cleanup() {
    clearPendingDrainAfterTerminalTimer()
  }

  return {
    pendingQueue,
    canQueueMore,
    busySendMode,
    maxPending: MAX_PENDING,
    enqueuePendingInput,
    enqueueHiddenControl,
    removePendingChip,
    clearPendingQueue,
    popPendingTail,
    popAllPendingIntoComposer,
    schedulePendingDrainAfterTerminal,
    clearPendingDrainAfterTerminalTimer,
    cleanup,
  }
}
