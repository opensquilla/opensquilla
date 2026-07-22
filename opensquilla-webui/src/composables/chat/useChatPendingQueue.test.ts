import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useChatPendingQueue } from './useChatPendingQueue'
import type { Attachment } from '@/types/chat'

describe('useChatPendingQueue hidden controls', () => {
  it('preserves the stable ingress id when draining a hidden control', async () => {
    const dispatchHiddenControl = vi.fn(async () => ({
      status: 'accepted' as const,
      reason: 'accepted' as const,
      clientRequestId: 'provider-handoff-request-3',
      sessionKey: 'agent:main:webchat:test',
    }))
    const onHiddenControlDispatchResult = vi.fn()
    const queue = useChatPendingQueue({
      inputText: ref('draft stays here'),
      pendingAttachments: ref<Attachment[]>([]),
      pendingSessionIntent: ref(null),
      isStreaming: ref(false),
      isBlocked: () => false,
      autoResizeTextarea: vi.fn(),
      sendCurrentInput: vi.fn(),
      resetInputHistory: vi.fn(),
      hasComposer: () => true,
      dispatchHiddenControl,
      onHiddenControlDispatchResult,
    })

    expect(queue.enqueueHiddenControl({
      text: '/meta meta-short-drama -- original request',
      displayText: '/meta meta-short-drama -- original request',
      clientRequestId: 'provider-handoff-request-3',
      sessionKey: 'agent:main:webchat:test',
    })).toBe(true)

    queue.schedulePendingDrainAfterTerminal()
    await new Promise(resolve => setTimeout(resolve, 60))
    await nextTick()

    expect(dispatchHiddenControl).toHaveBeenCalledWith(
      '/meta meta-short-drama -- original request',
      '/meta meta-short-drama -- original request',
      'provider-handoff-request-3',
    )
    expect(onHiddenControlDispatchResult).toHaveBeenCalledWith({
      status: 'accepted',
      reason: 'accepted',
      clientRequestId: 'provider-handoff-request-3',
      sessionKey: 'agent:main:webchat:test',
    })
    queue.cleanup()
  })

  it('deduplicates one durable hidden control before applying queue capacity', () => {
    const queue = useChatPendingQueue({
      inputText: ref(''),
      pendingAttachments: ref<Attachment[]>([]),
      pendingSessionIntent: ref(null),
      isStreaming: ref(true),
      isBlocked: () => false,
      autoResizeTextarea: vi.fn(),
      sendCurrentInput: vi.fn(),
      resetInputHistory: vi.fn(),
      hasComposer: () => true,
    })
    const durable = {
      text: '/meta test',
      displayText: '/meta test',
      clientRequestId: 'same-request',
      sessionKey: 'agent:main:webchat:test',
    }

    expect(queue.enqueueHiddenControl(durable)).toBe(true)
    expect(queue.enqueueHiddenControl(durable)).toBe(true)
    expect(queue.pendingQueue.value).toHaveLength(1)
    for (let index = 0; index < 4; index += 1) {
      expect(queue.enqueueHiddenControl({
        ...durable,
        clientRequestId: `request-${index}`,
      })).toBe(true)
    }
    expect(queue.enqueueHiddenControl({
      ...durable,
      clientRequestId: 'queue-full-request',
    })).toBe(false)
    expect(queue.pendingQueue.value).toHaveLength(queue.maxPending)
    queue.cleanup()
  })

  it('reports discarded durable controls without losing their identity', () => {
    const onHiddenControlDispatchResult = vi.fn()
    const queue = useChatPendingQueue({
      inputText: ref(''),
      pendingAttachments: ref<Attachment[]>([]),
      pendingSessionIntent: ref(null),
      isStreaming: ref(true),
      isBlocked: () => false,
      autoResizeTextarea: vi.fn(),
      sendCurrentInput: vi.fn(),
      resetInputHistory: vi.fn(),
      hasComposer: () => true,
      onHiddenControlDispatchResult,
    })
    queue.enqueueHiddenControl({
      text: '/meta test',
      displayText: '/meta test',
      clientRequestId: 'discarded-request',
      sessionKey: 'agent:main:webchat:test',
    })

    queue.clearPendingQueue()

    expect(onHiddenControlDispatchResult).toHaveBeenCalledWith({
      status: 'rejected',
      reason: 'discarded',
      clientRequestId: 'discarded-request',
      sessionKey: 'agent:main:webchat:test',
    })
    queue.cleanup()
  })

  it('turns an unexpected drain failure into a recoverable unknown result', async () => {
    const onHiddenControlDispatchResult = vi.fn()
    const queue = useChatPendingQueue({
      inputText: ref(''),
      pendingAttachments: ref<Attachment[]>([]),
      pendingSessionIntent: ref(null),
      isStreaming: ref(false),
      isBlocked: () => false,
      autoResizeTextarea: vi.fn(),
      sendCurrentInput: vi.fn(),
      resetInputHistory: vi.fn(),
      hasComposer: () => true,
      dispatchHiddenControl: vi.fn(async () => { throw new Error('unexpected') }),
      onHiddenControlDispatchResult,
    })
    queue.enqueueHiddenControl({
      text: '/meta test',
      displayText: '/meta test',
      clientRequestId: 'unknown-request',
      sessionKey: 'agent:main:webchat:test',
    })

    queue.schedulePendingDrainAfterTerminal()
    await new Promise(resolve => setTimeout(resolve, 60))
    await nextTick()

    expect(onHiddenControlDispatchResult).toHaveBeenCalledWith({
      status: 'unknown',
      reason: 'response_unknown',
      clientRequestId: 'unknown-request',
      sessionKey: 'agent:main:webchat:test',
    })
    queue.cleanup()
  })
})
