import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { useChatSend, type UseChatSendOptions } from './useChatSend'
import type { FoldLiveTurnMode } from './useChatTurnLog'
import type { Attachment, ChatMessage } from '@/types/chat'
import type { BusySendMode } from '@/composables/chat/useChatPendingQueue'

const pushToast = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ pushToast }),
}))

function makeOptions(overrides: Partial<UseChatSendOptions> = {}) {
  const rpc = {
    call: vi.fn().mockResolvedValue({ sessionKey: 'agent:main:webchat:test' }),
  }
  const stream: UseChatSendOptions['stream'] = {
    isStreaming: ref(false),
    streamBubble: ref(false),
    streamHasVisibleOutput: ref(false),
    startStreaming: vi.fn(),
    endStreaming: vi.fn(),
    appendDelta: vi.fn(),
    scheduleRender: vi.fn(),
    appendToolCall: vi.fn(),
    appendToolDelta: vi.fn(),
    appendToolResult: vi.fn(),
    appendArtifact: vi.fn(),
    reconcileFinalText: vi.fn(),
    resetStreamIdleTimer: vi.fn(),
    clearStreamIdleTimer: vi.fn(),
    setStreamActivity: vi.fn(),
    showThinkingIndicator: vi.fn(),
    hideThinkingIndicator: vi.fn(),
    appendFrame: vi.fn(),
    useReducer: ref<FoldLiveTurnMode>(false),
  }
  const options: UseChatSendOptions = {
    rpc,
    inputText: ref('hello'),
    messages: ref<ChatMessage[]>([]),
    sessionKey: ref('agent:main:webchat:test'),
    busySendMode: ref<BusySendMode>('queue'),
    elevatedMode: ref(''),
    runMode: ref('trusted'),
    pendingAttachments: ref<Attachment[]>([]),
    pendingSessionIntent: ref(null),
    aborted: ref(false),
    activeStreamTaskId: ref(''),
    autoScroll: ref(false),
    stream,
    normalizeElevatedMode: mode => mode,
    persistSession: vi.fn(),
    isCompactInFlightForCurrentSession: () => false,
    hasPendingAttachmentWork: () => false,
    enqueuePendingInput: vi.fn(() => true),
    popAllPendingIntoComposer: vi.fn(() => false),
    executeSlashCommand: vi.fn(async () => false),
    closeSlashMenu: vi.fn(),
    autoResizeTextarea: vi.fn(),
    scrollToBottom: vi.fn(),
    ...overrides,
  }
  return { api: useChatSend(options), options, rpc, stream }
}

describe('useChatSend attachment payloads', () => {
  it('sends the selected sandbox run mode as trusted source metadata', async () => {
    const { api, rpc } = makeOptions({
      runMode: ref('standard'),
    } as Partial<UseChatSendOptions>)

    await api.onSend()

    expect(rpc.call).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      _source: { runMode: 'standard' },
    }))
  })

  it('serializes only sendable attachments and leaves failed attachments in the composer', async () => {
    const failed: Attachment = {
      kind: 'failed',
      local_id: 1,
      name: 'failed.pdf',
      mime: 'application/pdf',
      error: 'HTTP 500',
      file: new File(['failed'], 'failed.pdf', { type: 'application/pdf' }),
    }
    const ready: Attachment = {
      kind: 'staged',
      local_id: 2,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-ready',
    }
    const pendingAttachments = ref<Attachment[]>([failed, ready])
    const { api, options, rpc } = makeOptions({ pendingAttachments })

    await api.onSend()

    expect(rpc.call).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      attachments: [
        { type: 'application/pdf', file_uuid: 'file-ready', mime: 'application/pdf', name: 'ready.pdf' },
      ],
    }))
    expect(options.messages.value[0]).toMatchObject({
      role: 'user',
      text: 'hello',
      attachments: [
        { kind: 'staged', displayId: 'local:2', renderKey: 'local:2', name: 'ready.pdf', mime: 'application/pdf' },
      ],
    })
    expect(JSON.stringify(options.messages.value[0])).not.toContain('file-ready')
    expect(JSON.stringify(options.messages.value[0])).not.toContain('failed.pdf')
    expect(pendingAttachments.value).toEqual([failed])
  })

  it('does not dispatch an empty failed-only attachment draft', async () => {
    const failed: Attachment = {
      kind: 'failed',
      local_id: 1,
      name: 'failed.pdf',
      mime: 'application/pdf',
      error: 'HTTP 500',
      file: new File(['failed'], 'failed.pdf', { type: 'application/pdf' }),
    }
    const pendingAttachments = ref<Attachment[]>([failed])
    const { api, rpc } = makeOptions({
      inputText: ref(''),
      pendingAttachments,
    })

    await api.onSend()

    expect(rpc.call).not.toHaveBeenCalled()
    expect(pendingAttachments.value).toEqual([failed])
  })

  it('restores staged attachments if chat.send fails after upload succeeded', async () => {
    const ready: Attachment = {
      kind: 'staged',
      local_id: 1,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-ready',
    }
    const pendingAttachments = ref<Attachment[]>([ready])
    const rpc = {
      call: vi.fn().mockRejectedValue(new Error('network down')),
    }
    const { api, options } = makeOptions({ rpc, pendingAttachments })

    await api.onSend()

    expect(pendingAttachments.value).toEqual([ready])
    expect(options.messages.value[options.messages.value.length - 1]).toMatchObject({
      role: 'error',
      text: 'Send failed: network down',
    })
  })
})
