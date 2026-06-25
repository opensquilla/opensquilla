import { ref, computed, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { useDocumentEvent } from '@/composables/useDocumentEvent'
import { useRequest } from '@/composables/useRequest'
import { useUsagePreferences } from '@/composables/usage/useUsagePreferences'
import { useUsageTotals } from '@/composables/usage/useUsageTotals'
import { useUsageChartRows } from '@/composables/usage/useUsageChartRows'
import { useUsageModelCards } from '@/composables/usage/useUsageModelCards'
import { useUsageSessionRows } from '@/composables/usage/useUsageSessionRows'
import { downloadText } from '@/utils/browser'
import type { BreakdownRow, ModelBreakdownItem, SessionRow, TableColumn, UsageStatusData } from '@/types/usage'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CNY_RATE = 7.25

const TABLE_COLUMNS: TableColumn[] = [
  { key: 'session', label: 'Session' },
  { key: 'updated_at', label: 'Modified' },
  { key: 'input_tokens', label: 'Input' },
  { key: 'output_tokens', label: 'Output' },
  { key: 'cache_read_tokens', label: 'Cache R' },
  { key: 'cache_write_tokens', label: 'Cache W' },
  { key: 'cost_usd', label: 'Cost' },
  { key: 'cost_source', label: 'Source' },
  { key: 'model', label: 'Model' },
]

const SORTABLE_COLS = ['session', 'updated_at', 'input_tokens', 'output_tokens', 'cost_usd', 'model']

export function useUsageData() {
// ---------------------------------------------------------------------------
// Stores & Router
// ---------------------------------------------------------------------------

const router = useRouter()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const {
  currency,
  range,
  setCurrency,
  setRange,
} = useUsagePreferences()
const sortCol = ref('updated_at')
const sortAsc = ref(false)
const chartMode = ref<'tokens' | 'cost'>('tokens')
const expandedSessions = ref<Set<string>>(new Set())

const { data: usageStatusData, loading: usageLoading, error: usageError, refresh: refreshUsage } = useRequest<UsageStatusData>(
  'usage.status',
  undefined,
  { errorLabel: 'Failed to load usage', immediate: false },
)

const sessions = computed<SessionRow[]>(() => usageStatusData.value?.sessions || [])
const lastStatus = computed<UsageStatusData | null>(() => usageStatusData.value ?? null)

let autoRefreshId: ReturnType<typeof setInterval> | null = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const tableColumns = computed(() => TABLE_COLUMNS)
const sortableCols = computed(() => SORTABLE_COLS)

const visibleSessions = computed(() => {
  const cutoff = rangeCutoffMs(range.value)
  if (cutoff == null) return sessions.value
  return sessions.value.filter(row => {
    const ts = sessionTimestamp(row)
    return ts != null && ts >= cutoff
  })
})

const undatedHiddenCount = computed(() => {
  if (range.value === 'all') return 0
  return sessions.value.filter(row => sessionTimestamp(row) == null).length
})

const rangeHiddenHint = computed(() => {
  const hidden = undatedHiddenCount.value
  if (hidden <= 0) return ''
  return `${hidden} undated legacy session${hidden === 1 ? '' : 's'} hidden`
})

const {
  usageTotals,
  totalTokensDisplay,
  tokensBreakdownParts,
  totalCostDisplay,
  costHintText,
  costHintTitle,
  sessionCountDisplay,
  avgCostDisplay,
} = useUsageTotals({
  visibleSessions,
  currency,
  cnyRate: CNY_RATE,
  rowVal,
  fmtCost,
  sourceCompositionHint,
})

const { chartCaption, chartRows } = useUsageChartRows({
  visibleSessions,
  chartMode,
  rowVal,
  fmtCost,
  fmtNum,
})

const { modelCards, modelsMeta } = useUsageModelCards({
  visibleSessions,
  rowVal,
})

const { sortedRows, sessionsMeta } = useUsageSessionRows({
  visibleSessions,
  rangeHiddenHint,
  sortCol,
  sortAsc,
  rowVal,
  numericRowVal,
  sessionTimestamp,
  relTime,
  sortVal,
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

// The initial fetch and the 60s refresh timer both live on activate/deactivate,
// so a kept-alive but hidden Usage view stops polling. onActivated fires on
// first mount too, so it owns the one-time fetch as well — no separate
// onMounted fetch, which would double-fetch usage.status on first paint.
onActivated(() => {
  if (!autoRefreshId) autoRefreshId = setInterval(loadData, 60000)
  // A returning view refreshes immediately so cached numbers don't linger.
  loadData()
})

onDeactivated(() => {
  if (autoRefreshId) {
    clearInterval(autoRefreshId)
    autoRefreshId = null
  }
})

onUnmounted(() => {
  if (autoRefreshId) {
    clearInterval(autoRefreshId)
    autoRefreshId = null
  }
})

useDocumentEvent('visibilitychange', onVisibilityChange)

function onVisibilityChange() {
  if (document.visibilityState === 'visible') loadData()
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function setSort(col: string) {
  if (sortCol.value === col) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = col
    sortAsc.value = false
  }
}

function openSession(key: string) {
  if (key && key !== '—') {
    router.push({ path: '/chat', query: { session: key } })
  }
}

function toggleModelExpand(row: { raw: SessionRow; sessionKey: string }) {
  const key = row.sessionKey || ''
  if (expandedSessions.value.has(key)) {
    expandedSessions.value.delete(key)
  } else {
    expandedSessions.value.add(key)
  }
}

function loadData() {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  return refreshUsage()
}

function exportCsv() {
  const headers = [
    'session',
    'input_tokens',
    'output_tokens',
    'cache_read_tokens',
    'cache_write_tokens',
    'cost_usd',
    'cost_cny',
    'billed_cost_usd',
    'estimated_cost_usd',
    'cost_source',
    'missing_cost_entries',
    'cost_ephemeral',
    'model',
  ]
  const visibleRows = visibleSessions.value
  const rows = visibleRows.map(row => [
    rowVal(row, 'session', 'sessionKey', 'key') || '',
    rowVal(row, 'input_tokens', 'inputTokens') ?? '',
    rowVal(row, 'output_tokens', 'outputTokens') ?? '',
    rowVal(row, 'cache_read_tokens', 'cacheReadTokens') ?? '',
    rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') ?? '',
    rowVal(row, 'cost_usd', 'costUsd') != null ? Number(rowVal(row, 'cost_usd', 'costUsd')).toFixed(6) : '',
    rowVal(row, 'cost_usd', 'costUsd') != null ? (Number(rowVal(row, 'cost_usd', 'costUsd')) * CNY_RATE).toFixed(6) : '',
    rowVal(row, 'billed_cost_usd', 'billedCostUsd') != null ? Number(rowVal(row, 'billed_cost_usd', 'billedCostUsd')).toFixed(6) : '',
    rowVal(row, 'estimated_cost_usd', 'estimatedCostUsd') != null ? Number(rowVal(row, 'estimated_cost_usd', 'estimatedCostUsd')).toFixed(6) : '',
    costSource(row),
    rowVal(row, 'missing_cost_entries', 'missingCostEntries') ?? '',
    rowVal(row, 'cost_ephemeral', 'costEphemeral') ? 'true' : 'false',
    row.model || '',
  ])
  const csv = [headers, ...rows].map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n')
  const suffix = range.value === 'all' ? 'all' : `${range.value}d`
  download(`opensquilla-usage-${suffix}-cny${CNY_RATE}.csv`, 'text/csv', csv)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function rangeCutoffMs(r: string): number | null {
  if (r === 'all') return null
  return Date.now() - (Number(r) * 86400000)
}

function fmtCost(usd: number | null | undefined, opts?: { decimals?: number }): string {
  if (usd == null) return '—'
  const n = Number(usd)
  const decimals = (opts && opts.decimals != null) ? opts.decimals : 4
  if (currency.value === 'CNY') {
    return '¥' + (n * CNY_RATE).toFixed(decimals)
  }
  return '$' + n.toFixed(decimals)
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return '—'
  const v = Number(n)
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K'
  return String(v)
}

function rowVal(row: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] != null) return row[key]
  }
  return null
}

function numericRowVal(row: Record<string, unknown>, ...keys: string[]): number | null {
  const value = rowVal(row, ...keys)
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function sessionTimestamp(row: SessionRow): number | null {
  for (const key of ['endedAt', 'ended_at', 'updatedAt', 'updated_at', 'startedAt', 'started_at', 'createdAt', 'created_at']) {
    const value = numericRowVal(row, key)
    if (value != null) return value
  }
  return null
}

function sortVal(row: SessionRow, key: string): string | number {
  switch (key) {
    case 'session':
      return (rowVal(row, 'session', 'sessionKey', 'key') || '') as string
    case 'updated_at':
      return sessionTimestamp(row) || 0
    case 'input_tokens':
      return Number(rowVal(row, 'input_tokens', 'inputTokens') || 0)
    case 'output_tokens':
      return Number(rowVal(row, 'output_tokens', 'outputTokens') || 0)
    case 'cache_read_tokens':
      return Number(rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0)
    case 'cache_write_tokens':
      return Number(rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0)
    case 'cost_usd':
      return Number(rowVal(row, 'cost_usd', 'costUsd') || 0)
    default:
      return (rowVal(row, key) || '') as string
  }
}

function costSource(row: SessionRow | ModelBreakdownItem): string {
  return String(rowVal(row as Record<string, unknown>, 'cost_source', 'costSource') || 'none')
}

function costSourceClass(source: string): string {
  const known = ['provider_billed', 'provider_billed_prorated', 'opensquilla_estimate', 'mixed', 'unavailable', 'none']
  if (known.includes(source)) return source
  return 'none'
}

function costSourceLabel(row: SessionRow | ModelBreakdownItem): string {
  const source = costSource(row)
  const ephemeral = Boolean(rowVal(row as Record<string, unknown>, 'cost_ephemeral', 'costEphemeral'))
  if (ephemeral) return 'Ephemeral'
  switch (source) {
    case 'provider_billed': return 'Actual'
    case 'provider_billed_prorated': return 'Actual'
    case 'opensquilla_estimate': return 'Estimated'
    case 'mixed': return 'Mixed'
    case 'unavailable': return 'Unpriced'
    default: return 'None'
  }
}

function costSourceTooltip(row: SessionRow | ModelBreakdownItem): string {
  const source = costSource(row)
  const ephemeral = Boolean(rowVal(row as Record<string, unknown>, 'cost_ephemeral', 'costEphemeral'))
  if (ephemeral) return 'Ephemeral session — cost not yet persisted'
  switch (source) {
    case 'provider_billed': return 'Actual — cost billed by the provider'
    case 'provider_billed_prorated': return 'Total is real billed; per-model split is estimated.'
    case 'opensquilla_estimate': return 'Estimated — derived locally from token counts'
    case 'mixed': return 'Mixed — partial billing data, rest estimated'
    case 'unavailable': return 'Unpriced — no pricing table entry for this model'
    default: return 'No cost recorded'
  }
}

function costSourceClasses(row: SessionRow | ModelBreakdownItem): Record<string, boolean> {
  const source = costSource(row)
  const ephemeral = Boolean(rowVal(row as Record<string, unknown>, 'cost_ephemeral', 'costEphemeral'))
  return {
    [`usage-source--${costSourceClass(source)}`]: true,
    'usage-source--ephemeral': ephemeral,
  }
}

function costSourceClassesForBreakdown(m: BreakdownRow): Record<string, boolean> {
  return costSourceClasses(m as unknown as ModelBreakdownItem)
}

function costSourceLabelForBreakdown(m: BreakdownRow): string {
  return costSourceLabel(m as unknown as ModelBreakdownItem)
}

function costSourceTooltipForBreakdown(m: BreakdownRow): string {
  return costSourceTooltip(m as unknown as ModelBreakdownItem)
}

function sourceCompositionHint(rows: SessionRow[]): string {
  const counts: Record<string, number> = { Actual: 0, Estimated: 0, Mixed: 0, Unpriced: 0, Ephemeral: 0 }
  rows.forEach(row => {
    const label = costSourceLabel(row)
    if (counts[label] != null) counts[label] += 1
  })
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([label, n]) => `${label.toLowerCase()} ${n}`)
    .join(' · ')
}

function modelDisplayLabel(row: SessionRow): string {
  const bd = row.modelBreakdown
  if (Array.isArray(bd) && bd.length > 0) {
    return bd.length > 1 ? `auto · ${bd.length} models` : (bd[0].model || row.model || '—')
  }
  return row.model || '—'
}

function rowKey(row: SessionRow): string {
  return (rowVal(row, 'session', 'sessionKey', 'key') || '') as string
}

function rowBreakdown(row: SessionRow): BreakdownRow[] {
  const bd = row.modelBreakdown || []
  const totalCost = bd.reduce((acc, m) => acc + (Number(m.costUsd) || 0), 0)
  return bd.map(m => {
    const tokens = (Number(m.inputTokens) || 0) + (Number(m.outputTokens) || 0)
    const cost = Number(m.costUsd) || 0
    const share = totalCost > 0 ? (cost / totalCost) * 100 : 0
    const provider = (m.model || '').split('/')[0] || ''
    const name = (m.model || '').split('/').slice(1).join('/') || m.model || 'unknown'
    return { model: m.model || '', provider, name, tokens, cost, share }
  })
}

function rowBreakdownTotalTokens(row: SessionRow): number {
  const bd = row.modelBreakdown || []
  return bd.reduce((acc, m) => acc + (Number(m.inputTokens) || 0) + (Number(m.outputTokens) || 0), 0)
}

function rowBreakdownTotalCost(row: SessionRow): number {
  const bd = row.modelBreakdown || []
  return bd.reduce((acc, m) => acc + (Number(m.costUsd) || 0), 0)
}

function rowBreakdownAnyProrated(row: SessionRow): boolean {
  const bd = row.modelBreakdown || []
  return bd.some(m => {
    const src = String(m.costSource || m.cost_source || '')
    return src === 'provider_billed_prorated'
  })
}

function relTime(timestamp: number | string): string {
  const d = typeof timestamp === 'number' ? new Date(timestamp) : new Date(timestamp)
  if (isNaN(d.getTime())) return String(timestamp)

  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString()
}

function download(filename: string, mime: string, content: string) {
  downloadText(filename, mime, content)
}

  return {
    currency,
    sessions,
    sortCol,
    sortAsc,
    chartMode,
    range,
    lastStatus,
    usageLoading,
    usageError,
    expandedSessions,
    tableColumns,
    sortableCols,
    visibleSessions,
    undatedHiddenCount,
    rangeHiddenHint,
    usageTotals,
    totalTokensDisplay,
    tokensBreakdownParts,
    totalCostDisplay,
    costHintText,
    costHintTitle,
    sessionCountDisplay,
    avgCostDisplay,
    chartCaption,
    chartRows,
    modelCards,
    modelsMeta,
    sortedRows,
    sessionsMeta,
    setCurrency,
    setRange,
    setSort,
    openSession,
    toggleModelExpand,
    loadData,
    exportCsv,
    rangeCutoffMs,
    fmtCost,
    fmtNum,
    rowVal,
    numericRowVal,
    sessionTimestamp,
    sortVal,
    costSource,
    costSourceClass,
    costSourceLabel,
    costSourceTooltip,
    costSourceClasses,
    costSourceClassesForBreakdown,
    costSourceLabelForBreakdown,
    costSourceTooltipForBreakdown,
    sourceCompositionHint,
    modelDisplayLabel,
    rowKey,
    rowBreakdown,
    rowBreakdownTotalTokens,
    rowBreakdownTotalCost,
    rowBreakdownAnyProrated,
    relTime,
    download,
  }
}
