<template>
  <section class="rag-search-workspace">
    <form class="rag-search-composer control-panel" @submit.prevent="emit('search')">
      <label for="rag-query">{{ t('rag.search.title') }}</label>
      <textarea
        id="rag-query"
        class="control-input"
        :value="props.query"
        data-testid="rag-query"
        rows="4"
        :placeholder="t('rag.search.placeholder')"
        @input="emit('update:query', ($event.target as HTMLTextAreaElement).value)"
        @keydown="onQueryKeydown"
      />
      <details>
        <summary>{{ t('rag.search.advanced') }}</summary>
        <label class="rag-search-composer__limit">
          {{ t('rag.search.limit') }}
          <input
            class="control-input"
            :value="props.limit"
            type="number"
            min="1"
            max="20"
            @input="emit('update:limit', Number(($event.target as HTMLInputElement).value))"
          />
        </label>
      </details>
      <button
        data-testid="rag-search"
        class="btn btn--primary rag-search-composer__submit"
        type="submit"
        :disabled="props.searching || !props.canSearch || !props.query.trim()"
      >
        {{ props.searching ? t('rag.search.searching') : t('rag.search.submit') }}
      </button>
    </form>

    <p
      v-if="props.searchError"
      data-testid="rag-search-error"
      class="rag-search-workspace__error"
      role="alert"
    >
      {{ props.searchError }}
    </p>

    <div class="rag-workspace" :class="{ 'is-reader-open': props.mobileReaderOpen }">
      <section class="rag-results control-panel" :aria-label="t('rag.results.title')">
        <h2 class="control-panel__title">{{ t('rag.results.title') }}</h2>
        <p v-if="props.searchResponse" class="rag-results__summary" aria-live="polite">
          {{ t('rag.results.returned', { count: props.searchResponse.returnedCount }) }}
          <template v-if="props.searchResponse.totalMatched !== null">
            · {{ t('rag.results.matched', { count: props.searchResponse.totalMatched }) }}
          </template>
          <span
            v-if="props.searchResponse.resultsTruncated"
            class="control-pill control-pill--warn"
          >
            {{ t('rag.results.truncated') }}
          </span>
          <span
            v-if="props.searchResponse.providerBudgetViolation"
            class="control-pill control-pill--warn"
          >
            {{ t('rag.results.budgetTrimmed') }}
          </span>
          <span
            v-if="props.searchResponse.retrievalProfile !== null"
            class="control-pill"
            :class="{ 'control-pill--warn': profileDiffers }"
          >
            {{ t('rag.results.providerExecutedProfile', {
              profile: props.searchResponse.retrievalProfile,
            }) }}
          </span>
        </p>
        <div v-if="!props.searchResponse" class="state">
          {{ t('rag.results.empty') }}
        </div>
        <div class="rag-results__list">
          <article
            v-for="item in props.searchResponse?.results || []"
            :key="item.evidenceId"
            class="rag-result"
            :data-result-id="item.evidenceId"
          >
            <button
              type="button"
              class="control-card control-card--interactive rag-result-card"
              :class="{ 'control-card--selected': item.evidenceId === props.selectedEvidenceId }"
              :data-evidence-id="item.evidenceId"
              @click="emit('select', item.evidenceId)"
            >
              <strong class="rag-result-card__title">{{ resultTitle(item) }}</strong>
              <small
                v-if="secondaryDocumentTitle(item)"
                class="rag-result-card__document-title"
              >
                {{ secondaryDocumentTitle(item) }}
              </small>
              <small class="rag-result-card__metadata">
                <span v-if="item.rank !== null">#{{ item.rank }}</span>
                <span v-if="item.document?.sourcePath">
                  {{ t('rag.results.sourcePath') }}: {{ item.document.sourcePath }}
                </span>
                <span v-if="item.document?.source || item.citation.source">
                  {{ item.document?.source || item.citation.source }}
                </span>
                <span v-if="item.citation.locator">{{ item.citation.locator }}</span>
              </small>
              <span class="rag-result-card__snippet">{{ item.snippet }}</span>
              <span v-if="item.snippetTruncated" class="control-pill">
                {{ t('rag.results.snippetTruncated') }}
              </span>
            </button>
            <details
              v-if="item.chunk"
              data-testid="rag-complete-chunk"
              class="rag-result__complete"
            >
              <summary>{{ t('rag.results.completeChunk') }}</summary>
              <small>{{ t('rag.results.chunkCharacters', {
                count: item.chunk.contentChars,
              }) }}</small>
              <article>{{ item.chunk.content }}</article>
            </details>
          </article>
        </div>
      </section>

      <section
        ref="reader"
        class="rag-reader control-panel"
        :class="{ 'is-mobile-open': props.mobileReaderOpen }"
        :aria-label="t('rag.reader.title')"
      >
        <button
          class="btn btn--ghost rag-reader__back"
          type="button"
          @click="emit('closeReader')"
        >
          {{ t('rag.reader.backToResults') }}
        </button>

        <div v-if="props.reading" role="status" aria-live="polite">
          {{ t('rag.reader.loading') }}
        </div>
        <p
          v-if="props.readError"
          data-testid="rag-reader-error"
          class="rag-search-workspace__error"
          role="alert"
        >
          {{ props.readError }}
        </p>
        <div v-if="!props.getResponse && !props.reading" class="state">
          {{ t('rag.reader.empty') }}
        </div>
        <template v-if="props.getResponse">
          <header>
            <h2 class="control-panel__title">{{ readerTitle }}</h2>
            <p v-if="readerSecondaryTitle">{{ readerSecondaryTitle }}</p>
            <dl class="rag-reader__metadata">
              <div v-if="props.getResponse.document.fileName">
                <dt>{{ t('rag.results.fileName') }}</dt>
                <dd>{{ props.getResponse.document.fileName }}</dd>
              </div>
              <div v-if="props.getResponse.document.sourcePath">
                <dt>{{ t('rag.results.sourcePath') }}</dt>
                <dd>{{ props.getResponse.document.sourcePath }}</dd>
              </div>
              <div v-if="props.getResponse.document.source">
                <dt>source</dt>
                <dd>{{ props.getResponse.document.source }}</dd>
              </div>
              <div v-if="props.getResponse.document.mediaType">
                <dt>mediaType</dt>
                <dd>{{ props.getResponse.document.mediaType }}</dd>
              </div>
              <div v-if="props.getResponse.document.revision">
                <dt>revision</dt>
                <dd>{{ props.getResponse.document.revision }}</dd>
              </div>
              <div v-if="props.getResponse.citation.locator">
                <dt>locator</dt>
                <dd>{{ props.getResponse.citation.locator }}</dd>
              </div>
              <div v-if="props.getResponse.contentChars !== null">
                <dt>contentChars</dt>
                <dd>{{ t('rag.results.chunkCharacters', {
                  count: props.getResponse.contentChars,
                }) }}</dd>
              </div>
              <div><dt>{{ t('rag.reader.previous') }}</dt><dd>{{ props.getResponse.previousCursor || '—' }}</dd></div>
              <div><dt>{{ t('rag.reader.next') }}</dt><dd>{{ props.getResponse.nextCursor || '—' }}</dd></div>
            </dl>
          </header>
          <p v-if="props.getResponse.legacyLimitedGet" class="rag-reader__warning">
            {{ t('rag.reader.legacyLimited') }}
          </p>
          <article class="rag-reader__content">
            {{ props.getResponse.content }}
          </article>
          <footer class="rag-reader__pager">
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="props.reading || !props.getResponse.previousCursor"
              @click="props.getResponse.previousCursor && emit(
                'page',
                props.getResponse.evidenceId,
                props.getResponse.previousCursor,
              )"
            >
              {{ t('rag.reader.previous') }}
            </button>
            <button
              data-testid="rag-next-segment"
              type="button"
              class="btn btn--ghost"
              :disabled="props.reading || !props.getResponse.nextCursor"
              @click="props.getResponse.nextCursor && emit(
                'page',
                props.getResponse.evidenceId,
                props.getResponse.nextCursor,
              )"
            >
              {{ t('rag.reader.next') }}
            </button>
          </footer>
        </template>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type {
  RagGetResponse,
  RagSearchResponse,
  RagSearchResult,
} from '@/views/ragProvider'

const props = defineProps<{
  query: string
  limit: number
  canSearch: boolean
  searching: boolean
  searchError: string
  searchResponse: RagSearchResponse | null
  selectedEvidenceId: string | null
  getResponse: RagGetResponse | null
  reading: boolean
  readError: string
  mobileReaderOpen: boolean
  expectedRetrievalProfile: string | null
}>()

const emit = defineEmits<{
  'update:query': [value: string]
  'update:limit': [value: number]
  search: []
  select: [evidenceId: string]
  page: [evidenceId: string, cursor: string]
  closeReader: []
}>()

const { t } = useI18n()
const reader = ref<HTMLElement | null>(null)
const profileDiffers = computed(() => (
  props.searchResponse?.retrievalProfile !== null
  && props.searchResponse?.retrievalProfile !== props.expectedRetrievalProfile
))
const readerTitle = computed(() => (
  props.getResponse?.document.fileName
  ?? props.getResponse?.document.title
  ?? ''
))
const readerSecondaryTitle = computed(() => {
  const document = props.getResponse?.document
  if (!document?.fileName || document.fileName === document.title) return ''
  return document.title
})

function resultTitle(item: RagSearchResult): string {
  return item.document?.fileName ?? item.document?.title ?? item.citation.title
}

function secondaryDocumentTitle(item: RagSearchResult): string {
  if (!item.document?.fileName || item.document.fileName === item.document.title) return ''
  return item.document.title
}

function onQueryKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || (!event.metaKey && !event.ctrlKey)) return
  event.preventDefault()
  if (props.canSearch && !props.searching && props.query.trim()) emit('search')
}

watch(() => props.getResponse?.content, async () => {
  await nextTick()
  if (reader.value) reader.value.scrollTop = 0
})
</script>

<style scoped>
.rag-search-workspace {
  display: grid;
  gap: var(--sp-4);
}

.rag-search-composer label,
.rag-search-composer__limit {
  display: grid;
  gap: var(--sp-2);
}

.rag-search-composer textarea {
  min-height: 7rem;
  resize: vertical;
}

.rag-search-composer summary {
  color: var(--text-muted);
  cursor: pointer;
}

.rag-search-composer__limit {
  margin-top: var(--sp-3);
  max-width: 12rem;
}

.rag-search-composer__submit {
  justify-self: start;
}

.rag-search-workspace__error,
.rag-reader__warning {
  color: var(--warn);
  margin: 0;
}

.rag-workspace {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: minmax(280px, 0.42fr) minmax(0, 0.58fr);
  min-height: 34rem;
}

.rag-results,
.rag-reader {
  max-height: min(68vh, 52rem);
  overflow: auto;
}

.rag-results__summary {
  align-items: center;
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0;
}

.rag-results__list {
  display: grid;
  gap: var(--sp-3);
}

.rag-result {
  display: grid;
  gap: var(--sp-2);
  min-width: 0;
}

.rag-result-card {
  width: 100%;
}

.rag-result-card small,
.rag-reader header p {
  color: var(--text-muted);
}

.rag-result-card__metadata {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.rag-result-card__snippet {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.rag-result__complete {
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  padding: var(--sp-2) var(--sp-3);
}

.rag-result__complete summary {
  cursor: pointer;
  font-weight: 600;
}

.rag-result__complete small {
  color: var(--text-muted);
  display: block;
  margin-top: var(--sp-2);
}

.rag-result__complete article {
  line-height: 1.6;
  margin-top: var(--sp-2);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.rag-reader__metadata {
  display: grid;
  gap: var(--sp-2);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: var(--sp-3) 0;
}

.rag-reader__metadata div {
  min-width: 0;
}

.rag-reader__metadata dt {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.rag-reader__metadata dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.rag-reader__content {
  font-family: var(--font-sans);
  line-height: 1.7;
  max-width: 82ch;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.rag-reader__pager {
  display: flex;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.rag-reader__back {
  display: none;
}

@media (max-width: 900px) {
  .rag-workspace {
    grid-template-columns: 1fr;
  }

  .rag-reader {
    display: none;
  }

  .rag-reader.is-mobile-open {
    display: flex;
  }

  .rag-workspace.is-reader-open .rag-results {
    display: none;
  }

  .rag-reader__back {
    display: inline-flex;
  }
}
</style>
