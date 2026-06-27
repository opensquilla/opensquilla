<template>
  <div v-if="sources.length" ref="rootRef" class="sources-row">
    <button
      type="button"
      class="sources-row__toggle"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="sources-row__label">Sources</span>
      <span class="sources-row__count">{{ sources.length }}</span>
      <span class="sources-row__chips" aria-hidden="true">
        <span v-for="source in chipSources" :key="source.url" class="sources-row__chip">
          <span class="sources-row__favicon">{{ initialFor(source) }}</span>
        </span>
      </span>
      <Icon class="sources-row__chevron" name="chevronRight" :size="14" />
    </button>
    <ul v-if="open" class="sources-row__list">
      <li
        v-for="source in sources"
        :key="source.url"
        class="sources-row__item"
        :class="{ 'sources-row__item--pulse': source.sourceId === highlightId }"
        :data-source-id="source.sourceId"
      >
        <a
          class="sources-row__link"
          :href="source.url"
          target="_blank"
          rel="noreferrer noopener"
        >
          <span class="sources-row__index" aria-hidden="true">[{{ source.sourceId }}]</span>
          <span class="sources-row__chip">
            <span class="sources-row__favicon">{{ initialFor(source) }}</span>
          </span>
          <span class="sources-row__title">{{ source.title || source.domain }}</span>
          <span class="sources-row__domain">{{ source.domain }}</span>
        </a>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ChatToolCall } from '@/types/chat'
import type { SourcePart } from '@/types/parts'
import { toolOperationKey } from '@/utils/chat/toolDisplay'

const MAX_SOURCES = 12
const MAX_CHIPS = 4

interface SourceLink {
  url: string
  title: string
  domain: string
}

const props = defineProps<{
  calls: ChatToolCall[]
  // Optional numbered source list (sourceId = position) folded by toSources.
  // When present it is the authority for the row's numbering; absent, the row
  // derives the same list from `calls` and numbers it by position.
  sources?: SourcePart[]
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const highlightId = ref<number | null>(null)
let pulseTimer = 0

// Open the row, bring source `n` into view, and pulse it. Driven by a citation
// pill in the message body (AssistantMessage wires this through onCitation).
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

function parseJsonRecord(text: string): Record<string, unknown> | null {
  const raw = String(text || '').trim()
  if (!raw.startsWith('{')) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function domainFor(url: string): string {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return ''
    return parsed.hostname
  } catch {
    return ''
  }
}

function addSource(out: SourceLink[], seen: Map<string, SourceLink>, url: unknown, title: unknown) {
  if (typeof url !== 'string') return
  const trimmed = url.trim()
  // Persisted tool results compact long strings with a trailing '…'; a
  // truncated URL is a guaranteed dead link, so never render it as a source.
  if (trimmed.endsWith('…')) return
  const domain = domainFor(trimmed)
  if (!domain) return
  const key = trimmed.replace(/#.*$/, '')
  const cleanTitle = typeof title === 'string' ? title.trim() : ''
  const existing = seen.get(key)
  if (existing) {
    if (!existing.title && cleanTitle) existing.title = cleanTitle
    return
  }
  const source: SourceLink = { url: trimmed, title: cleanTitle, domain }
  seen.set(key, source)
  out.push(source)
}

function extractSources(raw: unknown, out: SourceLink[], seen: Map<string, SourceLink>): number {
  if (!Array.isArray(raw)) return 0
  const before = out.length
  for (const item of raw) {
    if (item && typeof item === 'object') {
      const entry = item as Record<string, unknown>
      addSource(out, seen, entry.url || entry.final_url || entry.canonical_url, entry.title)
    }
  }
  return out.length - before
}

// Truncated persisted results can break JSON.parse; recover what is left by
// scanning the raw text for title/url field pairs in order.
const SOURCE_FIELD_RE = /"(title|url|final_url)"\s*:\s*"((?:[^"\\]|\\.)*)"/g

function scanSourceFields(raw: string, out: SourceLink[], seen: Map<string, SourceLink>) {
  let pendingTitle = ''
  for (const match of raw.matchAll(SOURCE_FIELD_RE)) {
    let value = ''
    try {
      value = JSON.parse(`"${match[2]}"`)
    } catch {
      continue
    }
    if (match[1] === 'title') {
      pendingTitle = value
    } else {
      addSource(out, seen, value, pendingTitle)
      pendingTitle = ''
    }
  }
}

function operationHasSearchResults(operation: string): boolean {
  return operation === 'web.search'
}

const derivedSources = computed<SourcePart[]>(() => {
  const out: SourceLink[] = []
  const seen = new Map<string, SourceLink>()
  for (const call of props.calls || []) {
    const operation = toolOperationKey(call.name)
    if (!operationHasSearchResults(operation) && operation !== 'web.read') continue
    if (call.isError || call.status === 'error') continue
    const record = parseJsonRecord(call.result)
    if (operationHasSearchResults(operation)) {
      const directSources = extractSources(call.sources, out, seen)
      if (directSources > 0) continue
      const recordSources = record ? extractSources(record.sources, out, seen) : 0
      if (recordSources > 0) continue
      const results = record && Array.isArray(record.results) ? record.results as unknown[] : null
      if (results) {
        for (const item of results) {
          if (item && typeof item === 'object') {
            const entry = item as Record<string, unknown>
            addSource(out, seen, entry.url, entry.title)
          }
        }
      } else if (call.result) {
        scanSourceFields(call.result, out, seen)
      }
      continue
    }
    if (record) {
      addSource(out, seen, record.final_url || record.url, record.title)
    } else {
      const input = parseJsonRecord(call.inputRaw || '')
      addSource(out, seen, input?.url, '')
    }
  }
  return out.slice(0, MAX_SOURCES).map((source, index) => ({
    sourceId: index + 1,
    url: source.url,
    title: source.title,
    domain: source.domain,
  }))
})

// Prefer the numbered list folded upstream; fall back to the calls-derived list
// so the row stays usable standalone. Both number identically by position.
const sources = computed<SourcePart[]>(() =>
  props.sources?.length ? props.sources : derivedSources.value,
)

const chipSources = computed(() => sources.value.slice(0, MAX_CHIPS))

function initialFor(source: SourcePart): string {
  const base = source.domain.replace(/^www\./, '')
  return (base[0] || '?').toUpperCase()
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
  border-radius: 999px;
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
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
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
  border-radius: 999px;
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
  border-radius: 999px;
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
  transition: transform 0.12s ease;
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
  animation: sourcePulse 1.2s ease;
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

.sources-row__link:hover {
  background: var(--bg-hover);
}

.sources-row__link:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
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
