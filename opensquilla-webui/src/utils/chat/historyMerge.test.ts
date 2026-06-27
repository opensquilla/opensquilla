import { describe, it, expect } from 'vitest'
import { mergeLiveOnlyFields, reconcileHistoryMessages } from './historyMerge'
import type { ChatMessage, ChatReasoning } from '@/types/chat'

function msg(overrides: Partial<ChatMessage>): ChatMessage {
  return { role: 'assistant', text: '', ts: null, ...overrides } as ChatMessage
}
const reasoning = (seconds: number): ChatReasoning => ({ text: '', seconds })

describe('mergeLiveOnlyFields', () => {
  it('keeps live reasoning seconds when the server snapshot measured none', () => {
    const merged = mergeLiveOnlyFields(msg({ reasoning: reasoning(8) }), msg({ reasoning: undefined }))
    expect(merged.reasoning?.seconds).toBe(8)
  })

  it('lets the server win when it measured its own seconds', () => {
    const merged = mergeLiveOnlyFields(msg({ reasoning: reasoning(8) }), msg({ reasoning: reasoning(12) }))
    expect(merged.reasoning?.seconds).toBe(12)
  })

  it('keeps routerSettled sticky once it has settled', () => {
    expect(mergeLiveOnlyFields(msg({ routerSettled: true }), msg({ routerSettled: undefined })).routerSettled).toBe(true)
  })

  it('keeps the local interrupted flag until the server persists its own', () => {
    expect(mergeLiveOnlyFields(msg({ interrupted: true }), msg({ interrupted: undefined })).interrupted).toBe(true)
    // server defines it (even as false) → the server value wins
    expect(mergeLiveOnlyFields(msg({ interrupted: true }), msg({ interrupted: false })).interrupted).toBe(false)
  })

  it('preserves prev reasoning whenever the server row measured none, independent of prev.role', () => {
    // The role check only governs whether the SERVER's measured seconds may
    // suppress the graft; it does not gate the graft itself on prev being an
    // assistant. Non-assistant rows never carry reasoning in practice, so this
    // branch is unreachable — but the suite locks the contract the code actually
    // has, not the one a reader might assume. (Asymmetry surfaced by this test;
    // behavior left unchanged — see the implementation note.)
    const merged = mergeLiveOnlyFields(
      msg({ role: 'user', reasoning: reasoning(8) }),
      msg({ role: 'user', reasoning: undefined }),
    )
    expect(merged.reasoning?.seconds).toBe(8)
  })
})

describe('reconcileHistoryMessages', () => {
  it('returns the incoming window verbatim when there is no prior state', () => {
    const incoming = [msg({ messageId: 'a' })]
    expect(reconcileHistoryMessages([], incoming)).toBe(incoming)
  })

  it('is server-authoritative: ordering and membership follow the incoming window', () => {
    const prev = [msg({ messageId: 'a' }), msg({ messageId: 'b' }), msg({ messageId: 'c' })]
    const incoming = [msg({ messageId: 'c' }), msg({ messageId: 'a' })] // reordered, b dropped
    expect(reconcileHistoryMessages(prev, incoming).map(m => m.messageId)).toEqual(['c', 'a'])
  })

  it('rides live-only fields along only on a real messageId match', () => {
    const prev = [msg({ messageId: 'm1', reasoning: reasoning(9), routerSettled: true })]
    const out = reconcileHistoryMessages(prev, [msg({ messageId: 'm1', reasoning: undefined })])
    expect(out[0].reasoning?.seconds).toBe(9)
    expect(out[0].routerSettled).toBe(true)
  })

  it('takes server rows verbatim when they carry no messageId', () => {
    const prev = [msg({ messageId: 'm1', reasoning: reasoning(9) })]
    const out = reconcileHistoryMessages(prev, [msg({ messageId: undefined, reasoning: undefined })])
    expect(out[0].reasoning).toBeUndefined()
  })
})
