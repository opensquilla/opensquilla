import { KNOWLEDGE_API_BASE, type FetchLike } from './knowledgeUpload'

export interface KnowledgeLibraryStats {
  filesIndexed: number
  chunksIndexed: number
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number'
    && Number.isFinite(value)
    && Number.isInteger(value)
    && value >= 0
}

export function parseKnowledgeLibraryStats(value: unknown): KnowledgeLibraryStats {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Knowledge API returned invalid library stats')
  }
  const body = value as Record<string, unknown>
  if (!nonNegativeInteger(body.filesIndexed) || !nonNegativeInteger(body.chunksIndexed)) {
    throw new Error('Knowledge API returned invalid library stats')
  }
  return {
    filesIndexed: body.filesIndexed,
    chunksIndexed: body.chunksIndexed,
  }
}

export async function getKnowledgeLibraryStats(
  fetcher: FetchLike = fetch,
): Promise<KnowledgeLibraryStats> {
  const response = await fetcher(`${KNOWLEDGE_API_BASE}/stats`, {
    credentials: 'same-origin',
  })
  if (!response.ok) throw new Error(`Knowledge API request failed (${response.status})`)
  return parseKnowledgeLibraryStats(await response.json())
}
