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
        </p>
        <div v-if="!props.searchResponse" class="state">
          {{ t('rag.results.empty') }}
        </div>
        <div class="rag-results__list">
          <button
            v-for="item in props.searchResponse?.results || []"
            :key="item.evidenceId"
            type="button"
            class="control-card control-card--interactive rag-result-card"
            :class="{ 'control-card--selected': item.evidenceId === props.selectedEvidenceId }"
            :data-evidence-id="item.evidenceId"
            @click="emit('select', item.evidenceId)"
          >
            <strong>{{ item.citation.title }}</strong>
            <small>{{ item.citation.source || item.citation.locator || item.evidenceId }}</small>
            <span>{{ item.snippet }}</span>
            <span v-if="item.snippetTruncated" class="control-pill">
              {{ t('rag.results.snippetTruncated') }}
            </span>
          </button>
        </div>
      </section>

      <section
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
            <h2 class="control-panel__title">{{ props.getResponse.document.title }}</h2>
            <p>{{ props.getResponse.citation.locator || props.getResponse.document.source }}</p>
          </header>
          <p v-if="props.getResponse.legacyLimitedGet" class="rag-reader__warning">
            {{ t('rag.reader.legacyLimited') }}
          </p>
          <article ref="readerContent" class="rag-reader__content">
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
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RagGetResponse, RagSearchResponse } from '@/views/ragProvider'

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
const readerContent = ref<HTMLElement | null>(null)

function onQueryKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || (!event.metaKey && !event.ctrlKey)) return
  event.preventDefault()
  if (props.canSearch && !props.searching && props.query.trim()) emit('search')
}

watch(() => props.getResponse?.content, async () => {
  await nextTick()
  if (readerContent.value) readerContent.value.scrollTop = 0
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

.rag-result-card {
  width: 100%;
}

.rag-result-card small,
.rag-reader header p {
  color: var(--text-muted);
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
