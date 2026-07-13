// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import i18n from '@/i18n'

const rpcMock = vi.hoisted(() => ({
  call: vi.fn(),
  waitForConnection: vi.fn(),
}))

vi.mock('@/stores/rpc', () => ({
  useRpcStore: () => rpcMock,
}))

import KnowledgeView from './KnowledgeView.vue'
import {
  buildSearchProfilePayload,
  canSaveDefault,
  defaultProfileDraftFromStatus,
  defaultRetrievalProfileId,
  fallbackActive,
  formatResultScoreMeta,
  formatResultScorePrimary,
  queryOverrideOptions,
  retrievalProfilesFromStatus,
  searchProgressLabel,
  selectedRetrievalProfile,
} from './knowledgeRetrieval'

const READY_STATUS = {
  connectionState: 'READY' as const,
  capabilitiesStale: false,
  configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
  effectiveDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
  defaultFallbackReason: null,
  retrievalProfiles: [
    {
      id: 'sqlite_fts5_default',
      label: 'SQLite FTS5',
      kind: 'lexical' as const,
      available: true,
      reason: null,
    },
    {
      id: 'hybrid_rrf_bge_m3_fts5',
      label: 'Hybrid RRF',
      kind: 'hybrid' as const,
      available: true,
      reason: null,
      model: 'baai/bge-m3',
      dimensions: 1024,
    },
    {
      id: 'vector_bge_m3_1024',
      label: 'Vector bge-m3',
      kind: 'vector' as const,
      available: false,
      reason: 'vector_index_empty',
      model: 'baai/bge-m3',
      dimensions: 1024,
    },
  ],
}

describe('knowledge retrieval capability state helpers', () => {
  it('derives the editable default draft only from READY configured state', () => {
    expect(defaultProfileDraftFromStatus(READY_STATUS)).toBe('hybrid_rrf_bge_m3_fts5')
    expect(defaultProfileDraftFromStatus({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: 'configured_but_unavailable',
    })).toBe('configured_but_unavailable')
    expect(defaultProfileDraftFromStatus({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: null,
      defaultRetrievalProfile: 'legacy_must_not_become_editable',
    })).toBe('')
    expect(defaultProfileDraftFromStatus({
      ...READY_STATUS,
      connectionState: 'DEGRADED',
    })).toBe('')
    expect(defaultProfileDraftFromStatus({
      connectionState: 'LEGACY',
      defaultRetrievalProfile: 'sqlite_fts5_default',
    })).toBe('')
  })

  it('offers query overrides only for available READY service profiles', () => {
    expect(queryOverrideOptions(READY_STATUS).map((profile) => profile.id)).toEqual([
      'sqlite_fts5_default',
      'hybrid_rrf_bge_m3_fts5',
    ])
    expect(queryOverrideOptions({
      ...READY_STATUS,
      connectionState: 'DEGRADED',
    })).toEqual([])
    expect(queryOverrideOptions({ connectionState: 'LEGACY' })).toEqual([])
    expect(queryOverrideOptions(null)).toEqual([])
  })

  it('allows default saves only while READY has an available service profile', () => {
    const noAvailableProfiles = {
      ...READY_STATUS,
      retrievalProfiles: READY_STATUS.retrievalProfiles.map((profile) => ({
        ...profile,
        available: false,
      })),
    }

    expect(canSaveDefault(READY_STATUS)).toBe(true)
    expect(canSaveDefault({ ...READY_STATUS, capabilitiesStale: false })).toBe(true)
    expect(canSaveDefault({ ...READY_STATUS, capabilitiesStale: true })).toBe(false)
    expect(canSaveDefault({ ...READY_STATUS, capabilitiesStale: undefined })).toBe(false)
    expect(canSaveDefault({
      ...READY_STATUS,
      capabilitiesStale: 'false',
    } as unknown as Parameters<typeof canSaveDefault>[0])).toBe(false)
    expect(canSaveDefault({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: undefined,
      defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    })).toBe(false)
    expect(canSaveDefault(noAvailableProfiles)).toBe(false)
    expect(canSaveDefault({ ...READY_STATUS, connectionState: 'DEGRADED' })).toBe(false)
    expect(canSaveDefault({ connectionState: 'LEGACY' })).toBe(false)
    expect(canSaveDefault(null)).toBe(false)
  })

  it('reports service fallback only for connected states with a safe reason', () => {
    const readyFallbackStatus = {
      ...READY_STATUS,
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
      defaultFallbackReason: 'configured_default_unavailable',
    }
    const malformedReason = {
      ...READY_STATUS,
      defaultFallbackReason: ['SECRET must not be coerced'],
    } as unknown as Parameters<typeof fallbackActive>[0]

    expect(fallbackActive(readyFallbackStatus)).toBe(true)
    expect(fallbackActive({
      ...READY_STATUS,
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
      defaultFallbackReason: null,
    })).toBe(true)
    expect(fallbackActive({
      ...READY_STATUS,
      effectiveDefaultRetrievalProfile: null,
      defaultFallbackReason: null,
    })).toBe(true)
    expect(fallbackActive(READY_STATUS)).toBe(false)
    expect(fallbackActive({
      ...readyFallbackStatus,
      connectionState: 'DEGRADED',
    })).toBe(true)
    expect(fallbackActive({
      ...readyFallbackStatus,
      connectionState: 'LEGACY',
    })).toBe(false)
    expect(fallbackActive(malformedReason)).toBe(false)
    expect(fallbackActive(null)).toBe(false)
  })

  it('fails closed for missing, transitional, unavailable, legacy, and unknown states', () => {
    const legacyStatus = {
      connectionState: 'LEGACY' as const,
      defaultRetrievalProfile: 'sqlite_fts5_default',
      retrievalProfiles: READY_STATUS.retrievalProfiles,
    }
    const unknownStatus = {
      connectionState: 'SURPRISE',
      retrievalProfiles: READY_STATUS.retrievalProfiles,
    } as unknown as Parameters<typeof retrievalProfilesFromStatus>[0]

    expect(retrievalProfilesFromStatus(null)).toEqual([])
    expect(retrievalProfilesFromStatus({ connectionState: 'DISCOVERING' })).toEqual([])
    expect(retrievalProfilesFromStatus({ connectionState: 'UNAVAILABLE' })).toEqual([])
    expect(retrievalProfilesFromStatus(legacyStatus)).toEqual([])
    expect(retrievalProfilesFromStatus(unknownStatus)).toEqual([])

    expect(buildSearchProfilePayload(null, '')).toBeNull()
    expect(buildSearchProfilePayload({ connectionState: 'DISCOVERING' }, '')).toBeNull()
    expect(buildSearchProfilePayload({ connectionState: 'UNAVAILABLE' }, '')).toBeNull()
    expect(buildSearchProfilePayload(unknownStatus, '')).toBeNull()
  })

  it('does not synthesize a selectable profile from legacy fields', () => {
    const legacyStatus = {
      connectionState: 'LEGACY' as const,
      defaultRetrievalProfile: 'sqlite_fts5_default',
      retrievalProfiles: READY_STATUS.retrievalProfiles,
    }

    expect(selectedRetrievalProfile(legacyStatus, 'sqlite_fts5_default')).toBeNull()
    expect(defaultRetrievalProfileId(legacyStatus)).toBe('')
  })

  it('keeps degraded profiles read-only and only allows service-default searches', () => {
    const degradedStatus = {
      ...READY_STATUS,
      connectionState: 'DEGRADED' as const,
      capabilitiesStale: true,
    }
    const legacyStatus = {
      connectionState: 'LEGACY' as const,
      defaultRetrievalProfile: 'sqlite_fts5_default',
      retrievalProfiles: READY_STATUS.retrievalProfiles,
    }

    expect(retrievalProfilesFromStatus(degradedStatus)).toEqual(READY_STATUS.retrievalProfiles)
    expect(buildSearchProfilePayload(degradedStatus, '')).toEqual({})
    expect(buildSearchProfilePayload(degradedStatus, 'sqlite_fts5_default')).toEqual({})
    expect(buildSearchProfilePayload(legacyStatus, '')).toEqual({})
    expect(buildSearchProfilePayload(legacyStatus, 'sqlite_fts5_default')).toEqual({})
  })

  it('builds READY search overrides only for available service profiles', () => {
    const before = structuredClone(READY_STATUS)

    expect(buildSearchProfilePayload(READY_STATUS, '')).toEqual({})
    expect(buildSearchProfilePayload(READY_STATUS, 'sqlite_fts5_default')).toEqual({
      retrievalProfile: 'sqlite_fts5_default',
    })
    expect(buildSearchProfilePayload(READY_STATUS, 'hybrid_rrf_bge_m3_fts5')).toEqual({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    })
    expect(buildSearchProfilePayload(READY_STATUS, 'vector_bge_m3_1024')).toBeNull()
    expect(buildSearchProfilePayload(READY_STATUS, 'missing_profile')).toBeNull()
    expect(READY_STATUS).toEqual(before)
  })

  it('fails closed for READY statuses without valid available profiles', () => {
    const noAvailableProfiles = {
      ...READY_STATUS,
      retrievalProfiles: READY_STATUS.retrievalProfiles.map((profile) => ({
        ...profile,
        available: false,
      })),
    }
    const malformedStatus = {
      connectionState: 'READY',
      retrievalProfiles: [
        null,
        { id: '', label: 'empty', kind: 'lexical', available: true, reason: null },
        { id: 'bad-kind', label: 'bad', kind: 'sql', available: true, reason: null },
      ],
    } as unknown as Parameters<typeof retrievalProfilesFromStatus>[0]

    expect(buildSearchProfilePayload(noAvailableProfiles, '')).toBeNull()
    expect(retrievalProfilesFromStatus(malformedStatus)).toEqual([])
    expect(buildSearchProfilePayload(malformedStatus, '')).toBeNull()
  })
})

describe('knowledge retrieval helpers', () => {
  it('uses service retrievalProfiles when status exposes them', () => {
    const profiles = retrievalProfilesFromStatus({
      connectionState: 'READY',
      retrievalProfiles: [
        {
          id: 'sqlite_fts5_default',
          label: 'SQLite FTS5',
          kind: 'lexical' as const,
          available: true,
          reason: null,
        },
        {
          id: 'hybrid_rrf_bge_m3_fts5',
          label: 'Hybrid RRF',
          kind: 'hybrid' as const,
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

  it('does not synthesize FTS when status has no retrievalProfiles', () => {
    expect(retrievalProfilesFromStatus({ connectionState: 'READY' })).toEqual([])
  })

  it('selects service default when it is available', () => {
    expect(
      defaultRetrievalProfileId({
        connectionState: 'READY',
        configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        retrievalProfiles: [
          {
            id: 'sqlite_fts5_default',
            label: 'SQLite FTS5',
            kind: 'lexical' as const,
            available: true,
            reason: null,
          },
          {
            id: 'hybrid_rrf_bge_m3_fts5',
            label: 'Hybrid RRF',
            kind: 'hybrid' as const,
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
        connectionState: 'READY',
        configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        retrievalProfiles: [
          {
            id: 'sqlite_fts5_default',
            label: 'SQLite FTS5',
            kind: 'lexical' as const,
            available: true,
            reason: null,
          },
          {
            id: 'hybrid_rrf_bge_m3_fts5',
            label: 'Hybrid RRF',
            kind: 'hybrid' as const,
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
          connectionState: 'READY',
          configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical' as const,
              available: false,
              reason: 'fts_index_empty',
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
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

  it('builds search payload without embedding metadata', () => {
    expect(
      buildSearchProfilePayload(
        {
          connectionState: 'READY',
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
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
    })
  })

  it('rejects an unknown explicit search profile without changing progress fallback', () => {
    expect(
      buildSearchProfilePayload(
        {
          connectionState: 'READY',
          configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical' as const,
              available: true,
              reason: null,
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'missing_profile',
      ),
    ).toBeNull()
    expect(
      searchProgressLabel(
        {
          connectionState: 'READY',
          configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical' as const,
              available: true,
              reason: null,
            },
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
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

  it('rejects a disabled explicit search profile', () => {
    expect(
      buildSearchProfilePayload(
        {
          connectionState: 'READY',
          configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
              available: true,
              reason: null,
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector' as const,
              available: false,
              reason: 'vector_index_empty',
              model: 'baai/bge-m3',
              dimensions: 1024,
            },
          ],
        },
        'vector_bge_m3_1024',
      ),
    ).toBeNull()
  })

  it('uses lexical progress label when selected vector profile is disabled', () => {
    expect(
      searchProgressLabel(
        {
          connectionState: 'READY',
          configuredDefaultRetrievalProfile: 'sqlite_fts5_default',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical' as const,
              available: true,
              reason: null,
            },
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector' as const,
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

  it('does not build a search payload when all service profiles are unavailable', () => {
    const allUnavailableStatus = {
      connectionState: 'READY' as const,
      configuredDefaultRetrievalProfile: 'vector_bge_m3_1024',
      retrievalProfiles: [
        {
          id: 'vector_bge_m3_1024',
          label: 'Vector bge-m3',
          kind: 'vector' as const,
          available: false,
          reason: 'vector_index_empty',
          model: 'baai/bge-m3',
          dimensions: 1024,
        },
        {
          id: 'hybrid_rrf_bge_m3_fts5',
          label: 'Hybrid RRF',
          kind: 'hybrid' as const,
          available: false,
          reason: 'fts_or_vector_index_empty',
          model: 'baai/bge-m3',
          dimensions: 1024,
        },
      ],
    }

    expect(buildSearchProfilePayload(allUnavailableStatus, 'vector_bge_m3_1024')).toBeNull()
    expect(defaultRetrievalProfileId(allUnavailableStatus, 'missing_profile')).toBe('vector_bge_m3_1024')
  })

  it('formats hybrid and vector scores from resolved profile kind', () => {
    const hybridProfile = {
      id: 'hybrid_rrf_bge_m3_fts5',
      label: 'Hybrid RRF',
      kind: 'hybrid' as const,
      available: true,
      reason: null,
    }
    const vectorProfile = {
      id: 'vector_bge_m3_1024',
      label: 'Vector bge-m3',
      kind: 'vector' as const,
      available: true,
      reason: null,
    }

    expect(
      formatResultScorePrimary(
        {
          score: 0.022529,
          fusionScore: 0.022529,
          retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
        },
        hybridProfile,
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
        hybridProfile,
      ),
    ).toEqual([
      { label: 'BM25', value: '-12.346' },
      { label: 'Vector', value: '#4' },
      { label: 'Vector score', value: '0.789' },
    ])

    expect(
      formatResultScorePrimary(
        {
          score: 0.5,
          vectorScore: 0.81234,
          retrievalProfile: 'vector_bge_m3_1024',
        },
        vectorProfile,
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
        vectorProfile,
      ),
    ).toEqual([
      { label: 'Vector', value: '#2' },
      { label: 'Vector score', value: '0.812' },
    ])
  })

  it('formats custom hybrid profile ids by kind', () => {
    const customHybridProfile = {
      id: 'hybrid_custom_rrf',
      label: 'Custom Hybrid',
      kind: 'hybrid' as const,
      available: true,
      reason: null,
    }

    expect(
      formatResultScorePrimary(
        {
          score: 0.11,
          fusionScore: 0.4567,
          retrievalProfile: 'hybrid_custom_rrf',
        },
        customHybridProfile,
      ),
    ).toBe('fusion 0.457')
    expect(
      formatResultScoreMeta(
        {
          score: 0.11,
          bm25Rank: -3.2,
          vectorRank: 3,
          vectorScore: 0.7654,
          fusionScore: 0.4567,
          retrievalProfile: 'hybrid_custom_rrf',
        },
        customHybridProfile,
      ),
    ).toEqual([
      { label: 'BM25', value: '-3.200' },
      { label: 'Vector', value: '#3' },
      { label: 'Vector score', value: '0.765' },
    ])
  })

  it('uses embedding retrieval label for vector and hybrid searches', () => {
    expect(
      searchProgressLabel(
        {
          connectionState: 'READY',
          retrievalProfiles: [
            {
              id: 'vector_bge_m3_1024',
              label: 'Vector bge-m3',
              kind: 'vector' as const,
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
          connectionState: 'READY',
          retrievalProfiles: [
            {
              id: 'hybrid_rrf_bge_m3_fts5',
              label: 'Hybrid RRF',
              kind: 'hybrid' as const,
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
          connectionState: 'READY',
          retrievalProfiles: [
            {
              id: 'sqlite_fts5_default',
              label: 'SQLite FTS5',
              kind: 'lexical' as const,
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


const mountedApps: App<Element>[] = []

const SERVICE_PROFILES = [
  {
    id: 'sqlite_fts5_default',
    label: 'SQLite FTS5',
    kind: 'lexical' as const,
    available: true,
    reason: null,
  },
  {
    id: 'hybrid_rrf_bge_m3_fts5',
    label: 'Hybrid RRF',
    kind: 'hybrid' as const,
    available: true,
    reason: null,
    model: 'baai/bge-m3',
    dimensions: 1024,
  },
  {
    id: 'vector_bge_m3_1024',
    label: 'Vector bge-m3',
    kind: 'vector' as const,
    available: false,
    reason: 'vector_index_empty',
    model: 'baai/bge-m3',
    dimensions: 1024,
  },
]

function statusPayload(overrides: Record<string, unknown> = {}) {
  return {
    connectionState: 'READY',
    capabilitiesStale: false,
    configuredDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    effectiveDefaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    defaultFallbackReason: null,
    rootDir: '/mnt/data/datasets',
    documentsIndexed: 3,
    chunksIndexed: 12,
    filesIndexed: 3,
    pipeline: 'test pipeline',
    indexProfiles: ['sqlite_fts5_default'],
    vectorChunksIndexed: 12,
    vectorCoveragePct: 100,
    embeddingModel: 'baai/bge-m3',
    embeddingDimensions: 1024,
    retrievalProfiles: SERVICE_PROFILES,
    defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    ...overrides,
  }
}

function searchResult(overrides: Record<string, unknown> = {}) {
  return {
    evidenceId: 'ev-1',
    documentId: 'doc-1',
    chunkId: 'chunk-1',
    title: 'Annual filing',
    source: 'filing.pdf',
    sourcePath: '/mnt/data/datasets/filing.pdf',
    pageStart: 1,
    pageEnd: 1,
    section: null,
    snippet: 'Revenue increased in the quarter.',
    score: 0.022529,
    bm25Rank: -12.34567,
    vectorRank: 2,
    vectorScore: 0.81234,
    fusionScore: 0.022529,
    citation: 'filing.pdf#p1',
    languageBucket: 'en',
    chunkingStrategy: 'paragraph',
    ...overrides,
  }
}

async function flushUi(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

async function mountKnowledgeView(options: { status?: Record<string, unknown>; rawStatus?: Record<string, unknown>; results?: Array<Record<string, unknown>> } = {}) {
  const status = options.rawStatus || statusPayload(options.status)
  const results = options.results || [searchResult()]

  rpcMock.waitForConnection.mockResolvedValue(undefined)
  rpcMock.call.mockImplementation(async (method: string) => {
    if (method === 'knowledge.status') return status
    if (method === 'knowledge.questions') return { questions: [] }
    if (method === 'tools.catalog') return { tools: [{ name: 'knowledge_search' }] }
    if (method === 'knowledge.search') return { results }
    if (method === 'knowledge.ingest') return { jobId: 'job-1' }
    throw new Error(`Unexpected RPC method: ${method}`)
  })

  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(KnowledgeView)
  app.use(i18n)
  app.mount(el)
  mountedApps.push(app)
  await flushUi()
  return { el }
}

function retrievalSelect(el: HTMLElement): HTMLSelectElement {
  const select = el.querySelector<HTMLSelectElement>('.rag-source-panel select.control-input')
  if (!select) throw new Error('retrieval select not found')
  return select
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  element.value = value
  element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
}

function rpcCall(method: string): unknown[] | undefined {
  return rpcMock.call.mock.calls.find((call) => call[0] === method)
}

beforeEach(() => {
  document.body.innerHTML = ''
  rpcMock.call.mockReset()
  rpcMock.waitForConnection.mockReset()
})

afterEach(() => {
  while (mountedApps.length) {
    mountedApps.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('KnowledgeView retrieval UI wiring', () => {
  it('renders service retrieval profiles and keeps the current profile when available', async () => {
    const { el } = await mountKnowledgeView()
    const select = retrievalSelect(el)

    expect(select.value).toBe('sqlite_fts5_default')
    expect(Array.from(select.options).map((option) => ({
      value: option.value,
      text: option.textContent?.trim(),
      disabled: option.disabled,
    }))).toEqual([
      { value: 'sqlite_fts5_default', text: 'SQLite FTS5', disabled: false },
      { value: 'hybrid_rrf_bge_m3_fts5', text: 'Hybrid RRF', disabled: false },
      { value: 'vector_bge_m3_1024', text: 'Vector bge-m3 (vector_index_empty)', disabled: true },
    ])
  })

  it('sends only the selected retrieval profile and renders scores using its kind', async () => {
    const { el } = await mountKnowledgeView({ results: [searchResult({ retrievalProfile: null })] })
    setInputValue(retrievalSelect(el), 'hybrid_rrf_bge_m3_fts5')
    await flushUi()

    const query = el.querySelector<HTMLTextAreaElement>('.rag-searchbar__query')
    if (!query) throw new Error('search query input not found')
    setInputValue(query, 'What changed in revenue?')
    await flushUi()

    const form = el.querySelector<HTMLFormElement>('form.rag-searchbar')
    if (!form) throw new Error('search form not found')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushUi()

    const searchPayload = rpcCall('knowledge.search')?.[1]
    expect(searchPayload).toMatchObject({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    })
    expect(searchPayload).not.toHaveProperty('embeddingModel')
    expect(searchPayload).not.toHaveProperty('embeddingDimensions')
    expect(el.textContent).toContain('fusion 0.023')
    expect(el.textContent).toContain('Vector #2')
    expect(el.textContent).not.toContain('Vector#2')
  })

  it('keeps ingest index profile separate from the selected retrieval profile', async () => {
    const { el } = await mountKnowledgeView()
    setInputValue(retrievalSelect(el), 'hybrid_rrf_bge_m3_fts5')
    await flushUi()

    const buildButton = Array.from(el.querySelectorAll<HTMLButtonElement>('.rag-source-panel button.btn--primary'))
      .find((button) => button.textContent?.includes('Build collection'))
    if (!buildButton) throw new Error('build collection button not found')
    buildButton.click()
    await flushUi()

    expect(rpcCall('knowledge.ingest')?.[1]).toMatchObject({
      indexProfiles: ['sqlite_fts5_default'],
    })
  })

  it('disables search and avoids RPC when service profiles are all unavailable', async () => {
    const { el } = await mountKnowledgeView({
      status: {
        retrievalProfiles: [
          {
            id: 'vector_bge_m3_1024',
            label: 'Vector bge-m3',
            kind: 'vector' as const,
            available: false,
            reason: 'vector_index_empty',
            model: 'baai/bge-m3',
            dimensions: 1024,
          },
          {
            id: 'hybrid_custom_rrf',
            label: 'Custom Hybrid',
            kind: 'hybrid' as const,
            available: false,
            reason: 'fts_or_vector_index_empty',
            model: 'baai/bge-m3',
            dimensions: 1024,
          },
        ],
        defaultRetrievalProfile: 'vector_bge_m3_1024',
      },
    })

    const query = el.querySelector<HTMLTextAreaElement>('.rag-searchbar__query')
    if (!query) throw new Error('search query input not found')
    setInputValue(query, 'Can I search?')
    await flushUi()

    const button = el.querySelector<HTMLButtonElement>('form.rag-searchbar button[type="submit"]')
    if (!button) throw new Error('search button not found')
    expect(button.disabled).toBe(true)

    const form = el.querySelector<HTMLFormElement>('form.rag-searchbar')
    if (!form) throw new Error('search form not found')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushUi()

    expect(rpcMock.call.mock.calls.filter((call) => call[0] === 'knowledge.search')).toHaveLength(0)
    expect(el.textContent).toContain('No retrieval profile available')
  })

  it('does not mark embedding ready when no vectors are indexed', async () => {
    const { el } = await mountKnowledgeView({
      status: {
        vectorChunksIndexed: 0,
        vectorCoveragePct: 0,
        embeddingModel: 'baai/bge-m3',
        embeddingDimensions: 1024,
      },
    })

    const embeddingCard = Array.from(el.querySelectorAll<HTMLElement>('.control-stat'))
      .find((card) => card.querySelector('.control-stat__label')?.textContent?.trim() === 'Embedding')
    if (!embeddingCard) throw new Error('embedding metric not found')

    expect(embeddingCard.textContent).toContain('Missing')
    expect(embeddingCard.textContent).not.toContain('Ready')
    expect(embeddingCard.classList.contains('control-stat--warn')).toBe(true)
  })

  it('shows unknown embedding status without warning class for legacy status payloads', async () => {
    const { el } = await mountKnowledgeView({
      rawStatus: {
        rootDir: '/mnt/data/datasets',
        documentsIndexed: 3,
        chunksIndexed: 12,
        filesIndexed: 3,
        pipeline: 'legacy pipeline',
        indexProfiles: ['sqlite_fts5_default'],
      },
    })

    const embeddingCard = Array.from(el.querySelectorAll<HTMLElement>('.control-stat'))
      .find((card) => card.querySelector('.control-stat__label')?.textContent?.trim() === 'Embedding')
    if (!embeddingCard) throw new Error('embedding metric not found')

    expect(embeddingCard.textContent).toContain('Unknown')
    expect(embeddingCard.textContent).not.toContain('Missing')
    expect(embeddingCard.classList.contains('control-stat--warn')).toBe(false)
  })
})
