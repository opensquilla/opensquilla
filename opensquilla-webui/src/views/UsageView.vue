<template>
  <div class="usage-stage">
    <header class="usage-stage__header">
      <div class="usage-stage__title-block">
        <span class="usage-stage__eyebrow">Control &middot; Analytics</span>
        <h2 class="usage-stage__title">Usage</h2>
        <p class="usage-stage__subtitle">Tokens, cost, and per-model spend across every session.</p>
        <small class="usage-range-notice" aria-live="polite">{{ rangeHiddenHint }}</small>
      </div>
      <div class="usage-stage__actions mobile-action-strip">
        <div class="usage-currency mobile-action-strip__item" role="group" aria-label="Currency">
          <button
            class="usage-currency__btn"
            :class="{ 'is-active': currency === 'USD' }"
            title="US Dollar"
            @click="setCurrency('USD')"
          >$ USD</button>
          <button
            class="usage-currency__btn"
            :class="{ 'is-active': currency === 'CNY' }"
            title="Chinese Yuan"
            @click="setCurrency('CNY')"
          >¥ CNY</button>
        </div>
        <button class="btn btn--ghost mobile-action-strip__button" title="Download CSV" @click="exportCsv">
          <Icon name="download" :size="16" /><span class="mobile-action-strip__label">Export</span>
        </button>
        <button class="btn btn--ghost mobile-action-strip__button" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" /><span class="mobile-action-strip__label">Refresh</span>
        </button>
      </div>
    </header>

    <section class="stat-row" id="usage-metrics">
      <div class="stat stat--hero">
        <div class="stat-label">Total tokens</div>
        <div class="stat-value">{{ totalTokensDisplay }}</div>
        <div class="stat-hint" v-html="tokensBreakdownHtml" />
      </div>
      <div class="stat">
        <div class="stat-label">Total cost</div>
        <div class="stat-value mono">{{ totalCostDisplay }}</div>
        <div class="stat-hint" :title="costHintTitle">{{ costHintText }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Sessions</div>
        <div class="stat-value">{{ sessionCountDisplay }}</div>
        <div class="stat-hint">across all models</div>
      </div>
      <div class="stat">
        <div class="stat-label">Avg cost / session</div>
        <div class="stat-value mono">{{ avgCostDisplay }}</div>
        <div class="stat-hint">running average</div>
      </div>
    </section>

    <section class="usage-chart">
      <div class="usage-chart__head">
        <div class="usage-segs" role="tablist" aria-label="Chart metric">
          <button
            class="usage-seg"
            :class="{ 'is-active': chartMode === 'tokens' }"
            role="tab"
            @click="chartMode = 'tokens'"
          >Tokens</button>
          <button
            class="usage-seg"
            :class="{ 'is-active': chartMode === 'cost' }"
            role="tab"
            @click="chartMode = 'cost'"
          >Cost</button>
        </div>
        <div class="usage-range" role="tablist" aria-label="Date range">
          <button
            v-for="r in ['all', '7', '14', '30']"
            :key="r"
            class="usage-range__btn"
            :class="{ 'is-active': range === r }"
            role="tab"
            @click="setRange(r)"
          >{{ r === 'all' ? 'All' : r + 'd' }}</button>
        </div>
      </div>
      <div class="usage-chart__legend">
        <span class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--input" />Input</span>
        <span v-show="chartMode === 'tokens'" class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--output" />Output</span>
        <span class="usage-chart__legend-spacer" />
        <span class="usage-chart__caption">{{ chartCaption }}</span>
      </div>
      <div class="usage-bars">
        <template v-if="chartRows.length === 0">
          <div class="usage-bars__empty">
            <div class="usage-bars__empty-icon">
              <Icon name="usage" :size="36" />
            </div>
            <div>No data in the selected window.</div>
          </div>
        </template>
        <button
          v-for="(row, i) in chartRows"
          :key="i"
          class="usage-bar-row"
          type="button"
          :title="`Open ${row.sessionKey}`"
          :style="`--i:${i}`"
          @click="openSession(row.sessionKey)"
        >
          <span class="usage-bar-row__label">{{ row.label }}</span>
          <span class="usage-bar-row__track">
            <span class="usage-bar-row__fill usage-bar-row__fill--input" :style="`width:${row.inputPct.toFixed(1)}%`" />
            <span
              v-if="row.outputPct > 0"
              class="usage-bar-row__fill usage-bar-row__fill--output"
              :style="`width:${row.outputPct.toFixed(1)}%`"
            />
            <span class="usage-bar-row__cap" :style="`left:${Math.min(100, row.totalPct).toFixed(1)}%`" />
          </span>
          <span class="usage-bar-row__value usage-mono">{{ row.valueLabel }}</span>
        </button>
      </div>
    </section>

    <section class="usage-models">
      <div class="usage-section-head">
        <h3 class="usage-section-title">By model</h3>
        <span class="usage-section-meta">{{ modelsMeta }}</span>
      </div>
      <div class="usage-model-grid">
        <template v-if="modelCards.length === 0">
          <div class="usage-models__empty">No model usage yet.</div>
        </template>
        <article
          v-for="(m, i) in modelCards"
          :key="m.model"
          class="usage-model-card"
          :style="`--i:${i}`"
        >
          <header class="usage-model-card__head">
            <div class="usage-model-card__id">
              <span v-if="m.provider" class="usage-model-card__provider">{{ m.provider }}</span>
              <span class="usage-model-card__name" :title="m.model">{{ m.name }}</span>
            </div>
            <span class="usage-model-card__share" title="Share of total cost">{{ m.share.toFixed(1) }}%</span>
          </header>
          <div class="usage-model-card__share-bar">
            <span class="usage-model-card__share-fill" :style="`width:${m.share.toFixed(1)}%`" />
          </div>
          <dl class="usage-model-card__rows">
            <div><dt>Tokens</dt><dd class="usage-mono">{{ m.totalTokens.toLocaleString() }}</dd></div>
            <div><dt>Input</dt><dd class="usage-mono usage-dim">{{ m.inputTokens.toLocaleString() }}</dd></div>
            <div><dt>Output</dt><dd class="usage-mono usage-dim">{{ m.outputTokens.toLocaleString() }}</dd></div>
            <div v-if="m.cacheReadTokens > 0"><dt>Cache R</dt><dd class="usage-mono usage-dim">{{ m.cacheReadTokens.toLocaleString() }}</dd></div>
            <div v-if="m.cacheWriteTokens > 0"><dt>Cache W</dt><dd class="usage-mono usage-dim">{{ m.cacheWriteTokens.toLocaleString() }}</dd></div>
            <div><dt>Sessions</dt><dd>{{ m.sessions }}</dd></div>
            <div class="usage-model-card__cost-row"><dt>Cost</dt><dd class="usage-mono usage-cost">{{ fmtCost(m.costUsd) }}</dd></div>
          </dl>
        </article>
      </div>
    </section>

    <section class="usage-sessions">
      <div class="usage-section-head">
        <h3 class="usage-section-title">Sessions</h3>
        <span class="usage-section-meta">{{ sessionsMeta }}</span>
      </div>
      <div class="usage-table-wrap">
        <table class="usage-table">
          <thead>
            <tr>
              <th
                v-for="col in tableColumns"
                :key="col.key"
                :class="{ 'usage-th-sort': sortableCols.includes(col.key) }"
                @click="sortableCols.includes(col.key) ? setSort(col.key) : undefined"
              >
                {{ col.label }}
                <span v-if="sortCol === col.key" class="usage-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-if="sortedRows.length === 0">
              <tr>
                <td :colspan="tableColumns.length" class="usage-empty-row">
                  <div class="state">
                    <div class="state-icon">
                      <Icon name="usage" :size="36" />
                    </div>
                    <div class="state-title">No usage data yet</div>
                    <p class="state-text">Run a session and token spend will appear here automatically.</p>
                  </div>
                </td>
              </tr>
            </template>
            <template v-for="row in sortedRows" :key="rowKey(row.raw)">
              <tr>
                <td data-label="Session">
                  <a
                    v-if="row.sessionKey"
                    href="#"
                    class="usage-sess-link"
                    :title="`Open chat for ${row.sessionKey}`"
                    @click.prevent="openSession(row.sessionKey)"
                  >{{ row.sessionKey }}</a>
                  <span v-else>—</span>
                </td>
                <td data-label="Modified" class="usage-mono usage-dim">{{ row.modified }}</td>
                <td data-label="Input" class="usage-mono">{{ row.inputTokens != null ? row.inputTokens.toLocaleString() : '—' }}</td>
                <td data-label="Output" class="usage-mono">{{ row.outputTokens != null ? row.outputTokens.toLocaleString() : '—' }}</td>
                <td data-label="Cache R" class="usage-mono usage-dim">{{ row.cacheReadTokens != null ? row.cacheReadTokens.toLocaleString() : '—' }}</td>
                <td data-label="Cache W" class="usage-mono usage-dim">{{ row.cacheWriteTokens != null ? row.cacheWriteTokens.toLocaleString() : '—' }}</td>
                <td data-label="Cost" class="usage-mono usage-cost">{{ fmtCost(row.cost) }}</td>
                <td data-label="Source">
                  <span
                    class="usage-source"
                    :class="costSourceClasses(row.raw)"
                    :title="costSourceTooltip(row.raw)"
                  >{{ costSourceLabel(row.raw) }}</span>
                </td>
                <td data-label="Model">
                  <button
                    v-if="row.hasModelBreakdown"
                    class="usage-model-toggle"
                    :class="{ open: expandedSessions.has(row.sessionKey || '') }"
                    @click="toggleModelExpand(row)"
                  >
                    <span>{{ modelDisplayLabel(row.raw) }}</span><span class="usage-model-caret">▾</span>
                  </button>
                  <span v-else class="usage-model-text">{{ modelDisplayLabel(row.raw) }}</span>
                </td>
              </tr>
              <tr v-if="expandedSessions.has(row.sessionKey || '')" class="usage-expand-row">
                <td class="usage-expand-cell" :colspan="tableColumns.length">
                  <div class="usage-expand">
                    <div class="usage-expand__head">
                      <span class="usage-expand__connector" aria-hidden="true" />
                      <span class="usage-expand__eyebrow">Model breakdown</span>
                      <span class="usage-expand__count">{{ rowBreakdown(row.raw).length }} model{{ rowBreakdown(row.raw).length === 1 ? '' : 's' }}</span>
                      <span class="usage-expand__spacer" />
                      <span class="usage-expand__total">{{ rowBreakdownTotalTokens(row.raw).toLocaleString() }} tokens &middot; {{ fmtCost(rowBreakdownTotalCost(row.raw)) }}</span>
                    </div>
                    <div v-if="rowBreakdownAnyProrated(row.raw)" class="usage-expand__notice" role="note">
                      Per-model split is estimated; total is the actual billed amount.
                    </div>
                    <div class="usage-expand__list" role="table" aria-label="Model breakdown">
                      <div
                        v-for="(m, mi) in rowBreakdown(row.raw)"
                        :key="mi"
                        class="usage-expand__row"
                        :style="`--i:${mi}`"
                        role="row"
                      >
                        <div class="usage-expand__model" role="cell" :title="m.model">
                          <span v-if="m.provider" class="usage-expand__provider">{{ m.provider }}/</span><span class="usage-expand__name">{{ m.name }}</span>
                        </div>
                        <div class="usage-expand__share" role="cell">
                          <span class="usage-expand__share-track">
                            <span class="usage-expand__share-fill" :style="`width:${m.share.toFixed(2)}%`" />
                          </span>
                          <span class="usage-expand__share-pct">{{ m.share.toFixed(1) }}%</span>
                        </div>
                        <div class="usage-expand__tokens" role="cell">{{ m.tokens.toLocaleString() }}</div>
                        <div class="usage-expand__cost" role="cell">{{ fmtCost(m.cost) }}</div>
                        <div class="usage-expand__source" role="cell">
                          <span
                            class="usage-source"
                            :class="costSourceClassesForBreakdown(m)"
                            :title="costSourceTooltipForBreakdown(m)"
                          >{{ costSourceLabelForBreakdown(m) }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionRow {
  session?: string
  sessionKey?: string
  key?: string
  updated_at?: number | string
  updatedAt?: number | string
  endedAt?: number | string
  ended_at?: number | string
  startedAt?: number | string
  started_at?: number | string
  createdAt?: number | string
  created_at?: number | string
  input_tokens?: number | string
  inputTokens?: number | string
  output_tokens?: number | string
  outputTokens?: number | string
  cache_read_tokens?: number | string
  cacheReadTokens?: number | string
  cache_write_tokens?: number | string
  cacheWriteTokens?: number | string
  cost_usd?: number | string
  costUsd?: number | string
  cost_source?: string
  costSource?: string
  cost_ephemeral?: boolean
  costEphemeral?: boolean
  model?: string
  modelBreakdown?: ModelBreakdownItem[]
  [key: string]: unknown
}

interface ModelBreakdownItem {
  model?: string
  inputTokens?: number | string
  input_tokens?: number | string
  outputTokens?: number | string
  output_tokens?: number | string
  costUsd?: number | string
  cost_usd?: number | string
  costSource?: string
  cost_source?: string
  costEphemeral?: boolean
  cost_ephemeral?: boolean
}

interface UsageStatusData {
  sessions?: SessionRow[]
  totalSessions?: number
  totalTokens?: number
  totalCostUsd?: number
}

interface TableColumn {
  key: string
  label: string
}

interface ChartRow {
  sessionKey: string
  label: string
  inputPct: number
  outputPct: number
  totalPct: number
  valueLabel: string
}

interface ModelCard {
  model: string
  provider: string
  name: string
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheWriteTokens: number
  costUsd: number
  sessions: number
  share: number
  totalTokens: number
}

interface BreakdownRow {
  model: string
  provider: string
  name: string
  tokens: number
  cost: number
  share: number
  costSource?: string
  cost_source?: string
  costEphemeral?: boolean
  cost_ephemeral?: boolean
}

interface UsageTotals {
  input: number
  output: number
  cost: number
  cacheRead: number
  cacheWrite: number
  sessions: number
}

interface SortedRow {
  raw: SessionRow
  sessionKey: string
  modified: string
  inputTokens: number | null
  outputTokens: number | null
  cacheReadTokens: number | null
  cacheWriteTokens: number | null
  cost: number | null
  hasModelBreakdown: boolean
}

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

// ---------------------------------------------------------------------------
// Stores & Router
// ---------------------------------------------------------------------------

const router = useRouter()
const rpc = useRpcStore()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const currency = ref(localStorage.getItem('opensquilla-currency') || 'USD')
const sessions = ref<SessionRow[]>([])
const sortCol = ref('updated_at')
const sortAsc = ref(false)
const chartMode = ref<'tokens' | 'cost'>('tokens')
const range = ref(normalizeRange(localStorage.getItem('opensquilla-usage-range')))
const lastStatus = ref<UsageStatusData | null>(null)
const expandedSessions = ref<Set<string>>(new Set())

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

const usageTotals = computed((): UsageTotals => {
  return visibleSessions.value.reduce((acc: UsageTotals, row) => {
    acc.input += Number(rowVal(row, 'input_tokens', 'inputTokens') || 0)
    acc.output += Number(rowVal(row, 'output_tokens', 'outputTokens') || 0)
    acc.cost += Number(rowVal(row, 'cost_usd', 'costUsd') || 0)
    acc.cacheRead += Number(rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0)
    acc.cacheWrite += Number(rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0)
    return acc
  }, { input: 0, output: 0, cost: 0, cacheRead: 0, cacheWrite: 0, sessions: visibleSessions.value.length })
})

const totalTokensDisplay = computed(() => {
  const t = usageTotals.value
  const total = t.input + t.output
  return total != null ? total.toLocaleString() : '—'
})

const tokensBreakdownHtml = computed(() => {
  const t = usageTotals.value
  const parts: string[] = []
  if (t.input != null) parts.push(`<span><em>In</em> ${t.input.toLocaleString()}</span>`)
  if (t.output != null) parts.push(`<span><em>Out</em> ${t.output.toLocaleString()}</span>`)
  if (t.cacheRead) parts.push(`<span><em>Cache R</em> ${t.cacheRead.toLocaleString()}</span>`)
  if (t.cacheWrite) parts.push(`<span><em>Cache W</em> ${t.cacheWrite.toLocaleString()}</span>`)
  return parts.join('<span>·</span>')
})

const totalCostDisplay = computed(() => fmtCost(usageTotals.value.cost, { decimals: 4 }))

const costHintText = computed(() => {
  const visibleRows = visibleSessions.value
  const sourceHint = sourceCompositionHint(visibleRows)
  let currencyHint = ''
  const totalCostUsd = usageTotals.value.cost
  if (currency.value === 'CNY') {
    currencyHint = `≈ ${('$' + Number(totalCostUsd).toFixed(4))} USD`
  } else if (currency.value === 'USD') {
    currencyHint = `≈ ¥${(Number(totalCostUsd) * CNY_RATE).toFixed(4)} CNY`
  }
  return [currencyHint, sourceHint].filter(Boolean).join(' · ')
})

const costHintTitle = computed(() => {
  return `CNY values use baked-in rate ${CNY_RATE}. Verify against current FX for accounting use.`
})

const sessionCountDisplay = computed(() => {
  const n = usageTotals.value.sessions
  return n != null ? String(n) : '—'
})

const avgCostDisplay = computed(() => {
  const t = usageTotals.value
  const avg = t.sessions > 0 ? t.cost / t.sessions : null
  return avg != null ? fmtCost(avg, { decimals: 4 }) : '—'
})

const chartCaption = computed(() => {
  const pool = visibleSessions.value.filter(r => {
    const inp = Number(rowVal(r, 'input_tokens', 'inputTokens') || 0)
    const out = Number(rowVal(r, 'output_tokens', 'outputTokens') || 0)
    return (inp + out) > 0
  })
  const shown = Math.min(20, pool.length)
  const suffix = pool.length > shown ? ` · showing ${shown} of ${pool.length}` : ''
  return (chartMode.value === 'cost' ? 'Top sessions by cost' : 'Top sessions by total tokens') + suffix
})

const chartRows = computed((): ChartRow[] => {
  const visibleRows = visibleSessions.value
  const sorted = [...visibleRows].filter(r => {
    const inp = Number(rowVal(r, 'input_tokens', 'inputTokens') || 0)
    const out = Number(rowVal(r, 'output_tokens', 'outputTokens') || 0)
    return (inp + out) > 0
  }).sort((a, b) => {
    if (chartMode.value === 'cost') {
      return (Number(rowVal(b, 'cost_usd', 'costUsd') || 0)) - (Number(rowVal(a, 'cost_usd', 'costUsd') || 0))
    }
    const totalA = (Number(rowVal(a, 'input_tokens', 'inputTokens') || 0)) + (Number(rowVal(a, 'output_tokens', 'outputTokens') || 0))
    const totalB = (Number(rowVal(b, 'input_tokens', 'inputTokens') || 0)) + (Number(rowVal(b, 'output_tokens', 'outputTokens') || 0))
    return totalB - totalA
  }).slice(0, 20)

  if (sorted.length === 0) return []

  let maxVal = 0
  if (chartMode.value === 'cost') {
    maxVal = Math.max(...sorted.map(r => Number(rowVal(r, 'cost_usd', 'costUsd') || 0)))
  } else {
    maxVal = Math.max(...sorted.map(r =>
      (Number(rowVal(r, 'input_tokens', 'inputTokens') || 0)) + (Number(rowVal(r, 'output_tokens', 'outputTokens') || 0))
    ))
  }
  if (maxVal === 0) maxVal = 1

  return sorted.map(row => {
    const fullLabel = (rowVal(row, 'session', 'sessionKey', 'key') || '—') as string
    const label = fullLabel.length > 26 ? fullLabel.slice(0, 24) + '…' : fullLabel
    let valueLabel: string, inputPct: number, outputPct: number, totalPct: number
    if (chartMode.value === 'cost') {
      const cost = Number(rowVal(row, 'cost_usd', 'costUsd') || 0)
      const pct = (cost / maxVal) * 100
      inputPct = pct
      outputPct = 0
      totalPct = pct
      valueLabel = fmtCost(cost)
    } else {
      const inp = Number(rowVal(row, 'input_tokens', 'inputTokens') || 0)
      const out = Number(rowVal(row, 'output_tokens', 'outputTokens') || 0)
      const total = inp + out
      inputPct = (inp / maxVal) * 100
      outputPct = (out / maxVal) * 100
      totalPct = inputPct + outputPct
      valueLabel = fmtNum(total)
    }
    return {
      sessionKey: fullLabel,
      label,
      inputPct,
      outputPct,
      totalPct,
      valueLabel,
    }
  })
})

const modelCards = computed((): ModelCard[] => {
  const visibleRows = visibleSessions.value
  const map: Record<string, ModelCard> = {}

  visibleRows.forEach(row => {
    const breakdown = Array.isArray(row.modelBreakdown) ? row.modelBreakdown : []
    const items = breakdown.length > 0 ? breakdown : [{
      model: row.model || 'unknown',
      inputTokens: Number(rowVal(row, 'input_tokens', 'inputTokens') || 0),
      outputTokens: Number(rowVal(row, 'output_tokens', 'outputTokens') || 0),
      cacheReadTokens: Number(rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0),
      cacheWriteTokens: Number(rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0),
      costUsd: Number(rowVal(row, 'cost_usd', 'costUsd') || 0),
    }]
    const modelsSeenInSession = new Set<string>()
    items.forEach(item => {
      const model = item.model || row.model || 'unknown'
      if (!map[model]) {
        map[model] = {
          model,
          provider: '',
          name: '',
          inputTokens: 0,
          outputTokens: 0,
          cacheReadTokens: 0,
          cacheWriteTokens: 0,
          costUsd: 0,
          sessions: 0,
          share: 0,
          totalTokens: 0,
        }
      }
      map[model].inputTokens += Number(rowVal(item, 'input_tokens', 'inputTokens') || 0)
      map[model].outputTokens += Number(rowVal(item, 'output_tokens', 'outputTokens') || 0)
      map[model].cacheReadTokens += Number(rowVal(item, 'cache_read_tokens', 'cacheReadTokens') || 0)
      map[model].cacheWriteTokens += Number(rowVal(item, 'cache_write_tokens', 'cacheWriteTokens') || 0)
      map[model].costUsd += Number(rowVal(item, 'cost_usd', 'costUsd') || 0)
      if (!modelsSeenInSession.has(model)) {
        map[model].sessions += 1
        modelsSeenInSession.add(model)
      }
    })
  })

  const models = Object.values(map).sort((a, b) => b.costUsd - a.costUsd)
  const totalCost = models.reduce((acc, m) => acc + m.costUsd, 0)

  return models.map(m => {
    const provider = (m.model || '').split('/')[0] || ''
    const name = (m.model || '').split('/').slice(1).join('/') || m.model || 'unknown'
    return {
      ...m,
      provider,
      name,
      share: totalCost > 0 ? (m.costUsd / totalCost) * 100 : 0,
      totalTokens: m.inputTokens + m.outputTokens,
    }
  })
})

const modelsMeta = computed(() => {
  const n = modelCards.value.length
  return `${n} model${n === 1 ? '' : 's'}`
})

const sortedRows = computed((): SortedRow[] => {
  const visibleRows = visibleSessions.value
  const sorted = [...visibleRows].sort((a, b) => {
    let va = sortVal(a, sortCol.value)
    let vb = sortVal(b, sortCol.value)
    if (typeof va === 'string') va = va.toLowerCase()
    if (typeof vb === 'string') vb = vb.toLowerCase()
    const cmp = va < vb ? -1 : va > vb ? 1 : 0
    return sortAsc.value ? cmp : -cmp
  })

  return sorted.map(row => {
    const sessionKey = (rowVal(row, 'session', 'sessionKey', 'key') || '') as string
    const cost = rowVal(row, 'cost_usd', 'costUsd')
    const timestamp = sessionTimestamp(row)
    const modified = timestamp != null ? relTime(timestamp) : '—'
    const bd = row.modelBreakdown
    const hasModelBreakdown = !!(bd && bd.length > 1)

    return {
      raw: row,
      sessionKey,
      modified,
      inputTokens: numericRowVal(row, 'input_tokens', 'inputTokens'),
      outputTokens: numericRowVal(row, 'output_tokens', 'outputTokens'),
      cacheReadTokens: numericRowVal(row, 'cache_read_tokens', 'cacheReadTokens'),
      cacheWriteTokens: numericRowVal(row, 'cache_write_tokens', 'cacheWriteTokens'),
      cost: cost != null ? Number(cost) : null,
      hasModelBreakdown,
    }
  })
})

const sessionsMeta = computed(() => {
  const n = sortedRows.value.length
  return [`${n} session${n === 1 ? '' : 's'}`, rangeHiddenHint.value].filter(Boolean).join(' · ')
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  autoRefreshId = setInterval(loadData, 60000)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  if (autoRefreshId) clearInterval(autoRefreshId)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

function onVisibilityChange() {
  if (document.visibilityState === 'visible') loadData()
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function setCurrency(cur: string) {
  if (cur !== 'USD' && cur !== 'CNY') return
  currency.value = cur
  localStorage.setItem('opensquilla-currency', currency.value)
}

function setRange(r: string) {
  range.value = normalizeRange(r)
  localStorage.setItem('opensquilla-usage-range', range.value)
}

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

async function loadData() {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  try {
    await rpc.waitForConnection()
  } catch {
    return
  }

  rpc.call<UsageStatusData>('usage.status').then(status => {
    lastStatus.value = status
    sessions.value = status.sessions || []
  }).catch(err => {
    console.warn('Failed to load usage:', err.message)
  })
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

function normalizeRange(r: string | null): string {
  const value = String(r || '7')
  return ['all', '7', '14', '30'].includes(value) ? value : '7'
}

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
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.usage-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
  max-width: none;
  position: relative;
}

.usage-stage__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding-top: var(--sp-3);
}
.usage-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.usage-stage__eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.usage-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  position: relative;
  margin: 0;
}
.usage-stage__title::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 36px;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
}
.usage-stage__subtitle {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  margin: var(--sp-3) 0 0;
  max-width: 60ch;
}
.usage-range-notice {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  margin-top: 4px;
  min-height: 1.2em;
}
.usage-stage__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

/* Currency toggle */
.usage-currency {
  display: inline-flex;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.usage-currency__btn {
  background: transparent;
  border: 0;
  padding: 6px 12px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.usage-currency__btn.is-active {
  background: var(--accent);
  color: #fff;
}

/* Stat row */
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--sp-3);
}
.stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat--hero {
  position: relative;
}
.stat--hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 0% 0%, color-mix(in srgb, var(--accent) 10%, transparent), transparent 60%);
  pointer-events: none;
  border-radius: inherit;
}
.stat-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.stat-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.18;
  font-variant-numeric: tabular-nums;
}
.stat-value.mono {
  font-family: var(--font-mono);
  font-size: 1.5rem;
}
.stat-hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  margin-top: 2px;
}
.stat-hint :deep(em) {
  color: var(--text-dim);
  font-style: normal;
  margin-right: 4px;
}

/* Chart */
.usage-chart {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.usage-chart__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.usage-segs {
  display: inline-flex;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.usage-seg {
  background: transparent;
  border: 0;
  padding: 6px 14px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.usage-seg.is-active {
  background: var(--accent);
  color: #fff;
}
.usage-range {
  display: inline-flex;
  gap: 4px;
}
.usage-range__btn {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px 10px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition), border-color var(--transition);
}
.usage-range__btn.is-active {
  background: var(--bg-elevated);
  border-color: var(--accent);
  color: var(--accent);
}
.usage-chart__legend {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-muted);
  flex-wrap: wrap;
}
.usage-chart__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.usage-chart__swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
}
.usage-chart__swatch--input {
  background: var(--accent);
}
.usage-chart__swatch--output {
  background: color-mix(in srgb, var(--accent) 60%, var(--ok));
}
.usage-chart__legend-spacer {
  flex: 1;
}
.usage-chart__caption {
  font-style: italic;
  color: var(--text-dim);
}

/* Bars */
.usage-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.usage-bars__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-6);
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.usage-bars__empty-icon {
  color: var(--text-dim);
}
.usage-bar-row {
  display: grid;
  grid-template-columns: minmax(0, 180px) 1fr auto;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  transition: opacity var(--transition);
  animation: usage-fade-in 300ms ease both;
  animation-delay: calc(var(--i) * 30ms);
}
.usage-bar-row:hover {
  opacity: 0.85;
}
.usage-bar-row__label {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
  padding-right: 4px;
}
.usage-bar-row__track {
  position: relative;
  height: 18px;
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.usage-bar-row__fill {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  border-radius: var(--radius-sm);
}
.usage-bar-row__fill--input {
  background: var(--accent);
}
.usage-bar-row__fill--output {
  background: color-mix(in srgb, var(--accent) 60%, var(--ok));
}
.usage-bar-row__cap {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--text);
  opacity: 0.3;
}
.usage-bar-row__value {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  min-width: 60px;
  text-align: right;
}

/* Models section */
.usage-models,
.usage-sessions {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.usage-section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--sp-2);
}
.usage-section-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  margin: 0;
}
.usage-section-meta {
  font-size: var(--fs-xs);
  color: var(--text-dim);
}

/* Model grid */
.usage-model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--sp-3);
}
.usage-models__empty {
  padding: var(--sp-5);
  text-align: center;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.usage-model-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  animation: usage-fade-in 300ms ease both;
  animation-delay: calc(var(--i) * 40ms);
}
.usage-model-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
}
.usage-model-card__id {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}
.usage-model-card__provider {
  font-size: var(--fs-xs);
  color: var(--text-dim);
}
.usage-model-card__name {
  font-weight: 600;
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.usage-model-card__share {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.usage-model-card__share-bar {
  height: 4px;
  background: var(--bg-elevated);
  border-radius: 2px;
  overflow: hidden;
}
.usage-model-card__share-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 400ms ease;
}
.usage-model-card__rows {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin: 0;
  font-size: var(--fs-xs);
}
.usage-model-card__rows > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 4px;
}
.usage-model-card__rows dt {
  color: var(--text-dim);
  font-weight: 500;
}
.usage-model-card__rows dd {
  margin: 0;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.usage-model-card__cost-row {
  grid-column: 1 / -1;
  border-top: 1px solid var(--border);
  padding-top: 4px;
  margin-top: 2px;
}

/* Table */
.usage-table-wrap {
  overflow-x: auto;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.usage-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}
.usage-table th {
  text-align: left;
  padding: 10px 12px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.usage-table td {
  padding: 10px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  vertical-align: middle;
}
.usage-table tr:last-child td {
  border-bottom: 0;
}
.usage-th-sort {
  cursor: pointer;
  user-select: none;
  transition: color var(--transition);
}
.usage-th-sort:hover {
  color: var(--accent);
}
.usage-table__arrow {
  margin-left: 4px;
  color: var(--accent);
}
.usage-empty-row {
  text-align: center;
  padding: var(--sp-6);
}
.usage-sess-link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}
.usage-sess-link:hover {
  text-decoration: underline;
}
.usage-mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.usage-dim {
  color: var(--text-dim);
}
.usage-cost {
  font-weight: 600;
}

/* Model toggle in table */
.usage-model-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 0;
  padding: 0;
  cursor: pointer;
  font: inherit;
  color: var(--accent);
}
.usage-model-toggle:hover {
  text-decoration: underline;
}
.usage-model-caret {
  font-size: 10px;
  transition: transform 200ms ease;
}
.usage-model-toggle.open .usage-model-caret {
  transform: rotate(180deg);
}
.usage-model-text {
  color: var(--text-muted);
}

/* Expand row */
.usage-expand-row {
  background: var(--bg-elevated);
}
.usage-expand-cell {
  padding: 0 !important;
}
.usage-expand {
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.usage-expand__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
}
.usage-expand__connector {
  width: 2px;
  height: 16px;
  background: var(--accent);
  border-radius: 1px;
}
.usage-expand__eyebrow {
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.usage-expand__count {
  color: var(--text-muted);
}
.usage-expand__spacer {
  flex: 1;
}
.usage-expand__total {
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.usage-expand__notice {
  font-size: var(--fs-xs);
  color: var(--warn);
  padding: 4px 8px;
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border-radius: var(--radius-sm);
}
.usage-expand__list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.usage-expand__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px 80px 80px 100px;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  animation: usage-fade-in 200ms ease both;
  animation-delay: calc(var(--i) * 30ms);
}
.usage-expand__model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.usage-expand__provider {
  color: var(--text-dim);
}
.usage-expand__share {
  display: flex;
  align-items: center;
  gap: 6px;
}
.usage-expand__share-track {
  flex: 1;
  height: 4px;
  background: var(--bg-elevated);
  border-radius: 2px;
  overflow: hidden;
}
.usage-expand__share-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}
.usage-expand__share-pct {
  font-family: var(--font-mono);
  color: var(--text-dim);
  min-width: 36px;
  text-align: right;
}
.usage-expand__tokens,
.usage-expand__cost {
  font-family: var(--font-mono);
  text-align: right;
}

/* Cost source badges */
.usage-source {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 10.5px;
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-muted);
}
.usage-source--provider_billed {
  border-color: color-mix(in srgb, var(--ok) 50%, var(--border));
  color: var(--ok);
}
.usage-source--provider_billed_prorated {
  border-style: dashed;
  border-color: color-mix(in srgb, var(--ok) 50%, var(--border));
  color: var(--ok);
}
.usage-source--opensquilla_estimate {
  border-color: color-mix(in srgb, var(--warn) 50%, var(--border));
  color: var(--warn);
}
.usage-source--mixed {
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
  color: var(--accent);
}
.usage-source--unavailable {
  border-color: color-mix(in srgb, var(--danger) 50%, var(--border));
  color: var(--danger);
}
.usage-source--ephemeral {
  opacity: 0.7;
  font-style: italic;
}

/* Empty state */
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-5);
  color: var(--text-muted);
}
.state-icon {
  color: var(--text-dim);
}
.state-title {
  font-weight: 600;
  color: var(--text);
}
.state-text {
  margin: 0;
  font-size: var(--fs-sm);
}

/* Animations */
@keyframes usage-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Responsive */
@media (max-width: 720px) {
  .usage-stage__header {
    flex-direction: column;
    align-items: stretch;
  }
  .usage-stage__actions {
    width: 100%;
  }
  .usage-bar-row {
    grid-template-columns: minmax(0, 100px) 1fr auto;
  }
  .usage-expand__row {
    grid-template-columns: 1fr 80px;
    gap: 4px;
  }
  .usage-expand__share,
  .usage-expand__tokens,
  .usage-expand__cost,
  .usage-expand__source {
    display: none;
  }
}
</style>
