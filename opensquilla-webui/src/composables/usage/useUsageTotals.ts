import { computed, type ComputedRef, type Ref } from 'vue'
import type { SessionRow, UsageTotals } from '@/types/usage'

export function useUsageTotals(options: {
  visibleSessions: ComputedRef<SessionRow[]>
  currency: Ref<string>
  cnyRate: number
  rowVal: (row: Record<string, unknown>, ...keys: string[]) => unknown
  fmtCost: (usd: number | null | undefined, opts?: { decimals?: number }) => string
  sourceCompositionHint: (rows: SessionRow[]) => string
}) {
  const usageTotals = computed((): UsageTotals => {
    return options.visibleSessions.value.reduce((acc: UsageTotals, row) => {
      acc.input += Number(options.rowVal(row, 'input_tokens', 'inputTokens') || 0)
      acc.output += Number(options.rowVal(row, 'output_tokens', 'outputTokens') || 0)
      acc.cost += Number(options.rowVal(row, 'cost_usd', 'costUsd') || 0)
      acc.cacheRead += Number(options.rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0)
      acc.cacheWrite += Number(options.rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0)
      return acc
    }, { input: 0, output: 0, cost: 0, cacheRead: 0, cacheWrite: 0, sessions: options.visibleSessions.value.length })
  })

  const totalTokensDisplay = computed(() => {
    const t = usageTotals.value
    const total = t.input + t.output
    return total != null ? total.toLocaleString() : '-'
  })

  const tokensBreakdownParts = computed(() => {
    const t = usageTotals.value
    const parts: Array<{ label: string; value: string }> = []
    if (t.input != null) parts.push({ label: 'In', value: t.input.toLocaleString() })
    if (t.output != null) parts.push({ label: 'Out', value: t.output.toLocaleString() })
    if (t.cacheRead) parts.push({ label: 'Cache R', value: t.cacheRead.toLocaleString() })
    if (t.cacheWrite) parts.push({ label: 'Cache W', value: t.cacheWrite.toLocaleString() })
    return parts
  })

  const totalCostDisplay = computed(() => options.fmtCost(usageTotals.value.cost, { decimals: 4 }))

  const costHintText = computed(() => {
    const visibleRows = options.visibleSessions.value
    const sourceHint = options.sourceCompositionHint(visibleRows)
    let currencyHint = ''
    const totalCostUsd = usageTotals.value.cost
    if (options.currency.value === 'CNY') {
      currencyHint = `≈ ${('$' + Number(totalCostUsd).toFixed(4))} USD`
    } else if (options.currency.value === 'USD') {
      currencyHint = `≈ ¥${(Number(totalCostUsd) * options.cnyRate).toFixed(4)} CNY`
    }
    return [currencyHint, sourceHint].filter(Boolean).join(' · ')
  })

  const costHintTitle = computed(() => {
    return `CNY values use baked-in rate ${options.cnyRate}. Verify against current FX for accounting use.`
  })

  const sessionCountDisplay = computed(() => {
    const n = usageTotals.value.sessions
    return n != null ? String(n) : '-'
  })

  const avgCostDisplay = computed(() => {
    const t = usageTotals.value
    const avg = t.sessions > 0 ? t.cost / t.sessions : null
    return avg != null ? options.fmtCost(avg, { decimals: 4 }) : '-'
  })

  return {
    usageTotals,
    totalTokensDisplay,
    tokensBreakdownParts,
    totalCostDisplay,
    costHintText,
    costHintTitle,
    sessionCountDisplay,
    avgCostDisplay,
  }
}
