import { describe, it, expect } from 'vitest'
import {
  mergeLiveOnlyFields,
  reconcileHistoryMessages,
  reconcileHistoryWindow,
  reconcileRunningHistoryMessages,
} from './historyMerge'
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

describe('reconcileHistoryWindow', () => {
  it('keeps canonical pages older than the refreshed server window', () => {
    const previous = Array.from({ length: 250 }, (_, index) => msg({
      messageId: `m-${index}`,
      text: `previous ${index}`,
      restoredFromHistory: true,
    }))
    const latestWindow = Array.from({ length: 200 }, (_, index) => msg({
      messageId: `m-${index + 50}`,
      text: `server ${index + 50}`,
      restoredFromHistory: true,
    }))

    const merged = reconcileHistoryWindow(previous, latestWindow)

    expect(merged).toHaveLength(250)
    expect(merged[0].messageId).toBe('m-0')
    expect(merged[49].messageId).toBe('m-49')
    expect(merged[50].text).toBe('server 50')
    expect(merged[249].messageId).toBe('m-249')
  })

  it('does not concatenate canonical rows when the refreshed window has no overlap', () => {
    const previous = [
      msg({ messageId: 'old', restoredFromHistory: true }),
      msg({ role: 'user', text: 'optimistic', restoredFromHistory: false }),
    ]
    const incoming = [msg({ messageId: 'new', restoredFromHistory: true })]

    expect(reconcileHistoryWindow(previous, incoming).map(message => message.messageId)).toEqual(['new'])
  })
})

describe('reconcileRunningHistoryMessages', () => {
  it('preserves the live tail after the last user when a running history snapshot is colder', () => {
    const prev = [
      msg({ role: 'user', text: 'build it', messageId: 'u1' }),
      msg({
        role: 'router',
        text: '',
        routerDecision: { source: 'llm_ensemble', model: 'z-ai/glm-5.2', tier: 'c1' },
        ensemble: {
          profile: 'llm_ensemble',
          modelCount: 1,
          totalCandidates: 1,
          requestCount: 1,
          fallbackUsed: false,
          fallbackReason: '',
          costUsd: 0,
          savedUsd: 0,
          savedPct: 0,
          models: [{
            role: 'proposer_1',
            label: 'proposer_1',
            provider: 'openrouter',
            model: 'z-ai/glm-5.2',
            modelShort: 'glm-5.2',
            input: 0,
            output: 0,
            costUsd: 0,
            status: 'running',
          }],
        },
      }),
      msg({ role: 'assistant', text: 'Writing a file', tool_calls: [{ id: 't1', name: 'write_file' }] as any }),
    ]
    const incoming = [msg({ role: 'user', text: 'build it', messageId: 'u1', restoredFromHistory: true })]

    const out = reconcileRunningHistoryMessages(prev, incoming)

    expect(out).toHaveLength(3)
    expect(out[0].messageId).toBe('u1')
    expect(out[1].role).toBe('router')
    expect(out[1].ensemble?.models[0]?.model).toBe('z-ai/glm-5.2')
    expect(out[2].role).toBe('assistant')
    expect(out[2].tool_calls?.[0]?.name).toBe('write_file')
  })

  it('does not duplicate live rows that the server snapshot already contains by message id', () => {
    const prev = [
      msg({ role: 'user', text: 'build it', messageId: 'u1' }),
      msg({ role: 'assistant', text: 'partial', messageId: 'a1', routerSettled: true }),
    ]
    const incoming = [
      msg({ role: 'user', text: 'build it', messageId: 'u1', restoredFromHistory: true }),
      msg({ role: 'assistant', text: 'partial', messageId: 'a1', restoredFromHistory: true }),
    ]

    const out = reconcileRunningHistoryMessages(prev, incoming)

    expect(out.map(message => message.messageId)).toEqual(['u1', 'a1'])
    expect(out[1].routerSettled).toBe(true)
  })
})
