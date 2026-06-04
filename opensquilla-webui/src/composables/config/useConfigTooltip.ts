import { nextTick, ref } from 'vue'

export function useConfigTooltip(help: Record<string, string>) {
  const activeTooltipKey = ref<string | null>(null)
  const tooltipRef = ref<HTMLElement | null>(null)
  const tooltipPlacement = ref<'bottom' | 'top'>('bottom')
  const tooltipStyle = ref<Record<string, string>>({})
  const tooltipArrowStyle = ref<Record<string, string>>({})
  let tooltipLocked = false
  let tooltipHideTimeout: ReturnType<typeof setTimeout> | null = null

  function helpFor(key: string): string {
    if (key in help) return help[key]
    return 'No description yet - see the docs.'
  }

  function showTooltip(event: Event, key: string) {
    activeTooltipKey.value = key
    tooltipLocked = false
    void nextTick(() => positionTooltip(event.target as HTMLElement))
  }

  function toggleTooltip(event: Event, key: string) {
    if (activeTooltipKey.value === key) {
      hideTooltip()
      return
    }
    activeTooltipKey.value = key
    tooltipLocked = true
    void nextTick(() => positionTooltip(event.target as HTMLElement))
  }

  function hideTooltip() {
    activeTooltipKey.value = null
    tooltipLocked = false
  }

  function hideTooltipDelayed(_event: Event, key: string) {
    if (tooltipHideTimeout) clearTimeout(tooltipHideTimeout)
    tooltipHideTimeout = setTimeout(() => {
      if (activeTooltipKey.value === key && !tooltipLocked) {
        hideTooltip()
      }
    }, 80)
  }

  function positionTooltip(anchor: HTMLElement) {
    const tip = tooltipRef.value
    if (!tip) return
    const rect = anchor.getBoundingClientRect()
    const tipRect = tip.getBoundingClientRect()
    const margin = 8
    let left = rect.left + rect.width / 2 - tipRect.width / 2
    left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin))
    let top = rect.bottom + 8
    let placement: 'bottom' | 'top' = 'bottom'
    if (top + tipRect.height + margin > window.innerHeight) {
      top = rect.top - tipRect.height - 8
      placement = 'top'
    }
    tooltipPlacement.value = placement
    tooltipStyle.value = {
      left: `${Math.round(left)}px`,
      top: `${Math.round(top)}px`,
      position: 'fixed',
    }
    const cx = rect.left + rect.width / 2 - left
    tooltipArrowStyle.value = {
      left: `${Math.max(12, Math.min(cx, tipRect.width - 12))}px`,
    }
  }

  function onDocClickForTooltip(e: MouseEvent) {
    if (!activeTooltipKey.value) return
    const tip = tooltipRef.value
    if (tip && tip.contains(e.target as Node)) return
    hideTooltip()
  }

  function onDocKeyForTooltip(e: KeyboardEvent) {
    if (e.key === 'Escape' && activeTooltipKey.value) {
      hideTooltip()
    }
  }

  return {
    activeTooltipKey,
    tooltipRef,
    tooltipPlacement,
    tooltipStyle,
    tooltipArrowStyle,
    helpFor,
    showTooltip,
    toggleTooltip,
    hideTooltip,
    hideTooltipDelayed,
    onDocClickForTooltip,
    onDocKeyForTooltip,
  }
}
