import { computed, nextTick, ref, type Ref } from 'vue'
import type { Attachment, ChatPendingItem } from '@/types/chat'

const MAX_PENDING = 5

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
}

export function useChatPendingQueue(options: UseChatPendingQueueOptions) {
  const pendingQueue = ref<ChatPendingItem[]>([])
  let pendingDrainTimer: ReturnType<typeof setTimeout> | null = null

  const canQueueMore = computed(() => pendingQueue.value.length < MAX_PENDING)

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
    console.info(`Queued (${pendingQueue.value.length}/${MAX_PENDING})`)
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
    if (pendingQueue.value.length === 0) return false
    const tail = pendingQueue.value.pop()
    options.inputText.value = tail?.text || ''
    options.pendingAttachments.value = tail?.attachments || []
    options.pendingSessionIntent.value = tail?.intent || null
    options.autoResizeTextarea()
    return true
  }

  function popAllPendingIntoComposer(): boolean {
    clearPendingDrainAfterTerminalTimer()
    if (!options.hasComposer() || pendingQueue.value.length === 0) return false
    const queuedTexts = pendingQueue.value.map(p => p.text).filter(Boolean)
    const queuedAttachments = pendingQueue.value.flatMap(p => p.attachments || [])
    const headIntent = pendingQueue.value[0]?.intent
    const current = options.inputText.value || ''
    const joined = [current, ...queuedTexts].filter(Boolean).join('\n')
    pendingQueue.value = []
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
    maxPending: MAX_PENDING,
    enqueuePendingInput,
    removePendingChip,
    clearPendingQueue,
    popPendingTail,
    popAllPendingIntoComposer,
    schedulePendingDrainAfterTerminal,
    clearPendingDrainAfterTerminalTimer,
    cleanup,
  }
}
