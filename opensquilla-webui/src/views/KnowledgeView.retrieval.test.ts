import { describe, expect, it } from 'vitest'
import {
  buildSearchProfilePayload,
  defaultRetrievalProfileId,
  formatResultScoreMeta,
  formatResultScorePrimary,
  retrievalProfilesFromStatus,
  searchProgressLabel,
} from './knowledgeRetrieval'

describe('knowledge retrieval helpers', () => {
  it('uses service retrievalProfiles when status exposes them', () => {
    const profiles = retrievalProfilesFromStatus({
      retrievalProfiles: [
        {
          id: 'sqlite_fts5_default',
          label: 'SQLite FTS5',
          kind: 'lexical',
          available: true,
          reason: null,
        },
        {
          id: 'hybrid_rrf_bge_m3_fts5',
          label: 'Hybrid RRF',
          kind: 'hybrid',
          available: true,
          reason: null,
          model: 'baai/bge-m3',
          dimensions: 1024,
        },
      ],
    })

    expect(profiles.map((profile) => profile.id)).toEqual([
      'sqlite_fts5_default',
      'hybrid_rrf_bge_m3_fts5',
    ])
  })

  it('falls back to FTS when status has no retrievalProfiles', () => {
    expect(retrievalProfilesFromStatus({}).map((profile) => profile.id)).toEqual([
      'sqlite_fts5_default',
    ])
  })

  it('selects service default when it is available', () => {
    expect(
      defaultRetrievalProfileId({
        defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        retrievalProfiles: [
          {
            id: 'sqlite_fts5_default',
            label: 'SQLite FTS5',
            kind: 'lexical',
            available: true,
            reason: null,
          },
          {
            id: 'hybrid_rrf_bge_m3_fts5',
            label: 'Hybrid RRF',
            kind: 'hybrid',
            available: true,
            reason: null,
            model: 'baai/bge-m3',
            dimensions: 1024,
          },
        ],
      }),
    ).toBe('hybrid_rrf_bge_m3_fts5')
  })

  it('skips disabled service default and selects first available profile', () => {
    expect(
      defaultRetrievalProfileId({
        defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        retrievalProfiles: [
          {
            id: 'sqlite_fts5_default',
            label: 'SQLite FTS5',
            kind: 'lexical',
            available: true,
            reason: null,
          },
          {
            id: 'hybrid_rrf_bge_m3_fts5',
            label: 'Hybrid RRF',
            kind: 'hybrid',
            available: false,
            reason: 'fts_or_vector_index_empty',
            model: 'baai/bge-m3',
            dimensions: 1024,
          },
        ],
      }),
    ).toBe('sqlite_fts5_default')
  })

  it('skips disabled current profile and selects available service default', () => {
    expect(
      defaultRetrievalProfileId(
        {
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical',
              available: false,
              reason: 'fts_index_empty',
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'sqlite_fts5_default',
      ),
    ).toBe('hybrid_rrf_bge_m3_fts5')
  })

  it('builds search payload with selected embedding metadata', () => {
    expect(
      buildSearchProfilePayload(
        {
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'hybrid_rrf_bge_m3_fts5',
      ),
    ).toEqual({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
      embeddingModel: 'baai/bge-m3',
      embeddingDimensions: 1024,
    })
  })

  it('uses service default metadata when selected profile is unknown', () => {
    expect(
      buildSearchProfilePayload(
        {
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical',
              available: true,
              reason: null,
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'missing_profile',
      ),
    ).toEqual({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
      embeddingModel: 'baai/bge-m3',
      embeddingDimensions: 1024,
    })
    expect(
      searchProgressLabel(
        {
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical',
              available: true,
              reason: null,
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'missing_profile',
      ),
    ).toBe('Embedding retrieval')
  })

  it('uses service default metadata when selected profile is disabled', () => {
    expect(
      buildSearchProfilePayload(
        {
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector',
              available: false,
              reason: 'vector_index_empty',
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'vector_bge_m3_1024',
      ),
    ).toEqual({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
      embeddingModel: 'baai/bge-m3',
      embeddingDimensions: 1024,
    })
  })

  it('uses lexical progress label when selected vector profile is disabled', () => {
    expect(
      searchProgressLabel(
        {
          defaultRetrievalProfile: 'sqlite_fts5_default',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical',
              available: true,
              reason: null,
            },
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector',
              available: false,
              reason: 'vector_index_empty',
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'vector_bge_m3_1024',
      ),
    ).toBe('Searching')
  })

  it('uses fallback payload when all service profiles are unavailable', () => {
    expect(
      buildSearchProfilePayload(
        {
          defaultRetrievalProfile: 'vector_bge_m3_1024',
          retrievalProfiles: [
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector',
              available: false,
              reason: 'vector_index_empty',
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: false,
              reason: 'fts_or_vector_index_empty',
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'vector_bge_m3_1024',
      ),
    ).toEqual({
      retrievalProfile: 'sqlite_fts5_default',
    })
  })

  it('formats hybrid and vector scores', () => {
    expect(
      formatResultScorePrimary(
        {
          score: 0.022529,
          fusionScore: 0.022529,
          retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        },
        'sqlite_fts5_default',
      ),
    ).toBe('fusion 0.023')
    expect(
      formatResultScoreMeta(
        {
          score: 0.022529,
          bm25Rank: -12.34567,
          vectorRank: 4,
          vectorScore: 0.78912,
          fusionScore: 0.022529,
          retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        },
        'sqlite_fts5_default',
      ),
    ).toEqual(['BM25 -12.346', 'Vector #4', 'Vector score 0.789'])

    expect(
      formatResultScorePrimary(
        {
          score: 0.5,
          vectorScore: 0.81234,
          retrievalProfile: 'vector_bge_m3_1024',
        },
        'sqlite_fts5_default',
      ),
    ).toBe('vector 0.812')
    expect(
      formatResultScoreMeta(
        {
          score: 0.5,
          bm25Rank: 7,
          vectorRank: 2,
          vectorScore: 0.81234,
          retrievalProfile: 'vector_bge_m3_1024',
        },
        'sqlite_fts5_default',
      ),
    ).toEqual(['Vector #2', 'Vector score 0.812'])
  })

  it('uses embedding retrieval label for vector and hybrid searches', () => {
    expect(
      searchProgressLabel(
        {
          retrievalProfiles: [
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'vector_bge_m3_1024',
      ),
    ).toBe('Embedding retrieval')

    expect(
      searchProgressLabel(
        {
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid',
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'hybrid_rrf_bge_m3_fts5',
      ),
    ).toBe('Embedding retrieval')
  })

  it('uses searching progress label for lexical and fallback retrieval', () => {
    expect(
      searchProgressLabel(
        {
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical',
              available: true,
              reason: null,
            },
          ],
        },
        'sqlite_fts5_default',
      ),
    ).toBe('Searching')
    expect(searchProgressLabel({}, 'missing_profile')).toBe('Searching')
  })
})
