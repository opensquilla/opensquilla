<script lang="ts">
export type SidebarFamilyId = 'chats' | 'channels' | 'automations'

export interface SidebarConversationItem {
  key: string
  title: string
  effectiveAgentId: string
  agentName: string
  groupLabel: string
  groupKey: string
  sourceFamily: SidebarFamilyId
  runStatus: string
  runLabel: string
  updatedAt: number
  hasContractGaps: boolean
}

export const SIDEBAR_LIST_MODE_KEY = 'opensquilla-sidebar-conversation-mode'
export const SIDEBAR_COLLAPSED_GROUPS_KEY = 'opensquilla-sidebar-collapsed-groups'
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { runStatusLabelText } from '@/composables/useSessions'

type SidebarListMode = 'recent' | 'grouped'
type SidebarFilterId = 'all' | 'chats' | 'automations'

interface SidebarGroupView {
  id: string
  label: string
  items: SidebarConversationItem[]
  aggStatus: string
  aggLabel: string
  updatedAt: number
}

interface SidebarSectionView {
  id: SidebarFamilyId
  label: string
  groups: SidebarGroupView[]
}

const props = defineProps<{
  items: SidebarConversationItem[]
  error: boolean
  loading: boolean
  currentKey: string
  contractDebugEnabled: boolean
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'refresh'): void
}>()

const conversationFilters: Array<{ id: SidebarFilterId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'chats', label: 'Chats' },
  { id: 'automations', label: 'Automations' },
]

const familySections: Array<{ id: SidebarFamilyId; label: string }> = [
  { id: 'chats', label: 'Chats' },
  { id: 'automations', label: 'Automations' },
  { id: 'channels', label: 'Channels' },
]

// Active statuses outrank terminal ones so a group header lights up while work runs.
const aggregateStatusPriority = ['running', 'queued', 'failed', 'timeout', 'interrupted', 'cancelled']

function readStoredMode(): SidebarListMode {
  try {
    const saved = localStorage.getItem(SIDEBAR_LIST_MODE_KEY)
    if (saved === 'recent' || saved === 'grouped') return saved
  } catch {
    // ignore
  }
  return 'recent'
}

function readCollapsedGroups(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(SIDEBAR_COLLAPSED_GROUPS_KEY) || '[]')
    if (Array.isArray(saved)) return saved.filter((value): value is string => typeof value === 'string')
  } catch {
    // ignore
  }
  return []
}

const mode = ref<SidebarListMode>(readStoredMode())
const familyFilter = ref<SidebarFilterId>('all')
const agentFilter = ref('')
const collapsedGroups = ref<string[]>(readCollapsedGroups())

const filteredItems = computed((): SidebarConversationItem[] => {
  let items = props.items
  if (familyFilter.value !== 'all') items = items.filter(item => item.sourceFamily === familyFilter.value)
  if (agentFilter.value) items = items.filter(item => item.effectiveAgentId === agentFilter.value)
  return items
})

const hasActiveFilter = computed(() => familyFilter.value !== 'all' || !!agentFilter.value)

const agentFilterName = computed(() => {
  if (!agentFilter.value) return ''
  const match = props.items.find(item => item.effectiveAgentId === agentFilter.value)
  return match?.agentName || agentFilter.value
})

function aggregateStatus(items: SidebarConversationItem[]): string {
  for (const status of aggregateStatusPriority) {
    if (items.some(item => item.runStatus === status)) return status
  }
  return 'idle'
}

const groupedSections = computed((): SidebarSectionView[] => {
  const sections: SidebarSectionView[] = []
  for (const family of familySections) {
    const familyItems = filteredItems.value.filter(item => item.sourceFamily === family.id)
    if (!familyItems.length) continue
    const groups = new Map<string, SidebarGroupView>()
    for (const item of familyItems) {
      const label = family.id === 'chats'
        ? (item.agentName || 'Agent')
        : (item.groupLabel || (family.id === 'automations' ? 'Automation' : 'Channel'))
      const id = `${family.id}:${family.id === 'chats' ? item.effectiveAgentId : (item.groupKey || label)}`
      const existing = groups.get(id)
      if (existing) {
        existing.items.push(item)
        existing.updatedAt = Math.max(existing.updatedAt, item.updatedAt || 0)
      } else {
        groups.set(id, { id, label, items: [item], aggStatus: 'idle', aggLabel: '', updatedAt: item.updatedAt || 0 })
      }
    }
    const sorted = Array.from(groups.values())
      .map(group => {
        const aggStatus = aggregateStatus(group.items)
        return { ...group, aggStatus, aggLabel: runStatusLabelText(aggStatus) }
      })
      .sort((a, b) => b.updatedAt - a.updatedAt)
    sections.push({ id: family.id, label: family.label, groups: sorted })
  }
  return sections
})

function setMode(next: SidebarListMode) {
  mode.value = next
  try { localStorage.setItem(SIDEBAR_LIST_MODE_KEY, next) } catch { /* ignore */ }
}

function isCollapsed(groupId: string): boolean {
  return collapsedGroups.value.includes(groupId)
}

function toggleGroup(groupId: string) {
  collapsedGroups.value = isCollapsed(groupId)
    ? collapsedGroups.value.filter(id => id !== groupId)
    : [...collapsedGroups.value, groupId]
  try { localStorage.setItem(SIDEBAR_COLLAPSED_GROUPS_KEY, JSON.stringify(collapsedGroups.value)) } catch { /* ignore */ }
}

function toggleAgentFilter(agentId: string) {
  agentFilter.value = agentFilter.value === agentId ? '' : agentId
}

function clearAgentFilter() {
  agentFilter.value = ''
}

function agentInitial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || '?'
}
</script>

<template>
  <div class="sidebar-section sidebar-history" :data-conversation-mode="mode" aria-label="Conversations">
    <div class="sidebar-section-header">
      <div class="sidebar-mode-toggle" role="group" aria-label="Conversation list mode">
        <button
          type="button"
          class="sidebar-mode-btn"
          :class="{ 'is-active': mode === 'recent' }"
          :aria-pressed="mode === 'recent'"
          @click="setMode('recent')"
        >
          Recent
        </button>
        <button
          type="button"
          class="sidebar-mode-btn"
          :class="{ 'is-active': mode === 'grouped' }"
          :aria-pressed="mode === 'grouped'"
          @click="setMode('grouped')"
        >
          Grouped
        </button>
      </div>
      <button
        class="sidebar-refresh-btn"
        title="Refresh conversations"
        :class="{ spinning: loading }"
        @click="emit('refresh')"
      >
        <Icon name="refresh" :size="12" />
      </button>
    </div>
    <div class="sidebar-filter-row" aria-label="Filter conversations">
      <button
        v-for="filter in conversationFilters"
        :key="filter.id"
        type="button"
        class="sidebar-filter-chip"
        :class="{ 'is-active': familyFilter === filter.id }"
        :aria-pressed="familyFilter === filter.id"
        @click="familyFilter = filter.id"
      >
        {{ filter.label }}
      </button>
      <button
        v-if="agentFilter"
        type="button"
        class="sidebar-filter-chip sidebar-agent-chip is-active"
        :title="`Clear agent filter: ${agentFilterName}`"
        @click="clearAgentFilter"
      >
        {{ agentFilterName }} <span aria-hidden="true">&times;</span>
      </button>
    </div>
    <div v-if="error" class="sidebar-history-empty">
      Unable to load sessions
    </div>
    <div v-else-if="filteredItems.length === 0" class="sidebar-history-empty">
      {{ hasActiveFilter ? 'No matches' : 'No recent conversations' }}
    </div>
    <div v-else-if="mode === 'recent'" class="sidebar-history-list">
      <div v-for="item in filteredItems" :key="item.key" class="sidebar-history-row">
        <button
          class="sidebar-history-item"
          :class="{ 'is-current': item.key === currentKey }"
          :title="item.title"
          @click="emit('select', item.key)"
        >
          <span class="sidebar-history-dot" :class="`status--${item.runStatus}`" />
          <span class="sidebar-history-title">{{ item.title }}</span>
          <span v-if="contractDebugEnabled && item.hasContractGaps" class="sidebar-history-gap" title="Backend session-list-v1 contract fields are missing">Gap</span>
          <span v-if="item.runStatus !== 'idle'" class="sidebar-history-run">{{ item.runLabel }}</span>
        </button>
        <button
          type="button"
          class="sidebar-agent-badge"
          :class="{ 'is-active': agentFilter === item.effectiveAgentId }"
          :aria-pressed="agentFilter === item.effectiveAgentId"
          :aria-label="`Filter by ${item.agentName}`"
          :title="`Filter by ${item.agentName}`"
          @click="toggleAgentFilter(item.effectiveAgentId)"
        >
          {{ agentInitial(item.agentName) }}
        </button>
      </div>
    </div>
    <div v-else class="sidebar-history-list sidebar-history-list--grouped">
      <template v-for="section in groupedSections" :key="section.id">
        <div class="sidebar-family-label">{{ section.label }}</div>
        <div
          v-for="group in section.groups"
          :key="group.id"
          class="sidebar-group"
          :class="{ 'is-collapsed': isCollapsed(group.id) }"
        >
          <button
            type="button"
            class="sidebar-group-header"
            :aria-expanded="!isCollapsed(group.id)"
            @click="toggleGroup(group.id)"
          >
            <Icon class="sidebar-group-chevron" name="chevronDown" :size="12" />
            <span class="sidebar-group-name">{{ group.label }}</span>
            <span class="sidebar-group-count">{{ group.items.length }}</span>
            <span
              v-if="group.aggStatus !== 'idle'"
              class="sidebar-history-dot sidebar-group-dot"
              :class="`status--${group.aggStatus}`"
              role="img"
              :aria-label="group.aggLabel"
              :title="group.aggLabel"
            />
          </button>
          <div v-show="!isCollapsed(group.id)" class="sidebar-group-items">
            <div v-for="item in group.items" :key="item.key" class="sidebar-history-row">
              <button
                class="sidebar-history-item"
                :class="{ 'is-current': item.key === currentKey }"
                :title="item.title"
                @click="emit('select', item.key)"
              >
                <span class="sidebar-history-dot" :class="`status--${item.runStatus}`" />
                <span class="sidebar-history-title">{{ item.title }}</span>
                <span v-if="contractDebugEnabled && item.hasContractGaps" class="sidebar-history-gap" title="Backend session-list-v1 contract fields are missing">Gap</span>
                <span v-if="item.runStatus !== 'idle'" class="sidebar-history-run">{{ item.runLabel }}</span>
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
