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
    const malformedDefaults = {
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: [],
      effectiveDefaultRetrievalProfile: {},
      defaultFallbackReason: null,
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
    expect(fallbackActive({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: null,
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
      defaultFallbackReason: null,
    })).toBe(true)
    expect(fallbackActive({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: null,
      effectiveDefaultRetrievalProfile: null,
      defaultFallbackReason: null,
    })).toBe(false)
    expect(fallbackActive(READY_STATUS)).toBe(false)
    expect(fallbackActive({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: undefined,
      defaultFallbackReason: null,
    })).toBe(false)
    expect(fallbackActive({
      ...READY_STATUS,
      configuredDefaultRetrievalProfile: ' ',
      defaultFallbackReason: null,
    })).toBe(false)
    expect(fallbackActive({
      ...READY_STATUS,
      effectiveDefaultRetrievalProfile: undefined,
      defaultFallbackReason: null,
    })).toBe(false)
    expect(fallbackActive({
      ...READY_STATUS,
      effectiveDefaultRetrievalProfile: ' ',
      defaultFallbackReason: null,
    })).toBe(false)
    expect(fallbackActive({
      ...readyFallbackStatus,
      connectionState: 'DEGRADED',
    })).toBe(true)
    expect(fallbackActive({
      ...readyFallbackStatus,
      connectionState: 'LEGACY',
    })).toBe(false)
    expect(fallbackActive(malformedReason)).toBe(false)
    expect(fallbackActive(malformedDefaults)).toBe(false)
    expect(fallbackActive({
      ...malformedDefaults,
      defaultFallbackReason: 'service_fallback',
    })).toBe(true)
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

  it('preserves nullable runtime profile metadata without mutating status', () => {
    const runtimeStatus = {
      connectionState: 'READY' as const,
      retrievalProfiles: [
        {
          id: 'sqlite_fts5_default',
          label: 'SQLite FTS5',
          kind: 'lexical' as const,
          available: true,
          reason: null,
          model: null,
          dimensions: null,
        },
      ],
    }
    const before = structuredClone(runtimeStatus)

    expect(retrievalProfilesFromStatus(runtimeStatus)).toEqual(runtimeStatus.retrievalProfiles)
    expect(runtimeStatus).toEqual(before)
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

  it('rejects malformed and duplicate service profiles across connection states', () => {
    const validProfile = {
      id: 'sqlite_fts5_default',
      label: 'SQLite FTS5',
      kind: 'lexical' as const,
      available: true,
      reason: null,
    }
    const readyStatus = (profile: unknown) => ({
      connectionState: 'READY',
      retrievalProfiles: [profile],
    }) as unknown as Parameters<typeof retrievalProfilesFromStatus>[0]
    const duplicateIds = {
      connectionState: 'READY' as const,
      retrievalProfiles: [validProfile, { ...validProfile, label: 'Duplicate' }],
    }
    const disconnected = {
      connectionState: 'DISCONNECTED' as const,
      defaultRetrievalProfile: null,
      retrievalProfiles: [validProfile],
    }
    const integerDimensions = readyStatus({ ...validProfile, dimensions: -1 })

    for (const status of [
      readyStatus({ ...validProfile, label: '   ' }),
      readyStatus({ ...validProfile, label: ' SQLite FTS5 ' }),
      readyStatus({ ...validProfile, model: 42 }),
      readyStatus({ ...validProfile, dimensions: '1024' }),
      readyStatus({ ...validProfile, dimensions: 1024.5 }),
      duplicateIds,
    ]) {
      expect(retrievalProfilesFromStatus(status)).toEqual([])
      expect(buildSearchProfilePayload(status, '')).toBeNull()
    }
    expect(retrievalProfilesFromStatus(disconnected)).toEqual([])
    expect(buildSearchProfilePayload(disconnected, '')).toBeNull()
    expect(retrievalProfilesFromStatus(integerDimensions)).toEqual([
      { ...validProfile, dimensions: -1 },
    ])
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
    capabilitiesVersion: '0123456789abcdef',
    capabilitiesFetchedAt: 1_720_000_000_000,
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

interface MountKnowledgeViewOptions {
  status?: Record<string, unknown>
  rawStatus?: unknown
  statusResponse?: Promise<unknown>
  statusResponses?: Array<unknown | Promise<unknown>>
  settingsPatch?: unknown | Error
  results?: Array<Record<string, unknown>>
}

async function mountKnowledgeView(options: MountKnowledgeViewOptions = {}) {
  const status = options.rawStatus ?? statusPayload(options.status)
  const results = options.results || [searchResult()]
  const statusResponses = options.statusResponses?.slice()

  rpcMock.waitForConnection.mockResolvedValue(undefined)
  rpcMock.call.mockImplementation(async (method: string) => {
    if (method === 'knowledge.status') {
      if (statusResponses?.length) return statusResponses.shift()
      return options.statusResponse || status
    }
    if (method === 'knowledge.questions') return { questions: [] }
    if (method === 'tools.catalog') return { tools: [{ name: 'knowledge_search' }] }
    if (method === 'knowledge.search') return { results }
    if (method === 'knowledge.settings.patch') {
      if (options.settingsPatch instanceof Error) throw options.settingsPatch
      return options.settingsPatch ?? status
    }
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

function byTestId<T extends HTMLElement>(el: HTMLElement, testId: string): T {
  const element = el.querySelector<T>(`[data-testid="${testId}"]`)
  if (!element) throw new Error(`${testId} not found`)
  return element
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  element.value = value
  element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
}

function rpcCall(method: string): unknown[] | undefined {
  return rpcMock.call.mock.calls.find((call) => call[0] === method)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolver) => {
    resolve = resolver
  })
  return { promise, resolve }
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
  it('renders LEGACY default-search results without an active retrieval profile', async () => {
    const { el } = await mountKnowledgeView({
      rawStatus: {
        connectionState: 'LEGACY',
        capabilitiesStale: false,
        capabilitiesVersion: null,
        capabilitiesFetchedAt: 1_720_000_000_000,
        rootDir: '/mnt/data/datasets',
        documentsIndexed: 3,
        chunksIndexed: 12,
        filesIndexed: 3,
        pipeline: 'legacy pipeline',
        indexProfiles: ['sqlite_fts5_default'],
        defaultRetrievalProfile: null,
      },
      results: [searchResult({ retrievalProfile: undefined })],
    })

    const query = el.querySelector<HTMLTextAreaElement>('.rag-searchbar__query')
    if (!query) throw new Error('search query input not found')
    setInputValue(query, 'What changed in revenue?')
    await flushUi()

    const form = el.querySelector<HTMLFormElement>('form.rag-searchbar')
    if (!form) throw new Error('search form not found')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushUi()

    expect(rpcCall('knowledge.search')?.[1]).toEqual({
      query: 'What changed in revenue?',
      topK: 8,
      collectionId: 'datasets',
    })
    expect(el.textContent).toContain('Annual filing')
    expect(el.textContent).toContain('service default')
  })

  it('locks DEGRADED retrieval controls to service-default search payloads', async () => {
    const { el } = await mountKnowledgeView({
      status: {
        connectionState: 'DEGRADED',
        capabilitiesStale: true,
        defaultFallbackReason: 'capability_refresh_failed',
      },
    })

    const retrievalControl = el.querySelector<HTMLSelectElement>('.rag-source-panel select.control-input')
    expect(retrievalControl === null || retrievalControl.disabled).toBe(true)

    const query = el.querySelector<HTMLTextAreaElement>('.rag-searchbar__query')
    if (!query) throw new Error('search query input not found')
    setInputValue(query, 'Use the service default')
    await flushUi()

    const form = el.querySelector<HTMLFormElement>('form.rag-searchbar')
    if (!form) throw new Error('search form not found')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushUi()

    expect(rpcCall('knowledge.search')?.[1]).toEqual({
      query: 'Use the service default',
      topK: 8,
      collectionId: 'datasets',
    })
  })

  it('keeps both retrieval selectors empty while the initial status is pending', async () => {
    const pendingStatus = deferred<Record<string, unknown>>()
    const { el } = await mountKnowledgeView({ statusResponse: pendingStatus.promise })

    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    expect(defaultSelect.value).toBe('')
    expect(querySelect.value).toBe('')
    expect(defaultSelect.textContent).not.toContain('SQLite FTS5')
    expect(querySelect.textContent).not.toContain('SQLite FTS5')
    expect(defaultSelect.disabled).toBe(true)
    expect(querySelect.disabled).toBe(true)

    pendingStatus.resolve(statusPayload())
    await flushUi()
  })

  it('renders independent READY settings with stable semantic hooks', async () => {
    const { el } = await mountKnowledgeView()
    const testIds = [
      'knowledge-connection-state',
      'knowledge-default-profile',
      'knowledge-effective-profile',
      'knowledge-fallback-warning',
      'knowledge-save-default',
      'knowledge-query-profile',
      'knowledge-query-input',
      'knowledge-search',
    ]
    for (const testId of testIds) {
      expect(el.querySelector(`[data-testid="${testId}"]`)).not.toBeNull()
    }

    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    expect(defaultSelect.value).toBe('hybrid_rrf_bge_m3_fts5')
    expect(querySelect.value).toBe('')
    expect(Array.from(defaultSelect.options).map((option) => ({
      value: option.value,
      disabled: option.disabled,
    }))).toEqual([
      { value: 'sqlite_fts5_default', disabled: false },
      { value: 'hybrid_rrf_bge_m3_fts5', disabled: false },
      { value: 'vector_bge_m3_1024', disabled: true },
    ])
    expect(Array.from(querySelect.options).map((option) => option.value)).toEqual([
      '',
      'sqlite_fts5_default',
      'hybrid_rrf_bge_m3_fts5',
    ])
    expect(byTestId(el, 'knowledge-connection-state').textContent).toContain('READY')
    expect(byTestId(el, 'knowledge-effective-profile').textContent).toContain('Hybrid RRF')
    expect(byTestId(el, 'knowledge-fallback-warning').hidden).toBe(true)
    expect(el.textContent).toContain('0123456789abcdef')
    expect(el.querySelector('.rag-source-panel select')).toBeNull()
  })

  it('accepts READY runtime wire profiles with nullable lexical metadata', async () => {
    const runtimeProfiles = SERVICE_PROFILES.map((profile) => (
      profile.id === 'sqlite_fts5_default'
        ? { ...profile, model: null, dimensions: null }
        : profile
    ))
    const { el } = await mountKnowledgeView({
      status: {
        configuredDefaultRetrievalProfile: 'sqlite_fts5_default',
        effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
        retrievalProfiles: runtimeProfiles,
      },
    })

    expect(byTestId(el, 'knowledge-connection-state').textContent).toContain('READY')
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    expect(defaultSelect.disabled).toBe(false)
    expect(defaultSelect.value).toBe('sqlite_fts5_default')
    expect(Array.from(querySelect.options).map((option) => option.value)).toContain(
      'sqlite_fts5_default',
    )

    setInputValue(
      byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input'),
      'Search with the runtime default',
    )
    await flushUi()
    byTestId<HTMLButtonElement>(el, 'knowledge-search').click()
    await flushUi()

    expect(rpcCall('knowledge.search')?.[1]).toEqual({
      query: 'Search with the runtime default',
      topK: 8,
      collectionId: 'datasets',
    })
  })

  it('omits retrieval metadata from service-default search payloads', async () => {
    const { el } = await mountKnowledgeView({ results: [searchResult({ retrievalProfile: null })] })
    const query = byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input')
    setInputValue(query, 'What changed in revenue?')
    await flushUi()

    byTestId<HTMLButtonElement>(el, 'knowledge-search').click()
    await flushUi()

    expect(rpcCall('knowledge.search')?.[1]).toEqual({
      query: 'What changed in revenue?',
      topK: 8,
      collectionId: 'datasets',
    })
    expect(el.textContent).toContain('fusion 0.023')
  })

  it('sends only an explicit query override and renders scores using its kind', async () => {
    const { el } = await mountKnowledgeView({ results: [searchResult({ retrievalProfile: null })] })
    setInputValue(byTestId<HTMLSelectElement>(el, 'knowledge-query-profile'), 'hybrid_rrf_bge_m3_fts5')
    await flushUi()

    const query = byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input')
    setInputValue(query, 'What changed in revenue?')
    await flushUi()

    byTestId<HTMLButtonElement>(el, 'knowledge-search').click()
    await flushUi()

    expect(rpcCall('knowledge.search')?.[1]).toEqual({
      query: 'What changed in revenue?',
      topK: 8,
      collectionId: 'datasets',
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
    })
    expect(el.textContent).toContain('fusion 0.023')
    expect(el.textContent).toContain('Vector #2')
    expect(el.textContent).not.toContain('Vector#2')
  })

  it('keeps collection ingest free of retrieval selectors and uses only index profiles', async () => {
    const { el } = await mountKnowledgeView()
    expect(el.querySelector('.rag-source-panel select')).toBeNull()

    const buildButton = Array.from(el.querySelectorAll<HTMLButtonElement>('.rag-source-panel button.btn--primary'))
      .find((button) => button.textContent?.includes('Build collection'))
    if (!buildButton) throw new Error('build collection button not found')
    buildButton.click()
    await flushUi()

    expect(rpcCall('knowledge.ingest')?.[1]).toMatchObject({
      indexProfiles: ['sqlite_fts5_default'],
    })
  })

  it('keeps DEGRADED and LEGACY controls read-only while allowing default search', async () => {
    for (const connectionState of ['DEGRADED', 'LEGACY']) {
      const { el } = await mountKnowledgeView({
        status: {
          connectionState,
          capabilitiesStale: connectionState === 'DEGRADED',
        },
      })
      const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
      const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
      const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
      const queryInput = byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input')
      const searchButton = byTestId<HTMLButtonElement>(el, 'knowledge-search')

      expect(defaultSelect.disabled).toBe(true)
      expect(querySelect.disabled).toBe(true)
      expect(Array.from(querySelect.options).map((option) => option.value)).toEqual([''])
      expect(saveButton.disabled).toBe(true)
      setInputValue(queryInput, `Search while ${connectionState}`)
      await flushUi()
      expect(searchButton.disabled).toBe(false)
      expect(el.textContent).toContain(
        connectionState === 'DEGRADED'
          ? 'Searches use the service default while capabilities are degraded.'
          : 'Legacy Knowledge service: default search only.',
      )
    }
  })

  it('disables search with explicit messages for transitional and unavailable states', async () => {
    for (const [connectionState, message] of [
      ['DISCOVERING', 'Discovering retrieval capabilities.'],
      ['UNAVAILABLE', 'Knowledge retrieval is unavailable.'],
    ] as const) {
      const { el } = await mountKnowledgeView({ status: { connectionState } })
      setInputValue(byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input'), 'Can I search?')
      await flushUi()

      expect(byTestId<HTMLButtonElement>(el, 'knowledge-search').disabled).toBe(true)
      expect(byTestId(el, 'knowledge-connection-state').textContent).toContain(connectionState)
      expect(el.textContent).toContain(message)
    }
  })

  it('disables stale READY saves even when the default draft changes', async () => {
    const { el } = await mountKnowledgeView({ status: { capabilitiesStale: true } })
    setInputValue(
      byTestId<HTMLSelectElement>(el, 'knowledge-default-profile'),
      'sqlite_fts5_default',
    )
    await flushUi()

    expect(byTestId<HTMLButtonElement>(el, 'knowledge-save-default').disabled).toBe(true)
    expect(el.textContent).toContain('Capability snapshot is stale. Refresh before saving.')
  })

  it('shows configured and effective profiles when the service default falls back', async () => {
    const { el } = await mountKnowledgeView({
      status: {
        configuredDefaultRetrievalProfile: 'vector_bge_m3_1024',
        effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
        defaultFallbackReason: 'vector_index_empty',
      },
    })

    expect(byTestId<HTMLSelectElement>(el, 'knowledge-default-profile').value).toBe('vector_bge_m3_1024')
    expect(byTestId(el, 'knowledge-effective-profile').textContent).toContain('SQLite FTS5')
    const warning = byTestId(el, 'knowledge-fallback-warning')
    expect(warning.hidden).toBe(false)
    expect(warning.textContent).toContain('Vector bge-m3')
    expect(warning.textContent).toContain('SQLite FTS5')
  })

  it('disables search and avoids RPC when READY has no available service profile', async () => {
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
        configuredDefaultRetrievalProfile: 'vector_bge_m3_1024',
        effectiveDefaultRetrievalProfile: null,
      },
    })

    const query = byTestId<HTMLTextAreaElement>(el, 'knowledge-query-input')
    setInputValue(query, 'Can I search?')
    await flushUi()

    const button = byTestId<HTMLButtonElement>(el, 'knowledge-search')
    expect(button.disabled).toBe(true)

    button.click()
    await flushUi()

    expect(rpcMock.call.mock.calls.filter((call) => call[0] === 'knowledge.search')).toHaveLength(0)
    expect(el.textContent).toContain('No retrieval profile available')
  })

  it('saves an available default and adopts only the confirmed service status', async () => {
    const confirmedStatus = statusPayload({
      configuredDefaultRetrievalProfile: 'sqlite_fts5_default',
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
      capabilitiesVersion: 'fedcba9876543210',
      capabilitiesFetchedAt: 1_720_000_100_000,
    })
    const { el } = await mountKnowledgeView({ settingsPatch: confirmedStatus })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(querySelect, 'hybrid_rrf_bge_m3_fts5')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    expect(saveButton.disabled).toBe(false)
    saveButton.click()
    await flushUi()

    expect(rpcCall('knowledge.settings.patch')?.[1]).toEqual({
      defaultRetrievalProfile: 'sqlite_fts5_default',
    })
    expect(defaultSelect.value).toBe('sqlite_fts5_default')
    expect(querySelect.value).toBe('hybrid_rrf_bge_m3_fts5')
    expect(byTestId(el, 'knowledge-effective-profile').textContent).toContain('SQLite FTS5')
    expect(el.textContent).toContain('fedcba9876543210')
    expect(saveButton.disabled).toBe(true)
  })

  it('preserves the dirty draft and shows the error when saving fails', async () => {
    const { el } = await mountKnowledgeView({ settingsPatch: new Error('Save denied') })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    saveButton.click()
    await flushUi()

    expect(rpcCall('knowledge.settings.patch')?.[1]).toEqual({
      defaultRetrievalProfile: 'sqlite_fts5_default',
    })
    expect(defaultSelect.value).toBe('sqlite_fts5_default')
    expect(el.textContent).toContain('Save denied')
    expect(saveButton.disabled).toBe(false)
  })

  it('does not save a draft that is not an available query override', async () => {
    const { el } = await mountKnowledgeView()
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(defaultSelect, 'vector_bge_m3_1024')
    await flushUi()

    expect(defaultSelect.value).toBe('vector_bge_m3_1024')
    expect(saveButton.disabled).toBe(true)
    saveButton.click()
    await flushUi()
    expect(rpcCall('knowledge.settings.patch')).toBeUndefined()
  })

  it('fails closed when settings.patch returns a malformed status', async () => {
    const { el } = await mountKnowledgeView({ settingsPatch: {} })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    saveButton.click()
    await flushUi()

    expect(defaultSelect.value).toBe('sqlite_fts5_default')
    expect(el.textContent).toContain('Invalid Knowledge settings response')
    expect(saveButton.disabled).toBe(false)
  })

  it('preserves the dirty draft when confirmed READY relationships are invalid', async () => {
    const malformedConfirmed = statusPayload({
      configuredDefaultRetrievalProfile: 'missing_profile',
    })
    const { el } = await mountKnowledgeView({ settingsPatch: malformedConfirmed })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    saveButton.click()
    await flushUi()

    expect(defaultSelect.value).toBe('sqlite_fts5_default')
    expect(el.textContent).toContain('Invalid Knowledge settings response')
    expect(saveButton.disabled).toBe(false)
  })

  it('fails closed when confirmed settings change the connection state', async () => {
    const confirmedStatus = statusPayload({
      connectionState: 'DEGRADED',
      capabilitiesStale: true,
      configuredDefaultRetrievalProfile: 'sqlite_fts5_default',
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
    })
    const { el } = await mountKnowledgeView({ settingsPatch: confirmedStatus })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    setInputValue(querySelect, 'hybrid_rrf_bge_m3_fts5')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    saveButton.click()
    await flushUi()

    expect(byTestId(el, 'knowledge-connection-state').textContent).toContain('DEGRADED')
    expect(defaultSelect.disabled).toBe(true)
    expect(querySelect.disabled).toBe(true)
    expect(querySelect.value).toBe('')
    expect(saveButton.disabled).toBe(true)
  })

  it('fails closed when knowledge.status returns a malformed payload', async () => {
    const { el } = await mountKnowledgeView({ rawStatus: {} })

    expect(byTestId<HTMLSelectElement>(el, 'knowledge-default-profile').disabled).toBe(true)
    expect(byTestId<HTMLSelectElement>(el, 'knowledge-query-profile').disabled).toBe(true)
    expect(byTestId<HTMLButtonElement>(el, 'knowledge-search').disabled).toBe(true)
    expect(el.textContent).toContain('Invalid Knowledge status response')
  })

  it('rejects semantically invalid READY capability snapshots', async () => {
    for (const rawStatus of [
      statusPayload({ configuredDefaultRetrievalProfile: 'missing_profile' }),
      statusPayload({ effectiveDefaultRetrievalProfile: 'missing_profile' }),
      statusPayload({ capabilitiesVersion: 'not-a-version' }),
      statusPayload({ capabilitiesFetchedAt: 'not-a-timestamp' }),
    ]) {
      const { el } = await mountKnowledgeView({ rawStatus })
      expect(byTestId<HTMLButtonElement>(el, 'knowledge-search').disabled).toBe(true)
      expect(el.textContent).toContain('Invalid Knowledge status response')
    }
  })

  it('blocks refresh while a default save is pending', async () => {
    const pendingPatch = deferred<Record<string, unknown>>()
    const { el } = await mountKnowledgeView({ settingsPatch: pendingPatch.promise })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    const refreshButton = el.querySelector<HTMLButtonElement>('.rag-stage__header button.btn--ghost')
    if (!refreshButton) throw new Error('header refresh button not found')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    saveButton.click()
    await flushUi()

    expect(refreshButton.disabled).toBe(true)
    refreshButton.click()
    await flushUi()
    expect(rpcMock.call.mock.calls.filter((call) => call[0] === 'knowledge.status')).toHaveLength(1)

    pendingPatch.resolve(statusPayload({
      configuredDefaultRetrievalProfile: 'sqlite_fts5_default',
      effectiveDefaultRetrievalProfile: 'sqlite_fts5_default',
    }))
    await flushUi()
  })

  it('blocks default saves while a status refresh is pending', async () => {
    const pendingRefresh = deferred<Record<string, unknown>>()
    const { el } = await mountKnowledgeView({
      statusResponses: [statusPayload(), pendingRefresh.promise],
    })
    const defaultSelect = byTestId<HTMLSelectElement>(el, 'knowledge-default-profile')
    const querySelect = byTestId<HTMLSelectElement>(el, 'knowledge-query-profile')
    const saveButton = byTestId<HTMLButtonElement>(el, 'knowledge-save-default')
    const refreshButton = el.querySelector<HTMLButtonElement>('.rag-stage__header button.btn--ghost')
    if (!refreshButton) throw new Error('header refresh button not found')
    setInputValue(querySelect, 'hybrid_rrf_bge_m3_fts5')
    setInputValue(defaultSelect, 'sqlite_fts5_default')
    await flushUi()

    refreshButton.click()
    await flushUi()

    expect(saveButton.disabled).toBe(true)
    saveButton.click()
    await flushUi()
    expect(rpcCall('knowledge.settings.patch')).toBeUndefined()

    pendingRefresh.resolve(statusPayload())
    await flushUi()
    expect(querySelect.value).toBe('hybrid_rrf_bge_m3_fts5')
  })

  it('renders an invalid finite capability timestamp as not reported', async () => {
    const { el } = await mountKnowledgeView({
      status: { capabilitiesFetchedAt: 1e300 },
    })

    expect(el.textContent).toContain('FetchedNot reported')
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
        connectionState: 'LEGACY',
        capabilitiesStale: false,
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
