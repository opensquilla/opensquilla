import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useChatComposerShortcuts } from './useChatComposerShortcuts'
import type { ChatMessage, ChatPendingItem } from '@/types/chat'

// The composable gates the Alt+Arrow queue chords on caret position via
// `e.target instanceof HTMLTextAreaElement`. The unit env is `node` (no DOM), so
// register a minimal stand-in as the global the composable checks against.
class FakeTextArea {
  value = ''
  selectionStart = 0
  selectionEnd = 0
}

beforeEach(() => {
  ;(globalThis as unknown as { HTMLTextAreaElement: unknown }).HTMLTextAreaElement = FakeTextArea
})
afterEach(() => {
  delete (globalThis as unknown as { HTMLTextAreaElement?: unknown }).HTMLTextAreaElement
})

function field(value: string, caret: 'start' | 'end' | 'middle'): FakeTextArea {
  const ta = new FakeTextArea()
  ta.value = value
  const pos = caret === 'start' ? 0 : caret === 'end' ? value.length : Math.floor(value.length / 2)
  ta.selectionStart = pos
  ta.selectionEnd = pos
  return ta
}

function harness(over: { inputText?: string; pendingQueue?: ChatPendingItem[]; canQueueMore?: boolean } = {}) {
  const spies = {
    popPendingTail: vi.fn(() => true),
    enqueuePendingInput: vi.fn(() => true),
    sendCurrentInput: vi.fn(),
    autoResizeTextarea: vi.fn(),
    handleSlashInput: vi.fn(),
    closeSlashMenu: vi.fn(),
    selectSlashCmd: vi.fn(),
  }
  const api = useChatComposerShortcuts({
    inputText: ref(over.inputText ?? ''),
    composing: ref(false),
    messages: ref<ChatMessage[]>([]),
    pendingQueue: ref<ChatPendingItem[]>(over.pendingQueue ?? []),
    canQueueMore: ref(over.canQueueMore ?? true),
    slashOpen: ref(false),
    slashIdx: ref(0),
    filteredSlashCmds: ref([]),
    isStreaming: ref(false),
    ...spies,
  })
  return { api, spies }
}

function keydown(opts: {
  key: string
  altKey?: boolean
  shiftKey?: boolean
  isComposing?: boolean
  keyCode?: number
  target: unknown
}): KeyboardEvent {
  return {
    key: opts.key,
    altKey: opts.altKey ?? false,
    shiftKey: opts.shiftKey ?? false,
    isComposing: opts.isComposing ?? false,
    keyCode: opts.keyCode ?? 0,
    target: opts.target,
    preventDefault: vi.fn(),
  } as unknown as KeyboardEvent
}

const QUEUE = [{ id: 'q1', text: 'queued' }] as unknown as ChatPendingItem[]

describe('useChatComposerShortcuts', () => {
  describe('IME composition guard', () => {
    it('does not send on Enter while the IME is composing (isComposing)', () => {
      const { api, spies } = harness({ inputText: '你好' })
      api.onTextareaKeydown(keydown({ key: 'Enter', isComposing: true, target: field('你好', 'end') }))
      expect(spies.sendCurrentInput).not.toHaveBeenCalled()
    })

    it('does not send on Enter during legacy keyCode 229 composition', () => {
      const { api, spies } = harness({ inputText: '你好' })
      api.onTextareaKeydown(keydown({ key: 'Enter', keyCode: 229, target: field('你好', 'end') }))
      expect(spies.sendCurrentInput).not.toHaveBeenCalled()
    })

    it('sends on a plain Enter when not composing', () => {
      const { api, spies } = harness({ inputText: 'hi' })
      const e = keydown({ key: 'Enter', target: field('hi', 'end') })
      api.onTextareaKeydown(e)
      expect(spies.sendCurrentInput).toHaveBeenCalledOnce()
      expect(e.preventDefault).toHaveBeenCalled()
    })
  })

  describe('Alt+Arrow queue chords are caret-gated (preserve macOS paragraph nav)', () => {
    it('enqueues on Alt+ArrowDown only when the caret is at the end', () => {
      const { api, spies } = harness({ inputText: 'line1\nline2', canQueueMore: true })

      const atEnd = keydown({ key: 'ArrowDown', altKey: true, target: field('line1\nline2', 'end') })
      api.onTextareaKeydown(atEnd)
      expect(spies.enqueuePendingInput).toHaveBeenCalledWith('line1\nline2')
      expect(atEnd.preventDefault).toHaveBeenCalled()

      spies.enqueuePendingInput.mockClear()
      const midDraft = keydown({ key: 'ArrowDown', altKey: true, target: field('line1\nline2', 'middle') })
      api.onTextareaKeydown(midDraft)
      expect(spies.enqueuePendingInput).not.toHaveBeenCalled()
      expect(midDraft.preventDefault).not.toHaveBeenCalled() // native Option+ArrowDown paragraph move survives
    })

    it('pops the queue on Alt+ArrowUp only when the caret is at the start', () => {
      const { api, spies } = harness({ pendingQueue: QUEUE })

      const atStart = keydown({ key: 'ArrowUp', altKey: true, target: field('', 'start') })
      api.onTextareaKeydown(atStart)
      expect(spies.popPendingTail).toHaveBeenCalledOnce()
      expect(atStart.preventDefault).toHaveBeenCalled()

      spies.popPendingTail.mockClear()
      const midDraft = keydown({ key: 'ArrowUp', altKey: true, target: field('line1\nline2', 'middle') })
      api.onTextareaKeydown(midDraft)
      expect(spies.popPendingTail).not.toHaveBeenCalled()
      expect(midDraft.preventDefault).not.toHaveBeenCalled() // native Option+ArrowUp paragraph move survives
    })
  })
})
