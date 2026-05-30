<template>
  <div class="sess-stage">
    <header class="sess-stage__header">
      <div class="sess-stage__title-block">
        <span class="sess-stage__eyebrow">Control &middot; Sessions</span>
        <h2 class="sess-stage__title">Sessions</h2>
        <p class="sess-stage__subtitle">
          Session history, current task activity, and agent runs — open one to chat, or clean up old state.
        </p>
      </div>
      <div class="sess-stage__actions">
        <div class="sess-search-wrap">
          <span class="sess-search-icon">
            <Icon name="search" :size="14" />
          </span>
          <input
            v-model="searchInput"
            type="text"
            class="sess-search-input"
            placeholder="Search session keys…"
            autocomplete="off"
            @input="onSearchInput"
          />
        </div>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
        <button class="btn btn--primary" @click="openNewSessionModal">
          <Icon name="plus" :size="16" />
          <span>New session</span>
        </button>
      </div>
    </header>

    <section class="stat-row">
      <div class="stat stat--hero">
        <div class="stat-label">Total sessions</div>
        <div class="stat-value">{{ totalSessions }}</div>
        <div class="stat-hint">
          {{ lifecycleOpen }} open &middot; {{ doneCount }} completed &middot; {{ failedOrTimedOut }} failed/timed out &middot; {{ abortedCount }} aborted
        </div>
      </div>
      <div class="stat" title="Sessions with queued or running tasks">
        <div class="stat-label">Executing</div>
        <div class="stat-value">
          {{ activeRuns }}<span v-if="activeRuns > 0" class="dot ok"></span>
        </div>
        <div class="stat-hint">{{ activeRuns ? 'tasks queued/running' : 'none executing' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Messages</div>
        <div class="stat-value mono">{{ totalMessages.toLocaleString() }}</div>
        <div class="stat-hint">{{ distinctAgents.size }} agent{{ distinctAgents.size === 1 ? '' : 's' }} &middot; across all sessions</div>
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
        <h3 class="sess-list__title" v-html="listTitle"></h3>
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
            Start one and pick up the conversation any time.
          </p>
          <button class="btn btn--primary sess-empty__cta" @click="openNewSessionModal">
            <Icon name="plus" :size="16" />
            <span>Start a new session</span>
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
                :class="{ 'is-active': sortCol === 'key' }"
                @click="setSort('key')"
              >
                Session key
                <span v-if="sortCol === 'key'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
              <th>Status</th>
              <th>Msgs</th>
              <th
                class="sess-th-sort"
                :class="{ 'is-active': sortCol === 'updated_at' }"
                @click="setSort('updated_at')"
              >
                Modified
                <span v-if="sortCol === 'updated_at'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
              <th
                class="sess-th-sort"
                :class="{ 'is-active': sortCol === 'message_count' }"
                @click="setSort('message_count')"
              >
                Msgs
                <span v-if="sortCol === 'message_count'" class="sess-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
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
                    {{ row.key }}
                  </button>
                  <div v-if="agentSubline(row)" v-html="agentSubline(row)"></div>
                </div>
              </td>
              <td>
                <div class="sess-status-stack">
                  <span :class="['chip', sessionStatusChip(sessionVisualStatus(row))]">
                    {{ sessionStatusLabel(sessionVisualStatus(row)) }}
                  </span>
                  <span v-if="runStatusBadge(row)" v-html="runStatusBadge(row)"></span>
                </div>
              </td>
              <td class="sess-mono">
                {{ row.message_count != null ? Number(row.message_count).toLocaleString() : '—' }}
              </td>
              <td class="sess-mono sess-dim">{{ row.updated_at ? relTime(row.updated_at) : '—' }}</td>
              <td class="sess-mono sess-dim">{{ row.message_count != null ? Number(row.message_count).toLocaleString() : '—' }}</td>
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

    <!-- New session modal -->
    <div v-if="showModal" class="modal-backdrop" @mousedown="onModalBackdropClick">
      <div class="modal sess-newchat-modal" role="dialog" aria-modal="true" aria-labelledby="ns-title">
        <div class="modal-title" id="ns-title">Start a new chat</div>
        <div class="modal-body">
          <div class="sess-form">
            <label class="sess-form__field">
              <span class="sess-form__label">Agent</span>
              <div class="sess-combobox-wrap">
                <input
                  v-model="modalAgentInput"
                  type="text"
                  class="input"
                  placeholder="Pick an agent or type a new ID"
                  autocomplete="off"
                  @input="onModalAgentInput"
                  @keydown.enter.prevent="onModalSubmit"
                />
                <div v-if="modalAgentSuggestions.length > 0" class="sess-combobox-dropdown">
                  <button
                    v-for="a in modalAgentSuggestions"
                    :key="a.id"
                    type="button"
                    class="sess-combobox-item"
                    :class="{ 'is-selected': modalSelectedAgent === a.id }"
                    @click="selectModalAgent(a.id)"
                  >
                    <span class="sess-combobox-item__label">{{ a.label }}</span>
                    <span v-if="a.sublabel" class="sess-combobox-item__sub">{{ a.sublabel }}</span>
                  </button>
                  <button
                    v-if="modalAgentInput.trim() && !modalAgents.find(a => a.id === modalAgentInput.trim())"
                    type="button"
                    class="sess-combobox-item sess-combobox-item--create"
                    @click="createModalAgent"
                  >
                    ↵ Create new agent "{{ modalAgentInput.trim() }}"
                  </button>
                </div>
              </div>
              <small class="sess-form__hint">Pick an agent or type a new ID to create it.</small>
            </label>
            <div v-if="modalError" class="sess-form__error">{{ modalError }}</div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="closeModal">Cancel</button>
          <button
            class="btn btn--primary"
            :disabled="!modalCanSubmit"
            @click="onModalSubmit"
          >
            {{ modalCreatePending ? 'Creating…' : 'Start chat' }}
          </button>
        </div>
      </div>
    </div>
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

interface Session {
  key: string
  status?: string
  model?: string
  message_count?: number
  updated_at?: string
  display_name?: string
  displayName?: string
  subject?: string
  derived_title?: string
  derivedTitle?: string
  agent_id?: string
  agentId?: string
  active_task?: { status?: string }
  activeTask?: { status?: string }
  last_task?: { status?: string }
  lastTask?: { status?: string }
  run_status?: string
  runStatus?: string
  terminal_status?: string
  terminalStatus?: string
  size_bytes?: number
}

interface Agent {
  id: string
  name?: string
  model?: string
  isBuiltin?: boolean
  type?: string
}

interface AgentsListData {
  agents?: Agent[]
}

interface SessionsListData {
  sessions?: Session[]
}

interface SessionCreateResponse {
  key?: string
}

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

const allSessions = ref<Session[]>([])
const filtered = ref<Session[]>([])
const sortCol = ref<'key' | 'updated_at' | 'message_count'>('updated_at')
const sortAsc = ref(false)
const page = ref(0)
const pageSize = ref(25)
const selected = ref<Set<string>>(new Set())
const searchVal = ref('')
const searchInput = ref('')
const agentsById = ref<Map<string, Agent>>(new Map())
const agentsLoaded = ref(false)

let searchDebounceId: ReturnType<typeof setTimeout> | null = null
let pollInterval: ReturnType<typeof setInterval> | null = null

// Modal state
const showModal = ref(false)
const modalAgents = ref<{ id: string; label: string; sublabel: string }[]>([])
const modalAgentInput = ref('')
const modalSelectedAgent = ref('')
const modalCreatePending = ref(false)
const modalError = ref('')
const modalSubmitting = ref(false)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))

const slice = computed(() => {
  const tp = totalPages.value
  page.value = Math.min(page.value, tp - 1)
  return filtered.value.slice(page.value * pageSize.value, (page.value + 1) * pageSize.value)
})

const allOnPageSelected = computed(() => {
  return slice.value.length > 0 && slice.value.every(s => selected.value.has(s.key))
})

const listTitle = computed(() => {
  const total = allSessions.value.length
  if (searchVal.value) {
    return `Matching sessions <span class="sess-list__count">${filtered.value.length} of ${total}</span>`
  }
  return `All sessions <span class="sess-list__count">${total}</span>`
})

const totalSessions = computed(() => allSessions.value.length)

const lifecycleOpen = computed(() => allSessions.value.filter(s => s.status === 'running').length)

const activeRuns = computed(() =>
  allSessions.value.filter(s => {
    const rs = sessionRunStatus(s)
    return rs === 'queued' || rs === 'running'
  }).length
)

const doneCount = computed(() =>
  allSessions.value.filter(s => sessionVisualStatus(s) === 'done').length
)

const failedOrTimedOut = computed(() =>
  allSessions.value.filter(s => {
    const status = sessionVisualStatus(s)
    return status === 'failed' || status === 'timeout'
  }).length
)

const abortedCount = computed(() =>
  allSessions.value.filter(s => sessionVisualStatus(s) === 'killed').length
)

const totalMessages = computed(() =>
  allSessions.value.reduce((acc, s) => acc + (Number(s.message_count) || 0), 0)
)

const distinctAgents = computed(() => {
  const agents = new Set<string>()
  allSessions.value.forEach(s => {
    const m = /^agent:([^:]+):/.exec(s.key || '')
    if (m) agents.add(m[1])
  })
  return agents
})

const modalAgentSuggestions = computed(() => {
  const typed = modalAgentInput.value.trim().toLowerCase()
  if (!typed) return modalAgents.value
  return modalAgents.value.filter(a =>
    a.id.toLowerCase().includes(typed) || a.label.toLowerCase().includes(typed)
  )
})

const modalCanSubmit = computed(() => {
  if (modalSubmitting.value) return false
  const typed = modalAgentInput.value.trim()
  return !!(modalSelectedAgent.value || typed)
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  pollInterval = setInterval(loadData, 30000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
  } catch {
    return
  }

  const [sessRes, agentsRes] = await Promise.allSettled([
    rpc.call<SessionsListData>('sessions.list', { limit: 200 }),
    rpc.call<AgentsListData>('agents.list'),
  ])

  if (agentsRes.status === 'fulfilled') {
    const list = agentsRes.value?.agents || []
    agentsById.value = new Map(list.map(a => [a.id, a]))
    agentsLoaded.value = true
  }

  if (sessRes.status === 'fulfilled') {
    allSessions.value = sessRes.value?.sessions || []
    selected.value.clear()
    applyFilter()
  } else {
    console.warn('Failed to load sessions: ' + (sessRes.reason?.message || 'unknown error'))
  }
}

// ---------------------------------------------------------------------------
// Filtering & Sorting
// ---------------------------------------------------------------------------

function onSearchInput() {
  if (searchDebounceId !== null) clearTimeout(searchDebounceId)
  searchDebounceId = setTimeout(() => {
    searchDebounceId = null
    searchVal.value = searchInput.value.trim().toLowerCase()
    page.value = 0
    selected.value.clear()
    applyFilter()
  }, 180)
}

function applyFilter() {
  if (!searchVal.value) {
    filtered.value = [...allSessions.value]
  } else {
    const sv = searchVal.value
    filtered.value = allSessions.value.filter(s =>
      String(s.key || '').toLowerCase().includes(sv) ||
      String(s.model || '').toLowerCase().includes(sv) ||
      String(s.display_name || s.displayName || '').toLowerCase().includes(sv) ||
      String(s.subject || '').toLowerCase().includes(sv) ||
      String(s.derived_title || s.derivedTitle || '').toLowerCase().includes(sv)
    )
  }
  sortData()
}

function sortData() {
  filtered.value.sort((a, b) => {
    let va: string | number = a[sortCol.value] ?? ''
    let vb: string | number = b[sortCol.value] ?? ''
    if (sortCol.value === 'message_count' || sortCol.value === 'updated_at') {
      va = Number(va) || 0
      vb = Number(vb) || 0
    } else {
      va = String(va).toLowerCase()
      vb = String(vb).toLowerCase()
    }
    const cmp = va < vb ? -1 : va > vb ? 1 : 0
    return sortAsc.value ? cmp : -cmp
  })
}

function setSort(col: 'key' | 'updated_at' | 'message_count') {
  if (sortCol.value === col) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = col
    sortAsc.value = true
  }
  sortData()
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

function toggleRow(key: string) {
  if (selected.value.has(key)) {
    selected.value.delete(key)
  } else {
    selected.value.add(key)
  }
}

function toggleSelectAll() {
  if (allOnPageSelected.value) {
    slice.value.forEach(s => selected.value.delete(s.key))
  } else {
    slice.value.forEach(s => selected.value.add(s.key))
  }
}

function clearSelection() {
  selected.value.clear()
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function openChat(key: string) {
  router.push({ path: '/chat', query: { session: key } })
}

async function copyKey(key: string) {
  try {
    await navigator.clipboard.writeText(key)
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

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

async function openNewSessionModal() {
  showModal.value = true
  modalAgentInput.value = ''
  modalSelectedAgent.value = ''
  modalCreatePending.value = false
  modalError.value = ''
  modalSubmitting.value = false

  try {
    const data = await rpc.call<AgentsListData>('agents.list')
    const agents = (data?.agents || []).map(a => ({
      id: a.id,
      label: a.name || a.id,
      sublabel: a.model || (a.isBuiltin || a.type === 'builtin' ? 'built-in' : ''),
    }))
    modalAgents.value = agents
    const mainAgent = agents.find(a => a.id === 'main')
    if (mainAgent) {
      modalSelectedAgent.value = 'main'
      modalAgentInput.value = mainAgent.label
    }
  } catch {
    modalAgents.value = []
  }
}

function closeModal() {
  showModal.value = false
}

function onModalBackdropClick(e: MouseEvent) {
  if (e.target === e.currentTarget) {
    closeModal()
  }
}

function onModalAgentInput() {
  const typed = modalAgentInput.value.trim()
  const exact = modalAgents.value.find(a => a.id === typed || a.label === typed)
  if (exact) {
    modalSelectedAgent.value = exact.id
    modalCreatePending.value = false
  } else {
    modalSelectedAgent.value = ''
    modalCreatePending.value = !!typed
  }
}

function selectModalAgent(id: string) {
  modalSelectedAgent.value = id
  modalCreatePending.value = false
  const agent = modalAgents.value.find(a => a.id === id)
  modalAgentInput.value = agent?.label || id
}

function createModalAgent() {
  modalCreatePending.value = true
  modalSelectedAgent.value = ''
}

async function onModalSubmit() {
  if (modalSubmitting.value) return
  modalError.value = ''

  let agentId: string
  if (modalCreatePending.value) {
    const id = modalAgentInput.value.trim()
    if (!id) return
    agentId = id
  } else {
    agentId = modalSelectedAgent.value || modalAgentInput.value.trim() || 'main'
  }

  modalSubmitting.value = true
  let createdAgent = false

  try {
    if (modalCreatePending.value) {
      try {
        await rpc.call('agents.create', { id: agentId, name: agentId })
        createdAgent = true
      } catch (err: any) {
        if ((err?.code || '') !== 'agent.exists') throw err
      }
    }
    const res = await rpc.call<SessionCreateResponse>('sessions.create', { agentId })
    console.warn(createdAgent ? `Created agent "${agentId}" and started chat` : 'Session created')
    closeModal()
    loadData()
    if (res?.key) {
      router.push({ path: '/chat', query: { session: res.key } })
    }
  } catch (err: any) {
    const code = err?.code || ''
    const msg = err?.message || String(err)
    let friendly = 'Failed to start chat: ' + msg
    if (code === 'UNAUTHORIZED' && modalCreatePending.value) {
      friendly = 'This connection does not have permission to create agents.'
    }
    if (code === 'agent.not_found') {
      friendly = `Agent "${agentId}" doesn't exist. Type a new ID and pick "Create new agent" from the dropdown.`
    }
    if (code === 'agent.exists') {
      friendly = `Agent "${agentId}" already exists — pick it from the list instead.`
    }
    modalError.value = friendly
    modalSubmitting.value = false
  }
}

// ---------------------------------------------------------------------------
// Session status helpers
// ---------------------------------------------------------------------------

function normalizeRunStatus(status: string | undefined): string {
  const value = String(status || '').toLowerCase()
  if (value === 'abandoned') return 'interrupted'
  if (value === 'succeeded' || value === 'success' || value === 'complete') return 'idle'
  if (['queued', 'running', 'interrupted', 'failed', 'timeout', 'cancelled'].includes(value)) {
    return value
  }
  return 'idle'
}

function sessionRunStatus(row: Session): string {
  const active = row.active_task || row.activeTask || null
  const activeStatus = active ? normalizeRunStatus(active.status) : ''
  const terminal = terminalRunStatus(row)
  const rawStatus = row.run_status || row.runStatus || active?.status || terminal || ''
  const runStatus = normalizeRunStatus(rawStatus)
  if (active && (activeStatus === 'queued' || activeStatus === 'running')) return activeStatus
  if (terminal) return normalizeRunStatus(terminal)
  return runStatus
}

function terminalRunStatus(row: Session): string {
  const lastTask = row.last_task || row.lastTask || null
  const rawStatus = lastTask?.status || row.terminal_status || row.terminalStatus || ''
  const status = normalizeRunStatus(rawStatus)
  return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(status) ? status : ''
}

function sessionVisualStatus(row: Session): string {
  const runStatus = sessionRunStatus(row)
  if (runStatus === 'failed' || runStatus === 'timeout') return runStatus
  if (runStatus === 'cancelled' || runStatus === 'interrupted') return 'killed'
  return String(row?.status || 'unknown').toLowerCase()
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

function runStatusBadge(row: Session): string {
  const runStatus = sessionRunStatus(row)
  const label = runStatusLabel(runStatus)
  if (!label) return ''
  const chipClass = runStatusChipClass(runStatus)
  return `<span class="chip ${chipClass} sess-run-chip" title="${label}">${label}</span>`
}

function agentIdFromKey(key: string): string {
  const m = /^agent:([^:]+):/.exec(key)
  return m ? m[1] : ''
}

function agentSubline(row: Session): string {
  const agentId = row.agent_id || row.agentId || agentIdFromKey(row.key)
  if (!agentId) return ''
  const entry = agentsById.value.get(agentId)
  if (entry) {
    if (agentId === 'main') return ''
    const name = entry.name || agentId
    return `<div class="sess-key__sub"><span class="sess-key__agent">${name}</span></div>`
  }
  if (agentId === 'main') return ''
  if (!agentsLoaded.value) {
    return `<div class="sess-key__sub"><span class="sess-key__agent">${agentId}</span></div>`
  }
  return `<div class="sess-key__sub"><span class="sess-key__agent sess-key__agent--orphan" title="Agent '${agentId}' is no longer registered">${agentId}<span class="chip chip-warn">⚠ Orphaned</span></span></div>`
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

function relTime(dateStr: string | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr

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
.sess-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  max-width: none;
  position: relative;
}

.sess-stage__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding-top: var(--sp-3);
}

.sess-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sess-stage__eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-dim);
}

.sess-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  position: relative;
  margin: 0;
}

.sess-stage__title::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 36px;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
}

.sess-stage__subtitle {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  margin: var(--sp-3) 0 0;
  max-width: 60ch;
}

.sess-stage__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

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

/* Stats */
.stat-row {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
}

.stat--hero {
  min-height: 116px;
}

.stat-label {
  color: var(--text-dim);
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.stat-value {
  align-items: center;
  display: flex;
  font-size: 2rem;
  font-variant-numeric: tabular-nums;
  gap: 8px;
  letter-spacing: 0;
  line-height: 1.12;
  margin-top: var(--sp-4);
}

.stat-value.mono {
  font-family: var(--font-mono);
}

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
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
  min-width: 200px;
}

.sess-table__cell--actions {
  width: 120px;
  text-align: right;
  white-space: nowrap;
}

.sess-table__key-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sess-key-link {
  background: transparent;
  border: none;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12.5px;
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

/* Modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: var(--sp-4);
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  max-width: 480px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.3);
}

.modal-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border);
}

.modal-body {
  padding: var(--sp-4) var(--sp-5);
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
}

/* Form in modal */
.sess-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.sess-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sess-form__label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.sess-form__hint {
  font-size: var(--fs-xs);
  color: var(--text-dim);
}

.sess-form__error {
  padding: var(--sp-2) var(--sp-3);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, var(--border));
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: var(--fs-sm);
}

/* Combobox */
.sess-combobox-wrap {
  position: relative;
}

.sess-combobox-wrap .input {
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  font-size: var(--fs-sm);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  outline: none;
  transition: border-color var(--transition), box-shadow var(--transition);
  font-family: inherit;
}

.sess-combobox-wrap .input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}

.sess-combobox-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  max-height: 240px;
  overflow-y: auto;
  z-index: 10;
}

.sess-combobox-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-sm);
  cursor: pointer;
  text-align: left;
  transition: background var(--transition);
}

.sess-combobox-item:hover,
.sess-combobox-item.is-selected {
  background: var(--bg-elevated);
}

.sess-combobox-item__sub {
  font-size: var(--fs-xs);
  color: var(--text-dim);
}

.sess-combobox-item--create {
  color: var(--accent);
  font-weight: 600;
  border-top: 1px solid var(--border);
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
