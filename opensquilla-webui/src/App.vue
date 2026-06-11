<template>
  <!-- Hover trigger strip (left edge, only active when sidebar is collapsed) -->
  <div
    v-show="!appStore.sidebarOpen"
    class="sidebar-hover-trigger"
    @mouseenter="onHoverEnter"
  />

  <!-- Sidebar -->
  <nav
    class="sidebar"
    :class="{
      docked: appStore.sidebarOpen,
      hovered: appStore.sidebarHovered,
    }"
    aria-label="Primary"
    id="sidebar-nav"
    @mouseleave="onHoverLeave"
  >
    <!-- Brand -->
    <div class="sidebar-brand">
      <img class="sidebar-brand-mark" :src="brandMarkUrl" alt="" aria-hidden="true" />
      <span class="sidebar-brand-text">OpenSquilla</span>
      <button
        class="sidebar-dock-toggle"
        :title="appStore.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'"
        @click="toggleDock"
      >
        <Icon :name="appStore.sidebarOpen ? 'panel-left-close' : 'panel-left-open'" :size="16" />
      </button>
    </div>

    <!-- Top action: new chat with explicit agent selection -->
    <div class="sidebar-actions">
      <button
        class="sidebar-new-session"
        title="Start a new chat"
        @click="openNewChatPicker"
      >
        <Icon name="plus" :size="16" />
        <span>New chat</span>
      </button>
    </div>

    <!-- Function list -->
    <div class="sidebar-section sidebar-primary-nav" aria-label="Control navigation">
      <div v-for="group in navGroups" :key="group.label" class="sidebar-nav-group">
        <div class="sidebar-nav-group-label">{{ group.label }}</div>
        <router-link
          v-for="route in group.items"
          :key="route.path"
          :to="route.path"
          class="sidebar-fn-item"
          :class="{ 'is-active': isNavActive(route.path) }"
          @click="handleNavClick"
        >
          <Icon :name="route.icon" :size="16" />
          <span class="sidebar-fn-label">{{ route.title }}</span>
          <span v-if="route.path === '/approvals' && appStore.approvalCount > 0" class="nav-badge">
            {{ appStore.approvalCount }}
          </span>
        </router-link>
      </div>
    </div>

    <!-- Recent conversations -->
    <SidebarConversations
      :items="sidebarConversations"
      :error="sessionListError"
      :loading="isLoading"
      :current-key="currentSessionKey"
      :contract-debug-enabled="contractDebugEnabled"
      @select="switchToSession"
      @refresh="loadSessions"
    />

    <!-- Bottom links -->
    <div v-if="bottomRoutes.length" class="sidebar-bottom">
      <router-link
        v-for="route in bottomRoutes"
        :key="route.path"
        :to="route.path"
        class="sidebar-fn-item"
        :class="{ 'is-active': $route.path === route.path }"
        :title="route.title"
        :aria-label="route.title"
        :data-tooltip="route.title"
        @click="handleNavClick"
      >
        <Icon :name="route.icon" :size="16" />
        <span class="sidebar-fn-label">{{ route.title }}</span>
      </router-link>
    </div>
  </nav>

  <!-- Mobile drawer scrim: tap outside the sidebar to close it (<=768px only) -->
  <div
    v-if="appStore.sidebarOpen"
    class="sidebar-scrim"
    role="presentation"
    aria-hidden="true"
    @click="appStore.setSidebarOpen(false)"
  />

  <div
    v-if="newChatPickerOpen"
    class="new-chat-backdrop"
    role="presentation"
    @mousedown="onNewChatBackdrop"
  >
    <section class="new-chat-dialog" role="dialog" aria-modal="true" aria-labelledby="new-chat-title">
      <header class="new-chat-dialog__header">
        <div>
          <h2 id="new-chat-title">New chat</h2>
          <p>Choose the agent this conversation belongs to.</p>
        </div>
        <button class="new-chat-dialog__close" title="Close" @click="closeNewChatPicker">×</button>
      </header>
      <div v-if="agentListError" class="new-chat-dialog__error">
        Agent list is unavailable. The main agent is still available.
      </div>
      <div class="new-chat-agent-list">
        <button
          v-for="agent in selectableAgents"
          :key="agent.id"
          type="button"
          class="new-chat-agent"
          :class="{ 'is-selected': selectedNewChatAgentId === agent.id }"
          @click="selectedNewChatAgentId = agent.id"
        >
          <span class="new-chat-agent__mark">
            <Icon name="agents" :size="16" />
          </span>
          <span class="new-chat-agent__body">
            <span class="new-chat-agent__name">{{ agent.name }}</span>
            <span class="new-chat-agent__meta">{{ agent.id }}{{ agent.model ? ` · ${agent.model}` : '' }}</span>
          </span>
        </button>
      </div>
      <footer class="new-chat-dialog__footer">
        <button class="btn btn--ghost" @click="goToAgents">Create agent...</button>
        <span class="new-chat-dialog__spacer"></span>
        <button class="btn btn--ghost" @click="closeNewChatPicker">Cancel</button>
        <button class="btn btn--primary" :disabled="!selectedNewChatAgentId" @click="startNewChatForSelectedAgent">
          Start chat
        </button>
      </footer>
    </section>
  </div>

  <!-- Main content -->
  <div
    class="main"
    :class="{
      docked: appStore.sidebarOpen,
      'main--chat': isChatRoute,
      'main--chat-sidebar-collapsed': isChatRoute && !appStore.sidebarOpen,
    }"
  >
    <header class="topbar" :class="{ 'topbar--chat': isChatRoute }">
      <div class="topbar-left">
        <!-- Sidebar toggle — visible when sidebar is collapsed -->
        <button
          v-show="!appStore.sidebarOpen"
          class="sidebar-dock-toggle topbar-toggle"
          title="Expand sidebar"
          @click="toggleDock"
        >
          <Icon name="panel-left-open" :size="16" />
        </button>
      </div>
      <div class="topbar-right">
        <button
          v-if="appStore.approvalCount > 0"
          class="approval-inline"
          @click="openBlockedApprovalSession"
          title="Open the blocked session"
        >
          Approval required
        </button>
        <span class="conn-pill" :class="rpcStore.state">{{ rpcStore.state }}</span>
        <button class="btn btn--icon btn--ghost" @click="appStore.cycleTheme" :title="`Theme: ${appStore.theme}`">
          <Icon :name="themeIconName" :size="16" />
        </button>
      </div>
    </header>
    <main class="content" :class="{ 'content--chat': isChatRoute }" id="content">
      <ErrorBoundary>
        <router-view />
      </ErrorBoundary>
    </main>
  </div>

  <ToastHost />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from './stores/app'
import { useRpcStore } from './stores/rpc'
import { useSessions, type SessionItem } from './composables/useSessions'
import Icon from './components/Icon.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import ToastHost from './components/ToastHost.vue'
import SidebarConversations, {
  type SidebarConversationItem,
  type SidebarFamilyId,
} from './components/SidebarConversations.vue'
import { useDocumentEvent } from './composables/useDocumentEvent'
import type { AgentOption, AgentsListResponse } from './types/rpc'
import { useNavigation } from './app/useNavigation'
import { normalizeAgentId } from './utils/chat/sessionKeys'

const appStore = useAppStore()
const rpcStore = useRpcStore()
const $route = useRoute()
const router = useRouter()
const { allSessions, sessionListError, isLoading, loadSessions } = useSessions()
const { navGroups, bottomRoutes } = useNavigation()

const agents = ref<AgentOption[]>([])
const agentListError = ref(false)
const newChatPickerOpen = ref(false)
const selectedNewChatAgentId = ref('main')
const localChatSessions = ref<Record<string, { effectiveAgentId: string; title: string; updatedAt: number }>>({})

const brandMarkUrl = computed(() => {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/img/opensquilla-mark.png`
})

const themeIconName = computed(() => {
  if (appStore.theme === 'system') return 'monitor'
  return appStore.resolvedTheme === 'dark' ? 'moon' : 'sun'
})

// Current session key from ChatView via URL
const currentSessionKey = computed(() => {
  return ($route.query.session as string) || ''
})

// Chat layout applies to both the session view and the draft route.
const isChatRoute = computed(() => $route.path === '/chat' || $route.path === '/chat/new')

const contractDebugEnabled = computed(() => appStore.features.contractDebug === true)

function isNavActive(path: string): boolean {
  if (path === '/chat') return isChatRoute.value
  return $route.path === path
}

function agentDisplayName(agentId: string): string {
  const agent = agents.value.find(a => a.id === agentId)
  return agent?.name || (agentId === 'main' ? 'Main Agent' : agentId)
}

// Raw session keys (agent:…:…) and bare UUIDs must never render in the sidebar.
const RAW_SESSION_KEY_PATTERN = /\bagent:[a-z0-9_-]+:[a-z0-9_-]+:/i
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

function looksLikeRawSessionId(value: string): boolean {
  return RAW_SESSION_KEY_PATTERN.test(value) || UUID_PATTERN.test(value) || /^(agent|cron):/i.test(value)
}

function sidebarConversationTitle(item: SessionItem): string {
  for (const candidate of [item.title, item.subtitle, item.groupLabel]) {
    const text = String(candidate || '').trim()
    if (text && !looksLikeRawSessionId(text)) return text
  }
  return 'Untitled session'
}

// Grouped-mode bucket label; raw ids (cron UUIDs, session keys) never render.
function sidebarGroupLabel(item: SessionItem): string {
  if (item.sessionKind === 'cron') {
    // Show the cron job's human name. The contract's generic "Cron" group
    // label and jobId UUIDs make useless headers, so fall through to the
    // job name embedded in the run title when the name field is absent.
    const candidates = [
      item.raw.cron?.name,
      String(item.title || '').replace(/^Cron:\s*/i, ''),
      item.groupLabel,
    ]
    for (const candidate of candidates) {
      const text = String(candidate || '').trim()
      if (text && !looksLikeRawSessionId(text)) return text
    }
    return 'Automation'
  }
  const text = String(item.groupLabel || '').trim()
  if (text && !looksLikeRawSessionId(text)) return text
  return item.sessionKind === 'channel' ? 'Channel' : 'Conversations'
}

// Stable grouping key; cron runs bucket by job id even when jobs share a name.
function sidebarGroupKey(item: SessionItem, label: string): string {
  if (item.sessionKind === 'cron') {
    const jobId = String(item.raw.cron?.jobId || item.raw.cron?.job_id || item.raw.cron?.id || '').trim()
    if (jobId) return jobId
  }
  return label
}

function sourceFamilyForSession(item: SessionItem): SidebarFamilyId | null {
  if (item.sessionKind === 'chat') {
    if (['cli', 'tui', 'mcp', 'subagent'].includes(item.surface)) return null
    return 'chats'
  }
  if (item.sessionKind === 'channel') return 'channels'
  if (item.sessionKind === 'cron') return 'automations'
  return null
}

const selectableAgents = computed(() => {
  const map = new Map<string, AgentOption>()
  map.set('main', { id: 'main', name: 'Main Agent' })
  for (const agent of agents.value) {
    const id = normalizeAgentId(agent.id)
    if (id) map.set(id, { ...agent, id })
  }
  for (const item of allSessions.value) {
    const agentId = normalizeAgentId(item.effectiveAgentId)
    if (agentId && !map.has(agentId)) map.set(agentId, { id: agentId, name: agentDisplayName(agentId) })
  }
  return Array.from(map.values())
})

const sidebarConversations = computed((): SidebarConversationItem[] => {
  const result: SidebarConversationItem[] = []
  const seen = new Set<string>()
  for (const item of allSessions.value) {
    const key = item.key
    if (!key || key === 'unknown') continue
    const sourceFamily = sourceFamilyForSession(item)
    if (!sourceFamily) continue
    seen.add(key)
    const groupLabel = sidebarGroupLabel(item)
    result.push({
      key,
      effectiveAgentId: item.effectiveAgentId,
      agentName: agentDisplayName(normalizeAgentId(item.effectiveAgentId)),
      groupLabel,
      groupKey: sidebarGroupKey(item, groupLabel),
      title: sidebarConversationTitle(item),
      sourceFamily,
      runStatus: item.runStatus,
      runLabel: item.runLabel,
      updatedAt: item.updatedAt,
      hasContractGaps: item.contractGaps.length > 0,
    })
  }
  for (const [key, local] of Object.entries(localChatSessions.value)) {
    if (seen.has(key)) continue
    result.push({
      key,
      effectiveAgentId: local.effectiveAgentId,
      agentName: agentDisplayName(normalizeAgentId(local.effectiveAgentId)),
      groupLabel: '',
      groupKey: '',
      sourceFamily: 'chats',
      title: local.title || 'New chat',
      runStatus: 'idle',
      runLabel: 'Idle',
      updatedAt: local.updatedAt,
      hasContractGaps: false,
    })
  }
  if (currentSessionKey.value && !seen.has(currentSessionKey.value) && !localChatSessions.value[currentSessionKey.value]) {
    const currentAgentId = normalizeAgentId(currentSessionKey.value.split(':')[1] || 'main')
    const currentUpdatedAt = Date.now()
    result.push({
      key: currentSessionKey.value,
      effectiveAgentId: currentAgentId,
      agentName: agentDisplayName(currentAgentId),
      groupLabel: '',
      groupKey: '',
      sourceFamily: 'chats',
      title: 'Current session',
      runStatus: 'idle',
      runLabel: 'Idle',
      updatedAt: currentUpdatedAt,
      hasContractGaps: true,
    })
  }
  return result.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 60)
})

let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let sessionRefreshTimer: ReturnType<typeof setTimeout> | null = null
let rpcUnsubSessionsChanged: (() => void) | null = null

function syncMobileSidebar() {
  if (window.innerWidth <= 768 && appStore.sidebarOpen) {
    appStore.setSidebarOpen(false)
  }
}

function toggleDock() {
  appStore.toggleSidebar()
}

function handleNavClick() {
  if (appStore.sidebarHovered) {
    appStore.setSidebarHovered(false)
  }
  if (window.innerWidth <= 768 && appStore.sidebarOpen) {
    appStore.setSidebarOpen(false)
  }
}

function preferredAgentId(): string {
  if (currentSessionKey.value) {
    const current = allSessions.value.find(item => item.key === currentSessionKey.value)
    if (current?.effectiveAgentId && current.effectiveAgentId !== 'unknown') return normalizeAgentId(current.effectiveAgentId)
    const local = localChatSessions.value[currentSessionKey.value]
    if (local?.effectiveAgentId) return normalizeAgentId(local.effectiveAgentId)
  }
  const latest = sidebarConversations.value.find(item => item.sourceFamily === 'chats' && item.effectiveAgentId !== 'unknown')?.effectiveAgentId
  return latest || 'main'
}

async function loadAgents() {
  agentListError.value = false
  try {
    await rpcStore.waitForConnection()
    const data = await rpcStore.call<AgentsListResponse>('agents.list')
    agents.value = (data?.agents || []).map(a => ({
      id: normalizeAgentId(a.id || a.agentId || a.name || ''),
      name: a.name || a.id || a.agentId || 'Agent',
      model: a.model || '',
    })).filter((a: AgentOption) => !!a.id)
  } catch (err: unknown) {
    console.warn('[App] agents.list error:', errorMessage(err))
    agentListError.value = true
    if (!agents.value.length) agents.value = [{ id: 'main', name: 'Main Agent' }]
  }
}

async function openNewChatPicker() {
  selectedNewChatAgentId.value = preferredAgentId()
  newChatPickerOpen.value = true
  if (!agents.value.length) {
    await loadAgents()
    if (!selectableAgents.value.some(a => a.id === selectedNewChatAgentId.value)) {
      selectedNewChatAgentId.value = preferredAgentId()
    }
  }
}

function closeNewChatPicker() {
  newChatPickerOpen.value = false
}

function onNewChatBackdrop(e: MouseEvent) {
  if (e.target === e.currentTarget) closeNewChatPicker()
}

function startNewChatForSelectedAgent() {
  // Draft state: no session exists until the first message is sent.
  const agentId = normalizeAgentId(selectedNewChatAgentId.value || 'main')
  closeNewChatPicker()
  router.push({ path: '/chat/new', query: { agent: agentId } })
}

function goToAgents() {
  closeNewChatPicker()
  router.push('/agents')
}

function switchToSession(key: string) {
  if (!key) return
  router.push({ path: '/chat', query: { session: key } })
  if (appStore.sidebarHovered) {
    appStore.setSidebarHovered(false)
  }
}

// Topbar approval pill: jump straight to the blocked session's chat so the
// in-thread card can be answered; fall back to the Approvals page when the
// pending request carries no session.
async function openBlockedApprovalSession() {
  try {
    const headers: Record<string, string> = {}
    try {
      const token = sessionStorage.getItem('opensquilla.wsToken') || ''
      if (token) headers['Authorization'] = `Bearer ${token}`
    } catch { /* ignore */ }
    const res = await fetch('/api/approvals', { headers })
    if (res.ok) {
      const data = await res.json() as { pending?: Array<{ sessionKey?: string }> }
      const key = (data.pending || [])
        .map(item => String(item.sessionKey || '').trim())
        .find(Boolean)
      if (key) {
        switchToSession(key)
        return
      }
    }
  } catch { /* fall through to the Approvals page */ }
  router.push('/approvals')
}

function onHoverEnter() {
  if (appStore.sidebarOpen) return
  if (hoverLeaveTimer) {
    clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = null
  }
  appStore.setSidebarHovered(true)
}

function onHoverLeave() {
  if (appStore.sidebarOpen) return
  hoverLeaveTimer = setTimeout(() => {
    appStore.setSidebarHovered(false)
  }, 250)
}

function scheduleSessionRefresh() {
  if (sessionRefreshTimer) clearTimeout(sessionRefreshTimer)
  sessionRefreshTimer = setTimeout(() => {
    sessionRefreshTimer = null
    loadSessions()
  }, 150)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && appStore.sidebarOpen) {
    appStore.setSidebarOpen(false)
  }
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

useDocumentEvent('keydown', handleKeydown)

onMounted(() => {
  syncMobileSidebar()
  window.addEventListener('resize', syncMobileSidebar)
  loadAgents()
  loadSessions()
  rpcUnsubSessionsChanged = rpcStore.on('sessions.changed', scheduleSessionRefresh)
})

onUnmounted(() => {
  if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
  if (sessionRefreshTimer) clearTimeout(sessionRefreshTimer)
  if (rpcUnsubSessionsChanged) rpcUnsubSessionsChanged()
  window.removeEventListener('resize', syncMobileSidebar)
})

</script>
