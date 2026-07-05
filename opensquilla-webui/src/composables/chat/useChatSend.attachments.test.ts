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
    pendingForkBeforeMessageId: ref(null),
    aborted: ref(false),
    activeStreamTaskId: ref(''),
    activeStreamSessionKey: ref(''),
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

  it('refreshes staged uploads before serializing chat.send attachments', async () => {
    const pendingAttachments = ref<Attachment[]>([
      {
        kind: 'staged',
        local_id: 1,
        name: 'ready.pdf',
        mime: 'application/pdf',
        file_uuid: 'file-expired',
        expires_at: Date.now() / 1000 - 1,
        file: new File(['pdf'], 'ready.pdf', { type: 'application/pdf' }),
      },
    ])
    const prepareAttachmentsForSend = vi.fn(async () => {
      pendingAttachments.value = [
        {
          kind: 'staged',
          local_id: 1,
          name: 'ready.pdf',
          mime: 'application/pdf',
          file_uuid: 'file-fresh',
          expires_at: Date.now() / 1000 + 600,
          file: new File(['pdf'], 'ready.pdf', { type: 'application/pdf' }),
        },
      ]
      return true
    })
    const { api, rpc } = makeOptions({ pendingAttachments, prepareAttachmentsForSend })

    await api.onSend()

    expect(prepareAttachmentsForSend).toHaveBeenCalledTimes(1)
    expect(rpc.call).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      attachments: [
        { type: 'application/pdf', file_uuid: 'file-fresh', mime: 'application/pdf', name: 'ready.pdf' },
      ],
    }))
  })

  it('does not include attachments added while preparing an earlier send', async () => {
    const initialAttachment: Attachment = {
      kind: 'staged',
      local_id: 1,
      name: 'initial.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-initial',
    }
    const addedAttachment: Attachment = {
      kind: 'staged',
      local_id: 2,
      name: 'added-later.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-added-later',
    }
    const pendingAttachments = ref<Attachment[]>([initialAttachment])
    const prepareAttachmentsForSend = vi.fn(async () => {
      pendingAttachments.value = [initialAttachment, addedAttachment]
      return true
    })
    const { api, rpc } = makeOptions({ pendingAttachments, prepareAttachmentsForSend })

    await api.onSend()

    expect(rpc.call).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      attachments: [
        { type: 'application/pdf', file_uuid: 'file-initial', mime: 'application/pdf', name: 'initial.pdf' },
      ],
    }))
    expect(pendingAttachments.value).toEqual([addedAttachment])
  })

  it('does not mutate or send when attachment preparation returns false', async () => {
    const inputText = ref('hello')
    const expiredAttachment: Attachment = {
      kind: 'staged',
      local_id: 1,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-expired',
      expires_at: Date.now() / 1000 - 1,
      file: new File(['pdf'], 'ready.pdf', { type: 'application/pdf' }),
    }
    const pendingAttachments = ref<Attachment[]>([expiredAttachment])
    const prepareAttachmentsForSend = vi.fn(async () => false)
    const { api, options, rpc, stream } = makeOptions({
      inputText,
      pendingAttachments,
      prepareAttachmentsForSend,
    })

    await api.onSend()

    expect(prepareAttachmentsForSend).toHaveBeenCalledTimes(1)
    expect(rpc.call).not.toHaveBeenCalled()
    expect(options.messages.value).toHaveLength(0)
    expect(inputText.value).toBe('hello')
    expect(pendingAttachments.value).toEqual([expiredAttachment])
    expect(stream.startStreaming).not.toHaveBeenCalled()
  })

  it('does not mutate or send when session changes during attachment preparation', async () => {
    let resolvePrepare!: (ready: boolean) => void
    let prepareContext: { isCurrent?: () => boolean } | undefined
    const inputText = ref('hello')
    const sessionKey = ref('agent:main:webchat:first')
    const stagedAttachment: Attachment = {
      kind: 'staged',
      local_id: 1,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'file-ready',
      file: new File(['pdf'], 'ready.pdf', { type: 'application/pdf' }),
    }
    const pendingAttachments = ref<Attachment[]>([stagedAttachment])
    const prepareAttachmentsForSend = vi.fn((context?: { isCurrent?: () => boolean }) => new Promise<boolean>(resolve => {
      prepareContext = context
      resolvePrepare = resolve
    }))
    const { api, options, rpc, stream } = makeOptions({
      inputText,
      sessionKey,
      pendingAttachments,
      prepareAttachmentsForSend,
    })

    const send = api.onSend()
    sessionKey.value = 'agent:main:webchat:second'
    expect(prepareContext?.isCurrent?.()).toBe(false)
    resolvePrepare(true)
    await send

    expect(prepareAttachmentsForSend).toHaveBeenCalledTimes(1)
    expect(rpc.call).not.toHaveBeenCalled()
    expect(options.messages.value).toHaveLength(0)
    expect(inputText.value).toBe('hello')
    expect(pendingAttachments.value).toEqual([stagedAttachment])
    expect(stream.startStreaming).not.toHaveBeenCalled()
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

  it('sends pending fork target and clears it after chat.send is accepted', async () => {
    const pendingForkBeforeMessageId = ref<string | null>('msg-B')
    const { api, rpc } = makeOptions({ pendingForkBeforeMessageId })

    await api.onSend()

    expect(rpc.call).toHaveBeenCalledWith('chat.send', expect.objectContaining({
      forkBeforeMessageId: 'msg-B',
    }))
    expect(pendingForkBeforeMessageId.value).toBeNull()
  })

  it('keeps pending fork target if chat.send fails so retry can fork', async () => {
    const pendingForkBeforeMessageId = ref<string | null>('msg-B')
    const rpc = {
      call: vi.fn().mockRejectedValue(new Error('network down')),
    }
    const { api } = makeOptions({ rpc, pendingForkBeforeMessageId })

    await api.onSend()

    expect(pendingForkBeforeMessageId.value).toBe('msg-B')
  })

  it('invalidates the previous task id before a fresh send is accepted', async () => {
    let resolveSend!: (value: unknown) => void
    const call: UseChatSendOptions['rpc']['call'] = <T = unknown>() => new Promise<T>((resolve) => {
      resolveSend = resolve as (value: unknown) => void
    })
    const rpc = {
      call: vi.fn(call) as UseChatSendOptions['rpc']['call'],
    }
    const activeStreamTaskId = ref('task-old')
    const activeStreamSessionKey = ref('')
    const { api } = makeOptions({ rpc, activeStreamTaskId, activeStreamSessionKey })

    const send = api.onSend()

    expect(activeStreamTaskId.value).not.toBe('task-old')
    expect(activeStreamTaskId.value).toBeTruthy()
    expect(activeStreamSessionKey.value).toBe('agent:main:webchat:test')

    resolveSend({
      sessionKey: 'agent:main:webchat:test',
      task_id: 'task-new',
    })
    await send

    expect(activeStreamTaskId.value).toBe('task-new')
  })

  it('stops the session that owns the stream and poisons its stale task id', () => {
    const activeStreamTaskId = ref('task-old')
    const activeStreamSessionKey = ref('agent:main:webchat:old')
    const { api, rpc, stream } = makeOptions({
      sessionKey: ref('agent:main:webchat:new'),
      activeStreamTaskId,
      activeStreamSessionKey,
    })
    stream.isStreaming.value = true

    api.onStop()

    expect(rpc.call).toHaveBeenCalledWith('chat.abort', {
      sessionKey: 'agent:main:webchat:old',
      taskId: 'task-old',
      source: 'webui_stop',
    })
    expect(activeStreamTaskId.value).not.toBe('task-old')
  })

  it('does not let a stopped send response rebind the next turn', async () => {
    const pendingResponses: Array<(value: unknown) => void> = []
    const rpc = {
      call: vi.fn(<T = unknown>(method: string) => {
        if (method === 'chat.abort') return Promise.resolve({ aborted: true }) as Promise<T>
        return new Promise<T>((resolve) => {
          pendingResponses.push(resolve as (value: unknown) => void)
        })
      }) as UseChatSendOptions['rpc']['call'],
    }
    const inputText = ref('first')
    const activeStreamTaskId = ref('')
    const { api, stream } = makeOptions({ rpc, inputText, activeStreamTaskId })
    stream.startStreaming = vi.fn(() => { stream.isStreaming.value = true })
    stream.endStreaming = vi.fn(() => { stream.isStreaming.value = false })

    const firstSend = api.onSend()
    api.onStop()

    inputText.value = 'second'
    const secondSend = api.onSend()

    pendingResponses[1]({ sessionKey: 'agent:main:webchat:test', task_id: 'task-B' })
    await secondSend
    expect(activeStreamTaskId.value).toBe('task-B')

    pendingResponses[0]({ sessionKey: 'agent:main:webchat:test', task_id: 'task-A' })
    await firstSend

    expect(activeStreamTaskId.value).toBe('task-B')
    expect(rpc.call).toHaveBeenCalledWith('chat.abort', {
      sessionKey: 'agent:main:webchat:test',
      taskId: 'task-A',
      source: 'webui_stale_send',
    })
  })
})
