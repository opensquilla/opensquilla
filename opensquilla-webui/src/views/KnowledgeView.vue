<template>
  <div class="rag-provider control-stage control-stage--spacious">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <h1 class="control-stage__title">RAG Provider</h1>
        <p class="control-stage__subtitle">外部知识检索连接状态、协议能力与合同测试</p>
      </div>
      <button class="btn btn--ghost" type="button" :disabled="loading" @click="loadStatus">
        {{ loading ? '刷新中' : '刷新状态' }}
      </button>
    </header>

    <p v-if="error" class="rag-provider__error" role="alert">{{ error }}</p>

    <section class="control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 4">
      <article class="control-stat control-stat--static">
        <span class="control-stat__label">连接状态</span>
        <strong data-testid="rag-state" class="control-stat__value">{{ status?.connectionState || '—' }}</strong>
        <span class="control-stat__hint">{{ stateHint }}</span>
      </article>
      <article class="control-stat control-stat--static">
        <span class="control-stat__label">Provider</span>
        <strong class="control-stat__value">{{ status?.provider?.name || '—' }}</strong>
        <span class="control-stat__hint">{{ providerIdentity }}</span>
      </article>
      <article class="control-stat control-stat--static">
        <span class="control-stat__label">协议</span>
        <strong class="control-stat__value">{{ status?.protocolVersion || '—' }}</strong>
        <span class="control-stat__hint">search {{ capabilityLabel(status?.capabilities?.search) }} · get {{ capabilityLabel(status?.capabilities?.get) }}</span>
      </article>
      <article class="control-stat control-stat--static">
        <span class="control-stat__label">上次成功</span>
        <strong class="control-stat__value">{{ lastSuccess }}</strong>
        <span class="control-stat__hint">失败计数 {{ status?.consecutiveFailures ?? 0 }}</span>
      </article>
    </section>

    <section v-if="status?.warning" class="control-panel rag-provider__warning" role="status">
      {{ status.warning }}
    </section>

    <div class="rag-provider__grid">
      <section class="control-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Capabilities</span>
            <h2 class="control-panel__title">生效能力与预算</h2>
          </div>
          <a
            v-if="status?.links.management"
            class="btn btn--ghost"
            :href="status.links.management"
            target="_blank"
            rel="noopener noreferrer"
          >打开 Provider 管理页面</a>
        </div>
        <dl class="rag-provider__details">
          <div><dt>Search 数量</dt><dd>{{ status?.effectiveLimits?.maxSearchResults ?? '—' }}</dd></div>
          <div><dt>Snippet 字符</dt><dd>{{ status?.effectiveLimits?.maxSnippetChars ?? '—' }}</dd></div>
          <div><dt>Search 总字符</dt><dd>{{ status?.effectiveLimits?.maxSearchResponseChars ?? '—' }}</dd></div>
          <div><dt>Get 正文字符</dt><dd>{{ status?.effectiveLimits?.maxGetContentChars ?? '—' }}</dd></div>
          <div><dt>Collection scope</dt><dd>{{ scopeLabel }}</dd></div>
          <div><dt>Profile override</dt><dd>{{ status?.retrievalProfileOverride || 'Provider 默认' }}</dd></div>
          <div><dt>Provider 默认 profile</dt><dd>{{ status?.searchOptions?.defaultRetrievalProfile || '—' }}</dd></div>
          <div><dt>最近错误</dt><dd>{{ status?.lastErrorCode || '无' }}</dd></div>
        </dl>
      </section>

      <section class="control-panel">
        <div class="control-panel__head">
          <div>
            <span class="control-panel__eyebrow">Contract test</span>
            <h2 class="control-panel__title">测试检索</h2>
          </div>
        </div>
        <form class="rag-provider__search" @submit.prevent="search">
          <textarea
            v-model="query"
            data-testid="rag-query"
            class="control-input"
            rows="3"
            placeholder="输入要发送给 knowledge.search 的查询"
          />
          <label>
            <span>Limit</span>
            <input v-model.number="limit" class="control-input" type="number" min="1" max="20" />
          </label>
          <button
            data-testid="rag-search"
            class="btn btn--primary"
            type="submit"
            :disabled="searching || !canSearch || !query.trim()"
          >{{ searching ? '检索中' : '执行检索' }}</button>
        </form>
        <p v-if="searchResponse" class="rag-provider__summary">
          返回 {{ searchResponse.returnedCount }} 条
          <template v-if="searchResponse.totalMatched !== null"> · 匹配 {{ searchResponse.totalMatched }} 条</template>
          <template v-if="searchResponse.resultsTruncated"> · Provider 已截断</template>
          <template v-if="searchResponse.providerBudgetViolation"> · OpenSquilla 已执行预算裁剪</template>
        </p>
        <div class="rag-provider__results">
          <article v-for="item in searchResponse?.results || []" :key="item.evidenceId" class="control-card">
            <strong>{{ item.citation.title }}</strong>
            <small>{{ item.citation.source || item.citation.locator || item.evidenceId }}</small>
            <p>{{ item.snippet }}<span v-if="item.snippetTruncated">…</span></p>
            <button class="btn btn--ghost" type="button" :disabled="reading || !status?.capabilities?.get" @click="readEvidence(item.evidenceId, null)">
              读取原文
            </button>
          </article>
        </div>
      </section>
    </div>

    <section v-if="getResponse" class="control-panel rag-provider__reader">
      <div class="control-panel__head">
        <div>
          <span class="control-panel__eyebrow">Evidence</span>
          <h2 class="control-panel__title">{{ getResponse.document.title }}</h2>
        </div>
        <span>{{ getResponse.citation.locator || getResponse.document.source }}</span>
      </div>
      <p v-if="getResponse.legacyLimitedGet" class="rag-provider__warning">Legacy 模式只保证旧 chunk 内容，不代表完整全文。</p>
      <pre data-testid="rag-content" class="rag-provider__content">{{ getResponse.content }}</pre>
      <div class="rag-provider__pager">
        <button class="btn btn--ghost" type="button" :disabled="reading || !getResponse.previousCursor" @click="readEvidence(getResponse.evidenceId, getResponse.previousCursor)">上一页</button>
        <button class="btn btn--ghost" type="button" :disabled="reading || !getResponse.nextCursor" @click="readEvidence(getResponse.evidenceId, getResponse.nextCursor)">下一页</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import {
  normalizeRagGetResponse,
  normalizeRagProviderStatus,
  normalizeRagSearchResponse,
  type RagGetResponse,
  type RagProviderStatus,
  type RagSearchResponse,
} from './ragProvider'

const rpc = useRpcStore()
const status = ref<RagProviderStatus | null>(null)
const searchResponse = ref<RagSearchResponse | null>(null)
const getResponse = ref<RagGetResponse | null>(null)
const loading = ref(false)
const searching = ref(false)
const reading = ref(false)
const error = ref('')
const query = ref('')
const limit = ref(8)

const canSearch = computed(() => status.value?.connectionState === 'READY' || status.value?.connectionState === 'LEGACY')
const providerIdentity = computed(() => {
  const provider = status.value?.provider
  return provider ? `${provider.version} · ${provider.instanceId}` : '尚未发现兼容 Provider'
})
const scopeLabel = computed(() => status.value?.collectionScope.length ? status.value.collectionScope.join(', ') : '未限制')
const lastSuccess = computed(() => {
  const value = status.value?.lastSuccessAt
  return value ? new Date(value * 1000).toLocaleString() : '—'
})
const stateHint = computed(() => {
  switch (status.value?.connectionState) {
    case 'READY': return '标准协议可用，工具已注册'
    case 'DEGRADED': return '短暂故障，工具保留但调用会安全失败'
    case 'UNAVAILABLE': return 'Provider 不可用，工具已注销'
    case 'INCOMPATIBLE': return '协议主版本不兼容'
    case 'CONNECTING': return '正在发现能力'
    case 'LEGACY': return '显式旧版兼容模式'
    default: return '默认关闭，不建立网络连接'
  }
})

function capabilityLabel(value: boolean | undefined): string {
  return value === true ? '可用' : '不可用'
}

function message(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    await rpc.waitForConnection()
    const normalized = normalizeRagProviderStatus(await rpc.call('knowledge.status', {}))
    if (!normalized) throw new Error('Invalid RAG Provider status response')
    status.value = normalized
  } catch (value) {
    status.value = null
    error.value = message(value)
  } finally {
    loading.value = false
  }
}

async function search() {
  const clean = query.value.trim()
  if (!clean || !canSearch.value) return
  searching.value = true
  error.value = ''
  try {
    const boundedLimit = Math.min(20, Math.max(1, Number(limit.value) || 8))
    const normalized = normalizeRagSearchResponse(
      await rpc.call('knowledge.search', { query: clean, limit: boundedLimit }),
    )
    if (!normalized) throw new Error('Invalid RAG Provider search response')
    searchResponse.value = normalized
    getResponse.value = null
  } catch (value) {
    error.value = message(value)
  } finally {
    searching.value = false
  }
}

async function readEvidence(evidenceId: string, cursor: string | null) {
  reading.value = true
  error.value = ''
  try {
    const params: { evidenceId: string; cursor?: string } = { evidenceId }
    if (cursor) params.cursor = cursor
    const normalized = normalizeRagGetResponse(await rpc.call('knowledge.get', params))
    if (!normalized) throw new Error('Invalid RAG Provider get response')
    getResponse.value = normalized
  } catch (value) {
    error.value = message(value)
  } finally {
    reading.value = false
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.rag-provider { display: grid; gap: var(--space-4); }
.rag-provider__grid { display: grid; grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr); gap: var(--space-4); }
.rag-provider__details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.rag-provider__details div { padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); }
.rag-provider__details dt { color: var(--text-muted); font-size: var(--font-size-xs); }
.rag-provider__details dd { margin: var(--space-1) 0 0; overflow-wrap: anywhere; }
.rag-provider__search { display: grid; grid-template-columns: minmax(0, 1fr) 6rem auto; align-items: end; gap: var(--space-3); }
.rag-provider__search label { display: grid; gap: var(--space-1); }
.rag-provider__results { display: grid; gap: var(--space-3); margin-top: var(--space-3); }
.rag-provider__results article { display: grid; gap: var(--space-2); }
.rag-provider__results small, .rag-provider__summary { color: var(--text-muted); }
.rag-provider__content { max-height: 32rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.rag-provider__pager { display: flex; justify-content: flex-end; gap: var(--space-2); }
.rag-provider__error, .rag-provider__warning { color: var(--status-warning-text); }
@media (max-width: 900px) {
  .rag-provider__grid { grid-template-columns: 1fr; }
  .rag-provider__search { grid-template-columns: 1fr; }
  .rag-provider__details { grid-template-columns: 1fr; }
}
</style>
