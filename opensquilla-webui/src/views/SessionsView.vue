<template>
  <div class="hub control-stage">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <h2 class="control-stage__title">Sessions</h2>
        <p class="control-stage__subtitle">
          Start a task, unblock a run, or pick up where you left off.
        </p>
      </div>
      <div class="control-stage__actions">
        <button class="btn btn--ghost" title="Refresh" :disabled="refreshing" @click="refresh">
          <Icon name="refresh" :size="16" />
          <span>{{ refreshing ? 'Refreshing…' : 'Refresh' }}</span>
        </button>
      </div>
    </header>

    <SessionsTaskInput @submit="startTask" />

    <SessionsAttentionStrip
      :approvals-count="pendingApprovals.length"
      :running-count="runningCount"
      :queued-count="queuedCount"
      :cost-usd="costUsd"
      @open-approvals="openBlockedSession"
      @open-usage="router.push('/usage')"
    />

    <section class="hub-list">
      <div class="hub-list__head">
        <div class="hub-filters" role="group" aria-label="Filter sessions">
          <button
            v-for="chip in FILTER_CHIPS"
            :key="chip.id"
            type="button"
            class="hub-filter"
            :class="{ 'is-active': filter === chip.id }"
            :aria-pressed="filter === chip.id"
            @click="filter = chip.id"
          >
            {{ chip.label }}
          </button>
        </div>
        <div class="hub-search">
          <span class="hub-search__icon" aria-hidden="true">
            <Icon name="search" :size="14" />
          </span>
          <input
            v-model="search"
            type="text"
            class="hub-search__input"
            placeholder="Search sessions…"
            aria-label="Search sessions"
            autocomplete="off"
          />
        </div>
      </div>

      <ErrorState
        v-if="sessionListError"
        message="Could not load sessions."
        :on-retry="loadAll"
      />

      <div v-else-if="isLoading && allSessions.length === 0" class="hub-state">
        <LoadingSpinner />
        <p class="hub-state__text">Loading sessions…</p>
      </div>

      <div v-else-if="allSessions.length === 0" class="hub-state">
        <div class="hub-state__title">No sessions yet.</div>
        <p class="hub-state__text">
          Start your first task above — sessions appear here as agents pick up work.
        </p>
      </div>

      <div v-else-if="ledgerEntries.length === 0" class="hub-state">
        <div class="hub-state__title">No matches</div>
        <p class="hub-state__text">No sessions match the current filter.</p>
        <button class="btn btn--ghost" @click="clearFilters">Clear filters</button>
      </div>

      <SessionsLedger
        v-else
        :entries="ledgerEntries"
        :agent-names="agentNames"
        :needs-input-keys="needsInputKeys"
        @open="openSession"
        @remove="removeSession"
      />
    </section>

    <SessionInspectDrawer
      :open="inspectItem !== null"
      :item="inspectItem"
      :agent-name="inspectAgentName"
      :parent-item="inspectParent"
      :needs-input="inspectItem ? needsInputKeys.has(inspectItem.key) : false"
      @close="closeInspect"
      @open-chat="openInChat"
      @aborted="onInspectAborted"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useConfirm } from '@/composables/useConfirm'
import SessionsTaskInput from '@/components/sessions/SessionsTaskInput.vue'
import SessionsAttentionStrip from '@/components/sessions/SessionsAttentionStrip.vue'
import SessionsLedger from '@/components/sessions/SessionsLedger.vue'
import SessionInspectDrawer from '@/components/sessions/SessionInspectDrawer.vue'
import {
  arrangeSessionLedger,
  sessionMatches,
  sessionParentKey,
  useSessions,
  type SessionItem,
} from '@/composables/useSessions'

type FilterId = 'all' | 'chats' | 'automations' | 'channels'

interface AgentsListResponse {
  agents?: Array<{ id?: string; name?: string }>
}

interface UsageStatusResponse {
  totalCostUsd?: number
}

interface DeleteResponse {
  deleted?: string[]
  errors?: unknown[]
}

const FILTER_CHIPS: Array<{ id: FilterId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'chats', label: 'Chats' },
  { id: 'automations', label: 'Automations' },
  { id: 'channels', label: 'Channels' },
]

const FILTER_KINDS: Record<Exclude<FilterId, 'all'>, string> = {
  chats: 'chat',
  automations: 'cron',
  channels: 'channel',
}

const REFRESH_DEBOUNCE_MS = 150
const FALLBACK_POLL_MS = 30000

const router = useRouter()
const rpc = useRpcStore()
const { confirm } = useConfirm()
const { allSessions, isLoading, sessionListError, loadSessions } = useSessions()

const filter = ref<FilterId>('all')
const search = ref('')
const agentNames = ref<Map<string, string>>(new Map())
const pendingApprovals = ref<string[]>([])
const costUsd = ref<number | null>(null)

let refreshTimer: ReturnType<typeof setTimeout> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let unsubs: Array<() => void> = []

// ---------------------------------------------------------------------------
// Derivations
// ---------------------------------------------------------------------------

const runningCount = computed(() => allSessions.value.filter(s => s.runStatus === 'running').length)
const queuedCount = computed(() => allSessions.value.filter(s => s.runStatus === 'queued').length)
const needsInputKeys = computed(() => new Set(pendingApprovals.value))

function matchesFilter(item: SessionItem, byKey: Map<string, SessionItem>): boolean {
  if (filter.value === 'all') return true
  const kind = FILTER_KINDS[filter.value]
  // Subagent rows follow their parent through the filter.
  let current: SessionItem | undefined = item
  for (let hop = 0; current && hop < 4; hop++) {
    if (current.sessionKind === kind) return true
    const parentKey = sessionParentKey(current)
    current = parentKey ? byKey.get(parentKey) : undefined
  }
  return false
}

const ledgerEntries = computed(() => {
  const query = search.value.trim().toLowerCase()
  const byKey = new Map(allSessions.value.map(item => [item.key, item]))
  const visible = allSessions.value.filter(item =>
    matchesFilter(item, byKey) && (!query || sessionMatches(item, query)))
  return arrangeSessionLedger(visible)
})

// The inspected row tracks the live session list by key so status flips keep
// rendering; the click-time snapshot covers rows that drop out of the list.
const inspectKey = ref('')
const inspectFallback = ref<SessionItem | null>(null)

const inspectItem = computed(() => {
  if (!inspectKey.value) return null
  return allSessions.value.find(item => item.key === inspectKey.value) || inspectFallback.value
})

const inspectParent = computed(() => {
  const item = inspectItem.value
  if (!item) return null
  const parentKey = sessionParentKey(item)
  return parentKey ? allSessions.value.find(candidate => candidate.key === parentKey) || null : null
})

const inspectAgentName = computed(() => {
  const id = inspectItem.value?.effectiveAgentId
  if (!id || id === 'unknown') return 'Unknown agent'
  return agentNames.value.get(id) || id
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadAgents() {
  try {
    const data = await rpc.call<AgentsListResponse>('agents.list')
    agentNames.value = new Map(
      (data?.agents || [])
        .filter(agent => agent.id)
        .map(agent => [String(agent.id), String(agent.name || agent.id)]))
  } catch {
    // Ledger falls back to agent ids.
  }
}

function approvalAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  try {
    const token = sessionStorage.getItem('opensquilla.wsToken') || ''
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* ignore */ }
  return headers
}

async function refreshApprovals() {
  try {
    const res = await fetch('/api/approvals', { headers: approvalAuthHeaders() })
    if (!res.ok) return
    const data = await res.json() as { pending?: Array<{ sessionKey?: string }> }
    pendingApprovals.value = (data.pending || [])
      .map(item => String(item.sessionKey || '').trim())
      .filter(Boolean)
  } catch {
    // Strip keeps the last known count.
  }
}

async function refreshCost() {
  try {
    const data = await rpc.call<UsageStatusResponse>('usage.status')
    costUsd.value = data?.totalCostUsd != null ? Number(data.totalCostUsd) : null
  } catch {
    costUsd.value = null
  }
}

function loadAll() {
  void loadSessions()
  void loadAgents()
  void refreshApprovals()
  void refreshCost()
}

const refreshing = ref(false)

// Manual refresh shows a busy state; the fallback poll keeps calling loadAll so
// the button reacts only to user clicks, not background refreshes.
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([loadSessions(), loadAgents(), refreshApprovals(), refreshCost()])
  } finally {
    refreshing.value = false
  }
}

function scheduleSessionRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    void loadSessions()
  }, REFRESH_DEBOUNCE_MS)
}

function handleApprovalPush() {
  void refreshApprovals()
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function startTask(text: string) {
  router.push({
    path: '/chat/new',
    query: { agent: 'main' },
    // autosend asks the draft to fire the prefill in one step, so "Start task"
    // actually starts the task instead of dropping the operator at the composer.
    state: { prefill: text, autosend: true },
  }).catch(() => {})
}

// Row click opens the inspect drawer; navigation moved to the drawer's
// explicit "Open in chat" action.
function openSession(item: SessionItem) {
  inspectKey.value = item.key
  inspectFallback.value = item
}

function closeInspect() {
  inspectKey.value = ''
  inspectFallback.value = null
}

function openInChat(item: SessionItem) {
  closeInspect()
  router.push({ path: '/chat', query: { session: item.key } })
}

function onInspectAborted() {
  void loadSessions()
}

function openBlockedSession() {
  const key = pendingApprovals.value.find(Boolean)
  if (key) {
    router.push({ path: '/chat', query: { session: key } })
  } else {
    router.push('/approvals')
  }
}

function clearFilters() {
  filter.value = 'all'
  search.value = ''
}

async function removeSession(item: SessionItem) {
  const ok = await confirm({
    title: 'Delete session',
    body: `Delete session "${item.title}"? This cannot be undone.\n\nThe transcript will not be flushed to disk; use /reset first if you want a backup.`,
    primaryLabel: 'Delete',
  })
  if (!ok) {
    return
  }
  try {
    await rpc.call<DeleteResponse>('sessions.delete', { keys: [item.key] })
  } catch (err) {
    console.warn('Delete failed: ' + (err instanceof Error ? err.message : String(err)))
  }
  void loadSessions()
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadAll()
  unsubs = [
    rpc.on('sessions.changed', scheduleSessionRefresh),
    rpc.on('exec.approval.requested', handleApprovalPush),
    rpc.on('exec.approval.resolved', handleApprovalPush),
    rpc.on('plugin.approval.requested', handleApprovalPush),
    rpc.on('plugin.approval.resolved', handleApprovalPush),
  ]
  pollTimer = setInterval(loadAll, FALLBACK_POLL_MS)
})

onUnmounted(() => {
  unsubs.forEach(unsub => unsub())
  unsubs = []
  if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>

<style scoped>
.hub-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.hub-list__head {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  justify-content: space-between;
}

.hub-filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.hub-filter {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-xs);
  font-weight: 650;
  padding: var(--sp-1) var(--sp-3);
  transition: background var(--transition), border-color var(--transition), color var(--transition);
}

.hub-filter:hover {
  border-color: var(--border-focus);
  color: var(--text);
}

.hub-filter:focus-visible {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

.hub-filter.is-active {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  color: var(--accent);
}

.hub-search {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  gap: var(--sp-2);
  min-width: 200px;
  padding: 0 var(--sp-3);
}

.hub-search__icon {
  color: var(--text-dim);
  display: inline-flex;
  flex-shrink: 0;
}

.hub-search__input {
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-sm);
  outline: none;
  padding: var(--sp-2) 0;
  width: 100%;
}

.hub-search__input::placeholder {
  color: var(--text-dim);
}

.hub-state {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.hub-state__title {
  color: var(--text);
  font-size: var(--fs-lg);
  font-weight: 600;
}

.hub-state__text {
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

@media (max-width: 760px) {
  .hub-list__head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
