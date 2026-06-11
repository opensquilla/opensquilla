<script lang="ts">
export type SidebarFamilyId = 'chats' | 'channels' | 'automations'

export interface SidebarConversationItem {
  key: string
  title: string
  effectiveAgentId: string
  agentName: string
  sourceFamily: SidebarFamilyId
  runStatus: string
  runLabel: string
  updatedAt: number
  hasContractGaps: boolean
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'

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

const agentFilter = ref('')

const filteredItems = computed((): SidebarConversationItem[] => {
  if (!agentFilter.value) return props.items
  return props.items.filter(item => item.effectiveAgentId === agentFilter.value)
})

const agentFilterName = computed(() => {
  if (!agentFilter.value) return ''
  const match = props.items.find(item => item.effectiveAgentId === agentFilter.value)
  return match?.agentName || agentFilter.value
})

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
  <div class="sidebar-section sidebar-history" aria-label="Recent conversations">
    <div class="sidebar-recents-header">
      <span class="sidebar-recents-eyebrow">Recents</span>
      <button
        class="sidebar-refresh-btn"
        title="Refresh conversations"
        aria-label="Refresh conversations"
        :class="{ spinning: loading }"
        @click="emit('refresh')"
      >
        <Icon name="refresh" :size="12" />
      </button>
    </div>
    <div v-if="agentFilter" class="sidebar-filter-row">
      <button
        type="button"
        class="sidebar-agent-chip"
        :aria-label="`Clear agent filter: ${agentFilterName}`"
        @click="clearAgentFilter"
      >
        {{ agentFilterName }} <span aria-hidden="true">&times;</span>
      </button>
    </div>
    <div v-if="error" class="sidebar-history-empty">
      Unable to load sessions
    </div>
    <div v-else-if="filteredItems.length === 0" class="sidebar-history-empty">
      {{ agentFilter ? 'No matches' : 'No recent conversations' }}
    </div>
    <div v-else class="sidebar-history-list">
      <div v-for="item in filteredItems" :key="item.key" class="sidebar-history-row" :data-family="item.sourceFamily">
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
  </div>
</template>
