<template>
  <div class="rag-stage control-stage control-stage--spacious">
    <header class="rag-stage__header control-stage__header">
      <div class="rag-stage__title-block control-stage__title-block">
        <h2 class="rag-stage__title control-stage__title">RAG</h2>
        <p class="rag-stage__subtitle control-stage__subtitle">
          Local document sources, indexing, and retrieval preview.
        </p>
      </div>
      <div class="rag-stage__actions control-stage__actions mobile-action-strip">
        <button class="btn btn--ghost mobile-action-strip__button" type="button" :disabled="loading" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span class="mobile-action-strip__label">{{ loading ? 'Refreshing' : 'Refresh' }}</span>
        </button>
      </div>
    </header>

    <ErrorState v-if="error && !status" :message="error" :on-retry="loadData" />

    <section v-else class="rag-stat-row control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 6">
      <article
        v-for="metric in statusMetrics"
        :key="metric.label"
        class="control-stat rag-stat"
        :class="metric.className"
      >
        <span class="control-stat__label">{{ metric.label }}</span>
        <strong class="control-stat__value">{{ metric.value }}</strong>
        <span class="control-stat__hint">{{ metric.hint }}</span>
      </article>
    </section>

    <section v-if="jobState || lastJobSummary" class="rag-job control-panel" aria-live="polite">
      <div class="rag-job__head">
        <div class="rag-job__title">
          <LoadingSpinner v-if="jobState" />
          <span v-else :class="['rag-dot', lastJobSummary?.ok ? 'rag-dot--ok' : 'rag-dot--danger']"></span>
          <div>
            <strong>{{ jobState ? `${jobState.action} running` : lastJobSummary?.title }}</strong>
            <small>{{ jobState ? jobState.target : lastJobSummary?.hint }}</small>
          </div>
        </div>
        <span class="control-pill" :class="jobState ? 'control-pill--warn' : (lastJobSummary?.ok ? 'control-pill--ok' : 'control-pill--danger')">
          {{ jobState ? formatDuration(jobElapsedMs) : (lastJobSummary?.ok ? 'Completed' : 'Failed') }}
        </span>
      </div>
      <div v-if="jobState" class="rag-job__live">
        <div class="control-readout" :style="{ '--readout-ch': 'var(--warn)' }">
          <span class="control-readout__dot control-readout__dot--pulse"></span>
          <span class="control-readout__label">active jobs</span>
          <span class="control-readout__trace"><span class="control-readout__trace-fill" :style="{ width: activeJobTraceWidth }"></span></span>
          <span class="control-readout__status">{{ status?.ingestion?.activeJobs ?? 0 }}</span>
        </div>
        <div class="rag-job__metrics">
          <span><strong>{{ currentJobMetrics.filesSeen }}</strong> files seen</span>
          <span><strong>{{ currentJobMetrics.filesIndexed }}</strong> indexed</span>
          <span><strong>{{ currentJobMetrics.filesSkipped }}</strong> skipped</span>
          <span><strong>{{ currentJobMetrics.filesFailed }}</strong> failed</span>
          <span><strong>{{ currentJobMetrics.chunksWritten }}</strong> chunks</span>
          <span><strong>{{ currentJobMetrics.embeddingsWritten }}</strong> embeddings</span>
        </div>
      </div>
      <div v-else-if="lastJobSummary?.error" class="rag-job__error">{{ lastJobSummary.error }}</div>
      <div v-else-if="lastJobSummary" class="rag-job__metrics">
        <span><strong>{{ lastJobSummary.metrics.filesSeen }}</strong> files seen</span>
        <span><strong>{{ lastJobSummary.metrics.filesIndexed }}</strong> indexed</span>
        <span><strong>{{ lastJobSummary.metrics.filesSkipped }}</strong> skipped</span>
        <span><strong>{{ lastJobSummary.metrics.filesFailed }}</strong> failed</span>
        <span><strong>{{ lastJobSummary.metrics.chunksWritten }}</strong> chunks</span>
        <span><strong>{{ lastJobSummary.metrics.embeddingsWritten }}</strong> embeddings</span>
      </div>
    </section>

    <div class="rag-workbench">
      <section class="control-panel rag-source-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Source</span>
            <h3 class="control-panel__title">Add source</h3>
          </div>
          <div class="rag-segmented" role="group" aria-label="Source type">
            <button
              type="button"
              class="rag-segmented__btn"
              :class="{ 'is-active': sourceMode === 'upload' }"
              :aria-pressed="sourceMode === 'upload'"
              :disabled="isBusy"
              @click="sourceMode = 'upload'"
            >
              ZIP
            </button>
            <button
              type="button"
              class="rag-segmented__btn"
              :class="{ 'is-active': sourceMode === 'server' }"
              :aria-pressed="sourceMode === 'server'"
              :disabled="isBusy"
              @click="sourceMode = 'server'"
            >
              Path
            </button>
          </div>
        </div>

        <div v-if="sourceMode === 'upload'" class="rag-upload">
          <input ref="fileInput" type="file" accept=".zip,application/zip" hidden @change="onFileChange" />
          <button
            type="button"
            class="rag-dropzone"
            :class="{ 'is-dragover': dragOver }"
            :disabled="isBusy"
            @click="fileInput?.click()"
            @dragover.prevent="dragOver = true"
            @dragleave="dragOver = false"
            @drop.prevent="onDrop"
          >
            <Icon name="plus" :size="18" />
            <span>
              <strong>{{ uploadFile ? uploadFile.name : 'Choose ZIP archive' }}</strong>
              <small>{{ uploadFile ? formatBytes(uploadFile.size) : 'Drop one archive or select a local file.' }}</small>
            </span>
          </button>
          <button v-if="uploadFile" class="btn btn--ghost rag-clear-file" type="button" :disabled="isBusy" @click="clearUploadFile">
            <Icon name="x" :size="16" />
            <span>Clear</span>
          </button>
        </div>

        <div v-else class="rag-form-grid">
          <label class="rag-field rag-field--wide">
            <span>Server path</span>
            <input v-model.trim="sourceForm.path" class="control-input" type="text" placeholder="/path/to/docs" :disabled="isBusy" />
          </label>
          <label class="rag-field">
            <span>Include</span>
            <input v-model.trim="sourceForm.include" class="control-input" type="text" :disabled="isBusy" />
          </label>
          <label class="rag-field">
            <span>Exclude</span>
            <input v-model.trim="sourceForm.exclude" class="control-input" type="text" :disabled="isBusy" />
          </label>
        </div>

        <div class="rag-source-summary">
          <div>
            <strong>{{ sourceLabel || 'Auto source name' }}</strong>
            <small>{{ sourceMode === 'upload' ? 'ZIP upload' : 'Server path' }} · {{ sourceGroup }}</small>
          </div>
          <span class="control-pill">{{ sourceMode === 'upload' ? 'managed copy' : 'external path' }}</span>
        </div>

        <details class="rag-advanced">
          <summary class="control-row control-row--divider">Advanced</summary>
          <div class="rag-form-grid rag-form-grid--advanced">
            <label class="rag-field">
              <span>Name</span>
              <input v-model.trim="sourceForm.name" class="control-input" type="text" placeholder="Auto" :disabled="isBusy" />
            </label>
            <label class="rag-field">
              <span>Collection</span>
              <input v-model.trim="sourceForm.collectionId" class="control-input" type="text" placeholder="default" :disabled="isBusy" />
            </label>
          </div>
        </details>

        <div class="rag-panel-actions">
          <button class="btn btn--ghost" type="button" :disabled="isBusy" @click="addSource(false)">
            <Icon name="plus" :size="16" />
            <span>{{ sourceMode === 'upload' ? 'Import' : 'Add' }}</span>
          </button>
          <button class="btn btn--primary" type="button" :disabled="isBusy" @click="addSource(true)">
            <Icon name="refresh" :size="16" />
            <span>{{ sourceMode === 'upload' ? 'Import + Sync' : 'Add + Sync' }}</span>
          </button>
        </div>
      </section>

      <section class="control-panel rag-settings-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Settings</span>
            <h3 class="control-panel__title">Runtime defaults</h3>
          </div>
          <button class="btn btn--ghost" type="button" :disabled="!settingsDirty || savingSettings" @click="saveSettings">
            <Icon name="save" :size="16" />
            <span>{{ savingSettings ? 'Saving' : 'Save' }}</span>
          </button>
        </div>

        <div class="control-row">
          <div class="control-row__label-block">
            <span class="control-row__label">RAG enabled</span>
            <span class="control-row__desc">Gateway may need a restart when this changes.</span>
          </div>
          <div class="control-row__control">
            <label class="rag-switch">
              <input v-model="settings.enabled" type="checkbox" />
              <span class="rag-switch__track"></span>
            </label>
          </div>
        </div>

        <div class="control-row control-row--stack">
          <div class="control-row__label-block">
            <span class="control-row__label">Default retrieval</span>
            <span class="control-row__desc">Search preview and tools can still choose a mode per request.</span>
          </div>
          <div class="control-row__control">
            <div class="rag-segmented rag-segmented--wide" role="group" aria-label="Default retrieval mode">
              <button
                v-for="mode in retrievalModes"
                :key="mode.value"
                type="button"
                class="rag-segmented__btn"
                :class="{ 'is-active': settings.retrievalMode === mode.value }"
                :aria-pressed="settings.retrievalMode === mode.value"
                @click="setSettingsMode(mode.value)"
              >
                {{ mode.label }}
              </button>
            </div>
          </div>
        </div>

        <p v-if="settingsNotice" class="rag-notice" :class="`rag-notice--${settingsNotice.tone}`">
          {{ settingsNotice.text }}
        </p>
        <p v-else-if="status?.unavailable" class="rag-notice rag-notice--warn">
          {{ status.statusError || 'RAG manager is not available.' }}
        </p>
      </section>
    </div>

    <section class="control-panel rag-sources-panel">
      <div class="control-panel__head">
        <div>
          <span class="control-panel__eyebrow">Sources</span>
          <h3 class="control-panel__title">Configured sources</h3>
        </div>
        <span class="control-pill">{{ sources.length }} total</span>
      </div>

      <div v-if="loading && sources.length === 0" class="control-empty">
        <LoadingSpinner />
      </div>
      <div v-else-if="sources.length === 0" class="control-empty">
        <Icon class="control-empty__icon" name="fileText" :size="28" />
        <div class="control-empty__title">No RAG sources</div>
        <div class="control-empty__hint">Import a ZIP archive or add a server path above.</div>
      </div>
      <div v-else class="rag-table-wrap">
        <table class="rag-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Status</th>
              <th>Path</th>
              <th>Last sync</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in sources" :key="source.sourceId">
              <td>
                <div class="rag-source-cell">
                  <strong :title="source.name || source.sourceId">{{ source.name || source.sourceId }}</strong>
                  <small>{{ source.sourceId }}</small>
                </div>
              </td>
              <td>
                <span class="control-pill" :class="sourceStatusClass(source)">
                  {{ sourceStatusLabel(source) }}
                </span>
              </td>
              <td>
                <span class="rag-path" :title="source.path || ''">{{ source.path || '-' }}</span>
              </td>
              <td class="rag-mono">{{ formatTimestamp(source.lastScanFinishedAt) }}</td>
              <td>
                <div class="rag-row-actions">
                  <button class="rag-icon-btn" type="button" title="Sync" :disabled="isBusy" @click="syncSource(source, false)">
                    <Icon name="refresh" :size="15" />
                  </button>
                  <button class="rag-icon-btn" type="button" title="Reindex" :disabled="isBusy" @click="syncSource(source, true)">
                    <Icon name="regenerate" :size="15" />
                  </button>
                  <button class="btn btn--ghost rag-text-btn" type="button" :disabled="isBusy" @click="setSourceEnabled(source, !isSourceEnabled(source))">
                    {{ isSourceEnabled(source) ? 'Disable' : 'Enable' }}
                  </button>
                  <button class="rag-icon-btn rag-icon-btn--danger" type="button" title="Remove" :disabled="isBusy" @click="removeSource(source)">
                    <Icon name="trash" :size="15" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="control-panel rag-search-panel">
      <div class="control-panel__head">
        <div>
          <span class="control-panel__eyebrow">Search</span>
          <h3 class="control-panel__title">Retrieval preview</h3>
        </div>
        <span v-if="searchPayload?.fallback" class="control-pill control-pill--warn">
          {{ fallbackLabel(searchPayload.fallback) }}
        </span>
      </div>

      <form class="rag-searchbar" @submit.prevent="search">
        <input
          v-model.trim="searchForm.query"
          class="control-input rag-searchbar__query"
          type="search"
          placeholder="Search indexed documents"
          @input="searchModeTouched = true"
        />
        <select v-model="searchForm.mode" class="control-input rag-searchbar__mode" @change="searchModeTouched = true">
          <option value="hybrid">hybrid</option>
          <option value="fts">fts</option>
          <option value="vector_only">vector_only</option>
        </select>
        <button class="btn btn--primary" type="submit" :disabled="searching || !searchForm.query">
          <Icon name="search" :size="16" />
          <span>{{ searching ? 'Searching' : 'Search' }}</span>
        </button>
      </form>

      <ErrorState v-if="searchError" :message="searchError" :on-retry="search" />
      <div v-else-if="!searchPayload" class="control-empty rag-search-empty">
        <Icon class="control-empty__icon" name="search" :size="28" />
        <div class="control-empty__title">No search yet</div>
        <div class="control-empty__hint">Results are compact chunks. Open a chunk to inspect more source text.</div>
      </div>
      <div v-else-if="results.length === 0" class="control-empty">
        <div class="control-empty__title">No chunk matches</div>
        <div class="control-empty__hint">{{ searchMeta }}</div>
      </div>
      <div v-else class="rag-results">
        <div class="rag-inspect">
          <div>
            <strong>{{ results.length }} chunk matches</strong>
            <small>{{ searchMeta }}</small>
          </div>
          <span v-if="searchPayload.payloadBudget?.maxChars" class="control-pill" :class="{ 'control-pill--warn': searchPayload.payloadBudget.truncated }">
            {{ formatCount(searchPayload.payloadBudget.actualChars) }} / {{ formatCount(searchPayload.payloadBudget.maxChars) }} chars
          </span>
          <span v-if="searchScoring.textWeight !== undefined" class="control-pill">text {{ fixed(searchScoring.textWeight) }}</span>
          <span v-if="searchScoring.vectorWeight !== undefined" class="control-pill">vector {{ fixed(searchScoring.vectorWeight) }}</span>
        </div>

        <article v-for="(result, index) in results" :key="result.chunkId || `${result.path}-${index}`" class="rag-result control-card">
          <div class="rag-result__rank">#{{ index + 1 }}</div>
          <div class="rag-result__body">
            <div class="rag-result__topline">
              <span class="control-pill control-pill--accent">chunk</span>
              <span class="control-pill">{{ result.retrievalMode || searchPayload.effectiveMode || searchPayload.mode || searchForm.mode }}</span>
              <span v-if="result.untrustedEvidence" class="control-pill control-pill--warn">untrusted evidence</span>
              <span class="rag-result__score">score {{ fixed(result.score) }}</span>
            </div>
            <h4>{{ result.title || basename(result.path) || 'Untitled document' }}</h4>
            <div class="rag-result__path">{{ result.path || '' }}</div>
            <p class="rag-result__preview">{{ result.contentPreview || result.snippet || result.content || '' }}</p>

            <div v-if="hasScoreBreakdown(result)" class="rag-score-grid">
              <span v-if="scoreBreakdown(result).formula"><strong>Formula</strong>{{ scoreBreakdown(result).formula }}</span>
              <span v-if="scoreBreakdown(result).textWeight !== undefined"><strong>FTS weight</strong>{{ fixed(scoreBreakdown(result).textWeight) }}</span>
              <span v-if="scoreBreakdown(result).ftsContribution !== undefined"><strong>FTS contribution</strong>{{ fixed(scoreBreakdown(result).ftsContribution) }}</span>
              <span v-if="scoreBreakdown(result).vectorWeight !== undefined"><strong>Vector weight</strong>{{ fixed(scoreBreakdown(result).vectorWeight) }}</span>
              <span v-if="scoreBreakdown(result).vectorContribution !== undefined"><strong>Vector contribution</strong>{{ fixed(scoreBreakdown(result).vectorContribution) }}</span>
            </div>

            <div class="rag-result__meta">
              <span v-if="result.citation?.label"><strong>Citation</strong>{{ result.citation.label }}</span>
              <span v-if="lineRange(result.citation)"><strong>Lines</strong>{{ lineRange(result.citation) }}</span>
              <span v-if="result.collectionId"><strong>Collection</strong>{{ result.collectionId }}</span>
              <span v-if="result.sourceId"><strong>Source</strong>{{ result.sourceId }}</span>
              <span v-if="result.chunkId"><strong>Chunk</strong>{{ shortId(result.chunkId) }}</span>
              <span v-if="result.vectorScore !== null && result.vectorScore !== undefined"><strong>Vector</strong>{{ fixed(result.vectorScore) }}</span>
              <span v-if="ftsScore(result) !== null && ftsScore(result) !== undefined"><strong>FTS</strong>{{ fixed(ftsScore(result)) }}</span>
            </div>

            <div class="rag-result__actions">
              <button class="btn btn--ghost" type="button" :disabled="chunkLoading[result.chunkId || '']" @click="toggleChunk(result)">
                <Icon :name="expandedChunks[result.chunkId || ''] ? 'chevronDown' : 'chevronRight'" :size="16" />
                <span>{{ expandedChunks[result.chunkId || ''] ? 'Hide chunk' : 'Show chunk' }}</span>
              </button>
            </div>

            <div v-if="expandedChunks[result.chunkId || '']" class="rag-expanded">
              <div class="rag-expanded__head">
                <strong>Chunk detail</strong>
                <span v-if="expandedChunks[result.chunkId || ''].truncated" class="control-pill control-pill--warn">truncated</span>
                <span v-if="expandedChunks[result.chunkId || ''].citation?.label" class="control-pill">{{ expandedChunks[result.chunkId || ''].citation?.label }}</span>
              </div>
              <pre>{{ expandedChunks[result.chunkId || ''].content || '' }}</pre>
            </div>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useToasts } from '@/composables/useToasts'
import { useRpcStore } from '@/stores/rpc'

type RetrievalMode = 'hybrid' | 'fts' | 'vector_only'
type SourceMode = 'upload' | 'server'

interface RagConfig {
  enabled?: boolean
  retrieval_mode?: string
  embedding?: {
    provider?: string
    remote?: { model?: string }
    local?: { model?: string }
  }
}

interface ConfigPayload {
  rag?: RagConfig
}

interface RagStatus {
  enabled?: boolean
  unavailable?: boolean
  reason?: string
  statusError?: string
  retrievalMode?: string
  counts?: Record<string, number>
  sourcesSummary?: Record<string, number>
  documentsSummary?: Record<string, number>
  embedding?: {
    enabled?: boolean
    model?: string
  }
  vector?: {
    available?: boolean
    dimensions?: number | null
    indexStatus?: string
  }
  ingestion?: {
    activeJobs?: number
    latestJob?: RagJob | null
    summary?: Partial<RagJobMetrics>
  }
}

interface RagSource {
  sourceId: string
  name?: string
  path?: string
  status?: string
  enabled?: boolean
  lastScanFinishedAt?: number | string | null
}

interface RagJobMetrics {
  filesSeen: number
  filesIndexed: number
  filesSkipped: number
  filesFailed: number
  chunksWritten: number
  embeddingsWritten: number
}

interface RagJob extends Partial<RagJobMetrics> {
  status?: string
  durationMs?: number | null
}

interface RagSearchResult {
  chunkId?: string
  documentId?: string
  collectionId?: string
  sourceId?: string
  title?: string
  path?: string
  content?: string
  contentPreview?: string
  snippet?: string
  score?: number
  vectorScore?: number | null
  ftsScore?: number | null
  textScore?: number | null
  retrievalMode?: string
  sourceStatus?: string
  untrustedEvidence?: boolean
  citation?: RagCitation
  scoreBreakdown?: ScoreBreakdown
  metadata?: {
    scoreBreakdown?: ScoreBreakdown
  }
}

interface RagCitation {
  label?: string
  lineStart?: number | null
  lineEnd?: number | null
  page?: number | null
}

interface ScoreBreakdown {
  formula?: string
  textWeight?: number
  ftsContribution?: number
  vectorWeight?: number
  vectorContribution?: number
}

interface RagSearchResponse {
  query?: string
  mode?: string
  effectiveMode?: string
  results?: RagSearchResult[]
  fallback?: { from?: string; to?: string }
  diagnostics?: {
    durationMs?: number
    scoring?: {
      strategy?: string
      textWeight?: number
      vectorWeight?: number
    }
    candidates?: {
      fts?: number
      vector?: number
      merged?: number
    }
  }
  payloadBudget?: {
    maxChars?: number
    actualChars?: number
    truncated?: boolean
  }
}

interface RagShowResponse {
  content?: string
  truncated?: boolean
  citation?: RagCitation
}

interface JobState {
  action: string
  target: string
  startedAt: number
}

interface JobSummary {
  title: string
  hint: string
  ok: boolean
  error?: string
  metrics: RagJobMetrics
}

const DEFAULT_INCLUDE = '*.md,*.txt,**/*.md,**/*.txt'
const DEFAULT_EXCLUDE = '.obsidian/**,.git/**,private/**'
const EMPTY_METRICS: RagJobMetrics = {
  filesSeen: 0,
  filesIndexed: 0,
  filesSkipped: 0,
  filesFailed: 0,
  chunksWritten: 0,
  embeddingsWritten: 0,
}

const retrievalModes: Array<{ value: RetrievalMode; label: string }> = [
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'fts', label: 'Text' },
  { value: 'vector_only', label: 'Vector' },
]

const rpc = useRpcStore()
const { confirm } = useConfirm()
const { pushToast } = useToasts()

const loading = ref(false)
const error = ref<string | null>(null)
const status = ref<RagStatus | null>(null)
const configData = ref<ConfigPayload | null>(null)
const sources = ref<RagSource[]>([])

const sourceMode = ref<SourceMode>('upload')
const sourceForm = reactive({
  path: '',
  include: DEFAULT_INCLUDE,
  exclude: DEFAULT_EXCLUDE,
  name: '',
  collectionId: 'default',
})
const fileInput = ref<HTMLInputElement | null>(null)
const uploadFile = ref<File | null>(null)
const dragOver = ref(false)

const settings = reactive({
  enabled: false,
  retrievalMode: 'hybrid' as RetrievalMode,
})
const savingSettings = ref(false)
const settingsNotice = ref<{ tone: 'ok' | 'warn' | 'danger'; text: string } | null>(null)

const jobState = ref<JobState | null>(null)
const jobElapsedMs = ref(0)
const lastJobSummary = ref<JobSummary | null>(null)

const searchForm = reactive({
  query: '',
  mode: 'hybrid' as RetrievalMode,
})
const searchModeTouched = ref(false)
const searching = ref(false)
const searchError = ref<string | null>(null)
const searchPayload = ref<RagSearchResponse | null>(null)
const results = ref<RagSearchResult[]>([])
const expandedChunks = reactive<Record<string, RagShowResponse>>({})
const chunkLoading = reactive<Record<string, boolean>>({})

let stateUnsub: (() => void) | null = null
let jobTickTimer: ReturnType<typeof setInterval> | null = null
let jobStatusTimer: ReturnType<typeof setInterval> | null = null

const isBusy = computed(() => Boolean(jobState.value))
const ragConfig = computed(() => configData.value?.rag || {})

const settingsDirty = computed(() => {
  const cfg = ragConfig.value
  return (
    settings.enabled !== Boolean(cfg.enabled) ||
    settings.retrievalMode !== normalizeMode(cfg.retrieval_mode)
  )
})

const sourceGroup = computed(() => sourceForm.collectionId.trim() || 'default')

const sourceLabel = computed(() => {
  const manual = sourceForm.name.trim()
  if (manual) return manual
  if (sourceMode.value === 'upload') {
    return uploadFile.value?.name.replace(/\.zip$/i, '').trim() || ''
  }
  const rawPath = sourceForm.path.replace(/\/+$/, '').trim()
  if (!rawPath) return ''
  const parts = rawPath.split('/').filter(Boolean)
  return parts[parts.length - 1] || rawPath
})

const statusMetrics = computed(() => {
  const s = status.value
  return [
    {
      label: 'RAG',
      value: s?.enabled ? 'Enabled' : 'Disabled',
      hint: s?.unavailable ? 'Restart required' : (s?.enabled ? 'Configured on' : 'Disabled in config'),
      className: s?.enabled && !s.unavailable ? 'control-stat--accent' : 'control-stat--warn',
    },
    {
      label: 'Retrieval',
      value: formatRetrievalMode(s?.retrievalMode),
      hint: 'Default search mode',
      className: '',
    },
    {
      label: 'Sources',
      value: formatCount(s?.counts?.sources),
      hint: summaryHint(s?.sourcesSummary, 'sources', s?.counts?.sources),
      className: Number(s?.counts?.sources || 0) > 0 ? 'control-stat--accent' : '',
    },
    {
      label: 'Documents',
      value: formatCount(s?.counts?.documents),
      hint: summaryHint(s?.documentsSummary, 'documents', s?.counts?.documents),
      className: '',
    },
    {
      label: 'Chunks',
      value: formatCount(s?.counts?.chunks),
      hint: 'Indexed chunks',
      className: '',
    },
    {
      label: 'Vector',
      value: formatIndexStatus(s?.vector),
      hint: vectorHint(s),
      className: s?.vector?.available ? 'control-stat--accent' : 'control-stat--warn',
    },
  ]
})

const currentJobMetrics = computed<RagJobMetrics>(() => {
  const latest = status.value?.ingestion?.latestJob
  const summary = status.value?.ingestion?.summary
  return summarizeJobs([latest || summary || {}])
})

const activeJobTraceWidth = computed(() => {
  const count = Number(status.value?.ingestion?.activeJobs || 0)
  return `${Math.min(100, Math.max(8, count * 34))}%`
})

const searchScoring = computed(() => searchPayload.value?.diagnostics?.scoring || {})

const searchMeta = computed(() => {
  const payload = searchPayload.value
  if (!payload) return ''
  const parts = [
    payload.query || searchForm.query,
    payload.effectiveMode || payload.mode || searchForm.mode,
    payload.diagnostics?.durationMs !== undefined ? `${payload.diagnostics.durationMs} ms` : '',
  ]
  return parts.filter(Boolean).join(' · ')
})

onMounted(() => {
  stateUnsub = rpc.on('_state', (state) => {
    if (state === 'connected') void loadData()
  })
  void loadData()
})

onUnmounted(() => {
  if (stateUnsub) stateUnsub()
  clearJobTimers()
})

async function loadData(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await rpc.waitForConnection()
    configData.value = await rpc.call<ConfigPayload>('config.get', {})
    try {
      status.value = await rpc.call<RagStatus>('rag.status', {})
    } catch (err) {
      status.value = statusFromConfig(err)
    }
    syncSettingsFromConfig()
    if (status.value?.enabled && !status.value.unavailable) {
      const payload = await rpc.call<{ items?: RagSource[] }>('rag.list', {
        kind: 'sources',
        includeDisabled: true,
      })
      sources.value = payload.items || []
    } else {
      sources.value = []
    }
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    loading.value = false
  }
}

async function refreshStatusQuiet(): Promise<void> {
  try {
    status.value = await rpc.call<RagStatus>('rag.status', {})
    if (status.value?.enabled && !status.value.unavailable) {
      const payload = await rpc.call<{ items?: RagSource[] }>('rag.list', {
        kind: 'sources',
        includeDisabled: true,
      })
      sources.value = payload.items || sources.value
    }
  } catch {
    // The foreground action owns user-visible errors.
  }
}

function syncSettingsFromConfig(): void {
  const cfg = ragConfig.value
  settings.enabled = Boolean(cfg.enabled ?? status.value?.enabled)
  settings.retrievalMode = normalizeMode(cfg.retrieval_mode || status.value?.retrievalMode)
  if (!searchModeTouched.value) searchForm.mode = settings.retrievalMode
}

function setSettingsMode(mode: RetrievalMode): void {
  settings.retrievalMode = mode
  if (!searchModeTouched.value) searchForm.mode = mode
}

async function saveSettings(): Promise<void> {
  const cfg = ragConfig.value
  const patches: Record<string, boolean | string> = {}
  if (settings.enabled !== Boolean(cfg.enabled)) patches['rag.enabled'] = settings.enabled
  if (settings.retrievalMode !== normalizeMode(cfg.retrieval_mode)) {
    patches['rag.retrieval_mode'] = settings.retrievalMode
  }
  if (Object.keys(patches).length === 0) return
  savingSettings.value = true
  settingsNotice.value = null
  try {
    const result = await rpc.call<{ restartRequired?: boolean }>('config.patch', { patches })
    settingsNotice.value = result.restartRequired
      ? { tone: 'warn', text: 'Saved. Restart gateway to apply this runtime change.' }
      : { tone: 'ok', text: 'Saved.' }
    pushToast(settingsNotice.value.text, { tone: result.restartRequired ? 'info' : 'ok' })
    await loadData()
  } catch (err) {
    settingsNotice.value = { tone: 'danger', text: messageFromError(err) }
    pushToast(settingsNotice.value.text, { tone: 'danger' })
  } finally {
    savingSettings.value = false
  }
}

function onFileChange(event: Event): void {
  const input = event.currentTarget as HTMLInputElement
  setUploadFile(input.files?.[0] || null)
}

function onDrop(event: DragEvent): void {
  dragOver.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  setUploadFile(files.find(file => file.name.toLowerCase().endsWith('.zip')) || files[0] || null)
}

function setUploadFile(file: File | null): void {
  uploadFile.value = file
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    pushToast('RAG import only accepts .zip files.', { tone: 'danger' })
  }
}

function clearUploadFile(): void {
  uploadFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function addSource(index: boolean): Promise<void> {
  if (sourceMode.value === 'upload') {
    await importZip(index)
    return
  }
  await addServerSource(index)
}

async function addServerSource(index: boolean): Promise<void> {
  const path = sourceForm.path.trim()
  if (!path) {
    pushToast('Server path is required.', { tone: 'danger' })
    return
  }
  beginJob(index ? 'Add + Sync' : 'Add', path)
  try {
    const payload = await rpc.call('rag.add', {
      path,
      name: sourceLabel.value || null,
      collectionId: sourceGroup.value,
      include: splitGlobs(sourceForm.include),
      exclude: splitGlobs(sourceForm.exclude),
      index,
    })
    finishJob(index ? 'Add + Sync' : 'Add', payload)
    await loadData()
  } catch (err) {
    failJob(err)
  }
}

async function importZip(index: boolean): Promise<void> {
  const file = uploadFile.value
  if (!file) {
    pushToast('Choose a .zip file first.', { tone: 'danger' })
    return
  }
  if (!file.name.toLowerCase().endsWith('.zip')) {
    pushToast('RAG import only accepts .zip files.', { tone: 'danger' })
    return
  }
  const action = index ? 'Import + Sync' : 'Import'
  beginJob(action, file.name)
  try {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('collectionId', sourceGroup.value)
    form.append('name', sourceLabel.value || file.name.replace(/\.zip$/i, ''))
    form.append('index', index ? 'true' : 'false')
    const response = await fetch('/api/v1/rag/imports', {
      method: 'POST',
      body: form,
      headers: authHeaders(),
      credentials: 'same-origin',
    })
    const payload = await readJsonResponse(response)
    if (!response.ok) {
      throw new Error(String(payload.error || `Upload failed with HTTP ${response.status}`))
    }
    clearUploadFile()
    finishJob(action, payload)
    await loadData()
  } catch (err) {
    failJob(err)
  }
}

async function syncSource(source: RagSource, force: boolean): Promise<void> {
  const sourceId = source.sourceId
  if (!sourceId) return
  const action = force ? 'Reindex' : 'Sync'
  beginJob(action, source.name || sourceId)
  try {
    const payload = await rpc.call(force ? 'rag.reindex' : 'rag.sync', { sourceId })
    finishJob(action, payload)
    await loadData()
  } catch (err) {
    failJob(err)
  }
}

async function setSourceEnabled(source: RagSource, enabled: boolean): Promise<void> {
  try {
    await rpc.call(enabled ? 'rag.enable_source' : 'rag.disable_source', { sourceId: source.sourceId })
    pushToast(enabled ? 'Source enabled.' : 'Source disabled.', { tone: 'ok' })
    await loadData()
  } catch (err) {
    pushToast(messageFromError(err), { tone: 'danger' })
  }
}

async function removeSource(source: RagSource): Promise<void> {
  const ok = await confirm({
    title: 'Remove RAG source',
    body: `Remove ${source.name || source.sourceId} and delete its indexed chunks from RAG?`,
    primaryLabel: 'Remove',
    primaryClass: 'btn--danger',
  })
  if (!ok) return
  try {
    await rpc.call('rag.remove_source', { sourceId: source.sourceId, deleteIndex: true })
    searchPayload.value = null
    results.value = []
    clearExpandedChunks()
    pushToast('Source removed.', { tone: 'ok' })
    await loadData()
  } catch (err) {
    pushToast(messageFromError(err), { tone: 'danger' })
  }
}

async function search(): Promise<void> {
  if (!searchForm.query) return
  searching.value = true
  searchError.value = null
  try {
    const payload = await rpc.call<RagSearchResponse>('rag.search', {
      query: searchForm.query,
      mode: searchForm.mode,
      limit: 5,
    })
    searchPayload.value = payload
    results.value = payload.results || []
    clearExpandedChunks()
  } catch (err) {
    searchError.value = messageFromError(err)
  } finally {
    searching.value = false
  }
}

async function toggleChunk(result: RagSearchResult): Promise<void> {
  const chunkId = result.chunkId
  if (!chunkId) return
  if (expandedChunks[chunkId]) {
    delete expandedChunks[chunkId]
    return
  }
  chunkLoading[chunkId] = true
  try {
    expandedChunks[chunkId] = await rpc.call<RagShowResponse>('rag.show', {
      chunkId,
      maxChars: 6000,
    })
  } catch (err) {
    pushToast(messageFromError(err), { tone: 'danger' })
  } finally {
    chunkLoading[chunkId] = false
  }
}

function beginJob(action: string, target: string): void {
  clearJobTimers()
  jobState.value = { action, target, startedAt: Date.now() }
  jobElapsedMs.value = 0
  lastJobSummary.value = null
  jobTickTimer = setInterval(() => {
    if (jobState.value) jobElapsedMs.value = Date.now() - jobState.value.startedAt
  }, 1000)
  jobStatusTimer = setInterval(() => {
    void refreshStatusQuiet()
  }, 2500)
}

function finishJob(action: string, payload: unknown): void {
  const elapsed = jobState.value ? Date.now() - jobState.value.startedAt : 0
  clearJobTimers()
  jobState.value = null
  const metrics = summarizeJobs(extractJobs(payload))
  lastJobSummary.value = {
    title: `${action} completed`,
    hint: formatDuration(elapsed),
    ok: true,
    metrics,
  }
}

function failJob(err: unknown): void {
  const elapsed = jobState.value ? Date.now() - jobState.value.startedAt : 0
  const action = jobState.value?.action || 'RAG job'
  clearJobTimers()
  jobState.value = null
  const message = messageFromError(err)
  lastJobSummary.value = {
    title: `${action} failed`,
    hint: formatDuration(elapsed),
    ok: false,
    error: message,
    metrics: { ...EMPTY_METRICS },
  }
  pushToast(message, { tone: 'danger' })
}

function clearJobTimers(): void {
  if (jobTickTimer) {
    clearInterval(jobTickTimer)
    jobTickTimer = null
  }
  if (jobStatusTimer) {
    clearInterval(jobStatusTimer)
    jobStatusTimer = null
  }
}

function statusFromConfig(err: unknown): RagStatus {
  const rag = ragConfig.value
  const enabled = Boolean(rag.enabled)
  return {
    enabled,
    unavailable: enabled,
    reason: enabled ? 'manager_unavailable' : 'rag_disabled',
    statusError: messageFromError(err),
    retrievalMode: normalizeMode(rag.retrieval_mode),
    embedding: {
      enabled: Boolean(rag.embedding && rag.embedding.provider !== 'none'),
      model: rag.embedding?.remote?.model || rag.embedding?.local?.model || 'fts-only',
    },
    vector: { available: false, dimensions: null, indexStatus: 'unavailable' },
    counts: { collections: 0, sources: 0, documents: 0, chunks: 0, errors: 0 },
    sourcesSummary: {},
    documentsSummary: {},
    ingestion: { activeJobs: 0, latestJob: null, summary: {} },
  }
}

function isSourceEnabled(source: RagSource): boolean {
  return source.enabled !== false && source.status !== 'disabled'
}

function sourceStatusLabel(source: RagSource): string {
  return source.status || (isSourceEnabled(source) ? 'active' : 'disabled')
}

function sourceStatusClass(source: RagSource): string {
  const statusLabel = sourceStatusLabel(source)
  if (statusLabel === 'active' || statusLabel === 'ready') return 'control-pill--ok'
  if (statusLabel === 'disabled') return 'control-pill--warn'
  if (statusLabel === 'error' || statusLabel === 'failed') return 'control-pill--danger'
  return ''
}

function formatTimestamp(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-'
  const raw = typeof value === 'number' ? value * 1000 : value
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function normalizeMode(value: unknown): RetrievalMode {
  const raw = String(value || 'hybrid').trim()
  if (raw === 'vector') return 'vector_only'
  if (raw === 'text') return 'fts'
  if (raw === 'fts' || raw === 'vector_only' || raw === 'hybrid') return raw
  return 'hybrid'
}

function formatRetrievalMode(value: unknown): string {
  const mode = normalizeMode(value)
  if (mode === 'fts') return 'Text'
  if (mode === 'vector_only') return 'Vector'
  return 'Hybrid'
}

function formatIndexStatus(vector: RagStatus['vector']): string {
  const raw = vector?.indexStatus || (vector?.available ? 'ready' : 'unavailable')
  const labels: Record<string, string> = {
    ready: 'Ready',
    unavailable: 'Unavailable',
    stale: 'Stale',
    rebuilding: 'Rebuilding',
  }
  return labels[String(raw)] || String(raw || '-')
}

function summaryHint(summary: Record<string, number> | undefined, noun: string, total: number | undefined): string {
  const entries = Object.entries(summary || {})
    .filter(([, value]) => Number(value || 0) > 0)
    .map(([key, value]) => `${formatCount(value)} ${key}`)
  if (entries.length) return entries.join(' · ')
  if (Number(total || 0) > 0) return `${formatCount(total)} total`
  return `No ${noun}`
}

function vectorHint(s: RagStatus | null): string {
  const vector = s?.vector || {}
  const embedding = s?.embedding || {}
  if (!vector.available) {
    return embedding.enabled ? 'Embedding configured, index unavailable' : 'Embedding disabled'
  }
  const dims = vector.dimensions ? `${formatCount(vector.dimensions)} dims` : ''
  const model = embedding.model && embedding.model !== 'fts-only' ? embedding.model : ''
  return [dims, model].filter(Boolean).join(' · ') || 'Vector search ready'
}

function splitGlobs(value: string): string[] {
  return value.split(',').map(item => item.trim()).filter(Boolean)
}

function authHeaders(): HeadersInit {
  try {
    const token = sessionStorage.getItem('opensquilla.wsToken') || ''
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

async function readJsonResponse(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text().catch(() => '')
  if (!text) return {}
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    return { error: text }
  }
}

function extractJobs(payload: unknown): RagJob[] {
  if (!payload || typeof payload !== 'object') return []
  const maybe = payload as { jobs?: RagJob[]; job?: RagJob }
  if (Array.isArray(maybe.jobs)) return maybe.jobs
  if (maybe.job) return [maybe.job]
  return []
}

function summarizeJobs(jobs: Array<Partial<RagJobMetrics> | null | undefined>): RagJobMetrics {
  return jobs.reduce<RagJobMetrics>((acc, job) => {
    if (!job) return acc
    acc.filesSeen += Number(job.filesSeen || 0)
    acc.filesIndexed += Number(job.filesIndexed || 0)
    acc.filesSkipped += Number(job.filesSkipped || 0)
    acc.filesFailed += Number(job.filesFailed || 0)
    acc.chunksWritten += Number(job.chunksWritten || 0)
    acc.embeddingsWritten += Number(job.embeddingsWritten || 0)
    return acc
  }, { ...EMPTY_METRICS })
}

function clearExpandedChunks(): void {
  Object.keys(expandedChunks).forEach((key) => delete expandedChunks[key])
}

function hasScoreBreakdown(result: RagSearchResult): boolean {
  const breakdown = scoreBreakdown(result)
  return Boolean(
    breakdown.formula ||
    breakdown.textWeight !== undefined ||
    breakdown.ftsContribution !== undefined ||
    breakdown.vectorWeight !== undefined ||
    breakdown.vectorContribution !== undefined,
  )
}

function scoreBreakdown(result: RagSearchResult): ScoreBreakdown {
  return result.scoreBreakdown || result.metadata?.scoreBreakdown || {}
}

function ftsScore(result: RagSearchResult): number | null | undefined {
  return result.ftsScore ?? result.textScore
}

function lineRange(citation?: RagCitation): string {
  if (!citation) return ''
  if (citation.page !== null && citation.page !== undefined) return `p. ${citation.page}`
  if (citation.lineStart && citation.lineEnd) return `L${citation.lineStart}-${citation.lineEnd}`
  if (citation.lineStart) return `L${citation.lineStart}`
  return ''
}

function fallbackLabel(fallback: { from?: string; to?: string }): string {
  return `${fallback.from || 'mode'} -> ${fallback.to || 'fallback'}`
}

function basename(path?: string): string {
  const raw = String(path || '')
  return raw.split('/').filter(Boolean).pop() || raw
}

function shortId(value?: string): string {
  const raw = String(value || '')
  if (!raw) return ''
  return raw.length > 14 ? `${raw.slice(0, 10)}...` : raw
}

function fixed(value: unknown): string {
  return Number(value || 0).toFixed(3)
}

function formatCount(value: unknown): string {
  return new Intl.NumberFormat().format(Number(value || 0))
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor((ms || 0) / 1000))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes <= 0) return `${rest}s`
  return `${minutes}m ${String(rest).padStart(2, '0')}s`
}

function messageFromError(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}
</script>

<style scoped>
.rag-stat-row {
  --control-stat-min: 160px;
}

.rag-stat {
  min-height: 116px;
}

.rag-workbench {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
}

.rag-segmented {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: inline-flex;
  overflow: hidden;
}

.rag-segmented--wide {
  width: 100%;
}

.rag-segmented__btn {
  background: transparent;
  border: 0;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-xs);
  font-weight: 600;
  min-height: 34px;
  padding: 0 var(--sp-3);
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
}

.rag-segmented__btn:hover {
  color: var(--text);
}

.rag-segmented__btn.is-active {
  background: var(--accent);
  color: var(--accent-foreground);
}

.rag-segmented__btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.rag-upload {
  display: grid;
  gap: var(--sp-2);
}

.rag-dropzone {
  align-items: center;
  background: var(--bg);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: flex;
  gap: var(--sp-3);
  min-height: 84px;
  padding: var(--sp-4);
  text-align: left;
  transition: border-color var(--transition), background var(--transition);
  width: 100%;
}

.rag-dropzone:hover,
.rag-dropzone.is-dragover {
  background: var(--bg-hover);
  border-color: var(--accent);
}

.rag-dropzone strong,
.rag-dropzone small {
  display: block;
  line-height: 1.35;
}

.rag-dropzone small {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.rag-clear-file {
  justify-self: flex-start;
}

.rag-form-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.rag-form-grid--advanced {
  padding-top: var(--sp-1);
}

.rag-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rag-field--wide {
  grid-column: 1 / -1;
}

.rag-field span {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 600;
}

.rag-field .control-input,
.rag-searchbar .control-input {
  max-width: none;
  width: 100%;
}

.rag-source-summary {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: var(--sp-3);
}

.rag-source-summary strong,
.rag-source-summary small {
  display: block;
}

.rag-source-summary small {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.rag-advanced {
  border-top: 1px solid var(--border);
}

.rag-panel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.rag-switch {
  display: inline-flex;
}

.rag-switch input {
  height: 1px;
  opacity: 0;
  position: absolute;
  width: 1px;
}

.rag-switch__track {
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  display: inline-flex;
  height: 24px;
  position: relative;
  transition: background var(--transition), border-color var(--transition);
  width: 44px;
}

.rag-switch__track::after {
  background: var(--text-dim);
  border-radius: 50%;
  content: "";
  height: 18px;
  left: 2px;
  position: absolute;
  top: 2px;
  transition: transform var(--transition), background var(--transition);
  width: 18px;
}

.rag-switch input:checked + .rag-switch__track {
  background: color-mix(in srgb, var(--accent) 20%, var(--bg-elevated));
  border-color: var(--accent);
}

.rag-switch input:checked + .rag-switch__track::after {
  background: var(--accent);
  transform: translateX(20px);
}

.rag-notice {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
  padding: var(--sp-3);
}

.rag-notice--ok {
  border-color: color-mix(in srgb, var(--ok) 35%, var(--border));
  color: var(--ok);
}

.rag-notice--warn {
  border-color: color-mix(in srgb, var(--warn) 35%, var(--border));
  color: var(--warn);
}

.rag-notice--danger {
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
  color: var(--danger);
}

.rag-job {
  gap: var(--sp-4);
}

.rag-job__head,
.rag-job__title {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
}

.rag-job__head {
  justify-content: space-between;
}

.rag-job__title strong,
.rag-job__title small {
  display: block;
}

.rag-job__title small {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.rag-dot {
  border-radius: 50%;
  display: inline-flex;
  height: 10px;
  width: 10px;
}

.rag-dot--ok {
  background: var(--ok);
}

.rag-dot--danger {
  background: var(--danger);
}

.rag-job__live {
  display: grid;
  gap: var(--sp-3);
}

.rag-job__metrics {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.rag-job__metrics span {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  padding: var(--sp-2);
}

.rag-job__metrics strong {
  color: var(--text);
  display: block;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.rag-job__error {
  color: var(--danger);
  font-size: var(--fs-sm);
}

.rag-table-wrap {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow-x: auto;
}

.rag-table {
  border-collapse: collapse;
  color: var(--text);
  font-size: var(--fs-sm);
  width: 100%;
}

.rag-table th {
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-strong);
  color: var(--text-muted);
  font-weight: 600;
  padding: var(--sp-3) var(--sp-4);
  text-align: left;
  white-space: nowrap;
}

.rag-table td {
  border-bottom: 1px solid var(--hairline);
  padding: var(--sp-3) var(--sp-4);
  vertical-align: middle;
}

.rag-table tbody tr:last-child td {
  border-bottom: none;
}

.rag-table tbody tr:hover td {
  background: var(--bg-hover);
}

.rag-source-cell strong,
.rag-source-cell small {
  display: block;
}

.rag-source-cell strong {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-source-cell small,
.rag-path {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.rag-path {
  display: inline-block;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.rag-mono {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.rag-row-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.rag-icon-btn {
  align-items: center;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 32px;
  justify-content: center;
  width: 32px;
}

.rag-icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.rag-icon-btn--danger:hover {
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.rag-icon-btn:disabled,
.rag-text-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.rag-text-btn {
  min-height: 32px;
  padding-inline: var(--sp-3);
}

.rag-searchbar {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: minmax(0, 1fr) 170px auto;
}

.rag-searchbar__query {
  min-width: 0;
}

.rag-searchbar__mode {
  min-width: 0;
}

.rag-search-empty {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.rag-results {
  display: grid;
  gap: var(--sp-3);
}

.rag-inspect {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: space-between;
  padding: var(--sp-3);
}

.rag-inspect strong,
.rag-inspect small {
  display: block;
}

.rag-inspect small {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.rag-result {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: 48px minmax(0, 1fr);
}

.rag-result__rank {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  padding-top: 2px;
}

.rag-result__body {
  min-width: 0;
}

.rag-result__topline,
.rag-result__meta,
.rag-result__actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.rag-result__score {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin-left: auto;
}

.rag-result h4 {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: var(--sp-3) 0 2px;
}

.rag-result__path {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-result__preview {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.55;
  margin: var(--sp-3) 0;
}

.rag-result__meta {
  margin-bottom: var(--sp-3);
}

.rag-result__meta span,
.rag-score-grid span {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  padding: 4px 8px;
}

.rag-result__meta strong,
.rag-score-grid strong {
  color: var(--text);
  margin-right: 5px;
}

.rag-score-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}

.rag-expanded {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-top: var(--sp-3);
  overflow: hidden;
}

.rag-expanded__head {
  align-items: center;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: space-between;
  padding: var(--sp-3);
}

.rag-expanded pre {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.55;
  margin: 0;
  max-height: 420px;
  overflow: auto;
  padding: var(--sp-3);
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1180px) {
  .rag-stat-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .rag-workbench {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .rag-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .rag-form-grid,
  .rag-searchbar,
  .rag-result {
    grid-template-columns: 1fr;
  }

  .rag-job__head,
  .rag-source-summary,
  .rag-inspect {
    align-items: flex-start;
    flex-direction: column;
  }

  .rag-job__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rag-result__score {
    margin-left: 0;
  }
}

@media (max-width: 520px) {
  .rag-stat-row,
  .rag-job__metrics {
    grid-template-columns: 1fr;
  }
}
</style>
