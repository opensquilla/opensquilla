import { computed, type ComputedRef, type Ref } from 'vue'
import i18n from '@/i18n'
import type { SessionRow, UsageTotals } from '@/types/usage'

const t = i18n.global.t

export function useUsageTotals(options: {
  visibleSessions: ComputedRef<SessionRow[]>
  serverTotals?: ComputedRef<UsageTotals | null>
  currency: Ref<string>
  cnyRate: number
  rowVal: (row: Record<string, unknown>, ...keys: string[]) => unknown
  fmtCost: (usd: number | null | undefined, opts?: { decimals?: number }) => string
  sourceCompositionHint: (rows: SessionRow[]) => string
}) {
  const usageTotals = computed((): UsageTotals => {
    if (options.serverTotals?.value) return options.serverTotals.value
    const totals = options.visibleSessions.value.reduce((acc: UsageTotals, row) => {
      acc.input += Number(options.rowVal(row, 'input_tokens', 'inputTokens') || 0)
      acc.output += Number(options.rowVal(row, 'output_tokens', 'outputTokens') || 0)
      acc.cost += Number(options.rowVal(row, 'cost_usd', 'costUsd') || 0)
      acc.cacheRead += Number(options.rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0)
      acc.cacheWrite += Number(options.rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0)
      acc.billedCost += Number(options.rowVal(row, 'billed_cost_usd', 'billedCostUsd') || 0)
      acc.estimatedCost += Number(options.rowVal(row, 'estimated_cost_usd', 'estimatedCostUsd') || 0)
      acc.estimatedEventCount += Number(
        options.rowVal(row, 'estimated_event_count', 'estimatedEventCount') || 0,
      )
      acc.missingCostEntries += Number(options.rowVal(row, 'missing_cost_entries', 'missingCostEntries') || 0)
      return acc
    }, {
      input: 0,
      output: 0,
      cost: 0,
      cacheRead: 0,
      cacheWrite: 0,
      sessions: options.visibleSessions.value.length,
      totalTokens: 0,
      billedCost: 0,
      estimatedCost: 0,
      estimatedEventCount: 0,
      missingCostEntries: 0,
      eventCount: 0,
      costSource: 'none',
      costSourceCounts: {},
    })
    totals.totalTokens = totals.input + totals.output
    return totals
  })

  const totalTokensDisplay = computed(() => {
    const t = usageTotals.value
    const total = t.input + t.output
    return total != null ? total.toLocaleString() : '-'
  })

  const tokensBreakdownParts = computed(() => {
    const t = usageTotals.value
    const parts: Array<{ label: string; value: string }> = []
    if (t.input != null) parts.push({ label: i18n.global.t('usageLogs.tokenParts.in'), value: t.input.toLocaleString() })
    if (t.output != null) parts.push({ label: i18n.global.t('usageLogs.tokenParts.out'), value: t.output.toLocaleString() })
    if (t.cacheRead) parts.push({ label: i18n.global.t('usageLogs.tokenParts.cacheRead'), value: t.cacheRead.toLocaleString() })
    if (t.cacheWrite) parts.push({ label: i18n.global.t('usageLogs.tokenParts.cacheWrite'), value: t.cacheWrite.toLocaleString() })
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
    return t('usageLogs.costHintTitle', { rate: options.cnyRate })
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
