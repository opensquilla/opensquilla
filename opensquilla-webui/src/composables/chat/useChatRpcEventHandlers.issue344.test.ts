// Issue #344: a stale task's late stream events bled into the current turn.
//
// Repro: task-A (PPTX→PDF) failed, the user then sent task-B (image→HTML), but
// task-A's late tool_use_start / artifact / terminal-error kept rendering in —
// and ending — the turn that was supposed to belong to task-B. The events were
// only filtered by session key, so same-session stale events passed through.
//
// The fix binds the live stream to a single `activeStreamTaskId` and drops
// events tagged with a different task. These tests drive the real handler entry
// points and assert task-A's events no longer touch task-B's turn, while
// task-B's own events (and legacy untagged events) still flow.
import { describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type Ref } from 'vue'
import type { ChatMessage, ChatRunStatus, ChatRunStatusSource } from '@/types/chat'
import type { ToolUsePayload } from '@/types/rpc'
import {
  useChatRpcEventHandlers,
  type ChatRpcStreamApi,
  type UseChatRpcEventHandlersOptions,
} from './useChatRpcEventHandlers'

const SESSION = 'agent:main:webchat:issue344'

function makeStream(): ChatRpcStreamApi {
  return {
    isStreaming: ref(true),
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
    useReducer: ref(false),
  }
}

function makeHarness(activeStreamTaskId = '') {
  const stream = makeStream()
  const messages: Ref<ChatMessage[]> = ref([])
  const activeTaskId = ref(activeStreamTaskId)
  const options: UseChatRpcEventHandlersOptions = {
    sessionKey: ref(SESSION),
    currentEpoch: ref(0),
    lastStreamSeq: ref(0),
    activeTaskGroups: ref(new Set<string>()),
    activeStreamTaskId: activeTaskId,
    aborted: ref(false),
    messages,
    pendingQueue: ref([]),
    usageAccum: ref({
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      cost: null,
      routedTurns: 0,
      sessionSaved: 0,
    }),
    usageModel: ref(''),
    stream,
    normalizeRunStatus: (s: string) => s,
    sessionRunStatus: () => ({ status: 'idle', label: 'Idle', task: null }),
    applySessionRunState: vi.fn(),
    queueRouterDecision: vi.fn(),
    appendEnsembleProgress: vi.fn(),
    markEnsembleHandoff: vi.fn(),
    flushPendingRouterDecision: vi.fn(),
    clearPendingRouterDecision: vi.fn(),
    handleRouterControlReplay: vi.fn(),
    showCompactionToast: vi.fn(),
    scheduleHistorySync: vi.fn(),
    schedulePendingDrainAfterTerminal: vi.fn(),
    popAllPendingIntoComposer: vi.fn(() => false),
    saveWidgetState: vi.fn(),
    subscribeSession: vi.fn(),
    loadHistory: vi.fn(),
    loadCurrentSessionUsage: vi.fn(),
  }
  const scope = effectScope()
  const api = scope.run(() => useChatRpcEventHandlers(options))!
  return { api, options, stream, messages, activeTaskId, scope }
}

function toolUse(taskId: string | undefined, toolName: string): ToolUsePayload {
  return {
    session_key: SESSION,
    stream_seq: 1,
    task_id: taskId,
    tool_use_id: `${toolName}-id`,
    tool_name: toolName,
  } as unknown as ToolUsePayload
}

describe('issue #344 — live stream is bound to a single task', () => {
  it("drops a stale task's tool_use_start while another task owns the live stream", () => {
    const { api, stream } = makeHarness('task-B')
    api.handlers.onToolUseStart(toolUse('task-A', 'create_pdf.py'))
    expect(stream.appendToolCall).not.toHaveBeenCalled()
  })

  it("appends the active task's own tool_use_start", () => {
    const { api, stream } = makeHarness('task-B')
    api.handlers.onToolUseStart(toolUse('task-B', 'write_html'))
    expect(stream.appendToolCall).toHaveBeenCalledTimes(1)
  })

  it('still appends untagged events so a legacy backend keeps working', () => {
    const { api, stream } = makeHarness('task-B')
    api.handlers.onToolUseStart(toolUse(undefined, 'shell'))
    expect(stream.appendToolCall).toHaveBeenCalledTimes(1)
  })

  it("does not end the current stream on a stale task's terminal error", () => {
    const { api, stream, messages } = makeHarness('task-B')
    api.handlers.onAny('task.failed', {
      task_id: 'task-A',
      session_key: SESSION,
      terminal_message: '图片转文字PDF错误',
    })
    expect(stream.endStreaming).not.toHaveBeenCalled()
    expect(messages.value.some((m) => m.role === 'error')).toBe(false)
  })

  it("does not end the current stream on a stale task's terminal sessions.changed", () => {
    const { api, stream, options } = makeHarness('task-B')
    api.handlers.onSessionsChanged({
      session_key: SESSION,
      reason: 'task_terminal',
      run_status: 'cancelled',
      last_task: { task_id: 'task-A', status: 'cancelled' },
    } as never)
    expect(stream.endStreaming).not.toHaveBeenCalled()
    expect(options.applySessionRunState).not.toHaveBeenCalled()
  })

  it("ends the current stream on the active task's terminal error", () => {
    const { api, stream, messages } = makeHarness('task-B')
    api.handlers.onAny('task.failed', {
      task_id: 'task-B',
      session_key: SESSION,
      terminal_message: 'HTML generation failed',
    })
    expect(stream.endStreaming).toHaveBeenCalled()
    expect(messages.value.some((m) => m.role === 'error')).toBe(true)
  })

  it('binds activeStreamTaskId from task.running, then filters the prior task', () => {
    const { api, options, stream } = makeHarness('')
    api.handlers.onTaskRunning({ task_id: 'task-B', session_key: SESSION })
    expect(options.activeStreamTaskId.value).toBe('task-B')
    api.handlers.onToolUseStart(toolUse('task-A', 'create_pdf.py'))
    expect(stream.appendToolCall).not.toHaveBeenCalled()
  })

  it('binds a queued task while a fresh send is still pending so early cancellation can end it', () => {
    const { api, options, stream } = makeHarness('__opensquilla_pending_stream_task__')

    api.handlers.onTaskQueued({ task_id: 'task-B', session_key: SESSION })
    expect(options.activeStreamTaskId.value).toBe('task-B')

    api.handlers.onAny('task.cancelled', {
      task_id: 'task-B',
      session_key: SESSION,
      terminal_message: 'The task was cancelled before it finished.',
    })

    expect(stream.endStreaming).toHaveBeenCalled()
  })

  it("accepts the stopped task's cancelled terminal event after Stop poisoned the active id", () => {
    const { api, options, stream } = makeHarness('__opensquilla_stopped_stream_task__')
    stream.isStreaming.value = false

    api.handlers.onAny('task.cancelled', {
      task_id: 'task-B',
      session_key: SESSION,
      terminal_message: 'The task was cancelled before it finished.',
    })

    expect(options.applySessionRunState).toHaveBeenCalledWith(expect.objectContaining({
      run_status: 'cancelled',
      last_task: expect.objectContaining({
        task_id: 'task-B',
        status: 'cancelled',
      }),
    }))
  })

  it("accepts the stopped task's terminal sessions.changed payload", () => {
    const { api, options, stream } = makeHarness('__opensquilla_stopped_stream_task__')
    stream.isStreaming.value = false
    const cancelledPayload = {
      session_key: SESSION,
      reason: 'task_terminal',
      run_status: 'cancelled',
      last_task: { task_id: 'task-B', status: 'cancelled' },
    } satisfies ChatRunStatusSource & { session_key: string; reason: string }
    options.sessionRunStatus = vi.fn((source: ChatRunStatusSource | null | undefined): ChatRunStatus => {
      const isCancelled = source?.run_status === 'cancelled'
      return {
        status: isCancelled ? 'cancelled' : 'idle',
        label: isCancelled ? 'Cancelled' : 'Idle',
        task: source?.last_task ?? null,
      }
    })

    api.handlers.onSessionsChanged(cancelledPayload as never)

    expect(options.applySessionRunState).toHaveBeenCalledWith(
      expect.objectContaining({
        run_status: 'cancelled',
        last_task: expect.objectContaining({
          task_id: 'task-B',
          status: 'cancelled',
        }),
      }),
    )
  })
})
