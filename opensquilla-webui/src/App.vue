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
      <router-link
        to="/"
        class="sidebar-brand-link"
        aria-label="OpenSquilla home"
        @click="handleNavClick"
      >
        <img class="sidebar-brand-mark" :src="brandMarkUrl" alt="" aria-hidden="true" />
        <span class="sidebar-brand-text">OpenSquilla</span>
      </router-link>
      <button
        class="sidebar-dock-toggle"
        :title="appStore.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'"
        :aria-label="appStore.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'"
        @click="toggleDock"
      >
        <Icon :name="appStore.sidebarOpen ? 'panel-left-close' : 'panel-left-open'" :size="16" />
      </button>
    </div>

    <!-- New chat opens a draft instantly against the preferred agent; the agent
         can still be switched from the draft landing. -->
    <div class="sidebar-actions">
      <button
        class="sidebar-new-session"
        :title="newChatHint ? `Start a new chat (${newChatHint})` : 'Start a new chat'"
        @click="startNewChatInstant"
      >
        <Icon name="plus" :size="16" />
        <span class="sidebar-new-session__label">New chat</span>
        <!-- Badge tracks the configured binding and hides when the shortcut is
             disabled (Settings → Keyboard), so it never advertises a dead key. -->
        <kbd v-if="newChatHint" class="sidebar-kbd" aria-hidden="true">{{ newChatHint }}</kbd>
      </button>
      <!-- Canonical search / go-to. Replaces the rail Search row that truncated;
           the visible chord keeps the shortcut discoverable for mouse users. -->
      <button
        type="button"
        class="sidebar-cmd-btn"
        :title="`Search / Go to… (${commandPaletteHint})`"
        :aria-label="`Search and go to (press ${commandPaletteHint})`"
        aria-haspopup="dialog"
        :aria-expanded="commandPaletteOpen"
        @click="openCommandPalette"
      >
        <Icon name="search" :size="16" />
      </button>
    </div>

    <!-- Always-visible grouped nav index. Bounded and self-scrolling under a
         short viewport so it never squeezes Recents, which owns the elastic
         space below; every destination stays a labelled text row. -->
    <div class="sidebar-section sidebar-core" role="navigation" aria-label="Control navigation">
      <!-- Pinned level-1 rows (Sessions / Cron / Skills), single-sourced from the
           Work band of the route taxonomy so promoting a route is a one-line meta
           edit and the rail, the mobile drawer, and the palette never drift. -->
      <router-link
        v-for="item in workNav"
        :key="item.path"
        :to="item.path"
        class="sidebar-fn-item"
        :class="{ 'is-active': isNavActive(item.path) }"
        :aria-current="isNavActive(item.path) ? 'page' : undefined"
        @click="handleNavClick"
      >
        <Icon :name="item.icon" :size="16" />
        <span class="sidebar-fn-label">{{ item.title }}</span>
      </router-link>
      <!-- Manage / Monitor bands. Option B leans the DESKTOP rail to the
           command-palette-led essentials, so these are hidden on desktop
           (docked + hover) via CSS and reached through the palette / deep links.
           They stay rendered for the <=768px drawer ("More") so every
           destination is still a tap away on mobile; routes are unchanged. -->
      <div class="sidebar-core__managed">
        <template v-for="section in consoleSections" :key="section.group">
          <p class="sidebar-nav-group-label" aria-hidden="true">{{ section.label }}</p>
          <router-link
            v-for="route in section.items"
            :key="route.path"
            :to="route.path"
            class="sidebar-fn-item"
            :class="{ 'is-active': isNavActive(route.path) }"
            :aria-current="isNavActive(route.path) ? 'page' : undefined"
            @click="handleNavClick"
          >
            <Icon :name="route.icon" :size="16" />
            <span class="sidebar-fn-label">{{ route.title }}</span>
          </router-link>
        </template>
      </div>
      <!-- "More": the secondary destinations (Approvals / Agents / Channels /
           Overview / Usage / Logs). Desktop-only trigger; it carries the pending
           approval count so the urgency signal stays visible at level-1 without
           opening the popover. Hidden on mobile, where the bands render inline. -->
      <button
        ref="moreTriggerRef"
        type="button"
        class="sidebar-fn-item sidebar-more-btn"
        :class="{ 'is-open': moreOpen }"
        aria-haspopup="dialog"
        :aria-expanded="moreOpen"
        :aria-label="appStore.approvalCount > 0
          ? `More — ${appStore.approvalCount} approvals pending`
          : 'More'"
        @click="toggleMore"
      >
        <Icon name="menu" :size="16" />
        <span class="sidebar-fn-label">More</span>
        <span
          v-if="appStore.approvalCount > 0"
          class="sidebar-count-badge"
        >{{ appStore.approvalCount }}</span>
        <Icon v-else name="chevronDown" :size="14" class="sidebar-more-chevron" />
      </button>
    </div>

    <SidebarSetupBanner />

    <!-- Recent conversations -->
    <SidebarConversations
      :sections="sidebarSections"
      :error="sessionListError"
      :loading="isLoading"
      :current-key="currentSessionKey"
      :contract-debug-enabled="contractDebugEnabled"
      @select="switchToSession"
      @refresh="loadSessions"
      @rename="onRenameSession"
      @delete="onDeleteSession"
      @new-chat="startNewChatInstant"
    />

    <!-- Fixed footer: settings + connection state -->
    <div class="sidebar-foot">
      <button
        type="button"
        class="sidebar-fn-item"
        data-icon="settings"
        @click="openSettings"
      >
        <Icon name="settings" :size="16" />
        <span class="sidebar-fn-label">Settings</span>
      </button>
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

  <CommandPalette
    v-model:open="commandPaletteOpen"
    :hint="commandPaletteHint"
    @new-chat="onPaletteNewChat"
    @open-settings="onPaletteOpenSettings"
    @toggle-theme="onPaletteToggleTheme"
    @select-session="onPaletteSelectSession"
  />

  <!-- "More" popover: teleported to <body> so it escapes the rail's
       overflow:hidden and dock/hover transform. Approvals keeps its bespoke
       deep-link handler + count badge; the rest are plain destinations. -->
  <Teleport to="body">
    <div
      v-if="moreOpen"
      ref="morePopoverRef"
      class="sidebar-more-popover"
      :style="moreStyle"
      role="dialog"
      aria-label="More destinations"
    >
      <template v-for="section in consoleSections" :key="section.group">
        <p class="sidebar-nav-group-label">{{ section.label }}</p>
        <template v-for="route in section.items" :key="route.path">
          <button
            v-if="route.path === '/approvals'"
            type="button"
            class="sidebar-fn-item"
            :class="{ 'is-active': isNavActive('/approvals') }"
            :aria-current="isNavActive('/approvals') ? 'page' : undefined"
            @click="onMoreApprovals"
          >
            <Icon name="approvals" :size="16" />
            <span class="sidebar-fn-label">Approvals</span>
            <span
              v-if="appStore.approvalCount > 0"
              class="sidebar-count-badge"
              :aria-label="`${appStore.approvalCount} pending`"
            >{{ appStore.approvalCount }}</span>
          </button>
          <router-link
            v-else
            :to="route.path"
            class="sidebar-fn-item"
            :class="{ 'is-active': isNavActive(route.path) }"
            :aria-current="isNavActive(route.path) ? 'page' : undefined"
            @click="onMoreNavigate"
          >
            <Icon :name="route.icon" :size="16" />
            <span class="sidebar-fn-label">{{ route.title }}</span>
          </router-link>
        </template>
      </template>
    </div>
  </Teleport>

  <!-- Main content -->
  <div
    class="main"
    :class="{
      docked: appStore.sidebarOpen,
      'main--chat': isChatRoute,
      'main--chat-sidebar-collapsed': isChatRoute && !appStore.sidebarOpen,
      'main--tabbar-hidden': mobileKeyboardOpen,
    }"
  >
    <header class="topbar" :class="{ 'topbar--chat': isChatRoute }">
      <div class="topbar-left">
        <!-- Sidebar toggle — visible when sidebar is collapsed -->
        <button
          v-show="!appStore.sidebarOpen"
          class="sidebar-dock-toggle topbar-toggle"
          title="Expand sidebar"
          aria-label="Expand sidebar"
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
        <button
          v-if="webConfigEnabled"
          type="button"
          class="conn-pill conn-pill--link"
          :class="rpcStore.state"
          :title="`Connection: ${rpcStore.state} — manage in Settings`"
          aria-label="Manage gateway connection"
          @click="openConnectionSettings"
        >{{ rpcStore.state }}</button>
        <span v-else class="conn-pill" :class="rpcStore.state">{{ rpcStore.state }}</span>
        <div class="theme-menu-wrap">
          <button
            ref="themeButtonRef"
            class="btn btn--icon btn--ghost"
            title="Theme"
            aria-label="Theme"
            aria-haspopup="menu"
            :aria-expanded="themeMenuOpen"
            @click.stop="themeMenuOpen = !themeMenuOpen"
          >
            <Icon :name="themeIconName" :size="16" />
          </button>
          <div v-if="themeMenuOpen" class="theme-menu" role="menu" aria-label="Theme">
            <button
              v-for="opt in themeOptions"
              :key="opt.mode"
              type="button"
              class="theme-menu__item"
              role="menuitemradio"
              :aria-checked="appStore.theme === opt.mode"
              @click="pickTheme(opt.mode)"
            >
              <Icon :name="opt.icon" :size="15" />
              <span>{{ opt.label }}</span>
              <Icon v-if="appStore.theme === opt.mode" class="theme-menu__check" name="check" :size="14" />
            </button>
          </div>
        </div>
      </div>
    </header>
    <main class="content" :class="{ 'content--chat': isChatRoute }" id="content">
      <ErrorBoundary>
        <router-view v-slot="{ Component, route }">
          <Transition name="route-fade" mode="out-in">
            <KeepAlive v-if="route.meta.keepAlive" :max="5">
              <component :is="Component" :key="route.name" />
            </KeepAlive>
            <component v-else :is="Component" :key="route.name" />
          </Transition>
        </router-view>
      </ErrorBoundary>
    </main>
  </div>

  <!-- Mobile bottom tab bar (<=768px only; hides while the keyboard is up) -->
  <nav
    class="mobile-tabbar"
    :class="{ 'is-keyboard-open': mobileKeyboardOpen }"
    aria-label="Primary mobile"
  >
    <router-link
      to="/chat"
      class="mobile-tab"
      :class="{ 'is-active': isNavActive('/chat') }"
      @click="handleNavClick"
    >
      <Icon name="chat" :size="20" />
      <span class="mobile-tab__label">Chat</span>
    </router-link>
    <router-link
      to="/sessions"
      class="mobile-tab"
      :class="{ 'is-active': isNavActive('/sessions') }"
      @click="handleNavClick"
    >
      <Icon name="sessions" :size="20" />
      <span class="mobile-tab__label">Sessions</span>
    </router-link>
    <router-link
      to="/approvals"
      class="mobile-tab"
      :class="{ 'is-active': isNavActive('/approvals') }"
      @click="handleNavClick"
    >
      <Icon name="approvals" :size="20" />
      <span class="mobile-tab__label">Approvals</span>
      <span v-if="appStore.approvalCount > 0" class="mobile-tab__badge">{{ appStore.approvalCount }}</span>
    </router-link>
    <button
      type="button"
      class="mobile-tab"
      :class="{ 'is-active': appStore.sidebarOpen }"
      @click="appStore.setSidebarOpen(true)"
    >
      <Icon name="menu" :size="20" />
      <span class="mobile-tab__label">More</span>
    </button>
  </nav>

  <ToastHost />

  <ConfirmModal />

  <!-- Single app-wide announcer for the pending-approval count. The nav badge
       and topbar pill stay silent (no double-announce); this region carries the
       only spoken update when the count changes. -->
  <p class="app-approval-live" aria-live="polite" role="status">{{ approvalAnnouncement }}</p>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getPlatform } from '@/platform'
import { useDialogA11y } from '@/composables/useDialogA11y'
import { useAppStore, type ThemeMode, type PendingApproval } from './stores/app'
import { useRpcStore } from './stores/rpc'
import {
  arrangeSidebarSections,
  useSessions,
  type SessionItem,
  type SidebarSection,
  type SidebarSectionRow,
} from './composables/useSessions'
import Icon from './components/Icon.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import ToastHost from './components/ToastHost.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import SidebarConversations from './components/SidebarConversations.vue'
import SidebarSetupBanner from './components/SidebarSetupBanner.vue'
import CommandPalette from './components/CommandPalette.vue'
import { useDocumentEvent } from './composables/useDocumentEvent'
import { useAgentOptions } from './composables/useAgentOptions'
import { useToasts } from './composables/useToasts'
import { useNavigation } from './app/useNavigation'
import { normalizeAgentId } from './utils/chat/sessionKeys'
import type { RpcEventHandler } from '@/lib/rpc'
import { isMacPlatform } from './utils/browser'
import { useShortcutsStore } from './stores/shortcuts'
import { bindingMatches, formatBinding } from './utils/keychord'

const appStore = useAppStore()
const rpcStore = useRpcStore()
const shortcutsStore = useShortcutsStore()
const $route = useRoute()
const router = useRouter()
const { allSessions, sessionListError, isLoading, loadSessions } = useSessions()
const { consoleSections, bottomRoutes, workNav } = useNavigation()
const { pushToast } = useToasts()
const webConfigEnabled = getPlatform().capabilities.hasWebConfig

// Shared agents.list state + fetch (singleton): App.vue and ChatView's
// in-draft switcher use the same list and one fetch.
const { agents, loadAgents } = useAgentOptions()
const mobileKeyboardOpen = ref(false)
const commandPaletteOpen = ref(false)
const localChatSessions = ref<Record<string, { effectiveAgentId: string; title: string; updatedAt: number }>>({})
// Pending optimistic renames, keyed by session key; cleared after the next list
// reload returns the backend's canonical title.
const renameOverrides = ref<Record<string, string>>({})

const brandMarkUrl = computed(() => {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/img/opensquilla-mark.png`
})

// Display chords track the configurable bindings so the rail hint, the New chat
// badge, and the palette never drift from what the handler actually honours. A
// disabled shortcut yields an empty hint (the New chat badge then hides).
const isMac = isMacPlatform()
const commandPaletteHint = computed(() =>
  formatBinding(shortcutsStore.effectiveBinding('command-palette'), isMac))
const newChatHint = computed(() =>
  formatBinding(shortcutsStore.effectiveBinding('new-chat'), isMac))

const themeIconName = computed(() => {
  if (appStore.theme === 'system') return 'monitor'
  return appStore.resolvedTheme === 'dark' ? 'moon' : 'sun'
})

const themeMenuOpen = ref(false)
const themeButtonRef = ref<HTMLButtonElement | null>(null)
const themeOptions = [
  { mode: 'light', label: 'Light', icon: 'sun' },
  { mode: 'dark', label: 'Dark', icon: 'moon' },
  { mode: 'system', label: 'System', icon: 'monitor' },
] as const

function pickTheme(mode: ThemeMode) {
  appStore.setTheme(mode)
  themeMenuOpen.value = false
  themeButtonRef.value?.focus()
}

useDocumentEvent('click', (e) => {
  if (!themeMenuOpen.value) return
  const wrap = themeButtonRef.value?.closest('.theme-menu-wrap')
  if (wrap && e.target instanceof Node && !wrap.contains(e.target)) {
    themeMenuOpen.value = false
  }
})

// "More" popover: the secondary destinations on desktop. Built on the shared
// dialog-a11y composable (Tab-trap + Escape + focus restore to the trigger) and
// teleported to <body>, so it is anchored to the trigger via a fixed-position
// rect rather than nested inside the rail's overflow:hidden scroll container.
const moreOpen = ref(false)
const moreTriggerRef = ref<HTMLElement | null>(null)
const morePopoverRef = ref<HTMLElement | null>(null)
const moreStyle = ref<Record<string, string>>({})

useDialogA11y(morePopoverRef, moreOpen, () => { moreOpen.value = false })

function toggleMore() {
  if (moreOpen.value) {
    moreOpen.value = false
    return
  }
  const trigger = moreTriggerRef.value
  if (!trigger) return
  const r = trigger.getBoundingClientRect()
  // The trigger sits high in the rail (just below the pinned rows; Recents owns
  // the space beneath it), so the popover opens downward, left-aligned, capped to
  // the room below so a long list scrolls inside instead of overflowing.
  moreStyle.value = {
    position: 'fixed',
    left: `${r.left}px`,
    top: `${r.bottom + 4}px`,
    minWidth: `${Math.max(r.width, 220)}px`,
    maxHeight: `${Math.max(160, window.innerHeight - r.bottom - 12)}px`,
  }
  moreOpen.value = true
}

function onMoreNavigate() {
  moreOpen.value = false
  handleNavClick()
}

function onMoreApprovals() {
  moreOpen.value = false
  // Preserve the blocked-session deep-link + selection behavior of the row.
  onApprovalsRowClick()
}

// Pointer dismissal scoped to the popover + its trigger (mirrors the theme menu);
// useDialogA11y already owns Escape + focus restore, so no second key handler.
useDocumentEvent('click', (e) => {
  if (!moreOpen.value) return
  const target = e.target
  if (
    target instanceof Element &&
    (target.closest('.sidebar-more-popover') || target.closest('.sidebar-more-btn'))
  ) {
    return
  }
  moreOpen.value = false
})

// Current session key from ChatView via URL
const currentSessionKey = computed(() => {
  return ($route.query.session as string) || ''
})

// Chat layout applies to both the session view and the draft route.
const isChatRoute = computed(() => $route.path === '/chat' || $route.path === '/chat/new')

// The web Settings overlay (route-mounted dialog) is open on these routes. It
// owns its own Escape/focus, so App-level keyboard shortcuts defer to it. On
// desktop `/settings` is a full page (DesktopSettingsView), not an overlay, so
// this stays false there.
const settingsOverlayOpen = computed(() =>
  webConfigEnabled && ($route.name === 'settings' || $route.name === 'settings-section'))

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

// A draft / current-session row the backend list does not yet carry. The
// sidebar arranger reads only a handful of fields off the SessionItem, so a
// synthetic chat row carries just those plus a stub `raw` (no parent → root).
function syntheticChatSession(
  key: string,
  effectiveAgentId: string,
  title: string,
  updatedAt: number,
): SessionItem {
  return {
    key,
    title,
    subtitle: '',
    groupLabel: normalizeAgentId(effectiveAgentId),
    effectiveAgentId,
    sessionKind: 'chat',
    surface: 'webchat',
    conversationKind: 'direct',
    threadLabel: '',
    channelContext: null,
    status: 'idle',
    visualStatus: 'idle',
    runStatus: 'idle',
    runLabel: 'Idle',
    messageCount: null,
    updatedAt,
    interactive: true,
    forkedFromParent: false,
    contractGaps: [],
    raw: { key },
  }
}

// Sessions to arrange into the sidebar: the backend list plus the local draft
// and the current chat session when the list does not carry them yet (both
// injected as Chats so a brand-new conversation appears immediately).
const sidebarSessionItems = computed((): SessionItem[] => {
  const items: SessionItem[] = []
  const seen = new Set<string>()
  for (const item of allSessions.value) {
    if (!item.key || item.key === 'unknown') continue
    seen.add(item.key)
    items.push(item)
  }
  for (const [key, local] of Object.entries(localChatSessions.value)) {
    if (seen.has(key)) continue
    seen.add(key)
    items.push(syntheticChatSession(key, local.effectiveAgentId, local.title || 'New chat', local.updatedAt))
  }
  const current = currentSessionKey.value
  if (current && !seen.has(current)) {
    const currentAgentId = normalizeAgentId(current.split(':')[1] || 'main')
    items.push(syntheticChatSession(current, currentAgentId, 'Current session', Date.now()))
  }
  return items
})

// Collapsible family sections (Chats / Channels / Automations). Row titles and
// agent names are resolved here so the raw-session-id scrub and the display-name
// lookup stay in App.vue; subagents indent under their parent via the helper.
const sidebarSections = computed((): SidebarSection[] => {
  const byKey = new Map(sidebarSessionItems.value.map(item => [item.key, item]))
  return arrangeSidebarSections(sidebarSessionItems.value).map(section => ({
    ...section,
    rows: section.rows.map((row): SidebarSectionRow => {
      const source = byKey.get(row.key)
      const title = renameOverrides.value[row.key]
        || (source ? sidebarConversationTitle(source) : row.title)
      return {
        ...row,
        title,
        agentName: agentDisplayName(normalizeAgentId(row.effectiveAgentId)),
      }
    }),
  }))
})

let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let sessionRefreshTimer: ReturnType<typeof setTimeout> | null = null
let rpcUnsubSessionsChanged: (() => void) | null = null

function syncMobileSidebar() {
  if (window.innerWidth <= 768 && appStore.sidebarOpen) {
    appStore.setSidebarOpen(false)
  }
}

// Hide the bottom tab bar while the on-screen keyboard owns the bottom edge.
// A visual-viewport shrink well beyond browser-chrome changes (>140px) is the
// simplest cross-platform signal; per-input focus tracking was considered and
// dropped as fragile. When the heuristic misses, the bar just stays visible.
function syncMobileKeyboard() {
  const viewport = window.visualViewport
  if (!viewport) return
  mobileKeyboardOpen.value = window.innerWidth <= 768 && window.innerHeight - viewport.height > 140
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
  const chats = sidebarSections.value.find(section => section.family === 'chats')
  const latest = chats?.rows.find(row => row.effectiveAgentId !== 'unknown')?.effectiveAgentId
  return latest || 'main'
}

// Primary new-chat path: open a draft instantly against the preferred agent
// (last-used, or main). The agent can still be switched from the draft landing.
function startNewChatInstant() {
  handleNavClick()
  router.push({ path: '/chat/new', query: { agent: preferredAgentId() } })
}

// Command palette: ⌘K / Ctrl+K and the rail "Search / Go to…" row both open it.
// Its action commands route back through the existing handlers so behaviour stays
// single-sourced (new chat opens a draft, Settings reuses the footer path).
function openCommandPalette() {
  handleNavClick()
  commandPaletteOpen.value = true
}

function onPaletteNewChat() {
  startNewChatInstant()
}

function onPaletteOpenSettings() {
  openSettings()
}

function onPaletteToggleTheme() {
  // Cycle the appearance MODE (light → dark → system) so the palette keeps
  // parity with the topbar's 3-way picker instead of collapsing to binary and
  // silently dropping the "system" follow option.
  const order: ThemeMode[] = ['light', 'dark', 'system']
  const next = order[(order.indexOf(appStore.theme) + 1) % order.length]
  appStore.setTheme(next)
}

function onPaletteSelectSession(key: string) {
  switchToSession(key)
}

function switchToSession(key: string) {
  if (!key) return
  router.push({ path: '/chat', query: { session: key } })
  if (appStore.sidebarHovered) {
    appStore.setSidebarHovered(false)
  }
}

// Optimistic rename: show the new title immediately, then persist via
// sessions.patch (display_name is the top-precedence title) and reload so the
// backend's canonical title wins. The override clears once the reload lands.
async function onRenameSession({ key, title }: { key: string; title: string }) {
  const next = title.trim()
  if (!key || !next) return
  renameOverrides.value = { ...renameOverrides.value, [key]: next }
  const local = localChatSessions.value[key]
  if (local) localChatSessions.value[key] = { ...local, title: next }
  try {
    await rpcStore.call('sessions.patch', { key, displayName: next })
    pushToast('Session renamed', { tone: 'ok' })
  } catch (err: unknown) {
    console.warn('[App] sessions.patch error:', errorMessage(err))
    pushToast('Failed to rename session', { tone: 'danger' })
  } finally {
    await loadSessions()
    const { [key]: _dropped, ...rest } = renameOverrides.value
    renameOverrides.value = rest
  }
}

// Delete a session, then refresh the list. If the deleted session is the one
// open in the chat view, drop into a fresh draft so the view does not linger on
// a session that no longer exists.
async function onDeleteSession(key: string) {
  if (!key) return
  const wasCurrent = key === currentSessionKey.value
  let result: { deleted?: string[]; errors?: string[] } | undefined
  try {
    result = await rpcStore.call<{ deleted?: string[]; errors?: string[] }>('sessions.delete', { keys: [key] })
  } catch (err: unknown) {
    // A rejected call must not look like success: surface the error and bail
    // before dropping the row, reloading, or navigating away from a session
    // that still exists on the backend.
    console.warn('[App] sessions.delete error:', errorMessage(err))
    pushToast('Failed to delete session', { tone: 'danger' })
    return
  }
  // The backend resolves even when a key fails to delete — it collects per-key
  // errors into the response instead of throwing — so a non-throwing call is
  // not proof of success. Only proceed when the key is actually reported
  // deleted; otherwise surface the failure and bail.
  if (!result?.deleted?.includes(key)) {
    console.warn('[App] sessions.delete reported failure:', result?.errors)
    pushToast('Failed to delete session', { tone: 'danger' })
    return
  }
  pushToast('Session deleted', { tone: 'ok' })
  if (localChatSessions.value[key]) {
    const { [key]: _dropped, ...rest } = localChatSessions.value
    localChatSessions.value = rest
  }
  await loadSessions()
  if (wasCurrent) {
    router.push({ path: '/chat/new', query: { agent: preferredAgentId() } })
  }
}

// Topbar approval pill: jump straight to the blocked session's chat so the
// in-thread card can be answered. The live `pendingApprovals` list (kept fresh
// by the push subscription + reconnect seed) is the source of truth — no
// re-fetch — and the oldest pending session (closest to timeout) is the
// deterministic target. With no routable session, fall back to the Approvals
// page.
function openBlockedApprovalSession() {
  const oldest = appStore.oldestPendingWithSession
  if (oldest?.sessionKey) {
    switchToSession(oldest.sessionKey)
    return
  }
  router.push('/approvals')
}

// Sidebar Approvals row: a persistent destination. While requests are pending
// it shares the topbar pill's deep-link to the blocked session; when idle it is
// the proactive way into the Approvals page (queue + strategy), with no fetch.
function onApprovalsRowClick() {
  handleNavClick()
  if (appStore.approvalCount > 0) {
    openBlockedApprovalSession()
  } else {
    router.push('/approvals')
  }
}

// Footer settings row. Both platforms own a `/settings` route now (web mounts
// the overlay dialog; desktop renders its own settings view), so a single push
// covers both. The desktop route carries `nav: 'bottom'`, so prefer its
// registered path when present to keep any future bottom-nav ordering authoritative.
function openSettings() {
  handleNavClick()
  router.push(bottomRoutes.value[0]?.path ?? '/settings')
}

// Topbar connection pill (web): jump straight to the Connection section so the
// gateway link can be inspected or re-pointed.
function openConnectionSettings() {
  router.push('/settings/connection')
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
  // Chord bindings carry the primary modifier as Cmd on Apple platforms and Ctrl
  // elsewhere — and require the other modifier to be absent — so we never match
  // macOS' Ctrl+K (emacs kill-to-end-of-line inside text fields). preventDefault
  // runs BEFORE any early return so the browser never sees the chord: on
  // Chrome/Edge/Firefox (Win/Linux) Ctrl+K focuses the omnibox/search, and in
  // Firefox-mac Cmd+K focuses the search bar. Swallowing it unconditionally also
  // lets the shortcut fire from inside the composer textarea, where the cursor
  // usually sits.
  //
  // Configurable chord shortcuts, consulted from the shortcuts store so the
  // Keyboard settings section is the single source of truth. effectiveBinding
  // returns null for a disabled shortcut, so bindingMatches skips it. New chat
  // is checked first because the palette's no-shift binding would otherwise also
  // match a Shift+K press under a looser guard. preventDefault still runs before
  // the settingsOverlay guard so the browser never sees the chord.
  const paletteBinding = shortcutsStore.effectiveBinding('command-palette')
  const newChatBinding = shortcutsStore.effectiveBinding('new-chat')
  if (bindingMatches(e, newChatBinding, isMac)) {
    e.preventDefault()
    if (settingsOverlayOpen.value) return
    startNewChatInstant()
    return
  }
  if (bindingMatches(e, paletteBinding, isMac)) {
    e.preventDefault()
    if (settingsOverlayOpen.value) return
    // Toggle so a second press closes it; the palette owns Escape/focus while open.
    commandPaletteOpen.value = !commandPaletteOpen.value
    return
  }

  // Skip App's fallbacks when a handler that runs BEFORE this one already
  // consumed the key: the composer textarea (@keydown, target phase) and any
  // earlier-registered document listener (e.g. ChatView). Overlays (drawers,
  // modals) attach their document listeners on open — AFTER this one — so they
  // run later and are NOT covered by this guard; their collision with the
  // sidebar-Escape branch is ruled out by the mobile-only gate below instead.
  if (e.defaultPrevented) return

  if (e.key === 'Escape' && themeMenuOpen.value) {
    themeMenuOpen.value = false
    themeButtonRef.value?.focus()
    return
  }
  // Escape dismisses the sidebar only as the mobile slide-over. On desktop the
  // sidebar is a persistent dock toggled by its own button, so it must never
  // collapse as a side effect of an Escape meant for an overlay opened on top of
  // it. Because those overlays run after this handler (see above), this
  // mobile-only gate — not the defaultPrevented check — is what prevents that
  // collision; keep it. The settings overlay owns Escape while open and is excluded.
  if (e.key === 'Escape' && appStore.sidebarOpen && !settingsOverlayOpen.value && window.innerWidth <= 768) {
    appStore.setSidebarOpen(false)
  }
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// ---------------------------------------------------------------------------
// App-wide approval awareness
//
// The Approvals page only updates the count while it is mounted; a tool that
// blocks a background/queued turn must surface the badge from any view. The
// gateway pushes `<namespace>.approval.requested|resolved` the moment a run
// blocks or a decision lands, so we keep `pendingApprovals`/`approvalCount`
// live here, seeded once on (re)connect to recover requests that predate the
// socket (e.g. a reload while one is already pending).
// ---------------------------------------------------------------------------

interface ApprovalPushPayload {
  approval_id?: string
  approvalId?: string
  session_key?: string
  sessionKey?: string
  tool_name?: string
  toolName?: string
  command?: string
}

interface ApprovalSnapshotItem {
  id?: string
  sessionKey?: string
  toolName?: string
  pluginId?: string
  actionKind?: string
  command?: string
  argv?: string[]
}

const rpcApprovalUnsubs: Array<() => void> = []

function approvalAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  try {
    const token = sessionStorage.getItem('opensquilla.wsToken') || ''
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* ignore */ }
  return headers
}

function snapshotItemToPending(item: ApprovalSnapshotItem): PendingApproval | null {
  const approvalId = String(item.id || '').trim()
  if (!approvalId) return null
  let command = String(item.command || '')
  if (!command && Array.isArray(item.argv) && item.argv.length > 0) {
    command = item.argv.map(String).join(' ')
  }
  return {
    approvalId,
    sessionKey: String(item.sessionKey || ''),
    tool: String(item.toolName || item.pluginId || item.actionKind || 'Unknown tool'),
    command,
  }
}

// Seed the live list from the snapshot so the count is correct after a reload
// while a request is already pending; mirrors how ApprovalsView fetches it. The
// snapshot is ordered oldest-first, which the deep-link relies on.
async function seedPendingApprovals() {
  try {
    const res = await fetch('/api/approvals', { headers: approvalAuthHeaders() })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const data = await res.json() as { pending?: ApprovalSnapshotItem[] }
    const items = (data.pending || [])
      .map(snapshotItemToPending)
      .filter((item): item is PendingApproval => item !== null)
    appStore.setPendingApprovals(items)
  } catch (err) {
    console.warn('[App] approvals seed failed:', errorMessage(err))
  }
}

function onApprovalRequested(payload: ApprovalPushPayload) {
  const approvalId = String(payload.approval_id || payload.approvalId || '').trim()
  if (!approvalId) return
  appStore.upsertPendingApproval({
    approvalId,
    sessionKey: String(payload.session_key || payload.sessionKey || ''),
    tool: String(payload.tool_name || payload.toolName || 'Unknown tool'),
    command: String(payload.command || ''),
  })
}

function onApprovalResolved(payload: ApprovalPushPayload) {
  const approvalId = String(payload.approval_id || payload.approvalId || '').trim()
  if (approvalId) appStore.removePendingApproval(approvalId)
}

// Reconnect re-seeds the list (recovers approvals that arrived while the socket
// was down); the push events keep it live thereafter.
function onApprovalConnectionState(state: unknown) {
  if (state === 'connected') void seedPendingApprovals()
}

function subscribeApprovals() {
  rpcApprovalUnsubs.push(
    rpcStore.on('exec.approval.requested', onApprovalRequested as RpcEventHandler),
    rpcStore.on('exec.approval.resolved', onApprovalResolved as RpcEventHandler),
    rpcStore.on('plugin.approval.requested', onApprovalRequested as RpcEventHandler),
    rpcStore.on('plugin.approval.resolved', onApprovalResolved as RpcEventHandler),
    rpcStore.on('_state', onApprovalConnectionState as RpcEventHandler),
  )
}

function unsubscribeApprovals() {
  rpcApprovalUnsubs.forEach(unsub => unsub())
  rpcApprovalUnsubs.length = 0
}

// ---------------------------------------------------------------------------
// Tab-title + screen-reader badge for the pending count
// ---------------------------------------------------------------------------

const BASE_TITLE = document.title

const approvalAnnouncement = ref('')

let titleDebounce: ReturnType<typeof setTimeout> | null = null

function applyTitleBadge(count: number) {
  document.title = count > 0 ? `(${count}) ${BASE_TITLE}` : BASE_TITLE
}

// Debounce so a burst of count changes does not thrash the tab title.
watch(() => appStore.approvalCount, count => {
  approvalAnnouncement.value = count > 0 ? `${count} approvals pending` : ''
  if (titleDebounce) clearTimeout(titleDebounce)
  titleDebounce = setTimeout(() => {
    titleDebounce = null
    applyTitleBadge(count)
  }, 500)
})

useDocumentEvent('keydown', handleKeydown)

onMounted(() => {
  syncMobileSidebar()
  window.addEventListener('resize', syncMobileSidebar)
  window.visualViewport?.addEventListener('resize', syncMobileKeyboard)
  loadAgents()
  loadSessions()
  rpcUnsubSessionsChanged = rpcStore.on('sessions.changed', scheduleSessionRefresh)
  // Keep the approval badge/count live app-wide, not just on the Approvals page.
  subscribeApprovals()
  // Seed now in case the socket is already connected (the `_state` listener
  // covers later reconnects); recovers a request pending before mount.
  if (rpcStore.isConnected) void seedPendingApprovals()
})

onUnmounted(() => {
  if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
  if (sessionRefreshTimer) clearTimeout(sessionRefreshTimer)
  if (rpcUnsubSessionsChanged) rpcUnsubSessionsChanged()
  unsubscribeApprovals()
  if (titleDebounce) {
    clearTimeout(titleDebounce)
    titleDebounce = null
  }
  document.title = BASE_TITLE
  window.removeEventListener('resize', syncMobileSidebar)
  window.visualViewport?.removeEventListener('resize', syncMobileKeyboard)
})

</script>

<style scoped>
/* Topbar connection pill as a button (web): inherits the base .conn-pill look
   and state colors, adds button reset + an affordance that it is clickable. */
.conn-pill--link {
  cursor: pointer;
  font-family: inherit;
}
.conn-pill--link:hover {
  filter: brightness(1.08);
}
.conn-pill--link:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 2px;
}

/* Off-screen but screen-reader-reachable announcer for the approval count. */
.app-approval-live {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
