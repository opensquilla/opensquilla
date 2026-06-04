<template>
  <div class="sess-stage control-stage">
    <header class="sess-stage__header control-stage__header">
      <div class="sess-stage__title-block control-stage__title-block">
        <h2 class="sess-stage__title control-stage__title">Sessions</h2>
        <p class="sess-stage__subtitle control-stage__subtitle">
          Session history, current task activity, and agent runs — open one to chat, or clean up old state.
        </p>
      </div>
      <div class="sess-stage__actions control-stage__actions">
        <div class="sess-search-wrap">
          <span class="sess-search-icon">
            <Icon name="search" :size="14" />
          </span>
          <input
            v-model="searchInput"
            type="text"
            class="sess-search-input"
            placeholder="Search sessions…"
            autocomplete="off"
            @input="onSearchInput"
          />
        </div>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <section class="stat-row control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 3">
      <div class="stat stat--hero control-stat control-stat--hero">
        <div class="stat-label control-stat__label">Total sessions</div>
        <div class="stat-value control-stat__value">{{ totalSessions }}</div>
        <div class="stat-hint control-stat__hint">
          {{ lifecycleOpen }} open &middot; {{ doneCount }} completed &middot; {{ failedOrTimedOut }} failed/timed out &middot; {{ abortedCount }} aborted
        </div>
      </div>
      <div class="stat control-stat" title="Sessions with queued or running tasks">
        <div class="stat-label control-stat__label">Executing</div>
        <div class="stat-value control-stat__value">
          {{ activeRuns }}<span v-if="activeRuns > 0" class="dot ok"></span>
        </div>
        <div class="stat-hint control-stat__hint">{{ activeRuns ? 'tasks queued/running' : 'none executing' }}</div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">Messages</div>
        <div class="stat-value mono control-stat__value control-stat__value--mono">{{ totalMessages.toLocaleString() }}</div>
        <div class="stat-hint control-stat__hint">{{ distinctAgents.size }} agent{{ distinctAgents.size === 1 ? '' : 's' }} &middot; across all sessions</div>
      </div>
    </section>

    <div v-show="selected.size > 0" class="sess-bulk-bar is-on">
      <span class="sess-bulk-bar__count"><strong>{{ selected.size }}</strong> selected</span>
      <button class="sess-iconbtn sess-iconbtn--ghost" @click="clearSelection">Clear</button>
      <span class="sess-bulk-bar__spacer"></span>
      <button class="sess-iconbtn sess-iconbtn--danger" @click="bulkDelete">
        <Icon name="trash" :size="14" />
        <span>Delete selected</span>
      </button>
    </div>

    <section class="sess-list">
      <div class="sess-list__head">
        <h3 class="sess-list__title">
          <template v-if="searchVal">Matching sessions <span class="sess-list__count">{{ filtered.length }} of {{ allSessions.length }}</span></template>
          <template v-else>All sessions <span class="sess-list__count">{{ allSessions.length }}</span></template>
        </h3>
        <div class="sess-list__controls">
          <label class="sess-page-size">
            <span>Show</span>
            <select v-model.number="pageSize" @change="page = 0">
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </label>
        </div>
      </div>

      <div v-if="slice.length === 0 && allSessions.length === 0" class="sess-table-wrap">
        <div class="sess-empty">
          <div class="sess-empty__art" aria-hidden="true">
            <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <radialGradient id="sg" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stop-color="rgba(240,160,48,0.18)"/>
                  <stop offset="60%" stop-color="rgba(240,160,48,0.04)"/>
                  <stop offset="100%" stop-color="rgba(240,160,48,0)"/>
                </radialGradient>
              </defs>
              <circle cx="60" cy="60" r="58" fill="url(#sg)"/>
              <g stroke="currentColor" stroke-width="1.4" fill="none" opacity="0.55">
                <rect x="22" y="34" width="50" height="38" rx="6"/>
                <line x1="32" y1="46" x2="62" y2="46"/>
                <line x1="32" y1="54" x2="56" y2="54"/>
                <line x1="32" y1="62" x2="50" y2="62"/>
              </g>
              <g stroke="var(--accent)" stroke-width="1.6" fill="none">
                <rect x="48" y="50" width="50" height="38" rx="6"/>
                <line x1="58" y1="62" x2="88" y2="62"/>
                <line x1="58" y1="70" x2="82" y2="70"/>
                <line x1="58" y1="78" x2="76" y2="78"/>
              </g>
              <circle cx="98" cy="50" r="4" fill="var(--accent)" class="sess-empty__pulse"/>
            </svg>
          </div>
          <div class="sess-empty__title">No sessions yet.</div>
          <p class="sess-empty__msg">
            Sessions appear here as soon as you chat with an agent or schedule a cron job.<br/>
            Start chats from the sidebar, or configure agents first.
          </p>
          <button class="btn btn--primary sess-empty__cta" @click="goToAgents">
            <Icon name="agents" :size="16" />
            <span>Open Agents</span>
          </button>
        </div>
      </div>

      <div v-else-if="slice.length === 0" class="sess-table-wrap">
        <div class="state">
          <div class="state-icon">
            <Icon name="search" :size="36" />
          </div>
          <div class="state-title">No matches</div>
          <p class="state-text">No sessions match your search. Try a different query, or clear it to see everything.</p>
        </div>
      </div>

      <div v-else class="sess-table-wrap">
        <table class="sess-table">
          <thead>
            <tr>
              <th class="sess-table__cell--check">
                <label class="sess-check">
                  <input
                    type="checkbox"
                    :checked="allOnPageSelected"
                    @change="toggleSelectAll"
                  />
                  <span></span>
                </label>
              </th>
              <th
                class="sess-th-sort"
                :class="{ 'is-active': sortCol === 'title' }"
                @click="setSort('title')"
              >
                Session
                <span v-if="sortCol === 'title'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
              <th>Type</th>
              <th>Agent</th>
              <th>Status</th>
              <th
                class="sess-th-sort"
                :class="{ 'is-active': sortCol === 'messageCount' }"
                @click="setSort('messageCount')"
              >
                Messages
                <span v-if="sortCol === 'messageCount'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
              <th
                class="sess-th-sort"
                :class="{ 'is-active': sortCol === 'updatedAt' }"
                @click="setSort('updatedAt')"
              >
                Modified
                <span v-if="sortCol === 'updatedAt'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
              <th class="sess-table__cell--actions"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in slice"
              :key="row.key"
              :class="{ 'is-selected': selected.has(row.key) }"
            >
              <td class="sess-table__cell--check">
                <label class="sess-check">
                  <input
                    type="checkbox"
                    :checked="selected.has(row.key)"
                    @change="toggleRow(row.key)"
                  />
                  <span></span>
                </label>
              </td>
              <td class="sess-table__cell--key">
                <div class="sess-table__key-content">
                  <span
                    class="dot"
                    :class="sessionStatusClass(sessionVisualStatus(row))"
                    :title="sessionStatusLabel(sessionVisualStatus(row))"
                  ></span>
                  <button
                    type="button"
                    class="sess-key-link"
                    :title="'Open chat: ' + row.key"
                    @click="openChat(row.key)"
                  >
                    {{ row.title }}
                  </button>
                  <div class="sess-key__sub">
                    <span v-if="row.subtitle" class="sess-key__subtitle">{{ row.subtitle }}</span>
                    <span v-else class="sess-key__subtitle sess-key__subtitle--gap">Missing subtitle</span>
                    <code class="sess-key__debug" title="Debug session key">{{ row.key }}</code>
                  </div>
                  <div class="sess-key__badges">
                    <span class="sess-group-badge">{{ row.groupLabel }}</span>
                    <span v-if="row.contractGaps.length" class="chip chip-warn sess-gap-chip" :title="contractGapTitle(row)">Contract gap</span>
                  </div>
                </div>
              </td>
              <td>
                <div class="sess-type-stack">
                  <span :class="['sess-type-chip', `sess-type-chip--${row.sessionKind}`]">{{ sessionKindLabel(row.sessionKind) }}</span>
                  <span class="sess-type-meta">{{ surfaceLabel(row) }}</span>
                </div>
              </td>
              <td>
                <div class="sess-agent-stack">
                  <span class="sess-agent-badge">{{ agentDisplayName(row) }}</span>
                  <span class="sess-agent-id">{{ row.effectiveAgentId }}</span>
                </div>
              </td>
              <td>
                <div class="sess-status-stack">
                  <span :class="['chip', sessionStatusChip(sessionVisualStatus(row))]">
                    {{ sessionStatusLabel(sessionVisualStatus(row)) }}
                  </span>
                  <span v-if="runStatusLabel(row.runStatus)" :class="['chip', runStatusChipClass(row.runStatus), 'sess-run-chip']">
                    {{ runStatusLabel(row.runStatus) }}
                  </span>
                </div>
              </td>
              <td class="sess-mono">
                {{ row.messageCount != null ? Number(row.messageCount).toLocaleString() : '—' }}
              </td>
              <td class="sess-mono sess-dim">{{ row.updatedAt ? relTime(row.updatedAt) : '—' }}</td>
              <td class="sess-table__cell--actions">
                <button class="sess-iconbtn" :title="'Open chat: ' + row.key" @click="openChat(row.key)">
                  <Icon name="chat" :size="14" />
                </button>
                <button class="sess-iconbtn" title="Copy session key" @click="copyKey(row.key)">
                  <Icon name="copy" :size="14" />
                </button>
                <button class="sess-iconbtn sess-iconbtn--danger" title="Delete" @click="deleteSession(row.key)">
                  <Icon name="trash" :size="14" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="filtered.length > 0" class="sess-pagination">
        <button
          class="sess-page-btn"
          :disabled="page === 0"
          title="Previous page"
          @click="page--"
        >
          ‹
        </button>
        <span class="sess-page-info">
          {{ page + 1 }} / {{ totalPages }} <span class="sess-dim">· {{ filtered.length }} total</span>
        </span>
        <button
          class="sess-page-btn"
          :disabled="page >= totalPages - 1"
          title="Next page"
          @click="page++"
        >
          ›
        </button>
      </div>
    </section>

  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import { useSessionsData } from '@/composables/sessions/useSessionsData'
import { useSessionTableState } from '@/composables/sessions/useSessionTableState'
import { copyTextWithFallback } from '@/utils/browser'
import type { SessionItem } from '@/composables/useSessions'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DeleteResponse {
  deleted?: string[]
  errors?: (string | { message?: string; error?: string; reason?: string })[]
}

// ---------------------------------------------------------------------------
// Stores & Router
// ---------------------------------------------------------------------------

const router = useRouter()
const rpc = useRpcStore()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const {
  allSessions,
  filtered,
  sortCol,
  sortAsc,
  page,
  pageSize,
  selected,
  searchVal,
  searchInput,
  totalPages,
  slice,
  allOnPageSelected,
  totalSessions,
  lifecycleOpen,
  activeRuns,
  doneCount,
  failedOrTimedOut,
  abortedCount,
  totalMessages,
  distinctAgents,
  setSessions,
  onSearchInput,
  setSort,
  toggleRow,
  toggleSelectAll,
  clearSelection,
} = useSessionTableState()

const { agentsById, loadData } = useSessionsData(setSessions)

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function openChat(key: string) {
  router.push({ path: '/chat', query: { session: key } })
}

function goToAgents() {
  router.push('/agents')
}

async function copyKey(key: string) {
  try {
    await copyTextWithFallback(key)
    console.warn('Copied session key')
  } catch {
    console.warn('Copy failed')
  }
}

function deleteSession(key: string) {
  if (!confirm(`Delete session "${key}"? This cannot be undone.\n\nThe transcript will not be flushed to disk; use /reset first if you want a backup.`)) {
    return
  }
  doDelete([key])
}

function bulkDelete() {
  const keys = Array.from(selected.value)
  if (keys.length === 0) return
  if (!confirm(`Delete ${keys.length} session${keys.length === 1 ? '' : 's'}? This cannot be undone.\n\nThe transcript will not be flushed to disk; use /reset first if you want a backup.`)) {
    return
  }
  doDelete(keys)
}

async function doDelete(keys: string[]) {
  try {
    const res = await rpc.call<DeleteResponse>('sessions.delete', { keys })
    const errCount = (res?.errors?.length) || 0
    const okCount = res?.deleted?.length ?? (keys.length - errCount)
    if (errCount > 0) {
      console.warn(`Deleted ${okCount}, ${errCount} failed`)
    } else {
      console.warn(`Deleted ${okCount} session${okCount === 1 ? '' : 's'}`)
    }
  } catch (err) {
    console.warn('Bulk delete failed: ' + (err instanceof Error ? err.message : String(err)))
  }
  selected.value.clear()
  loadData()
}

function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: 'Task queued',
    running: 'Task running',
    interrupted: 'Interrupted',
    failed: 'Last task failed',
    timeout: 'Last task timed out',
    cancelled: 'Last task cancelled',
  }
  return labels[status] || ''
}

function runStatusChipClass(status: string): string {
  const classes: Record<string, string> = {
    queued: 'chip-warn',
    running: 'chip-ok',
    interrupted: 'chip-warn',
    failed: 'chip-danger',
    timeout: 'chip-warn',
  }
  return classes[status] || ''
}

function sessionVisualStatus(row: SessionItem): string {
  return row.visualStatus
}

function sessionKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    chat: 'Chat',
    channel: 'Channel',
    task: 'Task',
    cron: 'Cron',
    system: 'System',
    unknown: 'Unknown',
  }
  return labels[kind] || kind
}

function surfaceLabel(row: SessionItem): string {
  const parts = [row.surface, row.conversationKind]
    .filter(value => value && value !== 'unknown')
    .map(value => value.charAt(0).toUpperCase() + value.slice(1))
  if (row.threadLabel) parts.push(row.threadLabel)
  return parts.join(' · ') || 'Unknown'
}

function agentDisplayName(row: SessionItem): string {
  const agentId = row.effectiveAgentId
  if (!agentId || agentId === 'unknown') return 'Unknown agent'
  const entry = agentsById.value.get(agentId)
  if (entry) return entry.name || agentId
  return agentId
}

function contractGapTitle(row: SessionItem): string {
  return `Missing session-list-v1 fields: ${row.contractGaps.join(', ')}`
}

// ---------------------------------------------------------------------------
// Status display helpers
// ---------------------------------------------------------------------------

function sessionStatusClass(status: string): string {
  const s = (status || 'unknown').toLowerCase()
  if (s === 'running' || s === 'active' || s === 'ready' || s === 'ok') return 'ok'
  if (s === 'done' || s === 'completed' || s === 'complete') return 'ok'
  if (s === 'failed' || s === 'error' || s === 'err') return 'err'
  if (s === 'timeout') return 'warn'
  if (s === 'killed' || s === 'cancelled' || s === 'interrupted') return 'warn'
  if (s === 'paused' || s === 'degraded') return 'warn'
  if (s === 'closed' || s === 'ended' || s === 'offline' || s === 'unknown') return 'off'
  return 'off'
}

function sessionStatusChip(status: string): string {
  const s = (status || 'unknown').toLowerCase()
  if (s === 'running' || s === 'active' || s === 'ready' || s === 'ok') return 'chip-ok'
  if (s === 'done' || s === 'completed' || s === 'complete') return 'chip-ok'
  if (s === 'failed' || s === 'error' || s === 'err') return 'chip-danger'
  if (s === 'timeout') return 'chip-warn'
  if (s === 'killed' || s === 'cancelled' || s === 'interrupted') return 'chip-warn'
  if (s === 'paused' || s === 'degraded') return 'chip-warn'
  return ''
}

function sessionStatusLabel(status: string): string {
  const s = (status || 'unknown').toLowerCase()
  const labels: Record<string, string> = {
    running: 'Running',
    active: 'Active',
    ready: 'Ready',
    ok: 'OK',
    done: 'Done',
    completed: 'Completed',
    complete: 'Complete',
    failed: 'Failed',
    error: 'Error',
    timeout: 'Timed out',
    killed: 'Killed',
    cancelled: 'Cancelled',
    interrupted: 'Interrupted',
    paused: 'Paused',
    degraded: 'Degraded',
    closed: 'Closed',
    ended: 'Ended',
    offline: 'Offline',
    unknown: 'Unknown',
  }
  return labels[s] || s.charAt(0).toUpperCase() + s.slice(1)
}

// ---------------------------------------------------------------------------
// Time helper
// ---------------------------------------------------------------------------

function relTime(timestamp: number | undefined): string {
  if (!timestamp) return '—'
  const d = new Date(timestamp)
  if (isNaN(d.getTime())) return '—'

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
</script>

<style scoped>
/* Search */
.sess-search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0 12px;
  min-width: 200px;
}

.sess-search-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.sess-search-input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 0;
  width: 100%;
}

.sess-search-input::placeholder {
  color: var(--text-dim);
}

.stat--hero {
  min-height: 116px;
}

.dot {
  border-radius: 999px;
  display: inline-block;
  height: 8px;
  width: 8px;
}

.dot.ok {
  background: var(--ok);
}

.dot.warn {
  background: var(--warn);
}

.dot.err {
  background: var(--danger);
}

.dot.off {
  background: var(--text-dim);
}

/* Bulk bar */
.sess-bulk-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}

.sess-bulk-bar__count {
  font-size: var(--fs-sm);
  color: var(--text);
}

.sess-bulk-bar__spacer {
  flex: 1;
}

/* List */
.sess-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.sess-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}

.sess-list__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.sess-list__count {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
  padding: 2px 8px;
}

.sess-list__controls {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.sess-page-size {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}

.sess-page-size select {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 4px 8px;
  font-size: var(--fs-sm);
}

/* Table */
.sess-table-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.sess-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.sess-table th {
  text-align: left;
  padding: 10px 12px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
  white-space: nowrap;
}

.sess-table td {
  padding: 10px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  vertical-align: middle;
}

.sess-table tbody tr:last-child td {
  border-bottom: none;
}

.sess-table tbody tr:hover {
  background: color-mix(in srgb, var(--bg-elevated) 50%, transparent);
}

.sess-table tbody tr.is-selected {
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}

.sess-th-sort {
  cursor: pointer;
  user-select: none;
  transition: color var(--transition);
}

.sess-th-sort:hover {
  color: var(--text);
}

.sess-table__arrow {
  color: var(--accent);
}

.sess-table__cell--check {
  width: 40px;
  text-align: center;
}

.sess-table__cell--key {
  min-width: 280px;
}

.sess-table__cell--actions {
  width: 120px;
  text-align: right;
  white-space: nowrap;
}

.sess-table__key-content {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.sess-key-link {
  background: transparent;
  border: none;
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
  font-weight: 650;
  padding: 0;
  cursor: pointer;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.sess-key-link:hover {
  color: var(--accent);
}

.sess-key__sub {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.sess-key__subtitle {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sess-key__subtitle--gap {
  color: var(--warn);
}

.sess-key__debug {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sess-key__badges {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.sess-group-badge,
.sess-agent-badge {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  font-weight: 650;
  padding: 2px 8px;
}

.sess-gap-chip {
  text-transform: none;
}

.sess-type-stack,
.sess-agent-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sess-type-chip {
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text);
  display: inline-flex;
  font-size: 11px;
  font-weight: 700;
  justify-content: center;
  line-height: 1;
  padding: 5px 9px;
  width: fit-content;
}

.sess-type-chip--chat {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 24%, var(--border));
}

.sess-type-chip--channel {
  background: color-mix(in srgb, var(--ok) 10%, transparent);
  border-color: color-mix(in srgb, var(--ok) 24%, var(--border));
}

.sess-type-chip--task,
.sess-type-chip--cron {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 24%, var(--border));
}

.sess-type-chip--system,
.sess-type-chip--unknown {
  background: var(--bg-elevated);
  color: var(--text-muted);
}

.sess-type-meta,
.sess-agent-id {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sess-status-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sess-mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.sess-dim {
  color: var(--text-dim);
}

/* Checkbox */
.sess-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  width: 18px;
  height: 18px;
  position: relative;
}

.sess-check input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.sess-check span {
  width: 16px;
  height: 16px;
  border: 1.5px solid var(--border);
  border-radius: 3px;
  display: block;
  transition: background var(--transition), border-color var(--transition);
}

.sess-check input:checked + span {
  background: var(--accent);
  border-color: var(--accent);
}

/* Action buttons */
.sess-iconbtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}

.sess-iconbtn:hover {
  background: var(--bg-elevated);
  color: var(--text);
}

.sess-iconbtn--danger {
  color: var(--danger);
}

.sess-iconbtn--danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.sess-iconbtn--ghost {
  width: auto;
  padding: 4px 10px;
  font-size: var(--fs-sm);
  color: var(--text-muted);
  border-color: var(--border);
}

/* Pagination */
.sess-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
}

.sess-page-btn {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
}

.sess-page-btn:hover:not(:disabled) {
  border-color: var(--border-focus);
  background: var(--bg-surface);
}

.sess-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.sess-page-info {
  font-size: var(--fs-sm);
  color: var(--text);
}

/* Chips */
.chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  text-transform: uppercase;
}

.chip-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.chip-warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.chip-danger {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

/* Empty state */
.sess-empty {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.sess-empty__art {
  color: var(--text-dim);
  height: 120px;
  width: 120px;
}

.sess-empty__art svg {
  display: block;
  height: 100%;
  width: 100%;
}

.sess-empty__pulse {
  animation: sess-pulse 2s ease-in-out infinite;
}

@keyframes sess-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.sess-empty__title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.sess-empty__msg {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

.sess-empty__cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* State (no matches) */
.state {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
  color: var(--text-muted);
}

.state-icon {
  color: var(--text-dim);
}

.state-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text);
}

.state-text {
  font-size: var(--fs-sm);
  margin: 0;
}

/* Agent subline */
.sess-key__sub {
  font-size: 11px;
}

.sess-key__agent {
  color: var(--text-dim);
}

.sess-key__agent--orphan {
  color: var(--warn);
}

/* Responsive */
@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .sess-stage__header {
    flex-direction: column;
    align-items: stretch;
  }

  .stat-row {
    grid-template-columns: 1fr;
  }

  .sess-table {
    font-size: 12px;
  }

  .sess-table th,
  .sess-table td {
    padding: 8px;
  }

  .sess-table__cell--actions {
    width: auto;
  }
}
</style>
