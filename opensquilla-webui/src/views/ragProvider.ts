export type RagProviderState =
  | 'DISABLED'
  | 'CONNECTING'
  | 'READY'
  | 'DEGRADED'
  | 'UNAVAILABLE'
  | 'INCOMPATIBLE'
  | 'LEGACY'

export interface RagDocument {
  id?: string
  title: string
  source?: string
  fileName?: string
  sourcePath?: string
  mediaType?: string
  revision?: string
  uri?: string
  openUrl?: string
}

export interface RagChunk {
  id: string
  content: string
  contentChars: number
}

export interface RagCitation {
  title: string
  source?: string
  locator?: string
  uri?: string
}

export interface RagSearchResult {
  evidenceId: string
  rank: number | null
  document: RagDocument | null
  chunk: RagChunk | null
  snippet: string
  snippetTruncated: boolean
  citation: RagCitation
}

export interface RagSearchResponse {
  returnedCount: number
  totalMatched: number | null
  resultsTruncated: boolean
  providerBudgetViolation: boolean
  retrievalProfile: string | null
  results: RagSearchResult[]
}

export interface RagGetResponse {
  evidenceId: string
  document: RagDocument
  content: string
  contentChars: number | null
  previousCursor: string | null
  nextCursor: string | null
  citation: RagCitation
  legacyLimitedGet: boolean
}

export interface RagProfileSetResponse {
  retrievalProfileOverride: string | null
  providerDefaultRetrievalProfile: string | null
  effectiveRetrievalProfile: string | null
  restartRequired: false
}

export interface RagProviderStatus {
  connectionState: RagProviderState
  enabled: boolean
  provider: { name: string; version: string; instanceId: string } | null
  protocolVersion: string | null
  capabilities: { search: true; get: boolean } | null
  effectiveLimits: {
    maxSearchResults: number
    maxSnippetChars: number
    maxSearchResponseChars: number
    maxGetContentChars: number
    maxChunkChars: number | null
  } | null
  searchOptions: {
    supportsCollectionScope: boolean
    retrievalProfiles: { id: string; label: string }[]
    defaultRetrievalProfile: string | null
  } | null
  links: { management?: string }
  lastSuccessAt: number | null
  lastErrorCode: string | null
  consecutiveFailures: number
  retrievalProfileOverride: string | null
  effectiveRetrievalProfile: string | null
  collectionScope: string[]
  legacyConfigPresent: boolean
  legacyAdapterEnabled: boolean
  warning: string | null
}

const STATES = new Set<RagProviderState>([
  'DISABLED',
  'CONNECTING',
  'READY',
  'DEGRADED',
  'UNAVAILABLE',
  'INCOMPATIBLE',
  'LEGACY',
])

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function positiveInteger(value: unknown): value is number {
  return nonNegativeInteger(value) && value > 0
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function safeManagementLink(value: string): boolean {
  if (value.startsWith('/') && !value.startsWith('//')) return true
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export function browserManagementLink(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? value : null
  } catch {
    return null
  }
}

const PROTOCOL_CONTROL_CHARACTER_RE = /[\u0000-\u001f\u007f-\u009f]/

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && Boolean(value.trim()) && !PROTOCOL_CONTROL_CHARACTER_RE.test(value)
}

function characterCount(value: string): number {
  return Array.from(value).length
}

function safeSourcePath(value: string): boolean {
  if (!value || value.startsWith('/') || value.startsWith('\\')) return false
  if (value.includes('\\') || /^[A-Za-z]:/.test(value)) return false
  if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(value)) return false
  return value.split('/').every(part => part !== '' && part !== '.' && part !== '..')
}

function safeDisplayMetadata(value: string): boolean {
  if (value === '.' || value === '..') return false
  if (value.includes('/') || value.includes('\\')) return false
  return !/^[A-Za-z][A-Za-z0-9+.-]*:/.test(value)
}

function parsedUrl(value: string): URL | null {
  try {
    return new URL(value)
  } catch {
    return null
  }
}

function safeResourceUri(value: string): boolean {
  if (!value || value.includes('\\') || /\s/.test(value)) return false
  const url = parsedUrl(value)
  if (!url || !/^[A-Za-z][A-Za-z0-9+.-]*:$/.test(url.protocol)) return false
  if (['javascript:', 'data:', 'file:', 'vbscript:'].includes(url.protocol.toLowerCase())) {
    return false
  }
  if (url.username || url.password) return false
  return Boolean(url.host || url.pathname)
}

function safeOpenUrl(value: string): boolean {
  if (!value || value.includes('\\') || /\s/.test(value)) return false
  if (value.startsWith('/') && !value.startsWith('//')) return true
  const url = parsedUrl(value)
  if (!url || !['http:', 'https:'].includes(url.protocol.toLowerCase())) return false
  return Boolean(url.host) && !url.username && !url.password
}

function optionalText(raw: Record<string, unknown>, key: string): string | undefined {
  const value = raw[key]
  return nonEmptyString(value) ? value : undefined
}

function optionalDisplayMetadata(
  raw: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = optionalText(raw, key)
  return value !== undefined && safeDisplayMetadata(value) ? value : undefined
}

function normalizedDocument(value: unknown): RagDocument | null {
  const raw = record(value)
  if (!raw || !nonEmptyString(raw.id) || !nonEmptyString(raw.title)) return null
  const result: RagDocument = { id: raw.id, title: raw.title }
  for (const key of ['source', 'fileName'] as const) {
    const item = optionalDisplayMetadata(raw, key)
    if (item !== undefined) result[key] = item
  }
  for (const key of ['mediaType', 'revision'] as const) {
    const item = optionalText(raw, key)
    if (item !== undefined) result[key] = item
  }
  if (nonEmptyString(raw.sourcePath) && safeSourcePath(raw.sourcePath)) {
    result.sourcePath = raw.sourcePath
  }
  if (nonEmptyString(raw.uri) && safeResourceUri(raw.uri)) result.uri = raw.uri
  if (nonEmptyString(raw.openUrl) && safeOpenUrl(raw.openUrl)) result.openUrl = raw.openUrl
  return result
}

function legacyDocument(value: unknown): RagDocument | null {
  const raw = record(value)
  if (!raw || typeof raw.title !== 'string' || typeof raw.source !== 'string') return null
  return { title: raw.title, source: raw.source }
}

interface CitationOptions {
  requireLocator?: boolean
  requireUri?: boolean
  documentUri?: string
}

function citation(value: unknown, options: CitationOptions = {}): RagCitation | null {
  const raw = record(value)
  if (!raw || !nonEmptyString(raw.title)) return null
  const locator = optionalText(raw, 'locator')
  if (options.requireLocator && locator === undefined) return null
  const rawUri = optionalText(raw, 'uri')
  let uri: string | undefined
  if (rawUri !== undefined && safeResourceUri(rawUri)) {
    const url = parsedUrl(rawUri)
    if (
      (!options.requireUri || Boolean(url?.search || url?.hash))
      && rawUri !== options.documentUri
    ) uri = rawUri
  }
  if (options.requireUri && uri === undefined) return null

  const result: RagCitation = { title: raw.title }
  const source = optionalDisplayMetadata(raw, 'source')
  if (source !== undefined) result.source = source
  if (locator !== undefined) result.locator = locator
  if (uri !== undefined) result.uri = uri
  return result
}

function normalizedCursor(value: unknown): string | null | undefined {
  if (value === null) return null
  return nonEmptyString(value) ? value : undefined
}

export function normalizeRagProviderStatus(value: unknown): RagProviderStatus | null {
  const raw = record(value)
  if (!raw || !STATES.has(raw.connectionState as RagProviderState)) return null
  if (typeof raw.enabled !== 'boolean') return null
  if (
    raw.protocolVersion !== null
    && raw.protocolVersion !== '1.0'
    && raw.protocolVersion !== '1.1'
  ) return null
  if (!nullableString(raw.lastErrorCode)) return null
  if (
    !nullableString(raw.retrievalProfileOverride)
    || !nullableString(raw.effectiveRetrievalProfile)
    || !nullableString(raw.warning)
  ) return null
  if (!nonNegativeInteger(raw.consecutiveFailures)) return null
  if (!(raw.lastSuccessAt === null || (typeof raw.lastSuccessAt === 'number' && Number.isFinite(raw.lastSuccessAt)))) return null
  if (!Array.isArray(raw.collectionScope) || !raw.collectionScope.every(item => typeof item === 'string')) return null
  if (typeof raw.legacyConfigPresent !== 'boolean' || typeof raw.legacyAdapterEnabled !== 'boolean') return null

  let provider: RagProviderStatus['provider'] = null
  if (raw.provider !== null) {
    const item = record(raw.provider)
    if (!item || !['name', 'version', 'instanceId'].every(key => typeof item[key] === 'string' && String(item[key]).length > 0)) return null
    provider = {
      name: item.name as string,
      version: item.version as string,
      instanceId: item.instanceId as string,
    }
  }

  let capabilities: RagProviderStatus['capabilities'] = null
  if (raw.capabilities !== null) {
    const item = record(raw.capabilities)
    if (!item || item.search !== true || typeof item.get !== 'boolean') return null
    capabilities = { search: true, get: item.get }
  }

  let effectiveLimits: RagProviderStatus['effectiveLimits'] = null
  if (raw.effectiveLimits !== null) {
    const item = record(raw.effectiveLimits)
    const keys = ['maxSearchResults', 'maxSnippetChars', 'maxSearchResponseChars', 'maxGetContentChars'] as const
    if (!item || !keys.every(key => positiveInteger(item[key]))) return null
    let maxChunkChars: number | null = null
    if (item.maxChunkChars !== undefined && item.maxChunkChars !== null) {
      if (!positiveInteger(item.maxChunkChars)) return null
      maxChunkChars = item.maxChunkChars
    } else if (raw.protocolVersion === '1.1') {
      return null
    }
    effectiveLimits = {
      maxSearchResults: item.maxSearchResults as number,
      maxSnippetChars: item.maxSnippetChars as number,
      maxSearchResponseChars: item.maxSearchResponseChars as number,
      maxGetContentChars: item.maxGetContentChars as number,
      maxChunkChars,
    }
  }

  let searchOptions: RagProviderStatus['searchOptions'] = null
  if (raw.searchOptions !== null) {
    const item = record(raw.searchOptions)
    if (!item || typeof item.supportsCollectionScope !== 'boolean' || !nullableString(item.defaultRetrievalProfile)) return null
    if (!Array.isArray(item.retrievalProfiles)) return null
    const profiles: { id: string; label: string }[] = []
    const profileIds = new Set<string>()
    for (const candidate of item.retrievalProfiles) {
      const profile = record(candidate)
      if (!profile || !nonEmptyString(profile.id) || !nonEmptyString(profile.label)) return null
      if (profileIds.has(profile.id)) return null
      profileIds.add(profile.id)
      profiles.push({ id: profile.id, label: profile.label })
    }
    let defaultRetrievalProfile = item.defaultRetrievalProfile
    if (defaultRetrievalProfile !== null && !profileIds.has(defaultRetrievalProfile)) {
      if (raw.protocolVersion === '1.0') defaultRetrievalProfile = null
      else return null
    }
    searchOptions = {
      supportsCollectionScope: item.supportsCollectionScope,
      retrievalProfiles: profiles,
      defaultRetrievalProfile,
    }
  }

  const rawLinks = record(raw.links)
  if (!rawLinks || (rawLinks.management !== undefined && typeof rawLinks.management !== 'string')) return null
  if (typeof rawLinks.management === 'string' && !safeManagementLink(rawLinks.management)) return null
  const links = typeof rawLinks.management === 'string'
    ? { management: rawLinks.management }
    : {}

  const state = raw.connectionState as RagProviderState
  if (['READY', 'DEGRADED', 'LEGACY'].includes(state) && (!provider || !capabilities || !effectiveLimits)) return null

  return {
    connectionState: state,
    enabled: raw.enabled,
    provider,
    protocolVersion: raw.protocolVersion,
    capabilities,
    effectiveLimits,
    searchOptions,
    links,
    lastSuccessAt: raw.lastSuccessAt,
    lastErrorCode: raw.lastErrorCode,
    consecutiveFailures: raw.consecutiveFailures,
    retrievalProfileOverride: raw.retrievalProfileOverride,
    effectiveRetrievalProfile: raw.effectiveRetrievalProfile,
    collectionScope: raw.collectionScope.slice() as string[],
    legacyConfigPresent: raw.legacyConfigPresent,
    legacyAdapterEnabled: raw.legacyAdapterEnabled,
    warning: raw.warning,
  }
}

export function normalizeRagProfileSetResponse(value: unknown): RagProfileSetResponse | null {
  const raw = record(value)
  if (!raw) return null
  if (!nullableString(raw.retrievalProfileOverride)) return null
  if (!nullableString(raw.providerDefaultRetrievalProfile)) return null
  if (!nullableString(raw.effectiveRetrievalProfile)) return null
  if (raw.restartRequired !== false) return null
  return {
    retrievalProfileOverride: raw.retrievalProfileOverride,
    providerDefaultRetrievalProfile: raw.providerDefaultRetrievalProfile,
    effectiveRetrievalProfile: raw.effectiveRetrievalProfile,
    restartRequired: false,
  }
}

export function effectiveRetrievalProfile(status: RagProviderStatus | null): string | null {
  return status?.effectiveRetrievalProfile
    ?? status?.retrievalProfileOverride
    ?? status?.searchOptions?.defaultRetrievalProfile
    ?? null
}

export function normalizeRagSearchResponse(value: unknown): RagSearchResponse | null {
  const raw = record(value)
  if (!raw || !Array.isArray(raw.results) || !nonNegativeInteger(raw.returnedCount)) return null
  if (raw.returnedCount !== raw.results.length) return null
  if (typeof raw.resultsTruncated !== 'boolean' || typeof raw.providerBudgetViolation !== 'boolean') return null
  const totalMatched = raw.totalMatched === undefined || raw.totalMatched === null
    ? null
    : nonNegativeInteger(raw.totalMatched) ? raw.totalMatched : undefined
  if (totalMatched === undefined) return null

  const hasRetrieval = raw.retrieval !== undefined
  const hasV11ResultFields = raw.results.some((candidate) => {
    const item = record(candidate)
    return item !== null && ['rank', 'document', 'chunk'].some(key => key in item)
  })
  if (!hasRetrieval && hasV11ResultFields) return null

  let retrievalProfile: string | null = null
  if (hasRetrieval) {
    const retrieval = record(raw.retrieval)
    if (!retrieval) return null
    if (retrieval.profile === null) retrievalProfile = null
    else if (nonEmptyString(retrieval.profile)) retrievalProfile = retrieval.profile
    else return null
  }

  const results: RagSearchResult[] = []
  for (const [index, candidate] of raw.results.entries()) {
    const item = record(candidate)
    if (
      !item
      || !nonEmptyString(item.evidenceId)
      || typeof item.snippet !== 'string'
      || typeof item.snippetTruncated !== 'boolean'
    ) return null

    if (!hasRetrieval) {
      const itemCitation = citation(item.citation)
      if (!itemCitation) return null
      results.push({
        evidenceId: item.evidenceId,
        rank: null,
        document: null,
        chunk: null,
        snippet: item.snippet,
        snippetTruncated: item.snippetTruncated,
        citation: itemCitation,
      })
      continue
    }

    if (!positiveInteger(item.rank) || item.rank !== index + 1) return null
    const document = normalizedDocument(item.document)
    const chunk = record(item.chunk)
    if (!document || !chunk || !nonEmptyString(chunk.id) || typeof chunk.content !== 'string') {
      return null
    }
    if (
      !nonNegativeInteger(chunk.contentChars)
      || chunk.contentChars !== characterCount(chunk.content)
    ) return null
    const itemCitation = citation(item.citation, {
      requireLocator: true,
      requireUri: true,
      documentUri: document.uri,
    })
    if (!itemCitation) return null
    results.push({
      evidenceId: item.evidenceId,
      rank: item.rank,
      document,
      chunk: {
        id: chunk.id,
        content: chunk.content,
        contentChars: chunk.contentChars,
      },
      snippet: item.snippet,
      snippetTruncated: item.snippetTruncated,
      citation: itemCitation,
    })
  }
  return {
    returnedCount: results.length,
    totalMatched,
    resultsTruncated: raw.resultsTruncated,
    providerBudgetViolation: raw.providerBudgetViolation,
    retrievalProfile,
    results,
  }
}

export function normalizeRagGetResponse(value: unknown): RagGetResponse | null {
  const raw = record(value)
  const rawDocument = record(raw?.document)
  if (!raw || !rawDocument) return null
  if (!nonEmptyString(raw.evidenceId) || typeof raw.content !== 'string') return null
  const previousCursor = normalizedCursor(raw.previousCursor)
  const nextCursor = normalizedCursor(raw.nextCursor)
  if (previousCursor === undefined || nextCursor === undefined) return null
  if (!(raw.legacyLimitedGet === undefined || typeof raw.legacyLimitedGet === 'boolean')) return null

  const hasV11Fields = raw.contentChars !== undefined
    || ['id', 'fileName', 'sourcePath', 'mediaType', 'revision', 'uri', 'openUrl']
      .some(key => key in rawDocument)

  let document: RagDocument | null
  let contentChars: number | null
  let itemCitation: RagCitation | null
  if (hasV11Fields) {
    document = normalizedDocument(rawDocument)
    if (
      !document
      || !nonNegativeInteger(raw.contentChars)
      || raw.contentChars !== characterCount(raw.content)
    ) return null
    contentChars = raw.contentChars
    itemCitation = citation(raw.citation, {
      requireLocator: true,
      requireUri: true,
      documentUri: document.uri,
    })
  } else {
    document = legacyDocument(rawDocument)
    contentChars = null
    itemCitation = citation(raw.citation)
  }
  if (!document || !itemCitation) return null

  return {
    evidenceId: raw.evidenceId,
    document,
    content: raw.content,
    contentChars,
    previousCursor,
    nextCursor,
    citation: itemCitation,
    legacyLimitedGet: raw.legacyLimitedGet === true,
  }
}
