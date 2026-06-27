import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { useChatStream } from './useChatStream'

// Focused coverage for the streaming render coalescer: stream deltas are
// batched onto the frame clock (requestAnimationFrame) and the live reveal
// renders with syntax highlighting deferred. The test env is `node`, so rAF is
// stubbed and driven manually; fake timers cover the Date.now() flush throttle.
function makeStream(renderMarkdown = vi.fn((t: string, _o?: { highlight?: boolean }) => `<p>${t}</p>`)) {
  const scrollToBottom = vi.fn()
  const api = useChatStream({
    messages: ref([]) as never,
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
  return { api, scrollToBottom, renderMarkdown }
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
})
