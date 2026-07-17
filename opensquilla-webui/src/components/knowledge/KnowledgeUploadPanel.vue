<template>
  <section class="knowledge-upload control-panel" aria-labelledby="knowledge-upload-title">
    <header class="knowledge-upload__header">
      <div>
        <h2 id="knowledge-upload-title" class="control-panel__title">
          {{ t('rag.upload.title') }}
        </h2>
        <p>{{ t('rag.upload.description') }}</p>
      </div>
      <span class="control-pill">{{ t('rag.upload.collection', { id: 'customer_shared' }) }}</span>
    </header>

    <fieldset class="knowledge-upload__indexes" :disabled="indexesLocked">
      <legend>{{ t('rag.upload.indexes.title') }}</legend>
      <label>
        <input v-model="indexTypes" type="checkbox" value="fts">
        <span>
          <strong>{{ t('rag.upload.indexes.fts') }}</strong>
          <small>{{ t('rag.upload.indexes.ftsHint') }}</small>
        </span>
      </label>
      <label>
        <input v-model="indexTypes" type="checkbox" value="vector">
        <span>
          <strong>{{ t('rag.upload.indexes.vector') }}</strong>
          <small>{{ t('rag.upload.indexes.vectorHint') }}</small>
        </span>
      </label>
    </fieldset>
    <p v-if="indexTypes.length === 0" class="knowledge-upload__error" role="alert">
      {{ t('rag.upload.indexes.required') }}
    </p>

    <div class="knowledge-upload__file-row">
      <label class="knowledge-upload__file-label" for="knowledge-upload-file">
        {{ t('rag.upload.fileLabel') }}
      </label>
      <input
        id="knowledge-upload-file"
        data-testid="knowledge-upload-file"
        class="control-input"
        type="file"
        accept=".zip,application/zip,application/x-zip-compressed"
        :disabled="fileInputLocked"
        @change="selectFile"
      >
      <p class="knowledge-upload__hint">{{ t('rag.upload.fileHint') }}</p>
    </div>

    <p v-if="selectedFile" data-testid="knowledge-upload-selected">
      <strong>{{ selectedFile.name }}</strong>
      · {{ formatBytes(selectedFile.size) }}
    </p>
    <p
      v-if="needsFileReselection"
      data-testid="knowledge-upload-reselect"
      class="knowledge-upload__notice"
      role="status"
    >
      {{ t('rag.upload.reselect', { filename: stored?.filename }) }}
    </p>
    <p v-if="selectionError" class="knowledge-upload__error" role="alert">
      {{ selectionError }}
    </p>

    <div class="knowledge-upload__actions">
      <button
        data-testid="knowledge-upload-start"
        class="btn btn--primary"
        type="button"
        :disabled="actionDisabled"
        @click="runAction"
      >
        {{ actionLabel }}
      </button>
      <button
        v-if="stored?.jobId && !job"
        class="btn btn--ghost"
        type="button"
        :disabled="busy"
        @click="refreshReferencedJob"
      >
        {{ t('rag.upload.retryStatus') }}
      </button>
      <span v-if="activeJob" class="knowledge-upload__hint">
        {{ t('rag.upload.singleTask') }}
      </span>
    </div>

    <div
      v-if="upload"
      class="knowledge-upload__progress"
      aria-live="polite"
    >
      <div class="knowledge-upload__progress-heading">
        <strong>{{ t('rag.upload.uploadProgress') }}</strong>
        <span data-testid="knowledge-upload-bytes">
          {{ formatBytes(upload.uploadedBytes) }} / {{ formatBytes(upload.sizeBytes) }}
          · {{ uploadPercent }}%
        </span>
      </div>
      <progress
        data-testid="knowledge-upload-progress"
        :value="upload.uploadedBytes"
        :max="Math.max(1, upload.sizeBytes)"
        :aria-label="t('rag.upload.uploadProgress')"
      />
    </div>

    <section v-if="job" class="knowledge-upload__job" aria-labelledby="knowledge-job-title">
      <header class="knowledge-upload__job-header">
        <h3 id="knowledge-job-title">{{ t('rag.upload.job.title') }}</h3>
        <span
          data-testid="knowledge-job-state"
          class="control-pill"
          :class="jobStateTone"
        >
          {{ t(`rag.upload.job.states.${job.state}`) }}
        </span>
      </header>

      <div class="knowledge-upload__progress">
        <div class="knowledge-upload__progress-heading">
          <strong>{{ t('rag.upload.job.overall') }}</strong>
          <span>{{ overallPercent }}%</span>
        </div>
        <progress
          :value="overallPercent"
          max="100"
          :aria-label="t('rag.upload.job.overall')"
        />
      </div>

      <ol class="knowledge-upload__phases" :aria-label="t('rag.upload.job.phasesLabel')">
        <li
          v-for="phase in phases"
          :key="phase"
          :data-phase="phase"
          :data-phase-status="phaseStatus(phase)"
          :class="`is-${phaseStatus(phase)}`"
        >
          <span aria-hidden="true">{{ phaseMarker(phase) }}</span>
          <span>{{ t(`rag.upload.job.phases.${phase}`) }}</span>
          <small>{{ t(`rag.upload.job.phaseStates.${phaseStatus(phase)}`) }}</small>
        </li>
      </ol>

      <div
        v-if="terminalJob"
        data-testid="knowledge-upload-result"
        class="knowledge-upload__result"
      >
        <h3>{{ t('rag.upload.result.title') }}</h3>
        <dl class="knowledge-upload__stats">
          <div>
            <dt>{{ t('rag.upload.result.files') }}</dt>
            <dd>{{ filesProcessed }} / {{ filesTotal }}</dd>
            <small>
              {{ t('rag.upload.result.filesBreakdown', {
                skipped: job.files.skipped,
                failed: job.files.failed,
              }) }}
            </small>
          </div>
          <div>
            <dt>{{ t('rag.upload.result.chunks') }}</dt>
            <dd>{{ chunksCount }}</dd>
          </div>
          <div>
            <dt>{{ t('rag.upload.result.fts') }}</dt>
            <dd>{{ requestedMetric('fts', ftsCount) }}</dd>
          </div>
          <div>
            <dt>{{ t('rag.upload.result.vector') }}</dt>
            <dd>{{ requestedMetric('vector', vectorCount) }}</dd>
          </div>
        </dl>
      </div>

      <div
        v-if="job.warnings.length"
        data-testid="knowledge-job-warnings"
        class="knowledge-upload__warning"
        role="status"
      >
        <strong>{{ t('rag.upload.result.warnings') }}</strong>
        <ul>
          <li v-for="warning in job.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </div>
      <p
        v-if="jobError"
        data-testid="knowledge-job-error"
        class="knowledge-upload__error"
        role="alert"
      >
        {{ jobError }}
      </p>
      <button
        v-if="job.state === 'ready' || job.state === 'ready_with_warnings'"
        data-testid="knowledge-upload-verify"
        class="btn btn--ghost"
        type="button"
        @click="emit('verifySearch')"
      >
        {{ t('rag.upload.verifySearch') }}
      </button>
    </section>

    <p v-if="uiError" data-testid="knowledge-upload-error" class="knowledge-upload__error" role="alert">
      {{ uiError }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  completeKnowledgeUpload,
  createKnowledgeUpload,
  getKnowledgeJob,
  getKnowledgeUpload,
  loadStoredKnowledgeUpload,
  matchesStoredFile,
  saveStoredKnowledgeUpload,
  uploadFileInChunks,
  type KnowledgeIndexType,
  type KnowledgeJob,
  type KnowledgeJobPhase,
  type KnowledgeUploadStatus,
  type StoredKnowledgeUpload,
} from './knowledgeUpload'

const emit = defineEmits<{ verifySearch: [] }>()
const { t, locale } = useI18n()

const phases: KnowledgeJobPhase[] = [
  'validating',
  'extracting',
  'parsing',
  'fts_indexing',
  'vector_indexing',
  'complete',
]
const phaseRanks = new Map(phases.map((phase, index) => [phase, index]))
const terminalStates = new Set(['ready', 'ready_with_warnings', 'failed'])

const indexTypes = ref<KnowledgeIndexType[]>(['fts', 'vector'])
const selectedFile = shallowRef<File | null>(null)
const stored = ref<StoredKnowledgeUpload | null>(null)
const upload = ref<KnowledgeUploadStatus | null>(null)
const job = ref<KnowledgeJob | null>(null)
const operation = ref<'idle' | 'restoring' | 'creating' | 'uploading' | 'completing' | 'checking'>('idle')
const selectionError = ref('')
const uiError = ref('')
let pollTimer: number | null = null

const busy = computed(() => operation.value !== 'idle')
const terminalJob = computed(() => Boolean(job.value && terminalStates.has(job.value.state)))
const activeJob = computed(() => Boolean(
  stored.value?.jobId && (!job.value || job.value.state === 'queued' || job.value.state === 'running'),
))
const unfinishedUpload = computed(() => Boolean(stored.value && !stored.value.jobId && upload.value))
const resumePending = computed(() => Boolean(
  unfinishedUpload.value && upload.value && upload.value.uploadedBytes < upload.value.sizeBytes,
))
const awaitingCompletion = computed(() => Boolean(
  unfinishedUpload.value && upload.value && upload.value.uploadedBytes >= upload.value.sizeBytes,
))
const selectedMatchesStored = computed(() => Boolean(
  selectedFile.value && stored.value && matchesStoredFile(selectedFile.value, stored.value),
))
const needsFileReselection = computed(() => resumePending.value && !selectedMatchesStored.value)
const indexesLocked = computed(() => busy.value || activeJob.value || unfinishedUpload.value)
const fileInputLocked = computed(() => busy.value || activeJob.value || awaitingCompletion.value)
const actionDisabled = computed(() => {
  if (busy.value || activeJob.value || indexTypes.value.length === 0 || selectionError.value) return true
  if (awaitingCompletion.value) return false
  if (resumePending.value) return !selectedMatchesStored.value
  return !selectedFile.value
})
const actionLabel = computed(() => {
  if (operation.value === 'restoring' || operation.value === 'checking') return t('rag.upload.checking')
  if (operation.value === 'creating') return t('rag.upload.creating')
  if (operation.value === 'uploading') return t('rag.upload.uploading')
  if (operation.value === 'completing') return t('rag.upload.completing')
  if (awaitingCompletion.value) return t('rag.upload.continueIndexing')
  if (resumePending.value) return t('rag.upload.resume')
  return t('rag.upload.start')
})
const uploadPercent = computed(() => {
  if (!upload.value?.sizeBytes) return 0
  return Math.min(100, Math.floor((upload.value.uploadedBytes / upload.value.sizeBytes) * 100))
})
const overallPercent = computed(() => {
  if (!job.value) return 0
  return Math.min(100, Math.max(0, Math.round(job.value.overallProgress)))
})
const jobStateTone = computed(() => ({
  'control-pill--ok': job.value?.state === 'ready',
  'control-pill--warn': job.value?.state === 'ready_with_warnings' || job.value?.state === 'failed',
}))
const jobError = computed(() => describeError(job.value?.error))
const filesTotal = computed(() => formatCount(job.value?.files.total))
const filesProcessed = computed(() => formatCount(job.value?.files.processed))
const chunksCount = computed(() => formatCount(job.value?.chunks.total))
const ftsCount = computed(() => formatCount(job.value?.chunks.ftsIndexed))
const vectorCount = computed(() => formatCount(job.value?.chunks.vectorIndexed))

function message(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

function formatBytes(value: number): string {
  if (value < 1024) return t('rag.upload.bytes', { count: value })
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let amount = value / 1024
  let unit = units[0]
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024
    unit = units[index]
  }
  return `${new Intl.NumberFormat(locale.value, { maximumFractionDigits: 2 }).format(amount)} ${unit}`
}

function describeError(value: unknown): string {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    if (typeof record.message === 'string') return record.message
    if (typeof record.detail === 'string') return record.detail
    if (typeof record.code === 'string') return record.code
  }
  try {
    return JSON.stringify(value)
  } catch {
    return t('rag.upload.result.unknownError')
  }
}

function formatCount(value: number | undefined): string {
  return value === undefined ? '—' : new Intl.NumberFormat(locale.value).format(value)
}

function requestedMetric(indexType: KnowledgeIndexType, value: string): string {
  return indexTypes.value.includes(indexType) ? value : t('rag.upload.result.notRequested')
}

function phaseStatus(
  phase: KnowledgeJobPhase,
): 'pending' | 'current' | 'done' | 'failed' | 'skipped' {
  if ((phase === 'fts_indexing' && !indexTypes.value.includes('fts'))
    || (phase === 'vector_indexing' && !indexTypes.value.includes('vector'))) return 'skipped'
  if (!job.value) return 'pending'
  if (job.value.state === 'failed' && job.value.phase === phase) return 'failed'
  if (job.value.state === 'ready' || job.value.state === 'ready_with_warnings') return 'done'
  const currentRank = phaseRanks.get(job.value.phase) ?? 0
  const phaseRank = phaseRanks.get(phase) ?? 0
  if (phaseRank < currentRank) return 'done'
  if (phase === job.value.phase) return 'current'
  return 'pending'
}

function phaseMarker(phase: KnowledgeJobPhase): string {
  const status = phaseStatus(phase)
  if (status === 'done') return '✓'
  if (status === 'current') return '●'
  if (status === 'failed') return '!'
  if (status === 'skipped') return '–'
  return '○'
}

function selectFile(event: Event) {
  selectionError.value = ''
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (!file) {
    selectedFile.value = null
    return
  }
  if (!file.name.toLowerCase().endsWith('.zip')) {
    selectedFile.value = null
    selectionError.value = t('rag.upload.errors.zipOnly')
    input.value = ''
    return
  }
  if (resumePending.value && stored.value && !matchesStoredFile(file, stored.value)) {
    selectedFile.value = null
    selectionError.value = t('rag.upload.errors.fileMismatch', { filename: stored.value.filename })
    input.value = ''
    return
  }
  selectedFile.value = file
}

function persist(value: StoredKnowledgeUpload) {
  stored.value = value
  try {
    saveStoredKnowledgeUpload(value)
  } catch {
    uiError.value = t('rag.upload.errors.storage')
  }
}

function clearPoll() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePoll(jobId: string) {
  clearPoll()
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    void loadJob(jobId, true)
  }, 1500)
}

async function loadJob(jobId: string, background = false) {
  if (!background) operation.value = 'checking'
  try {
    const next = await getKnowledgeJob(jobId)
    job.value = next
    uiError.value = ''
    if (next.state === 'queued' || next.state === 'running') schedulePoll(jobId)
    else clearPoll()
  } catch (value) {
    uiError.value = message(value)
    if (stored.value?.jobId === jobId) schedulePoll(jobId)
  } finally {
    if (!background) operation.value = 'idle'
  }
}

async function finishUpload(uploadId: string) {
  operation.value = 'completing'
  try {
    const accepted = await completeKnowledgeUpload(uploadId)
    if (!stored.value) throw new Error(t('rag.upload.errors.missingResume'))
    persist({ ...stored.value, uploadId: accepted.uploadId, jobId: accepted.jobId })
    await loadJob(accepted.jobId, true)
  } catch (value) {
    uiError.value = message(value)
  } finally {
    operation.value = 'idle'
  }
}

async function transfer(file: File, initial: KnowledgeUploadStatus) {
  operation.value = 'uploading'
  uiError.value = ''
  try {
    const completed = await uploadFileInChunks(file, initial, {
      onProgress(next) {
        upload.value = next
      },
    })
    upload.value = completed
    await finishUpload(completed.uploadId)
  } catch (value) {
    uiError.value = message(value)
  } finally {
    if (operation.value === 'uploading') operation.value = 'idle'
  }
}

async function createAndTransfer(file: File) {
  operation.value = 'creating'
  uiError.value = ''
  try {
    const created = await createKnowledgeUpload(file, indexTypes.value)
    indexTypes.value = [...created.indexTypes]
    upload.value = created
    job.value = null
    persist({
      version: 1,
      collectionId: 'customer_shared',
      uploadId: created.uploadId,
      jobId: null,
      filename: file.name,
      sizeBytes: file.size,
      lastModified: file.lastModified,
      indexTypes: [...created.indexTypes],
    })
    await transfer(file, created)
  } catch (value) {
    uiError.value = message(value)
  } finally {
    if (operation.value === 'creating') operation.value = 'idle'
  }
}

function runAction() {
  if (actionDisabled.value) return
  if (awaitingCompletion.value && upload.value) {
    void finishUpload(upload.value.uploadId)
    return
  }
  const file = selectedFile.value
  if (!file) return
  if (resumePending.value && upload.value) void transfer(file, upload.value)
  else void createAndTransfer(file)
}

function refreshReferencedJob() {
  if (stored.value?.jobId) void loadJob(stored.value.jobId)
}

async function restore() {
  const saved = loadStoredKnowledgeUpload()
  if (!saved) return
  stored.value = saved
  indexTypes.value = [...saved.indexTypes]
  operation.value = 'restoring'
  try {
    if (saved.jobId) {
      await loadJob(saved.jobId, true)
      return
    }
    const restoredUpload = await getKnowledgeUpload(saved.uploadId)
    upload.value = restoredUpload
    if (restoredUpload.jobId) {
      persist({ ...saved, jobId: restoredUpload.jobId })
      await loadJob(restoredUpload.jobId, true)
    } else if (restoredUpload.uploadedBytes >= restoredUpload.sizeBytes) {
      await finishUpload(restoredUpload.uploadId)
    }
  } catch (value) {
    uiError.value = message(value)
  } finally {
    if (operation.value === 'restoring') operation.value = 'idle'
  }
}

onMounted(() => {
  void restore()
})

onUnmounted(clearPoll)
</script>

<style scoped>
.knowledge-upload {
  display: grid;
  gap: var(--sp-4);
}

.knowledge-upload p,
.knowledge-upload h3 {
  margin: 0;
}

.knowledge-upload__header,
.knowledge-upload__job-header,
.knowledge-upload__actions,
.knowledge-upload__progress-heading {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  justify-content: space-between;
}

.knowledge-upload__header > div {
  display: grid;
  gap: var(--sp-2);
}

.knowledge-upload__indexes {
  border: 0;
  display: grid;
  gap: var(--sp-3);
  margin: 0;
  padding: 0;
}

.knowledge-upload__indexes legend {
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.knowledge-upload__indexes label {
  align-items: start;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3);
}

.knowledge-upload__indexes label span {
  display: grid;
  gap: var(--sp-1);
}

.knowledge-upload__indexes small,
.knowledge-upload__hint {
  color: var(--text-muted);
}

.knowledge-upload__file-row {
  display: grid;
  gap: var(--sp-2);
}

.knowledge-upload__file-label {
  font-weight: 600;
}

.knowledge-upload__progress,
.knowledge-upload__job,
.knowledge-upload__result {
  display: grid;
  gap: var(--sp-3);
}

.knowledge-upload progress {
  accent-color: var(--accent);
  inline-size: 100%;
}

.knowledge-upload__phases {
  display: grid;
  gap: var(--sp-2);
  list-style: none;
  margin: 0;
  padding: 0;
}

.knowledge-upload__phases li {
  align-items: center;
  border-left: 2px solid var(--border);
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 1.5rem minmax(0, 1fr) auto;
  padding: var(--sp-2) var(--sp-3);
}

.knowledge-upload__phases li.is-current,
.knowledge-upload__phases li.is-done {
  border-left-color: var(--accent);
}

.knowledge-upload__phases li.is-failed {
  border-left-color: var(--warn);
}

.knowledge-upload__phases li.is-skipped,
.knowledge-upload__phases li.is-pending {
  color: var(--text-muted);
}

.knowledge-upload__stats {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  margin: 0;
}

.knowledge-upload__stats div {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  display: grid;
  gap: var(--sp-1);
  padding: var(--sp-3);
}

.knowledge-upload__stats dd {
  font-size: 1.2rem;
  font-weight: 600;
  margin: 0;
}

.knowledge-upload__notice,
.knowledge-upload__warning {
  color: var(--warn);
}

.knowledge-upload__warning {
  display: grid;
  gap: var(--sp-2);
}

.knowledge-upload__warning ul {
  margin: 0;
  padding-left: var(--sp-5);
}

.knowledge-upload__error {
  color: var(--warn);
}

@media (min-width: 700px) {
  .knowledge-upload__indexes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .knowledge-upload__indexes legend {
    grid-column: 1 / -1;
  }
}
</style>
