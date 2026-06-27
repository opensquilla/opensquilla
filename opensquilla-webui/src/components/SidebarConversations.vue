<script lang="ts">
import type { SidebarSection, SidebarSectionFamily, SidebarSectionRow } from '@/composables/useSessions'

export type { SidebarSection, SidebarSectionFamily, SidebarSectionRow } from '@/composables/useSessions'

/** Legacy family id kept for the agent-initial filter callers. */
export type SidebarFamilyId = SidebarSectionFamily

/**
 * A rendered sidebar row: the pure `SidebarSectionRow` produced by
 * `arrangeSidebarSections`, with `agentName` resolved by App.vue (the composable
 * leaves it empty so the display-name lookup stays in one place).
 */
export type SidebarConversationItem = SidebarSectionRow

const COLLAPSE_STORAGE_KEY = 'opensquilla-sidebar-sections'

export function readSidebarCollapsedState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, boolean> : {}
  } catch {
    return {}
  }
}

function writeSidebarCollapsedState(state: Record<string, boolean>) {
  try {
    localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

export { COLLAPSE_STORAGE_KEY, writeSidebarCollapsedState }
export type { SidebarSection as SidebarSectionType }
</script>

<script setup lang="ts">
import { computed, nextTick, ref, type ComponentPublicInstance } from 'vue'
import Icon from './Icon.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useDocumentEvent } from '@/composables/useDocumentEvent'

const props = defineProps<{
  sections: SidebarSection[]
  error: boolean
  loading: boolean
  currentKey: string
  contractDebugEnabled: boolean
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'refresh'): void
  (e: 'rename', payload: { key: string; title: string }): void
  (e: 'delete', key: string): void
  (e: 'new-chat'): void
}>()

const { confirm } = useConfirm()

/* ── Agent filter (lives within the Chats section) ─────────────────── */

const agentFilter = ref('')

function toggleAgentFilter(agentId: string) {
  agentFilter.value = agentFilter.value === agentId ? '' : agentId
}

function clearAgentFilter() {
  agentFilter.value = ''
}

const agentFilterName = computed(() => {
  if (!agentFilter.value) return ''
  for (const section of props.sections) {
    const match = section.rows.find(row => row.effectiveAgentId === agentFilter.value)
    if (match) return match.agentName || agentFilter.value
  }
  return agentFilter.value
})

function agentInitial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || '?'
}

/* ── Collapsible sections ──────────────────────────────────────────── */

// Persisted collapse state, keyed by family. A family is open unless an
// explicit `true` (collapsed) flag was stored for it; Chats opens by default.
const collapsed = ref<Record<string, boolean>>(readSidebarCollapsedState())

function isCollapsed(family: SidebarFamilyId): boolean {
  return collapsed.value[family] === true
}

function toggleSection(family: SidebarFamilyId) {
  const next = { ...collapsed.value, [family]: !isCollapsed(family) }
  collapsed.value = next
  writeSidebarCollapsedState(next)
}

// Sections with at least one row, honoring the agent filter inside Chats.
const visibleSections = computed(() => {
  return props.sections
    .map(section => ({
      ...section,
      rows: section.family === 'chats' && agentFilter.value
        ? section.rows.filter(row => row.effectiveAgentId === agentFilter.value)
        : section.rows,
    }))
    .filter(section => section.rows.length > 0)
})

// Total rendered rows: drives the onboarding empty-state and the filter's
// "No matches" message separately from a true first-run empty list.
const totalRows = computed(() =>
  props.sections.reduce((sum, section) => sum + section.rows.length, 0),
)

const hasFilterMatches = computed(() =>
  visibleSections.value.some(section => section.rows.length > 0),
)

/* ── Per-row ⋯ menu + inline rename ────────────────────────────────── */

const openMenuKey = ref('')
// The ⋯ trigger that opened the active menu, captured so Escape can return
// focus to it. A function-ref on the single open .sidebar-row-menu scopes the
// roving-focus queries (only one menu renders at a time).
const menuTriggerEl = ref<HTMLElement | null>(null)
const openMenuEl = ref<HTMLElement | null>(null)
function setOpenMenu(el: Element | ComponentPublicInstance | null) {
  openMenuEl.value = el instanceof HTMLElement ? el : null
}
// Fixed-position style for the teleported menu, computed from the trigger rect
// on open so the menu escapes the Recents scroll-clip.
const menuStyle = ref<Record<string, string>>({})
const renamingKey = ref('')
const renameDraft = ref('')
// A function ref captures the single active rename input. A string ref inside
// the v-for would collect into an array even though only one input renders, so
// the explicit callback keeps a direct element handle for focus/select.
const renameInputEl = ref<HTMLInputElement | null>(null)
function setRenameInput(el: Element | ComponentPublicInstance | null) {
  renameInputEl.value = el instanceof HTMLInputElement ? el : null
}
// Guards the blur-saves behavior so an Enter/Esc keystroke does not also fire a
// duplicate save through the input's blur handler.
let renameCommitting = false

function toggleMenu(key: string, event?: Event) {
  if (openMenuKey.value === key) {
    closeMenu()
    return
  }
  openMenuKey.value = key
  const trigger = event?.currentTarget
  menuTriggerEl.value = trigger instanceof HTMLElement ? trigger : null
  // The menu is teleported to <body>; anchor it to the trigger, flipping upward
  // near the viewport bottom so the Delete item is never clipped off-screen.
  if (menuTriggerEl.value) {
    const r = menuTriggerEl.value.getBoundingClientRect()
    const openUp = r.bottom + 100 > window.innerHeight
    menuStyle.value = {
      position: 'fixed',
      left: `${r.right}px`,
      top: `${openUp ? r.top : r.bottom + 4}px`,
      transform: openUp ? 'translate(-100%, -100%)' : 'translateX(-100%)',
    }
  }
  // Move focus into the menu so keyboard users land on an actionable item.
  nextTick(() => {
    const items = openMenuEl.value?.querySelectorAll<HTMLElement>('.sidebar-row-menu__item')
    items?.[0]?.focus()
  })
}

function closeMenu() {
  openMenuKey.value = ''
  openMenuEl.value = null
  menuTriggerEl.value = null
}

// Escape closes and returns focus to the row's ⋯ trigger; arrows rove between
// the menu items, wrapping at the ends.
function onMenuKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    const trigger = menuTriggerEl.value
    closeMenu()
    nextTick(() => trigger?.focus())
    return
  }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const items = Array.from(
    openMenuEl.value?.querySelectorAll<HTMLElement>('.sidebar-row-menu__item') ?? [],
  )
  if (!items.length) return
  e.preventDefault()
  const current = items.indexOf(document.activeElement as HTMLElement)
  const delta = e.key === 'ArrowDown' ? 1 : -1
  const next = (current + delta + items.length) % items.length
  items[next]?.focus()
}

useDocumentEvent('click', (e) => {
  if (!openMenuKey.value) return
  if (e.target instanceof Node) {
    const host = (e.target as Element).closest?.('.sidebar-row-menu-wrap, .sidebar-row-menu')
    if (host) return
  }
  closeMenu()
})

function startRename(row: SidebarConversationItem) {
  closeMenu()
  renamingKey.value = row.key
  renameDraft.value = row.title
  renameCommitting = false
  nextTick(() => {
    renameInputEl.value?.focus()
    renameInputEl.value?.select()
  })
}

function commitRename() {
  if (renameCommitting) return
  const key = renamingKey.value
  if (!key) return
  renameCommitting = true
  const title = renameDraft.value.trim()
  const original = props.sections
    .flatMap(section => section.rows)
    .find(row => row.key === key)?.title || ''
  renamingKey.value = ''
  renameDraft.value = ''
  if (title && title !== original) emit('rename', { key, title })
}

function cancelRename() {
  renameCommitting = true
  renamingKey.value = ''
  renameDraft.value = ''
}

function onRenameBlur() {
  // Enter/Esc already settled this row; only a genuine focus-loss commits.
  if (renameCommitting) return
  commitRename()
}

async function requestDelete(row: SidebarConversationItem) {
  closeMenu()
  const ok = await confirm({
    title: 'Delete session',
    body: `Delete session "${row.title}"? This cannot be undone.`,
    primaryLabel: 'Delete',
  })
  if (!ok) return
  emit('delete', row.key)
}

function onSelectRow(row: SidebarConversationItem) {
  if (renamingKey.value === row.key) return
  emit('select', row.key)
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

    <!-- Filtered to nothing within the Chats agent filter -->
    <div v-else-if="agentFilter && !hasFilterMatches" class="sidebar-history-empty">
      No matches
    </div>

    <!-- First-run onboarding: no sessions exist yet -->
    <div v-else-if="totalRows === 0" class="sidebar-onboarding">
      <p class="sidebar-onboarding__lead">No conversations yet.</p>
      <button type="button" class="sidebar-onboarding__cta" @click="emit('new-chat')">
        <Icon name="plus" :size="14" />
        <span>Start a chat</span>
      </button>
      <div class="sidebar-onboarding__links">
        <router-link to="/sessions" class="sidebar-onboarding__link">Sessions</router-link>
        <router-link to="/overview" class="sidebar-onboarding__link">Overview</router-link>
      </div>
    </div>

    <div v-else class="sidebar-history-list">
      <div
        v-for="section in visibleSections"
        :key="section.family"
        class="sidebar-group"
        :data-family="section.family"
      >
        <button
          type="button"
          class="sidebar-group__header"
          :aria-expanded="!isCollapsed(section.family)"
          :aria-controls="`sidebar-group-${section.family}`"
          @click="toggleSection(section.family)"
        >
          <Icon class="sidebar-group__chevron" name="chevronRight" :size="12" />
          <span class="sidebar-group__label">{{ section.label }}</span>
          <span class="sidebar-group__count">{{ section.rows.length }}</span>
        </button>

        <div
          v-show="!isCollapsed(section.family)"
          :id="`sidebar-group-${section.family}`"
          class="sidebar-group__body"
        >
          <div
            v-for="row in section.rows"
            :key="row.key"
            class="sidebar-history-row"
            :data-family="section.family"
            :data-depth="row.depth"
            :style="{ '--row-depth': row.depth }"
          >
            <span v-if="row.depth > 0" class="sidebar-history-rail" aria-hidden="true" />

            <!-- Inline rename input replaces the row button while editing -->
            <input
              v-if="renamingKey === row.key"
              :ref="setRenameInput"
              v-model="renameDraft"
              class="sidebar-history-rename"
              type="text"
              :aria-label="`Rename ${row.title}`"
              @keydown.enter.prevent="commitRename"
              @keydown.esc.prevent="cancelRename"
              @blur="onRenameBlur"
            />

            <button
              v-else
              class="sidebar-history-item"
              :class="{ 'is-current': row.key === currentKey }"
              :title="row.title"
              @click="onSelectRow(row)"
            >
              <span
                class="sidebar-history-dot"
                :class="`status--${row.runStatus}`"
                role="img"
                :aria-label="`Status: ${row.runLabel}`"
              />
              <span class="sidebar-history-title">{{ row.title }}</span>
              <span
                v-if="contractDebugEnabled && row.hasContractGaps"
                class="sidebar-history-gap"
                aria-label="Backend session-list-v1 contract fields are missing"
                title="Backend session-list-v1 contract fields are missing"
              >Gap</span>
              <span v-if="row.runStatus !== 'idle'" class="sidebar-history-run">{{ row.runLabel }}</span>
            </button>

            <!-- Chat-only ⋯ menu: rename + delete -->
            <div
              v-if="row.sessionKind === 'chat' && renamingKey !== row.key"
              class="sidebar-row-menu-wrap"
            >
              <button
                type="button"
                class="sidebar-row-menu-btn"
                aria-haspopup="menu"
                :aria-expanded="openMenuKey === row.key"
                :aria-label="`Actions for ${row.title}`"
                :title="`Actions for ${row.title}`"
                @click.stop="toggleMenu(row.key, $event)"
              >
                <span aria-hidden="true">&#8943;</span>
              </button>
              <Teleport to="body">
              <div
                v-if="openMenuKey === row.key"
                :ref="setOpenMenu"
                class="sidebar-row-menu"
                :style="menuStyle"
                role="menu"
                :aria-label="`Actions for ${row.title}`"
                @keydown="onMenuKeydown"
              >
                <button
                  type="button"
                  class="sidebar-row-menu__item"
                  role="menuitem"
                  @click.stop="startRename(row)"
                >
                  <Icon name="pencil" :size="14" />
                  <span>Rename</span>
                </button>
                <button
                  type="button"
                  class="sidebar-row-menu__item sidebar-row-menu__item--danger"
                  role="menuitem"
                  @click.stop="requestDelete(row)"
                >
                  <Icon name="trash" :size="14" />
                  <span>Delete</span>
                </button>
              </div>
              </Teleport>
            </div>

            <!-- Agent-initial badge: indicator + click-to-filter (Chats only) -->
            <button
              v-else-if="section.family === 'chats' && renamingKey !== row.key"
              type="button"
              class="sidebar-agent-badge"
              :class="{ 'is-active': agentFilter === row.effectiveAgentId }"
              :aria-pressed="agentFilter === row.effectiveAgentId"
              :aria-label="`Filter by ${row.agentName}`"
              :title="`Filter by ${row.agentName}`"
              @click.stop="toggleAgentFilter(row.effectiveAgentId)"
            >
              {{ agentInitial(row.agentName) }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
