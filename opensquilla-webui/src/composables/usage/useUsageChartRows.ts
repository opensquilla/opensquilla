import { computed, type ComputedRef, type Ref } from 'vue'
import type { ChartRow, SessionRow } from '@/types/usage'

export function useUsageChartRows(options: {
  visibleSessions: ComputedRef<SessionRow[]>
  chartMode: Ref<'tokens' | 'cost'>
  rowVal: (row: Record<string, unknown>, ...keys: string[]) => unknown
  fmtCost: (usd: number | null | undefined, opts?: { decimals?: number }) => string
  fmtNum: (value: number | null | undefined) => string
}) {
  const chartCaption = computed(() => {
    const pool = options.visibleSessions.value.filter(r => {
      const inp = Number(options.rowVal(r, 'input_tokens', 'inputTokens') || 0)
      const out = Number(options.rowVal(r, 'output_tokens', 'outputTokens') || 0)
      return (inp + out) > 0
    })
    const shown = Math.min(20, pool.length)
    const suffix = pool.length > shown ? ` · showing ${shown} of ${pool.length}` : ''
    return (options.chartMode.value === 'cost' ? 'Top sessions by cost' : 'Top sessions by total tokens') + suffix
  })

  const chartRows = computed((): ChartRow[] => {
    const sorted = [...options.visibleSessions.value].filter(r => {
      const inp = Number(options.rowVal(r, 'input_tokens', 'inputTokens') || 0)
      const out = Number(options.rowVal(r, 'output_tokens', 'outputTokens') || 0)
      return (inp + out) > 0
    }).sort((a, b) => {
      if (options.chartMode.value === 'cost') {
        return (Number(options.rowVal(b, 'cost_usd', 'costUsd') || 0)) - (Number(options.rowVal(a, 'cost_usd', 'costUsd') || 0))
      }
      const totalA = Number(options.rowVal(a, 'input_tokens', 'inputTokens') || 0) + Number(options.rowVal(a, 'output_tokens', 'outputTokens') || 0)
      const totalB = Number(options.rowVal(b, 'input_tokens', 'inputTokens') || 0) + Number(options.rowVal(b, 'output_tokens', 'outputTokens') || 0)
      return totalB - totalA
    }).slice(0, 20)

    if (sorted.length === 0) return []

    let maxVal = 0
    if (options.chartMode.value === 'cost') {
      maxVal = Math.max(...sorted.map(r => Number(options.rowVal(r, 'cost_usd', 'costUsd') || 0)))
    } else {
      maxVal = Math.max(...sorted.map(r =>
        Number(options.rowVal(r, 'input_tokens', 'inputTokens') || 0) + Number(options.rowVal(r, 'output_tokens', 'outputTokens') || 0)
      ))
    }
    if (maxVal === 0) maxVal = 1

    return sorted.map(row => {
      const fullLabel = (options.rowVal(row, 'session', 'sessionKey', 'key') || '-') as string
      const label = fullLabel.length > 26 ? fullLabel.slice(0, 24) + '...' : fullLabel
      if (options.chartMode.value === 'cost') {
        const cost = Number(options.rowVal(row, 'cost_usd', 'costUsd') || 0)
        const pct = (cost / maxVal) * 100
        return {
          sessionKey: fullLabel,
          label,
          inputPct: pct,
          outputPct: 0,
          totalPct: pct,
          valueLabel: options.fmtCost(cost),
        }
      }

      const inp = Number(options.rowVal(row, 'input_tokens', 'inputTokens') || 0)
      const out = Number(options.rowVal(row, 'output_tokens', 'outputTokens') || 0)
      const total = inp + out
      const inputPct = (inp / maxVal) * 100
      const outputPct = (out / maxVal) * 100
      return {
        sessionKey: fullLabel,
        label,
        inputPct,
        outputPct,
        totalPct: inputPct + outputPct,
        valueLabel: options.fmtNum(total),
      }
    })
  })

  return { chartCaption, chartRows }
}
