export type RetrievalKind = 'lexical' | 'vector' | 'hybrid'
export type KnowledgeConnectionState =
  | 'DISCONNECTED'
  | 'DISCOVERING'
  | 'READY'
  | 'DEGRADED'
  | 'UNAVAILABLE'
  | 'LEGACY'

export interface RetrievalProfileStatus {
  id: string
  label: string
  kind: RetrievalKind
  available: boolean
  reason: string | null
  model?: string
  dimensions?: number
}

export interface KnowledgeStatusLike {
  connectionState?: KnowledgeConnectionState
  capabilitiesStale?: boolean
  configuredDefaultRetrievalProfile?: string | null
  effectiveDefaultRetrievalProfile?: string | null
  defaultFallbackReason?: string | null
  retrievalProfiles?: RetrievalProfileStatus[]
  defaultRetrievalProfile?: string
}

export interface KnowledgeResultScoreLike {
  score?: number | null
  bm25Rank?: number | null
  vectorRank?: number | null
  vectorScore?: number | null
  fusionScore?: number | null
  retrievalProfile?: string | null
}

export interface SearchProfilePayload {
  retrievalProfile?: string
}

export interface ResultScoreMeta {
  label: string
  value: string
}

type RetrievalProfileScoreHint = RetrievalProfileStatus | string | null | undefined

function serviceRetrievalProfiles(
  status: KnowledgeStatusLike | null | undefined,
): RetrievalProfileStatus[] {
  const profiles = status?.retrievalProfiles
  if (!Array.isArray(profiles) || !profiles.every(isRetrievalProfileStatus)) return []
  if (new Set(profiles.map((profile) => profile.id)).size !== profiles.length) return []
  return profiles.slice()
}

export function retrievalProfilesFromStatus(
  status: KnowledgeStatusLike | null | undefined,
): RetrievalProfileStatus[] {
  const state = connectionStateFromStatus(status)
  return state === 'READY' || state === 'DEGRADED' ? serviceRetrievalProfiles(status) : []
}

export function defaultProfileDraftFromStatus(
  status: KnowledgeStatusLike | null | undefined,
): string {
  if (connectionStateFromStatus(status) !== 'READY') return ''
  const configuredDefault = status?.configuredDefaultRetrievalProfile
  return typeof configuredDefault === 'string'
    && configuredDefault.length > 0
    && configuredDefault.trim() === configuredDefault
    ? configuredDefault
    : ''
}

export function queryOverrideOptions(
  status: KnowledgeStatusLike | null | undefined,
): RetrievalProfileStatus[] {
  return connectionStateFromStatus(status) === 'READY'
    ? retrievalProfilesFromStatus(status).filter((profile) => profile.available)
    : []
}

export function canSaveDefault(
  status: KnowledgeStatusLike | null | undefined,
): boolean {
  return connectionStateFromStatus(status) === 'READY'
    && status?.capabilitiesStale === false
    && defaultProfileDraftFromStatus(status).length > 0
    && queryOverrideOptions(status).length > 0
}

export function fallbackActive(
  status: KnowledgeStatusLike | null | undefined,
): boolean {
  const state = connectionStateFromStatus(status)
  if (state !== 'READY' && state !== 'DEGRADED') return false
  const reason = status?.defaultFallbackReason
  if (typeof reason === 'string' && reason.trim().length > 0) return true

  const configuredDefault = status?.configuredDefaultRetrievalProfile
  if (
    typeof configuredDefault !== 'string'
    || configuredDefault.length === 0
    || configuredDefault.trim() !== configuredDefault
  ) return false

  const effectiveDefault = status?.effectiveDefaultRetrievalProfile
  if (effectiveDefault === null) return true
  return typeof effectiveDefault === 'string'
    && effectiveDefault.length > 0
    && effectiveDefault.trim() === effectiveDefault
    && effectiveDefault !== configuredDefault
}

function availableRetrievalProfile(
  status: KnowledgeStatusLike | null | undefined,
  currentProfileId = '',
): RetrievalProfileStatus | undefined {
  const profiles = retrievalProfilesFromStatus(status)
  if (currentProfileId) {
    const currentProfile = profiles.find(
      (profile) => profile.id === currentProfileId && profile.available,
    )
    if (currentProfile) {
      return currentProfile
    }
  }
  const serviceDefault = status?.effectiveDefaultRetrievalProfile
    || status?.configuredDefaultRetrievalProfile
  if (serviceDefault) {
    const defaultProfile = profiles.find(
      (profile) => profile.id === serviceDefault && profile.available,
    )
    if (defaultProfile) {
      return defaultProfile
    }
  }
  return profiles.find((profile) => profile.available)
}

export function selectedRetrievalProfile(
  status: KnowledgeStatusLike | null | undefined,
  profileId: string,
): RetrievalProfileStatus | null {
  return availableRetrievalProfile(status, profileId) || null
}

export function defaultRetrievalProfileId(
  status: KnowledgeStatusLike | null | undefined,
  currentProfileId = '',
): string {
  const availableProfile = availableRetrievalProfile(status, currentProfileId)
  if (availableProfile) {
    return availableProfile.id
  }

  const serviceProfiles = retrievalProfilesFromStatus(status)
  if (serviceProfiles.length) {
    const currentProfile = serviceProfiles.find((profile) => profile.id === currentProfileId)
    if (currentProfile) {
      return currentProfile.id
    }
    const serviceDefault = status?.configuredDefaultRetrievalProfile
    const defaultProfile = serviceProfiles.find((profile) => profile.id === serviceDefault)
    return defaultProfile?.id || serviceProfiles[0]?.id || ''
  }

  return ''
}

export function buildSearchProfilePayload(
  status: KnowledgeStatusLike | null | undefined,
  profileId: string,
): SearchProfilePayload | null {
  const state = connectionStateFromStatus(status)
  if (state === 'DEGRADED' || state === 'LEGACY') return {}
  if (state !== 'READY') return null

  const availableProfiles = serviceRetrievalProfiles(status).filter(
    (profile) => profile.available,
  )
  if (!availableProfiles.length) return null
  if (!profileId) return {}
  return availableProfiles.some((profile) => profile.id === profileId)
    ? { retrievalProfile: profileId }
    : null
}

export function searchProgressLabel(
  status: KnowledgeStatusLike | null | undefined,
  profileId: string,
): string {
  const profile = selectedRetrievalProfile(status, profileId)
  return profile?.kind === 'vector' || profile?.kind === 'hybrid'
    ? 'Embedding retrieval'
    : 'Searching'
}

export function formatResultScorePrimary(
  result: KnowledgeResultScoreLike,
  fallbackProfile: RetrievalProfileScoreHint,
): string {
  const kind = resultScoreKind(result, fallbackProfile)
  if (kind === 'vector') {
    return `vector ${fixedScore(result.vectorScore ?? result.score)}`
  }
  if (kind === 'hybrid') {
    return `fusion ${fixedScore(result.fusionScore ?? result.score)}`
  }
  return `lexical ${fixedScore(result.score)}`
}

export function formatResultScoreMeta(
  result: KnowledgeResultScoreLike,
  fallbackProfile: RetrievalProfileScoreHint,
): ResultScoreMeta[] {
  const kind = resultScoreKind(result, fallbackProfile)
  const meta: ResultScoreMeta[] = []
  if (kind === 'hybrid' || kind === 'lexical') {
    if (result.bm25Rank !== null && result.bm25Rank !== undefined) {
      meta.push({ label: 'BM25', value: fixedScore(result.bm25Rank) })
    }
  }
  if (kind === 'vector' || kind === 'hybrid') {
    if (result.vectorRank !== null && result.vectorRank !== undefined) {
      meta.push({ label: 'Vector', value: `#${result.vectorRank}` })
    }
    if (result.vectorScore !== null && result.vectorScore !== undefined) {
      meta.push({ label: 'Vector score', value: fixedScore(result.vectorScore) })
    }
  }
  return meta
}

function resultScoreKind(
  result: KnowledgeResultScoreLike,
  fallbackProfile: RetrievalProfileScoreHint,
): RetrievalKind {
  if (
    fallbackProfile
    && typeof fallbackProfile !== 'string'
    && (!result.retrievalProfile || result.retrievalProfile === fallbackProfile.id)
  ) {
    return fallbackProfile.kind
  }
  return retrievalKindFromId(result.retrievalProfile || profileHintId(fallbackProfile))
}

function profileHintId(profile: RetrievalProfileScoreHint): string {
  if (!profile) return ''
  return typeof profile === 'string' ? profile : profile.id
}

function connectionStateFromStatus(
  status: KnowledgeStatusLike | null | undefined,
): KnowledgeConnectionState | null {
  switch (status?.connectionState) {
    case 'DISCONNECTED':
    case 'DISCOVERING':
    case 'READY':
    case 'DEGRADED':
    case 'UNAVAILABLE':
    case 'LEGACY':
      return status.connectionState
    default:
      return null
  }
}

function isRetrievalProfileStatus(value: unknown): value is RetrievalProfileStatus {
  if (!value || typeof value !== 'object') return false
  const profile = value as Partial<RetrievalProfileStatus>
  return (
    typeof profile.id === 'string'
    && profile.id.length > 0
    && profile.id.trim() === profile.id
    && typeof profile.label === 'string'
    && profile.label.length > 0
    && (profile.kind === 'lexical' || profile.kind === 'vector' || profile.kind === 'hybrid')
    && typeof profile.available === 'boolean'
    && (profile.reason === null || typeof profile.reason === 'string')
    && (profile.model === undefined || typeof profile.model === 'string')
    && (
      profile.dimensions === undefined
      || (typeof profile.dimensions === 'number' && Number.isFinite(profile.dimensions))
    )
  )
}

function retrievalKindFromId(profileId: string): RetrievalKind {
  if (profileId.startsWith('vector_')) return 'vector'
  if (profileId.startsWith('hybrid_')) return 'hybrid'
  return 'lexical'
}

function fixedScore(value: number | null | undefined): string {
  return Number(value || 0).toFixed(3)
}
