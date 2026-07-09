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
        defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
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
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
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

  it('builds search payload with selected embedding metadata', () => {
    expect(
      buildSearchProfilePayload(
        {
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

  it('uses service default metadata when selected profile is disabled', () => {
    expect(
      buildSearchProfilePayload(
        {
          defaultRetrievalProfile: 'hybrid_rrf_bge_m3_fts5',
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
      defaultRetrievalProfile: 'vector_bge_m3_1024',
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

  it('sends selected retrieval metadata and renders scores using the active profile fallback', async () => {
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

    expect(rpcCall('knowledge.search')?.[1]).toMatchObject({
      retrievalProfile: 'hybrid_rrf_bge_m3_fts5',
      embeddingModel: 'baai/bge-m3',
      embeddingDimensions: 1024,
    })
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
