<template>
  <div class="settings-overlay" @click.self="requestClose()">
    <Transition name="settings-pop" appear @after-leave="onLeaveComplete">
    <section
      v-if="visible"
      ref="modalRef"
      class="settings-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <header class="settings-modal__head">
        <h2 id="settings-modal-title" class="settings-modal__title">{{ t('settings.dialog.title') }}</h2>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          :aria-label="t('common.close')"
          :title="t('common.close')"
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
            <strong class="settings-banner__count">{{ t('settings.dialog.actionNeeded', { count: actionItems.length }) }}</strong>
            <span class="settings-banner__items">
              <button
                v-for="item in actionItems"
                :key="item.label"
                type="button"
                class="settings-banner__item"
                :aria-label="t('settings.dialog.openSection', { label: item.label, section: sectionLabel(item.section) })"
                @click="selectSection(item.section)"
              >{{ item.label }}</button>
            </span>
          </template>
          <span v-else class="settings-banner__ready">{{ t('settings.dialog.readyToRun') }}</span>
          <span class="settings-banner__spacer"></span>
          <button
            type="button"
            class="settings-banner__toggle"
            :aria-expanded="disclosureOpen ? 'true' : 'false'"
            aria-controls="settings-banner-disclosure"
            @click="disclosureOpen = !disclosureOpen"
          >
            <span class="settings-banner__chevron" :class="{ 'is-open': disclosureOpen }" aria-hidden="true">&#9656;</span>
            <span>{{ t('settings.dialog.cliHandoff') }}</span>
          </button>
        </div>
        <div v-show="disclosureOpen" id="settings-banner-disclosure" class="settings-banner__disclosure">
          <div class="setup-cli">
            <section v-if="fixCommands.length > 0" class="setup-cli__group" :aria-label="t('settings.dialog.fixNow')">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">{{ t('settings.dialog.fixNow') }}</h4></div>
              <SetupCommandBlock
                v-for="cmd in fixCommands"
                :key="cmd.label"
                class="setup-cli__row"
                :label="cmd.label"
                :command="cmd.command"
                @copy="copyCommand"
              />
            </section>
            <section class="setup-cli__group" :aria-label="t('settings.dialog.cliHandoff')">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">{{ t('settings.dialog.cliHandoff') }}</h4></div>
              <SetupCommandBlock
                v-for="cmd in handoffCommands"
                :key="cmd.label"
                class="setup-cli__row"
                :label="cmd.label"
                :command="cmd.command"
                @copy="copyCommand"
              />
            </section>
            <section class="setup-cli__group" :aria-label="t('settings.dialog.cliRecipes')">
              <div class="setup-cli__group-head"><h4 class="control-panel__eyebrow">{{ t('settings.dialog.cliRecipes') }}</h4></div>
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
          <div class="setup-summary" :aria-label="t('settings.dialog.configSummary')">
            <div v-for="row in configSummary" :key="row.label">
              <span>{{ row.label }}</span><strong>{{ row.value }}</strong>
            </div>
          </div>
        </div>
      </div>
      </template>

      <div class="settings-body">
        <nav ref="railRef" class="settings-rail" role="tablist" :aria-label="t('settings.dialog.sections')" :aria-orientation="railOrientation">
          <template v-for="(s, i) in visibleSections" :key="s.id">
            <!-- Presentational group eyebrow: labels the rail without adding a
                 tab stop. Rendered when the group changes so each bin is headed
                 once. Hidden on the mobile horizontal strip. -->
            <span
              v-if="i === 0 || s.group !== visibleSections[i - 1].group"
              class="settings-rail__group"
              role="presentation"
              aria-hidden="true"
            >{{ t('settings.rail.groups.' + s.group) }}</span>
            <button
              :id="'settings-rail-' + s.id"
              type="button"
              role="tab"
              class="settings-rail__item"
              :class="{ 'is-active': section === s.id }"
              :aria-selected="section === s.id ? 'true' : 'false'"
              :aria-controls="'settings-section-' + s.id"
              :aria-label="s.client ? t('settings.rail.' + s.id) : `${t('settings.rail.' + s.id)}: ${sectionStatus(s.id).label}${sectionDirty(s.id) ? t('settings.dialog.unsavedSuffix') : ''}`"
              @click="selectSection(s.id)"
            >
              <Icon :name="s.icon" :size="16" aria-hidden="true" />
              <span class="settings-rail__label">{{ t('settings.rail.' + s.id) }}</span>
              <span v-if="sectionDirty(s.id)" class="settings-rail__dirty" aria-hidden="true"></span>
              <span v-if="!s.client" class="settings-rail__dot" :class="sectionStatus(s.id).tone" aria-hidden="true"></span>
            </button>
          </template>
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

          <!-- Runtime (desktop only) also renders regardless of load state: it
               reports the owned gateway and offers restart/reset precisely for
               when the gateway is down and config never loaded. -->
          <DesktopRuntimePanel v-else-if="section === 'runtime' && isDesktop" />

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
              @go-to-section="selectSection"
            />
            <SetupBehaviorPanel
              v-else-if="section === 'behavior'"
              :panel="behaviorPanel"
              @update-auto-session-titles="setAutoSessionTitles"
            />
            <SettingsPrivacyPanel
              v-else-if="section === 'privacy'"
              :panel="privacyPanel"
              @update-disable-network-observability="setDisableNetworkObservability"
            />
            <SetupRouterPanel
              v-else-if="section === 'router'"
              :panel="routerPanel"
              @update-router-mode="setRouterMode"
              @update-router-default-tier="setRouterDefaultTier"
              @update-router-visual-mode="setRouterVisualMode"
              @update-tier-field="updateTierField"
              @go-to-section="selectSection"
            />
            <SetupChannelsPanel
              v-else-if="section === 'channels'"
              :panel="channelsPanel"
              @update-channel-type="selectChannelType"
              @channel-type-change="onChannelTypeChange"
              @update-channel-field="updateChannelField"
              @save="saveChannel"
              @enable-channel="enableChannel"
              @disable-channel="disableChannel"
              @remove-channel="removeChannel"
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
        <span class="settings-dirtybar__text">{{ t('settings.dialog.unsavedIn', { sections: dirtySectionNames }) }}</span>
        <span class="settings-dirtybar__spacer"></span>
        <button type="button" class="btn" @click="discardChanges">{{ t('common.discard') }}</button>
        <button type="button" class="btn btn--primary" @click="saveDirtySections">{{ t('common.save') }}</button>
      </div>

      <footer class="settings-foot">
        <span class="settings-foot__text">{{ t('settings.dialog.moreOptionsIn') }}</span>
        <code class="settings-foot__path">{{ displayConfigPath }}</code>
        <button
          type="button"
          class="settings-foot__copy"
          :aria-label="t('settings.dialog.copyConfigPath')"
          :title="t('settings.dialog.copyConfigPath')"
          @click="copyDisplayPath"
        >
          <Icon name="copy" :size="13" />
        </button>
        <span class="settings-foot__sep" aria-hidden="true">&middot;</span>
        <span class="settings-foot__text">{{ t('settings.dialog.applyLiveNote') }}</span>
      </footer>
    </section>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import SetupCommandBlock from '@/components/setup/SetupCommandBlock.vue'
import SetupBehaviorPanel from '@/components/setup/SetupBehaviorPanel.vue'
import SetupConnectionPanel from '@/components/settings/SetupConnectionPanel.vue'
import SetupProviderPanel from '@/components/setup/SetupProviderPanel.vue'
import SetupRouterPanel from '@/components/setup/SetupRouterPanel.vue'
import SetupChannelsPanel from '@/components/setup/SetupChannelsPanel.vue'
import SetupCapabilitiesPanel from '@/components/setup/SetupCapabilitiesPanel.vue'
import SettingsPrivacyPanel from '@/components/settings/SettingsPrivacyPanel.vue'
import SettingsAppearancePanel from '@/components/settings/SettingsAppearancePanel.vue'
import SettingsKeyboardPanel from '@/components/settings/SettingsKeyboardPanel.vue'
import SettingsAdvancedPanel from '@/components/settings/SettingsAdvancedPanel.vue'
import DesktopRuntimePanel from '@/components/settings/DesktopRuntimePanel.vue'
import { useSetupCatalog, SETTINGS_SECTIONS } from '@/composables/setup/useSetupCatalog'
import { sectionFromRouteParam } from '@/composables/setup/useSettingsSection'
import { useConfirm } from '@/composables/useConfirm'
import { usePlatform } from '@/platform'
import '@/styles/settings-forms.css'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { confirm, confirmState } = useConfirm()

// Desktop owns a local gateway, so it exposes a Runtime section the web build
// hides. `desktopOnly` sections are filtered out everywhere else.
const isDesktop = usePlatform().capabilities.isDesktop
const visibleSections = computed(() => SETTINGS_SECTIONS.filter(s => !s.desktopOnly || isDesktop))

const {
  section,
  setSection,
  loaded,
  providerPanel,
  behaviorPanel,
  privacyPanel,
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
  setAutoSessionTitles,
  setDisableNetworkObservability,
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
  saveChannel,
  enableChannel,
  disableChannel,
  removeChannel,
  saveSearch,
  saveMemory,
  saveImage,
  saveAudio,
  copyCommand,
  copyConfigPath,
} = useSetupCatalog()

const modalRef = ref<HTMLElement | null>(null)
const railRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)

// Keep the active section's rail tab in view — on mobile the rail scrolls
// horizontally, so a deep-linked or later section would otherwise sit off-screen.
function scrollActiveTabIntoView() {
  void nextTick(() => {
    const el = railRef.value?.querySelector<HTMLElement>('.settings-rail__item.is-active')
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  })
}
// Drives the modal's enter/leave <Transition>. Closing flips this to false so the
// leave animation plays; the actual route navigation is deferred to onLeaveComplete.
const visible = ref(true)
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
  const resolved = sectionFromRouteParam(routeParam.value)
  // A desktopOnly section requested where it is unavailable (e.g. a stale
  // /settings/runtime deep link on web) has no rail entry or panel branch; fall
  // back to the default so the dialog never renders an empty body.
  setSection(visibleSections.value.some(s => s.id === resolved) ? resolved : 'provider')
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
function navigateAway() {
  // Never route close through bare '/': its redirect re-runs the saved-route
  // logic and could bounce back into Settings. Push the platform default view
  // directly (same breakpoint as the '/' redirect in sharedRoutes) so close is a
  // single, predictable, loop-proof exit. `returnTo` is already null for a cold
  // deep link (onMounted rejects any '/settings…' back-entry).
  const fallback = window.matchMedia('(max-width: 768px)').matches ? '/chat' : '/sessions'
  void router.push(returnTo ?? fallback)
}

// The modal's leave transition finished — perform the deferred navigation that
// actually unmounts the overlay. Vue fires this on the next frame even when the
// transition is disabled (reduced motion), so close never stalls.
function onLeaveComplete() {
  if (closing) navigateAway()
}

function closeOverlay() {
  if (closing) return
  closing = true
  // Restore focus to the invoker synchronously (don't wait out the leave
  // animation) so keyboard users and the focus-return tests see focus land now.
  const target = usableInvoker() ?? sidebarSettingsButton()
  target?.focus()
  invokerEl = null
  // Flip visibility to play the modal's leave transition; onLeaveComplete then
  // navigates away (which unmounts the route component).
  visible.value = false
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

// Whenever the active section changes (rail click, deep link, Back), bring its
// tab into view on the horizontally-scrolling mobile rail.
watch(section, scrollActiveTabIntoView)

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
  scrollActiveTabIntoView()
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
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-modal);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  height: min(85vh, 100%);
  overflow: hidden;
  width: min(1200px, 100%);
}

/* Symmetric modal motion: slides up + fades in on open, slides down + fades out
   on close. The close navigation is deferred until this leave finishes (see
   closeOverlay / onLeaveComplete), so unlike the old entrance-only keyframe the
   modal no longer pops out instantly. Tokens: entrance decelerates; the exit is
   a tier faster and accelerates. */
.settings-pop-enter-active {
  transition: opacity var(--dur-base) var(--ease-out),
              transform var(--dur-base) var(--ease-out);
}
.settings-pop-leave-active {
  transition: opacity var(--dur-fast) var(--ease-in),
              transform var(--dur-fast) var(--ease-in);
}
.settings-pop-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.settings-pop-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .settings-pop-enter-active,
  .settings-pop-leave-active {
    transition: none;
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
  border-radius: var(--radius-full);
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
.settings-rail__dot.is-warn { background: var(--warn-fill); }
.settings-rail__dot.is-muted { background: var(--text-dim); opacity: 0.5; }

.settings-rail__dirty {
  background: var(--accent);
  border-radius: 50%;
  flex-shrink: 0;
  height: 5px;
  width: 5px;
}

/* Quiet uppercase eyebrow that heads each rail group (see .control-nav-group__label).
   Non-interactive, so it never enters the tab order. */
.settings-rail__group {
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  margin: var(--sp-3) 0 var(--sp-1);
  padding: 0 var(--sp-3);
  text-transform: uppercase;
}

.settings-rail__group:first-child {
  margin-top: 0;
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
    /* Signal that the strip scrolls: fade the leading/trailing edges, and snap
       tabs so they don't end mid-cut. (black = opaque in an alpha mask.) */
    scroll-snap-type: x proximity;
    -webkit-mask-image: linear-gradient(to right, transparent 0, black 16px, black calc(100% - 16px), transparent 100%);
    mask-image: linear-gradient(to right, transparent 0, black 16px, black calc(100% - 16px), transparent 100%);
  }

  .settings-rail__item {
    flex-shrink: 0;
    min-height: 44px;
    scroll-snap-align: start;
  }

  /* The horizontal chip strip stays flat — group eyebrows would break the row. */
  .settings-rail__group {
    display: none;
  }

  .settings-panel {
    padding: var(--sp-3);
  }

  .settings-foot {
    padding-bottom: max(var(--sp-2), env(safe-area-inset-bottom));
  }
}
</style>
