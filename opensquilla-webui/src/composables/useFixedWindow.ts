import { ref, computed, onUnmounted, type Ref, type ComputedRef } from 'vue'

/**
 * A list with fixed-height rows where only the on-screen slice is mounted.
 *
 * Given a flat reactive array, a fixed row height, and the scroll container
 * ref, this returns the visible range (plus overscan) and the top/bottom spacer
 * heights that keep the scrollbar geometry honest. The caller renders the
 * `visible` slice inside a wrapper padded by `topPad`/`bottomPad` and forwards
 * the container's `@scroll` to `onScroll`.
 */
export interface FixedWindow<T> {
  /** Items currently mounted (visible range + overscan). */
  visible: ComputedRef<Array<{ item: T; index: number }>>
  /** Spacer heights that keep total scroll height honest. */
  topPad: ComputedRef<number>
  bottomPad: ComputedRef<number>
  /** Attach to the scroll container's @scroll. */
  onScroll: (e: Event) => void
  /** Recompute viewport height (call on mount / resize). */
  measure: () => void
  /** Jump to the last row (auto-follow). */
  scrollToEnd: () => void
}

export function useFixedWindow<T>(
  source: Ref<T[]> | ComputedRef<T[]>,
  rowHeight: number,
  container: Ref<HTMLElement | null>,
  overscan = 12,
): FixedWindow<T> {
  const scrollTop = ref(0)
  const viewportH = ref(0)

  const total = computed(() => source.value.length)

  const startIndex = computed(() =>
    Math.max(0, Math.floor(scrollTop.value / rowHeight) - overscan))
  const visibleCount = computed(() =>
    Math.ceil(viewportH.value / rowHeight) + overscan * 2)
  const endIndex = computed(() =>
    Math.min(total.value, startIndex.value + visibleCount.value))

  const visible = computed(() => {
    const out: Array<{ item: T; index: number }> = []
    for (let i = startIndex.value; i < endIndex.value; i++) {
      out.push({ item: source.value[i], index: i })
    }
    return out
  })

  const topPad = computed(() => startIndex.value * rowHeight)
  const bottomPad = computed(() =>
    Math.max(0, (total.value - endIndex.value) * rowHeight))

  let ro: ResizeObserver | null = null
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => measure())
  }
  let observed: HTMLElement | null = null

  function onScroll(e: Event) {
    const el = e.target as HTMLElement
    scrollTop.value = el.scrollTop
  }

  // Measures the container and lazily attaches the resize observer. The caller
  // wires the container ref in onMounted, so the first measure() after mount is
  // where the element becomes available — observe it there rather than guessing
  // a microtask deadline.
  function measure() {
    const el = container.value
    if (!el) return
    viewportH.value = el.clientHeight
    if (ro && observed !== el) {
      if (observed) ro.unobserve(observed)
      ro.observe(el)
      observed = el
    }
  }

  function scrollToEnd() {
    const el = container.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    scrollTop.value = el.scrollTop
  }

  onUnmounted(() => { ro?.disconnect() })

  return { visible, topPad, bottomPad, onScroll, measure, scrollToEnd }
}
