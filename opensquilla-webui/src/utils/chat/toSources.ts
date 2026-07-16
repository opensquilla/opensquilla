import type { ChatRenderedMessage, ChatToolCall } from '@/types/chat'
import type {
  KnowledgeSourcePart,
  SourcePart,
  WebSourcePart,
} from '@/types/parts'
import { toolOperationKey } from '@/utils/chat/toolDisplay'

const MAX_SOURCES = 12
const MAX_KNOWLEDGE_SNIPPET_CHARS = 400
const PROTOCOL_CONTROL_CHARACTER_RE = /[\u0000-\u001f\u007f-\u009f]/

type WebSourceDraft = Omit<WebSourcePart, 'sourceId'>
type KnowledgeSourceDraft = Omit<KnowledgeSourcePart, 'sourceId'>
type SourceDraft = WebSourceDraft | KnowledgeSourceDraft

interface SourceMeta {
  canonicalUrl?: string
  provider?: string
  fetched?: boolean
  fetchStatus?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function parseJsonRecord(value: string | undefined): Record<string, unknown> | null {
  const raw = String(value || '').trim()
  if (!raw.startsWith('{')) return null
  try {
    return asRecord(JSON.parse(raw))
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
  if (typeof value !== 'string' || PROTOCOL_CONTROL_CHARACTER_RE.test(value)) return undefined
  const text = value.trim()
  return text || undefined
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

function mergeWebMeta(source: WebSourceDraft, meta: SourceMeta) {
  if (!source.canonicalUrl && meta.canonicalUrl) source.canonicalUrl = meta.canonicalUrl
  if (!source.provider && meta.provider) source.provider = meta.provider
  if (source.fetched !== true && meta.fetched === true) source.fetched = true
  if (
    meta.fetchStatus === 'ok'
    || !source.fetchStatus
    || source.fetchStatus === 'not_requested'
  ) {
    if (meta.fetchStatus) source.fetchStatus = meta.fetchStatus
  }
}

function addWebSource(
  out: SourceDraft[],
  seen: Map<string, WebSourceDraft>,
  url: unknown,
  title: unknown,
  meta: SourceMeta = {},
): boolean {
  if (typeof url !== 'string') return false
  const trimmed = url.trim()
  if (trimmed.endsWith('…')) return false
  const domain = domainFor(trimmed)
  if (!domain) return false
  const key = trimmed.replace(/#.*$/, '')
  const cleanTitle = typeof title === 'string' ? title.trim() : ''
  const existing = seen.get(key)
  if (existing) {
    if (!existing.title && cleanTitle) existing.title = cleanTitle
    mergeWebMeta(existing, meta)
    return true
  }
  const source: WebSourceDraft = {
    kind: 'web',
    url: trimmed,
    title: cleanTitle,
    domain,
    ...meta,
  }
  seen.set(key, source)
  out.push(source)
  return true
}

function extractWebSources(
  raw: unknown,
  out: SourceDraft[],
  seen: Map<string, WebSourceDraft>,
): number {
  if (!Array.isArray(raw)) return 0
  let extracted = 0
  for (const item of raw) {
    const entry = asRecord(item)
    if (!entry || entry.kind === 'knowledge') continue
    if (entry.kind !== undefined && entry.kind !== 'web') continue
    if (addWebSource(
      out,
      seen,
      entry.url || entry.final_url || entry.canonical_url,
      entry.title,
      sourceMeta(entry),
    )) extracted += 1
  }
  return extracted
}

const WEB_SOURCE_FIELD_RE = /"(title|url|final_url)"\s*:\s*"((?:[^"\\]|\\.)*)"/g

function scanWebSourceFields(
  raw: string,
  out: SourceDraft[],
  seen: Map<string, WebSourceDraft>,
) {
  let pendingTitle = ''
  for (const match of raw.matchAll(WEB_SOURCE_FIELD_RE)) {
    let value = ''
    try {
      value = JSON.parse(`"${match[2]}"`)
    } catch {
      continue
    }
    if (match[1] === 'title') {
      pendingTitle = value
    } else {
      addWebSource(out, seen, value, pendingTitle)
      pendingTitle = ''
    }
  }
}

export function safeKnowledgeSourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value) return undefined
  if (
    value.includes('\\')
    || /\s/.test(value)
    || PROTOCOL_CONTROL_CHARACTER_RE.test(value)
  ) return undefined
  try {
    decodeURI(value)
  } catch {
    return undefined
  }
  if (value.startsWith('/')) return value.startsWith('//') ? undefined : value
  if (!/^https?:\/\//i.test(value)) return undefined
  try {
    const parsed = new URL(value)
    if (!['http:', 'https:'].includes(parsed.protocol.toLowerCase())) return undefined
    if (!parsed.host || parsed.username || parsed.password) return undefined
    return value
  } catch {
    return undefined
  }
}

function boundedSnippet(value: unknown): {
  snippet?: string
  snippetTruncated?: boolean
} {
  if (typeof value !== 'string') return {}
  const characters = Array.from(value)
  return {
    snippet: characters.slice(0, MAX_KNOWLEDGE_SNIPPET_CHARS).join(''),
    snippetTruncated: characters.length > MAX_KNOWLEDGE_SNIPPET_CHARS,
  }
}

function positiveRank(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : undefined
}

function preferredKnowledgeTitle(
  fileName: string | undefined,
  documentTitle: string | undefined,
  citationTitle: string | undefined,
  fallback = 'Knowledge source',
): string {
  return fileName || documentTitle || citationTitle || fallback
}

function parseKnowledgeSource(value: unknown): KnowledgeSourceDraft | null {
  const entry = asRecord(value)
  if (!entry || entry.kind !== 'knowledge') return null
  const document = asRecord(entry.document)
  const citation = asRecord(entry.citation)
  const evidenceId = sourceText(entry.evidenceId)
  const rank = positiveRank(entry.rank)
  const documentId = sourceText(document?.id)
  const documentTitle = sourceText(document?.title)
  const fileName = sourceText(document?.fileName)
  const sourcePath = sourceText(document?.sourcePath)
  const source = sourceText(document?.source) || sourceText(citation?.source)
  const mediaType = sourceText(document?.mediaType)
  const revision = sourceText(document?.revision)
  const documentUri = sourceText(document?.uri)
  const citationTitle = sourceText(citation?.title)
  const citationUri = sourceText(citation?.uri)
  const locator = sourceText(citation?.locator)
  const url = safeKnowledgeSourceUrl(document?.openUrl)
  const domain = url ? domainFor(url) || undefined : undefined
  const bounded = boundedSnippet(entry.snippet)
  const title = preferredKnowledgeTitle(fileName, documentTitle, citationTitle)
  const sourcePart: KnowledgeSourceDraft = {
    kind: 'knowledge',
    title,
  }

  if (evidenceId) sourcePart.evidenceId = evidenceId
  if (rank) sourcePart.rank = rank
  if (fileName && documentTitle && fileName !== documentTitle) {
    sourcePart.documentTitle = documentTitle
  }
  if (url) sourcePart.url = url
  if (domain) sourcePart.domain = domain
  if (documentId) sourcePart.documentId = documentId
  if (fileName) sourcePart.fileName = fileName
  if (sourcePath) sourcePart.sourcePath = sourcePath
  if (source) sourcePart.source = source
  if (mediaType) sourcePart.mediaType = mediaType
  if (revision) sourcePart.revision = revision
  if (documentUri) sourcePart.documentUri = documentUri
  if (citationTitle) sourcePart.citationTitle = citationTitle
  if (citationUri) sourcePart.citationUri = citationUri
  if (locator) sourcePart.locator = locator
  if (bounded.snippet !== undefined) sourcePart.snippet = bounded.snippet
  if (typeof entry.snippetTruncated === 'boolean' || bounded.snippetTruncated) {
    sourcePart.snippetTruncated = entry.snippetTruncated === true || bounded.snippetTruncated === true
  }
  return sourcePart
}

function knowledgeIdentity(source: KnowledgeSourceDraft): string | null {
  if (source.evidenceId) return `knowledge:evidence:${source.evidenceId}`
  if (source.documentId) return `knowledge:document:${source.documentId}`
  if (source.citationUri) return `knowledge:citation:${source.citationUri}`
  if (source.documentUri) return `knowledge:document-uri:${source.documentUri}`
  return null
}

function mergeKnowledgeSource(
  existing: KnowledgeSourceDraft,
  incoming: KnowledgeSourceDraft,
) {
  for (const [key, value] of Object.entries(incoming)) {
    if (value === undefined || key === 'kind') continue
    const field = key as keyof KnowledgeSourceDraft
    if (existing[field] === undefined || existing[field] === '') {
      Object.assign(existing, { [field]: value })
    }
  }
  existing.title = preferredKnowledgeTitle(
    existing.fileName,
    existing.documentTitle,
    existing.citationTitle,
    existing.title,
  )
  if (incoming.snippetTruncated === true) existing.snippetTruncated = true
}

function extractKnowledgeSources(
  raw: unknown,
  out: SourceDraft[],
  seen: Map<string, KnowledgeSourceDraft>,
) {
  if (!Array.isArray(raw)) return
  for (const item of raw) {
    const source = parseKnowledgeSource(item)
    if (!source) continue
    const identity = knowledgeIdentity(source)
    const existing = identity ? seen.get(identity) : undefined
    if (existing) {
      mergeKnowledgeSource(existing, source)
      continue
    }
    if (identity) seen.set(identity, source)
    out.push(source)
  }
}

export function isKnowledgeSource(
  source: SourcePart,
): source is KnowledgeSourcePart {
  return source.kind === 'knowledge'
}

export function sourceStableKey(source: SourcePart): string {
  if (!isKnowledgeSource(source)) return source.url
  if (source.evidenceId) return `knowledge:evidence:${source.evidenceId}`
  if (source.documentId) return `knowledge:document:${source.documentId}`
  if (source.citationUri) return `knowledge:citation:${source.citationUri}`
  if (source.documentUri) return `knowledge:document-uri:${source.documentUri}`
  return `knowledge:source:${source.sourceId}`
}

export function toSourcesFromToolCalls(
  toolCalls: readonly ChatToolCall[] | undefined,
): SourcePart[] {
  const out: SourceDraft[] = []
  const seenWeb = new Map<string, WebSourceDraft>()
  const seenKnowledge = new Map<string, KnowledgeSourceDraft>()

  for (const call of toolCalls || []) {
    if (call.isError || call.status === 'error') continue
    const operation = toolOperationKey(call.name)
    if (operation === 'knowledge.search' || operation === 'knowledge.get') {
      extractKnowledgeSources(call.sources, out, seenKnowledge)
      continue
    }
    if (operation === 'web.search' || operation === 'web.read') {
      if (extractWebSources(call.sources, out, seenWeb) > 0) continue
      const result = parseJsonRecord(call.result)
      if (operation === 'web.search') {
        if (result && extractWebSources(result.sources, out, seenWeb) > 0) continue
        if (result && extractWebSources(result.results, out, seenWeb) > 0) continue
        if (call.result) scanWebSourceFields(call.result, out, seenWeb)
        continue
      }
      if (result) {
        addWebSource(
          out,
          seenWeb,
          result.final_url || result.url,
          result.title,
          sourceMeta(result),
        )
      } else {
        const input = parseJsonRecord(call.inputRaw)
        addWebSource(out, seenWeb, input?.url, '')
      }
    }
  }

  return out.slice(0, MAX_SOURCES).map((source, index) => ({
    ...source,
    sourceId: index + 1,
  })) as SourcePart[]
}

/**
 * Pure per-turn source fold. Knowledge sources come exclusively from the
 * structured event/segment `sources` sidecar. Web tools prefer that sidecar
 * and retain their legacy result/input fallback for live and historical calls.
 */
export function toSources(msg: ChatRenderedMessage): SourcePart[] {
  return toSourcesFromToolCalls(msg.toolCalls)
}
