import type { ChatRenderedMessage } from '@/types/chat'
import type { SourcePart } from '@/types/parts'
import { toolOperationKey } from '@/utils/chat/toolDisplay'

const MAX_SOURCES = 12

interface SourceLink {
  url: string
  title: string
  domain: string
  canonicalUrl?: string
  provider?: string
  fetched?: boolean
  fetchStatus?: string
}

interface SourceMeta {
  canonicalUrl?: string
  provider?: string
  fetched?: boolean
  fetchStatus?: string
}

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

function sourceText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function sourceMeta(entry: Record<string, unknown>): SourceMeta {
  const meta: SourceMeta = {}
  const canonicalUrl = sourceText(entry.canonical_url) || sourceText(entry.canonicalUrl)
  const provider = sourceText(entry.provider)
  const fetchStatus = sourceText(entry.fetch_status) || sourceText(entry.fetchStatus)
  if (canonicalUrl) meta.canonicalUrl = canonicalUrl
  if (provider) meta.provider = provider
  if (typeof entry.fetched === 'boolean') meta.fetched = entry.fetched
  if (fetchStatus) meta.fetchStatus = fetchStatus
  return meta
}

function mergeMeta(source: SourceLink, meta: SourceMeta) {
  if (!source.canonicalUrl && meta.canonicalUrl) source.canonicalUrl = meta.canonicalUrl
  if (!source.provider && meta.provider) source.provider = meta.provider
  if (source.fetched !== true && meta.fetched === true) source.fetched = true
  if (
    meta.fetchStatus === 'ok' ||
    !source.fetchStatus ||
    source.fetchStatus === 'not_requested'
  ) {
    if (meta.fetchStatus) source.fetchStatus = meta.fetchStatus
  }
}

function addSource(
  out: SourceLink[],
  seen: Map<string, SourceLink>,
  url: unknown,
  title: unknown,
  meta: SourceMeta = {},
) {
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
    mergeMeta(existing, meta)
    return
  }
  const source: SourceLink = { url: trimmed, title: cleanTitle, domain, ...meta }
  seen.set(key, source)
  out.push(source)
}

function extractSources(raw: unknown, out: SourceLink[], seen: Map<string, SourceLink>): number {
  if (!Array.isArray(raw)) return 0
  const before = out.length
  for (const item of raw) {
    if (item && typeof item === 'object') {
      const entry = item as Record<string, unknown>
      addSource(
        out,
        seen,
        entry.url || entry.final_url || entry.canonical_url,
        entry.title,
        sourceMeta(entry),
      )
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

/**
 * Pure per-turn source fold. Replicates SourcesRow.vue's source-extraction
 * logic verbatim (direct `sources` payloads, then web.search / web.read
 * results, dedup, MAX_SOURCES cap) so the derived `sources[]` matches the row
 * the component renders. AssistantMessage passes this list to SourcesRow and to
 * TextPart for citation resolution, so the two must stay in sync.
 */
export function toSources(msg: ChatRenderedMessage): SourcePart[] {
  const out: SourceLink[] = []
  const seen = new Map<string, SourceLink>()
  for (const call of msg.toolCalls || []) {
    const operation = toolOperationKey(call.name)
    if (operation !== 'web.search' && operation !== 'web.read') continue
    if (call.isError || call.status === 'error') continue
    const record = parseJsonRecord(call.result)
    if (operation === 'web.search') {
      const directSources = extractSources(call.sources, out, seen)
      if (directSources > 0) continue
      const recordSources = record ? extractSources(record.sources, out, seen) : 0
      if (recordSources > 0) continue
      const results = record && Array.isArray(record.results) ? record.results as unknown[] : null
      if (results) {
        for (const item of results) {
          if (item && typeof item === 'object') {
            const entry = item as Record<string, unknown>
            addSource(out, seen, entry.url, entry.title, sourceMeta(entry))
          }
        }
      } else if (call.result) {
        scanSourceFields(call.result, out, seen)
      }
      continue
    }
    if (record) {
      addSource(out, seen, record.final_url || record.url, record.title, sourceMeta(record))
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
    canonicalUrl: source.canonicalUrl,
    provider: source.provider,
    fetched: source.fetched,
    fetchStatus: source.fetchStatus,
  }))
}
