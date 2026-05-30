<template>
  <nav class="sidebar" :class="{ open: appStore.sidebarOpen }" aria-label="Primary" id="sidebar-nav">
    <div class="nav-brand">
      <img class="brand-mark" :src="brandMarkUrl" alt="" aria-hidden="true" />
      OpenSquilla
    </div>
    <template v-for="group in navGroups" :key="group.label">
      <div class="nav-group-label">{{ group.label }}</div>
      <router-link
        v-for="route in group.routes"
        :key="route.path"
        :to="route.path"
        class="nav-item"
        :class="{ 'is-active': $route.path === route.path }"
        :aria-current="$route.path === route.path ? 'page' : undefined"
        @click="handleNavClick"
      >
        <Icon :name="route.icon" :size="16" />
        <span>{{ route.title }}</span>
        <span v-if="route.path === '/approvals' && appStore.approvalCount > 0" class="nav-badge">
          {{ appStore.approvalCount }}
        </span>
      </router-link>
    </template>
  </nav>
  <div class="main">
    <header class="topbar">
      <div class="topbar-left">
        <button
          class="btn btn--icon btn--ghost sidebar-toggle"
          @click="appStore.toggleSidebar"
          :aria-expanded="appStore.sidebarOpen"
          aria-controls="sidebar-nav"
          title="Toggle menu"
        >
          <Icon name="menu" :size="16" />
        </button>
        <span class="conn-pill" :class="rpcStore.state">{{ rpcStore.state }}</span>
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
        <button class="btn btn--icon btn--ghost" @click="appStore.cycleTheme" :title="`Theme: ${appStore.theme}`">
          <Icon :name="themeIconName" :size="16" />
        </button>
      </div>
    </header>
    <main class="content" id="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'
import { useRpcStore } from './stores/rpc'
import Icon from './components/Icon.vue'

const appStore = useAppStore()
const rpcStore = useRpcStore()
const $route = useRoute()

const brandMarkUrl = computed(() => {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/img/opensquilla-mark.png`
})

const themeIconName = computed(() => {
  if (appStore.theme === 'system') return 'monitor'
  return appStore.resolvedTheme === 'dark' ? 'moon' : 'sun'
})

interface NavRoute {
  path: string
  title: string
  icon: 'chat' | 'home' | 'channels' | 'sessions' | 'skills' | 'agents' | 'usage' | 'cron' | 'config' | 'logs' | 'approvals'
}

interface NavGroup {
  label: string
  routes: NavRoute[]
}

const navGroups = computed<NavGroup[]>(() => [
  {
    label: 'Chat',
    routes: [{ path: '/chat', title: 'Chat', icon: 'chat' }],
  },
  {
    label: 'Control',
    routes: [
      { path: '/overview', title: 'Overview', icon: 'home' },
      { path: '/health', title: 'Health', icon: 'logs' },
      { path: '/channels', title: 'Channels', icon: 'channels' },
      { path: '/skills', title: 'Skills', icon: 'skills' },
      { path: '/sessions', title: 'Sessions', icon: 'sessions' },
      { path: '/agents', title: 'Agents', icon: 'agents' },
      { path: '/usage', title: 'Usage', icon: 'usage' },
      { path: '/cron', title: 'Cron', icon: 'cron' },
    ],
  },
  {
    label: 'Settings',
    routes: [
      { path: '/config', title: 'Config', icon: 'config' },
      { path: '/logs', title: 'Logs', icon: 'logs' },
      { path: '/approvals', title: 'Approvals', icon: 'approvals' },
    ],
  },
])

function handleNavClick() {
  appStore.setSidebarOpen(false)
}

// Mobile: close sidebar when route changes
watch(() => $route.path, () => {
  appStore.setSidebarOpen(false)
})

// Close sidebar on click outside (mobile)
function handleClickOutside(e: MouseEvent) {
  const sidebar = document.querySelector('.sidebar')
  const toggle = document.querySelector('.sidebar-toggle')
  if (!sidebar?.classList.contains('open')) return
  if (sidebar.contains(e.target as Node) || toggle?.contains(e.target as Node)) return
  appStore.setSidebarOpen(false)
}

document.addEventListener('click', handleClickOutside)

// Close sidebar on Escape key
document.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key === 'Escape' && appStore.sidebarOpen) {
    appStore.setSidebarOpen(false)
  }
})
</script>
