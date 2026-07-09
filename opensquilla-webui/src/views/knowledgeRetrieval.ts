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
  const profiles = retrievalProfilesFromStatus(status)
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
): RetrievalProfileStatus {
  if (!serviceRetrievalProfiles(status).length) {
    return FALLBACK_RETRIEVAL_PROFILE
  }
  return availableRetrievalProfile(status, profileId) || FALLBACK_RETRIEVAL_PROFILE
}

export function defaultRetrievalProfileId(
  status: KnowledgeStatusLike | null | undefined,
  currentProfileId = '',
): string {
  return availableRetrievalProfile(status, currentProfileId)?.id || FALLBACK_RETRIEVAL_PROFILE.id
}

export function buildSearchProfilePayload(
  status: KnowledgeStatusLike | null | undefined,
  profileId: string,
): SearchProfilePayload {
  const profile = selectedRetrievalProfile(status, profileId)
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
  return profile.kind === 'vector' || profile.kind === 'hybrid'
    ? 'Embedding retrieval'
    : 'Searching'
}

export function formatResultScorePrimary(
  result: KnowledgeResultScoreLike,
  fallbackProfileId: string,
): string {
  const retrieval = result.retrievalProfile || fallbackProfileId
  if (retrieval.startsWith('vector_')) {
    return `vector ${fixedScore(result.vectorScore ?? result.score)}`
  }
  if (retrieval === 'hybrid_rrf_bge_m3_fts5') {
    return `fusion ${fixedScore(result.fusionScore ?? result.score)}`
  }
  return `lexical ${fixedScore(result.score)}`
}

export function formatResultScoreMeta(
  result: KnowledgeResultScoreLike,
  fallbackProfileId: string,
): string[] {
  const retrieval = result.retrievalProfile || fallbackProfileId
  const meta: string[] = []
  if (retrieval === 'hybrid_rrf_bge_m3_fts5' || retrieval === 'sqlite_fts5_default') {
    if (result.bm25Rank !== null && result.bm25Rank !== undefined) {
      meta.push(`BM25 ${fixedScore(result.bm25Rank)}`)
    }
  }
  if (retrieval.startsWith('vector_') || retrieval === 'hybrid_rrf_bge_m3_fts5') {
    if (result.vectorRank !== null && result.vectorRank !== undefined) {
      meta.push(`Vector #${result.vectorRank}`)
    }
    if (result.vectorScore !== null && result.vectorScore !== undefined) {
      meta.push(`Vector score ${fixedScore(result.vectorScore)}`)
    }
  }
  return meta
}

function fixedScore(value: number | null | undefined): string {
  return Number(value || 0).toFixed(3)
}
