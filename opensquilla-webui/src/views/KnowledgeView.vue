<template>
  <div class="rag-stage control-stage control-stage--spacious">
    <header class="rag-stage__header control-stage__header">
      <div class="rag-stage__title-block control-stage__title-block">
        <h1 class="rag-stage__title control-stage__title">RAG</h1>
        <p class="rag-stage__subtitle control-stage__subtitle">本地金融资料库检索、证据查看与人工评测</p>
      </div>
      <div class="rag-stage__actions control-stage__actions mobile-action-strip">
        <button
          class="btn btn--ghost mobile-action-strip__button"
          type="button"
          :disabled="loading || preparing"
          @click="refreshAll"
        >
          <Icon name="refresh" :size="16" />
          <span class="mobile-action-strip__label">{{ loading ? '刷新中' : '刷新' }}</span>
        </button>
        <button
          class="btn btn--primary mobile-action-strip__button"
          type="button"
          :disabled="preparing"
          @click="prepareSample"
        >
          <Icon name="plus" :size="16" />
          <span class="mobile-action-strip__label">{{ preparing ? '构建中' : '构建知识库' }}</span>
        </button>
      </div>
    </header>

    <ErrorState v-if="error && !status" :message="error" :on-retry="refreshAll" />

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

    <section v-if="preparing || judgmentPath" class="rag-job control-panel" aria-live="polite">
      <div class="rag-job__head">
        <div class="rag-job__title">
          <LoadingSpinner v-if="preparing" />
          <span v-else class="rag-dot rag-dot--ok"></span>
          <div>
            <strong>{{ preparing ? 'Building collection index' : 'Judgment saved' }}</strong>
            <small>{{ preparing ? sourceRoot : judgmentPath }}</small>
          </div>
        </div>
        <span class="control-pill" :class="preparing ? 'control-pill--warn' : 'control-pill--ok'">
          {{ preparing ? 'Running' : 'Saved' }}
        </span>
      </div>
    </section>

    <div class="rag-workbench">
      <section class="control-panel rag-source-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Source</span>
            <h2 class="control-panel__title">Collection ingest</h2>
          </div>
          <span class="control-pill" :class="hasIndex ? 'control-pill--ok' : 'control-pill--warn'">
            {{ hasIndex ? 'Indexed' : 'Pending' }}
          </span>
        </div>

        <div class="rag-form-grid">
          <label class="rag-field">
            <span>Collection</span>
            <input v-model="collectionName" class="control-input" autocomplete="off" :disabled="preparing" />
          </label>
          <label class="rag-field">
            <span>Retrieval</span>
            <select v-model="retrievalProfile" class="control-input">
              <option value="sqlite_fts5_default">SQLite FTS5</option>
            </select>
          </label>
          <label class="rag-field rag-field--wide">
            <span>资料根目录</span>
            <input v-model="sourceRoot" class="control-input" autocomplete="off" :disabled="preparing" />
          </label>
          <label class="rag-field">
            <span>样本数量</span>
            <input
              v-model.number="sampleLimit"
              class="control-input control-input--narrow"
              type="number"
              min="1"
              max="120"
              :disabled="preparing"
            />
          </label>
          <label class="rag-field">
            <span>默认 Top K</span>
            <input v-model.number="topK" class="control-input control-input--narrow" type="number" min="1" max="20" />
          </label>
        </div>

        <div class="rag-source-summary">
          <div>
            <strong>{{ sourceLabel }}</strong>
            <small>{{ status?.rootDir || sourceRoot }}</small>
          </div>
          <span class="control-pill">{{ activeIndexProfile }}</span>
        </div>

        <div class="rag-panel-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || preparing" @click="refreshAll">
            <Icon name="refresh" :size="16" />
            <span>Refresh</span>
          </button>
          <button class="btn btn--primary" type="button" :disabled="preparing" @click="prepareSample">
            <Icon name="regenerate" :size="16" />
            <span>{{ preparing ? 'Building' : 'Build collection' }}</span>
          </button>
        </div>
      </section>

      <section class="control-panel rag-questions-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Eval</span>
            <h2 class="control-panel__title">Golden queries</h2>
          </div>
          <button class="btn btn--ghost" type="button" :disabled="questionsLoading" @click="loadQuestions">
            <Icon name="refresh" :size="16" />
            <span>{{ questionsLoading ? 'Loading' : 'Load' }}</span>
          </button>
        </div>

        <div v-if="questionsLoading && questions.length === 0" class="control-empty">
          <LoadingSpinner />
        </div>
        <div v-else-if="questions.length === 0" class="control-empty">
          <Icon class="control-empty__icon" name="listChecks" :size="28" />
          <div class="control-empty__title">No queries</div>
          <div class="control-empty__hint">Build the sample index to load evaluation prompts.</div>
        </div>
        <div v-else class="rag-question-list">
          <button
            v-for="question in questions"
            :key="question.id"
            class="rag-question"
            :class="{ 'is-active': question.id === activeQuestionId }"
            type="button"
            @click="selectQuestion(question)"
          >
            <span class="rag-question__id">{{ question.id }}</span>
            <span class="rag-question__text">{{ question.question }}</span>
          </button>
        </div>
      </section>
    </div>

    <div class="rag-review-layout">
      <section class="control-panel rag-search-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Search</span>
            <h2 class="control-panel__title">Retrieval preview</h2>
          </div>
          <span class="control-pill">{{ searchLimitLabel }}</span>
        </div>

        <form class="rag-searchbar" @submit.prevent="runSearch">
          <textarea
            v-model="query"
            class="control-input rag-searchbar__query"
            rows="2"
            placeholder="输入检索问题"
          />
          <label class="rag-field rag-field--compact">
            <span>Top K</span>
            <input v-model.number="topK" class="control-input control-input--narrow" type="number" min="1" max="20" />
          </label>
          <button class="btn btn--primary" type="submit" :disabled="searching || !query.trim()">
            <Icon name="search" :size="16" />
            <span>{{ searching ? 'Searching' : 'Search' }}</span>
          </button>
        </form>

        <ErrorState v-if="error && status" :message="error" :on-retry="refreshAll" />
        <div v-else-if="searching" class="control-empty">
          <LoadingSpinner />
        </div>
        <div v-else-if="results.length === 0" class="control-empty rag-search-empty">
          <Icon class="control-empty__icon" name="search" :size="28" />
          <div class="control-empty__title">No search yet</div>
          <div class="control-empty__hint">Select a golden query or submit a question.</div>
        </div>
        <div v-else class="rag-results">
          <div class="rag-inspect">
            <div>
              <strong>{{ results.length }} chunk matches</strong>
              <small>{{ searchMeta }}</small>
            </div>
            <span class="control-pill">{{ sourceLabel }}</span>
          </div>

          <article
            v-for="(result, index) in results"
            :key="result.chunkId"
            class="rag-result control-card"
            :class="{ 'control-card--selected': result.chunkId === selectedChunkId }"
          >
            <div class="rag-result__rank">#{{ index + 1 }}</div>
            <div class="rag-result__body">
              <div class="rag-result__topline">
                <span class="control-pill control-pill--accent">chunk</span>
                <span class="control-pill">{{ result.languageBucket || 'text' }}</span>
                <span class="control-pill">{{ result.chunkingStrategy || 'chunker' }}</span>
                <span class="rag-result__score">
                  lexical {{ fixed(result.score) }}
                </span>
              </div>

              <button class="rag-result__title" type="button" @click="toggleResult(result)">
                {{ result.title || result.documentId }}
              </button>
              <div class="rag-result__path">{{ result.sourcePath || result.source }}</div>
              <p class="rag-result__preview">{{ result.snippet }}</p>

              <div class="rag-result__meta">
                <span><strong>Citation</strong>{{ result.citation }}</span>
                <span><strong>Source</strong>{{ result.source }}</span>
                <span><strong>Retrieval</strong>{{ result.retrievalProfile || retrievalProfile }}</span>
                <span v-if="result.pageStart"><strong>Page</strong>{{ result.pageStart }}</span>
                <span v-if="result.bm25Rank !== null && result.bm25Rank !== undefined">
                  <strong>BM25</strong>{{ fixed(result.bm25Rank) }}
                </span>
                <span><strong>Chunk</strong>{{ shortId(result.chunkId) }}</span>
              </div>

              <div class="rag-result__actions">
                <button
                  class="btn btn--ghost"
                  type="button"
                  :disabled="detailLoadingId === result.chunkId"
                  @click="toggleResult(result)"
                >
                  <Icon :name="result.chunkId === selectedChunkId ? 'chevronDown' : 'chevronRight'" :size="16" />
                  <span>{{ result.chunkId === selectedChunkId ? 'Hide chunk' : 'Show chunk' }}</span>
                </button>
              </div>

              <div v-if="detailLoadingId === result.chunkId" class="rag-expanded">
                <div class="rag-expanded__head">
                  <strong>Chunk detail</strong>
                  <span class="control-pill control-pill--warn">Loading</span>
                </div>
                <div class="rag-expanded__loading">
                  <LoadingSpinner />
                </div>
              </div>

              <div v-else-if="selectedDetail && selectedDetail.chunkId === result.chunkId" class="rag-expanded">
                <div class="rag-expanded__head">
                  <strong>Chunk detail</strong>
                  <span class="control-pill">{{ selectedDetail.citation }}</span>
                </div>
                <pre>{{ selectedDetail.text }}</pre>
                <div v-if="selectedDetail.lineage?.length" class="rag-lineage">
                  <span
                    v-for="step in selectedDetail.lineage"
                    :key="`${selectedDetail.chunkId}-${step.stepOrdinal}`"
                    class="control-pill"
                  >
                    {{ step.stepOrdinal }} · {{ step.operation }}
                  </span>
                </div>
              </div>
            </div>
          </article>
        </div>
      </section>

      <aside class="control-panel rag-evidence-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Review</span>
            <h2 class="control-panel__title">Evidence judgment</h2>
          </div>
          <button class="btn btn--ghost" type="button" :disabled="!selectedDetail" @click="clearSelection">
            <Icon name="x" :size="16" />
            <span>Clear</span>
          </button>
        </div>

        <div v-if="selectedDetail" class="rag-evidence">
          <strong>{{ selectedDetail.title }}</strong>
          <small>{{ selectedDetail.citation }}</small>
          <pre>{{ selectedDetail.text }}</pre>
          <div v-if="selectedDetail.lineage?.length" class="rag-lineage">
            <span
              v-for="step in selectedDetail.lineage"
              :key="`${selectedDetail.chunkId}-aside-${step.stepOrdinal}`"
              class="control-pill"
            >
              {{ step.operation }}
            </span>
          </div>
        </div>
        <div v-else class="control-empty rag-evidence-empty">
          <Icon class="control-empty__icon" name="fileText" :size="28" />
          <div class="control-empty__title">No evidence selected</div>
          <div class="control-empty__hint">Open a result chunk before saving a judgment.</div>
        </div>

        <form class="rag-judge" @submit.prevent="saveJudgment">
          <label class="rag-field">
            <span>答案/检索质量</span>
            <select v-model="judgment.rating" class="control-input">
              <option value="correct">正确</option>
              <option value="partial">部分正确</option>
              <option value="wrong">错误</option>
            </select>
          </label>
          <label class="rag-field">
            <span>证据</span>
            <select v-model="judgment.evidence" class="control-input">
              <option value="supported">证据充分</option>
              <option value="weak">证据不足</option>
              <option value="missing">无证据</option>
            </select>
          </label>
          <label class="rag-field">
            <span>幻觉</span>
            <select v-model="judgment.hallucination" class="control-input">
              <option value="none">无幻觉</option>
              <option value="possible">可能有</option>
              <option value="yes">有幻觉</option>
            </select>
          </label>
          <label class="rag-field">
            <span>备注</span>
            <textarea v-model="judgment.notes" class="control-input rag-judge__notes" rows="3" />
          </label>
          <button class="btn btn--primary" type="submit" :disabled="savingJudgment || !query.trim()">
            <Icon name="save" :size="16" />
            <span>{{ savingJudgment ? 'Saving' : 'Save judgment' }}</span>
          </button>
        </form>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ErrorState from '@/components/ErrorState.vue'
import Icon from '@/components/Icon.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useRpcStore } from '@/stores/rpc'

interface KnowledgeStatus {
  rootDir: string
  documentsIndexed: number
  chunksIndexed: number
  filesIndexed?: number
  pipeline?: string
  indexProfiles?: string[]
  latestJob?: {
    status: string
    filesSeen: number
    filesReady: number
    filesFailed: number
  }
}

interface KnowledgeQuestion {
  id: string
  question: string
  expectedDocIds?: string[]
  expectedEvidenceHint?: string
}

interface KnowledgeResult {
  evidenceId: string
  documentId: string
  chunkId: string
  title: string
  source: string
  sourcePath: string
  pageStart: number | null
  pageEnd: number | null
  section: string | null
  snippet: string
  score: number
  bm25Rank?: number | null
  rankPosition?: number
  citation: string
  languageBucket: string
  pairId?: string | null
  collectionId?: string
  retrievalProfile?: string
  chunkingStrategy?: string | null
}

interface KnowledgeDetail {
  chunkId: string
  documentId: string
  collectionId?: string
  title: string
  text: string
  citation: string
  preprocessorStrategy?: string | null
  chunkingStrategy?: string | null
  lineage?: Array<{
    stepOrdinal: number
    operation: string
    reversible: boolean
  }>
}

const rpc = useRpcStore()
const sourceRoot = ref('/mnt/data/datasets')
const collectionName = ref('default')
const retrievalProfile = ref('sqlite_fts5_default')
const sampleLimit = ref(30)
const topK = ref(8)
const query = ref('')
const status = ref<KnowledgeStatus | null>(null)
const questions = ref<KnowledgeQuestion[]>([])
const results = ref<KnowledgeResult[]>([])
const selectedDetail = ref<KnowledgeDetail | null>(null)
const selectedChunkId = computed(() => selectedDetail.value?.chunkId || '')
const activeQuestionId = ref('')
const toolNames = ref<string[]>([])
const error = ref('')
const loading = ref(false)
const preparing = ref(false)
const searching = ref(false)
const questionsLoading = ref(false)
const savingJudgment = ref(false)
const detailLoadingId = ref('')
const judgmentPath = ref('')

const judgment = reactive({
  rating: 'correct',
  evidence: 'supported',
  hallucination: 'none',
  notes: '',
})

const toolCount = computed(() => toolNames.value.filter((name) => name.startsWith('knowledge_')).length)
const hasIndex = computed(() => Number(status.value?.chunksIndexed || 0) > 0)
const sourceLabel = computed(() => basename(status.value?.rootDir || sourceRoot.value) || 'local')
const searchLimitLabel = computed(() => `top ${Number(topK.value || 0) || 8}`)
const activeIndexProfile = computed(() => status.value?.indexProfiles?.[0] || retrievalProfile.value)
const latestJobHint = computed(() => {
  const job = status.value?.latestJob
  if (!job) return 'Analyzed files'
  return `${job.status}: ${formatCount(job.filesReady)}/${formatCount(job.filesSeen)} ready`
})

const statusMetrics = computed(() => [
  {
    label: 'RAG',
    value: hasIndex.value ? 'Ready' : 'Pending',
    hint: 'Local tool source',
    className: hasIndex.value ? 'control-stat--accent' : 'control-stat--warn',
  },
  {
    label: 'Files',
    value: formatCount(status.value?.filesIndexed),
    hint: latestJobHint.value,
    className: '',
  },
  {
    label: 'Chunks',
    value: formatCount(status.value?.chunksIndexed),
    hint: 'Retrievable evidence',
    className: hasIndex.value ? 'control-stat--accent' : '',
  },
  {
    label: 'Questions',
    value: formatCount(questions.value.length),
    hint: 'Evaluation prompts',
    className: '',
  },
  {
    label: 'Tools',
    value: formatCount(toolCount.value),
    hint: 'Agent callable',
    className: toolCount.value > 0 ? 'control-stat--accent' : 'control-stat--warn',
  },
  {
    label: 'Index',
    value: activeIndexProfile.value.replace('sqlite_', '').toUpperCase(),
    hint: status.value?.pipeline || 'Local SQLite store',
    className: '',
  },
])

const searchMeta = computed(() => {
  const parts = [
    query.value.trim(),
    `${results.value.length} results`,
    searchLimitLabel.value,
  ]
  return parts.filter(Boolean).join(' · ')
})

async function refreshAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadStatus(), loadQuestions(), loadTools()])
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    loading.value = false
  }
}

async function loadStatus(): Promise<void> {
  await rpc.waitForConnection()
  status.value = await rpc.call<KnowledgeStatus>('knowledge.status', {})
}

async function loadQuestions(): Promise<void> {
  questionsLoading.value = true
  try {
    await rpc.waitForConnection()
    const payload = await rpc.call<{ questions: KnowledgeQuestion[] }>('knowledge.questions', {})
    questions.value = payload.questions || []
  } finally {
    questionsLoading.value = false
  }
}

async function loadTools(): Promise<void> {
  await rpc.waitForConnection()
  const payload = await rpc.call<{ tools: Array<{ name: string }> }>('tools.catalog', {})
  toolNames.value = (payload.tools || []).map((tool) => tool.name)
}

async function prepareSample(): Promise<void> {
  preparing.value = true
  error.value = ''
  judgmentPath.value = ''
  try {
    await rpc.waitForConnection()
    await rpc.call('knowledge.ingest', {
      sourceRoot: sourceRoot.value,
      limit: Number(sampleLimit.value || 30),
      collectionName: collectionName.value || 'default',
      collectionId: 'default',
      indexProfiles: [retrievalProfile.value],
    })
    await refreshAll()
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    preparing.value = false
  }
}

function selectQuestion(question: KnowledgeQuestion): void {
  activeQuestionId.value = question.id
  query.value = question.question
  void runSearch()
}

async function runSearch(): Promise<void> {
  const cleanQuery = query.value.trim()
  if (!cleanQuery) return
  searching.value = true
  error.value = ''
  selectedDetail.value = null
  try {
    await rpc.waitForConnection()
    const payload = await rpc.call<{ results: KnowledgeResult[] }>('knowledge.search', {
      query: cleanQuery,
      topK: Number(topK.value || 8),
      collectionId: 'default',
      retrievalProfile: retrievalProfile.value,
    })
    results.value = payload.results || []
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    searching.value = false
  }
}

async function toggleResult(result: KnowledgeResult): Promise<void> {
  if (selectedDetail.value?.chunkId === result.chunkId) {
    selectedDetail.value = null
    return
  }
  await openResult(result)
}

async function openResult(result: KnowledgeResult): Promise<void> {
  detailLoadingId.value = result.chunkId
  error.value = ''
  try {
    await rpc.waitForConnection()
    selectedDetail.value = await rpc.call<KnowledgeDetail>('knowledge.get', {
      chunkId: result.chunkId,
    })
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    detailLoadingId.value = ''
  }
}

function clearSelection(): void {
  selectedDetail.value = null
}

async function saveJudgment(): Promise<void> {
  savingJudgment.value = true
  error.value = ''
  try {
    await rpc.waitForConnection()
    const payload = await rpc.call<{ path: string }>('knowledge.judgment', {
      questionId: activeQuestionId.value,
      question: query.value,
      rating: judgment.rating,
      evidence: judgment.evidence,
      hallucination: judgment.hallucination,
      notes: judgment.notes,
      selectedChunkId: selectedDetail.value?.chunkId || null,
      results: results.value.slice(0, 5),
    })
    judgmentPath.value = payload.path
  } catch (err) {
    error.value = messageFromError(err)
  } finally {
    savingJudgment.value = false
  }
}

function basename(path: string): string {
  const raw = String(path || '').replace(/\/+$/, '')
  return raw.split('/').filter(Boolean).pop() || raw
}

function shortId(value?: string): string {
  const raw = String(value || '')
  if (!raw) return ''
  return raw.length > 16 ? `${raw.slice(0, 12)}...` : raw
}

function fixed(value: unknown): string {
  return Number(value || 0).toFixed(3)
}

function formatCount(value: unknown): string {
  return new Intl.NumberFormat().format(Number(value || 0))
}

function messageFromError(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

onMounted(() => {
  void refreshAll()
})
</script>

<style scoped>
.rag-stage {
  gap: var(--sp-4);
}

.rag-stat-row {
  --control-stat-min: 150px;
}

.rag-stat {
  min-height: 116px;
}

.rag-workbench,
.rag-review-layout {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
}

.rag-form-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.rag-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.rag-field--wide {
  grid-column: 1 / -1;
}

.rag-field--compact {
  width: 104px;
}

.rag-field span {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 600;
}

.rag-field .control-input,
.rag-searchbar .control-input,
.rag-judge .control-input {
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

.rag-source-summary div {
  min-width: 0;
}

.rag-source-summary strong,
.rag-source-summary small {
  display: block;
}

.rag-source-summary strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-source-summary small {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-panel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.rag-question-list {
  display: grid;
  gap: var(--sp-2);
  max-height: 330px;
  overflow: auto;
  padding-right: 2px;
}

.rag-question {
  align-items: flex-start;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: 52px minmax(0, 1fr);
  padding: var(--sp-3);
  text-align: left;
  transition: background var(--transition), border-color var(--transition);
}

.rag-question:hover,
.rag-question.is-active {
  background: var(--bg-hover);
  border-color: var(--accent);
}

.rag-question__id {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.rag-question__text {
  font-size: var(--fs-sm);
  line-height: 1.45;
  min-width: 0;
  overflow-wrap: anywhere;
}

.rag-searchbar {
  align-items: end;
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: minmax(0, 1fr) 104px auto;
}

.rag-searchbar__query {
  min-height: 76px;
  resize: vertical;
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

.rag-result__title {
  background: transparent;
  border: 0;
  color: var(--text);
  cursor: pointer;
  display: block;
  font: inherit;
  font-size: var(--fs-md);
  font-weight: 700;
  letter-spacing: 0;
  margin: var(--sp-3) 0 2px;
  padding: 0;
  text-align: left;
  width: 100%;
}

.rag-result__title:hover {
  color: var(--accent);
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
  overflow-wrap: anywhere;
}

.rag-result__meta {
  margin-bottom: var(--sp-3);
}

.rag-result__meta span {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  max-width: 100%;
  overflow: hidden;
  padding: 4px 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-result__meta strong {
  color: var(--text);
  margin-right: 5px;
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

.rag-expanded pre,
.rag-evidence pre {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.55;
  margin: 0;
  overflow: auto;
  padding: var(--sp-3);
  white-space: pre-wrap;
  word-break: break-word;
}

.rag-expanded pre {
  max-height: 420px;
}

.rag-expanded__loading {
  padding: var(--sp-4);
}

.rag-lineage {
  align-items: center;
  border-top: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  padding: var(--sp-3);
}

.rag-evidence {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.rag-evidence strong,
.rag-evidence small {
  display: block;
  padding-inline: var(--sp-3);
}

.rag-evidence strong {
  padding-top: var(--sp-3);
}

.rag-evidence small {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-evidence pre {
  max-height: 360px;
}

.rag-evidence-empty {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.rag-judge {
  border-top: 1px solid var(--border);
  display: grid;
  gap: var(--sp-3);
  padding-top: var(--sp-3);
}

.rag-judge__notes {
  resize: vertical;
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
  overflow-wrap: anywhere;
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

@media (max-width: 1180px) {
  .rag-stat-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .rag-workbench,
  .rag-review-layout {
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

  .rag-field--compact {
    width: 100%;
  }

  .rag-source-summary,
  .rag-inspect,
  .rag-job__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .rag-result__score {
    margin-left: 0;
  }
}

@media (max-width: 520px) {
  .rag-stat-row {
    grid-template-columns: 1fr;
  }
}
</style>
