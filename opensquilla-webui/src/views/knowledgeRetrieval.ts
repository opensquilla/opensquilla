export type RetrievalKind = 'lexical' | 'vector' | 'hybrid'

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
  retrievalProfile: string
  embeddingModel?: string
  embeddingDimensions?: number
}

export interface ResultScoreMeta {
  label: string
  value: string
}

type RetrievalProfileScoreHint = RetrievalProfileStatus | string | null | undefined

export const FALLBACK_RETRIEVAL_PROFILE: RetrievalProfileStatus = {
  id: 'sqlite_fts5_default',
  label: 'SQLite FTS5',
  kind: 'lexical',
  available: true,
  reason: null,
}

function serviceRetrievalProfiles(
  status: KnowledgeStatusLike | null | undefined,
): RetrievalProfileStatus[] {
  return status?.retrievalProfiles?.filter((profile) => profile?.id) || []
}

export function retrievalProfilesFromStatus(
  status: KnowledgeStatusLike | null | undefined,
): RetrievalProfileStatus[] {
  const profiles = serviceRetrievalProfiles(status)
  return profiles.length ? profiles : [FALLBACK_RETRIEVAL_PROFILE]
}

function availableRetrievalProfile(
  status: KnowledgeStatusLike | null | undefined,
  currentProfileId = '',
): RetrievalProfileStatus | undefined {
  const serviceProfiles = serviceRetrievalProfiles(status)
  const profiles = serviceProfiles.length ? serviceProfiles : [FALLBACK_RETRIEVAL_PROFILE]
  if (currentProfileId) {
    const currentProfile = profiles.find(
      (profile) => profile.id === currentProfileId && profile.available,
    )
    if (currentProfile) {
      return currentProfile
    }
  }
  const serviceDefault = status?.defaultRetrievalProfile
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
  if (!serviceRetrievalProfiles(status).length) {
    return FALLBACK_RETRIEVAL_PROFILE
  }
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

  const serviceProfiles = serviceRetrievalProfiles(status)
  if (serviceProfiles.length) {
    const currentProfile = serviceProfiles.find((profile) => profile.id === currentProfileId)
    if (currentProfile) {
      return currentProfile.id
    }
    const serviceDefault = status?.defaultRetrievalProfile
    const defaultProfile = serviceProfiles.find((profile) => profile.id === serviceDefault)
    return defaultProfile?.id || serviceProfiles[0].id
  }

  return FALLBACK_RETRIEVAL_PROFILE.id
}

export function buildSearchProfilePayload(
  status: KnowledgeStatusLike | null | undefined,
  profileId: string,
): SearchProfilePayload | null {
  const profile = selectedRetrievalProfile(status, profileId)
  if (!profile) return null
  return {
    retrievalProfile: profile.id,
    ...(profile.model ? { embeddingModel: profile.model } : {}),
    ...(profile.dimensions ? { embeddingDimensions: profile.dimensions } : {}),
  }
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
  if (!profile) return FALLBACK_RETRIEVAL_PROFILE.id
  return typeof profile === 'string' ? profile : profile.id
}

function retrievalKindFromId(profileId: string): RetrievalKind {
  if (profileId.startsWith('vector_')) return 'vector'
  if (profileId.startsWith('hybrid_')) return 'hybrid'
  return 'lexical'
}

function fixedScore(value: number | null | undefined): string {
  return Number(value || 0).toFixed(3)
}
