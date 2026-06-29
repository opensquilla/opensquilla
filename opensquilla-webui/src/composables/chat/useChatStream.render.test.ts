import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { useChatStream } from './useChatStream'
import type { ChatMessage } from '@/types/chat'

// Focused coverage for the streaming render coalescer: stream deltas are
// batched onto the frame clock (requestAnimationFrame) and the live reveal
// renders with syntax highlighting deferred. The test env is `node`, so rAF is
// stubbed and driven manually; fake timers cover the Date.now() flush throttle.
function makeStream(renderMarkdown = vi.fn((t: string, _o?: { highlight?: boolean }) => `<p>${t}</p>`)) {
  const scrollToBottom = vi.fn()
  const messages = ref<ChatMessage[]>([])
  const api = useChatStream({
    messages,
    lastHeaderRole: ref(''),
    aborted: ref(false),
    autoScroll: ref(true),
    applySessionRunState: vi.fn(),
    renderMarkdown: renderMarkdown as never,
    stripDirectiveTags: (t: string) => t,
    stripGeneratedArtifactMarkers: (t: string) => t,
    stripProtocolTextLeak: (t: string) => t,
    scrollToBottom,
  })
  return { api, messages, scrollToBottom, renderMarkdown }
}

describe('useChatStream render coalescing', () => {
  let rafCbs: FrameRequestCallback[]
  let rafSeq: number

  beforeEach(() => {
    vi.useFakeTimers()
    rafCbs = []
    rafSeq = 0
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { rafCbs.push(cb); return ++rafSeq })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('coalesces rapid deltas into a single frame flush and defers highlighting', () => {
    const { api, scrollToBottom, renderMarkdown } = makeStream()

    api.appendDelta('a')
    api.appendDelta('b')
    api.appendDelta('c')

    // One frame requested for three deltas; nothing renders until it fires.
    expect(rafCbs.length).toBe(1)
    expect(renderMarkdown).not.toHaveBeenCalled()

    vi.advanceTimersByTime(50) // past MIN_FLUSH_INTERVAL_MS
    rafCbs[0](0)

    // Rendered once over the combined text, with highlighting deferred.
    expect(renderMarkdown).toHaveBeenCalledTimes(1)
    expect(renderMarkdown).toHaveBeenCalledWith('abc', { highlight: false })
    expect(scrollToBottom).toHaveBeenCalledTimes(1)

    api.cleanup()
  })

  it('re-arms a fresh frame after a flush', () => {
    const { api, renderMarkdown } = makeStream()

    api.appendDelta('a')
    expect(rafCbs.length).toBe(1)
    vi.advanceTimersByTime(50)
    rafCbs[0](0)
    expect(renderMarkdown).toHaveBeenCalledTimes(1)

    api.appendDelta('b')
    expect(rafCbs.length).toBe(2) // a new frame is scheduled after the prior flush
    vi.advanceTimersByTime(50)
    rafCbs[1](0)
    expect(renderMarkdown).toHaveBeenCalledTimes(2)
    expect(renderMarkdown).toHaveBeenLastCalledWith('ab', { highlight: false })

    api.cleanup()
  })

  it('does not render a stale frame after cleanup', () => {
    const { api, renderMarkdown } = makeStream()

    api.appendDelta('a')
    expect(rafCbs.length).toBe(1)
    api.cleanup()

    vi.advanceTimersByTime(50)
    rafCbs[0](0) // firing the cancelled frame must not render

    expect(renderMarkdown).not.toHaveBeenCalled()
  })

  it('renders cumulative post-tool text snapshots as only the new suffix', () => {
    const { api, messages } = makeStream()
    const prefix = 'prefix'
    const suffix = 'suffix'

    api.appendDelta(prefix)
    api.appendToolCall({ tool_use_id: 'tool-1', tool_name: 'web_search' })
    api.appendToolResult({ tool_use_id: 'tool-1', tool_name: 'web_search', result: 'ok' })
    api.appendDelta(prefix + suffix)

    expect(api.foldedTurn.value.rawText).toBe(prefix + suffix)

    api.endStreaming()

    expect(messages.value[0]?.text).toBe(prefix + suffix)
    expect(messages.value[0]?.timeline).toEqual([
      { type: 'text', raw: prefix },
      { type: 'tool-group', groupId: 'stream:tool-group:web.search:0', operationKey: 'web.search' },
      { type: 'text', raw: suffix },
    ])
    api.cleanup()
  })

  it('keeps additive post-tool text deltas unchanged', () => {
    const { api, messages } = makeStream()

    api.appendDelta('prefix')
    api.appendToolCall({ tool_use_id: 'tool-1', tool_name: 'web_search' })
    api.appendToolResult({ tool_use_id: 'tool-1', tool_name: 'web_search', result: 'ok' })
    api.appendDelta('suffix')

    expect(api.foldedTurn.value.rawText).toBe('prefixsuffix')

    api.endStreaming()

    expect(messages.value[0]?.text).toBe('prefixsuffix')
    api.cleanup()
  })

  it('keeps cumulative-looking text before a tool boundary unchanged', () => {
    const { api, messages } = makeStream()

    api.appendDelta('prefix')
    api.appendDelta('prefixsuffix')

    expect(api.foldedTurn.value.rawText).toBe('prefixprefixsuffix')

    api.endStreaming()

    expect(messages.value[0]?.text).toBe('prefixprefixsuffix')
    api.cleanup()
  })
})
