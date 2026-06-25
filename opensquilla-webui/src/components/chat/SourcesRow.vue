<template>
  <div v-if="sources.length" class="sources-row">
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
      <li v-for="source in sources" :key="source.url" class="sources-row__item">
        <a
          class="sources-row__link"
          :href="source.url"
          target="_blank"
          rel="noreferrer noopener"
        >
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
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ChatToolCall } from '@/types/chat'
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
}>()

const open = ref(false)

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

const sources = computed<SourceLink[]>(() => {
  const out: SourceLink[] = []
  const seen = new Map<string, SourceLink>()
  for (const call of props.calls || []) {
    const operation = toolOperationKey(call.name)
    if (operation !== 'web.search' && operation !== 'web.read') continue
    if (call.isError || call.status === 'error') continue
    const record = parseJsonRecord(call.result)
    if (operation === 'web.search') {
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
  return out.slice(0, MAX_SOURCES)
})

const chipSources = computed(() => sources.value.slice(0, MAX_CHIPS))

function initialFor(source: SourceLink): string {
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
}
</style>
