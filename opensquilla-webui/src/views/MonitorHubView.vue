<template>
  <div class="monitor-hub">
    <!-- One Monitor destination, four sections. Each former page keeps its full
         UI and its canonical URL: the tabs ARE the routes, so /usage and /logs
         deep links stay valid and the palette can target a specific section. -->
    <div class="monitor-hub__bar">
      <nav class="monitor-hub__tabs" role="tablist" :aria-label="t('nav.groupMonitor')">
        <router-link
          v-for="tab in TABS"
          :key="tab.path"
          :to="tab.path"
          custom
          v-slot="{ navigate }"
        >
          <button
            role="tab"
            class="monitor-hub__tab"
            :class="{ 'is-active': isActive(tab.path) }"
            :aria-selected="isActive(tab.path)"
            aria-controls="monitor-hub-panel"
            @click="navigate"
          >
            <Icon :name="tab.icon" :size="14" />
            <span>{{ t(tab.label) }}</span>
          </button>
        </router-link>
      </nav>
      <SupportDiagnosticsMenu />
    </div>
    <div id="monitor-hub-panel" role="tabpanel" class="monitor-hub__panel">
      <KeepAlive :max="4">
        <component :is="activeComponent" />
      </KeepAlive>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import SupportDiagnosticsMenu from '@/components/SupportDiagnosticsMenu.vue'
import type { IconName } from '@/utils/icons'
import OverviewView from '@/views/OverviewView.vue'
import ChannelsView from '@/views/ChannelsView.vue'
import UsageView from '@/views/UsageView.vue'
import LogsView from '@/views/LogsView.vue'

const { t } = useI18n()
const route = useRoute()

const TABS: Array<{ path: string; label: string; icon: IconName; component: unknown }> = [
  { path: '/overview', label: 'nav.overview', icon: 'home', component: OverviewView },
  { path: '/channels', label: 'nav.channels', icon: 'channels', component: ChannelsView },
  { path: '/usage', label: 'nav.usage', icon: 'usage', component: UsageView },
  { path: '/logs', label: 'nav.logs', icon: 'logs', component: LogsView },
]

function isActive(path: string): boolean {
  return route.path === path
}

const activeComponent = computed(() => {
  const tab = TABS.find((entry) => entry.path === route.path)
  return (tab ?? TABS[0]).component
})
</script>

<style scoped>
.monitor-hub {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.monitor-hub__bar {
  align-items: flex-start;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  min-width: 0;
}

.monitor-hub__tabs {
  display: flex;
  gap: 2px;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  padding: 3px;
  background: var(--bg-surface-2);
  border-radius: var(--radius-control);
  /* Narrow screens: let the strip scroll instead of clipping the last tab. */
  overflow-x: auto;
  scrollbar-width: none;
}
.monitor-hub__tabs::-webkit-scrollbar {
  display: none;
}

.monitor-hub__tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
  white-space: nowrap;
  padding: 6px 14px;
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 600;
  cursor: pointer;
}

.monitor-hub__tab:hover {
  color: var(--text);
}

.monitor-hub__tab.is-active {
  background: var(--bg-surface);
  color: var(--text);
  box-shadow: var(--elev-1);
}

.monitor-hub__tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

/* The hub's tab strip now clears the floating topbar, so the hosted views'
   own headers no longer need their topbar clearance padding. */
@media (min-width: 769px) {
  .monitor-hub {
    padding-top: calc(36px + var(--sp-2));
  }
  .monitor-hub :deep(.control-stage__header) {
    padding-top: var(--sp-2);
  }
}

/* Hosted views must not repeat a page title under the tab that already names
   them: hide the H1 title-block; the header keeps only its actions row, which
   collapses to a slim right-aligned toolbar (the Overview treatment, applied
   uniformly so every tab opens the same way). */
.monitor-hub :deep(.control-stage__title-block) {
  display: none;
}
.monitor-hub :deep(.control-stage__header) {
  justify-content: flex-end;
}

@media (max-width: 600px) {
  .monitor-hub__bar {
    align-items: center;
  }
}
</style>
