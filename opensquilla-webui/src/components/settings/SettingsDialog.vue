<template>
  <div class="settings-overlay" @click.self="requestClose()">
    <section
      ref="modalRef"
      class="settings-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <header class="settings-modal__head">
        <h2 id="settings-modal-title" class="settings-modal__title">Settings</h2>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          aria-label="Close"
          title="Close"
          @click="requestClose()"
        >
          <Icon name="x" :size="16" />
        </button>
      </header>

      <!-- The readiness banner needs config + status, so it waits for load. The
           rail and Connection panel render immediately (below) so the gateway
           can be (re)connected even before any config loads. -->
      <template v-if="loaded">
      <div class="settings-banner" :class="hasSetupAction ? 'is-warn' : 'is-ok'">
        <div class="settings-banner__row">
          <Icon :name="hasSetupAction ? 'info' : 'check'" :size="16" aria-hidden="true" />
          <template v-if="hasSetupAction">
            <strong class="settings-banner__count">Action needed ({{ actionItems.length }})</strong>
            <span class="settings-banner__items">
              <button
                v-for="item in actionItems"
                :key="item.label"
                type="button"
                class="settings-banner__item"
                :aria-label="`${item.label} — open ${sectionLabel(item.section)}`"
                @click="selectSection(item.section)"
              >{{ item.label }}</button>
            </span>
          </template>
          <span v-else class="settings-banner__ready">Ready to run</span>
          <span class="settings-banner__spacer"></span>
          <button
            type="button"
            class="settings-banner__toggle"
            :aria-expanded="disclosureOpen ? 'true' : 'false'"
            aria-controls="settings-banner-disclosure"
            @click="disclosureOpen = !disclosureOpen"
          >
            <span class="settings-banner__chevron" :class="{ 'is-open': disclosureOpen }" aria-hidden="true">&#9656;</span>
            <span>CLI handoff</span>
          </button>
        </div>
        <div v-show="disclosureOpen" id="settings-banner-disclosure" class="settings-banner__disclosure">
          <div class="setup-cli">
            <section v-if="fixCommands.length > 0" class="setup-cli__group" aria-label="Fix now">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">Fix now</h4></div>
              <SetupCommandBlock
                v-for="cmd in fixCommands"
                :key="cmd.label"
                class="setup-cli__row"
                :label="cmd.label"
                :command="cmd.command"
                @copy="copyCommand"
              />
            </section>
            <section class="setup-cli__group" aria-label="CLI handoff">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">CLI handoff</h4></div>
              <SetupCommandBlock
                v-for="cmd in handoffCommands"
                :key="cmd.label"
                class="setup-cli__row"
                :label="cmd.label"
                :command="cmd.command"
                @copy="copyCommand"
              />
            </section>
            <section class="setup-cli__group" aria-label="CLI recipes">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">CLI recipes</h4></div>
              <SetupCommandBlock
                v-for="cmd in recipeCommands"
                :key="cmd.label"
                class="setup-cli__row"
                :label="cmd.label"
                :command="cmd.command"
                @copy="copyCommand"
              />
            </section>
          </div>
          <div class="setup-summary" aria-label="Config summary">
            <div v-for="row in configSummary" :key="row.label">
              <span>{{ row.label }}</span><strong>{{ row.value }}</strong>
            </div>
          </div>
        </div>
      </div>
      </template>

      <div class="settings-body">
        <nav class="settings-rail" role="tablist" aria-label="Settings sections" :aria-orientation="railOrientation">
          <button
            v-for="s in SETTINGS_SECTIONS"
            :id="'settings-rail-' + s.id"
            :key="s.id"
            type="button"
            role="tab"
            class="settings-rail__item"
            :class="{ 'is-active': section === s.id }"
            :aria-selected="section === s.id ? 'true' : 'false'"
            :aria-controls="'settings-section-' + s.id"
            :aria-label="s.client ? s.label : `${s.label}: ${sectionStatus(s.id).label}${sectionDirty(s.id) ? ', unsaved changes' : ''}`"
            @click="selectSection(s.id)"
          >
            <Icon :name="s.icon" :size="16" aria-hidden="true" />
            <span class="settings-rail__label">{{ s.label }}</span>
            <span v-if="sectionDirty(s.id)" class="settings-rail__dirty" aria-hidden="true"></span>
            <span v-if="!s.client" class="settings-rail__dot" :class="sectionStatus(s.id).tone" aria-hidden="true"></span>
          </button>
        </nav>

        <div
          :id="'settings-section-' + section"
          class="settings-panel"
          role="tabpanel"
          :aria-labelledby="'settings-rail-' + section"
        >
          <!-- Connection renders regardless of load state: it is how you point
               the UI at a reachable gateway when nothing has loaded yet. -->
          <SetupConnectionPanel v-if="section === 'connection'" />

          <!-- Config-backed sections wait for readiness so their baselines are
               final before any field can be edited. -->
          <div v-else-if="!loaded" class="settings-loading">
            <LoadingSpinner />
          </div>
          <template v-else>
            <SetupProviderPanel
              v-if="section === 'provider'"
              :panel="providerPanel"
              @update-provider-selected="selectProvider"
              @provider-change="onProviderChange"
              @update-provider-field="updateProviderField"
              @update-llm-timeout="updateLlmTimeout"
              @copy="copyCommand"
              @save="saveProvider"
            />
            <SetupRouterPanel
              v-else-if="section === 'router'"
              :panel="routerPanel"
              @update-router-mode="setRouterMode"
              @update-router-default-tier="setRouterDefaultTier"
              @update-router-visual-mode="setRouterVisualMode"
              @update-tier-field="updateTierField"
              @save="saveRouter"
            />
            <SetupChannelsPanel
              v-else-if="section === 'channels'"
              :panel="channelsPanel"
              @update-channel-type="selectChannelType"
              @channel-type-change="onChannelTypeChange"
              @update-channel-field="updateChannelField"
              @save="saveChannel"
            />
            <SetupCapabilitiesPanel
              v-else-if="section === 'capabilities'"
              :panel="capabilitiesPanel"
              @update-field="updateCapabilityField"
              @search-provider-change="onSearchProviderChange"
              @memory-provider-change="onMemoryProviderChange"
              @image-provider-change="onImageProviderChange"
              @save-search="saveSearch"
              @save-memory="saveMemory"
              @save-image="saveImage"
              @save-audio="saveAudio"
              @copy="copyCommand"
            />
            <SettingsAppearancePanel v-else-if="section === 'appearance'" />
            <SettingsKeyboardPanel v-else-if="section === 'keyboard'" />
            <SettingsAdvancedPanel v-else-if="section === 'advanced'" />
          </template>
        </div>
      </div>

      <div v-if="loaded && hasUnsavedChanges" class="settings-dirtybar" aria-live="polite">
        <span class="settings-dirtybar__pulse" aria-hidden="true"></span>
        <span class="settings-dirtybar__text">Unsaved changes in {{ dirtySectionNames }}</span>
        <span class="settings-dirtybar__spacer"></span>
        <button type="button" class="btn" @click="discardChanges">Discard</button>
        <button type="button" class="btn btn--primary" @click="saveDirtySections">Save</button>
      </div>

      <footer class="settings-foot">
        <span class="settings-foot__text">More options live in</span>
        <code class="settings-foot__path">{{ displayConfigPath }}</code>
        <button
          type="button"
          class="settings-foot__copy"
          aria-label="Copy config path"
          title="Copy config path"
          @click="copyDisplayPath"
        >
          <Icon name="copy" :size="13" />
        </button>
        <span class="settings-foot__sep" aria-hidden="true">&middot;</span>
        <span class="settings-foot__text">Most changes apply live; some need a gateway restart</span>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'
import SetupConnectionPanel from '@/components/settings/SetupConnectionPanel.vue'
import SetupProviderPanel from '@/components/setup/SetupProviderPanel.vue'
import SetupRouterPanel from '@/components/setup/SetupRouterPanel.vue'
import SetupChannelsPanel from '@/components/setup/SetupChannelsPanel.vue'
import SetupCapabilitiesPanel from '@/components/setup/SetupCapabilitiesPanel.vue'
import SettingsAppearancePanel from '@/components/settings/SettingsAppearancePanel.vue'
import SettingsKeyboardPanel from '@/components/settings/SettingsKeyboardPanel.vue'
import SettingsAdvancedPanel from '@/components/settings/SettingsAdvancedPanel.vue'
import { useSetupCatalog, SETTINGS_SECTIONS } from '@/composables/setup/useSetupCatalog'
import { sectionFromRouteParam } from '@/composables/setup/useSettingsSection'
import { useConfirm } from '@/composables/useConfirm'
import '@/styles/settings-forms.css'

const route = useRoute()
const router = useRouter()
const { confirm, confirmState } = useConfirm()

const {
  section,
  setSection,
  loaded,
  providerPanel,
  routerPanel,
  channelsPanel,
  capabilitiesPanel,
  hasSetupAction,
  actionItems,
  fixCommands,
  handoffCommands,
  recipeCommands,
  configSummary,
  configPath,
  selectInitialSection,
  sectionStatus,
  sectionDirty,
  dirtySections,
  hasUnsavedChanges,
  saveDirtySections,
  discardChanges,
  selectProvider,
  setRouterMode,
  setRouterDefaultTier,
  setRouterVisualMode,
  selectChannelType,
  updateProviderField,
  updateLlmTimeout,
  updateTierField,
  updateChannelField,
  updateCapabilityField,
  onProviderChange,
  onChannelTypeChange,
  onSearchProviderChange,
  onMemoryProviderChange,
  onImageProviderChange,
  saveProvider,
  saveRouter,
  saveChannel,
  saveSearch,
  saveMemory,
  saveImage,
  saveAudio,
  copyCommand,
  copyConfigPath,
} = useSetupCatalog()

const modalRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const disclosureOpen = ref(false)
const isMobile = ref(window.matchMedia('(max-width: 768px)').matches)
// Set once the user picks a section so the deep-link auto landing (which waits
// on readiness data) never stomps navigation made while config was loading.
let userNavigated = false

const railOrientation = computed(() => (isMobile.value ? 'horizontal' : 'vertical'))
const dirtySectionNames = computed(() => dirtySections.value.map(s => s.label).join(' · '))
const displayConfigPath = computed(() => configPath.value || '~/.opensquilla/config.toml')

// Where to return when the overlay closes. Captured on open from the route the
// user came from; null for a cold deep link (the overlay route was the entry
// point, e.g. someone pasted /settings/connection), which falls back to home.
let returnTo: string | null = null
// The control that had focus when the overlay opened, restored on close. For a
// cold deep link there is no in-app invoker, so close moves focus to the
// sidebar Settings button instead of leaving it on a detached node.
let invokerEl: HTMLElement | null = null
let mq: MediaQueryList | null = null
let closing = false

const routeParam = computed(() => route.params.section)
// `/setup` → `/settings/auto` asks for the first not-ready section once
// readiness is known; it is a routing sentinel, never a real rail section.
const wantsAutoSection = computed(() => routeParam.value === 'auto')

function sectionLabel(id: string): string {
  return SETTINGS_SECTIONS.find(s => s.id === id)?.label || id
}

// Reflect the active section in the URL with replace (not push) so the browser
// Back button exits Settings in one step rather than walking section history.
function selectSection(id: string) {
  userNavigated = true
  setSection(id)
  if (route.params.section !== id) {
    void router.replace({ path: `/settings/${id}` })
  }
}

// Resolve the section the route is asking for. Connection works before config
// loads; the auto sentinel waits for readiness; everything else maps the param
// (or the default) straight through.
function applyRouteSection() {
  if (wantsAutoSection.value) {
    if (loaded.value && !userNavigated) selectInitialSection('auto')
    return
  }
  setSection(sectionFromRouteParam(routeParam.value))
}

function copyDisplayPath() {
  if (configPath.value) {
    copyConfigPath()
  } else {
    copyCommand(displayConfigPath.value)
  }
}

function sidebarSettingsButton(): HTMLElement | null {
  return document.querySelector<HTMLElement>('.sidebar-foot button[data-icon="settings"]')
}

// A usable focus-restore target: a real element still in the document that is
// neither <body> (the cold-deep-link case, where activeElement was never a
// meaningful invoker) nor inside the dialog itself (which is about to unmount).
function usableInvoker(): HTMLElement | null {
  if (!invokerEl || invokerEl === document.body) return null
  if (!document.contains(invokerEl)) return null
  if (modalRef.value?.contains(invokerEl)) return null
  return invokerEl
}

// Leave the overlay: restore focus first (the route change unmounts us), then
// navigate to the captured return location, or home for a cold deep link.
function closeOverlay() {
  closing = true
  const target = usableInvoker() ?? sidebarSettingsButton()
  target?.focus()
  invokerEl = null
  void router.push(returnTo ?? '/')
}

// Closes unless a section carries unsaved edits and the user keeps them.
async function requestClose(): Promise<boolean> {
  if (hasUnsavedChanges.value) {
    const ok = await confirm({
      title: 'Discard unsaved changes?',
      body: 'You have unsaved edits. Closing now will lose them.',
      primaryLabel: 'Discard',
    })
    if (!ok) return false
  }
  closeOverlay()
  return true
}

function onDocumentKeydown(event: KeyboardEvent) {
  // The confirm modal owns the keyboard while it is open; let it handle Escape
  // so a single keypress cannot both dismiss the prompt and re-open it.
  if (confirmState.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    void requestClose()
    return
  }
  if (event.key !== 'Tab') return
  const rootEl = modalRef.value
  if (!rootEl) return
  const focusables = Array.from(rootEl.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'))
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement as HTMLElement | null
  const inside = !!active && rootEl.contains(active)
  if (event.shiftKey && (!inside || active === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault()
    first.focus()
  }
}

function onViewportChange(event: MediaQueryListEvent) {
  isMobile.value = event.matches
}

// Keep the active section in sync as the route param changes (deep link, Back,
// or a same-overlay section switch). The auto sentinel resolves once readiness
// loads; the loaded watcher below completes that case.
watch(routeParam, () => applyRouteSection())

// The auto deep link lands on its readiness-derived section once config is
// known, unless the user already navigated during the load.
watch(loaded, (isLoaded) => {
  if (isLoaded && wantsAutoSection.value && !userNavigated) selectInitialSection('auto')
})

onMounted(() => {
  // Capture the return location from where we entered the overlay. router.back()
  // is avoided because it cannot be trusted for cold deep links; an explicit
  // push to the stored path (or home) gives a single, predictable exit.
  const from = router.options.history.state.back
  returnTo = typeof from === 'string' && !from.startsWith('/settings') ? from : null
  invokerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
  applyRouteSection()
  document.addEventListener('keydown', onDocumentKeydown)
  mq = window.matchMedia('(max-width: 768px)')
  mq.addEventListener('change', onViewportChange)
  nextTick(() => closeBtn.value?.focus())
})

onUnmounted(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  mq?.removeEventListener('change', onViewportChange)
  mq = null
  // A route-driven unmount that did not go through closeOverlay (e.g. the user
  // pressed browser Back) still owes focus restoration: the real invoker, or
  // the sidebar Settings button for a cold deep link, never a detached node.
  if (!closing) (usableInvoker() ?? sidebarSettingsButton())?.focus()
  invokerEl = null
})
</script>

<style scoped>
.settings-overlay {
  align-items: center;
  background: var(--scrim);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: var(--sp-6);
  position: fixed;
  z-index: 300;
}

.settings-modal {
  animation: settingsIn 0.18s ease;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  height: min(85vh, 100%);
  overflow: hidden;
  width: min(1200px, 100%);
}

@keyframes settingsIn {
  from { transform: translateY(12px); opacity: 0.4; }
  to { transform: translateY(0); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .settings-modal {
    animation: none;
  }
}

.settings-modal__head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-shrink: 0;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}

.settings-modal__title {
  flex: 1;
  font-size: var(--fs-lg);
  font-weight: 700;
  margin: 0;
}

.settings-loading {
  align-items: center;
  display: flex;
  flex: 1;
  justify-content: center;
}

/* Readiness banner */
.settings-banner {
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  max-height: 45%;
  overflow-y: auto;
}

.settings-banner.is-ok {
  background: color-mix(in srgb, var(--ok) 8%, var(--bg-surface));
  color: var(--ok);
}

.settings-banner.is-warn {
  background: color-mix(in srgb, var(--warn) 8%, var(--bg-surface));
  color: var(--warn);
}

.settings-banner__row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  min-height: 40px;
  padding: var(--sp-2) var(--sp-4);
}

.settings-banner__count {
  font-size: var(--fs-sm);
  font-weight: 600;
  white-space: nowrap;
}

.settings-banner__ready {
  font-size: var(--fs-sm);
  font-weight: 600;
}

.settings-banner__items {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  min-width: 0;
}

.settings-banner__item {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--border));
  border-radius: 999px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-xs);
  padding: 2px 10px;
}

.settings-banner__item:hover {
  border-color: var(--warn);
  color: var(--text);
}

.settings-banner__spacer {
  flex: 1;
}

.settings-banner__toggle {
  align-items: center;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: var(--fs-xs);
  gap: var(--sp-1);
  padding: 4px var(--sp-2);
}

.settings-banner__toggle:hover {
  color: var(--text);
}

.settings-banner__chevron {
  display: inline-block;
  transition: transform var(--transition);
}

.settings-banner__chevron.is-open {
  transform: rotate(90deg);
}

@media (prefers-reduced-motion: reduce) {
  .settings-banner__chevron {
    transition: none;
  }
}

.settings-banner__disclosure {
  border-top: 1px solid var(--border);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-4);
}

/* Body: rail + active section */
.settings-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.settings-rail {
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  gap: 2px;
  overflow-y: auto;
  padding: var(--sp-3) var(--sp-2);
  width: 200px;
}

.settings-rail__item {
  align-items: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
}

.settings-rail__item:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.settings-rail__item.is-active {
  background: var(--bg-elevated);
  box-shadow: inset 2px 0 0 var(--accent);
  color: var(--text);
  font-weight: 600;
}

.settings-rail__label {
  flex: 1;
}

.settings-rail__dot {
  border-radius: 50%;
  flex-shrink: 0;
  height: 7px;
  width: 7px;
}

.settings-rail__dot.is-ok { background: var(--ok); }
.settings-rail__dot.is-warn { background: var(--warn); }
.settings-rail__dot.is-muted { background: var(--text-dim); opacity: 0.5; }

.settings-rail__dirty {
  background: var(--accent);
  border-radius: 50%;
  flex-shrink: 0;
  height: 5px;
  width: 5px;
}

.settings-panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--sp-4);
}

/* Dirty bar */
.settings-dirtybar {
  align-items: center;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border);
  display: flex;
  flex-shrink: 0;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-4);
}

.settings-dirtybar__pulse {
  background: var(--accent);
  border-radius: 50%;
  height: 8px;
  width: 8px;
}

.settings-dirtybar__text {
  color: var(--text);
  font-size: var(--fs-sm);
}

.settings-dirtybar__spacer {
  flex: 1;
}

/* Footer */
.settings-foot {
  align-items: center;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  font-size: var(--fs-xs);
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
}

.settings-foot__path {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-foot__copy {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.settings-foot__copy:hover {
  background: var(--bg-hover);
  border-color: var(--border);
  color: var(--text);
}

/* Mobile: full screen, horizontal section chips */
@media (max-width: 768px) {
  .settings-overlay {
    padding: 0;
  }

  .settings-modal {
    border: none;
    border-radius: 0;
    height: 100%;
    width: 100%;
  }

  .settings-body {
    flex-direction: column;
  }

  .settings-rail {
    border-bottom: 1px solid var(--border);
    border-right: none;
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
    padding: var(--sp-2);
    width: 100%;
  }

  .settings-rail__item {
    flex-shrink: 0;
    min-height: 44px;
  }

  .settings-panel {
    padding: var(--sp-3);
  }

  .settings-foot {
    padding-bottom: max(var(--sp-2), env(safe-area-inset-bottom));
  }
}
</style>
