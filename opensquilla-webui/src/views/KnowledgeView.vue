<template>
  <div class="rag-provider control-stage control-stage--spacious">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <h1 class="control-stage__title">{{ t('rag.title') }}</h1>
        <p class="control-stage__subtitle">{{ t('rag.subtitle') }}</p>
      </div>
      <button
        data-testid="rag-refresh"
        class="btn btn--ghost"
        type="button"
        :disabled="loadingStatus"
        @click="refreshStatus"
      >
        {{ loadingStatus ? t('rag.refreshing') : t('rag.refresh') }}
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
  onUnmounted,
  ref,
} from 'vue'
import { useI18n } from 'vue-i18n'
import KnowledgeProfileSelector from '@/components/knowledge/KnowledgeProfileSelector.vue'
import KnowledgeProviderDetails from '@/components/knowledge/KnowledgeProviderDetails.vue'
import KnowledgeSearchWorkspace from '@/components/knowledge/KnowledgeSearchWorkspace.vue'
import { useRpcStore } from '@/stores/rpc'
import {
  browserManagementLink,
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

const MOBILE_READER_QUERY = '(max-width: 900px)'
const rpc = useRpcStore()
const { t } = useI18n()

const status = ref<RagProviderStatus | null>(null)
const savedOverride = ref<string | null>(null)
const profileDraft = ref<string | null>(null)
const query = ref('')
const limit = ref(8)
const searchResponse = ref<RagSearchResponse | null>(null)
const selectedEvidenceId = ref<string | null>(null)
const getResponse = ref<RagGetResponse | null>(null)

const loadingStatus = ref(false)
const savingProfile = ref(false)
const searching = ref(false)
const reading = ref(false)

const statusError = ref('')
const profileError = ref('')
const searchError = ref('')
const readError = ref('')
const mobileReaderOpen = ref(false)

let statusRequestId = 0

const profileDirty = computed(() => profileDraft.value !== savedOverride.value)
const profileDisabled = computed(() => status.value?.searchOptions === null || !status.value)
const canSearch = computed(
  () => status.value?.connectionState === 'READY' || status.value?.connectionState === 'LEGACY',
)
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

function syncMobileReader(state: unknown) {
  mobileReaderOpen.value = isMobileViewport() && readerMarker(state) !== null
}

async function loadStatus({ preserveDraft = true }: LoadStatusOptions = {}) {
  const requestId = ++statusRequestId
  loadingStatus.value = true
  statusError.value = ''
  try {
    await rpc.waitForConnection()
    const normalized = normalizeRagProviderStatus(await rpc.call('knowledge.status', {}))
    if (!normalized) throw new Error(t('rag.errors.invalidStatusResponse'))
    if (requestId !== statusRequestId) return

    const keepDirtyDraft = preserveDraft && profileDirty.value
    status.value = normalized
    savedOverride.value = normalized.retrievalProfileOverride
    if (!keepDirtyDraft) profileDraft.value = normalized.retrievalProfileOverride
  } catch (value) {
    if (requestId !== statusRequestId) return
    statusError.value = message(value)
  } finally {
    if (requestId === statusRequestId) loadingStatus.value = false
  }
}

function refreshStatus() {
  void loadStatus({ preserveDraft: true })
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
    await loadStatus({ preserveDraft: false })
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
  selectedEvidenceId.value = evidenceId
  openMobileReader(evidenceId)
  await readEvidence(evidenceId, null)
}

async function readEvidence(evidenceId: string, cursor: string | null) {
  reading.value = true
  readError.value = ''
  try {
    const params: { evidenceId: string; cursor?: string } = { evidenceId }
    if (cursor) params.cursor = cursor
    const normalized = normalizeRagGetResponse(await rpc.call('knowledge.get', params))
    if (!normalized) throw new Error(t('rag.errors.invalidGetResponse'))
    getResponse.value = normalized
  } catch (value) {
    readError.value = message(value)
  } finally {
    reading.value = false
  }
}

function closeMobileReader() {
  if (!mobileReaderOpen.value) return
  mobileReaderOpen.value = false
  if (readerMarker(window.history.state)) window.history.back()
}

function onPopState(event: PopStateEvent) {
  const evidenceId = isMobileViewport() ? readerMarker(event.state) : null
  mobileReaderOpen.value = evidenceId !== null
  if (!evidenceId) return
  selectedEvidenceId.value = evidenceId
  if (getResponse.value?.evidenceId !== evidenceId) void readEvidence(evidenceId, null)
}

function teardownPage() {
  window.removeEventListener('popstate', onPopState)
}

onActivated(() => {
  teardownPage()
  window.addEventListener('popstate', onPopState)
  syncMobileReader(window.history.state)
  void loadStatus({ preserveDraft: true })
})

onDeactivated(() => {
  teardownPage()
  statusRequestId += 1
  loadingStatus.value = false
  mobileReaderOpen.value = false
})

onUnmounted(() => {
  teardownPage()
  statusRequestId += 1
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
}
</style>
