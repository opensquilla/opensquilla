import { ref, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatPendingItem,
} from '@/types/chat'
import type { ChatSlashCommand } from '@/composables/chat/useChatSlashCommands'

export interface UseChatComposerShortcutsOptions {
  inputText: Ref<string>
  composing: Ref<boolean>
  messages: Ref<ChatMessage[]>
  pendingQueue: Ref<ChatPendingItem[]>
  canQueueMore: Ref<boolean>
  slashOpen: Ref<boolean>
  slashIdx: Ref<number>
  filteredSlashCmds: Ref<ChatSlashCommand[]>
  isStreaming: Ref<boolean>
  autoResizeTextarea: () => void
  handleSlashInput: () => void
  closeSlashMenu: () => void
  selectSlashCmd: (cmd: ChatSlashCommand) => void
  popPendingTail: () => boolean
  enqueuePendingInput: (text: string) => boolean
  sendCurrentInput: () => void
}

export function useChatComposerShortcuts(options: UseChatComposerShortcutsOptions) {
  const inputHistoryIdx = ref<number | null>(null)
  const inputHistoryDraft = ref('')

  function resetInputHistory() {
    inputHistoryIdx.value = null
    inputHistoryDraft.value = ''
  }

  function onTextareaInput() {
    options.autoResizeTextarea()
    options.handleSlashInput()
  }

  function onTextareaKeydown(e: KeyboardEvent) {
    if (options.composing.value || e.isComposing || e.keyCode === 229) return

    // Caret position gates the Alt+Arrow queue chords below: claim them only at
    // the text boundaries so macOS' native Option+ArrowUp/Down ("move by
    // paragraph") still works mid-draft. The natural flow is unaffected — the
    // caret sits at the end after typing (push) and at the start of an empty or
    // short draft (pop) — and on Win/Linux, where Alt+Arrow has no native
    // binding, those boundaries are reached in the same common cases.
    const field = e.target instanceof HTMLTextAreaElement ? e.target : null
    const caretAtStart = !!field && field.selectionStart === 0 && field.selectionEnd === 0
    const caretAtEnd = !!field
      && field.selectionStart === field.value.length
      && field.selectionEnd === field.value.length

    if (options.slashOpen.value) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        options.slashIdx.value = Math.min(options.slashIdx.value + 1, options.filteredSlashCmds.value.length - 1)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        options.slashIdx.value = Math.max(options.slashIdx.value - 1, 0)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        if (options.filteredSlashCmds.value.length > 0) {
          e.preventDefault()
          options.selectSlashCmd(options.filteredSlashCmds.value[options.slashIdx.value])
          return
        }
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        options.closeSlashMenu()
        return
      }
    }

    if (e.key === 'Escape' && !options.isStreaming.value && options.pendingQueue.value.length === 0 && options.inputText.value) {
      e.preventDefault()
      options.inputText.value = ''
      options.autoResizeTextarea()
      return
    }

    if (e.key === 'ArrowUp' && e.altKey && caretAtStart && options.pendingQueue.value.length > 0) {
      e.preventDefault()
      options.popPendingTail()
      return
    }

    if (e.key === 'ArrowDown' && e.altKey && caretAtEnd && options.inputText.value && options.canQueueMore.value) {
      e.preventDefault()
      options.enqueuePendingInput(options.inputText.value)
      return
    }

    if (e.key === 'ArrowUp' && !e.altKey && !e.shiftKey && (!options.inputText.value || inputHistoryIdx.value !== null)) {
      if (cycleHistory(-1)) { e.preventDefault(); return }
    }
    if (e.key === 'ArrowDown' && !e.altKey && !e.shiftKey && inputHistoryIdx.value !== null) {
      if (cycleHistory(1)) { e.preventDefault(); return }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      options.sendCurrentInput()
    }
  }

  function cycleHistory(dir: number): boolean {
    const history = options.messages.value
      .filter(message => message.role === 'user' && typeof message.text === 'string')
      .map(message => message.text)
    if (history.length === 0) return false

    if (dir < 0) {
      if (inputHistoryIdx.value === null) {
        inputHistoryDraft.value = options.inputText.value || ''
        inputHistoryIdx.value = history.length - 1
      } else {
        inputHistoryIdx.value = Math.max(0, inputHistoryIdx.value - 1)
      }
      options.inputText.value = history[inputHistoryIdx.value]
      options.autoResizeTextarea()
      return true
    }

    if (inputHistoryIdx.value === null) return false
    const next = inputHistoryIdx.value + 1
    if (next >= history.length) {
      inputHistoryIdx.value = null
      options.inputText.value = inputHistoryDraft.value
      inputHistoryDraft.value = ''
    } else {
      inputHistoryIdx.value = next
      options.inputText.value = history[next]
    }
    options.autoResizeTextarea()
    return true
  }

  return {
    onTextareaInput,
    onTextareaKeydown,
    resetInputHistory,
  }
}
