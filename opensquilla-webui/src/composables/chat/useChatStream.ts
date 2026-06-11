import { computed, ref, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatRunStatusSource,
  ChatStreamSegment,
  ChatStreamTimelineItem,
  ChatToolCall,
  ChatTimelineSegment,
  RawToolCallPayload,
} from '@/types/chat'
import type {
  ArtifactPayload,
  ToolDeltaPayload,
  ToolResultPayload,
  ToolUsePayload,
} from '@/types/rpc'
import {
  isEmptyToolPreview,
  isInternalToolName,
  normalizeToolInputText,
  normalizeToolName,
  toolCallGroups,
  toolDisplayName,
  toolOperationKey,
  toolResultIsError,
  truncateToolPreview,
} from '@/utils/chat/toolDisplay'

const DEFAULT_STREAM_IDLE_TIMEOUT_MS = 210000
const THINKING_DELAY_MS = 400
const THINKING_TTL_MS = 60000
const SQUILLA_VERBS = ['Planning next step', 'Reading context', 'Waiting for model', 'Preparing output']
const SQUILLA_DWELL_MS = 2500
const STALE_SIGNAL_MS = 20000

const TOOL_PROGRESS_VERBS: Record<string, string> = {
  'web.search': 'Searching the web',
  'web.read': 'Reading a web page',
  'code.python': 'Running Python',
  'command.run': 'Running a command',
  'file.inspect': 'Inspecting files',
  'file.write': 'Writing a file',
  'file.edit': 'Editing a file',
  'artifact.create': 'Creating a file',
  'memory.search': 'Searching memory',
}

export interface UseChatStreamOptions {
  messages: Ref<ChatMessage[]>
  lastHeaderRole: Ref<string>
  aborted: Ref<boolean>
  autoScroll: Ref<boolean>
  applySessionRunState: (source: ChatRunStatusSource | null | undefined) => void
  renderMarkdown: (text: string) => string
  stripDirectiveTags: (text: string) => string
  stripGeneratedArtifactMarkers: (text: string) => string
  stripProtocolTextLeak: (text: string) => string
  scrollToBottom: () => void
}

export function useChatStream(options: UseChatStreamOptions) {
  const isStreaming = ref(false)
  const streamRaw = ref('')
  const streamSegments = ref<ChatStreamSegment[]>([])
  const streamArtifacts = ref<ArtifactPayload[]>([])
  const streamToolCalls = ref<ChatToolCall[]>([])
  const openToolGroups = ref<Set<string>>(new Set())
  const openToolItems = ref<Set<string>>(new Set())
  let streamToolGroupSeq = 0
  const streamBubble = ref(false)
  const streamShowHeader = ref(false)

  const streamHasVisibleOutput = computed(() => {
    return streamSegments.value.length > 0 ||
      streamToolCalls.value.length > 0 ||
      streamArtifacts.value.length > 0
  })

  const streamActivity = ref({ label: 'Sending', key: 'Sending', startedAt: 0 })
  const streamActivityTick = ref(0)
  let streamActivityTimer: ReturnType<typeof setInterval> | null = null
  const streamRound = ref(1)
  const lastSignalAt = ref(0)
  const toolTimes = ref(new Map<string, { startedAt: number; endedAt?: number }>())

  // The ribbon stays up for the whole run, including while tool rows render.
  const streamActivityVisible = computed(() => {
    return isStreaming.value && streamBubble.value
  })

  const streamActivityStale = computed(() => {
    streamActivityTick.value
    return lastSignalAt.value > 0 && Date.now() - lastSignalAt.value > STALE_SIGNAL_MS
  })

  const streamActivityText = computed(() => {
    streamActivityTick.value
    const now = Date.now()
    if (lastSignalAt.value > 0 && now - lastSignalAt.value > STALE_SIGNAL_MS) {
      const silent = Math.floor((now - lastSignalAt.value) / 1000)
      return `Still working — last signal ${silent}s ago`
    }
    const startedAt = streamActivity.value.startedAt || now
    const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
    const base = seconds >= 10 && streamActivity.value.label === 'Planning next step'
      ? 'Still waiting for model'
      : streamActivity.value.label
    return `${base} · ${seconds}s · round ${streamRound.value}`
  })

  const streamTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
    const groupsById = new Map(toolCallGroups(streamToolCalls.value, 'stream').map(group => [group.groupId, group]))
    return streamSegments.value.flatMap((seg, idx): ChatStreamTimelineItem[] => {
      if (seg.type === 'text') {
        if (!seg.raw && !seg.html) return []
        return [{ type: 'text', key: `text-${idx}`, html: seg.html || '' }]
      }
      const group = seg.groupId ? groupsById.get(seg.groupId) : null
      return group ? [{ type: 'tool-group', key: seg.groupId || `tool-${idx}`, group }] : []
    })
  })

  const thinkingVisible = ref(false)
  const thinkingText = ref('')
  let thinkingTimer: ReturnType<typeof setInterval> | null = null
  let thinkingDelayTimer: ReturnType<typeof setTimeout> | null = null
  let thinkingStartTime = 0

  const streamIdleTimer = ref<ReturnType<typeof setTimeout> | null>(null)
  const streamIdleTimeoutMs = ref(DEFAULT_STREAM_IDLE_TIMEOUT_MS)
  const streamIdlePausedForApproval = ref(false)
  let renderRafId: ReturnType<typeof setTimeout> | null = null
  let renderDirty = false

  function resetStreamState() {
    streamRaw.value = ''
    streamSegments.value = []
    streamToolCalls.value = []
    streamArtifacts.value = []
    toolTimes.value = new Map()
  }

  function noteStreamSignal() {
    lastSignalAt.value = Date.now()
  }

  // `key` identifies the activity phase: the elapsed counter restarts only
  // when the phase changes, so label refinements (e.g. tool arguments
  // streaming in) keep the same running clock.
  function setStreamActivity(label: string, key = label) {
    noteStreamSignal()
    const current = streamActivity.value
    if (current.key === key) {
      if (current.label !== label) {
        streamActivity.value = { label, key, startedAt: current.startedAt || Date.now() }
      }
    } else {
      streamActivity.value = { label, key, startedAt: Date.now() }
    }
    streamActivityTick.value++
    if (!streamActivityTimer) {
      streamActivityTimer = setInterval(() => {
        streamActivityTick.value++
      }, 1000)
    }
  }

  function toolNarrationLabel(tc: ChatToolCall): string {
    const verb = TOOL_PROGRESS_VERBS[toolOperationKey(tc.name)]
      || `Running ${tc.name.replace(/[_-]+/g, ' ')}`
    const arg = String(tc.inputPreview || '').replace(/\s+/g, ' ').trim().replace(/^"|"$/g, '')
    if (isEmptyToolPreview(arg)) return `${verb}…`
    return `${verb} · ${truncateToolPreview(arg, 48)}`
  }

  function narrateToolCall(tc: ChatToolCall) {
    setStreamActivity(toolNarrationLabel(tc), `tool:${tc.toolId}`)
  }

  function clearStreamActivity() {
    if (streamActivityTimer) {
      clearInterval(streamActivityTimer)
      streamActivityTimer = null
    }
    streamActivityTick.value++
  }

  function startStreaming() {
    isStreaming.value = true
    options.applySessionRunState({ run_status: 'running', active_task: { status: 'running' } })
    resetStreamState()
    openToolGroups.value = new Set()
    openToolItems.value = new Set()
    streamToolGroupSeq = 0
    streamRound.value = 1
    noteStreamSignal()
    streamBubble.value = true
    streamShowHeader.value = options.lastHeaderRole.value !== 'assistant'
    setStreamActivity('Sending')
    options.autoScroll.value = true
    resetStreamIdleTimer()
  }

  function endStreaming(opts?: { reason?: string }) {
    const wasAborted = opts?.reason === 'aborted'
    hideThinkingIndicator()
    clearStreamActivity()
    clearStreamIdleTimer()
    streamIdlePausedForApproval.value = false

    if (streamBubble.value) {
      const cleanedText = options.stripProtocolTextLeak(
        options.stripDirectiveTags(options.stripGeneratedArtifactMarkers(streamRaw.value)),
      ).trim()

      const sentinelOnly = !wasAborted && ['NO_REPLY', 'HEARTBEAT_OK'].includes(cleanedText)
      // After Stop, partial streamed output (text, tool rows, artifacts) is
      // kept; only a bubble with nothing visible at all is dropped.
      const emptyStream = !cleanedText && streamArtifacts.value.length === 0 && streamToolCalls.value.length === 0
      if (sentinelOnly || emptyStream) {
        streamBubble.value = false
        isStreaming.value = false
        resetStreamState()
        return
      }

      options.messages.value.push({
        role: 'assistant',
        text: cleanedText,
        ts: new Date().toISOString(),
        artifacts: streamArtifacts.value.slice(),
        tool_calls: streamToolCalls.value.map(streamToolCallToHistoryCall),
        timeline: streamTimelineSnapshot(cleanedText),
        interrupted: wasAborted || undefined,
      })
    }

    streamBubble.value = false
    isStreaming.value = false
    resetStreamState()
  }

  function resetStreamForRouterReplay() {
    resetStreamState()
    streamToolGroupSeq = 0
    streamBubble.value = true
    streamShowHeader.value = options.lastHeaderRole.value !== 'assistant'
    setStreamActivity('Switching model')
    clearRenderTimer()
  }

  function resetLiveTurnState() {
    hideThinkingIndicator()
    clearStreamActivity()
    clearStreamIdleTimer()
    streamIdlePausedForApproval.value = false
    isStreaming.value = false
    resetStreamState()
    streamBubble.value = false
  }

  function appendDelta(text: string) {
    if (options.aborted.value) return
    if (!isStreaming.value) startStreaming()
    setStreamActivity('Writing reply', `write:${streamRound.value}`)
    streamRaw.value += text

    const lastSegment = streamSegments.value[streamSegments.value.length - 1]
    if (!lastSegment || lastSegment.type !== 'text') {
      streamSegments.value.push({ type: 'text', raw: text, html: '', dirty: true })
    } else {
      lastSegment.raw = (lastSegment.raw || '') + text
      lastSegment.dirty = true
    }

    scheduleRender()
  }

  // Batch stream-driven DOM work (markdown re-render + autoscroll) into one
  // ~80ms flush so heavy tool turns do not re-render per event.
  function scheduleRender() {
    renderDirty = true
    if (!renderRafId) {
      renderRafId = setTimeout(flushRender, 80)
    }
  }

  function flushRender() {
    renderRafId = null
    if (!renderDirty) return

    for (const seg of streamSegments.value) {
      if (seg.type === 'text' && seg.dirty) {
        seg.html = options.renderMarkdown(seg.raw || '')
        seg.dirty = false
      }
    }

    renderDirty = false
    if (options.autoScroll.value) options.scrollToBottom()
  }

  function showThinkingIndicator() {
    if (streamBubble.value) {
      if (!streamHasVisibleOutput.value) setStreamActivity('Planning next step')
      return
    }
    if (thinkingVisible.value || thinkingDelayTimer) return
    thinkingStartTime = Date.now()
    thinkingDelayTimer = setTimeout(() => {
      thinkingDelayTimer = null
      if (streamBubble.value) return
      thinkingVisible.value = true
      updateThinkingText()
      thinkingTimer = setInterval(updateThinkingText, 1000)
    }, THINKING_DELAY_MS)
  }

  function updateThinkingText() {
    const elapsed = Date.now() - thinkingStartTime
    const seconds = Math.floor(elapsed / 1000)
    const verb = SQUILLA_VERBS[Math.floor(elapsed / SQUILLA_DWELL_MS) % SQUILLA_VERBS.length]
    thinkingText.value = `${verb} · ${seconds}s`
    if (seconds >= THINKING_TTL_MS / 1000) {
      hideThinkingIndicator()
      options.messages.value.push({ role: 'system', text: 'Still waiting for agent response...', ts: new Date().toISOString() })
    }
  }

  function hideThinkingIndicator() {
    if (thinkingDelayTimer) { clearTimeout(thinkingDelayTimer); thinkingDelayTimer = null }
    if (thinkingTimer) { clearInterval(thinkingTimer); thinkingTimer = null }
    thinkingVisible.value = false
  }

  function resetStreamIdleTimer() {
    // Every gateway event funnels through here, including run heartbeats, so
    // it doubles as the liveness signal for the staleness note.
    noteStreamSignal()
    clearStreamIdleTimer()
    if (!isStreaming.value || streamIdlePausedForApproval.value) return
    streamIdleTimer.value = setTimeout(() => {
      if (isStreaming.value && !streamIdlePausedForApproval.value) {
        endStreaming()
        const seconds = Math.round(streamIdleTimeoutMs.value / 1000)
        options.messages.value.push({ role: 'error', text: `Response timed out -- no events received for ${seconds}s`, ts: new Date().toISOString() })
      }
    }, streamIdleTimeoutMs.value)
  }

  function clearStreamIdleTimer() {
    if (streamIdleTimer.value) { clearTimeout(streamIdleTimer.value); streamIdleTimer.value = null }
  }

  function ensureStreamToolCall(payload: ToolUsePayload | ToolResultPayload, optionsArg: { running: boolean }): ChatToolCall | null {
    if (!payload) return null
    const name = normalizeToolName(payload)
    if (!name) return null
    if (isInternalToolName(name)) return null
    if (!isStreaming.value) startStreaming()
    const input = normalizeToolInputText(payload)
    const toolId = payload.tool_use_id || payload.toolUseId || payload.id || `${name}:${payload.stream_seq || Date.now()}`

    const existing = streamToolCalls.value.find(tc => tc.toolId === toolId)
    if (existing) {
      if (input) {
        existing.inputRaw = input
        existing.inputPreview = truncateToolPreview(input, 200)
        existing.displayName = toolDisplayName(existing.name, input)
      }
      return existing
    }

    // Only calls observed from their start get a wall clock; result-only
    // calls (and replayed history) never show a fabricated elapsed time.
    if (optionsArg.running && !toolTimes.value.has(toolId)) {
      toolTimes.value.set(toolId, { startedAt: Date.now() })
    }

    const operationKey = toolOperationKey(name)
    const lastSegment = streamSegments.value[streamSegments.value.length - 1]
    const groupId = lastSegment?.type === 'tool-group' && lastSegment.operationKey === operationKey && lastSegment.groupId
      ? lastSegment.groupId
      : `stream:tool-group:${operationKey}:${streamToolGroupSeq++}`

    if (lastSegment?.type !== 'tool-group' || lastSegment.groupId !== groupId) {
      streamSegments.value.push({ type: 'tool-group', groupId, operationKey })
    }

    const call: ChatToolCall = {
      toolId,
      name,
      displayName: toolDisplayName(name, input),
      groupId,
      inputRaw: input,
      inputPreview: truncateToolPreview(input, 200),
      isRunning: optionsArg.running,
      status: '',
      isError: false,
      result: '',
      resultPreview: '',
      isOpen: false,
    }
    streamToolCalls.value.push(call)
    return call
  }

  function appendToolCall(payload: ToolUsePayload) {
    const tc = ensureStreamToolCall(payload, { running: true })
    if (!tc) return
    narrateToolCall(tc)
    scheduleRender()
  }

  function appendToolDelta(payload: ToolDeltaPayload) {
    if (!payload || options.aborted.value) return
    const toolId = payload.tool_use_id || payload.toolUseId || payload.id || ''
    const fragment = payload.json_fragment ?? payload.jsonFragment ?? payload.fragment ?? ''
    const fragmentText = typeof fragment === 'string' ? fragment : String(fragment || '')
    if (!toolId || !fragmentText) return

    const existing = streamToolCalls.value.find(t => t.toolId === toolId)
    const tc = existing || ensureStreamToolCall(payload, { running: true })
    if (!tc) return

    const nextInput = `${tc.inputRaw || ''}${fragmentText}`
    tc.inputRaw = nextInput
    if (!isEmptyToolPreview(nextInput)) {
      tc.inputPreview = truncateToolPreview(nextInput, 200)
      tc.displayName = toolDisplayName(tc.name, nextInput)
    }
    if (tc.isRunning) narrateToolCall(tc)
    scheduleRender()
  }

  function appendToolResult(payload: ToolResultPayload) {
    if (!payload) return
    const name = normalizeToolName(payload)
    if (name && isInternalToolName(name)) return
    if (!isStreaming.value) startStreaming()
    const raw = payload.result || payload.content || payload.output || ''
    const content = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)
    const toolId = payload.tool_use_id || payload.toolUseId || payload.id || ''

    const tc = streamToolCalls.value.find(t => t.toolId === toolId) || ensureStreamToolCall(payload, { running: false })
    if (tc) {
      const input = normalizeToolInputText(payload)
      if (input) {
        tc.inputRaw = input
        tc.inputPreview = truncateToolPreview(input, 200)
        tc.displayName = toolDisplayName(tc.name, input)
      }
      tc.isRunning = false
      tc.status = toolResultIsError(payload) ? 'error' : 'success'
      tc.isError = toolResultIsError(payload)
      tc.result = content
      tc.resultPreview = truncateToolPreview(content, 200)

      const timing = toolTimes.value.get(tc.toolId)
      if (timing && !timing.endedAt) timing.endedAt = Date.now()

      const stillRunning = streamToolCalls.value.find(t => t.isRunning)
      if (stillRunning) {
        narrateToolCall(stillRunning)
      } else {
        // All tools in the batch came back: the model starts its next round.
        streamRound.value++
        setStreamActivity('Planning next step', `plan:${streamRound.value}`)
      }
    }

    scheduleRender()
  }

  function streamToolElapsedText(call: Pick<ChatToolCall, 'toolId'>): string {
    streamActivityTick.value
    const timing = toolTimes.value.get(call.toolId)
    if (!timing) return ''
    const end = timing.endedAt ?? Date.now()
    const seconds = Math.max(0, end - timing.startedAt) / 1000
    if (timing.endedAt && seconds < 10) return `${seconds.toFixed(1)}s`
    const whole = Math.floor(seconds)
    if (whole < 60) return `${whole}s`
    return `${Math.floor(whole / 60)}m ${whole % 60}s`
  }

  function streamToolCallToHistoryCall(tc: ChatToolCall): RawToolCallPayload {
    return {
      id: tc.toolId,
      toolId: tc.toolId,
      tool_use_id: tc.toolId,
      name: tc.name,
      tool_name: tc.name,
      input: tc.inputRaw || tc.inputPreview,
      groupId: tc.groupId,
      result: tc.result,
      is_error: tc.isError,
      isError: tc.isError,
      execution_status: tc.status ? { status: tc.status } : undefined,
    }
  }

  function streamTimelineSnapshot(fallbackText = ''): ChatTimelineSegment[] {
    const segments = streamSegments.value
      .flatMap((seg): ChatTimelineSegment[] => {
        if (seg.type === 'text') {
          const raw = String(seg.raw || '')
          return raw ? [{ type: 'text', raw }] : []
        }
        if (seg.type === 'tool-group') {
          return [{
            type: 'tool-group',
            groupId: seg.groupId,
            operationKey: seg.operationKey,
          }]
        }
        return []
      })
    if (segments.length === 0 && fallbackText) return [{ type: 'text', raw: fallbackText }]
    return segments
  }

  function appendArtifact(payload: ArtifactPayload) {
    if (!payload) return
    noteStreamSignal()
    streamArtifacts.value.push(payload)
    scheduleRender()
  }

  function reconcileFinalText(finalText: string) {
    if (finalText && finalText !== streamRaw.value) {
      streamRaw.value = finalText
    }
  }

  function isToolGroupOpen(groupId: string): boolean {
    return openToolGroups.value.has(groupId)
  }

  function toggleToolGroup(groupId: string) {
    const next = new Set(openToolGroups.value)
    next.has(groupId) ? next.delete(groupId) : next.add(groupId)
    openToolGroups.value = next
  }

  function isToolItemOpen(itemId: string): boolean {
    return openToolItems.value.has(itemId)
  }

  function toggleToolItem(itemId: string) {
    const next = new Set(openToolItems.value)
    next.has(itemId) ? next.delete(itemId) : next.add(itemId)
    openToolItems.value = next
  }

  function clearRenderTimer() {
    renderDirty = false
    if (renderRafId) {
      clearTimeout(renderRafId)
      renderRafId = null
    }
  }

  function cleanup() {
    clearRenderTimer()
    clearStreamIdleTimer()
    hideThinkingIndicator()
    clearStreamActivity()
  }

  return {
    isStreaming,
    streamArtifacts,
    streamBubble,
    streamHasVisibleOutput,
    streamTimelineItems,
    streamActivityVisible,
    streamActivityStale,
    streamActivityText,
    streamToolElapsedText,
    thinkingVisible,
    thinkingText,
    startStreaming,
    endStreaming,
    resetStreamForRouterReplay,
    resetLiveTurnState,
    appendDelta,
    appendToolCall,
    appendToolDelta,
    appendToolResult,
    appendArtifact,
    reconcileFinalText,
    resetStreamIdleTimer,
    clearStreamIdleTimer,
    setStreamActivity,
    showThinkingIndicator,
    hideThinkingIndicator,
    isToolGroupOpen,
    toggleToolGroup,
    isToolItemOpen,
    toggleToolItem,
    cleanup,
  }
}
