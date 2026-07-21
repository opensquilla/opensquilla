<template>
  <div class="ch-stage control-stage">
    <header v-if="!selectedChannel" class="ch-stage__header control-stage__header">
      <div class="ch-stage__title-block control-stage__title-block">
        <h1 class="ch-stage__title control-stage__title">{{ t('console.channels.title') }}</h1>
        <p class="ch-stage__subtitle control-stage__subtitle">{{ t('console.channels.subtitle') }}</p>
      </div>
      <div class="ch-stage__actions control-stage__actions">
        <button class="btn btn--primary" type="button" @click="openChannelCompose">
          <Icon name="plus" :size="16" aria-hidden="true" />
          <span>{{ t('console.channels.addChannel') }}</span>
        </button>
        <button class="btn btn--ghost" type="button" :title="t('console.common.refresh')" :disabled="loading || refreshing" @click="manualRefresh">
          <Icon name="refresh" :size="16" aria-hidden="true" :class="{ 'is-spinning': refreshing }" />
          <span>{{ refreshing ? t('console.common.refreshing') : t('console.common.refresh') }}</span>
        </button>
      </div>
    </header>

    <PendingRestartBanner />

    <!-- A background refresh failure keeps the last-good rows and warns inline;
         the full-page error only stands in when the very first load fails. -->
    <p v-if="error && channels.length > 0" class="ch-stale" role="status">
      <Icon name="info" :size="15" aria-hidden="true" />
      <span>{{ t('console.channels.staleData', { time: lastUpdatedLabel }) }}</span>
      <button type="button" class="btn btn--ghost" @click="manualRefresh">{{ t('console.common.retry') }}</button>
    </p>

    <ErrorState v-if="error && channels.length === 0" :message="error" :on-retry="loadData" />

    <div v-else-if="loading && channels.length === 0" class="control-empty">
      <LoadingSpinner />
    </div>

    <section v-else-if="channels.length === 0 && unconfiguredChannels.length === 0" class="control-empty ch-empty">
      <div class="ch-empty__icon" aria-hidden="true"><Icon name="channels" :size="34" /></div>
      <div class="control-empty__title">{{ t('console.channels.emptyTitle') }}</div>
      <p class="control-empty__hint">{{ t('console.channels.emptyMsg') }}</p>
      <button class="btn btn--primary" type="button" @click="openChannelCompose">
        <Icon name="plus" :size="16" aria-hidden="true" />
        <span>{{ t('console.channels.addFirstChannel') }}</span>
      </button>
    </section>

    <!-- ================= Drill-in: one channel as a full page ============= -->
    <section
      v-else-if="selectedChannel"
      ref="pageRef"
      class="chd"
      :aria-label="t('console.channels.detailLabel', { name: selectedName })"
    >
      <nav class="chd__crumb">
        <button type="button" class="chd__back" @click="requestLeaveDetail">
          <span aria-hidden="true">‹</span>
          <span>{{ t('console.channels.compose.back') }}</span>
        </button>
        <span class="chd__crumb-sep" aria-hidden="true">/</span>
        <span class="chd__crumb-name">{{ selectedName }}</span>
      </nav>

      <header class="chd__head">
        <ChannelBrandMark
          class="chd__mark"
          :type="String(selectedChannel.type || '')"
          :label="providerLabel(selectedChannel.type, t('console.channels.unknown'))"
        />
        <div class="chd__title">
          <h2>{{ selectedName }}</h2>
          <p class="chd__factsline">
            <ChannelStatusPill
              :status="selectedChannel.status"
              :enabled="selectedChannel.enabled"
              :pending-restart="pendingRestart.isPending(selectedName)"
              :error-class="lastErrorClass(selectedChannel.diagnostics)"
              :startup-failed="startupFailure(selectedChannel.diagnostics)"
              show-cause
            />
            <span class="chd__fact">{{ transportLabel(selectedChannel, t('console.channels.notReported')) }}</span>
            <button
              v-if="selectedChannel.bot_user_id"
              type="button"
              class="chd__fact chd__fact--mono chd__botid"
              :title="t('console.channels.detail.copyBotId', { id: selectedChannel.bot_user_id })"
              @click="copyBotId(selectedChannel.bot_user_id)"
            >{{ t('console.channels.detail.bot', { id: truncateId(selectedChannel.bot_user_id) }) }}</button>
            <span v-if="selectedChannel.connected_since" class="chd__fact" :title="formatSince(selectedChannel.connected_since, locale)">
              {{ t('console.channels.detail.connectedFor', { duration: formatConnectedDuration(selectedChannel.connected_since) }) }}
            </span>
            <span v-if="(selectedChannel.restart_attempts ?? 0) > 0" class="chd__fact">{{ restartsLabel(selectedChannel) }}</span>
          </p>
        </div>
        <!-- Runtime ops first, then configuration writes, destructive Remove
             isolated at the far edge — the row encodes the cost gradient. -->
        <div class="chd__actions" role="group" :aria-label="t('console.channels.opsActionsLabel')">
          <button class="btn btn--ghost" type="button" :disabled="actionPending(selectedChannel, 'probe')" @click="probeChannel(selectedChannel)">
            <Icon name="gauge" :size="15" aria-hidden="true" />
            <span>{{ actionPending(selectedChannel, 'probe') ? t('console.channels.testing') : t('console.channels.testConnection') }}</span>
          </button>
          <button
            class="btn btn--ghost"
            type="button"
            :disabled="actionPending(selectedChannel, 'restart') || selectedChannel.enabled === false || !adapterLoaded(selectedChannel)"
            :title="selectedChannel.enabled !== false && !adapterLoaded(selectedChannel) ? t('console.channels.restartNotLoaded') : undefined"
            @click="restartChannel(selectedChannel)"
          >
            <Icon name="refresh" :size="15" aria-hidden="true" />
            <span>{{ t('console.channels.restart') }}</span>
          </button>
          <button class="btn btn--ghost" type="button" :disabled="actionPending(selectedChannel, 'toggle')" :title="t('console.channels.configActionHint')" @click="toggleChannel(selectedChannel)">
            <span>{{ selectedChannel.enabled === false ? t('console.channels.enable') : t('console.channels.disable') }}</span>
          </button>
          <button class="btn btn--ghost chd__remove" type="button" :disabled="actionPending(selectedChannel, 'remove')" :title="t('console.channels.configActionHint')" @click="removeChannel(selectedChannel)">
            <span>{{ t('console.channels.removeChannel') }}</span>
          </button>
        </div>
      </header>

      <div v-if="selectedProbe" :class="['ch-probe-result', probeToneClass(selectedProbe)]" role="status">
        <Icon :name="selectedProbe.status === 'verified' ? 'check' : 'info'" :size="17" aria-hidden="true" />
        <div>
          <strong>{{ probeTitle(selectedProbe) }}</strong>
          <p>{{ probeResultDetail(selectedChannel) }}</p>
          <button v-if="selectedProbe.status === 'failed'" class="btn btn--ghost ch-probe-result__edit" type="button" @click="enterEdit">
            <Icon name="edit" :size="13" aria-hidden="true" />
            <span>{{ t('console.channels.editCredentials') }}</span>
          </button>
        </div>
      </div>

      <!-- The same alert strip the dashboard card renders, so the two
           surfaces cannot drift. -->
      <ChannelAlerts
        :pending-pairing="drillPending"
        :pending-overflow="Math.max(0, drillPendingCount - 1)"
        :default-as-admin="drillDefaultAsAdmin"
        :error-text="drillErrorText"
        :show-fix-credentials="!editMode"
        :busy="pairingBusy(selectedName)"
        @approve="asAdmin => approvePairing(selectedName, drillPending, asAdmin)"
        @reject="rejectPairing(selectedName, drillPending)"
        @restart="restartChannel(selectedChannel)"
        @fix-credentials="enterEdit"
      />

      <div class="chd__cols">
        <nav class="chd__nav" :aria-label="t('console.channels.detailSections')">
          <button
            v-for="section in SECTIONS"
            :key="section"
            type="button"
            :class="{ 'is-active': activeSection === section }"
            @click="goToSection(section)"
          >
            <span>{{ t(`console.channels.tabs.${section}`) }}</span>
            <span v-if="section === 'pairings'" class="chd__nav-count">{{ memberCount }}</span>
            <span v-if="section === 'pairings' && pendingPairingCount > 0" class="ch-tab-badge" :aria-label="t('console.channels.pairings.pendingBadge', { count: pendingPairingCount })">{{ pendingPairingCount }}</span>
            <span v-if="section === 'configuration' && draftDirty" class="ch-tab-dirty" :title="t('console.channels.editor.unsavedAria')" :aria-label="t('console.channels.editor.unsavedAria')">●</span>
          </button>
        </nav>

        <div class="chd__main">
          <section id="chd-section-pairings" class="chd__section">
            <ChannelMembersPanel :members="members" :channel-name="selectedName" />
          </section>

          <section id="chd-section-configuration" class="chd__section">
            <section class="ch-panel">
              <div class="ch-panel__heading">
                <h3>{{ editMode ? t('console.channels.editor.editConfiguration') : t('console.channels.savedConfiguration') }}</h3>
                <button v-if="!editMode && canEditConfig" class="btn btn--ghost" type="button" @click="enterEdit"><Icon name="edit" :size="14" />{{ t('console.channels.edit') }}</button>
              </div>
              <p class="ch-panel__intro">{{ editMode ? t('console.channels.editor.editIntro') : t('console.channels.secretRedactionHint') }}</p>
              <ChannelConfigEditor
                :editor="editor"
                :mode="editMode ? 'edit' : 'read'"
                @save-anyway="saveDraftAnyway"
                @retry="ensureConfigurationLoaded"
              />
            </section>
          </section>

          <section id="chd-section-diagnostics" class="chd__section">
            <section v-if="lastError(selectedChannel)" class="ch-alert is-danger">
              <Icon name="info" :size="18" /><div><strong>{{ t('console.channels.lastError') }}</strong><p>{{ lastError(selectedChannel) }}</p></div>
            </section>
            <section class="ch-panel">
              <h3>{{ t('console.channels.messageDelivery') }}</h3>
              <div class="ch-metrics">
                <div><strong>{{ deliveryCount(selectedChannel, 'ingress', 'accepted') }}</strong><span>{{ t('console.channels.acceptedIngress') }}</span></div>
                <div><strong>{{ deliveryCount(selectedChannel, 'ingress', 'processing') }}</strong><span>{{ t('console.channels.processingIngress') }}</span></div>
                <div><strong>{{ deliveryCount(selectedChannel, 'outbox', 'sent') }}</strong><span>{{ t('console.channels.confirmedOutbound') }}</span></div>
                <div :class="{ 'is-warn': deliveryCount(selectedChannel, 'outbox', 'unknown') > 0 }"><strong>{{ deliveryCount(selectedChannel, 'outbox', 'unknown') }}</strong><span>{{ t('console.channels.needsReview') }}</span></div>
              </div>
            </section>
            <section class="ch-panel ch-facts">
              <h3>{{ t('console.channels.connectionOwner') }}</h3>
              <dl>
                <div><dt>{{ t('console.channels.owner') }}</dt><dd>{{ ownerSummary(selectedChannel) }}</dd></div>
                <div v-if="selectedProbe"><dt>{{ t('console.channels.lastTest') }}</dt><dd>{{ selectedProbe.status }}</dd></div>
              </dl>
            </section>
            <!-- Capability reference folded away: health facts stay primary,
                 the platform feature table is consultation material. -->
            <details class="ch-tech">
              <summary>
                <span>{{ t('console.channels.detail.capabilityReference') }}</span>
                <span v-if="maturityKey(selectedChannel) !== 'unrated'" class="ch-maturity" :title="t('console.channels.maturityHint')">{{ maturityLabel(selectedChannel) }}</span>
              </summary>
              <p class="ch-panel__intro">{{ t('console.channels.worksHint') }}</p>
              <div v-if="platformRows(selectedChannel).length" class="ch-capabilities">
                <div v-for="row in platformRows(selectedChannel)" :key="row.category" class="ch-capability">
                  <Icon :name="row.tone === 'ok' ? 'check' : row.tone === 'warn' ? 'info' : 'x'" :size="15" :class="`is-${row.tone}`" />
                  <div><strong>{{ t(`console.channels.category.${row.category}`) }}</strong><span v-if="row.notes">{{ row.notes }}</span></div>
                  <span :class="['ch-proof', row.tone === 'ok' ? 'is-effective' : row.tone === 'warn' ? 'is-config' : 'is-declared']">{{ platformStatusLabel(row.status) }}</span>
                </div>
              </div>
              <div v-if="capabilityRows(selectedChannel).length" class="ch-capabilities">
                <div v-for="capability in capabilityRows(selectedChannel)" :key="capability.name" class="ch-capability">
                  <Icon :name="capability.effective ? 'check' : 'info'" :size="15" />
                  <div><strong>{{ humanize(capability.name) }}</strong><span>{{ evidenceLabel(capability) }}</span></div>
                  <span :class="['ch-proof', capability.effective ? 'is-effective' : 'is-declared']">{{ capability.effective ? t('console.channels.implemented') : t('console.channels.declaredOnly') }}</span>
                </div>
              </div>
              <p v-if="!platformRows(selectedChannel).length && !capabilityRows(selectedChannel).length" class="ch-muted chd__no-evidence">{{ t('console.channels.noCapabilityEvidence') }}</p>
            </details>
          </section>
        </div>
      </div>
    </section>

    <!-- ================= Home: dashboard of channel cards ================= -->
    <section v-else class="chb" :aria-label="t('console.channels.configuredChannels')">
      <p v-if="queryMissing" class="ch-query-missing" role="status">
        <span>{{ t('console.channels.queryNotFound', { name: selectedName }) }}</span>
        <button type="button" class="btn btn--ghost" @click="leaveDetail">{{ t('console.channels.queryNotFoundDismiss') }}</button>
      </p>
      <div class="chb__grid">
        <article
          v-for="ch in channels"
          :key="channelKey(ch)"
          class="chb-card"
          :class="{ 'is-muted': ch.enabled === false }"
          role="button"
          tabindex="0"
          :aria-label="t('console.channels.detailLabel', { name: channelKey(ch) })"
          @click="openChannel(ch)"
          @keydown.enter.self="openChannel(ch)"
          @keydown.space.self.prevent="openChannel(ch)"
        >
          <div class="chb-card__top">
            <ChannelBrandMark :type="String(ch.type || '')" :label="providerLabel(ch.type, t('console.channels.unknown'))" />
            <div class="chb-card__id">
              <strong class="chb-card__name">{{ channelKey(ch) }}</strong>
              <span class="chb-card__sub">{{ cardSubline(ch) }}</span>
            </div>
            <ChannelStatusPill
              class="chb-card__status"
              :status="ch.status"
              :enabled="ch.enabled"
              :pending-restart="pendingRestart.isPending(channelKey(ch))"
              :error-class="lastErrorClass(ch.diagnostics)"
              :startup-failed="startupFailure(ch.diagnostics)"
            />
          </div>
          <div class="chb-card__facts">
            <div class="chb-fact"><span class="chb-fact__k">{{ t('console.channels.home.connectedFor') }}</span><span class="chb-fact__v">{{ connectedDuration(ch) }}</span></div>
            <div class="chb-fact"><span class="chb-fact__k">{{ t('console.channels.home.membersFact') }}</span><span class="chb-fact__v">{{ factValue(ch, 'members') }}</span></div>
            <div class="chb-fact"><span class="chb-fact__k">{{ t('console.channels.home.adminsFact') }}</span><span class="chb-fact__v">{{ factValue(ch, 'admins') }}</span></div>
            <span
              v-if="cardPendingCount(ch) > 0"
              class="chb-card__pending"
              :title="t('console.channels.pairings.pendingBadge', { count: cardPendingCount(ch) })"
            >{{ t('console.channels.home.pendingCount', { count: cardPendingCount(ch) }) }}</span>
          </div>
          <ChannelAlerts
            :pending-pairing="cardPending(ch)"
            :pending-overflow="Math.max(0, cardPendingCount(ch) - 1)"
            :default-as-admin="cardDefaultAsAdmin(ch)"
            :error-text="cardErrorText(ch)"
            show-fix-credentials
            :busy="pairingBusy(channelKey(ch))"
            @approve="asAdmin => approvePairing(channelKey(ch), cardPending(ch), asAdmin)"
            @reject="rejectPairing(channelKey(ch), cardPending(ch))"
            @restart="restartChannel(ch)"
            @fix-credentials="fixCredentials(ch)"
          />
          <div class="chb-card__foot">
            <button
              v-if="ch.enabled === false"
              class="btn btn--ghost"
              type="button"
              :disabled="actionPending(ch, 'toggle')"
              @click.stop="toggleChannel(ch)"
            >{{ t('console.channels.enable') }}</button>
            <template v-else>
              <button
                class="btn btn--ghost"
                type="button"
                :disabled="actionPending(ch, 'probe')"
                @click.stop="probeChannel(ch)"
              >{{ actionPending(ch, 'probe') ? t('console.channels.testing') : t('console.channels.testConnection') }}</button>
              <button
                class="btn btn--ghost"
                type="button"
                :disabled="actionPending(ch, 'restart') || !adapterLoaded(ch)"
                :title="!adapterLoaded(ch) ? t('console.channels.restartNotLoaded') : undefined"
                @click.stop="restartChannel(ch)"
              >{{ t('console.channels.restart') }}</button>
            </template>
            <span class="chb-card__go" aria-hidden="true">{{ t('console.channels.home.details') }} →</span>
          </div>
        </article>

        <!-- Channels running in this gateway process but absent from config —
             surfaced so an operator can see an orphaned runtime channel. -->
        <article
          v-for="ch in unconfiguredChannels"
          :key="`unconfigured-${channelKey(ch)}`"
          class="chb-card is-muted is-static"
        >
          <div class="chb-card__top">
            <ChannelBrandMark :type="String(ch.type || '')" :label="providerLabel(ch.type, t('console.channels.unknown'))" />
            <div class="chb-card__id">
              <strong class="chb-card__name">{{ channelKey(ch) }}</strong>
              <span class="chb-card__sub">{{ t('console.channels.unconfiguredTitle') }}</span>
            </div>
            <ChannelStatusPill class="chb-card__status" :status="ch.status" :enabled="ch.enabled" :error-class="lastErrorClass(ch.diagnostics)" />
          </div>
          <p class="chb-card__hint">{{ t('console.channels.unconfiguredHint') }}</p>
        </article>

        <button type="button" class="chb-card chb-card--add" @click="openChannelCompose">
          <span aria-hidden="true">＋</span>
          <span>{{ t('console.channels.addChannel') }}</span>
        </button>
      </div>
    </section>

    <!-- Floating dirty bar: the page scrolls as a whole now, so the unsaved
         pill rides fixed at bottom-center instead of pinning to an aside. -->
    <Transition name="ceb-slide">
      <div v-if="editorBarVisible" class="chd-dirtybar">
        <ChannelEditorActionBar
          :changed-labels="editedLabels"
          :confirm-pending="discardRequest !== null"
          :testing="probeRunning"
          :saving="editorSaving"
          @test="testDraft"
          @discard="discardDraftAndExitEdit"
          @save="saveDraft"
          @keep-editing="resolveDiscard(false)"
          @confirm-discard="resolveDiscard(true)"
        />
      </div>
    </Transition>

    <!-- Add-channel takeover: centered surface over a scrim; gallery pre-pick,
         receipt chip + the shared config editor (compose mode) post-pick. -->
    <ChannelComposeSurface
      v-if="composeMode"
      :editor="composeEditor"
      :picked-type="composeType"
      :confirm-pending="composeDiscardRequest !== null"
      :saving="composeSaving"
      @exit="requestExitCompose"
      @pick="pickComposeType"
      @change="requestComposeRepick"
      @test="composeTest"
      @save="composeSave"
      @save-anyway="composeSaveAnyway"
      @keep-editing="resolveComposeDiscard(false)"
      @confirm-discard="resolveComposeDiscard(true)"
      @load-catalog="composeEditor.loadCatalog"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import ChannelStatusPill from '@/components/ChannelStatusPill.vue'
import ChannelAlerts from '@/components/channels/ChannelAlerts.vue'
import ChannelBrandMark from '@/components/setup/ChannelBrandMark.vue'
import ChannelComposeSurface from '@/components/channels/ChannelComposeSurface.vue'
import ChannelConfigEditor from '@/components/channels/ChannelConfigEditor.vue'
import ChannelEditorActionBar from '@/components/channels/ChannelEditorActionBar.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import PendingRestartBanner from '@/components/PendingRestartBanner.vue'
import { useRequest } from '@/composables/useRequest'
import { usePendingRestart } from '@/composables/usePendingRestart'
import { useToasts } from '@/composables/useToasts'
import { useConfirm } from '@/composables/useConfirm'
import { useChannelEditor } from '@/composables/channels/useChannelEditor'
import { useChannelMembers, type ChannelPairing } from '@/composables/channels/useChannelMembers'
import { useChannelCatalogI18n } from '@/composables/setup/useChannelCatalogI18n'
import ChannelMembersPanel from '@/components/channels/ChannelMembersPanel.vue'
import {
  capabilityRows,
  channelKey,
  deliveryCount,
  delivery,
  diagnostics,
  formatConnectedDuration,
  formatSince,
  humanize,
  lastError,
  maturityKey,
  MATURITY_KEYS,
  platformRows,
  providerLabel,
  record,
  transportLabel,
  type CapabilityEvidence,
  type Channel,
  type ProbeResult,
} from '@/composables/channels/channelFacts'
import {
  CHANNEL_STATUS_ORDER,
  adapterLoaded,
  lastErrorClass,
  startupFailure,
  statusPresentation,
  type ChannelStatusKey,
} from '@/lib/channelStatus'

interface ChannelsStatusResponse { channels?: Channel[] }
type DetailTab = 'overview' | 'pairings' | 'configuration' | 'diagnostics'
type SectionId = 'pairings' | 'configuration' | 'diagnostics'

const STATUS_SEVERITY = Object.fromEntries(
  CHANNEL_STATUS_ORDER.map((key, index) => [key, index]),
) as Record<ChannelStatusKey, number>
const DETAIL_TABS: DetailTab[] = ['overview', 'pairings', 'configuration', 'diagnostics']
const SECTIONS: SectionId[] = ['pairings', 'configuration', 'diagnostics']

const { t, locale } = useI18n()
const rpc = useRpcStore()
const router = useRouter()
const route = useRoute()
const { pushToast } = useToasts()
const { confirm } = useConfirm()
const pendingRestart = usePendingRestart()
const selectedName = ref('')
const detailTab = ref<DetailTab>('overview')
const pageRef = ref<HTMLElement | null>(null)
const pendingActions = ref(new Set<string>())
const probeResults = ref<Record<string, ProbeResult>>({})
// In-place configuration editor: draft state is owned by the view (not the
// section body), so scrolling to Members/Diagnostics keeps an unsaved draft
// alive and the Configuration sidenav dot stays lit.
const editor = useChannelEditor()
const editMode = ref(false)
const editorSaving = ref(false)
// Pending inline discard confirmation (the centralized guard's UI state).
const discardRequest = ref<{ resolve: (ok: boolean) => void } | null>(null)
// Compose takeover: a SECOND editor instance so an add-channel draft can
// never cross-contaminate the selected channel's edit draft.
const composeEditor = useChannelEditor()
const composeMode = ref(false)
const composeType = ref('')
const composeSaving = ref(false)
const composeDiscardRequest = ref<{ resolve: (ok: boolean) => void } | null>(null)
// Members (pairings + channel admins) for the drilled-in channel — state owned
// here so it survives section scrolling; ChannelMembersPanel renders it.
const members = useChannelMembers()

const { data: channelsData, loading, error, execute, refresh } = useRequest<ChannelsStatusResponse>(
  'channels.status', undefined, { immediate: false, errorLabel: t('console.channels.loadFailed') },
)

const channels = computed<Channel[]>(() => {
  const raw = (channelsData.value?.channels || []).filter(ch => ch && ch.configured !== false)
  return [...raw].sort(
    (a, b) => STATUS_SEVERITY[presentationFor(a).key] - STATUS_SEVERITY[presentationFor(b).key],
  )
})
// Channels running in this gateway process but absent from config.
const unconfiguredChannels = computed<Channel[]>(() =>
  (channelsData.value?.channels || []).filter(ch => ch && ch.configured === false))
const selectedChannel = computed(() => channels.value.find(ch => channelKey(ch) === selectedName.value) || null)
const selectedProbe = computed(() =>
  selectedChannel.value ? probeResults.value[channelKey(selectedChannel.value)] : undefined)

const loadData = refresh
let pollTimer: ReturnType<typeof setInterval> | null = null
let unsubs: Array<() => void> = []
let activatedOnce = false
const refreshing = ref(false)
const lastUpdatedAt = ref<number | null>(null)
const lastUpdatedLabel = computed(() =>
  lastUpdatedAt.value ? new Date(lastUpdatedAt.value).toLocaleTimeString() : '—')

async function manualRefresh(): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await refresh()
    if (!error.value) lastUpdatedAt.value = Date.now()
    await loadHomeFacts()
  } finally {
    refreshing.value = false
  }
}

function teardownLive() {
  unsubs.forEach(unsub => unsub())
  unsubs = []
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  document.removeEventListener('keydown', onDocumentKeydown)
  detachScrollSpy()
}

// Esc is two-stage while a draft surface is up: the first press blurs the
// focused field, the second acts as Cancel (guarded). Handled once at the
// document level so a press can never skip a stage.
function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (composeMode.value) {
    const active = document.activeElement
    if (
      active instanceof HTMLElement && active.closest('.chc') &&
      (active instanceof HTMLInputElement || active instanceof HTMLSelectElement || active instanceof HTMLTextAreaElement)
    ) {
      active.blur()
      return
    }
    void requestExitCompose()
    return
  }
  if (!selectedName.value || !editMode.value) return
  const active = document.activeElement
  if (
    active instanceof HTMLElement && pageRef.value?.contains(active) &&
    (active instanceof HTMLInputElement || active instanceof HTMLSelectElement || active instanceof HTMLTextAreaElement)
  ) {
    active.blur()
    return
  }
  void requestExitEdit()
}

onActivated(() => {
  applyDetailQuery()
  if (!activatedOnce) { activatedOnce = true; void execute() } else { void refresh() }
  // Background catalog refresh: the module-scope cache keeps rendering while
  // a newer field-spec snapshot lands.
  void editor.refreshCatalog()
  void loadHomeFacts()
  unsubs = [rpc.on('channel.status', () => { void refresh() })]
  pollTimer = setInterval(() => {
    void refresh().then(() => { if (!error.value) lastUpdatedAt.value = Date.now() })
  }, 30000)
  document.addEventListener('keydown', onDocumentKeydown)
  // Returning to /channels while still drilled in: teardownLive removed the
  // scrollspy on deactivate and the selectedChannel watcher will not re-fire
  // (the value never changed), so the listener must be re-armed here.
  if (selectedChannel.value) void nextTick(attachScrollSpy)
  lastUpdatedAt.value = Date.now()
})
onDeactivated(() => {
  teardownLive()
  // Draft surfaces are dropped only AFTER the navigation finalizes: the
  // route-leave guard below must not mutate watched state while vue-router
  // still has a pending navigation, because the query watcher's replace
  // would supersede (and silently cancel) the user's navigation. By the
  // time onDeactivated runs, route.path has moved on, so syncQuery no-ops.
  if (editMode.value) discardDraftAndExitEdit()
  if (composeMode.value) exitCompose()
})
onUnmounted(teardownLive)

// Route leave is a guarded exit for BOTH drafts: an unsaved edit or compose
// draft raises its inline confirm and the navigation waits on the verdict.
// The guard only answers the confirm — the actual draft teardown happens in
// onDeactivated, after the navigation has finalized (see above).
onBeforeRouteLeave(async () => {
  if (draftDirty.value && !(await confirmDiscardDraft())) return false
  if (composeDirty.value && !(await confirmDiscardCompose())) return false
  return true
})

/**
 * Enter the compose takeover — a history PUSH, so Back returns to the grid.
 * Guarded against a dirty edit draft; any drill-in closes behind the guard.
 */
async function openChannelCompose(): Promise<void> {
  if (composeMode.value) return
  if (draftDirty.value && !(await confirmDiscardDraft())) return
  if (editMode.value) discardDraftAndExitEdit()
  if (selectedName.value) forceCloseDetail()
  composeMode.value = true
  composeType.value = ''
  composeEditor.reset()
  void composeEditor.loadCatalog()
  syncQuery('push')
}

function presentationFor(ch: Channel) {
  return statusPresentation({
    status: ch.status,
    enabled: ch.enabled,
    connected: ch.connected,
    pendingRestart: pendingRestart.isPending(channelKey(ch)),
    errorClass: lastErrorClass(ch.diagnostics),
    startupFailed: startupFailure(ch.diagnostics),
  })
}

function statusText(ch: Channel): string {
  const pres = presentationFor(ch)
  return pres.key === 'unknown' ? t(pres.labelKey, { raw: pres.raw || '—' }) : t(pres.labelKey)
}

// Clear pending-restart entries the moment a status snapshot proves the
// restart happened. Reconcile against RAW rows (incl. configured:false).
watch(channelsData, data => {
  pendingRestart.reconcile(data?.channels || [])
  // The 30s poll (and channel.status events) must surface new pairing
  // requests: refetch facts for exactly the channels whose freshly reported
  // pending count no longer matches the cached facts (or whose facts fetch
  // previously failed).
  const stale = channels.value
    .filter(ch => {
      if (typeof ch.pendingPairings !== 'number') return false
      const facts = homeFacts.value[channelKey(ch)]
      if (!facts) return false
      return facts.pending == null || facts.pending.length !== ch.pendingPairings
    })
    .map(channelKey)
  if (stale.length > 0) void loadHomeFacts(stale)
})

// ---------------------------------------------------------------------------
// Home facts: the card grid renders REAL data only — per-channel pairings
// (member counts + the inline pending request) fetched in parallel, plus ONE
// bounded config read for channel_admin_senders. Nothing here is invented;
// a failed fetch degrades to "unknown" (rendered as —), never to hard zeros.
// ---------------------------------------------------------------------------

interface HomeFacts {
  /** null = the pairings fetch for this channel failed (unknown). */
  members: number | null
  /** null = the admin map could not be read (unknown). */
  admins: number | null
  /** null = the pairings fetch for this channel failed (unknown). */
  pending: ChannelPairing[] | null
}

const homeFacts = ref<Record<string, HomeFacts>>({})
let homeFactsRequest = 0

async function loadHomeFacts(only?: string[]): Promise<void> {
  const known = new Set(channels.value.map(channelKey))
  const names = (only ?? [...known]).filter(name => known.has(name))
  if (names.length === 0) return
  const id = ++homeFactsRequest
  try {
    await rpc.waitForConnection()
    // {} = known-empty (no admins configured anywhere); null = unknown (the
    // read failed) — the two must not be conflated, or a transient failure
    // would zero the admin count and re-arm the first-pairing bootstrap.
    const adminsPromise: Promise<Record<string, unknown> | null> = rpc
      .call<Record<string, unknown> | null>('config.get', { path: 'channel_admin_senders' })
      .then(map => record(map))
      .catch(() => null)
    const pairingsByName = await Promise.all(names.map(async name => {
      try {
        const res = await rpc.call<{ pairings?: ChannelPairing[] }>('channels.pairings', { channelName: name })
        return [name, (res?.pairings || []).filter(pairing => pairing.channelName === name)] as const
      } catch {
        return [name, null] as const
      }
    }))
    const adminsMap = await adminsPromise
    if (id !== homeFactsRequest) return
    const next: Record<string, HomeFacts> = { ...homeFacts.value }
    for (const [name, rows] of pairingsByName) {
      const adminList = adminsMap ? adminsMap[name] : null
      next[name] = {
        members: rows ? rows.filter(pairing => pairing.status === 'approved').length : null,
        admins: adminsMap ? (Array.isArray(adminList) ? adminList.length : 0) : null,
        pending: rows ? rows.filter(pairing => pairing.status === 'pending') : null,
      }
    }
    homeFacts.value = next
  } catch {
    // Facts are supplementary: a failed load keeps the cards rendering from
    // channels.status alone (facts show as —).
  }
}

// Reload facts whenever the configured channel set itself changes.
const factsSignature = computed(() => channels.value.map(channelKey).sort().join('\n'))
watch(factsSignature, signature => {
  if (signature) void loadHomeFacts()
}, { immediate: true })

function cardFacts(ch: Channel): HomeFacts | undefined {
  return homeFacts.value[channelKey(ch)]
}

function factValue(ch: Channel, kind: 'members' | 'admins'): string {
  const value = cardFacts(ch)?.[kind]
  return value == null ? '—' : String(value)
}

function connectedDuration(ch: Channel): string {
  return ch.connected_since ? formatConnectedDuration(ch.connected_since) : '—'
}

function cardSubline(ch: Channel): string {
  const parts = [transportLabel(ch, t('console.channels.notReported'))]
  const botId = String(ch.bot_user_id || '')
  if (botId) parts.push(t('console.channels.detail.bot', { id: shortId(botId) }))
  return parts.join(' · ')
}

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 12)}…` : id
}

function cardPending(ch: Channel): ChannelPairing | null {
  return cardFacts(ch)?.pending?.[0] || null
}

function cardPendingCount(ch: Channel): number {
  // Prefer the freshly polled status count (channels.status refreshes every
  // 30s); the detailed facts fill in when status does not report one.
  if (typeof ch.pendingPairings === 'number') return ch.pendingPairings
  return cardFacts(ch)?.pending?.length ?? 0
}

// First-pairing bootstrap: the "as admin" checkbox defaults on only when the
// channel is KNOWN to have no approved pairings and no admin senders. An
// unknown state (either fetch failed) must never default the grant on.
function cardDefaultAsAdmin(ch: Channel): boolean {
  const facts = cardFacts(ch)
  return Boolean(facts && facts.members === 0 && facts.admins === 0)
}

function cardErrorText(ch: Channel): string {
  if (presentationFor(ch).tone !== 'danger') return ''
  const detail = lastError(ch)
  const text = detail || statusText(ch)
  return text.length > 160 ? `${text.slice(0, 159)}…` : text
}

// ---------------------------------------------------------------------------
// Card quick actions for pairings: approve/reject right on the surface that
// showed the request. Deliberately confirmation-free (they are one-shot quick
// actions); the Members section keeps its confirmed, admin-capable flow.
// ---------------------------------------------------------------------------

function pairingBusy(name: string): boolean {
  return pendingActions.value.has(`${name}:pairing`)
}

async function withPendingKey(key: string, run: () => Promise<void>): Promise<void> {
  if (pendingActions.value.has(key)) return
  pendingActions.value = new Set(pendingActions.value).add(key)
  try { await run() } finally {
    const next = new Set(pendingActions.value)
    next.delete(key)
    pendingActions.value = next
  }
}

async function approvePairing(name: string, pairing: ChannelPairing | null, asAdmin: boolean): Promise<void> {
  if (!pairing) return
  const sender = pairing.senderName || pairing.senderId
  await withPendingKey(`${name}:pairing`, async () => {
    try {
      // Only include asAdmin when set: a plain approval keeps its minimal
      // payload and never touches channel_admin_senders.
      const params: Record<string, unknown> = { channelName: name, pairingId: pairing.pairingId }
      if (asAdmin) params.asAdmin = true
      await rpc.call('channels.pairing.approve', params)
      pushToast(
        t(asAdmin ? 'console.channels.pairings.approveAdminSuccess' : 'console.channels.pairings.approveSuccess', { sender }),
        { tone: 'ok' },
      )
    } catch (err) {
      pushToast(t('console.channels.pairings.approveFailed', { sender, error: errorMessage(err) }), { tone: 'danger' })
    }
    await reloadPairingState(name)
  })
}

async function rejectPairing(name: string, pairing: ChannelPairing | null): Promise<void> {
  if (!pairing) return
  const sender = pairing.senderName || pairing.senderId
  await withPendingKey(`${name}:pairing`, async () => {
    try {
      await rpc.call('channels.pairing.revoke', { channelName: name, pairingId: pairing.pairingId })
      pushToast(t('console.channels.home.rejectSuccess', { sender }), { tone: 'ok' })
    } catch (err) {
      pushToast(t('console.channels.home.rejectFailed', { sender, error: errorMessage(err) }), { tone: 'danger' })
    }
    await reloadPairingState(name)
  })
}

async function reloadPairingState(name: string): Promise<void> {
  const jobs: Array<Promise<unknown>> = [loadHomeFacts(), refresh()]
  if (selectedName.value === name) jobs.push(members.load(name))
  await Promise.all(jobs)
}

/** Card escape hatch for a failing channel: drill straight into credentials. */
function fixCredentials(ch: Channel): void {
  applySelection(channelKey(ch))
  detailTab.value = 'configuration'
  editMode.value = true
  void ensureConfigurationLoaded()
  pendingScrollTab.value = 'configuration'
  syncQuery('push')
}

// ---------------------------------------------------------------------------
// Configuration editor: dirty state, centralized discard guard, save/test.
// ---------------------------------------------------------------------------

const draftDirty = computed(() => editor.form.isDirty.value)
const canEditConfig = computed(() => editor.canEdit.value)
// The bar names changed fields with the same localized labels the rail shows.
const { localizeFieldLabel } = useChannelCatalogI18n()
const editedLabels = computed(() => {
  const type = editor.entryType.value
  const labels = new Map(editor.specFields.value.map(field => [field.name, field.label]))
  return editor.editedFields.value.map(name =>
    localizeFieldLabel(type, name, labels.get(name) || name))
})
const probeRunning = computed(() => editor.probe.value.phase === 'running')
const editorBarVisible = computed(() =>
  (editMode.value && draftDirty.value) || discardRequest.value !== null)

/**
 * THE guard. Every draft-destroying exit — leaving the drill-in page, opening
 * compose, route leave, Esc-cancel — runs through this one gate. A clean
 * draft passes straight through (synchronously, via the `draftDirty`
 * short-circuit at each call site); a dirty one raises the inline
 * destructive-ghost pair in the floating bar and resolves with the verdict.
 */
function confirmDiscardDraft(): Promise<boolean> {
  if (!draftDirty.value) return Promise.resolve(true)
  // A newer guarded action supersedes a pending one, which resolves as "keep".
  if (discardRequest.value) discardRequest.value.resolve(false)
  return new Promise<boolean>(resolve => {
    discardRequest.value = { resolve }
  })
}

function resolveDiscard(ok: boolean): void {
  discardRequest.value?.resolve(ok)
  discardRequest.value = null
}

function discardDraftAndExitEdit(): void {
  editor.discard()
  editMode.value = false
}

function enterEdit(): void {
  if (!selectedChannel.value) return
  detailTab.value = 'configuration'
  editMode.value = true
  void ensureConfigurationLoaded()
  void nextTick(() => {
    scrollToSection('configuration')
    pageRef.value
      ?.querySelector<HTMLElement>('.cfge input:not([readonly]):not([type="checkbox"]), .cfge select')
      ?.focus()
  })
}

async function requestExitEdit(): Promise<void> {
  if (draftDirty.value && !(await confirmDiscardDraft())) return
  discardDraftAndExitEdit()
}

function ensureConfigurationLoaded(): Promise<void> {
  const name = selectedName.value
  if (!name) return Promise.resolve()
  if (editor.loadedName.value === name && editor.phase.value === 'active') return Promise.resolve()
  if (editor.phase.value === 'loading') return Promise.resolve()
  return editor.open(name)
}

// Draft Test probes the CURRENT DRAFT (onboarding.channel.probe {entry});
// the read-mode action-row Test keeps probing the SAVED channel live.
function testDraft(): void {
  void editor.testDraft()
}

async function saveDraft(): Promise<void> {
  if (editorSaving.value) return
  editorSaving.value = true
  try {
    handleSaveResult(await editor.save())
  } finally {
    editorSaving.value = false
  }
}

async function saveDraftAnyway(): Promise<void> {
  if (editorSaving.value) return
  editorSaving.value = true
  try {
    handleSaveResult(await editor.saveAnyway())
  } finally {
    editorSaving.value = false
  }
}

function handleSaveResult(result: Awaited<ReturnType<typeof editor.save>>): void {
  if (result.status === 'invalid') {
    pushToast(t('setup.channels.fixRequired'), { tone: 'danger' })
    return
  }
  // Probe failure keeps the draft: inline failure rows + [Save anyway].
  if (result.status === 'probe-failed') return
  if (result.status === 'error') {
    pushToast(t('console.channels.editor.saveFailed', { error: result.message || '' }), { tone: 'danger' })
    return
  }
  const outcome = result.outcome
  if (outcome) {
    if (outcome.name && outcome.changed && outcome.restartRequired) {
      const row = channels.value.find(ch => channelKey(ch) === outcome.name)
      pendingRestart.record(outcome.name, 'upsert', { wasLoaded: row ? adapterLoaded(row) : false })
    }
    if (outcome.liveApplyFailed) {
      pushToast(t('setup.toast.channelStartFailed'), { tone: 'danger' })
    } else {
      pushToast(t(outcome.restartRequired ? 'setup.toast.channelSaved' : 'setup.toast.channelSavedLive'), { tone: 'ok' })
    }
  }
  // Baseline already reset by the reseed; drop edit=1 → back to read mode.
  editMode.value = false
  void refresh()
}

// ---------------------------------------------------------------------------
// Compose takeover: pick a platform, fill an empty draft, probe, save.
// ---------------------------------------------------------------------------

const composeDirty = computed(() => composeEditor.form.isDirty.value)

/** Compose twin of confirmDiscardDraft(): the inline destructive-ghost pair
 *  renders in the takeover footer, never a modal. */
function confirmDiscardCompose(): Promise<boolean> {
  if (!composeDirty.value) return Promise.resolve(true)
  if (composeDiscardRequest.value) composeDiscardRequest.value.resolve(false)
  return new Promise<boolean>(resolve => {
    composeDiscardRequest.value = { resolve }
  })
}

function resolveComposeDiscard(ok: boolean): void {
  composeDiscardRequest.value?.resolve(ok)
  composeDiscardRequest.value = null
}

function exitCompose(): void {
  composeMode.value = false
  composeType.value = ''
  composeSaving.value = false
  resolveComposeDiscard(false)
  composeEditor.reset()
}

async function requestExitCompose(): Promise<void> {
  if (composeDirty.value && !(await confirmDiscardCompose())) return
  exitCompose()
}

function pickComposeType(type: string): void {
  composeType.value = type
  void composeEditor.startCompose(type)
}

/** [Change] on the receipt chip: back to the gallery, guarded when dirty. */
async function requestComposeRepick(): Promise<void> {
  if (composeDirty.value && !(await confirmDiscardCompose())) return
  composeType.value = ''
  composeEditor.reset()
  void composeEditor.loadCatalog()
}

function composeTest(): void {
  void composeEditor.testDraft()
}

async function composeSave(): Promise<void> {
  if (composeSaving.value) return
  composeSaving.value = true
  try {
    await handleComposeSaveResult(await composeEditor.save())
  } finally {
    composeSaving.value = false
  }
}

async function composeSaveAnyway(): Promise<void> {
  if (composeSaving.value) return
  composeSaving.value = true
  try {
    await handleComposeSaveResult(await composeEditor.saveAnyway())
  } finally {
    composeSaving.value = false
  }
}

async function handleComposeSaveResult(result: Awaited<ReturnType<typeof composeEditor.save>>): Promise<void> {
  if (result.status === 'invalid') {
    pushToast(t('setup.channels.fixRequired'), { tone: 'danger' })
    return
  }
  // Probe failure keeps the draft: inline failure rows + [Save anyway].
  if (result.status === 'probe-failed') return
  if (result.status === 'error') {
    pushToast(t('console.channels.editor.saveFailed', { error: result.message || '' }), { tone: 'danger' })
    return
  }
  const outcome = result.outcome
  if (outcome) {
    if (outcome.name && outcome.changed && outcome.restartRequired) {
      pendingRestart.record(outcome.name, 'upsert', { wasLoaded: false })
    }
    if (outcome.liveApplyFailed) {
      pushToast(t('setup.toast.channelStartFailed'), { tone: 'danger' })
    } else {
      pushToast(t(outcome.restartRequired ? 'setup.toast.channelSaved' : 'setup.toast.channelSavedLive'), { tone: 'ok' })
    }
  }
  // Dismiss the takeover and land on the new channel's page.
  composeMode.value = false
  composeType.value = ''
  composeEditor.reset()
  await refresh()
  if (outcome?.name) applySelection(outcome.name)
}

// ---------------------------------------------------------------------------
// Selection + drill-in lifecycle (all draft-destroying paths run the guard)
// ---------------------------------------------------------------------------

async function openChannel(ch: Channel): Promise<void> {
  // The dirty short-circuit keeps the clean path synchronous (no microtask
  // gap between click and drill) while every dirty exit hits the guard.
  if (draftDirty.value && !(await confirmDiscardDraft())) return
  applySelection(channelKey(ch))
  // Entering drill-in is a history PUSH: Back returns to the dashboard.
  syncQuery('push')
}

// The state wipe lives BEHIND the guard: nothing here runs until a dirty
// draft is explicitly discarded. edit=1 never carries over to a new channel.
function applySelection(name: string): void {
  selectedName.value = name
  detailTab.value = 'overview'
  activeSection.value = 'pairings'
  editMode.value = false
  editor.reset()
  members.reset()
}

/** Guarded exit used by the breadcrumb (‹ Channels). */
async function requestLeaveDetail(): Promise<void> {
  if (draftDirty.value && !(await confirmDiscardDraft())) return
  leaveDetail()
}

function leaveDetail(): void {
  if (editMode.value) discardDraftAndExitEdit()
  forceCloseDetail()
  // Approvals and admin grants made inside the page must show on the cards.
  void loadHomeFacts()
}

function forceCloseDetail(): void {
  selectedName.value = ''
  editMode.value = false
  editor.reset()
  members.reset()
}

// The ONE hydration path for the drill-in page: click-driven entry and
// query-driven activation (deep links, Back/forward, F5 restore) both mutate
// selectedName, and the full page shows every section at once — so members
// and configuration load together here. The settle promise is retained so a
// deep-linked section scroll can re-anchor once async content stops shifting
// the layout.
let hydration: Promise<unknown> = Promise.resolve()
watch(selectedName, name => {
  if (!name) return
  hydration = Promise.allSettled([ensureConfigurationLoaded(), members.load(name)])
})

// ---------------------------------------------------------------------------
// Sections: sticky sidenav + scrollspy over one scrolling page.
// ---------------------------------------------------------------------------

const activeSection = ref<SectionId>('pairings')
const pendingScrollTab = ref<DetailTab | null>(null)
let spyTarget: HTMLElement | Window | null = null
let spyHoldUntil = 0

const memberCount = computed(() =>
  members.pairings.value.filter(pairing => pairing.status === 'approved').length)
const pendingPairingCount = computed(() => members.pendingCount.value)

const drillPendingList = computed(() =>
  members.pairings.value.filter(pairing => pairing.status === 'pending'))
const drillPending = computed(() => drillPendingList.value[0] || null)
const drillPendingCount = computed(() => drillPendingList.value.length)
const drillDefaultAsAdmin = computed(() =>
  members.adminsKnown.value &&
  !members.pairings.value.some(pairing => pairing.status === 'approved') &&
  members.adminSenders.value.length === 0)
const drillErrorText = computed(() =>
  selectedChannel.value ? cardErrorText(selectedChannel.value) : '')

function sectionEl(section: SectionId): HTMLElement | null {
  return pageRef.value?.querySelector<HTMLElement>(`#chd-section-${section}`) ?? null
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The app's one scrolling container (main.content); null in bare mounts. */
function scrollContainer(): HTMLElement | null {
  return (pageRef.value?.closest('.content') as HTMLElement | null) ?? null
}

function scrollToSection(tab: DetailTab, behaviorOverride?: ScrollBehavior): void {
  const behavior: ScrollBehavior =
    behaviorOverride ?? (prefersReducedMotion() ? 'auto' : 'smooth')
  if (tab === 'overview') {
    const container = scrollContainer()
    if (container) container.scrollTo?.({ top: 0, behavior })
    else window.scrollTo?.({ top: 0, behavior })
    return
  }
  activeSection.value = tab
  spyHoldUntil = Date.now() + 800
  sectionEl(tab)?.scrollIntoView?.({ behavior, block: 'start' })
}

function goToSection(section: SectionId): void {
  detailTab.value = section
  scrollToSection(section)
}

function onSpyScroll(): void {
  if (!pageRef.value) return
  if (Date.now() < spyHoldUntil) return
  let current: SectionId = SECTIONS[0]
  for (const section of SECTIONS) {
    const el = sectionEl(section)
    if (el && el.getBoundingClientRect().top < 140) current = section
  }
  activeSection.value = current
}

function attachScrollSpy(): void {
  detachScrollSpy()
  spyTarget = scrollContainer() ?? window
  spyTarget.addEventListener('scroll', onSpyScroll, { passive: true })
}

function detachScrollSpy(): void {
  spyTarget?.removeEventListener('scroll', onSpyScroll)
  spyTarget = null
}

watch(() => Boolean(selectedChannel.value), drilled => {
  if (drilled) void nextTick(attachScrollSpy)
  else detachScrollSpy()
})

// Deep-linked (or deferred) section scrolls run once the page has actually
// mounted — a cold ?channel=X&tab=pairings load may resolve channels after
// the query was parsed. Sections above the target keep hydrating async and
// shift the layout, so the anchor is re-applied instantly once the page's
// content settles.
watch([selectedChannel, pendingScrollTab], ([ch, tab]) => {
  if (!ch || !tab) return
  const target = tab
  pendingScrollTab.value = null
  void nextTick(() => scrollToSection(target))
  const settled = hydration
  void settled.then(() => nextTick(() => scrollToSection(target, 'auto')))
})

async function removeChannel(ch: Channel): Promise<void> {
  const name = channelKey(ch)
  const ok = await confirm({
    title: t('setup.channels.removeConfirmTitle'),
    body: t('setup.channels.removeConfirmBody', { name }),
    primaryLabel: t('setup.channels.removeConfirmPrimary'),
  })
  if (!ok) return
  await withAction(ch, 'remove', async () => {
    try {
      const res = await rpc.call<{ changed?: boolean; restartRequired?: boolean }>('onboarding.channel.remove', { name })
      if (res?.changed !== false && res?.restartRequired !== false) pendingRestart.record(name, 'remove')
      pushToast(t(res?.restartRequired === false ? 'setup.toast.channelRemovedLive' : 'setup.toast.channelRemoved'), { tone: 'ok' })
      // The entry is gone; any in-flight draft is moot — close without guard.
      forceCloseDetail()
      await refresh()
    } catch (err) {
      pushToast(errorMessage(err), { tone: 'danger' })
    }
  })
}

// ---------------------------------------------------------------------------
// Query reducer: ?channel=<name>&tab=<tab>&edit=1 keeps the drill-in page
// (and the editor mode) URL-addressable; ?compose=1&type=<id> does the same
// for the add-channel takeover, and the two are mutually exclusive. One
// inbound parser (applyDetailQuery) and one outbound writer (syncQuery) own
// the params — push for entering drill-in or compose, replace everywhere
// else — which is what keeps edit=1 from leaking across channels and
// prevents inbound/outbound feedback loops (the parser is idempotent).
// ---------------------------------------------------------------------------
const queryMissing = computed(() =>
  Boolean(selectedName.value) && !loading.value && channels.value.length > 0 && !selectedChannel.value)

const OWNED_QUERY_KEYS = ['channel', 'tab', 'edit', 'compose', 'type'] as const

// Serialized owned-query of the LAST write this reducer issued (or the last
// inbound query it parsed). The state watcher's replace is skipped when it
// would write the same owned query again — which is what lets an explicit
// history PUSH (drill-in, compose, fix-credentials) actually land: vue-router
// treats any later navigation, even an identical replace, as superseding the
// still-pending push and cancels it.
let lastSyncedQuery = ''

function serializeOwned(query: Record<string, string>): string {
  return OWNED_QUERY_KEYS.map(key => `${key}=${query[key] ?? ''}`).join('&')
}

function ownedQueryOf(query: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const key of OWNED_QUERY_KEYS) {
    const value = query[key]
    if (typeof value === 'string') out[key] = value
  }
  return out
}

function detailQuery(): Record<string, string> {
  if (composeMode.value) {
    const query: Record<string, string> = { compose: '1' }
    if (composeType.value) query.type = composeType.value
    return query
  }
  const query: Record<string, string> = {}
  if (selectedName.value) {
    query.channel = selectedName.value
    query.tab = detailTab.value
    if (editMode.value) query.edit = '1'
  }
  return query
}

function syncQuery(mode: 'push' | 'replace'): void {
  if (route.path !== '/channels') return
  const desired = detailQuery()
  const serialized = serializeOwned(desired)
  // No-op-safe writer: a replace that would re-write the current owned query
  // is skipped, so the state watcher can never race (and cancel) a push
  // issued in the same tick or a route leave already in flight.
  if (mode === 'replace' && serialized === lastSyncedQuery) return
  lastSyncedQuery = serialized
  const query: Record<string, string | null | (string | null)[]> = { ...route.query }
  for (const key of OWNED_QUERY_KEYS) delete query[key]
  Object.assign(query, desired)
  void router[mode]({ query })
}

// Legacy tab values keep resolving: capabilities folded into diagnostics.
function normalizeTab(tab: string): DetailTab | '' {
  if (tab === 'capabilities') return 'diagnostics'
  return DETAIL_TABS.includes(tab as DetailTab) ? (tab as DetailTab) : ''
}

/** The compose-enter/repick wipe, shared by the guarded and clean paths:
 *  any drill-in closes and the picked-type form — or the gallery — restores
 *  with an empty draft. */
function applyComposeQuery(type: string): void {
  selectedName.value = ''
  editMode.value = false
  editor.reset()
  members.reset()
  composeMode.value = true
  composeType.value = type
  composeEditor.reset()
  if (type) void composeEditor.startCompose(type)
  else void composeEditor.loadCatalog()
}

/** The channel-selection application, shared by the guarded and clean paths. */
function applyChannelQuery(name: string, tab: DetailTab | '', edit: boolean): void {
  applySelection(name)
  detailTab.value = tab || 'overview'
  pendingScrollTab.value = detailTab.value
  if (edit) {
    // A deep link straight into edit mode always lands on Configuration.
    detailTab.value = 'configuration'
    editMode.value = true
    pendingScrollTab.value = 'configuration'
  }
}

// Every query-driven transition that would destroy a draft takes the SAME
// guards as its button-driven twin: compose enter/repick and channel switch
// confirm a dirty edit/compose draft, compose exit confirms a dirty compose
// draft, and leaving drill-in confirms a dirty edit draft. "Keep editing"
// restores the previous URL with a replace.
function applyDetailQuery(): void {
  if (route.path !== '/channels') return
  lastSyncedQuery = serializeOwned(ownedQueryOf(route.query))
  if (route.query.compose === '1') {
    const type = typeof route.query.type === 'string' ? route.query.type : ''
    if (composeMode.value && composeType.value === type) return
    const dirty = composeMode.value ? composeDirty.value : draftDirty.value
    if (dirty) {
      const confirmDiscard = composeMode.value ? confirmDiscardCompose : confirmDiscardDraft
      void confirmDiscard().then(ok => {
        if (ok) applyComposeQuery(type)
        else syncQuery('replace')
      })
      return
    }
    applyComposeQuery(type)
    return
  }
  if (composeMode.value) {
    // Back (or a bare /channels URL) exits compose — guarded when dirty.
    if (composeDirty.value) {
      void confirmDiscardCompose().then(ok => {
        if (ok) {
          exitCompose()
          applyDetailQuery()
        } else {
          syncQuery('replace')
        }
      })
      return
    }
    exitCompose()
  }
  const name = typeof route.query.channel === 'string' ? route.query.channel : ''
  const tab = normalizeTab(typeof route.query.tab === 'string' ? route.query.tab : '')
  const edit = route.query.edit === '1'
  if (!name) {
    if (!selectedName.value) return
    // Browser Back (or a hand-edited URL) leaving the drill-in page runs the
    // same discard guard the breadcrumb does; "keep editing" restores the URL.
    if (draftDirty.value) {
      void confirmDiscardDraft().then(ok => {
        if (ok) leaveDetail()
        else syncQuery('replace')
      })
      return
    }
    leaveDetail()
    return
  }
  if (name !== selectedName.value) {
    if (selectedName.value && draftDirty.value) {
      void confirmDiscardDraft().then(ok => {
        if (ok) applyChannelQuery(name, tab, edit)
        else syncQuery('replace')
      })
      return
    }
    applyChannelQuery(name, tab, edit)
    return
  }
  if (tab && tab !== detailTab.value) {
    detailTab.value = tab
    pendingScrollTab.value = tab
  }
  if (edit && !editMode.value) {
    // A deep link straight into edit mode always lands on Configuration.
    detailTab.value = 'configuration'
    editMode.value = true
    pendingScrollTab.value = 'configuration'
  }
}

watch([selectedName, detailTab, editMode, composeMode, composeType], () => {
  syncQuery('replace')
})

// Back/forward and hand-edited URLs re-enter through the same parser the
// mount path uses; because it is idempotent, the writer's own replace calls
// cycle through here as no-ops.
watch(() => route.query, () => {
  if (route.path === '/channels') applyDetailQuery()
})

async function withAction(ch: Channel, action: string, run: () => Promise<void>): Promise<void> {
  await withPendingKey(`${channelKey(ch)}:${action}`, run)
}

function actionPending(ch: Channel, action: string): boolean { return pendingActions.value.has(`${channelKey(ch)}:${action}`) }

// Branch on the probe's three-way status, not the connected boolean: a bad
// token must read as a failure, not as "probe unavailable".
async function probeChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'probe', async () => {
    try {
      const result = await rpc.call<ProbeResult>('channels.probe', { name: channelKey(ch) })
      probeResults.value = { ...probeResults.value, [channelKey(ch)]: result }
      if (result.status === 'verified') {
        pushToast(t('console.channels.toastProbePassed', { name: channelKey(ch), ms: result.latencyMs ?? 0 }), { tone: 'ok' })
      } else if (result.status === 'failed') {
        pushToast(t('console.channels.toastProbeFailedResult', { name: channelKey(ch), detail: result.detail || t('console.channels.probeNoDetail') }), { tone: 'danger' })
      } else {
        pushToast(t('console.channels.toastProbeUnsupported', { name: channelKey(ch) }), { tone: 'info' })
      }
    } catch (err) {
      pushToast(t('console.channels.toastProbeFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

function probeToneClass(probe: ProbeResult): string {
  if (probe.status === 'verified') return 'is-ok'
  return probe.status === 'failed' ? 'is-danger' : 'is-muted'
}

function probeTitle(probe: ProbeResult): string {
  if (probe.status === 'verified') return t('console.channels.probeVerified')
  return probe.status === 'failed'
    ? t('console.channels.probeFailed')
    : t('console.channels.probeUnsupported')
}

async function restartChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'restart', async () => {
    try {
      await rpc.call('channels.restart', { name: channelKey(ch) })
      pushToast(t('console.channels.toastRestarted', { name: channelKey(ch) }), { tone: 'ok' })
      await refresh()
    } catch (err) {
      pushToast(t('console.channels.toastRestartFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

async function toggleChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'toggle', async () => {
    const enabling = ch.enabled === false
    try {
      const res = await rpc.call<{ changed?: boolean; restartRequired?: boolean; liveApply?: Record<string, string> | null }>(`onboarding.channel.${enabling ? 'enable' : 'disable'}`, { name: channelKey(ch) })
      if (res?.changed !== false && res?.restartRequired !== false) pendingRestart.record(channelKey(ch), enabling ? 'enable' : 'disable')
      if (enabling && res?.liveApply?.[channelKey(ch)] === 'failed') {
        pushToast(t('setup.toast.channelStartFailed'), { tone: 'danger' })
      } else {
        pushToast(t(enabling ? 'console.channels.toastEnabled' : 'console.channels.toastDisabled', { name: channelKey(ch) }), { tone: 'ok' })
      }
      await refresh()
    } catch (err) {
      pushToast(t('console.channels.toastToggleFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

function errorMessage(err: unknown): string { return err instanceof Error ? err.message : String(err) }

// Pluralized restart count for the header facts line ("1 restart").
function truncateId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 7)}…${id.slice(-4)}` : id
}

async function copyBotId(id: string) {
  try {
    await navigator.clipboard.writeText(id)
    pushToast(t('console.channels.detail.botIdCopied'), { tone: 'ok' })
  } catch {
    /* clipboard unavailable: the title still exposes the full id */
  }
}

function restartsLabel(ch: Channel): string {
  const count = ch.restart_attempts ?? 0
  return t('console.channels.detail.restarts', { count }, count)
}

function platformStatusLabel(status: string): string {
  if (status === 'supported') return t('console.channels.supported')
  return status === 'config_required'
    ? t('console.channels.needsConfig')
    : t('console.channels.notSupported')
}

function ownerSummary(ch: Channel): string {
  if (record(diagnostics(ch).transport_lease).fencing_token) return t('console.channels.ownerHere')
  const leases = delivery(ch).leases
  if (Array.isArray(leases) && leases.some(lease => !record(lease).expired)) return t('console.channels.ownerHere')
  return t('console.channels.ownerNone')
}

function maturityLabel(ch: Channel): string {
  const key = maturityKey(ch)
  return MATURITY_KEYS.has(key) ? t(`console.channels.maturityValue.${key}`) : humanize(key)
}

function evidenceLabel(capability: CapabilityEvidence): string {
  if (capability.methods?.length) return t('console.channels.methodEvidence', { methods: capability.methods.join(', ') })
  return capability.proof_status === 'verified' ? t('console.channels.liveVerified') : t('console.channels.declarationEvidence')
}

function probeResultDetail(ch: Channel): string {
  const result = probeResults.value[channelKey(ch)]
  if (!result) return ''
  if (result.detail) return result.detail
  if (result.latencyMs != null) return t('console.channels.probeLatency', { ms: result.latencyMs })
  return t('console.channels.probeNoDetail')
}
</script>

<style scoped>
/* ===== shared bits ===== */
.ch-muted { color: var(--text-dim); }
.ch-query-missing { align-items: center; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-muted); display: flex; flex-wrap: wrap; font-size: var(--fs-sm); gap: var(--sp-2); justify-content: space-between; margin: 0 0 var(--sp-3); padding: 8px 12px; }
.ch-query-missing > span { min-width: 0; overflow-wrap: anywhere; }
.ch-stale { align-items: center; background: color-mix(in srgb, var(--warn) 8%, var(--bg-surface)); border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--border)); border-radius: var(--radius-md); color: var(--text-muted); display: flex; font-size: var(--fs-sm); gap: var(--sp-2); margin: 0; padding: 7px 12px; }
.ch-stale > svg { color: var(--warn); flex: 0 0 auto; }
.ch-stale > span { flex: 1; }
.ch-empty { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); gap: var(--sp-3); }
.ch-empty__icon { align-items: center; background: color-mix(in srgb, var(--accent) 12%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--border)); border-radius: 50%; color: var(--accent); display: flex; height: 72px; justify-content: center; width: 72px; }
.is-spinning { animation: ch-spin 0.9s linear infinite; }
@keyframes ch-spin { to { transform: rotate(360deg); } }

/* ===== home: dashboard card grid ===== */
.chb__grid { display: grid; gap: var(--sp-3); grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.chb-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  min-width: 0;
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.chb-card:hover, .chb-card:focus-visible { border-color: var(--border-strong, var(--border)); box-shadow: var(--elev-1); transform: translateY(-2px); }
.chb-card:focus-visible { box-shadow: var(--focus-ring); outline: 0; }
.chb-card.is-muted { background: var(--bg); }
.chb-card.is-muted .chb-card__name, .chb-card.is-muted .chb-fact__v { color: var(--text-muted); }
.chb-card.is-static { cursor: default; }
.chb-card.is-static:hover { border-color: var(--border); box-shadow: none; transform: none; }
@media (prefers-reduced-motion: reduce) {
  .chb-card { transition: none; }
  .chb-card:hover, .chb-card:focus-visible { transform: none; }
}
.chb-card__top { align-items: center; display: flex; gap: var(--sp-3); min-width: 0; }
.chb-card__id { display: grid; gap: 2px; min-width: 0; }
.chb-card__name { color: var(--text); font-size: var(--fs-md); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chb-card__sub { color: var(--text-dim); font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chb-card__status { flex: none; font-size: var(--fs-xs); margin-left: auto; }
.chb-card__facts { align-items: center; border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: var(--sp-2) var(--sp-5); padding-top: var(--sp-3); }
.chb-fact { display: grid; gap: 1px; }
.chb-fact__k { color: var(--text-dim); font-size: 11px; }
.chb-fact__v { color: var(--text); font-size: var(--fs-sm); font-variant-numeric: tabular-nums; font-weight: 600; }
.chb-card__pending { border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border)); border-radius: var(--radius-full); color: var(--warn); font-size: 11px; font-weight: 700; margin-left: auto; padding: 2px 9px; white-space: nowrap; }
.chb-card__hint { color: var(--text-dim); font-size: var(--fs-xs); line-height: 1.5; margin: 0; }
.chb-card__foot { align-items: center; display: flex; gap: var(--sp-2); margin-top: auto; }
.chb-card__foot .btn { min-height: 28px; padding: 3px 11px; font-size: var(--fs-xs); }
.chb-card__go { color: var(--text-dim); font-size: var(--fs-xs); margin-left: auto; white-space: nowrap; }
.chb-card:hover .chb-card__go { color: var(--text); }
.chb-card--add {
  align-items: center;
  background: transparent;
  border-style: dashed;
  color: var(--text-muted);
  display: flex;
  flex-direction: row;
  font: inherit;
  font-size: var(--fs-sm);
  gap: var(--sp-2);
  justify-content: center;
  min-height: 150px;
}
.chb-card--add:hover, .chb-card--add:focus-visible { color: var(--text); }

/* ===== drill-in: full-page detail ===== */
.chd { display: flex; flex-direction: column; gap: var(--sp-3); }
.chd__crumb { align-items: center; color: var(--text-muted); display: flex; font-size: var(--fs-sm); gap: var(--sp-2); }
.chd__back { align-items: center; background: transparent; border: 0; color: var(--text-muted); cursor: pointer; display: inline-flex; font: inherit; font-size: var(--fs-sm); gap: 5px; padding: 4px 6px 4px 0; }
.chd__back:hover { color: var(--text); }
.chd__crumb-sep { color: var(--text-dim); }
.chd__crumb-name { color: var(--text); font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chd__head { align-items: center; border-bottom: 1px solid var(--border-strong, var(--border)); display: flex; flex-wrap: wrap; gap: var(--sp-3) var(--sp-4); padding-bottom: var(--sp-4); }
.chd__head :deep(.brand-mark) { font-size: 18px; height: 44px; width: 44px; }
.chd__title { display: grid; gap: 4px; min-width: 0; }
.chd__title h2 { font-size: var(--fs-xl); line-height: 1.2; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chd__factsline { align-items: center; color: var(--text-muted); display: flex; flex-wrap: wrap; font-size: var(--fs-sm); gap: 4px var(--sp-2); margin: 0; }
.chd__fact { min-width: 0; overflow-wrap: anywhere; }
.chd__fact::before { color: var(--text-dim); content: '·'; margin-right: var(--sp-2); }
.chd__fact--mono { font-family: var(--font-mono); font-size: var(--fs-xs); }
.chd__botid { background: transparent; border: 0; color: inherit; cursor: copy; padding: 0; }
.chd__botid:hover { color: var(--text); }
.chd__actions { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-left: auto; }
.chd__actions .btn { min-height: 32px; padding: 5px 10px; }
.chd__remove { color: var(--danger); }
.chd__cols { align-items: start; display: grid; gap: var(--sp-5); grid-template-columns: 172px minmax(0, 1fr); max-width: 1460px; }
.chd__nav { display: flex; flex-direction: column; gap: 2px; position: sticky; top: 56px; }
.chd__nav button { align-items: center; background: transparent; border: 0; border-left: 2px solid transparent; color: var(--text-muted); cursor: pointer; display: flex; font: inherit; font-size: var(--fs-sm); gap: 7px; line-height: 1.4; padding: 7px 10px; text-align: left; }
.chd__nav button:hover { color: var(--text); }
.chd__nav button:focus-visible { border-radius: var(--radius-sm); box-shadow: var(--focus-ring); outline: 0; }
.chd__nav button.is-active { border-left-color: var(--text); color: var(--text); font-weight: 550; }
.chd__nav-count { color: var(--text-dim); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; margin-left: auto; }
.chd__main { display: grid; gap: 24px; max-width: 1280px; min-width: 0; }
.chd__section { display: grid; gap: var(--sp-3); scroll-margin-top: 64px; }
.chd__no-evidence { font-size: var(--fs-sm); padding: 0 0 12px; }
/* One-document skeleton: drill sections read as titled groups, not widgets. */
.chd__main :deep(.ch-panel) { background: transparent; border: 0; border-radius: 0; overflow: visible; }
.chd__main :deep(.ch-panel > h3), .chd__main :deep(.ch-panel__heading) { border-bottom: 1px solid var(--border); padding: 0 0 8px; }
.chd__main :deep(.ch-panel__heading p) { margin: 2px 0 0; }
.chd__main :deep(.ch-panel__intro) { padding: 10px 0 0; }
.chd__main :deep(.ch-pairing-summary) { border-bottom: 0; padding: 8px 0 0; }
.chd__main :deep(.ch-pairing-summary .is-zero), .chd__main :deep(.ch-pairing-summary .is-zero strong) { color: var(--text-dim); font-weight: 400; }
.chd__main :deep(.ch-pairing-search) { margin: 8px 0 0; }
.chd__main :deep(.ch-pairing-state) { flex-direction: row; gap: 10px; justify-content: flex-start; min-height: 0; padding: 16px 0; text-align: left; }
.chd__main :deep(.ch-pairing-state strong) { font-weight: 550; }
.chd__main :deep(.ch-pairing-groups h4) { padding: 12px 0 6px; }
.chd__main :deep(.ch-pairing-row) { padding-left: 0; padding-right: 0; }
.chd__main :deep(.ch-metrics) { gap: 0 var(--sp-5); grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); max-width: 760px; }
.chd__main :deep(.ch-metrics > div) { border-right: 0; padding: 12px 0; }
.chd__main :deep(.ch-facts dl > div) { padding: 10px 0; }
.chd__main :deep(.cfge) { padding-left: 0; padding-right: 0; }

/* Unsaved-draft dot on the Configuration sidenav item: typographic, not
   chromatic. */
.ch-tab-dirty { color: var(--text); display: inline-block; font-size: 8px; line-height: 1; }
.ch-tab-badge { background: color-mix(in srgb, var(--warn) 20%, transparent); border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border)); border-radius: var(--radius-full); color: var(--warn); font-size: 10px; font-weight: 700; padding: 0 6px; }

/* ===== panels shared by the drill-in sections ===== */
.ch-panel, .ch-alert { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.ch-panel > h3, .ch-panel__heading { align-items: center; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; margin: 0; padding: 12px 14px; }
.ch-panel h3 { font-size: var(--fs-sm); margin: 0; }
.ch-panel__intro { color: var(--text-dim); font-size: var(--fs-sm); line-height: 1.5; margin: 0; padding: 12px 14px 0; }
.ch-probe-result, .ch-alert { align-items: flex-start; display: flex; gap: 10px; padding: 12px 14px; }
.ch-probe-result { background: color-mix(in srgb, var(--ok) 8%, var(--bg)); border: 1px solid color-mix(in srgb, var(--ok) 36%, var(--border)); border-radius: var(--radius-md); color: var(--ok); }
.ch-probe-result.is-danger { background: color-mix(in srgb, var(--danger) 8%, var(--bg)); border-color: color-mix(in srgb, var(--danger) 36%, var(--border)); color: var(--danger); }
.ch-probe-result.is-muted { background: var(--bg); border-color: var(--border); color: var(--text-muted); }
.ch-probe-result__edit { margin-top: 8px; min-height: 28px; padding: 3px 9px; }
.ch-probe-result p, .ch-alert p { color: var(--text-muted); font-size: var(--fs-sm); margin: 3px 0 0; }
.ch-probe-result > div, .ch-alert > div { min-width: 0; overflow-wrap: anywhere; }
.ch-alert.is-danger { background: color-mix(in srgb, var(--danger) 8%, var(--bg)); border-color: color-mix(in srgb, var(--danger) 38%, var(--border)); color: var(--danger); }
.ch-facts dl { margin: 0; }
.ch-facts dl > div { align-items: baseline; border-top: 1px solid var(--border); display: flex; gap: var(--sp-3); justify-content: space-between; padding: 11px 14px; }
.ch-facts dl > div:first-child { border-top: 0; }
.ch-facts dt { color: var(--text-dim); font-size: var(--fs-sm); }
.ch-facts dd { font-family: var(--font-mono); font-size: 11px; margin: 0; max-width: 64%; overflow-wrap: anywhere; text-align: right; }
.ch-metrics { display: grid; grid-template-columns: repeat(2, 1fr); }
.ch-metrics > div { border-right: 1px solid var(--border); border-top: 1px solid var(--border); display: grid; gap: 4px; padding: 14px; }
.ch-metrics > div:nth-child(even) { border-right: 0; }
.ch-metrics strong { font-family: var(--font-mono); font-size: var(--fs-lg); }
.ch-metrics span { color: var(--text-dim); font-size: 11px; }
.ch-metrics > div.is-warn strong { color: var(--warn); }
.ch-tech { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 var(--sp-2) var(--sp-2); }
.ch-tech > summary { align-items: center; color: var(--text-muted); cursor: pointer; display: flex; font-size: var(--fs-sm); gap: var(--sp-2); padding: 10px 6px; }
.ch-capabilities { padding: 8px 0; }
.ch-capability { align-items: center; display: grid; gap: 10px; grid-template-columns: 18px minmax(0, 1fr) auto; padding: 9px 14px; }
.ch-capability > svg { color: var(--ok); }
.ch-capability > svg.is-ok { color: var(--ok); }
.ch-capability > svg.is-warn { color: var(--warn); }
.ch-capability > svg.is-muted { color: var(--text-dim); }
.ch-capability div { display: grid; gap: 2px; }
.ch-capability strong { font-size: var(--fs-sm); }
.ch-capability span:not(.ch-proof) { color: var(--text-dim); font-size: 11px; }
.ch-maturity, .ch-proof { border: 1px solid var(--border); border-radius: var(--radius-full); color: var(--text-muted); display: inline-flex; font-size: 10px; font-weight: 700; letter-spacing: .03em; padding: 3px 8px; text-transform: uppercase; white-space: nowrap; }
.ch-maturity.is-stable, .ch-proof.is-effective { border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); color: var(--ok); }
.ch-proof.is-config { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); color: var(--warn); }
.ch-proof.is-declared { color: var(--text-dim); }
.is-warn { color: var(--warn); }

/* ===== floating dirty bar: bottom-center pill over the scrolling page =====
   Sticky (not fixed): it centers on the CONTENT column — fixed positioning
   would center on the viewport and drift off-axis by half the app sidebar. */
.chd-dirtybar { bottom: var(--sp-4); margin: 0 auto; position: sticky; width: min(720px, 100%); z-index: 45; }
.chd-dirtybar :deep(.ceb) { border: 1px solid var(--border-strong, var(--border)); border-radius: var(--radius-lg); box-shadow: var(--elev-3); position: static; }
.ceb-slide-enter-active, .ceb-slide-leave-active { transition: transform var(--dur-base) var(--ease-out), opacity var(--dur-base) var(--ease-out); }
.ceb-slide-enter-from, .ceb-slide-leave-to { opacity: 0; transform: translateY(16px); }
@media (prefers-reduced-motion: reduce) {
  .ceb-slide-enter-active, .ceb-slide-leave-active { transition: none; }
}

@media (max-width: 900px) {
  .chd__cols { grid-template-columns: minmax(0, 1fr); }
  /* The section nav stays pinned under the floating topbar while the page
     scrolls, so jumping between sections never requires scrolling back up. */
  .chd__nav { background: var(--bg-surface); flex-direction: row; overflow-x: auto; padding: var(--sp-1) 0; position: sticky; top: 48px; z-index: 5; }
  .chd__nav button { white-space: nowrap; }
  .chd__actions { margin-left: 0; }
}

/* 768px matches the app's mobile breakpoint (the bottom tab bar appears
   there). */
@media (max-width: 768px) {
  .ch-stage__header { align-items: stretch; flex-direction: column; }
  .ch-stage__actions { justify-content: stretch; }
  .ch-stage__actions .btn { flex: 1; }
  .chb__grid { grid-template-columns: minmax(0, 1fr); }
  /* Touch-target floor for the compact controls this view introduces. */
  .chb-card__foot .btn { min-height: 40px; }
  .chd__nav button { min-height: 44px; }
}
</style>
