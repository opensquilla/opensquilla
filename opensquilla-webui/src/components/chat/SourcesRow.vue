<template>
  <div v-if="sources.length" ref="rootRef" class="sources-row">
    <button
      type="button"
      class="sources-row__toggle"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="sources-row__label">{{ t('chat.sources') }}</span>
      <span class="sources-row__count">{{ sources.length }}</span>
      <span class="sources-row__chips" aria-hidden="true">
        <span
          v-for="source in chipSources"
          :key="sourceStableKey(source)"
          class="sources-row__chip"
        >
          <span class="sources-row__favicon">{{ initialFor(source) }}</span>
        </span>
      </span>
      <Icon class="sources-row__chevron" name="chevronRight" :size="14" />
    </button>
    <ul v-if="open" class="sources-row__list">
      <li
        v-for="source in sources"
        :key="sourceStableKey(source)"
        class="sources-row__item"
        :class="{ 'sources-row__item--pulse': source.sourceId === highlightId }"
        :data-source-id="source.sourceId"
      >
        <component
          :is="sourceHref(source) ? 'a' : 'div'"
          class="sources-row__link"
          :class="{ 'sources-row__link--knowledge': isKnowledgeSource(source) }"
          :href="sourceHref(source) || undefined"
          :target="sourceHref(source) ? '_blank' : undefined"
          :rel="sourceHref(source) ? 'noreferrer noopener' : undefined"
        >
          <span class="sources-row__index" aria-hidden="true">[{{ source.sourceId }}]</span>
          <span class="sources-row__chip">
            <span class="sources-row__favicon">{{ initialFor(source) }}</span>
          </span>
          <template v-if="isKnowledgeSource(source)">
            <span class="sources-row__knowledge-body">
              <span class="sources-row__knowledge-heading">
                <span class="sources-row__title">{{ source.title }}</span>
                <span v-if="knowledgeRank(source)" class="sources-row__rank">
                  #{{ knowledgeRank(source) }}
                </span>
              </span>
              <span
                v-if="knowledgeDocumentTitle(source)"
                class="sources-row__document-title"
              >
                {{ knowledgeDocumentTitle(source) }}
              </span>
              <span
                v-if="knowledgeMetadata(source).length"
                class="sources-row__knowledge-meta"
              >
                <span
                  v-for="(item, index) in knowledgeMetadata(source)"
                  :key="`${sourceStableKey(source)}:meta:${index}`"
                >
                  {{ item }}
                </span>
              </span>
              <span
                v-if="knowledgeSnippet(source)"
                class="sources-row__snippet"
              >
                {{ knowledgeSnippet(source) }}<span
                  v-if="knowledgeSnippetTruncated(source)"
                  aria-label="truncated"
                >…</span>
              </span>
            </span>
          </template>
          <template v-else>
            <span class="sources-row__title">{{ source.title || source.domain }}</span>
            <span
              class="sources-row__status"
              :class="`sources-row__status--${sourceTrust(source)}`"
            >
              {{ sourceTrustLabel(source) }}
            </span>
            <span class="sources-row__domain">{{ source.domain }}</span>
          </template>
        </component>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { ChatToolCall } from '@/types/chat'
import type { SourcePart } from '@/types/parts'
import {
  isKnowledgeSource,
  safeKnowledgeSourceUrl,
  sourceStableKey,
  toSourcesFromToolCalls,
} from '@/utils/chat/toSources'

const { t } = useI18n()
const MAX_CHIPS = 4
const MAX_SNIPPET_CHARS = 400

const props = defineProps<{
  calls: ChatToolCall[]
  // Optional numbered source list (sourceId = position) folded by toSources.
  // When present it is the authority for the row's numbering; absent, the row
  // derives the same structured sidecars from `calls`.
  sources?: SourcePart[]
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const highlightId = ref<number | null>(null)
let pulseTimer = 0

async function focusSource(sourceId: number) {
  open.value = true
  await nextTick()
  const el = rootRef.value?.querySelector(`[data-source-id="${sourceId}"]`)
  if (!el) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  highlightId.value = sourceId
  window.clearTimeout(pulseTimer)
  pulseTimer = window.setTimeout(() => {
    highlightId.value = null
  }, 1200)
}

onBeforeUnmount(() => {
  window.clearTimeout(pulseTimer)
})

defineExpose({ focusSource })

const derivedSources = computed<SourcePart[]>(() =>
  toSourcesFromToolCalls(props.calls),
)

const sources = computed<SourcePart[]>(() =>
  props.sources?.length ? props.sources : derivedSources.value,
)

const chipSources = computed(() => sources.value.slice(0, MAX_CHIPS))

function sourceHref(source: SourcePart): string {
  if (isKnowledgeSource(source)) {
    return safeKnowledgeSourceUrl(source.url) || ''
  }
  return source.url
}

function initialFor(source: SourcePart): string {
  const base = isKnowledgeSource(source)
    ? source.domain
      || source.fileName
      || source.title
      || source.documentTitle
      || source.sourcePath
      || source.source
      || ''
    : source.domain
  return (base.replace(/^www\./, '')[0] || '?').toUpperCase()
}

function knowledgeRank(source: SourcePart): number | undefined {
  return isKnowledgeSource(source) ? source.rank : undefined
}

function knowledgeDocumentTitle(source: SourcePart): string {
  return isKnowledgeSource(source) ? source.documentTitle || '' : ''
}

function knowledgeMetadata(source: SourcePart): string[] {
  if (!isKnowledgeSource(source)) return []
  return [source.sourcePath, source.source, source.locator].filter(
    (value): value is string => Boolean(value),
  )
}

function knowledgeSnippet(source: SourcePart): string {
  if (!isKnowledgeSource(source) || !source.snippet) return ''
  return Array.from(source.snippet).slice(0, MAX_SNIPPET_CHARS).join('')
}

function knowledgeSnippetTruncated(source: SourcePart): boolean {
  if (!isKnowledgeSource(source)) return false
  return source.snippetTruncated === true
    || Array.from(source.snippet || '').length > MAX_SNIPPET_CHARS
}

function sourceTrust(source: SourcePart): 'verified' | 'search' | 'failed' {
  if (isKnowledgeSource(source)) return 'search'
  if (source.fetched === true) return 'verified'
  if (source.fetchStatus && source.fetchStatus !== 'ok' && source.fetchStatus !== 'not_requested') {
    return 'failed'
  }
  return 'search'
}

function sourceTrustLabel(source: SourcePart): string {
  const trust = sourceTrust(source)
  if (trust === 'verified') return 'Verified'
  if (trust === 'failed') return 'Fetch failed'
  return 'Search result'
}
</script>

<style scoped>
.sources-row {
  margin: 0.375rem 0 0.125rem;
}

.sources-row__toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  font: inherit;
  font-size: 0.8125rem;
  color: var(--text-muted);
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
}

.sources-row__toggle:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
}

.sources-row__toggle:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.sources-row__label {
  font-weight: 500;
  color: var(--text);
}

.sources-row__count {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: var(--radius-full);
  color: var(--text-muted);
  background: var(--bg-hover);
}

.sources-row__chips {
  display: inline-flex;
  align-items: center;
}

.sources-row__chips .sources-row__chip + .sources-row__chip {
  margin-left: -0.25rem;
}

.sources-row__chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: var(--radius-full);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  overflow: hidden;
  flex-shrink: 0;
}

.sources-row__favicon {
  width: 0.875rem;
  height: 0.875rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.5625rem;
  font-weight: 600;
  color: var(--text-muted);
  line-height: 1;
}

.sources-row__chevron {
  color: var(--text-dim);
  transition: transform var(--dur-fast) var(--ease-standard);
}

.sources-row__toggle[aria-expanded='true'] .sources-row__chevron {
  transform: rotate(90deg);
}

.sources-row__list {
  margin: 0.375rem 0 0;
  padding: 0.25rem;
  list-style: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-xs);
}

.sources-row__item + .sources-row__item {
  border-top: 1px solid var(--hairline);
}

.sources-row__item--pulse {
  border-radius: var(--radius-sm);
  animation: sourcePulse 1.2s ease; /* motion-allow: long one-shot attention pulse, outside the transition scale */
}

@keyframes sourcePulse {
  0% {
    background: color-mix(in srgb, var(--accent) 22%, transparent);
  }
  100% {
    background: transparent;
  }
}

.sources-row__link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.375rem 0.5rem;
  border-radius: var(--radius-sm);
  text-decoration: none;
  color: var(--text);
  font-size: 0.8125rem;
  line-height: 1.4;
}

a.sources-row__link:hover {
  background: var(--bg-hover);
}

a.sources-row__link:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.sources-row__link--knowledge {
  align-items: flex-start;
  padding-block: 0.5rem;
}

.sources-row__index {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 0.625rem;
  color: var(--text-dim);
  min-width: 1.25rem;
  text-align: right;
}

.sources-row__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-row__knowledge-body {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 0.125rem;
}

.sources-row__knowledge-heading {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
  min-width: 0;
  font-weight: 500;
}

.sources-row__rank {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 0.625rem;
  color: var(--text-dim);
}

.sources-row__document-title {
  color: var(--text-muted);
  font-size: 0.75rem;
}

.sources-row__knowledge-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.75rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  overflow-wrap: anywhere;
}

.sources-row__snippet {
  margin-top: 0.125rem;
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sources-row__status {
  flex-shrink: 0;
  padding: 0.0625rem 0.375rem;
  border-radius: var(--radius-full);
  font-family: var(--font-mono);
  font-size: 0.625rem;
  line-height: 1.3;
  color: var(--text-dim);
  border: 1px solid var(--border);
  background: var(--bg-hover);
}

.sources-row__status--verified {
  color: var(--ok);
  border-color: color-mix(in srgb, var(--ok) 35%, var(--border));
  background: color-mix(in srgb, var(--ok) 9%, var(--bg-hover));
}

.sources-row__status--failed {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 35%, var(--border));
  background: color-mix(in srgb, var(--warn) 10%, var(--bg-hover));
}

.sources-row__domain {
  margin-left: auto;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--text-dim);
}

@media (max-width: 768px) {
  .sources-row__toggle {
    min-height: 2.75rem;
    padding: 0.375rem 0.625rem;
  }

  .sources-row__link {
    min-height: 2.75rem;
  }

  .sources-row__domain {
    display: none;
  }

  .sources-row__status {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sources-row__chevron {
    transition: none;
  }

  .sources-row__item--pulse {
    animation: none;
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }
}
</style>
