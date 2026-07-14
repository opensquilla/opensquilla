export type RagProviderState =
  | 'DISABLED'
  | 'CONNECTING'
  | 'READY'
  | 'DEGRADED'
  | 'UNAVAILABLE'
  | 'INCOMPATIBLE'
  | 'LEGACY'

export interface RagCitation {
  title: string
  source?: string
  locator?: string
  uri?: string
}

export interface RagSearchResult {
  evidenceId: string
  snippet: string
  snippetTruncated: boolean
  citation: RagCitation
}

export interface RagSearchResponse {
  returnedCount: number
  totalMatched: number | null
  resultsTruncated: boolean
  providerBudgetViolation: boolean
  results: RagSearchResult[]
}

export interface RagGetResponse {
  evidenceId: string
  document: { title: string; source: string }
  content: string
  previousCursor: string | null
  nextCursor: string | null
  citation: RagCitation
  legacyLimitedGet: boolean
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

function citation(value: unknown): RagCitation | null {
  const raw = record(value)
  if (!raw || typeof raw.title !== 'string' || !raw.title.trim()) return null
  const result: RagCitation = { title: raw.title }
  for (const key of ['source', 'locator', 'uri'] as const) {
    const item = raw[key]
    if (item !== undefined) {
      if (typeof item !== 'string') return null
      result[key] = item
    }
  }
  return result
}

export function normalizeRagProviderStatus(value: unknown): RagProviderStatus | null {
  const raw = record(value)
  if (!raw || !STATES.has(raw.connectionState as RagProviderState)) return null
  if (typeof raw.enabled !== 'boolean') return null
  if (!nullableString(raw.protocolVersion) || !nullableString(raw.lastErrorCode)) return null
  if (!nullableString(raw.retrievalProfileOverride) || !nullableString(raw.warning)) return null
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
    effectiveLimits = {
      maxSearchResults: item.maxSearchResults as number,
      maxSnippetChars: item.maxSnippetChars as number,
      maxSearchResponseChars: item.maxSearchResponseChars as number,
      maxGetContentChars: item.maxGetContentChars as number,
    }
  }

  let searchOptions: RagProviderStatus['searchOptions'] = null
  if (raw.searchOptions !== null) {
    const item = record(raw.searchOptions)
    if (!item || typeof item.supportsCollectionScope !== 'boolean' || !nullableString(item.defaultRetrievalProfile)) return null
    if (!Array.isArray(item.retrievalProfiles)) return null
    const profiles: { id: string; label: string }[] = []
    for (const candidate of item.retrievalProfiles) {
      const profile = record(candidate)
      if (!profile || typeof profile.id !== 'string' || !profile.id || typeof profile.label !== 'string' || !profile.label) return null
      profiles.push({ id: profile.id, label: profile.label })
    }
    searchOptions = {
      supportsCollectionScope: item.supportsCollectionScope,
      retrievalProfiles: profiles,
      defaultRetrievalProfile: item.defaultRetrievalProfile,
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
    collectionScope: raw.collectionScope.slice() as string[],
    legacyConfigPresent: raw.legacyConfigPresent,
    legacyAdapterEnabled: raw.legacyAdapterEnabled,
    warning: raw.warning,
  }
}

export function normalizeRagSearchResponse(value: unknown): RagSearchResponse | null {
  const raw = record(value)
  if (!raw || !Array.isArray(raw.results) || !nonNegativeInteger(raw.returnedCount)) return null
  if (raw.returnedCount !== raw.results.length) return null
  if (!(raw.totalMatched === null || nonNegativeInteger(raw.totalMatched))) return null
  if (typeof raw.resultsTruncated !== 'boolean' || typeof raw.providerBudgetViolation !== 'boolean') return null
  const results: RagSearchResult[] = []
  for (const candidate of raw.results) {
    const item = record(candidate)
    const itemCitation = citation(item?.citation)
    if (!item || typeof item.evidenceId !== 'string' || !item.evidenceId || typeof item.snippet !== 'string' || typeof item.snippetTruncated !== 'boolean' || !itemCitation) return null
    results.push({
      evidenceId: item.evidenceId,
      snippet: item.snippet,
      snippetTruncated: item.snippetTruncated,
      citation: itemCitation,
    })
  }
  return {
    returnedCount: raw.returnedCount,
    totalMatched: raw.totalMatched,
    resultsTruncated: raw.resultsTruncated,
    providerBudgetViolation: raw.providerBudgetViolation,
    results,
  }
}

export function normalizeRagGetResponse(value: unknown): RagGetResponse | null {
  const raw = record(value)
  const document = record(raw?.document)
  const itemCitation = citation(raw?.citation)
  if (!raw || !document || !itemCitation) return null
  if (typeof raw.evidenceId !== 'string' || !raw.evidenceId || typeof raw.content !== 'string') return null
  if (typeof document.title !== 'string' || typeof document.source !== 'string') return null
  if (!nullableString(raw.previousCursor) || !nullableString(raw.nextCursor)) return null
  if (!(raw.legacyLimitedGet === undefined || typeof raw.legacyLimitedGet === 'boolean')) return null
  return {
    evidenceId: raw.evidenceId,
    document: { title: document.title, source: document.source },
    content: raw.content,
    previousCursor: raw.previousCursor,
    nextCursor: raw.nextCursor,
    citation: itemCitation,
    legacyLimitedGet: raw.legacyLimitedGet === true,
  }
}
