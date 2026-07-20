<template>
  <div ref="knowledgeStage" class="rag-provider control-stage control-stage--spacious">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <h1 class="control-stage__title">{{ t('rag.title') }}</h1>
        <p class="control-stage__subtitle">{{ t('rag.subtitle') }}</p>
      </div>
      <button
        data-testid="rag-refresh"
        class="btn btn--ghost"
        type="button"
        :disabled="loadingStatus || loadingLibraryStats"
        @click="refreshStatus"
      >
        {{ loadingStatus || loadingLibraryStats ? t('rag.refreshing') : t('rag.refresh') }}
      </button>
    </header>

    <section class="rag-provider__status-line control-panel" aria-live="polite">
      <span
        data-testid="rag-state"
        class="control-pill"
        :class="statusToneClass"
      >
        {{ statusLabel }}
      </span>
      <strong data-testid="rag-provider-name">{{ status?.provider?.name || '—' }}</strong>
      <span v-if="status?.protocolVersion">{{ status.protocolVersion }}</span>
      <a
        v-if="managementUrl"
        class="btn btn--ghost"
        :href="managementUrl"
        target="_blank"
        rel="noopener noreferrer"
      >
        {{ t('rag.management') }}
      </a>
      <span v-else-if="hasLocalManagementHint" class="rag-provider__hint">
        {{ t('rag.managementLocalOnly') }}
      </span>
    </section>

    <p v-if="statusError" class="rag-provider__error" role="alert">
      {{ statusError }}
    </p>
    <p v-if="status?.warning" class="rag-provider__warning" role="status">
      {{ status.warning }}
    </p>

    <section class="rag-library-stats control-panel" :aria-label="t('rag.library.title')">
      <header>
        <div>
          <h2 class="control-panel__title">{{ t('rag.library.title') }}</h2>
          <p>{{ t('rag.library.description') }}</p>
        </div>
        <span v-if="loadingLibraryStats" class="control-pill">
          {{ t('rag.library.loading') }}
        </span>
      </header>
      <dl>
        <div>
          <dt>{{ t('rag.library.files') }}</dt>
          <dd data-testid="rag-library-files">{{ libraryCount(libraryStats?.filesIndexed) }}</dd>
        </div>
        <div>
          <dt>{{ t('rag.library.chunks') }}</dt>
          <dd data-testid="rag-library-chunks">{{ libraryCount(libraryStats?.chunksIndexed) }}</dd>
        </div>
      </dl>
      <p v-if="libraryStatsError" class="rag-provider__warning" role="status">
        {{ t('rag.library.unavailable') }}
      </p>
    </section>

    <KnowledgeUploadPanel
      @indexed="refreshLibraryStats"
      @verify-search="focusSearchWorkbench"
    />

    <KnowledgeProfileSelector
      :profiles="status?.searchOptions?.retrievalProfiles ?? []"
      :provider-default="status?.searchOptions?.defaultRetrievalProfile ?? null"
      :saved-override="savedOverride"
      :draft="profileDraft"
      :saving="savingProfile"
      :disabled="profileDisabled"
      :error="profileError"
      @change="profileDraft = $event"
      @save="saveProfile"
    />

    <KnowledgeSearchWorkspace
      v-model:query="query"
      v-model:limit="limit"
      :can-search="canSearch"
      :searching="searching"
      :search-error="searchError"
      :search-response="searchResponse"
      :selected-evidence-id="selectedEvidenceId"
      :get-response="getResponse"
      :reading="reading"
      :read-error="readError"
      :mobile-reader-open="mobileReaderOpen"
      :expected-retrieval-profile="expectedRetrievalProfile"
      @search="search"
      @select="selectEvidence"
      @page="readEvidence"
      @close-reader="closeMobileReader"
    />

    <KnowledgeProviderDetails :status="status" />
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  onActivated,
  onDeactivated,
  nextTick,
  onUnmounted,
  ref,
} from 'vue'
import { useI18n } from 'vue-i18n'
import KnowledgeProfileSelector from '@/components/knowledge/KnowledgeProfileSelector.vue'
import KnowledgeUploadPanel from '@/components/knowledge/KnowledgeUploadPanel.vue'
import KnowledgeProviderDetails from '@/components/knowledge/KnowledgeProviderDetails.vue'
import KnowledgeSearchWorkspace from '@/components/knowledge/KnowledgeSearchWorkspace.vue'
import {
  getKnowledgeLibraryStats,
  type KnowledgeLibraryStats,
} from '@/components/knowledge/knowledgeStats'
import { useRpcStore } from '@/stores/rpc'
import {
  browserManagementLink,
  effectiveRetrievalProfile,
  normalizeRagGetResponse,
  normalizeRagProfileSetResponse,
  normalizeRagProviderStatus,
  normalizeRagSearchResponse,
  type RagGetResponse,
  type RagProviderStatus,
  type RagSearchResponse,
} from './ragProvider'

interface LoadStatusOptions {
  preserveDraft?: boolean
}
const knowledgeStage = ref<HTMLElement | null>(null)

const MOBILE_READER_QUERY = '(max-width: 900px)'
const rpc = useRpcStore()
const { t } = useI18n()

const status = ref<RagProviderStatus | null>(null)
const libraryStats = ref<KnowledgeLibraryStats | null>(null)
const savedOverride = ref<string | null>(null)
const profileDraft = ref<string | null>(null)
const query = ref('')
const limit = ref(8)
const searchResponse = ref<RagSearchResponse | null>(null)
const selectedEvidenceId = ref<string | null>(null)
const getResponse = ref<RagGetResponse | null>(null)

const loadingStatus = ref(false)
const loadingLibraryStats = ref(false)
const savingProfile = ref(false)
const searching = ref(false)
const reading = ref(false)

const statusError = ref('')
const libraryStatsError = ref('')
const profileError = ref('')
const searchError = ref('')
const readError = ref('')
const mobileReaderOpen = ref(false)

let statusRequestId = 0
let libraryStatsRequestId = 0
let activationRequestId = 0
let readerRequestId = 0
let readerInflightKey: string | null = null
let pageActive = false

const profileDirty = computed(() => profileDraft.value !== savedOverride.value)
const expectedRetrievalProfile = computed(() => effectiveRetrievalProfile(status.value))
const profileDisabled = computed(() => status.value?.searchOptions === null || !status.value)
const canSearch = computed(
  () => status.value?.connectionState === 'READY' || status.value?.connectionState === 'LEGACY',
)
const canRead = computed(() => status.value?.capabilities?.get === true)
const managementUrl = computed(
  () => browserManagementLink(status.value?.links.management),
)
const hasLocalManagementHint = computed(
  () => Boolean(status.value?.links.management) && !managementUrl.value,
)
const statusLabel = computed(() => {
  if (!status.value) {
    return t(loadingStatus.value ? 'rag.status.connecting' : 'rag.status.disabled')
  }
  return t(`rag.status.${status.value.connectionState.toLowerCase()}`)
})
const statusToneClass = computed(() => ({
  'control-pill--ok': status.value?.connectionState === 'READY',
  'control-pill--warn': ['DEGRADED', 'INCOMPATIBLE', 'UNAVAILABLE'].includes(
    status.value?.connectionState ?? '',
  ),
}))

function message(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

function libraryCount(value: number | undefined): string {
  return value === undefined ? '—' : new Intl.NumberFormat().format(value)
}

function isMobileViewport(): boolean {
  return window.matchMedia(MOBILE_READER_QUERY).matches
}

function readerMarker(state: unknown): string | null {
  if (!state || typeof state !== 'object' || Array.isArray(state)) return null
  const value = (state as Record<string, unknown>).ragReader
  return typeof value === 'string' && value.trim() ? value : null
}

function currentHistoryState(): Record<string, unknown> {
  const value = window.history.state
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function openMobileReader(evidenceId: string) {
  if (!isMobileViewport()) return
  const nextState = { ...currentHistoryState(), ragReader: evidenceId }
  if (mobileReaderOpen.value) window.history.replaceState(nextState, '')
  else window.history.pushState(nextState, '')
  mobileReaderOpen.value = true
}

function consumeMobileReaderMarker() {
  const hasMarker = readerMarker(window.history.state) !== null
  mobileReaderOpen.value = false
  if (hasMarker) window.history.back()
}

function syncMobileReaderUi(state: unknown) {
  const evidenceId = isMobileViewport() ? readerMarker(state) : null
  if (!evidenceId || !canRead.value) {
    mobileReaderOpen.value = false
    return null
  }
  mobileReaderOpen.value = true
  selectedEvidenceId.value = evidenceId
  if (getResponse.value?.evidenceId !== evidenceId) {
    getResponse.value = null
    readError.value = ''
  }
  return evidenceId
}

function ensureMobileReader(state: unknown) {
  const evidenceId = syncMobileReaderUi(state)
  if (!evidenceId) return
  if (getResponse.value?.evidenceId !== evidenceId) void readEvidence(evidenceId, null)
}

async function focusSearchWorkbench() {
  await nextTick()
  const input = knowledgeStage.value?.querySelector<HTMLTextAreaElement>('[data-testid="rag-query"]')
  if (!input) return
  input.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  input.focus()
}

async function loadStatus({ preserveDraft = true }: LoadStatusOptions = {}) {
  const requestId = ++statusRequestId
  const activationId = activationRequestId
  loadingStatus.value = true
  statusError.value = ''
  try {
    await rpc.waitForConnection()
    if (
      !pageActive
      || activationId !== activationRequestId
      || requestId !== statusRequestId
    ) return false
    const normalized = normalizeRagProviderStatus(await rpc.call('knowledge.status', {}))
    if (!normalized) throw new Error(t('rag.errors.invalidStatusResponse'))
    if (
      !pageActive
      || activationId !== activationRequestId
      || requestId !== statusRequestId
    ) return false

    const keepDirtyDraft = preserveDraft && profileDirty.value
    status.value = normalized
    savedOverride.value = normalized.retrievalProfileOverride
    if (!keepDirtyDraft) profileDraft.value = normalized.retrievalProfileOverride
    return true
  } catch (value) {
    if (requestId !== statusRequestId) return false
    statusError.value = message(value)
    return false
  } finally {
    if (requestId === statusRequestId) loadingStatus.value = false
  }
}

function refreshStatus() {
  void loadStatus({ preserveDraft: true })
  void loadLibraryStats()
}

async function loadLibraryStats() {
  const requestId = ++libraryStatsRequestId
  loadingLibraryStats.value = true
  libraryStatsError.value = ''
  try {
    const next = await getKnowledgeLibraryStats()
    if (!pageActive || requestId !== libraryStatsRequestId) return false
    libraryStats.value = next
    return true
  } catch (value) {
    if (requestId !== libraryStatsRequestId) return false
    libraryStatsError.value = message(value)
    return false
  } finally {
    if (requestId === libraryStatsRequestId) loadingLibraryStats.value = false
  }
}

function refreshLibraryStats() {
  if (pageActive) void loadLibraryStats()
}

async function saveProfile() {
  if (savingProfile.value || !profileDirty.value) return
  savingProfile.value = true
  profileError.value = ''
  try {
    const normalized = normalizeRagProfileSetResponse(
      await rpc.call('knowledge.profile.set', {
        retrievalProfileOverride: profileDraft.value,
      }),
    )
    if (!normalized) throw new Error(t('rag.errors.invalidProfileResponse'))
    savedOverride.value = normalized.retrievalProfileOverride
    profileDraft.value = normalized.retrievalProfileOverride
    if (pageActive) await loadStatus({ preserveDraft: false })
  } catch (value) {
    profileError.value = message(value)
  } finally {
    savingProfile.value = false
  }
}

async function search() {
  const clean = query.value.trim()
  if (!clean || !canSearch.value || searching.value) return
  searching.value = true
  searchError.value = ''
  try {
    const boundedLimit = Math.min(20, Math.max(1, Number(limit.value) || 8))
    const normalized = normalizeRagSearchResponse(
      await rpc.call('knowledge.search', { query: clean, limit: boundedLimit }),
    )
    if (!normalized) throw new Error(t('rag.errors.invalidSearchResponse'))
    readerRequestId += 1
    readerInflightKey = null
    reading.value = false
    readError.value = ''
    searchResponse.value = normalized
    selectedEvidenceId.value = null
    getResponse.value = null
    consumeMobileReaderMarker()
  } catch (value) {
    searchError.value = message(value)
  } finally {
    searching.value = false
  }
}

async function selectEvidence(evidenceId: string) {
  if (!canRead.value) return
  selectedEvidenceId.value = evidenceId
  openMobileReader(evidenceId)
  await readEvidence(evidenceId, null)
}

async function readEvidence(evidenceId: string, cursor: string | null) {
  if (!canRead.value) return
  const requestKey = JSON.stringify([evidenceId, cursor])
  if (readerInflightKey === requestKey) return
  const requestId = ++readerRequestId
  readerInflightKey = requestKey
  if (getResponse.value?.evidenceId !== evidenceId) getResponse.value = null
  reading.value = true
  readError.value = ''
  try {
    const params: { evidenceId: string; cursor?: string } = { evidenceId }
    if (cursor) params.cursor = cursor
    const normalized = normalizeRagGetResponse(await rpc.call('knowledge.get', params))
    if (!normalized) throw new Error(t('rag.errors.invalidGetResponse'))
    if (requestId !== readerRequestId) return
    getResponse.value = normalized
  } catch (value) {
    if (requestId !== readerRequestId) return
    readError.value = message(value)
  } finally {
    if (requestId === readerRequestId) {
      reading.value = false
      if (readerInflightKey === requestKey) readerInflightKey = null
    }
  }
}

function closeMobileReader() {
  if (!mobileReaderOpen.value) return
  mobileReaderOpen.value = false
  if (readerMarker(window.history.state)) window.history.back()
}

function onPopState(event: PopStateEvent) {
  ensureMobileReader(event.state)
}

function teardownPage() {
  window.removeEventListener('popstate', onPopState)
}

onActivated(() => {
  pageActive = true
  activationRequestId += 1
  const activationId = activationRequestId
  teardownPage()
  window.addEventListener('popstate', onPopState)
  syncMobileReaderUi(window.history.state)
  void loadLibraryStats()
  void loadStatus({ preserveDraft: true }).then((loaded) => {
    if (!loaded || !pageActive || activationId !== activationRequestId) return
    ensureMobileReader(window.history.state)
  })
})

onDeactivated(() => {
  pageActive = false
  activationRequestId += 1
  teardownPage()
  statusRequestId += 1
  libraryStatsRequestId += 1
  readerRequestId += 1
  readerInflightKey = null
  loadingStatus.value = false
  loadingLibraryStats.value = false
  reading.value = false
  mobileReaderOpen.value = false
})

onUnmounted(() => {
  pageActive = false
  activationRequestId += 1
  teardownPage()
  statusRequestId += 1
  libraryStatsRequestId += 1
  readerRequestId += 1
  readerInflightKey = null
})
</script>

<style scoped>
.rag-provider {
  display: grid;
  gap: var(--sp-4);
}

.rag-provider__status-line {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.rag-provider__status-line .btn {
  margin-left: auto;
}

.rag-library-stats {
  display: grid;
  gap: var(--sp-3);
}

.rag-library-stats header {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.rag-library-stats header > div {
  display: grid;
  gap: var(--sp-1);
}

.rag-library-stats header p,
.rag-library-stats > p {
  margin: 0;
}

.rag-library-stats dl {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0;
}

.rag-library-stats dl div {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  display: grid;
  gap: var(--sp-1);
  padding: var(--sp-4);
}

.rag-library-stats dt {
  color: var(--text-muted);
}

.rag-library-stats dd {
  font-size: clamp(1.5rem, 3vw, 2.25rem);
  font-weight: 700;
  margin: 0;
}

.rag-provider__hint {
  color: var(--text-muted);
}

.rag-provider__error,
.rag-provider__warning {
  color: var(--warn);
  margin: 0;
}

:deep(.rag-profile-selector__footer) {
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .rag-provider__status-line .btn {
    margin-left: 0;
  }

  .rag-library-stats dl {
    grid-template-columns: 1fr;
  }
}
</style>
