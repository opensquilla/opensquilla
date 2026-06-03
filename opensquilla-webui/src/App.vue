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
    <div class="sidebar-section">
      <router-link
        v-for="route in quickRoutes"
        :key="route.path"
        :to="route.path"
        class="sidebar-fn-item"
        :class="{ 'is-active': $route.path === route.path }"
        @click="handleNavClick"
      >
        <Icon :name="route.icon" :size="18" />
        <span>{{ route.title }}</span>
        <span v-if="route.path === '/approvals' && appStore.approvalCount > 0" class="nav-badge">
          {{ appStore.approvalCount }}
        </span>
      </router-link>
    </div>

    <!-- Conversations -->
    <div class="sidebar-section sidebar-history">
      <div class="sidebar-section-header">
        <Icon name="chat" :size="18" />
        <span>Conversations</span>
        <button
          class="sidebar-refresh-btn"
          title="Refresh conversations"
          :class="{ spinning: isLoading }"
          @click="loadSessions"
        >
          <Icon name="refresh" :size="12" />
        </button>
      </div>
      <div v-if="sessionListError" class="sidebar-history-empty">
        Unable to load sessions
      </div>
      <div v-else-if="conversationFamilies.length === 0" class="sidebar-history-empty">
        No recent conversations
      </div>
      <div v-else class="sidebar-history-list">
        <div v-for="family in conversationFamilies" :key="family.id" class="sidebar-history-agent sidebar-history-family">
          <button
            class="sidebar-history-agent-toggle"
            :aria-expanded="isConversationGroupExpanded(family.id)"
            @click="toggleConversationGroup(family.id)"
          >
            <Icon :name="isConversationGroupExpanded(family.id) ? 'chevronDown' : 'chevronRight'" :size="14" />
            <Icon :name="family.icon" :size="15" />
            <span class="sidebar-history-agent-name">{{ family.label }}</span>
            <span class="sidebar-history-agent-count">{{ family.count }}</span>
          </button>
          <div v-if="isConversationGroupExpanded(family.id)" class="sidebar-history-agent-items sidebar-history-family-items">
            <div v-for="group in family.groups" :key="`${family.id}:${group.label}`" class="sidebar-history-agent sidebar-history-local">
              <button
                class="sidebar-history-agent-toggle sidebar-history-local-toggle"
                :aria-expanded="isConversationGroupExpanded(`${family.id}:${group.label}`)"
                @click="toggleConversationGroup(`${family.id}:${group.label}`)"
              >
                <Icon :name="isConversationGroupExpanded(`${family.id}:${group.label}`) ? 'chevronDown' : 'chevronRight'" :size="13" />
                <span class="sidebar-history-agent-name">{{ group.label }}</span>
                <span class="sidebar-history-agent-count">{{ group.items.length }}</span>
              </button>
              <div v-if="isConversationGroupExpanded(`${family.id}:${group.label}`)" class="sidebar-history-agent-items">
                <button
                  v-for="item in group.items"
                  :key="item.key"
                  class="sidebar-history-item"
                  :class="{ 'is-current': isCurrentSession(item.key) }"
                  :title="item.key"
                  @click="switchToSession(item.key)"
                >
                  <span class="sidebar-history-dot" :class="`status--${item.runStatus}`" />
                  <span class="sidebar-history-key">
                    <span class="sidebar-history-title">{{ item.title }}</span>
                    <span class="sidebar-history-meta">{{ item.meta }}</span>
                  </span>
                  <span v-if="item.hasContractGaps" class="sidebar-history-gap" title="Backend session-list-v1 contract fields are missing">Gap</span>
                  <span v-if="item.runStatus !== 'idle'" class="sidebar-history-run">{{ item.runLabel }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom links -->
    <div class="sidebar-bottom">
      <router-link
        v-for="route in bottomRoutes"
        :key="route.path"
        :to="route.path"
        class="sidebar-fn-item"
        :class="{ 'is-active': $route.path === route.path }"
        @click="handleNavClick"
      >
        <Icon :name="route.icon" :size="16" />
        <span>{{ route.title }}</span>
      </router-link>
    </div>
  </nav>

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
      'main--chat': $route.path === '/chat',
      'main--chat-sidebar-collapsed': $route.path === '/chat' && !appStore.sidebarOpen,
    }"
  >
    <header class="topbar" :class="{ 'topbar--chat': $route.path === '/chat' }">
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
          @click="$router.push('/approvals')"
          title="Open approvals"
        >
          Approval required
        </button>
        <span class="conn-pill" :class="rpcStore.state">{{ rpcStore.state }}</span>
        <button class="btn btn--icon btn--ghost" @click="appStore.cycleTheme" :title="`Theme: ${appStore.theme}`">
          <Icon :name="themeIconName" :size="16" />
        </button>
      </div>
    </header>
    <main class="content" :class="{ 'content--chat': $route.path === '/chat' }" id="content">
      <ErrorBoundary>
        <router-view />
      </ErrorBoundary>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from './stores/app'
import { useRpcStore } from './stores/rpc'
import { useSessions, type SessionItem } from './composables/useSessions'
import type { IconName } from './utils/icons'
import Icon from './components/Icon.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import type { AgentOption, AgentsListResponse } from './types/rpc'

const appStore = useAppStore()
const rpcStore = useRpcStore()
const $route = useRoute()
const router = useRouter()
const { allSessions, sessionListError, isLoading, loadSessions } = useSessions()

type SidebarFamilyId = 'chats' | 'channels' | 'automations'

interface SidebarConversationItem {
  key: string
  title: string
  effectiveAgentId: string
  sourceFamily: SidebarFamilyId
  localGroupLabel: string
  meta: string
  runStatus: string
  runLabel: string
  updatedAt: number
  hasContractGaps: boolean
}

interface SidebarConversationGroup {
  label: string
  items: SidebarConversationItem[]
  updatedAt: number
}

interface SidebarConversationFamily {
  id: SidebarFamilyId
  label: string
  icon: IconName
  groups: SidebarConversationGroup[]
  count: number
  updatedAt: number
}

const agents = ref<AgentOption[]>([])
const agentListError = ref(false)
const newChatPickerOpen = ref(false)
const selectedNewChatAgentId = ref('main')
const expandedConversationGroups = ref<Record<string, boolean>>({})
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

function isCurrentSession(key: string): boolean {
  return key === currentSessionKey.value
}

function normalizeAgentId(agentId: string): string {
  const raw = String(agentId || '').trim().toLowerCase()
  if (!raw || raw === 'default') return 'main'
  const normalized = raw.replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '')
  return normalized && normalized !== 'default' ? normalized : 'main'
}

function webchatSessionKey(agentId: string, suffix = Math.random().toString(36).slice(2, 10)): string {
  return `agent:${normalizeAgentId(agentId)}:webchat:${suffix}`
}

function agentDisplayName(agentId: string): string {
  const agent = agents.value.find(a => a.id === agentId)
  return agent?.name || (agentId === 'main' ? 'Main Agent' : agentId)
}

function humanize(value: string): string {
  const cleaned = String(value || '').replace(/[_-]/g, ' ').trim()
  return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : ''
}

function conversationMeta(item: Pick<SessionItem, 'surface' | 'conversationKind' | 'threadLabel' | 'effectiveAgentId' | 'messageCount'>): string {
  const parts = [humanize(item.surface), humanize(item.conversationKind)]
    .filter(value => value && value !== 'unknown')
  if (item.threadLabel) parts.push(item.threadLabel)
  if (item.effectiveAgentId && item.effectiveAgentId !== 'unknown') parts.push(agentDisplayName(item.effectiveAgentId))
  if (item.messageCount != null) parts.push(`${item.messageCount} msg${item.messageCount === 1 ? '' : 's'}`)
  return parts.join(' · ') || 'Session'
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

function channelGroupLabel(item: SessionItem): string {
  const ctx = item.channelContext || null
  const channel = humanize(ctx?.name || item.surface || item.groupLabel || 'Channel')
  const target = ctx?.id || item.raw.lastTo || item.raw.last_to || ''
  return target ? `${channel} / ${target}` : channel
}

function automationGroupLabel(item: SessionItem): string {
  const cron = item.raw.cron || null
  return String(cron?.jobId || cron?.job_id || item.title || item.groupLabel || 'Automation')
}

function localGroupLabelForSession(item: SessionItem, family: SidebarFamilyId): string {
  if (family === 'chats') return agentDisplayName(item.effectiveAgentId)
  if (family === 'channels') return channelGroupLabel(item)
  return automationGroupLabel(item)
}

function familyLabel(id: SidebarFamilyId): string {
  if (id === 'chats') return 'Chats'
  if (id === 'channels') return 'Channels'
  return 'Automations'
}

function familyIcon(id: SidebarFamilyId): IconName {
  if (id === 'chats') return 'chat'
  if (id === 'channels') return 'channels'
  return 'cron'
}

// Main function routes (visible in sidebar) — Chat is accessed via history, not a dedicated button
const quickRoutes = computed(() => [
  { path: '/overview', title: 'Overview', icon: 'home' as const },
  { path: '/agents', title: 'Agents', icon: 'agents' as const },
  { path: '/skills', title: 'Skills', icon: 'skills' as const },
  { path: '/channels', title: 'Channels', icon: 'channels' as const },
  { path: '/cron', title: 'Cron', icon: 'cron' as const },
  { path: '/sessions', title: 'Sessions', icon: 'sessions' as const },
  { path: '/usage', title: 'Usage', icon: 'usage' as const },
])

// Bottom routes (secondary)
const bottomRoutes = computed(() => [
  { path: '/config', title: 'Config', icon: 'config' as const },
  { path: '/logs', title: 'Logs', icon: 'logs' as const },
  { path: '/approvals', title: 'Approvals', icon: 'approvals' as const },
])

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
    result.push({
      key,
      effectiveAgentId: item.effectiveAgentId,
      title: item.title,
      sourceFamily,
      localGroupLabel: localGroupLabelForSession(item, sourceFamily),
      meta: conversationMeta(item),
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
      sourceFamily: 'chats',
      title: local.title || 'New chat',
      localGroupLabel: agentDisplayName(local.effectiveAgentId),
      meta: `Webchat · Direct · ${agentDisplayName(local.effectiveAgentId)}`,
      runStatus: 'idle',
      runLabel: 'Idle',
      updatedAt: local.updatedAt,
      hasContractGaps: false,
    })
  }
  if (currentSessionKey.value && !seen.has(currentSessionKey.value) && !localChatSessions.value[currentSessionKey.value]) {
    result.push({
      key: currentSessionKey.value,
      effectiveAgentId: normalizeAgentId(currentSessionKey.value.split(':')[1] || 'main'),
      sourceFamily: 'chats',
      title: 'Current session',
      localGroupLabel: agentDisplayName(normalizeAgentId(currentSessionKey.value.split(':')[1] || 'main')),
      meta: 'Webchat · Direct',
      runStatus: 'idle',
      runLabel: 'Idle',
      updatedAt: Date.now(),
      hasContractGaps: true,
    })
  }
  return result.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 60)
})

const conversationFamilies = computed((): SidebarConversationFamily[] => {
  const familyMap = new Map<SidebarFamilyId, SidebarConversationFamily>()
  for (const item of sidebarConversations.value) {
    let family = familyMap.get(item.sourceFamily)
    if (!family) {
      family = {
        id: item.sourceFamily,
        label: familyLabel(item.sourceFamily),
        icon: familyIcon(item.sourceFamily),
        groups: [],
        count: 0,
        updatedAt: 0,
      }
      familyMap.set(item.sourceFamily, family)
    }
    let group = family.groups.find(candidate => candidate.label === item.localGroupLabel)
    if (!group) {
      group = { label: item.localGroupLabel, items: [], updatedAt: 0 }
      family.groups.push(group)
    }
    group.items.push(item)
    group.updatedAt = Math.max(group.updatedAt, item.updatedAt)
    family.count += 1
    family.updatedAt = Math.max(family.updatedAt, item.updatedAt)
  }

  const currentFamily = sidebarConversations.value.find(item => item.key === currentSessionKey.value)?.sourceFamily || null
  return Array.from(familyMap.values())
    .map(family => ({
      ...family,
      groups: family.groups
        .map(group => ({
          ...group,
          items: [...group.items].sort((a, b) => b.updatedAt - a.updatedAt),
        }))
        .sort((a, b) => b.updatedAt - a.updatedAt),
    }))
    .sort((a, b) => {
      if (currentFamily) {
        if (a.id === currentFamily && b.id !== currentFamily) return -1
        if (b.id === currentFamily && a.id !== currentFamily) return 1
      }
      return b.updatedAt - a.updatedAt
    })
})

let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let sessionRefreshTimer: ReturnType<typeof setTimeout> | null = null
let rpcUnsubSessionsChanged: (() => void) | null = null

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
  } catch (err: any) {
    console.warn('[App] agents.list error:', err?.message || err)
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
  const agentId = normalizeAgentId(selectedNewChatAgentId.value || 'main')
  const key = webchatSessionKey(agentId)
  localChatSessions.value = {
    ...localChatSessions.value,
    [key]: { effectiveAgentId: agentId, title: 'New chat', updatedAt: Date.now() },
  }
  closeNewChatPicker()
  router.push({ path: '/chat', query: { session: key } })
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

function isConversationGroupExpanded(key: string): boolean {
  if (Object.prototype.hasOwnProperty.call(expandedConversationGroups.value, key)) {
    return expandedConversationGroups.value[key] !== false
  }
  return true
}

function persistExpandedConversationGroups() {
  try {
    localStorage.setItem('opensquilla_sidebar_conversation_groups', JSON.stringify(expandedConversationGroups.value))
  } catch {}
}

function toggleConversationGroup(key: string) {
  expandedConversationGroups.value = {
    ...expandedConversationGroups.value,
    [key]: !isConversationGroupExpanded(key),
  }
  persistExpandedConversationGroups()
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

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  try {
    const raw = localStorage.getItem('opensquilla_sidebar_conversation_groups')
    if (raw) expandedConversationGroups.value = JSON.parse(raw)
  } catch {}
  loadAgents()
  loadSessions()
  rpcUnsubSessionsChanged = rpcStore.on('sessions.changed', scheduleSessionRefresh)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
  if (sessionRefreshTimer) clearTimeout(sessionRefreshTimer)
  if (rpcUnsubSessionsChanged) rpcUnsubSessionsChanged()
})

</script>
